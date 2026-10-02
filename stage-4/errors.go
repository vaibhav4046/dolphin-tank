package main

import (
	"bytes"
	"encoding/json"
	"time"
)

// AppError is the single error type the domain returns; the HTTP layer renders it.
type AppError struct {
	Status  int
	Code    string
	Message string
}

func (e *AppError) Error() string { return e.Code + ": " + e.Message }

func NewErr(status int, code, msg string) *AppError {
	return &AppError{Status: status, Code: code, Message: msg}
}

func errValidation(msg string) *AppError { return NewErr(422, "validation_failed", msg) }
func errMalformed(msg string) *AppError  { return NewErr(400, "malformed_request", msg) }
func errNotFound(msg string) *AppError   { return NewErr(404, "not_found", msg) }
func errForbidden(msg string) *AppError  { return NewErr(403, "forbidden", msg) }
func errUnauthenticated() *AppError {
	return NewErr(401, "unauthenticated", "missing, malformed or unknown bearer token")
}

// MarshalJSON is the only JSON encoder: no HTML escaping, no trailing newline.
func MarshalJSON(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// FormatTime renders RFC 3339 in UTC, whole seconds, with an explicit "+00:00" offset (never "Z").
func FormatTime(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05-07:00")
}
