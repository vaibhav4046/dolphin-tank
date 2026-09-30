package main

import (
	"encoding/json"
	"net/url"
	"strings"
	"testing"
)

func fgObj(t *testing.T, s string) map[string]any {
	t.Helper()
	dec := json.NewDecoder(strings.NewReader(s))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		t.Fatal(err)
	}
	return m
}

func fgWantErr(t *testing.T, what string, e *AppError, status int, code string) {
	t.Helper()
	if e == nil || e.Status != status || e.Code != code {
		t.Fatalf("%s: want %d %s, got %v", what, status, code, e)
	}
}

func TestForgeReqAmount(t *testing.T) {
	good := map[string]int64{
		`1000`: 1000, `1000.0`: 1000, `1e3`: 1000, `1E3`: 1000, `1e+3`: 1000, `1.0e3`: 1000,
		`0.1e4`: 1000, `100000e-2`: 1000, `1`: 1, `1000000000`: 1_000_000_000, `1e9`: 1_000_000_000,
	}
	for lit, want := range good {
		got, e := ReqAmount(fgObj(t, `{"amount":`+lit+`}`), "amount")
		if e != nil || got != want {
			t.Errorf("%s: got %d, %v want %d", lit, got, e, want)
		}
	}
	for _, lit := range []string{`"1000"`, `true`, `false`, `null`, `[]`, `{}`, `1.5`, `0`, `0.0`, `-5`, `-0`,
		`1000000001`, `1e10`, `1e-1`, `1e999999999`, `1e-999999999`, `99999999999999999999`,
		`1000.0000000000000000000001`} {
		_, e := ReqAmount(fgObj(t, `{"amount":`+lit+`}`), "amount")
		fgWantErr(t, lit, e, 422, "validation_failed")
	}
	_, e := ReqAmount(fgObj(t, `{}`), "amount")
	fgWantErr(t, "missing", e, 422, "validation_failed")
}

func TestForgeReqString(t *testing.T) {
	if s, e := ReqString(fgObj(t, `{"a":"x"}`), "a"); e != nil || s != "x" {
		t.Fatal(s, e)
	}
	_, e := ReqString(fgObj(t, `{}`), "a")
	fgWantErr(t, "missing", e, 422, "validation_failed")
	for _, lit := range []string{`null`, `5`, `true`, `[]`, `{}`} {
		_, e = ReqString(fgObj(t, `{"a":`+lit+`}`), "a")
		fgWantErr(t, lit, e, 400, "malformed_request")
	}
}

func TestForgeOptNoteAndVisibility(t *testing.T) {
	if n, e := OptNote(fgObj(t, `{}`)); e != nil || n != "" {
		t.Fatal(n, e)
	}
	verbatim := " <b>é😀  "
	b, _ := json.Marshal(map[string]string{"note": verbatim})
	if n, e := OptNote(fgObj(t, string(b))); e != nil || n != verbatim {
		t.Fatalf("not verbatim: %q %v", n, e)
	}
	emoji200 := strings.Repeat("😀", 200)
	if _, e := OptNote(map[string]any{"note": emoji200}); e != nil {
		t.Fatal(e)
	}
	_, e := OptNote(map[string]any{"note": emoji200 + "x"})
	fgWantErr(t, "201 runes", e, 422, "validation_failed")
	for _, lit := range []string{`null`, `5`, `true`, `[]`} {
		_, e = OptNote(fgObj(t, `{"note":`+lit+`}`))
		fgWantErr(t, "note "+lit, e, 422, "validation_failed")
	}

	if v, e := OptVisibility(fgObj(t, `{}`)); e != nil || v != "public" {
		t.Fatal(v, e)
	}
	if v, e := OptVisibility(fgObj(t, `{"visibility":"private"}`)); e != nil || v != "private" {
		t.Fatal(v, e)
	}
	for _, lit := range []string{`null`, `"PUBLIC"`, `""`, `"friends"`, `1`, `true`} {
		_, e = OptVisibility(fgObj(t, `{"visibility":`+lit+`}`))
		fgWantErr(t, "visibility "+lit, e, 422, "validation_failed")
	}
}

func TestForgeReqHandles(t *testing.T) {
	if hs, e := ReqHandles(fgObj(t, `{"h":["a","b"]}`), "h"); e != nil || len(hs) != 2 || hs[1] != "b" {
		t.Fatal(hs, e)
	}
	_, e := ReqHandles(fgObj(t, `{}`), "h")
	fgWantErr(t, "missing", e, 422, "validation_failed")
	for _, lit := range []string{`"ada"`, `null`, `5`, `{}`, `[1]`, `["a",null]`, `["a",["b"]]`} {
		_, e = ReqHandles(fgObj(t, `{"h":`+lit+`}`), "h")
		fgWantErr(t, lit, e, 400, "malformed_request")
	}
	for _, lit := range []string{`[]`, `["a","a"]`, `["a","b","a"]`} {
		_, e = ReqHandles(fgObj(t, `{"h":`+lit+`}`), "h")
		fgWantErr(t, lit, e, 422, "validation_failed")
	}
}

func TestForgeCheckIdemKey(t *testing.T) {
	fgWantErr(t, "empty", CheckIdemKey(""), 400, "missing_idempotency_key")
	fgWantErr(t, "256", CheckIdemKey(strings.Repeat("k", 256)), 422, "validation_failed")
	for _, k := range []string{"k", strings.Repeat("k", 255), strings.Repeat("é", 255)} {
		if e := CheckIdemKey(k); e != nil {
			t.Fatalf("%d runes: %v", len([]rune(k)), e)
		}
	}
}

func TestForgeParseLimitOffset(t *testing.T) {
	ok := map[string][2]int{
		"": {50, 0}, "limit=1": {1, 0}, "limit=200&offset=0": {200, 0}, "limit=007": {7, 0},
		"offset=12": {50, 12}, "limit=10&offset=99999999999999999999": {10, pageClamp}, "unknown=1e9": {50, 0},
	}
	for raw, want := range ok {
		q, _ := url.ParseQuery(raw)
		l, o, e := ParseLimitOffset(q)
		if e != nil || l != want[0] || o != want[1] {
			t.Errorf("%q: got %d %d %v want %v", raw, l, o, e, want)
		}
	}
	for _, raw := range []string{"limit=1e9", "limit=4.0", "limit=%2B4", "limit=+4", "limit=-1", "limit=0", "limit=201",
		"limit=", "limit=abc", "limit=%204", "offset=-1", "offset=1e1", "offset=4.0", "offset=%2B4", "offset=",
		"limit=99999999999999999999", "limit=%D9%A4"} {
		q, _ := url.ParseQuery(raw)
		_, _, e := ParseLimitOffset(q)
		fgWantErr(t, raw, e, 422, "validation_failed")
	}
}
