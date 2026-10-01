package main

import (
	"net/http"
	"time"
)

func handleAuthorize(s *Server, c *call) (int, []byte, *AppError) {
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
		a, e := st.Authorize(c.uid, AuthorizeIn{ToHandle: to, Amount: amount, Note: note, Visibility: visibility}, time.Now())
		if e != nil {
			return nil, e
		}
		return a, nil
	})
}

func handleCapture(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, true, func(st *State, obj map[string]any) (any, *AppError) {
		amount, e := OptCaptureAmount(obj)
		if e != nil {
			return nil, e
		}
		final, e := OptFinal(obj)
		if e != nil {
			return nil, e
		}
		p, e := st.Capture(c.uid, c.id, CaptureIn{Amount: amount, Final: final}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
}

func handleVoid(s *Server, c *call) (int, []byte, *AppError) {
	if _, e := readObject(c.w, c.r, true); e != nil {
		return 0, nil, e
	}
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		a, e := st.Void(c.uid, c.id, time.Now())
		if e != nil {
			return nil, e
		}
		return a, nil
	})
	return http.StatusOK, body, e
}

func handleListAuthorizations(s *Server, c *call) (int, []byte, *AppError) {
	q := c.r.URL.Query()
	limit, offset, e := ParseLimitOffset(q)
	if e != nil {
		return 0, nil, e
	}
	direction, status := filterParam(q, "direction"), filterParam(q, "status")
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.ListAuthorizations(c.uid, direction, status, limit, offset, time.Now())
	})
	return http.StatusOK, body, e
}
