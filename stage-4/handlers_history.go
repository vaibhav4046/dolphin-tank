package main

import (
	"net/http"
	"net/url"
	"slices"
	"strings"
	"time"
)

// historyQuery parses the query string and treats a malformed percent-escape or semicolon in
// one of the named parameters as an invalid value (422) instead of letting net/url drop the
// pair and read the parameter as absent. Unrecognized parameters stay ignored.
func historyQuery(r *http.Request, names ...string) (url.Values, *AppError) {
	q, err := url.ParseQuery(r.URL.RawQuery)
	if err == nil {
		return q, nil
	}
	for _, pair := range strings.Split(r.URL.RawQuery, "&") {
		rawKey, rawValue, _ := strings.Cut(pair, "=")
		key, kerr := url.QueryUnescape(rawKey)
		if kerr != nil || !slices.Contains(names, key) {
			continue
		}
		if _, verr := url.QueryUnescape(rawValue); verr != nil || strings.Contains(pair, ";") {
			return nil, errValidation(key + " is not a valid value")
		}
	}
	return q, nil
}

// optionalParam is nil when the parameter is absent and points at "" when it is present but empty.
func optionalParam(q url.Values, name string) *string {
	vs, present := q[name]
	if !present {
		return nil
	}
	return &vs[0]
}

func handleMe(s *Server, c *call) (int, []byte, *AppError) {
	q, e := historyQuery(c.r, "as_of", "known_at")
	if e != nil {
		return 0, nil, e
	}
	mq := MeQuery{AsOf: optionalParam(q, "as_of"), KnownAt: optionalParam(q, "known_at")}
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.MeAt(c.uid, mq, time.Now())
	})
	return http.StatusOK, body, e
}

func handleStatement(s *Server, c *call) (int, []byte, *AppError) {
	q, e := historyQuery(c.r, "from", "to", "known_at", "snapshot", "limit", "offset")
	if e != nil {
		return 0, nil, e
	}
	limit, offset, e := ParseLimitOffset(q)
	if e != nil {
		return 0, nil, e
	}
	sq := StatementQuery{
		From: optionalParam(q, "from"), To: optionalParam(q, "to"),
		KnownAt: optionalParam(q, "known_at"), Snapshot: optionalParam(q, "snapshot"),
		Limit: limit, Offset: offset,
	}
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.Statement(c.uid, sq, time.Now())
	})
	return http.StatusOK, body, e
}

func handleCorrect(s *Server, c *call) (int, []byte, *AppError) {
	return s.idempotentWrite(c, false, func(st *State, obj map[string]any) (any, *AppError) {
		in, e := ParseCorrectionBody(obj)
		if e != nil {
			return nil, e
		}
		rev, e := st.Correct(c.uid, c.id, in, time.Now())
		if e != nil {
			return nil, e
		}
		return rev, nil
	})
}

func handlePaymentRevisions(s *Server, c *call) (int, []byte, *AppError) {
	body, e := s.store.Exec(func(st *State) (any, *AppError) {
		return st.PaymentRevisions(c.uid, c.id)
	})
	return http.StatusOK, body, e
}
