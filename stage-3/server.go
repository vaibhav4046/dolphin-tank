package main

import (
	"log"
	"net/http"
	"runtime/debug"
	"strings"
)

// Server is the HTTP layer. It owns no state: every read and write of service
// state goes through Store, whose single global mutex serialises them all.
type Server struct {
	store *Store
}

// call is one routed request after resolution and (for private routes) auth.
type call struct {
	w   http.ResponseWriter
	r   *http.Request
	uid string // authenticated user id; empty on public routes
	id  string // {id} path segment for /requests/{id}/...
}

// NewServer returns the full handler: routing, auth, envelope, panic recovery.
func NewServer(store *Store) http.Handler {
	return recoverPanics(&Server{store: store})
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if serveUI(w, r) {
		return
	}
	rt, id, ok := resolve(r.Method, r.URL.Path)
	if !ok {
		writeErr(w, NewErr(http.StatusNotFound, "not_found", "no such route"))
		return
	}
	c := &call{w: w, r: r, id: id}
	if !rt.public {
		uid, e := s.authenticate(r)
		if e != nil {
			writeErr(w, e)
			return
		}
		c.uid = uid
	}
	status, body, e := rt.handle(s, c)
	if e != nil {
		writeErr(w, e)
		return
	}
	writeBody(w, status, body)
}

func (s *Server) authenticate(r *http.Request) (string, *AppError) {
	token, ok := bearerToken(r.Header.Get("Authorization"))
	if !ok {
		return "", NewErr(http.StatusUnauthorized, "unauthenticated", "missing or malformed bearer token")
	}
	return s.store.Authenticate(token)
}

func bearerToken(header string) (string, bool) {
	scheme, token, found := strings.Cut(header, " ")
	if !found || !strings.EqualFold(scheme, "Bearer") {
		return "", false
	}
	token = strings.TrimSpace(token)
	return token, token != ""
}

func recoverPanics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			rec := recover()
			if rec == nil {
				return
			}
			if rec == http.ErrAbortHandler {
				panic(rec)
			}
			log.Printf("panic serving %s %s: %v\n%s", r.Method, r.URL.Path, rec, debug.Stack())
			writeErr(w, NewErr(http.StatusInternalServerError, "internal_error", "internal error"))
		}()
		next.ServeHTTP(w, r)
	})
}
