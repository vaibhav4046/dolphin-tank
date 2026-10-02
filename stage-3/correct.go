package main

import (
	"slices"
	"sort"
	"time"
	"unicode/utf8"
)

const corrReasonMaxRunes = 200

// CorrectionIn is the validated body of POST /payments/{id}/corrections.
type CorrectionIn struct {
	ExpectedRevision, Amount int64
	EffectiveAt, Reason      string
}

// Correct appends a revision to a payment the caller sent and moves the difference between the same
// two wallets, or changes nothing. The Store lock (held by the caller) is what serialises concurrent
// corrections: expected_revision is compared and the revision appended inside one critical section.
// Order: validation 422 -> 404 -> 403 -> linked 422 -> stale 409 -> funds 409 -> historical overdraft 409.
func (st *State) Correct(caller, paymentID string, in CorrectionIn, now time.Time) (*Revision, *AppError) {
	now = st.Stamp(now)
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	eff, e := validCorrection(in, now)
	if e != nil {
		return nil, e
	}
	p := st.payByID[paymentID]
	if p == nil {
		return nil, errNotFound("no such payment")
	}
	if p.FromUserID != u.ID {
		return nil, errForbidden("only the original sender may correct a payment")
	}
	if p.SettlementID != nil || p.AuthorizationID != nil {
		return nil, NewErr(422, "linked_payment_immutable", "settlement members and captures cannot be corrected")
	}
	history := st.revByPay[paymentID]
	latest := history[len(history)-1]
	if in.ExpectedRevision != latest.Revision {
		return nil, NewErr(409, "stale_revision", "expected_revision is not the latest revision")
	}

	sender, receiver := st.usersByID[p.FromUserID], st.usersByID[p.ToUserID]
	debited, credited, moved := sender, receiver, in.Amount-latest.Amount
	if moved < 0 {
		debited, credited, moved = receiver, sender, -moved
	}
	if moved > 0 && st.Available(debited, now) < moved {
		return nil, NewErr(409, "insufficient_funds", "available funds are below the correction")
	}

	rev := &Revision{PaymentID: paymentID, Revision: latest.Revision + 1, Amount: in.Amount,
		EffectiveAt: in.EffectiveAt, RecordedAt: FormatMicro(now), Reason: in.Reason, eff: eff, rec: now}
	st.appendRevision(rev)
	debited.Balance -= moved
	credited.Balance += moved
	keep := false
	defer func() {
		if !keep {
			debited.Balance += moved
			credited.Balance -= moved
			st.dropLastRevision(paymentID)
		}
	}()
	if st.overdrawnInThePast(sender.ID, now) || st.overdrawnInThePast(receiver.ID, now) {
		return nil, NewErr(409, "historical_overdraft", "the correction would leave a wallet negative at a past moment")
	}
	keep = true
	return rev, nil
}

// validCorrection is the domain's own view of a correction body (the HTTP parser mirrors it) plus the
// one rule only the clock can decide: effective_at is not later than now.
func validCorrection(in CorrectionIn, now time.Time) (time.Time, *AppError) {
	eff, ok := ParseInstant(in.EffectiveAt)
	if !ok || eff.After(now) {
		return time.Time{}, errValidation("effective_at must be an RFC 3339 instant with an offset, not later than now")
	}
	if n := utf8.RuneCountInString(in.Reason); n < 1 || n > corrReasonMaxRunes {
		return time.Time{}, errValidation("reason must be 1 to 200 characters")
	}
	if in.Amount < 0 || in.Amount > maxAmount {
		return time.Time{}, errValidation("amount must be an integer between 0 and 1000000000")
	}
	if in.ExpectedRevision < 1 {
		return time.Time{}, errValidation("expected_revision must be a positive integer")
	}
	return eff, nil
}

func (st *State) dropLastRevision(paymentID string) {
	st.Revisions = st.Revisions[:len(st.Revisions)-1]
	st.revByPay[paymentID] = st.revByPay[paymentID][:len(st.revByPay[paymentID])-1]
}

// overdrawnInThePast reports whether, under every revision recorded so far, the wallet's total or its
// available amount (total less holds) is negative at any boundary up to now: each instant a movement
// takes effect, plus each creation, capture, release and deadline of a hold the wallet placed.
// Movements sharing an instant are combined: a boundary is judged after all of them.
func (st *State) overdrawnInThePast(userID string, now time.Time) bool {
	u := st.usersByID[userID]
	moves := st.MovementsFor(userID, histInf)
	bounds := make([]time.Time, 0, len(moves)+8)
	for _, m := range moves {
		bounds = append(bounds, m.Rev.eff)
	}
	for _, a := range st.Authorizations {
		if a.FromUserID != userID {
			continue
		}
		bounds = append(bounds, a.placedAt(), a.expiresTime())
		if closed, ok := a.closedTime(); ok {
			bounds = append(bounds, closed)
		}
		for _, pid := range a.PaymentIDs {
			if p := st.payByID[pid]; p != nil {
				bounds = append(bounds, p.created)
			}
		}
	}
	slices.SortFunc(bounds, func(a, b time.Time) int { return a.Compare(b) })
	cumulative := make([]int64, len(moves)+1) // cumulative[i] = opening + the first i movements
	cumulative[0] = u.OpeningBalance
	for i, m := range moves {
		cumulative[i+1] = cumulative[i] + m.Delta
	}
	for i, t := range bounds {
		if t.After(now) || (i > 0 && t.Equal(bounds[i-1])) {
			continue
		}
		applied := sort.Search(len(moves), func(j int) bool { return moves[j].Rev.eff.After(t) })
		total := cumulative[applied]
		if total < 0 || total-st.heldAt(userID, t, histInf, true) < 0 {
			return true
		}
	}
	return false
}
