package main

import (
	"encoding/json"
	"testing"
)

func TestCanonBody(t *testing.T) {
	same := [][2]string{
		{`{"a":1000}`, `{"a":1000.0}`},
		{`{"a":1000}`, `{"a":1e3}`},
		{`{"a":1000}`, `{"a":10e2}`},
		{`{"a":1000}`, `{"a":0.1E4}`},
		{`{"a":0}`, `{"a":-0}`},
		{`{"a":0}`, `{"a":0.000e9}`},
		{`{"a":1,"b":[1,{"c":2,"d":3}]}`, `{ "b" : [ 1.0 , { "d":3, "c":2 } ] , "a":1 }`},
		{`{"a":1e999999999999}`, `{"a":10e999999999998}`},
	}
	for _, p := range same {
		if a, b := trCanonBody(ttBody(t, p[0])), trCanonBody(ttBody(t, p[1])); a != b {
			t.Errorf("%s vs %s should match: %q %q", p[0], p[1], a, b)
		}
	}
	diff := [][2]string{
		{`{"a":1000}`, `{"a":1001}`},
		{`{"a":1}`, `{"a":1.0000000000000001}`},
		{`{"a":"x"}`, `{"a":"X"}`},
		{`{"a":1}`, `{"a":"1"}`},
		{`{"a":null}`, `{"a":false}`},
		{`{"a":[1,2]}`, `{"a":[2,1]}`},
		{`{"a":1e999999999999}`, `{"a":1e999999999998}`},
		{`{}`, `{"visibility":"public"}`},
		{`{"a":-1}`, `{"a":1}`},
	}
	for _, p := range diff {
		if a, b := trCanonBody(ttBody(t, p[0])), trCanonBody(ttBody(t, p[1])); a == b {
			t.Errorf("%s vs %s must differ, both gave %q", p[0], p[1], a)
		}
	}
}

func TestIntFromNumber(t *testing.T) {
	ok := map[string]int64{
		"1e3": 1000, "1000.0": 1000, "0": 0, "-0": 0, "0.0": 0, "10e-1": 1, "9223372036854775807": 9223372036854775807,
		"-9223372036854775808": -9223372036854775808, "12E0": 12, "-5": -5,
	}
	for in, want := range ok {
		if got, good := trIntFromNumber(json.Number(in)); !good || got != want {
			t.Errorf("%s: got %d,%v want %d", in, got, good, want)
		}
	}
	for _, in := range []string{"1.5", "1e-1", "1e19", "9223372036854775808", "1e999999999999", "0.5", "-9223372036854775809"} {
		if got, good := trIntFromNumber(json.Number(in)); good {
			t.Errorf("%s should not be an int64, got %d", in, got)
		}
	}
}
