package main

import "time"

const (
	authOpen     = "open"
	authCaptured = "captured"
	authVoided   = "voided"
	authExpired  = "expired"

	defaultAuthTTLSeconds = 600
	maxAuthTTLSeconds     = 1_000_000_000
)

// Authorization is a hold: it reserves money on the payer's wallet without moving it.
// Status is the stored status and is NEVER changed by the clock; use StatusAt for the effective one.
type Authorization struct {
	AuthorizationID string   `json:"authorization_id"`
	FromUserID      string   `json:"from_user_id"`
	ToUserID        string   `json:"to_user_id"`
	Amount          int64    `json:"amount"`
	CapturedAmount  int64    `json:"captured_amount"`
	Note            string   `json:"note"`
	Visibility      string   `json:"visibility"`
	Status          string   `json:"status"`
	ExpiresAt       string   `json:"expires_at"`
	PaymentIDs      []string `json:"payment_ids"`
	CreatedAt       string   `json:"created_at"`
	// ClosedAt is the instant the hold was released: null while the stored status is open.
	// Clock expiry never writes it (the stored status stays open); the body derives it.
	ClosedAt *string `json:"closed_at"`
	// CreatedExact is vestigial: an earlier build put a microsecond instant here beside a whole-second
	// created_at. created_at now carries the microsecond itself and is the only instant a hold is placed
	// at; this field is still written (equal to created_at). On import a different created_exact (an
	// export of that earlier build) replaces created_at; no view reads it.
	CreatedExact *string `json:"created_exact,omitempty"`

	expiry       time.Time // parsed ExpiresAt, set by ReindexAt; zero in hand-built values
	created      time.Time // parsed CreatedAt
	closed       time.Time // parsed ClosedAt
	createdExact time.Time // parsed CreatedExact; zero when absent
}

// AuthorizationBody is the API view of an Authorization at one instant.
type AuthorizationBody struct {
	AuthorizationID string   `json:"authorization_id"`
	FromUserID      string   `json:"from_user_id"`
	FromHandle      string   `json:"from_handle"`
	ToUserID        string   `json:"to_user_id"`
	ToHandle        string   `json:"to_handle"`
	Amount          int64    `json:"amount"`
	CapturedAmount  int64    `json:"captured_amount"`
	RemainingAmount int64    `json:"remaining_amount"`
	Currency        string   `json:"currency"`
	Note            string   `json:"note"`
	Visibility      string   `json:"visibility"`
	Status          string   `json:"status"`
	ExpiresAt       string   `json:"expires_at"`
	PaymentID       *string  `json:"payment_id"`
	PaymentIDs      []string `json:"payment_ids"`
	CreatedAt       string   `json:"created_at"`
	ClosedAt        *string  `json:"closed_at"`
}

type AuthorizeIn struct {
	ToHandle   string
	Amount     int64
	Note       string
	Visibility string
}

// CaptureIn: Amount nil = the whole remainder. Final is the OptFinal result (absent means true).
type CaptureIn struct {
	Amount *int64
	Final  bool
}

type authorizationPage struct {
	Authorizations []*AuthorizationBody `json:"authorizations"`
	HasMore        bool                 `json:"has_more"`
}

func validAuthStatus(s string) bool {
	return s == authOpen || s == authCaptured || s == authVoided || s == authExpired
}

func (a *Authorization) expiresTime() time.Time {
	if !a.expiry.IsZero() {
		return a.expiry
	}
	t, _ := time.Parse(time.RFC3339, a.ExpiresAt)
	return t
}

func (a *Authorization) createdTime() time.Time {
	if !a.created.IsZero() {
		return a.created
	}
	t, _ := time.Parse(time.RFC3339, a.CreatedAt)
	return t
}

// placedAt is the instant the hold was placed: created_at, the same instant every view uses.
func (a *Authorization) placedAt() time.Time { return a.createdTime() }

// closedTime is the parsed ClosedAt; ok is false while the hold has not been released by an event.
func (a *Authorization) closedTime() (t time.Time, ok bool) {
	if a.ClosedAt == nil {
		return time.Time{}, false
	}
	if !a.closed.IsZero() {
		return a.closed, true
	}
	t, _ = ParseInstant(*a.ClosedAt)
	return t, true
}

