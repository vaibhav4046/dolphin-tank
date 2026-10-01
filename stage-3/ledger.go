package main

import "time"

type PaymentIn struct {
	ToHandle   string
	Amount     int64
	Note       string
	Visibility string
}

type RequestIn struct {
	PayerHandle string
	Amount      int64
	Note        string
}

type PayIn struct{ Visibility string }

type meBody struct {
	UserID      string `json:"user_id"`
	DisplayName string `json:"display_name"`
	Handle      string `json:"handle"`
	Balance     int64  `json:"balance"` // always equal to Total
	Total       int64  `json:"total"`
	Available   int64  `json:"available"`
	Held        int64  `json:"held"`
	Currency    string `json:"currency"`
	MinorUnits  int    `json:"minor_units"`
}

type requestPage struct {
	Requests []*Request `json:"requests"`
	HasMore  bool       `json:"has_more"`
}

type paymentPage struct {
	Payments []*Payment `json:"payments"`
	HasMore  bool       `json:"has_more"`
}

// Transfer is the ONLY place balances move. It does not check funds: callers verify affordability
// first (a settlement applies its transfers in order and checks the net result up front).
func (st *State) Transfer(from, to *User, amount int64, note, visibility string, requestID, settlementID *string, now time.Time) *Payment {
	return st.TransferFor(from, to, amount, note, visibility, requestID, settlementID, nil, now)
}

// TransferFor is Transfer plus the authorization a capture belongs to (nil otherwise).
func (st *State) TransferFor(from, to *User, amount int64, note, visibility string, requestID, settlementID, authorizationID *string, now time.Time) *Payment {
	from.Balance -= amount
	to.Balance += amount
	p := &Payment{
		PaymentID:       st.NewID("p"),
		FromUserID:      from.ID,
		FromHandle:      from.Handle,
		ToUserID:        to.ID,
		ToHandle:        to.Handle,
		Amount:          amount,
		Currency:        st.Currency,
		Note:            note,
		Visibility:      visibility,
		RequestID:       requestID,
		SettlementID:    settlementID,
		AuthorizationID: authorizationID,
		CreatedAt:       FormatTime(now),
	}
	st.Payments = append(st.Payments, p)
	return p
}

func (st *State) Pay(caller string, in PaymentIn, now time.Time) (*Payment, *AppError) {
	from, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	to := st.UserByHandle(in.ToHandle)
	if to == nil {
		return nil, errNotFound("no user has that handle")
	}
	if to.ID == from.ID {
		return nil, NewErr(422, "self_payment", "cannot pay yourself")
	}
	if st.Available(from, now) < in.Amount {
		return nil, NewErr(409, "insufficient_funds", "available funds are below the amount")
	}
	return st.Transfer(from, to, in.Amount, in.Note, in.Visibility, nil, nil, now), nil
}

func (st *State) CreateRequest(caller string, in RequestIn, now time.Time) (*Request, *AppError) {
	requester, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	payer := st.UserByHandle(in.PayerHandle)
	if payer == nil {
		return nil, errNotFound("no user has that handle")
	}
	if payer.ID == requester.ID {
		return nil, NewErr(422, "self_request", "cannot request money from yourself")
	}
	return st.newRequest(requester, payer, in.Amount, in.Note, now), nil
}

// newRequest never checks the payer's balance: a request may exceed it.
func (st *State) newRequest(requester, payer *User, amount int64, note string, now time.Time) *Request {
	r := &Request{
		RequestID:       st.NewID("rq"),
		RequesterID:     requester.ID,
		RequesterHandle: requester.Handle,
		PayerID:         payer.ID,
		PayerHandle:     payer.Handle,
		Amount:          amount,
		Currency:        st.Currency,
		Note:            note,
		Status:          statusPending,
		CreatedAt:       FormatTime(now),
	}
	st.addRequest(r)
	return r
}

