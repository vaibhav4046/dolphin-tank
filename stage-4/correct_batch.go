package main

import "time"

const batchMaxItems = 32

// BatchItem is one entry of POST /correction-batches. Err is the item's own body error: it is
// reported when the walk reaches the item, so an earlier item's 404 or 409 still comes first.
type BatchItem struct {
	PaymentID string
	In        CorrectionIn
	Err       *AppError
}

// CorrectionBatchOut is the 201 body of POST /correction-batches.
type CorrectionBatchOut struct {
	CorrectionBatchID string      `json:"correction_batch_id"`
	RecordedAt        string      `json:"recorded_at"`
	Revisions         []*Revision `json:"revisions"`
}

// ParseBatchBody reads the shape of the batch: 1..32 objects, each naming a payment_id, all distinct.
// Anything else is 422 validation_failed. Each item's correction fields are parsed with the ordinary
// correction rules, but their errors are kept on the item (see BatchItem). Unknown fields are ignored.
func ParseBatchBody(obj map[string]any) ([]BatchItem, *AppError) {
	raw, ok := obj["corrections"].([]any)
	if !ok || len(raw) < 1 || len(raw) > batchMaxItems {
		return nil, errValidation("corrections must be an array of 1 to 32 objects")
	}
	items := make([]BatchItem, len(raw))
	seen := make(map[string]struct{}, len(raw))
	for i, el := range raw {
		o, ok := el.(map[string]any)
		if !ok {
			return nil, errValidation("every correction must be an object")
		}
		id, ok := o["payment_id"].(string)
		if !ok {
			return nil, errValidation("every correction needs a payment_id string")
		}
		if _, dup := seen[id]; dup {
			return nil, errValidation("payment_id values must be distinct")
		}
		seen[id] = struct{}{}
		items[i].PaymentID = id
		items[i].In, items[i].Err = ParseCorrectionBody(o)
	}
	return items, nil
}

// batchStep is one validated item: the payment, its latest revision and the instant it takes effect.
type batchStep struct {
	p      *Payment
	latest *Revision
	in     CorrectionIn
	eff    time.Time
}

func (s batchStep) delta() int64 { return s.in.Amount - s.latest.Amount }

// CorrectBatch applies every item or none. The Store lock (held by the caller) is what makes a batch
// and any other correction sharing an expected revision exclusive: revisions are compared and appended
// inside one critical section. Order: item errors in input order (validation 422 -> 404 -> capture or
// refund 422 linked_payment_immutable -> stale 409 -> below the refunded amount 422) -> settlement
// completeness 422 -> identical settlement instants 422 -> combined current affordability 409 ->
// historical overdraft 409. A rejected batch changes nothing, not even the clock.
func (st *State) CorrectBatch(items []BatchItem, now time.Time) (*CorrectionBatchOut, *AppError) {
	stamp := st.ReadNow(now)
	steps, e := st.checkBatchItems(items, stamp)
	if e != nil {
		return nil, e
	}
	if e := st.checkBatchSettlements(steps); e != nil {
		return nil, e
	}
	if e := st.checkBatchAffordable(steps, stamp); e != nil {
		return nil, e
	}
	return st.applyBatch(steps, stamp)
}

func (st *State) checkBatchItems(items []BatchItem, stamp time.Time) ([]batchStep, *AppError) {
	steps := make([]batchStep, 0, len(items))
	for _, it := range items {
		if it.Err != nil {
			return nil, it.Err
		}
		eff, e := validCorrection(it.In, stamp)
		if e != nil {
			return nil, e
		}
		p := st.payByID[it.PaymentID]
		if p == nil {
			return nil, errNotFound("no such payment")
		}
		if p.AuthorizationID != nil || p.isRefund() {
			return nil, NewErr(422, "linked_payment_immutable", "captures and refunds cannot be corrected")
		}
		history := st.revByPay[it.PaymentID]
		latest := history[len(history)-1]
		if it.In.ExpectedRevision != latest.Revision {
			return nil, NewErr(409, "stale_revision", "expected_revision is not the latest revision")
		}
		if it.In.Amount < st.refundedAmount(it.PaymentID) {
			return nil, NewErr(422, "refund_exceeds_payment", "the correction would leave the payment below its refunded amount")
		}
		steps = append(steps, batchStep{p: p, latest: latest, in: it.In, eff: eff})
	}
	return steps, nil
}