// closedAtAt is the closed_at a reader sees at now: the stored event instant, or expires_at once the
// clock has passed the deadline of a stored-open authorization, otherwise null.
func (a *Authorization) closedAtAt(now time.Time) *string {
	switch {
	case a.ClosedAt != nil:
		c := *a.ClosedAt
		return &c
	case a.Status == authOpen && a.StatusAt(now) == authExpired:
		c := a.ExpiresAt
		return &c
	}
	return nil
}

// StatusAt is the effective status: a stored open authorization at or past its deadline is expired.
func (a *Authorization) StatusAt(now time.Time) string {
	if a.Status == authOpen && !now.Before(a.expiresTime()) {
		return authExpired
	}
	return a.Status
}

// RemainingAt is the amount still held at now: zero unless the authorization is effectively open.
func (a *Authorization) RemainingAt(now time.Time) int64 {
	if a.StatusAt(now) != authOpen {
		return 0
	}
	return a.Amount - a.CapturedAmount
}

// TTL is the lifetime of API-created authorizations in seconds (unset means 600).
func (st *State) TTL() int64 {
	if st.AuthTTLSeconds <= 0 {
		return defaultAuthTTLSeconds
	}
	return st.AuthTTLSeconds
}

// Held is the sum of remaining amounts over the user's effectively open authorizations.
// ponytail: linear scan under the global lock; index by payer if authorizations ever number in the millions.
func (st *State) Held(userID string, now time.Time) int64 {
	var held int64
	for _, a := range st.Authorizations {
		if a.FromUserID == userID {
			held += a.RemainingAt(now)
		}
	}
	return held
}

// Available is what the user can spend now: Balance minus holds. Never negative by invariant.
func (st *State) Available(u *User, now time.Time) int64 {
	return u.Balance - st.Held(u.ID, now)
}

func (st *State) authBody(a *Authorization, now time.Time) *AuthorizationBody {
	b := &AuthorizationBody{
		AuthorizationID: a.AuthorizationID,
		FromUserID:      a.FromUserID,
		ToUserID:        a.ToUserID,
		Amount:          a.Amount,
		CapturedAmount:  a.CapturedAmount,
		RemainingAmount: a.RemainingAt(now),
		Currency:        st.Currency,
		Note:            a.Note,
		Visibility:      a.Visibility,
		Status:          a.StatusAt(now),
		ExpiresAt:       a.ExpiresAt,
		PaymentIDs:      append([]string{}, a.PaymentIDs...),
		CreatedAt:       a.CreatedAt,
		ClosedAt:        a.closedAtAt(now),
	}
	if from := st.userByID(a.FromUserID); from != nil {
		b.FromHandle = from.Handle
	}
	if to := st.userByID(a.ToUserID); to != nil {
		b.ToHandle = to.Handle
	}
	if n := len(a.PaymentIDs); n > 0 {
		last := a.PaymentIDs[n-1]
		b.PaymentID = &last
	}
	return b
}

// Authorize places a hold. No money moves and the hold is not a feed item.
func (st *State) Authorize(caller string, in AuthorizeIn, now time.Time) (*AuthorizationBody, *AppError) {
	now = st.Stamp(now)
	from, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	to := st.UserByHandle(in.ToHandle)
	if to == nil {
		return nil, errNotFound("no user has that handle")
	}
	if to.ID == from.ID {
		return nil, NewErr(422, "self_payment", "cannot authorize a payment to yourself")
	}
	if st.Available(from, now) < in.Amount {
		return nil, NewErr(409, "insufficient_funds", "available funds are below the amount")
	}
	a := &Authorization{
		AuthorizationID: st.NewID("a"),
		FromUserID:      from.ID,
		ToUserID:        to.ID,
		Amount:          in.Amount,
		Note:            in.Note,
		Visibility:      in.Visibility,
		Status:          authOpen,
		ExpiresAt:       FormatMicro(now.Add(time.Duration(st.TTL()) * time.Second)),
		PaymentIDs:      []string{},
		CreatedAt:       FormatMicro(now),
	}
	a.expiry, _ = time.Parse(time.RFC3339, a.ExpiresAt)
	a.created, _ = time.Parse(time.RFC3339, a.CreatedAt)
	exact := a.CreatedAt
	a.CreatedExact, a.createdExact = &exact, a.created
	st.addAuthorization(a)
	return st.authBody(a, now), nil
}