func (st *State) PayRequest(caller, requestID string, in PayIn, now time.Time) (*Payment, *AppError) {
	payer, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	r := st.reqByID[requestID]
	if r == nil {
		return nil, errNotFound("no such request")
	}
	if r.PayerID != payer.ID {
		return nil, errForbidden("only the payer may pay this request")
	}
	if r.Status != statusPending {
		return nil, NewErr(409, "request_not_pending", "request is not pending")
	}
	if st.Available(payer, now) < r.Amount {
		return nil, NewErr(409, "insufficient_funds", "available funds are below the amount")
	}
	requester := st.userByID(r.RequesterID)
	rid := r.RequestID
	p := st.Transfer(payer, requester, r.Amount, r.Note, in.Visibility, &rid, nil, now)
	pid := p.PaymentID
	r.Status, r.PaymentID = statusPaid, &pid
	return p, nil
}

// Decline: payer only. A second decline is a 200 no-op; paid/cancelled is 409.
func (st *State) Decline(caller, requestID string) (*Request, *AppError) {
	return st.closeRequest(caller, requestID, statusDeclined)
}

// Cancel: requester only. A second cancel is a 200 no-op; paid/declined is 409.
func (st *State) Cancel(caller, requestID string) (*Request, *AppError) {
	return st.closeRequest(caller, requestID, statusCancelled)
}

func (st *State) closeRequest(caller, requestID, to string) (*Request, *AppError) {
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	r := st.reqByID[requestID]
	if r == nil {
		return nil, errNotFound("no such request")
	}
	if to == statusDeclined && r.PayerID != u.ID {
		return nil, errForbidden("only the payer may decline this request")
	}
	if to == statusCancelled && r.RequesterID != u.ID {
		return nil, errForbidden("only the requester may cancel this request")
	}
	if r.Status == to {
		return r, nil
	}
	if r.Status != statusPending {
		return nil, NewErr(409, "request_not_pending", "request is not pending")
	}
	r.Status = to
	return r, nil
}

// pageNewestFirst walks items newest first (reverse insertion order), keeps matches and returns
// the [offset, offset+limit) window plus has_more (a match exists beyond it). Never nil.
func pageNewestFirst[T any](items []T, keep func(T) bool, limit, offset int) ([]T, bool) {
	out := make([]T, 0, min(limit, 16))
	seen := 0
	for i := len(items) - 1; i >= 0; i-- {
		if !keep(items[i]) {
			continue
		}
		if seen >= offset {
			if len(out) == limit {
				return out, true
			}
			out = append(out, items[i])
		}
		seen++
	}
	return out, false
}

func (st *State) ListRequests(caller, direction, status string, limit, offset int) (any, *AppError) {
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	if direction != "" && direction != "incoming" && direction != "outgoing" {
		return nil, errValidation("direction must be incoming or outgoing")
	}
	if status != "" && !validStatus(status) {
		return nil, errValidation("status must be pending, paid, declined or cancelled")
	}
	keep := func(r *Request) bool {
		in, out := r.PayerID == u.ID, r.RequesterID == u.ID
		switch direction {
		case "incoming":
			out = false
		case "outgoing":
			in = false
		}
		return (in || out) && (status == "" || r.Status == status)
	}
	page, more := pageNewestFirst(st.Requests, keep, limit, offset)
	return requestPage{Requests: page, HasMore: more}, nil
}

// Activity is payments only: public ones, plus any the caller sent or received.
func (st *State) Activity(caller string, limit, offset int) any {
	keep := func(p *Payment) bool {
		return p.Visibility == visPublic || p.FromUserID == caller || p.ToUserID == caller
	}
	page, more := pageNewestFirst(st.Payments, keep, limit, offset)
	return paymentPage{Payments: page, HasMore: more}
}

func (st *State) Me(caller string, now time.Time) any {
	u := st.userByID(caller)
	if u == nil {
		return nil
	}
	held := st.Held(u.ID, now)
	return meBody{UserID: u.ID, DisplayName: u.DisplayName, Handle: u.Handle,
		Balance: u.Balance, Total: u.Balance, Available: u.Balance - held, Held: held,
		Currency: st.Currency, MinorUnits: st.MinorUnits}
}
