package main

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const historyFixture = `{"currency":"EUR","minor_units":2,"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":2500},
 {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":5000}]}`

var microInstant = regexp.MustCompile(`^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$`)

type histEnv struct {
	h            http.Handler
	ada, bob, cy map[string]string
}

func newHistoryEnv(t *testing.T) histEnv {
	t.Helper()
	h := NewServer(NewStore())
	if rec := do(h, "POST", "/_test/reset", historyFixture, nil); rec.Code != 204 {
		t.Fatalf("reset: %d %s", rec.Code, rec.Body)
	}
	return histEnv{h, loginAs(t, h, "ada@example.com"), loginAs(t, h, "bob@example.com"), loginAs(t, h, "cy@example.com")}
}

func (e histEnv) pay(t *testing.T, from map[string]string, key, to string, amount int) map[string]any {
	t.Helper()
	body := `{"to_handle":"` + to + `","amount":` + strconv.Itoa(amount) + `}`
	rec := do(e.h, "POST", "/payments", body, withKey(from, key))
	if rec.Code != 201 {
		t.Fatalf("pay %s %d: %d %s", to, amount, rec.Code, rec.Body)
	}
	return decode(t, rec.Body.Bytes())
}

func correction(rev, amount int, effectiveAt, reason string) string {
	return `{"expected_revision":` + strconv.Itoa(rev) + `,"amount":` + strconv.Itoa(amount) +
		`,"effective_at":"` + effectiveAt + `","reason":"` + reason + `"}`
}

func (e histEnv) correct(who map[string]string, key, paymentID, body string) *httptest.ResponseRecorder {
	return do(e.h, "POST", "/payments/"+paymentID+"/corrections", body, withKey(who, key))
}

func (e histEnv) balance(t *testing.T, who map[string]string) float64 {
	t.Helper()
	return decode(t, do(e.h, "GET", "/me", "", who).Body.Bytes())["balance"].(float64)
}

func (e histEnv) revisions(t *testing.T, who map[string]string, paymentID string) []any {
	t.Helper()
	rec := do(e.h, "GET", "/payments/"+paymentID+"/revisions", "", who)
	if rec.Code != 200 {
		t.Fatalf("revisions: %d %s", rec.Code, rec.Body)
	}
	return decode(t, rec.Body.Bytes())["revisions"].([]any)
}

func TestHistoryRoutesAuthAndMethods(t *testing.T) {
	e := newHistoryEnv(t)
	for _, c := range []struct{ method, path string }{
		{"GET", "/me?as_of=bad"}, {"GET", "/statement"}, {"GET", "/statement?from=bad"},
		{"POST", "/payments/p_1/corrections"}, {"GET", "/payments/p_1/revisions"},
	} {
		for _, auth := range []string{"", "Bearer", "Bearer nope", "Basic abc"} {
			hdr := map[string]string{"Idempotency-Key": "k"}
			if auth != "" {
				hdr["Authorization"] = auth
			}
			wantErr(t, c.method+" "+c.path+" auth="+auth, do(e.h, c.method, c.path, "not json", hdr), 401, "unauthenticated")
		}
	}
	for _, c := range []struct{ method, path string }{
		{"POST", "/statement"}, {"PUT", "/statement"}, {"GET", "/statement/x"},
		{"GET", "/payments/p_1/corrections"}, {"DELETE", "/payments/p_1/corrections"}, {"POST", "/payments/p_1/revisions"},
		{"GET", "/payments/p_1"}, {"POST", "/payments/p_1"}, {"GET", "/payments/"}, {"GET", "/payments//revisions"},
		{"POST", "/payments//corrections"}, {"GET", "/payments/p_1/revisions/x"}, {"POST", "/payments/p_1/corrections/x"},
		{"GET", "/payments/p_1/refund"}, {"POST", "/payments/p_1/refund"}, {"PUT", "/me"}, {"POST", "/me"},
	} {
		wantErr(t, c.method+" "+c.path, do(e.h, c.method, c.path, `{}`, withKey(e.ada, "k")), 404, "not_found")
	}
}

