package main

import (
	"net/http"
	"net/url"
	"time"
)

// emptyParam stands in for a present-but-empty filter so the domain rejects it
// (422) instead of reading "" as absent.
const emptyParam = "(empty)"

func filterParam(q url.Values, name string) string {
	if !q.Has(name) {
		return ""
	}
	if v := q.Get(name); v != "" {
		return v
	}
	return emptyParam
}

func handleMe(s *Server, c *call) (int, []byte, *AppError) {
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.Me(c.uid, time.Now()), nil
	})
	return http.StatusOK, body, e
}

func handleListRequests(s *Server, c *call) (int, []byte, *AppError) {
	q := c.r.URL.Query()
	limit, offset, e := ParseLimitOffset(q)
	if e != nil {
		return 0, nil, e
	}
	direction, status := filterParam(q, "direction"), filterParam(q, "status")
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.ListRequests(c.uid, direction, status, limit, offset)
	})
	return http.StatusOK, body, e
}

func handleActivity(s *Server, c *call) (int, []byte, *AppError) {
	limit, offset, e := ParseLimitOffset(c.r.URL.Query())
	if e != nil {
		return 0, nil, e
	}
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.Activity(c.uid, limit, offset), nil
	})
	return http.StatusOK, body, e
}
