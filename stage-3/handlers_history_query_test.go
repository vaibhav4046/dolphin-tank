package main

import (
	"net/url"
	"regexp"
	"testing"
	"time"
)

var snapshotToken = regexp.MustCompile(`^snap_[0-9a-f]{32}$`)

// acceptedInstants and refusedRaw are the forms every instant parameter must accept or refuse.
var (
	acceptedInstants = []string{
		"2026-09-24T13:20:00Z", "2026-09-24T13:20:00z", "2026-09-24T13:20:00+02:00",
		"2026-09-24T13:20:00-05:30", "2026-09-24T13:20:00.5Z", "2026-09-24T13:20:00.123456+00:00",
	}
	refusedRaw = []string{
		"", "2026-09-24T13:20:00", "2026-09-24", "2026-09-24 13:20:00Z", "2026-09-24T13:20:00Z junk",
		"2026-09-24T13:20:00+02:00 ", "yesterday", "1790000000", "2026-13-24T13:20:00Z",
	}
	// A valid offset sent with a bare "+" arrives as a space and must be refused, never repaired.
	barePlus = "2026-09-24T13:20:00+02:00"
)

func queryOf(name, value string) string { return name + "=" + url.QueryEscape(value) }

func TestMeInstantParsing(t *testing.T) {
	e := newHistoryEnv(t)
	for _, name := range []string{"as_of", "known_at"} {
		for _, v := range acceptedInstants {
			rec := do(e.h, "GET", "/me?"+queryOf(name, v), "", e.ada)
			body := decode(t, rec.Body.Bytes())
			if rec.Code != 200 || body[name] != v {
				t.Errorf("%s=%q: %d %s, want 200 echoing it verbatim", name, v, rec.Code, rec.Body)
			}
			other := map[string]string{"as_of": "known_at", "known_at": "as_of"}[name]
			if _, present := body[other]; present {
				t.Errorf("%s=%q: %s must not be echoed unless supplied", name, v, other)
			}
		}
		for _, v := range refusedRaw {
			wantErr(t, name+"="+v, do(e.h, "GET", "/me?"+queryOf(name, v), "", e.ada), 422, "validation_failed")
		}
		wantErr(t, name+" bare plus", do(e.h, "GET", "/me?"+name+"="+barePlus, "", e.ada), 422, "validation_failed")
		for _, raw := range []string{"%zz", "%", "2026-09-24T13:20:00Z%2"} {
			wantErr(t, name+" malformed escape "+raw, do(e.h, "GET", "/me?"+name+"="+raw, "", e.ada), 422, "validation_failed")
		}
	}
	plain := do(e.h, "GET", "/me", "", e.ada)
	extra := do(e.h, "GET", "/me?foo=bar&limit=zzz&from=nonsense", "", e.ada)
	if plain.Code != 200 || extra.Code != 200 || plain.Body.String() != extra.Body.String() {
		t.Errorf("unrecognized parameters must be ignored: %d %s vs %d %s", plain.Code, plain.Body, extra.Code, extra.Body)
	}
	both := decode(t, do(e.h, "GET", "/me?as_of=2026-09-24T13:20:00Z&known_at=2026-09-24T13:21:00%2B02:00", "", e.ada).Body.Bytes())
	if both["as_of"] != "2026-09-24T13:20:00Z" || both["known_at"] != "2026-09-24T13:21:00+02:00" {
		t.Errorf("both parameters echoed: %v", both)
	}
}

func TestMeAsOfBoundaries(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	created, ok := ParseInstant(p["created_at"].(string))
	if !ok {
		t.Fatalf("created_at %v", p["created_at"])
	}
	at := func(q string) map[string]any {
		t.Helper()
		rec := do(e.h, "GET", "/me?"+q, "", e.ada)
		if rec.Code != 200 {
			t.Fatalf("/me?%s: %d %s", q, rec.Code, rec.Body)
		}
		return decode(t, rec.Body.Bytes())
	}
	micro := func(d time.Duration) string { return FormatMicro(created.Add(d)) }
	for _, c := range []struct {
		name, query string
		balance     float64
	}{
		{"exactly at the payment counts", queryOf("as_of", micro(0)), 9000},
		{"one microsecond before is the opening balance", queryOf("as_of", micro(-time.Microsecond)), 10000},
		{"far past is the opening balance", queryOf("as_of", "1970-01-01T00:00:00Z"), 10000},
		{"far future is the current balance", queryOf("as_of", "2999-01-01T00:00:00Z"), 9000},
		{"known before the payment was recorded", queryOf("known_at", micro(-time.Microsecond)) + "&" + queryOf("as_of", "2999-01-01T00:00:00Z"), 10000},
		{"known when it was recorded", queryOf("known_at", micro(0)) + "&" + queryOf("as_of", "2999-01-01T00:00:00Z"), 9000},
	} {
		got := at(c.query)
		if got["balance"] != c.balance || got["total"] != c.balance || got["available"] != c.balance || got["held"] != float64(0) {
			t.Errorf("%s: %v, want balance=total=available=%v held=0", c.name, got, c.balance)
		}
	}
}

