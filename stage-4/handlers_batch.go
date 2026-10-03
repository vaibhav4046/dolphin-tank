package main

import (
	"net/http"
	"time"
)

func init() { fixedRoutes["POST /correction-batches"] = route{false, handleCorrectionBatch} }

// handleCorrectionBatch is POST /correction-batches, ordered like POST /settlements: operator 403,
// then the Idempotency-Key, then the body, then the single critical section in Store.Idempotent.
func handleCorrectionBatch(s *Server, c *call) (int, []byte, *AppError) {
	if !s.store.IsOperator(c.uid) {
		return 0, nil, NewErr(http.StatusForbidden, "forbidden", "correction batches require an operator")
	}
	key := c.r.Header.Get("Idempotency-Key")
	if e := CheckIdemKey(key); e != nil {
		return 0, nil, e
	}
	obj, e := readObject(c.w, c.r, false)
	if e != nil {
		return 0, nil, e
	}
	return s.store.Idempotent(c.uid, "POST", "/correction-batches", key, obj, func(st *State) (any, *AppError) {
		items, e := ParseBatchBody(obj)
		if e != nil {
			return nil, e
		}
		return st.CorrectBatch(items, time.Now())
	})
}
