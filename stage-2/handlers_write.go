package main

import (
	"net/http"
	"time"
)

// build runs under the store lock, after the idempotency key has been resolved.
// It reads fields in spec order (first error wins) and calls the domain method.
type build func(st *State, obj map[string]any) (any, *AppError)

// idempotentWrite is the shared order for the four user-facing idempotent paths:
// key header (400/422) -> body (400) -> Store.Idempotent (409 reuse / 201 / 200 replay).
func (s *Server) idempotentWrite(c *call, allowEmptyBody bool, fn build) (int, []byte, *AppError) {
	key := c.r.Header.Get("Idempotency-Key")
	if e := CheckIdemKey(key); e != nil {
		return 0, nil, e
	}
	obj, e := readObject(c.w, c.r, allowEmptyBody)
	if e != nil {
		return 0, nil, e
	}
	return s.store.Idempotent(c.uid, c.r.Method, c.r.URL.Path, key, obj, func(st *State) (any, *AppError) {
		return fn(st, obj)
	})
}

func handlePayment(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, false, func(st *State, obj map[string]any) (any, *AppError) {
		to, e := ReqString(obj, "to_handle")
		if e != nil {
			return nil, e
		}
		amount, e := ReqAmount(obj, "amount")
		if e != nil {
			return nil, e
		}
		note, e := OptNote(obj)
		if e != nil {
			return nil, e
		}
		visibility, e := OptVisibility(obj)
		if e != nil {
			return nil, e
		}
		p, e := st.Pay(c.uid, PaymentIn{ToHandle: to, Amount: amount, Note: note, Visibility: visibility}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
}

func handleCreateRequest(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, false, func(st *State, obj map[string]any) (any, *AppError) {
		payer, e := ReqString(obj, "payer_handle")
		if e != nil {
			return nil, e
		}
		amount, e := ReqAmount(obj, "amount")
		if e != nil {
			return nil, e
		}
		note, e := OptNote(obj)
		if e != nil {
			return nil, e
		}
		r, e := st.CreateRequest(c.uid, RequestIn{PayerHandle: payer, Amount: amount, Note: note}, time.Now())
		if e != nil {
			return nil, e
		}
		return r, nil
	})
}

func handlePayRequest(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, true, func(st *State, obj map[string]any) (any, *AppError) {
		visibility, e := OptVisibility(obj)
		if e != nil {
			return nil, e
		}
		p, e := st.PayRequest(c.uid, c.id, PayIn{Visibility: visibility}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
}

func handleSplit(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, false, func(st *State, obj map[string]any) (any, *AppError) {
		amount, e := ReqAmount(obj, "amount")
		if e != nil {
			return nil, e
		}
		handles, e := ReqHandles(obj, "participant_handles")
		if e != nil {
			return nil, e
		}
		note, e := OptNote(obj)
		if e != nil {
			return nil, e
		}
		return st.Split(c.uid, SplitIn{Amount: amount, Handles: handles, Note: note}, time.Now())
	})
}

func handleSettlement(s *Server, c *call) (int, []byte, *AppError) {
	if !s.store.IsOperator(c.uid) {
		return 0, nil, NewErr(http.StatusForbidden, "forbidden", "settlements require an operator")
	}
	key := c.r.Header.Get("Idempotency-Key")
	if e := CheckIdemKey(key); e != nil {
		return 0, nil, e
	}
	obj, e := readObject(c.w, c.r, false)
	if e != nil {
		return 0, nil, e
	}
	return s.store.Settle(c.uid, key, obj)
}

func handleDecline(s *Server, c *call) (int, []byte, *AppError) {
	return s.requestTransition(c, (*State).Decline)
}

func handleCancel(s *Server, c *call) (int, []byte, *AppError) {
	return s.requestTransition(c, (*State).Cancel)
}

func (s *Server) requestTransition(c *call, act func(st *State, caller, id string) (*Request, *AppError)) (int, []byte, *AppError) {
	if _, e := readObject(c.w, c.r, true); e != nil {
		return 0, nil, e
	}
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		r, e := act(st, c.uid, c.id)
		if e != nil {
			return nil, e
		}
		return r, nil
	})
	return http.StatusOK, body, e
}
