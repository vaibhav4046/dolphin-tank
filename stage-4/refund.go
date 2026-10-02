package main

import "time"

// RefundIn is the validated body of POST /payments/{id}/refunds.
type RefundIn struct{ Amount int64 }

// isRefund reports whether the payment is itself a refund of another payment.
func (p *Payment) isRefund() bool { return p.RefundOf != nil }

// refundedAmount is the sum of the refunds recorded against a payment. It is a plain scan of
// st.Payments: refunds are ordinary payments and cannot be corrected, so no index or counter exists
// that import, reset or export would have to rebuild. ponytail: O(payments) per refund or correction.
func (st *State) refundedAmount(paymentID string) int64 {
	var sum int64
	for _, p := range st.Payments {
		if p.RefundOf != nil && *p.RefundOf == paymentID {
			sum += p.Amount
		}
	}
	return sum
}

// Refund pays back part or all of a payment from the original receiver to the original sender: a new
// payment in the opposite direction with refund_of naming the target. It never touches the target's
// request, authorization, settlement membership or revisions. The Store lock (held by the caller)
// serialises concurrent refunds: the refunded total is read and the refund appended in one critical
// section, so refunds sharing one payment can never exceed its current amount together.
// Order: caller -> validation 422 -> 404 -> 403 -> invalid_refund_target 422 -> refund_exceeds_payment 422
// -> insufficient_funds 409 (held funds do not count). Every check precedes the first mutation.
func (st *State) Refund(caller, paymentID string, in RefundIn, now time.Time) (*Payment, *AppError) {
	now = st.Stamp(now)
	receiver, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	if in.Amount < 1 || in.Amount > maxAmount {
		return nil, errValidation("amount must be an integer between 1 and 1000000000")
	}
	target := st.payByID[paymentID]
	if target == nil {
		return nil, errNotFound("no such payment")
	}
	if target.ToUserID != receiver.ID {
		return nil, errForbidden("only the original receiver may refund a payment")
	}
	if target.isRefund() {
		return nil, NewErr(422, "invalid_refund_target", "a refund cannot be refunded")
	}
	history := st.revByPay[paymentID]
	if in.Amount > history[len(history)-1].Amount-st.refundedAmount(paymentID) {
		return nil, NewErr(422, "refund_exceeds_payment", "refunds would exceed the payment's current amount")
	}
	if st.Available(receiver, now) < in.Amount {
		return nil, NewErr(409, "insufficient_funds", "available funds are below the refund")
	}
	sender := st.usersByID[target.FromUserID]
	refund := st.TransferFor(receiver, sender, in.Amount, target.Note, target.Visibility, nil, nil, nil, now)
	id := target.PaymentID
	refund.RefundOf = &id
	return refund, nil
}
