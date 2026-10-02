package main

import (
	"regexp"
	"slices"
	"strings"
	"time"
)

const (
	// microLayout renders an instant in UTC with exactly six fraction digits and a "+00:00" offset.
	microLayout = "2006-01-02T15:04:05.000000-07:00"

	// historyVersion is the State.HistoryVersion of a state that carries revisions and opening balances.
	historyVersion = 3
)

// histInf is later than any recorded or client-supplied instant: the K of "everything recorded".
var histInf = time.Date(100000, 1, 1, 0, 0, 0, 0, time.UTC)

var instantShape = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$`)

// FormatMicro renders t in UTC with six fraction digits: "2006-01-02T15:04:05.000000+00:00".
func FormatMicro(t time.Time) string { return t.UTC().Format(microLayout) }

// ParseInstant is the one parser of client-supplied instants (as_of, known_at, from, to, effective_at,
// seeded created_at): an RFC 3339 date-time WITH an offset (Z, z or +hh:mm) and an optional fraction.
// Empty, naive, bare-date, space-separated and trailing-junk inputs are not instants.
func ParseInstant(s string) (time.Time, bool) {
	if !instantShape.MatchString(s) {
		return time.Time{}, false
	}
	b := []byte(s)
	b[10] = 'T'
	if b[len(b)-1] == 'z' {
		b[len(b)-1] = 'Z'
	}
	t, err := time.Parse(time.RFC3339, string(b))
	if err != nil {
		return time.Time{}, false
	}
	return t.UTC(), true
}

// Stamp is the instant a state-changing operation uses for every timestamp and decision in it.
// It advances: no two stamps are equal and each is later than anything recorded before, so back-to-back
// writes inside one clock tick still get distinct, increasing recorded times.
func (st *State) Stamp(now time.Time) time.Time {
	t := st.ReadNow(now)
	st.lastStamp = t
	return t
}

// ReadNow is the instant a read starts: the clock, but never earlier than the newest write's stamp plus
// one microsecond, so a read sees every earlier write. It does not advance anything.
func (st *State) ReadNow(now time.Time) time.Time {
	t := now.UTC().Truncate(time.Microsecond)
	if !st.lastStamp.IsZero() {
		if floor := st.lastStamp.Add(time.Microsecond); t.Before(floor) {
			t = floor
		}
	}
	return t
}

func (st *State) indexPayment(p *Payment) {
	if st.payByID == nil {
		st.payByID = map[string]*Payment{}
	}
	st.payByID[p.PaymentID] = p
}

func (st *State) appendRevision(r *Revision) {
	if st.revByPay == nil {
		st.revByPay = map[string][]*Revision{}
	}
	st.Revisions = append(st.Revisions, r)
	st.revByPay[r.PaymentID] = append(st.revByPay[r.PaymentID], r)
}

// selected is sel(p,k): the latest revision of the payment recorded at or before k, nil if none yet.
func (st *State) selected(paymentID string, k time.Time) *Revision {
	revs := st.revByPay[paymentID]
	for i := len(revs) - 1; i >= 0; i-- {
		if !revs[i].rec.After(k) {
			return revs[i]
		}
	}
	return nil
}

// Movement is one payment's effect on a wallet under the revision known at some instant.
type Movement struct {
	Payment *Payment
	Rev     *Revision
	Delta   int64
}

// movements lists the user's selected movements, each payment once, in payment insertion order.
// ponytail: scans every payment; index payments by user if states reach millions of payments.
func (st *State) movements(userID string, k time.Time) []Movement {
	var out []Movement
	for _, p := range st.Payments {
		if p.FromUserID != userID && p.ToUserID != userID {
			continue
		}
		r := st.selected(p.PaymentID, k)
		if r == nil {
			continue
		}
		var d int64
		if p.ToUserID == userID {
			d += r.Amount
		}
		if p.FromUserID == userID {
			d -= r.Amount
		}
		out = append(out, Movement{Payment: p, Rev: r, Delta: d})
	}
	return out
}

// MovementsFor is the user's movements under knowledge k, ordered by (effective instant, payment id bytewise).
func (st *State) MovementsFor(userID string, k time.Time) []Movement {
	out := st.movements(userID, k)
	slices.SortFunc(out, func(a, b Movement) int {
		if c := a.Rev.eff.Compare(b.Rev.eff); c != 0 {
			return c
		}
		return strings.Compare(a.Payment.PaymentID, b.Payment.PaymentID)
	})
	return out
}

// TotalAt is the wallet's balance at effective time t as known at k: the opening balance plus every
// selected movement that took effect at or before t. An unknown user has nothing.
func (st *State) TotalAt(userID string, t, k time.Time) int64 {
	u := st.usersByID[userID]
	if u == nil {
		return 0
	}
	total := u.OpeningBalance
	for _, m := range st.movements(userID, k) {
		if !m.Rev.eff.After(t) {
			total += m.Delta
		}
	}
	return total
}

// HeldAt is the sum of the user's holds (as payer) at time t under knowledge k. Rule H, per hold:
// it counts once created at or before both t and k. Its deadline is known with its creation, so it
// is 0 from expires_at on. A void or final capture releases it for a reader who knows of the event
// (closed_at <= min(t,k)). Otherwise it holds the amount less the captures made by min(t,k).
// A stored-expired hold (seeded without a lifecycle) holds nothing once created.
func (st *State) HeldAt(userID string, t, k time.Time) int64 {
	var held int64
	for _, a := range st.Authorizations {
		if a.FromUserID == userID {
			held += st.holdRemainingAt(a, t, k)
		}
	}
	return held
}

// heldAt is HeldAt; the flag is vestigial (holds have one placement instant now) and ignored.
func (st *State) heldAt(userID string, t, k time.Time, _ bool) int64 { return st.HeldAt(userID, t, k) }

func (st *State) holdRemainingAt(a *Authorization, t, k time.Time) int64 {
	known := t
	if k.Before(known) {
		known = k
	}
	if a.createdTime().After(known) {
		return 0
	}
	if !t.Before(a.expiresTime()) || a.Status == authExpired {
		return 0
	}
	if closed, ok := a.closedTime(); ok && a.Status != authOpen && !closed.After(known) {
		return 0
	}
	// Captures later than min(t,k) are not yet made or known. captured_amount may exceed the listed
	// capture payments (a seeded partial capture without payments): that part counts as already made.
	captured := a.CapturedAmount
	for _, pid := range a.PaymentIDs {
		if p := st.payByID[pid]; p != nil && p.created.After(known) {
			captured -= p.Amount
		}
	}
	return max(a.Amount-max(captured, 0), 0)
}

// AvailableAt is what the wallet could spend at t as known at k: total less holds.
func (st *State) AvailableAt(userID string, t, k time.Time) int64 {
	return st.TotalAt(userID, t, k) - st.HeldAt(userID, t, k)
}

// MeQuery is the raw query of GET /me: nil = parameter absent, a pointer to "" = present but empty (422).
type MeQuery struct{ AsOf, KnownAt *string }

// meAtBody is the /me body of a historical view: the same money fields plus the echoed parameters.
type meAtBody struct {
	meBody
	AsOf    *string `json:"as_of,omitempty"`
	KnownAt *string `json:"known_at,omitempty"`
}

// MeAt is GET /me. Without as_of and known_at it is Me (current corrected values). With either, all
// four money fields describe one view: total at as_of as known at known_at, minus holds in that view.
func (st *State) MeAt(caller string, q MeQuery, now time.Time) (any, *AppError) {
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	if q.AsOf == nil && q.KnownAt == nil {
		return st.Me(caller, now), nil
	}
	t, k := st.ReadNow(now), st.ReadNow(now)
	if q.AsOf != nil {
		var ok bool
		if t, ok = ParseInstant(*q.AsOf); !ok {
			return nil, errValidation("as_of must be an RFC 3339 instant with an offset")
		}
	}
	if q.KnownAt != nil {
		var ok bool
		if k, ok = ParseInstant(*q.KnownAt); !ok {
			return nil, errValidation("known_at must be an RFC 3339 instant with an offset")
		}
	}
	total, held := st.TotalAt(u.ID, t, k), st.HeldAt(u.ID, t, k)
	return meAtBody{
		meBody: meBody{UserID: u.ID, DisplayName: u.DisplayName, Handle: u.Handle,
			Balance: total, Total: total, Available: total - held, Held: held,
			Currency: st.Currency, MinorUnits: st.MinorUnits},
		AsOf: q.AsOf, KnownAt: q.KnownAt,
	}, nil
}
