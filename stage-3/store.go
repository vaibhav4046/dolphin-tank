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
	st := &State{Currency: "EUR", MinorUnits: 2, HistoryVersion: historyVersion}
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
// History is verified, never derived: whoever builds the state supplies each payment's revisions,
// every wallet's opening balance and every released hold's closed_at.
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
	if st.Revisions == nil {
		st.Revisions = []*Revision{}
	}
	if st.HistoryVersion != 0 && st.HistoryVersion != historyVersion {
		return fmt.Errorf("history_version must be %d, got %d", historyVersion, st.HistoryVersion)
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
		created, ok := ParseInstant(p.CreatedAt)
		if !ok {
			return fmt.Errorf("payment %q: created_at must be an RFC 3339 instant with an offset", p.PaymentID)
		}
		p.created = created
		payByID[p.PaymentID] = p
		ids[p.PaymentID] = struct{}{}
	}
	revByPay, err := indexRevisions(st.Revisions, payByID)
	if err != nil {
		return err
	}
	if err := checkOpenings(st.Users, st.Payments, revByPay); err != nil {
		return err
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
	st.payByID, st.revByPay = payByID, revByPay
	st.payOrdered = paymentsOrdered(st.Payments)
	st.lastStamp = newestInstant(st)
	st.HistoryVersion = historyVersion
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
		created, ok := ParseInstant(a.CreatedAt)
		if !ok {
			return nil, fmt.Errorf("authorization %q: created_at must be an RFC 3339 instant with an offset", a.AuthorizationID)
		}
		a.created = created
		if err := checkClosedAt(a); err != nil {
			return nil, err
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

// checkClosedAt: an authorization is released (closed_at set) exactly when its stored status is not open.
func checkClosedAt(a *Authorization) error {
	a.closed = time.Time{}
	if a.Status == authOpen {
		if a.ClosedAt != nil {
			return fmt.Errorf("authorization %q: closed_at must be null while open", a.AuthorizationID)
		}
		return nil
	}
	if a.ClosedAt == nil {
		return fmt.Errorf("authorization %q: closed_at is required once %s", a.AuthorizationID, a.Status)
	}
	closed, ok := ParseInstant(*a.ClosedAt)
	if !ok {
		return fmt.Errorf("authorization %q: closed_at must be an RFC 3339 instant with an offset", a.AuthorizationID)
	}
	a.closed = closed
	return nil
}

// indexRevisions verifies every payment's history and groups it: revisions are numbered 1..n in order,
// recorded strictly later each time, and revision 1 is the payment as paid.
func indexRevisions(revs []*Revision, pays map[string]*Payment) (map[string][]*Revision, error) {
	byPay := make(map[string][]*Revision, len(pays))
	for _, r := range revs {
		if r == nil {
			return nil, errors.New("state contains a null revision")
		}
		p := pays[r.PaymentID]
		if p == nil {
			return nil, fmt.Errorf("revision references unknown payment %q", r.PaymentID)
		}
		prev := byPay[r.PaymentID]
		if r.Revision != int64(len(prev))+1 {
			return nil, fmt.Errorf("payment %q: revisions must be numbered 1..n in order, got %d", r.PaymentID, r.Revision)
		}
		if r.Amount < 0 || (r.Revision > 1 && r.Amount > maxAmount) {
			return nil, fmt.Errorf("payment %q revision %d: amount out of range", r.PaymentID, r.Revision)
		}
		var ok1, ok2 bool
		r.eff, ok1 = ParseInstant(r.EffectiveAt)
		r.rec, ok2 = ParseInstant(r.RecordedAt)
		if !ok1 || !ok2 {
			return nil, fmt.Errorf("payment %q revision %d: effective_at and recorded_at must be RFC 3339 instants with an offset", r.PaymentID, r.Revision)
		}
		if len(prev) == 0 && r.Amount != p.Amount {
			return nil, fmt.Errorf("payment %q: revision 1 must carry the amount as paid", r.PaymentID)
		}
		if len(prev) > 0 && !r.rec.After(prev[len(prev)-1].rec) {
			return nil, fmt.Errorf("payment %q: recorded_at must strictly increase", r.PaymentID)
		}
		byPay[r.PaymentID] = append(prev, r)
	}
	for id := range pays {
		if len(byPay[id]) == 0 {
			return nil, fmt.Errorf("payment %q has no revision 1", id)
		}
	}
	return byPay, nil
}

// checkOpenings verifies Balance == OpeningBalance + net effect of each payment's latest revision.
func checkOpenings(users []*User, pays []*Payment, revs map[string][]*Revision) error {
	net := make(map[string]int64, len(users))
	for _, p := range pays {
		h := revs[p.PaymentID]
		amount := h[len(h)-1].Amount
		net[p.FromUserID] -= amount
		net[p.ToUserID] += amount
	}
	for _, u := range users {
		if u.Balance != u.OpeningBalance+net[u.ID] {
			return fmt.Errorf("user %q: balance %d is not the opening balance %d plus the payments' net %d",
				u.ID, u.Balance, u.OpeningBalance, net[u.ID])
		}
	}
	return nil
}

func paymentsOrdered(pays []*Payment) bool {
	for i := 1; i < len(pays); i++ {
		if pays[i].created.Before(pays[i-1].created) {
			return false
		}
	}
	return true
}

// newestInstant is the latest moment any write has used, so Stamp resumes strictly after it.
func newestInstant(st *State) time.Time {
	newest := st.lastStamp
	later := func(t time.Time) {
		if t = t.Truncate(time.Microsecond); t.After(newest) {
			newest = t
		}
	}
	for _, p := range st.Payments {
		later(p.created)
	}
	for _, r := range st.Revisions {
		later(r.rec)
	}
	for _, a := range st.Authorizations {
		later(a.created)
		later(a.closed)
	}
	return newest
}