func TestStatementQueryValidation(t *testing.T) {
	e := newHistoryEnv(t)
	for _, name := range []string{"from", "to", "known_at"} {
		for _, v := range acceptedInstants {
			if rec := do(e.h, "GET", "/statement?"+queryOf(name, v), "", e.ada); rec.Code != 200 {
				t.Errorf("%s=%q: %d %s", name, v, rec.Code, rec.Body)
			}
		}
		for _, v := range refusedRaw {
			wantErr(t, name+"="+v, do(e.h, "GET", "/statement?"+queryOf(name, v), "", e.ada), 422, "validation_failed")
		}
		wantErr(t, name+" bare plus", do(e.h, "GET", "/statement?"+name+"="+barePlus, "", e.ada), 422, "validation_failed")
		wantErr(t, name+" malformed escape", do(e.h, "GET", "/statement?"+name+"=%zz", "", e.ada), 422, "validation_failed")
	}
	for _, q := range []string{"limit=0", "limit=201", "limit=-1", "limit=abc", "limit=", "offset=-1", "offset=1.5", "offset=", "limit=1e1"} {
		wantErr(t, q, do(e.h, "GET", "/statement?"+q, "", e.ada), 422, "validation_failed")
	}
	wantErr(t, "from after to", do(e.h, "GET", "/statement?from=2026-09-25T00:00:00Z&to=2026-09-24T00:00:00Z", "", e.ada), 422, "validation_failed")
	if rec := do(e.h, "GET", "/statement?from=2026-09-24T00:00:00Z&to=2026-09-24T00:00:00Z", "", e.ada); rec.Code != 200 {
		t.Errorf("from == to is an empty window, not an error: %d %s", rec.Code, rec.Body)
	}
	if rec := do(e.h, "GET", "/statement?foo=bar&limit=5&offset=0&bar=%zz", "", e.ada); rec.Code != 200 {
		t.Errorf("unrecognized parameters must be ignored: %d %s", rec.Code, rec.Body)
	}
}

func TestStatementShapeAndSnapshotRules(t *testing.T) {
	e := newHistoryEnv(t)
	first := e.pay(t, e.ada, "pay-1", "bob", 1000)
	e.pay(t, e.bob, "pay-2", "ada", 300)
	rec := do(e.h, "GET", "/statement?limit=1", "", e.ada)
	if rec.Code != 200 {
		t.Fatalf("statement: %d %s", rec.Code, rec.Body)
	}
	st := decode(t, rec.Body.Bytes())
	entries, _ := st["entries"].([]any)
	token, _ := st["snapshot"].(string)
	if len(entries) != 1 || st["has_more"] != true || st["opening_balance"] != float64(10000) || st["closing_balance"] != float64(9300) || !snapshotToken.MatchString(token) {
		t.Fatalf("first page: %s", rec.Body)
	}
	entry := entries[0].(map[string]any)
	if entry["delta"] != float64(-1000) || entry["balance_after"] != float64(9000) || entry["revision"] != float64(1) ||
		entry["effective_at"] != first["created_at"] || entry["recorded_at"] != first["created_at"] ||
		entry["payment"].(map[string]any)["payment_id"] != first["payment_id"] {
		t.Errorf("first entry: %v", entry)
	}
	e.pay(t, e.ada, "pay-3", "cy", 50) // later activity must not change the snapshot
	next := decode(t, do(e.h, "GET", "/statement?snapshot="+token+"&limit=1&offset=1&nonsense=1", "", e.ada).Body.Bytes())
	if next["closing_balance"] != float64(9300) || next["has_more"] != false || next["snapshot"] != token ||
		len(next["entries"].([]any)) != 1 || next["entries"].([]any)[0].(map[string]any)["balance_after"] != float64(9300) {
		t.Errorf("snapshot page 2: %v", next)
	}
	for _, extra := range []string{"from=2026-09-24T00:00:00Z", "to=2026-09-24T00:00:00Z", "known_at=2026-09-24T00:00:00Z", "from=", "known_at=junk"} {
		wantErr(t, "snapshot with "+extra, do(e.h, "GET", "/statement?snapshot="+token+"&"+extra, "", e.ada), 422, "validation_failed")
	}
	wantErr(t, "empty snapshot", do(e.h, "GET", "/statement?snapshot=", "", e.ada), 422, "validation_failed")
	wantErr(t, "snapshot with bad limit", do(e.h, "GET", "/statement?snapshot="+token+"&limit=0", "", e.ada), 422, "validation_failed")
	wantErr(t, "unknown token", do(e.h, "GET", "/statement?snapshot=snap_00000000000000000000000000000000", "", e.ada), 404, "not_found")
	wantErr(t, "another user's token", do(e.h, "GET", "/statement?snapshot="+token, "", e.bob), 404, "not_found")
	do(e.h, "POST", "/_test/reset", historyFixture, nil)
	wantErr(t, "token from before reset", do(e.h, "GET", "/statement?snapshot="+token, "", loginAs(t, e.h, "ada@example.com")), 404, "not_found")
}
