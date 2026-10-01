package main

import (
	"errors"
	"fmt"
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
func (st *State) Reindex() error {
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
	if st.Tokens == nil {
		st.Tokens = map[string]string{}
	}
	if st.Seq == nil {
		st.Seq = map[string]int64{}
	}
	now := FormatTime(time.Now())
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
			p.CreatedAt = now
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
			r.CreatedAt = now
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
	for tok, uid := range st.Tokens {
		if tok == "" || byID[uid] == nil {
			return errors.New("token references an unknown user")
		}
	}
	st.usersByID, st.usersByHandle, st.usersByEmail = byID, byHandle, byEmail
	st.reqByID, st.ids = reqByID, ids
	return nil
}
