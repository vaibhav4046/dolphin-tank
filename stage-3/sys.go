package main

import "encoding/json"

// IdemRecord is one claimed idempotency key: the canonical form of the request
// body and the exact bytes returned the first time. Resp is a RawMessage so the
// bytes survive an export/import round trip verbatim.
type IdemRecord struct {
	Body string          `json:"body"`
	Resp json.RawMessage `json:"resp"`
}

// SysState is the part of the service state owned by the idempotency,
// settlement and snapshot code. It is exported with the rest of State.
type SysState struct {
	Operators map[string]bool        `json:"operators"`
	Idem      map[string]*IdemRecord `json:"idem"`
}

func (s *Store) IsOperator(userID string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.st.Sys.Operators[userID]
}
