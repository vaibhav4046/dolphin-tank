package main

import (
	"bytes"
	"encoding/json"
)

const (
	trTrack         = "pocketful"
	trFormatVersion = 1
)

type trEnvelope struct {
	Track         string `json:"track"`
	FormatVersion int    `json:"format_version"`
	State         *State `json:"state"`
}

// Export marshals the whole State under the lock: an atomic snapshot. Nil
// maps and slices are normalised first so an export of any state, and of the
// import of that export, is byte-identical.
func (s *Store) Export() ([]byte, *AppError) {
	s.mu.Lock()
	defer s.mu.Unlock()
	trNormalize(s.st)
	b, err := MarshalJSON(trEnvelope{Track: trTrack, FormatVersion: trFormatVersion, State: s.st})
	if err != nil {
		return nil, NewErr(500, "internal_error", "could not encode state")
	}
	return b, nil
}

// Import replaces everything with the exported state, or changes nothing.
func (s *Store) Import(raw []byte) *AppError {
	st, e := trParseExport(raw)
	if e != nil {
		return e
	}
	s.mu.Lock()
	s.st = st
	s.mu.Unlock()
	return nil
}

func trParseExport(raw []byte) (*State, *AppError) {
	if !json.Valid(raw) {
		return nil, NewErr(400, "malformed_request", "body is not valid JSON")
	}
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil || top == nil {
		return nil, trBad("import body must be an object with track, format_version and state")
	}
	var track string
	if json.Unmarshal(top["track"], &track) != nil || track != trTrack {
		return nil, trBad("track must be %q", trTrack)
	}
	var fv any
	dec := json.NewDecoder(bytes.NewReader(top["format_version"]))
	dec.UseNumber()
	n, isNum := json.Number(""), false
	if dec.Decode(&fv) == nil {
		n, isNum = fv.(json.Number)
	}
	if v, ok := trIntFromNumber(n); !isNum || !ok || v != trFormatVersion {
		return nil, trBad("format_version must be %d", trFormatVersion)
	}
	if b := bytes.TrimSpace(top["state"]); len(b) == 0 || b[0] != '{' {
		return nil, trBad("state must be an object")
	}
	var st State
	if err := json.Unmarshal(top["state"], &st); err != nil {
		return nil, trBad("state is not a valid pocketful state")
	}
	trNormalize(&st)
	if e := trValidateState(&st); e != nil {
		return nil, e
	}
	if err := trSafeReindex(&st); err != nil {
		return nil, trBad("invalid state: %v", err)
	}
	return &st, nil
}

// trNormalize makes every collection non-nil, so it marshals as [] or {}.
func trNormalize(st *State) {
	if st.Users == nil {
		st.Users = []*User{}
	}
	if st.Payments == nil {
		st.Payments = []*Payment{}
	}
	if st.Requests == nil {
		st.Requests = []*Request{}
	}
	if st.Splits == nil {
		st.Splits = []*Split{}
	}
	if st.Tokens == nil {
		st.Tokens = map[string]string{}
	}
	if st.Seq == nil {
		st.Seq = map[string]int64{}
	}
	if st.Sys.Operators == nil {
		st.Sys.Operators = map[string]bool{}
	}
	if st.Sys.Idem == nil {
		st.Sys.Idem = map[string]*IdemRecord{}
	}
}

// trValidateState checks what Reindex does not: currency, minor units, nil
// elements (which would panic), tokens of unknown users and broken receipts.
func trValidateState(st *State) *AppError {
	if st.Currency == "" {
		return trBad("currency must not be empty")
	}
	if st.MinorUnits != 0 && st.MinorUnits != 2 && st.MinorUnits != 3 {
		return trBad("minor_units must be 0, 2 or 3")
	}
	users := make(map[string]bool, len(st.Users))
	for _, u := range st.Users {
		if u == nil {
			return trBad("state contains a null user")
		}
		if u.Balance < 0 {
			return trBad("negative balance in state")
		}
		users[u.ID] = true
	}
	for _, p := range st.Payments {
		if p == nil {
			return trBad("state contains a null payment")
		}
	}
	for _, r := range st.Requests {
		if r == nil {
			return trBad("state contains a null request")
		}
	}
	for _, sp := range st.Splits {
		if sp == nil {
			return trBad("state contains a null split")
		}
	}
	for tok, uid := range st.Tokens {
		if tok == "" || !users[uid] {
			return trBad("state contains a token for an unknown user")
		}
	}
	for _, n := range st.Seq {
		if n < 0 {
			return trBad("negative id counter in state")
		}
	}
	for _, rec := range st.Sys.Idem {
		if rec == nil || len(rec.Resp) == 0 {
			return trBad("state contains an incomplete idempotency record")
		}
	}
	return nil
}
