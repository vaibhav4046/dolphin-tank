package main

import (
	"encoding/json"
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	maxReasonRunes     = 200
	maxRevisionLiteral = 64 // longer number literals cannot be a believable revision number
)

// ParseCorrectionBody reads the four required fields in spec order; the first error wins.
// Every wrong, missing or mistyped field is 422 validation_failed.
func ParseCorrectionBody(obj map[string]any) (CorrectionIn, *AppError) {
	var in CorrectionIn
	rev, e := reqRevisionNumber(obj, "expected_revision")
	if e != nil {
		return in, e
	}
	amount, e := reqCorrectionAmount(obj, "amount")
	if e != nil {
		return in, e
	}
	effective, e := reqInstantField(obj, "effective_at")
	if e != nil {
		return in, e
	}
	reason, e := reqReason(obj, "reason")
	if e != nil {
		return in, e
	}
	in.ExpectedRevision, in.Amount, in.EffectiveAt, in.Reason = rev, amount, effective, reason
	return in, nil
}

// numberLiteral returns the exact text of a decoded JSON number; anything else is not a number.
func numberLiteral(v any) (string, bool) {
	switch n := v.(type) {
	case json.Number:
		return n.String(), true
	case float64:
		return strconv.FormatFloat(n, 'f', -1, 64), true
	}
	return "", false
}

// reqCorrectionAmount follows ReqAmount's exact-integer rules but admits zero (a full reversal).
func reqCorrectionAmount(obj map[string]any, field string) (int64, *AppError) {
	v, ok := obj[field]
	if !ok {
		return 0, errValidation(field + " is required")
	}
	bad := errValidation(field + " must be an integer between 0 and 1000000000")
	lit, ok := numberLiteral(v)
	if !ok {
		return 0, bad
	}
	if isZeroLiteral(lit) {
		return 0, nil
	}
	a, ok := exactAmount(lit)
	if !ok {
		return 0, bad
	}
	return a, nil
}

// isZeroLiteral is true for 0, 0.0, -0 and 0e9: numerically zero, so an integer in range.
func isZeroLiteral(lit string) bool {
	mant, _, _ := strings.Cut(strings.TrimPrefix(lit, "-"), "e")
	mant, _, _ = strings.Cut(mant, "E")
	digits := strings.Replace(mant, ".", "", 1)
	return digits != "" && strings.Trim(digits, "0") == ""
}

// reqRevisionNumber reads a positive integer. Beyond int64 it clamps to MaxInt64, which no real
// revision equals, so the domain answers stale_revision rather than the parser answering 422.
func reqRevisionNumber(obj map[string]any, field string) (int64, *AppError) {
	v, ok := obj[field]
	if !ok {
		return 0, errValidation(field + " is required")
	}
	bad := errValidation(field + " must be a positive integer")
	lit, ok := numberLiteral(v)
	if !ok {
		return 0, bad
	}
	if a, ok := exactAmount(lit); ok {
		return a, nil
	}
	if len(lit) > maxRevisionLiteral || strings.HasPrefix(lit, "-") {
		return 0, bad
	}
	r, ok := new(big.Rat).SetString(lit)
	if !ok || !r.IsInt() || r.Sign() <= 0 {
		return 0, bad
	}
	if n := r.Num(); n.IsInt64() {
		return n.Int64(), nil
	}
	return math.MaxInt64, nil
}

func reqInstantField(obj map[string]any, field string) (string, *AppError) {
	v, ok := obj[field]
	if !ok {
		return "", errValidation(field + " is required")
	}
	s, isStr := v.(string)
	if !isStr {
		return "", errValidation(field + " must be an RFC 3339 instant with an offset")
	}
	if _, ok := ParseInstant(s); !ok {
		return "", errValidation(field + " must be an RFC 3339 instant with an offset")
	}
	return s, nil
}

func reqReason(obj map[string]any, field string) (string, *AppError) {
	v, ok := obj[field]
	if !ok {
		return "", errValidation(field + " is required")
	}
	s, isStr := v.(string)
	if !isStr {
		return "", errValidation(field + " must be a string")
	}
	if n := utf8.RuneCountInString(s); n < 1 || n > maxReasonRunes {
		return "", errValidation(field + " must be 1 to 200 characters")
	}
	return s, nil
}