// checkBatchSettlements: touching one member of a settlement requires every member (refund payments
// carry no settlement_id and are never members), and the members' new effective instants must be the
// same instant, whatever offset each is spelled in.
func (st *State) checkBatchSettlements(steps []batchStep) *AppError {
	var order []string
	inBatch := make(map[string]time.Time, len(steps))
	touched := map[string]bool{}
	for _, s := range steps {
		inBatch[s.p.PaymentID] = s.eff
		if sid := s.p.SettlementID; sid != nil && !touched[*sid] {
			touched[*sid] = true
			order = append(order, *sid)
		}
	}
	if len(order) == 0 {
		return nil
	}
	members := make(map[string][]string, len(order))
	for _, p := range st.Payments {
		if p.SettlementID != nil && touched[*p.SettlementID] {
			members[*p.SettlementID] = append(members[*p.SettlementID], p.PaymentID)
		}
	}
	for _, sid := range order {
		for _, pid := range members[sid] {
			if _, ok := inBatch[pid]; !ok {
				return NewErr(422, "incomplete_settlement", "every member of a settlement must be corrected together")
			}
		}
	}
	for _, sid := range order {
		first := inBatch[members[sid][0]]
		for _, pid := range members[sid][1:] {
			if !inBatch[pid].Equal(first) {
				return errValidation("members of one settlement must have the same effective instant")
			}
		}
	}
	return nil
}

// checkBatchAffordable judges each wallet by the net of every proposed revision: a wallet one item
// credits and another debits is only short if the difference is, and held funds do not count.
func (st *State) checkBatchAffordable(steps []batchStep, stamp time.Time) *AppError {
	net := make(map[string]int64, len(steps)*2)
	for _, s := range steps {
		net[s.p.FromUserID] -= s.delta()
		net[s.p.ToUserID] += s.delta()
	}
	for id, n := range net {
		if n < 0 && st.Available(st.usersByID[id], stamp)+n < 0 {
			return NewErr(409, "insufficient_funds", "available funds are below the batch")
		}
	}
	return nil
}

// applyBatch records every revision at one instant: the stamp, raised so each member's new
// recorded_at is later than its previous one (only an imported revision recorded ahead of the clock
// can need that). Then each wallet touched is checked at every past boundary; any failure rolls all
// of it back, and the batch id and the clock are only taken once nothing can fail.
func (st *State) applyBatch(steps []batchStep, stamp time.Time) (*CorrectionBatchOut, *AppError) {
	rec := stamp
	for _, s := range steps {
		if floor := s.latest.rec.Truncate(time.Microsecond).Add(time.Microsecond); rec.Before(floor) {
			rec = floor
		}
	}
	batchID := new(string)
	revs := make([]*Revision, len(steps))
	wallets := make(map[string]struct{}, len(steps)*2)
	for i, s := range steps {
		revs[i] = &Revision{PaymentID: s.p.PaymentID, Revision: s.latest.Revision + 1, Amount: s.in.Amount,
			EffectiveAt: s.in.EffectiveAt, RecordedAt: FormatMicro(rec), Reason: s.in.Reason,
			CorrectionBatchID: batchID, eff: s.eff, rec: rec}
		st.appendRevision(revs[i])
		st.moveBatchDelta(s, s.delta())
		wallets[s.p.FromUserID], wallets[s.p.ToUserID] = struct{}{}, struct{}{}
	}
	for id := range wallets {
		if !st.overdrawnInThePast(id, stamp) {
			continue
		}
		for i := len(steps) - 1; i >= 0; i-- {
			st.dropLastRevision(steps[i].p.PaymentID)
			st.moveBatchDelta(steps[i], -steps[i].delta())
		}
		return nil, NewErr(409, "historical_overdraft", "the batch would leave a wallet negative at a past moment")
	}
	*batchID = st.NewID("cb")
	st.lastStamp = stamp
	if rec.After(st.lastStamp) {
		st.lastStamp = rec
	}
	return &CorrectionBatchOut{CorrectionBatchID: *batchID, RecordedAt: FormatMicro(rec), Revisions: revs}, nil
}

// moveBatchDelta moves a revision's change from the payer to the payee (the reverse when negative).
func (st *State) moveBatchDelta(s batchStep, delta int64) {
	st.usersByID[s.p.FromUserID].Balance -= delta
	st.usersByID[s.p.ToUserID].Balance += delta
}
