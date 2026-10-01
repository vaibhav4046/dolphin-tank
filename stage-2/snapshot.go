package main

import (
	"bytes"
	"encoding/json"
	"time"
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
	// Only an absent key (a stage-1 export) defaults the ttl; a present null or 0
	// decodes to 0 and must not be mistaken for absence by trNormalize.
	var keys map[string]json.RawMessage
	_ = json.Unmarshal(top["state"], &keys)
	if _, supplied := keys["authorization_ttl_seconds"]; supplied && st.AuthTTLSeconds < 1 {
		return nil, trBad("authorization_ttl_seconds must be an integer from 1 to %d", trMaxTTL)
	}
	trNormalize(&st)
	if e := trValidateState(&st); e != nil {
		return nil, e
	}
	// Holds only ever shrink as time passes, so a state valid now is still valid
	// when Import swaps it in a moment later.
	now := time.Now()
	if e := trCheckHolds(&st, now); e != nil {
		return nil, e
	}
	if err := trSafeReindex(&st, now); err != nil {
		return nil, trBad("invalid state: %v", err)
	}
	return &st, nil
}

// trNormalize makes every collection non-nil, so it marshals as [] or {}, and
// gives a stage-1 state (no authorizations, no ttl) its stage-2 defaults.
func trNormalize(st *State) {
	if st.Authorizations == nil {
		st.Authorizations = []*Authorization{}
	}
	for _, a := range st.Authorizations {
		if a != nil && a.PaymentIDs == nil {
			a.PaymentIDs = []string{}
		}
	}
	if st.AuthTTLSeconds == 0 {
		st.AuthTTLSeconds = trDefaultTTL
	}
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
	if st.AuthTTLSeconds < 1 || st.AuthTTLSeconds > trMaxTTL {
		return trBad("authorization_ttl_seconds must be an integer from 1 to %d", trMaxTTL)
	}
	auths := make(map[string]bool, len(st.Authorizations))
	for _, a := range st.Authorizations {
		if a == nil {
			return trBad("state contains a null authorization")
		}
		auths[a.AuthorizationID] = true
	}
	for _, p := range st.Payments {
		if p.AuthorizationID != nil && !auths[*p.AuthorizationID] {
			return trBad("payment %q references an unknown authorization", p.PaymentID)
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
