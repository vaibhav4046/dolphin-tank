package main

import "time"

type SplitIn struct {
	Amount  int64
	Handles []string
	Note    string
}

type splitBody struct {
	SplitID   string     `json:"split_id"`
	Amount    int64      `json:"amount"`
	Currency  string     `json:"currency"`
	Note      string     `json:"note"`
	Shares    []Share    `json:"shares"`
	Requests  []*Request `json:"requests"`
	CreatedAt string     `json:"created_at"`
}

// SplitShares divides amount into n whole-unit shares; the remainder goes one unit each to the first participants.
func SplitShares(amount int64, n int) []int64 {
	if n <= 0 {
		return []int64{}
	}
	base, rem := amount/int64(n), amount%int64(n)
	shares := make([]int64, n)
	for i := range shares {
		shares[i] = base
		if int64(i) < rem {
			shares[i]++
		}
	}
	return shares
}

// Split records the bill and creates one pending request per participant except the caller.
// Every handle is resolved first, so a failure leaves no trace. No balance is read or moved.
func (st *State) Split(caller string, in SplitIn, now time.Time) (any, *AppError) {
	creator, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	people := make([]*User, len(in.Handles))
	for i, h := range in.Handles {
		if people[i] = st.UserByHandle(h); people[i] == nil {
			return nil, errNotFound("no user has handle " + h)
		}
	}
	amounts := SplitShares(in.Amount, len(people))
	shares := make([]Share, len(people))
	reqs := make([]*Request, 0, len(people))
	reqIDs := make([]string, 0, len(people))
	for i, u := range people {
		shares[i] = Share{Handle: u.Handle, Amount: amounts[i]}
		if u.ID == creator.ID {
			continue
		}
		r := st.newRequest(creator, u, amounts[i], in.Note, now)
		reqs = append(reqs, r)
		reqIDs = append(reqIDs, r.RequestID)
	}
	sp := &Split{
		SplitID:    st.NewID("sp"),
		CreatorID:  creator.ID,
		Amount:     in.Amount,
		Currency:   st.Currency,
		Note:       in.Note,
		Shares:     shares,
		RequestIDs: reqIDs,
		CreatedAt:  FormatTime(now),
	}
	st.Splits = append(st.Splits, sp)
	return splitBody{SplitID: sp.SplitID, Amount: sp.Amount, Currency: sp.Currency, Note: sp.Note,
		Shares: shares, Requests: reqs, CreatedAt: sp.CreatedAt}, nil
}
