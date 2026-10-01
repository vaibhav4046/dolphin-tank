package main

import (
	"errors"
	"fmt"
	"math"
	"sync"
	"time"
)

// Store owns the state. ponytail: ONE global mutex serialises every read and write, which is what
// makes the balance-sum, no-negative-balance and pay-once invariants hold; shard locks only if
// throughput ever demands it. Trace swaps s.st under s.mu in Reset/Import.
type Store struct {
	mu sync.Mutex
	st *State
}

func NewStore() *Store {
	st := &State{Currency: "EUR", MinorUnits: 2}
	if err := st.Reindex(); err != nil {
		panic(err) // an empty EUR state is always valid
	}
	return &Store{st: st}
}

// Exec runs fn and marshals its result while holding the lock; an error yields nil bytes.
func (s *Store) Exec(fn func(st *State) (any, *AppError)) ([]byte, *AppError) {
	s.mu.Lock()
	defer s.mu.Unlock()
	v, e := fn(s.st)
	if e != nil {
		return nil, e
	}
	return marshalBody(v)
}

func marshalBody(v any) ([]byte, *AppError) {
	b, err := MarshalJSON(v)
	if err != nil {
		return nil, NewErr(500, "internal_error", "response encoding failed")
	}
	return b, nil
}

func (s *Store) Authenticate(token string) (string, *AppError) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if uid, ok := s.st.Tokens[token]; ok {
		return uid, nil
	}
	return "", errUnauthenticated()
}

func validHandle(h string) bool {
	if len(h) < 1 || len(h) > 20 {
		return false
	}
	for i := 0; i < len(h); i++ {
		c := h[i]
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_') {
			return false
		}
	}
	return true
}

func validStatus(s string) bool {
	return s == statusPending || s == statusPaid || s == statusDeclined || s == statusCancelled
}

func validVisibility(v string) bool { return v == visPublic || v == visPrivate }

// Reindex rebuilds every lookup index from the persisted slices and verifies the state.
// It also derives denormalised fields (handles, currency) and applies fixture defaults
// (payment visibility public, request status pending, missing created_at = now).
// On error the State must be discarded.
func (st *State) Reindex() error { return st.ReindexAt(time.Now()) }

// ReindexAt is Reindex with an explicit clock: which authorizations still hold funds depends on now.
func (st *State) ReindexAt(now time.Time) error {
	if st.Currency == "" {
		return errors.New("currency is required")
	}
	if st.MinorUnits != 0 && st.MinorUnits != 2 && st.MinorUnits != 3 {
		return fmt.Errorf("minor_units must be 0, 2 or 3, got %d", st.MinorUnits)
	}
	if st.Users == nil {
		st.Users = []*User{}
	}
	if st.Payments == nil {
		st.Payments = []*Payment{}
	}
	if st.Requests == nil {
		st.Requests = []*Request{}
	}
	if st.Splits == nil {
		st.Splits = []*Split{}
	}
	if st.Authorizations == nil {
		st.Authorizations = []*Authorization{}
	}
	if st.AuthTTLSeconds < 0 || st.AuthTTLSeconds > maxAuthTTLSeconds {
		return fmt.Errorf("authorization_ttl_seconds must be 0 (unset) or 1 to %d, got %d", maxAuthTTLSeconds, st.AuthTTLSeconds)
	}
	if st.Tokens == nil {
		st.Tokens = map[string]string{}
	}
	if st.Seq == nil {
		st.Seq = map[string]int64{}
	}
	nowStr := FormatTime(now)
	ids := map[string]struct{}{}
	byID := map[string]*User{}
	byHandle := map[string]*User{}
	byEmail := map[string]*User{}
	for _, u := range st.Users {
		if u == nil || u.ID == "" {
			return errors.New("user without id")
		}
		if byID[u.ID] != nil {
			return fmt.Errorf("duplicate user id %q", u.ID)
		}
		if !validHandle(u.Handle) {
			return fmt.Errorf("user %q: invalid handle %q", u.ID, u.Handle)
		}
		if byHandle[u.Handle] != nil {
			return fmt.Errorf("duplicate handle %q", u.Handle)
		}
		if u.Balance < 0 {
			return fmt.Errorf("user %q: negative balance", u.ID)
		}
		if u.Email != "" {
			k := lowerEmail(u.Email)
			if byEmail[k] != nil {
				return fmt.Errorf("duplicate email %q", u.Email)
			}
			byEmail[k] = u
		}
		byID[u.ID], byHandle[u.Handle] = u, u
		ids[u.ID] = struct{}{}
	}
	payByID := map[string]*Payment{}
	for _, p := range st.Payments {
		if p == nil || p.PaymentID == "" {
			return errors.New("payment without id")
		}
		if payByID[p.PaymentID] != nil {
			return fmt.Errorf("duplicate payment id %q", p.PaymentID)
		}
		from, to := byID[p.FromUserID], byID[p.ToUserID]
		if from == nil || to == nil {
			return fmt.Errorf("payment %q references an unknown user", p.PaymentID)
		}
		if p.Visibility == "" {
			p.Visibility = visPublic
		}
		if !validVisibility(p.Visibility) {
			return fmt.Errorf("payment %q: invalid visibility %q", p.PaymentID, p.Visibility)
		}
		if p.Amount < 0 {
			return fmt.Errorf("payment %q: negative amount", p.PaymentID)
		}
		p.FromHandle, p.ToHandle, p.Currency = from.Handle, to.Handle, st.Currency
		if p.CreatedAt == "" {
			p.CreatedAt = nowStr
		}
		payByID[p.PaymentID] = p
		ids[p.PaymentID] = struct{}{}
	}
	reqByID := map[string]*Request{}
	for _, r := range st.Requests {
		if r == nil || r.RequestID == "" {
			return errors.New("request without id")
		}
		if reqByID[r.RequestID] != nil {
			return fmt.Errorf("duplicate request id %q", r.RequestID)
		}
		requester, payer := byID[r.RequesterID], byID[r.PayerID]
		if requester == nil || payer == nil {
			return fmt.Errorf("request %q references an unknown user", r.RequestID)
		}
		if r.Status == "" {
			r.Status = statusPending
		}
		if !validStatus(r.Status) {
			return fmt.Errorf("request %q: invalid status %q", r.RequestID, r.Status)
		}
		if r.Amount < 0 {
			return fmt.Errorf("request %q: negative amount", r.RequestID)
		}
		if r.PaymentID != nil && payByID[*r.PaymentID] == nil {
			return fmt.Errorf("request %q references unknown payment %q", r.RequestID, *r.PaymentID)
		}
		r.RequesterHandle, r.PayerHandle, r.Currency = requester.Handle, payer.Handle, st.Currency
		if r.CreatedAt == "" {
			r.CreatedAt = nowStr
		}
		reqByID[r.RequestID] = r
		ids[r.RequestID] = struct{}{}
	}
	splitSeen := map[string]bool{}
	for _, sp := range st.Splits {
		if sp == nil || sp.SplitID == "" {
			return errors.New("split without id")
		}
		if splitSeen[sp.SplitID] {
			return fmt.Errorf("duplicate split id %q", sp.SplitID)
		}
		splitSeen[sp.SplitID] = true
		if byID[sp.CreatorID] == nil {
			return fmt.Errorf("split %q references an unknown user", sp.SplitID)
		}
		for _, rid := range sp.RequestIDs {
			if reqByID[rid] == nil {
				return fmt.Errorf("split %q references unknown request %q", sp.SplitID, rid)
			}
		}
		if sp.Shares == nil {
			sp.Shares = []Share{}
		}
		if sp.RequestIDs == nil {
			sp.RequestIDs = []string{}
		}
		ids[sp.SplitID] = struct{}{}
	}
	authByID, err := indexAuthorizations(st.Authorizations, byID, payByID, ids, nowStr)
	if err != nil {
		return err
	}
	if err := checkHolds(st.Authorizations, byID, now); err != nil {
		return err
	}
	for tok, uid := range st.Tokens {
		if tok == "" || byID[uid] == nil {
			return errors.New("token references an unknown user")
		}
	}
	st.usersByID, st.usersByHandle, st.usersByEmail = byID, byHandle, byEmail
	st.reqByID, st.authByID, st.ids = reqByID, authByID, ids
	return nil
}

