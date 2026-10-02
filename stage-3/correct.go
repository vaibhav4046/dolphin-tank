package main

import "time"

// CorrectionIn is the validated body of POST /payments/{id}/corrections.
type CorrectionIn struct {
	ExpectedRevision, Amount int64
	EffectiveAt, Reason      string
}

// Correct appends a revision to a payment; see CONTRACT v3.
func (st *State) Correct(caller, paymentID string, in CorrectionIn, now time.Time) (*Revision, *AppError) {
	return nil, NewErr(500, "internal_error", "not implemented")
}