// Capture moves money out of the hold, receiver only. It never checks funds: Held <= Balance guarantees them.
// A final capture (or one that takes the whole remainder) closes the authorization and releases the rest.
func (st *State) Capture(caller, authID string, in CaptureIn, now time.Time) (*Payment, *AppError) {
	now = st.Stamp(now)
	rcv, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	a := st.authByID[authID]
	if a == nil {
		return nil, errNotFound("no such authorization")
	}
	if a.ToUserID != rcv.ID {
		return nil, errForbidden("only the receiver may capture this authorization")
	}
	if a.Status == authVoided || a.Status == authCaptured {
		return nil, NewErr(409, "authorization_not_open", "authorization is not open")
	}
	switch a.StatusAt(now) {
	case authExpired:
		return nil, NewErr(409, "authorization_expired", "authorization has expired")
	case authOpen:
	default:
		return nil, NewErr(409, "authorization_not_open", "authorization is not open")
	}
	rem := a.RemainingAt(now)
	if rem == 0 {
		return nil, NewErr(409, "authorization_not_open", "nothing left to capture")
	}
	amount := rem
	if in.Amount != nil {
		amount = *in.Amount
	}
	if amount > rem {
		return nil, NewErr(422, "capture_exceeds_authorization", "amount is above the uncaptured remainder")
	}
	payer := st.userByID(a.FromUserID)
	id := a.AuthorizationID
	p := st.TransferFor(payer, rcv, amount, a.Note, a.Visibility, nil, nil, &id, now)
	a.CapturedAmount += amount
	a.PaymentIDs = append(a.PaymentIDs, p.PaymentID)
	if in.Final || a.CapturedAmount == a.Amount {
		closed := p.CreatedAt
		a.Status, a.ClosedAt, a.closed = authCaptured, &closed, p.created
	}
	return p, nil
}

// Void releases the remaining hold, payer only. Captures already made stay. Voiding twice is a 200 no-op.
func (st *State) Void(caller, authID string, now time.Time) (*AuthorizationBody, *AppError) {
	now = st.Stamp(now)
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	a := st.authByID[authID]
	if a == nil {
		return nil, errNotFound("no such authorization")
	}
	if a.FromUserID != u.ID {
		return nil, errForbidden("only the payer may void this authorization")
	}
	if a.Status == authVoided {
		return st.authBody(a, now), nil
	}
	if a.StatusAt(now) != authOpen {
		return nil, NewErr(409, "authorization_not_open", "authorization is not open")
	}
	closed := FormatMicro(now)
	a.Status, a.ClosedAt, a.closed = authVoided, &closed, now
	return st.authBody(a, now), nil
}

// ListAuthorizations pages the caller's authorizations newest first; status filters the effective status.
func (st *State) ListAuthorizations(caller, direction, status string, limit, offset int, now time.Time) (any, *AppError) {
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	if direction != "" && direction != "incoming" && direction != "outgoing" {
		return nil, errValidation("direction must be incoming or outgoing")
	}
	if status != "" && !validAuthStatus(status) {
		return nil, errValidation("status must be open, captured, voided or expired")
	}
	keep := func(a *Authorization) bool {
		out, in := a.FromUserID == u.ID, a.ToUserID == u.ID
		switch direction {
		case "incoming":
			out = false
		case "outgoing":
			in = false
		}
		return (in || out) && (status == "" || a.StatusAt(now) == status)
	}
	page, more := pageNewestFirst(st.Authorizations, keep, limit, offset)
	bodies := make([]*AuthorizationBody, len(page))
	for i, a := range page {
		bodies[i] = st.authBody(a, now)
	}
	return authorizationPage{Authorizations: bodies, HasMore: more}, nil
}

func (st *State) addAuthorization(a *Authorization) {
	st.Authorizations = append(st.Authorizations, a)
	st.authByID[a.AuthorizationID] = a
}