// indexAuthorizations validates each authorization's own fields and references, applies
// defaults (visibility public, status open, empty payment_ids, missing created_at = now)
// and returns the id index.
func indexAuthorizations(auths []*Authorization, users map[string]*User, pays map[string]*Payment,
	ids map[string]struct{}, nowStr string) (map[string]*Authorization, error) {
	byID := make(map[string]*Authorization, len(auths))
	for _, a := range auths {
		if a == nil || a.AuthorizationID == "" {
			return nil, errors.New("authorization without id")
		}
		if byID[a.AuthorizationID] != nil {
			return nil, fmt.Errorf("duplicate authorization id %q", a.AuthorizationID)
		}
		if users[a.FromUserID] == nil || users[a.ToUserID] == nil {
			return nil, fmt.Errorf("authorization %q references an unknown user", a.AuthorizationID)
		}
		if a.Amount < 1 {
			return nil, fmt.Errorf("authorization %q: amount must be at least 1", a.AuthorizationID)
		}
		if a.CapturedAmount < 0 || a.CapturedAmount > a.Amount {
			return nil, fmt.Errorf("authorization %q: captured_amount must be between 0 and amount", a.AuthorizationID)
		}
		if a.Status == "" {
			a.Status = authOpen
		}
		if !validAuthStatus(a.Status) {
			return nil, fmt.Errorf("authorization %q: invalid status %q", a.AuthorizationID, a.Status)
		}
		if a.Visibility == "" {
			a.Visibility = visPublic
		}
		if !validVisibility(a.Visibility) {
			return nil, fmt.Errorf("authorization %q: invalid visibility %q", a.AuthorizationID, a.Visibility)
		}
		exp, err := time.Parse(time.RFC3339, a.ExpiresAt)
		if err != nil {
			return nil, fmt.Errorf("authorization %q: expires_at must be RFC 3339", a.AuthorizationID)
		}
		a.expiry = exp
		if a.PaymentIDs == nil {
			a.PaymentIDs = []string{}
		}
		for _, pid := range a.PaymentIDs {
			if pays[pid] == nil {
				return nil, fmt.Errorf("authorization %q references unknown payment %q", a.AuthorizationID, pid)
			}
		}
		if a.CreatedAt == "" {
			a.CreatedAt = nowStr
		}
		byID[a.AuthorizationID] = a
		ids[a.AuthorizationID] = struct{}{}
	}
	return byID, nil
}

// checkHolds enforces Held <= Balance per user at now. Expired and closed authorizations hold nothing.
func checkHolds(auths []*Authorization, users map[string]*User, now time.Time) error {
	held := map[string]int64{}
	for _, a := range auths {
		rem := a.RemainingAt(now)
		if rem > math.MaxInt64-held[a.FromUserID] {
			return fmt.Errorf("user %q: holds overflow", a.FromUserID)
		}
		held[a.FromUserID] += rem
	}
	for uid, h := range held {
		if h > users[uid].Balance {
			return fmt.Errorf("user %q: open holds exceed balance", uid)
		}
	}
	return nil
}
