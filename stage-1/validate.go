package main

import (
	"encoding/json"
	"math"
	"net/url"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	maxAmount       = 1_000_000_000
	maxNoteRunes    = 200
	maxIdemKeyRunes = 255
	defaultLimit    = 50
	maxLimit        = 200
	pageClamp       = math.MaxInt32 // offsets beyond this cannot match any list
)

// Field validators work on a JSON object decoded with UseNumber (numbers are json.Number).

func ReqString(obj map[string]any, field string) (string, *AppError) {
	v, ok := obj[field]
	if !ok {
		return "", errValidation(field + " is required")
	}
	s, ok := v.(string)
	if !ok {
		return "", errMalformed(field + " must be a string")
	}
	return s, nil
}

func ReqAmount(obj map[string]any, field string) (int64, *AppError) {
	v, ok := obj[field]
	if !ok {
		return 0, errValidation(field + " is required")
	}
	var lit string
	switch n := v.(type) {
	case json.Number:
		lit = n.String()
	case float64:
		lit = strconv.FormatFloat(n, 'f', -1, 64)
	default:
		return 0, errValidation(field + " must be an integer number of minor units")
	}
	a, ok := exactAmount(lit)
	if !ok {
		return 0, errValidation(field + " must be an integer between 1 and 1000000000")
	}
	return a, nil
}

// exactAmount reads a JSON number literal as a decimal without floating point:
// 1000, 1000.0 and 1e3 are all 1000. ok is false for non-integral or out-of-range values.
func exactAmount(lit string) (int64, bool) {
	if lit == "" || lit[0] == '-' {
		return 0, false
	}
	mant, exps := lit, ""
	if i := strings.IndexAny(lit, "eE"); i >= 0 {
		mant, exps = lit[:i], lit[i+1:]
	}
	intPart, frac, _ := strings.Cut(mant, ".")
	digits := intPart + frac
	exp10 := -len(frac)
	if exps != "" {
		sign := 1
		switch exps[0] {
		case '+':
			exps = exps[1:]
		case '-':
			sign = -1
			exps = exps[1:]
		}
		exps = strings.TrimLeft(exps, "0")
		if len(exps) > 6 {
			return 0, false // far outside 1..1e9 in either direction
		}
		if exps != "" {
			e, err := strconv.Atoi(exps)
			if err != nil {
				return 0, false
			}
			exp10 += sign * e
		}
	}
	digits = strings.TrimLeft(digits, "0")
	if digits == "" {
		return 0, false
	}
	for i := 0; i < len(digits); i++ {
		if digits[i] < '0' || digits[i] > '9' {
			return 0, false
		}
	}
	trimmed := strings.TrimRight(digits, "0")
	exp10 += len(digits) - len(trimmed)
	digits = trimmed
	if exp10 < 0 || len(digits)+exp10 > 10 {
		return 0, false
	}
	v, err := strconv.ParseInt(digits, 10, 64)
	if err != nil {
		return 0, false
	}
	for i := 0; i < exp10; i++ {
		v *= 10
	}
	return v, v >= 1 && v <= maxAmount
}

func OptNote(obj map[string]any) (string, *AppError) {
	v, ok := obj["note"]
	if !ok {
		return "", nil
	}
	s, ok := v.(string)
	if !ok {
		return "", errValidation("note must be a string")
	}
	if utf8.RuneCountInString(s) > maxNoteRunes {
		return "", errValidation("note must be at most 200 characters")
	}
	return s, nil
}

func OptVisibility(obj map[string]any) (string, *AppError) {
	v, ok := obj["visibility"]
	if !ok {
		return visPublic, nil
	}
	if s, isStr := v.(string); isStr && (s == visPublic || s == visPrivate) {
		return s, nil
	}
	return "", errValidation("visibility must be public or private")
}

func ReqHandles(obj map[string]any, field string) ([]string, *AppError) {
	v, ok := obj[field]
	if !ok {
		return nil, errValidation(field + " is required")
	}
	arr, ok := v.([]any)
	if !ok {
		return nil, errMalformed(field + " must be an array of strings")
	}
	out := make([]string, 0, len(arr))
	for _, e := range arr {
		s, ok := e.(string)
		if !ok {
			return nil, errMalformed(field + " must be an array of strings")
		}
		out = append(out, s)
	}
	if len(out) == 0 {
		return nil, errValidation(field + " must not be empty")
	}
	seen := make(map[string]struct{}, len(out))
	for _, h := range out {
		if _, dup := seen[h]; dup {
			return nil, errValidation(field + " must not contain duplicates")
		}
		seen[h] = struct{}{}
	}
	return out, nil
}

func CheckIdemKey(k string) *AppError {
	if k == "" {
		return NewErr(400, "missing_idempotency_key", "Idempotency-Key header is required")
	}
	if utf8.RuneCountInString(k) > maxIdemKeyRunes {
		return errValidation("Idempotency-Key must be 1 to 255 characters")
	}
	return nil
}

func ParseLimitOffset(q url.Values) (limit, offset int, e *AppError) {
	if limit, e = queryInt(q, "limit", defaultLimit); e != nil {
		return 0, 0, e
	}
	if offset, e = queryInt(q, "offset", 0); e != nil {
		return 0, 0, e
	}
	if limit < 1 || limit > maxLimit {
		return 0, 0, errValidation("limit must be between 1 and 200")
	}
	return limit, offset, nil
}

// queryInt accepts plain ASCII decimal digits only: no sign, point, exponent or spaces.
func queryInt(q url.Values, name string, def int) (int, *AppError) {
	vs, present := q[name]
	if !present {
		return def, nil
	}
	s := vs[0]
	if s == "" {
		return 0, errValidation(name + " must be a non-negative integer")
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return 0, errValidation(name + " must be a non-negative integer")
		}
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil || n > pageClamp { // all digits, so err can only be overflow
		n = pageClamp
	}
	return int(n), nil
}