func TestCorrectionMatrix(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	if !microInstant.MatchString(created) {
		t.Errorf("API-created payment created_at %q is not a microsecond UTC instant", created)
	}
	good := correction(1, 400, created, "corrected amount")

	wantErr(t, "no token", do(e.h, "POST", "/payments/"+id+"/corrections", good, withKey(nil, "k")), 401, "unauthenticated")
	wantErr(t, "missing key", do(e.h, "POST", "/payments/"+id+"/corrections", good, e.ada), 400, "missing_idempotency_key")
	wantErr(t, "key too long", e.correct(e.ada, strings.Repeat("k", 256), id, good), 422, "validation_failed")
	wantErr(t, "not json", e.correct(e.ada, "k1", id, `nope`), 400, "malformed_request")
	wantErr(t, "empty body", e.correct(e.ada, "k2", id, ``), 400, "malformed_request")
	wantErr(t, "array body", e.correct(e.ada, "k3", id, `[]`), 400, "malformed_request")

	wantErr(t, "unknown payment", e.correct(e.ada, "k4", "p_999", good), 404, "not_found")
	wantErr(t, "receiver", e.correct(e.bob, "k5", id, good), 403, "forbidden")
	wantErr(t, "stranger", e.correct(e.cy, "k6", id, good), 403, "forbidden")
	wantErr(t, "validation before 404", e.correct(e.ada, "k7", "p_999", `{}`), 422, "validation_failed")
	wantErr(t, "validation before 403", e.correct(e.bob, "k8", id, `{}`), 422, "validation_failed")
	wantErr(t, "404 before 403", e.correct(e.bob, "k9", "p_999", good), 404, "not_found")

	future := FormatMicro(time.Now().Add(time.Hour))
	for name, body := range map[string]string{
		"missing revision":  `{"amount":400,"effective_at":"` + created + `","reason":"r"}`,
		"revision zero":     correction(0, 400, created, "r"),
		"amount negative":   correction(1, -1, created, "r"),
		"amount over max":   correction(1, 1_000_000_001, created, "r"),
		"effective naive":   correction(1, 400, "2026-09-20T12:00:00", "r"),
		"effective future":  correction(1, 400, future, "r"),
		"reason empty":      correction(1, 400, created, ""),
		"reason too long":   correction(1, 400, created, strings.Repeat("x", 201)),
		"amount string":     `{"expected_revision":1,"amount":"400","effective_at":"` + created + `","reason":"r"}`,
		"amount fractional": `{"expected_revision":1,"amount":400.5,"effective_at":"` + created + `","reason":"r"}`,
	} {
		wantErr(t, name, e.correct(e.ada, "kv-"+name, id, body), 422, "validation_failed")
	}
	if got := len(e.revisions(t, e.ada, id)); got != 1 {
		t.Fatalf("rejected corrections must leave one revision, got %d", got)
	}

	rec := e.correct(e.ada, "corr-1", id, good)
	if rec.Code != 201 {
		t.Fatalf("correct: %d %s", rec.Code, rec.Body)
	}
	rev := decode(t, rec.Body.Bytes())
	if len(rev) != 6 || rev["payment_id"] != id || rev["revision"] != float64(2) || rev["amount"] != float64(400) ||
		rev["effective_at"] != created || rev["reason"] != "corrected amount" {
		t.Errorf("201 body: %s", rec.Body)
	}
	if recorded, _ := rev["recorded_at"].(string); !microInstant.MatchString(recorded) || recorded <= created {
		t.Errorf("recorded_at %q must be a microsecond instant after %q", recorded, created)
	}
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != 9600 || b != 2900 {
		t.Errorf("balances after correcting 1000 to 400: ada %v bob %v, want 9600 and 2900", a, b)
	}

	wantErr(t, "stale", e.correct(e.ada, "corr-stale", id, correction(1, 300, created, "again")), 409, "stale_revision")
	third := e.correct(e.ada, "corr-2", id, correction(2, 500, created, "second"))
	if third.Code != 201 || decode(t, third.Body.Bytes())["revision"] != float64(3) {
		t.Fatalf("revision 3: %d %s", third.Code, third.Body)
	}
	if replay := e.correct(e.ada, "corr-1", id, good); replay.Code != 200 || replay.Body.String() != rec.Body.String() {
		t.Errorf("replay after revision 3 must return the original revision 2 with 200: %d %s", replay.Code, replay.Body)
	}
	wantErr(t, "same key, other body", e.correct(e.ada, "corr-1", id, correction(1, 401, created, "x")), 409, "idempotency_key_reuse")
	wantErr(t, "claimed key beats validation", e.correct(e.ada, "corr-1", id, `{"expected_revision":0}`), 409, "idempotency_key_reuse")
	if got := len(e.revisions(t, e.ada, id)); got != 3 {
		t.Errorf("revisions after replays: %d, want 3", got)
	}
	if feed := do(e.h, "GET", "/activity", "", e.ada).Body.String(); strings.Count(feed, `"payment_id"`) != 1 || !strings.Contains(feed, `"amount":1000`) {
		t.Errorf("the feed must still show the one original payment: %s", feed)
	}
}

