package main

import "time"

const trMaxTransfers = 32

type trSettlementOut struct {
	SettlementID string     `json:"settlement_id"`
	CommittedAt  string     `json:"committed_at"`
	Payments     []*Payment `json:"payments"`
}

type trLeg struct {
	from, to *User
	amount   int64
	note     string
	vis      string
}

// Settle is POST /settlements. The caller must be an operator; the HTTP layer
// maps "no token" to 401 before getting here.
func (s *Store) Settle(userID, key string, body map[string]any) (int, []byte, *AppError) {
	if !s.IsOperator(userID) {
		return 0, nil, NewErr(403, "forbidden", "settlements require an operator")
	}
	return s.Idempotent(userID, "POST", "/settlements", key, body, func(st *State) (any, *AppError) {
		return trSettle(st, body, time.Now())
	})
}

// trSettle validates the whole batch, then checks collective affordability,
// and only then moves money. Nothing is mutated before the last check passes.
func trSettle(st *State, body map[string]any, now time.Time) (any, *AppError) {
	now = st.Stamp(now) // one instant for the whole batch: committed_at, every member's created_at, effective and recorded time
	raw, ok := body["transfers"].([]any)
	if !ok || len(raw) < 1 || len(raw) > trMaxTransfers {
		return nil, NewErr(422, "validation_failed", "transfers must be an array of 1 to 32 objects")
	}
	for _, el := range raw {
		if _, ok := el.(map[string]any); !ok {
			return nil, NewErr(422, "validation_failed", "every transfer must be an object")
		}
	}
	legs := make([]trLeg, 0, len(raw))
	for _, el := range raw {
		leg, e := trParseLeg(st, el.(map[string]any))
		if e != nil {
			return nil, e
		}
		legs = append(legs, leg)
	}

	net := make(map[*User]int64, len(legs)*2)
	for _, l := range legs {
		net[l.from] -= l.amount
		net[l.to] += l.amount
	}
	// A wallet's open holds stay reserved: its balance after the batch must still
	// cover them. A net-credited wallet always passes (Held <= Balance).
	for u, delta := range net {
		if u.Balance+delta < st.Held(u.ID, now) {
			return nil, NewErr(409, "insufficient_funds", "settlement would leave a wallet below its held funds")
		}
	}

	out := trSettlementOut{
		SettlementID: st.NewID("st"),
		CommittedAt:  FormatMicro(now),
		Payments:     make([]*Payment, 0, len(legs)),
	}
	for _, l := range legs {
		sid := out.SettlementID
		out.Payments = append(out.Payments, st.Transfer(l.from, l.to, l.amount, l.note, l.vis, nil, &sid, now))
	}
	return out, nil
}

// trParseLeg applies the ordinary payment rules to one entry, in this order:
// handle types, amount, note, visibility, unknown sender, unknown receiver,
// self-transfer.
func trParseLeg(st *State, o map[string]any) (trLeg, *AppError) {
	fh, ok1 := o["from_handle"].(string)
	th, ok2 := o["to_handle"].(string)
	if !ok1 || !ok2 {
		return trLeg{}, NewErr(422, "validation_failed", "from_handle and to_handle must be strings")
	}
	amount, e := ReqAmount(o, "amount")
	if e != nil {
		return trLeg{}, e
	}
	note, e := OptNote(o)
	if e != nil {
		return trLeg{}, e
	}
	vis, e := OptVisibility(o)
	if e != nil {
		return trLeg{}, e
	}
	from, to := st.UserByHandle(fh), st.UserByHandle(th)
	if from == nil || to == nil {
		return trLeg{}, NewErr(404, "not_found", "no user has that handle")
	}
	if from == to {
		return trLeg{}, NewErr(422, "self_payment", "cannot transfer to the same wallet")
	}
	return trLeg{from: from, to: to, amount: amount, note: note, vis: vis}, nil
}
