package main

import "strconv"

// Idempotent runs fn at most once per (user, method, path, key).
//
// Every read and write of the Store goes through the single s.mu, so the key
// lookup, the effect, the marshalling and the record write below are one
// critical section. That is what makes concurrent identical requests yield
// exactly one 201 and what keeps balances from ever being seen mid-move.
func (s *Store) Idempotent(userID, method, path, key string, body map[string]any,
	fn func(st *State) (any, *AppError)) (int, []byte, *AppError) {
	if e := CheckIdemKey(key); e != nil {
		return 0, nil, e
	}
	canon := trCanonBody(body)
	rk := trIdemKey(userID, method, path, key)

	s.mu.Lock()
	defer s.mu.Unlock()

	if rec, ok := s.st.Sys.Idem[rk]; ok && rec != nil {
		if rec.Body != canon {
			return 0, nil, NewErr(409, "idempotency_key_reuse", "Idempotency-Key was already used with a different request body")
		}
		return 200, append([]byte(nil), rec.Resp...), nil
	}

	v, e := fn(s.st)
	if e != nil {
		return 0, nil, e
	}
	resp, err := MarshalJSON(v)
	if err != nil {
		return 0, nil, NewErr(500, "internal_error", "could not encode response")
	}
	if s.st.Sys.Idem == nil {
		s.st.Sys.Idem = map[string]*IdemRecord{}
	}
	s.st.Sys.Idem[rk] = &IdemRecord{Body: canon, Resp: append([]byte(nil), resp...)}
	return 201, resp, nil
}

// trIdemKey quotes every part so the composite is unambiguous and always valid
// UTF-8 (a map key must survive JSON export), whatever bytes the client sent.
func trIdemKey(userID, method, path, key string) string {
	return strconv.Quote(userID) + " " + method + " " + strconv.Quote(path) + " " + strconv.Quote(key)
}
