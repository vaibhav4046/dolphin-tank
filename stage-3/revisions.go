package main

// PaymentRevisions lists a payment's revisions, oldest first. Only the sender and the
// receiver may read them; everyone else gets 404, even for a public payment.
func (st *State) PaymentRevisions(caller, paymentID string) (any, *AppError) {
	var found *Payment
	for _, p := range st.Payments {
		if p.PaymentID == paymentID {
			found = p
			break
		}
	}
	if found == nil || (found.FromUserID != caller && found.ToUserID != caller) {
		return nil, errNotFound("no such payment")
	}
	history := st.revByPay[paymentID]
	revisions := make([]*Revision, len(history))
	copy(revisions, history)
	return struct {
		Revisions []*Revision `json:"revisions"`
	}{revisions}, nil
}