func TestRevisionsMatrix(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	if rec := e.correct(e.ada, "c1", id, correction(1, 700, created, "fix")); rec.Code != 201 {
		t.Fatalf("correct: %d %s", rec.Code, rec.Body)
	}
	for who, hdr := range map[string]map[string]string{"sender": e.ada, "receiver": e.bob} {
		revs := e.revisions(t, hdr, id)
		if len(revs) != 2 {
			t.Fatalf("%s: %v", who, revs)
		}
		first, second := revs[0].(map[string]any), revs[1].(map[string]any)
		if first["revision"] != float64(1) || first["amount"] != float64(1000) || first["reason"] != "" ||
			first["effective_at"] != created || first["recorded_at"] != created || first["payment_id"] != id {
			t.Errorf("%s: revision 1 must be the original payment: %v", who, first)
		}
		if second["revision"] != float64(2) || second["amount"] != float64(700) || second["reason"] != "fix" {
			t.Errorf("%s: revision 2: %v", who, second)
		}
	}
	wantErr(t, "third party, public payment", do(e.h, "GET", "/payments/"+id+"/revisions", "", e.cy), 404, "not_found")
	wantErr(t, "unknown", do(e.h, "GET", "/payments/p_999/revisions", "", e.ada), 404, "not_found")
	wantErr(t, "no token", do(e.h, "GET", "/payments/"+id+"/revisions", "", nil), 401, "unauthenticated")
}

func TestCorrectionInsufficientFundsKeepsKeyUsable(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	e.pay(t, e.bob, "pay-2", "cy", 3500) // bob spends everything he holds
	body := correction(1, 0, created, "reverse")
	wantErr(t, "receiver cannot fund a decrease", e.correct(e.ada, "reverse-1", id, body), 409, "insufficient_funds")
	wantErr(t, "sender cannot fund an increase", e.correct(e.ada, "raise-1", id, correction(1, 20000, created, "raise")), 409, "insufficient_funds")
	if e.balance(t, e.ada) != 9000 || e.balance(t, e.bob) != 0 || len(e.revisions(t, e.ada, id)) != 1 {
		t.Fatalf("a refused correction must change nothing")
	}
	e.pay(t, e.cy, "pay-3", "bob", 1000)
	if rec := e.correct(e.ada, "reverse-1", id, body); rec.Code != 201 {
		t.Errorf("the key of a refused correction must stay usable: %d %s", rec.Code, rec.Body)
	}
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != 10000 || b != 0 {
		t.Errorf("after the full reversal: ada %v bob %v, want 10000 and 0", a, b)
	}
}

func TestCorrectionHistoricalOverdraft(t *testing.T) {
	e := newHistoryEnv(t)
	e.pay(t, e.ada, "pay-1", "bob", 10000)
	p2 := e.pay(t, e.bob, "pay-2", "ada", 4000)
	id, created := p2["payment_id"].(string), p2["created_at"].(string)
	early := correction(1, 4000, "2000-01-01T00:00:00+00:00", "backdate")
	wantErr(t, "bob would owe 1500 before he was paid", e.correct(e.bob, "bd-1", id, early), 409, "historical_overdraft")
	if len(e.revisions(t, e.bob, id)) != 1 {
		t.Fatalf("a refused correction must not append a revision")
	}
	if rec := e.correct(e.bob, "bd-1", id, correction(1, 4000, created, "same instant")); rec.Code != 201 {
		t.Errorf("a refused correction leaves no idempotency record, so the key is free: %d %s", rec.Code, rec.Body)
	}
}

func TestCorrectionOfCaptureIsLinked(t *testing.T) {
	e := newHistoryEnv(t)
	rec := do(e.h, "POST", "/authorizations", `{"to_handle":"bob","amount":2000}`, withKey(e.ada, "auth-1"))
	if rec.Code != 201 {
		t.Fatalf("authorize: %d %s", rec.Code, rec.Body)
	}
	authID := decode(t, rec.Body.Bytes())["authorization_id"].(string)
	rec = do(e.h, "POST", "/authorizations/"+authID+"/capture", `{"amount":500}`, withKey(e.bob, "cap-1"))
	if rec.Code != 201 {
		t.Fatalf("capture: %d %s", rec.Code, rec.Body)
	}
	capture := decode(t, rec.Body.Bytes())
	wantErr(t, "capture is immutable", e.correct(e.ada, "c1", capture["payment_id"].(string),
		correction(1, 100, capture["created_at"].(string), "no")), 422, "linked_payment_immutable")
}

func TestConcurrentCorrectionsSameRevision(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	const racers = 8
	codes := make([]int, racers)
	var wg sync.WaitGroup
	for i := range racers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes[i] = e.correct(e.ada, "race-"+strconv.Itoa(i), id, correction(1, 100+i, created, "race")).Code
		}()
	}
	wg.Wait()
	won, stale := 0, 0
	for _, c := range codes {
		switch c {
		case 201:
			won++
		case 409:
			stale++
		}
	}
	if won != 1 || stale != racers-1 || len(e.revisions(t, e.ada, id)) != 2 {
		t.Errorf("same expected_revision: %d wins, %d stale (codes %v), want exactly one", won, stale, codes)
	}
}
