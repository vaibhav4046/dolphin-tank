package main

import "net/http"

func handleSignup(s *Server, c *call) (int, []byte, *AppError) {
	obj, e := readObject(c.w, c.r, false)
	if e != nil {
		return 0, nil, e
	}
	email, e := ReqString(obj, "email")
	if e != nil {
		return 0, nil, e
	}
	password, e := ReqString(obj, "password")
	if e != nil {
		return 0, nil, e
	}
	displayName, e := ReqString(obj, "display_name")
	if e != nil {
		return 0, nil, e
	}
	body, e := s.store.Signup(email, password, displayName)
	return http.StatusCreated, body, e
}

func handleLogin(s *Server, c *call) (int, []byte, *AppError) {
	obj, e := readObject(c.w, c.r, false)
	if e != nil {
		return 0, nil, e
	}
	email, e := ReqString(obj, "email")
	if e != nil {
		return 0, nil, e
	}
	password, e := ReqString(obj, "password")
	if e != nil {
		return 0, nil, e
	}
	body, e := s.store.Login(email, password)
	return http.StatusOK, body, e
}
