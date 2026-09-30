package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"unicode/utf8"
)

const (
	maxBodyBytes     = 1 << 20   // every route except the two below
	maxTestBodyBytes = 256 << 20 // /_test/reset and /_test/import
)

func malformed(msg string) *AppError { return NewErr(http.StatusBadRequest, "malformed_request", msg) }

func readBody(w http.ResponseWriter, r *http.Request, limit int64) ([]byte, *AppError) {
	b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, limit))
	if err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			return nil, malformed("request body too large")
		}
		return nil, malformed("request body could not be read")
	}
	return b, nil
}

// parseObject accepts exactly one JSON object, numbers kept exact as json.Number.
// An empty body is {} only when allowEmpty.
func parseObject(b []byte, allowEmpty bool) (map[string]any, *AppError) {
	if !utf8.Valid(b) {
		return nil, malformed("request body is not valid UTF-8")
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		if errors.Is(err, io.EOF) && allowEmpty {
			return map[string]any{}, nil
		}
		return nil, malformed("request body is not valid JSON")
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, malformed("request body must be a single JSON value")
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return nil, malformed("request body must be a JSON object")
	}
	return obj, nil
}

func readObject(w http.ResponseWriter, r *http.Request, allowEmpty bool) (map[string]any, *AppError) {
	b, e := readBody(w, r, maxBodyBytes)
	if e != nil {
		return nil, e
	}
	return parseObject(b, allowEmpty)
}
