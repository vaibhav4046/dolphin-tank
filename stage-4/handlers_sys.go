package main

import "net/http"

var healthBody = []byte(`{"status":"ok"}`)

// Health never touches the store, so it answers even while a reset holds the lock.
func handleHealth(_ *Server, _ *call) (int, []byte, *AppError) {
	return http.StatusOK, healthBody, nil
}

func handleReset(s *Server, c *call) (int, []byte, *AppError) {
	raw, e := readBody(c.w, c.r, maxTestBodyBytes)
	if e != nil {
		return 0, nil, e
	}
	if e := s.store.Reset(raw); e != nil {
		return 0, nil, e
	}
	return http.StatusNoContent, nil, nil
}

func handleExport(s *Server, _ *call) (int, []byte, *AppError) {
	body, e := s.store.Export()
	return http.StatusOK, body, e
}

func handleImport(s *Server, c *call) (int, []byte, *AppError) {
	raw, e := readBody(c.w, c.r, maxTestBodyBytes)
	if e != nil {
		return 0, nil, e
	}
	if e := s.store.Import(raw); e != nil {
		return 0, nil, e
	}
	return http.StatusNoContent, nil, nil
}
