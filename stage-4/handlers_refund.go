package main

import "time"

func init() { subActions["/payments/"]["refunds"] = route{false, handleRefund} }

// handleRefund is POST /payments/{id}/refunds: key header -> body -> amount -> domain checks.
func handleRefund(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, false, func(st *State, obj map[string]any) (any, *AppError) {
		amount, e := ReqAmount(obj, "amount")
		if e != nil {
			return nil, e
		}
		p, e := st.Refund(c.uid, c.id, RefundIn{Amount: amount}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
}
