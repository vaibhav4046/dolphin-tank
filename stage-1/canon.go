package main

import (
	"encoding/json"
	"math/big"
	"sort"
	"strconv"
	"strings"
)

// trCanonBody renders a parsed JSON object so that two bodies that are the same
// JSON value give the same string: keys sorted, whitespace gone, numbers
// compared by exact value (1000 == 1000.0 == 1e3), strings compared exactly.
func trCanonBody(body map[string]any) string {
	var sb strings.Builder
	trCanon(&sb, body)
	return sb.String()
}

func trCanon(sb *strings.Builder, v any) {
	switch x := v.(type) {
	case nil:
		sb.WriteString("null")
	case bool:
		sb.WriteString(strconv.FormatBool(x))
	case string:
		b, _ := json.Marshal(x)
		sb.Write(b)
	case json.Number:
		sb.WriteString(trCanonNumber(x.String()))
	case float64:
		sb.WriteString(trCanonNumber(strconv.FormatFloat(x, 'e', -1, 64)))
	case []any:
		sb.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				sb.WriteByte(',')
			}
			trCanon(sb, e)
		}
		sb.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		sb.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				sb.WriteByte(',')
			}
			kb, _ := json.Marshal(k)
			sb.Write(kb)
			sb.WriteByte(':')
			trCanon(sb, x[k])
		}
		sb.WriteByte('}')
	default:
		b, _ := json.Marshal(x)
		sb.Write(b)
	}
}

// trDecomp splits a JSON number into sign, significant digits (no leading or
// trailing zeros) and a base-10 exponent, so value = digits * 10^exp. Zero is
// digits "". The exponent is a big.Int because JSON allows e999999999999.
func trDecomp(s string) (neg bool, digits string, exp *big.Int, ok bool) {
	if strings.HasPrefix(s, "-") {
		neg, s = true, s[1:]
	}
	mant, expStr := s, "0"
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		mant, expStr = s[:i], s[i+1:]
	}
	intPart, frac := mant, ""
	if i := strings.IndexByte(mant, '.'); i >= 0 {
		intPart, frac = mant[:i], mant[i+1:]
	}
	exp, ok = new(big.Int).SetString(expStr, 10)
	if !ok || intPart == "" {
		return false, "", nil, false
	}
	exp.Sub(exp, big.NewInt(int64(len(frac))))
	digits = strings.TrimLeft(intPart+frac, "0")
	trimmed := strings.TrimRight(digits, "0")
	exp.Add(exp, big.NewInt(int64(len(digits)-len(trimmed))))
	if trimmed == "" {
		return false, "", big.NewInt(0), true
	}
	return neg, trimmed, exp, true
}

func trCanonNumber(s string) string {
	neg, digits, exp, ok := trDecomp(s)
	if !ok {
		return s
	}
	if digits == "" {
		return "0"
	}
	sign := ""
	if neg {
		sign = "-"
	}
	return sign + digits + "e" + exp.String()
}

// trIntFromNumber returns the exact int64 value of a JSON number; false when it
// is not integral or does not fit. No float64 is involved.
func trIntFromNumber(n json.Number) (int64, bool) {
	neg, digits, exp, ok := trDecomp(n.String())
	if !ok {
		return 0, false
	}
	if digits == "" {
		return 0, true
	}
	if exp.Sign() < 0 || !exp.IsInt64() || exp.Int64() > 19 {
		return 0, false
	}
	full := digits + strings.Repeat("0", int(exp.Int64()))
	if neg {
		full = "-" + full
	}
	v, err := strconv.ParseInt(full, 10, 64)
	return v, err == nil
}
