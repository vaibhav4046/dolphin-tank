package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testFixture = `{"currency":"EUR","minor_units":2,"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":2500}]}`

func do(h http.Handler, method, path, body string, hdr map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func wantErr(t *testing.T, what string, rec *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	if rec.Code != status {
		t.Errorf("%s: status %d, want %d (body %s)", what, rec.Code, status, rec.Body)
		return
	}
	if ct := rec.Header().Get("Content-Type"); ct != jsonContentType {
		t.Errorf("%s: content-type %q", what, ct)
	}
	var env struct {
		Error struct{ Code, Message string } `json:"error"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &env); err != nil || env.Error.Code != code || env.Error.Message == "" {
		t.Errorf("%s: envelope %s, want code %s", what, rec.Body, code)
	}
}

func newTestServer(t *testing.T) (http.Handler, string) {
	t.Helper()
	h := NewServer(NewStore())
	if rec := do(h, "POST", "/_test/reset", testFixture, nil); rec.Code != 204 || rec.Body.Len() != 0 {
		t.Fatalf("reset: %d %s", rec.Code, rec.Body)
	}
	rec := do(h, "POST", "/auth/login", `{"email":"ada@example.com","password":"correct horse"}`, nil)
	var out struct{ Token string }
	if err := json.Unmarshal(rec.Body.Bytes(), &out); rec.Code != 200 || err != nil || out.Token == "" {
		t.Fatalf("login: %d %s", rec.Code, rec.Body)
	}
	return h, out.Token
}

func TestRoutingAndEnvelope(t *testing.T) {
	h, _ := newTestServer(t)
	for _, c := range []struct{ method, path string }{
		{"GET", "/nope"}, {"POST", "/health"}, {"GET", "/payments"}, {"DELETE", "/me"},
		{"GET", "/health/"}, {"POST", "/requests//pay"}, {"POST", "/requests/rq_1/refund"},
		{"GET", "/requests/rq_1/pay"}, {"POST", "/requests/rq_1/pay/x"}, {"GET", "/_test/reset"},
	} {
		wantErr(t, c.method+" "+c.path, do(h, c.method, c.path, "", nil), 404, "not_found")
	}
	rec := do(h, "GET", "/health", "", nil)
	if rec.Code != 200 || rec.Body.String() != `{"status":"ok"}` || rec.Header().Get("Content-Type") != jsonContentType {
		t.Errorf("health: %d %q %q", rec.Code, rec.Body, rec.Header().Get("Content-Type"))
	}
}

func TestAuthRequired(t *testing.T) {
	h, token := newTestServer(t)
	private := []struct{ method, path string }{
		{"GET", "/me"}, {"POST", "/payments"}, {"POST", "/requests"}, {"GET", "/requests"},
		{"POST", "/requests/rq_1/pay"}, {"POST", "/requests/rq_1/decline"}, {"POST", "/requests/rq_1/cancel"},
		{"POST", "/splits"}, {"GET", "/activity"}, {"POST", "/settlements"},
	}
	for _, c := range private {
		for _, auth := range []string{"", "Bearer", "Bearer ", "Basic " + token, "Bearer nope", token} {
			hdr := map[string]string{"Idempotency-Key": "k"}
			if auth != "" {
				hdr["Authorization"] = auth
			}
			wantErr(t, c.method+" "+c.path+" auth="+auth, do(h, c.method, c.path, "{}", hdr), 401, "unauthenticated")
		}
	}
	if rec := do(h, "GET", "/me", "", map[string]string{"Authorization": "bearer " + token}); rec.Code != 200 {
		t.Errorf("lowercase scheme: %d %s", rec.Code, rec.Body)
	}
}

func TestParseObject(t *testing.T) {
	for _, c := range []struct {
		name, body string
		allowEmpty bool
		ok         bool
	}{
		{"object", `{"a":1}`, false, true},
		{"huge exponent stays a number", `{"amount":1e999}`, false, true},
		{"whitespace around", " \n{\"a\":1}\t", false, true},
		{"empty refused", ``, false, false},
		{"blank refused", "  \n", false, false},
		{"empty allowed", ``, true, true},
		{"array", `[]`, true, false},
		{"string", `"x"`, true, false},
		{"null", `null`, true, false},
		{"number", `1`, true, false},
		{"two values", `{}{}`, true, false},
		{"trailing junk", `{} x`, true, false},
		{"truncated", `{"a":`, true, false},
		{"invalid utf-8", "{\"a\":\"\xff\"}", true, false},
		{"not json", `hello`, true, false},
		{"deep nesting", strings.Repeat("[", 20000), true, false},
	} {
		obj, e := parseObject([]byte(c.body), c.allowEmpty)
		if c.ok != (e == nil) || (e != nil && (e.Status != 400 || e.Code != "malformed_request")) {
			t.Errorf("%s: obj=%v err=%v", c.name, obj, e)
		}
	}
	obj, _ := parseObject([]byte(`{"amount":1e999}`), false)
	if n, ok := obj["amount"].(json.Number); !ok || n.String() != "1e999" {
		t.Errorf("number not preserved exactly: %#v", obj["amount"])
	}
}

func TestLimitOffsetRejected(t *testing.T) {
	h, token := newTestServer(t)
	auth := map[string]string{"Authorization": "Bearer " + token}
	for _, path := range []string{"/activity", "/requests"} {
		for _, q := range []string{"limit=0", "limit=201", "limit=1e9", "limit=4.0", "limit=+4", "limit=-1", "limit=abc", "offset=-1", "offset=1.0", "offset=1e1"} {
			wantErr(t, path+"?"+q, do(h, "GET", path+"?"+q, "", auth), 422, "validation_failed")
		}
		for _, q := range []string{"", "limit=1", "limit=200", "offset=0&limit=50", "unknown=1"} {
			if rec := do(h, "GET", path+"?"+q, "", auth); rec.Code != 200 {
				t.Errorf("%s?%s: %d %s", path, q, rec.Code, rec.Body)
			}
		}
	}
	wantErr(t, "bad status", do(h, "GET", "/requests?status=bogus", "", auth), 422, "validation_failed")
	wantErr(t, "bad direction", do(h, "GET", "/requests?direction=sideways", "", auth), 422, "validation_failed")
	wantErr(t, "empty status", do(h, "GET", "/requests?status=", "", auth), 422, "validation_failed")
}

func TestIdempotencyHeaderAndBody(t *testing.T) {
	h, token := newTestServer(t)
	auth := func(key string, set bool) map[string]string {
		hdr := map[string]string{"Authorization": "Bearer " + token}
		if set {
			hdr["Idempotency-Key"] = key
		}
		return hdr
	}
	paths := []string{"/payments", "/requests", "/requests/rq_1/pay", "/splits"}
	for _, p := range paths {
		wantErr(t, p+" no key", do(h, "POST", p, "{}", auth("", false)), 400, "missing_idempotency_key")
		wantErr(t, p+" empty key", do(h, "POST", p, "{}", auth("", true)), 400, "missing_idempotency_key")
		wantErr(t, p+" 256-char key", do(h, "POST", p, "{}", auth(strings.Repeat("k", 256), true)), 422, "validation_failed")
		for _, body := range []string{`[]`, `"x"`, `nope`, "{\"a\":\"\xff\"}", `{} {}`} {
			wantErr(t, p+" body "+body, do(h, "POST", p, body, auth("k", true)), 400, "malformed_request")
		}
	}
	wantErr(t, "non-operator settlement", do(h, "POST", "/settlements", "{}", auth("", false)), 403, "forbidden")
	wantErr(t, "2 MiB body", do(h, "POST", "/payments", `{"note":"`+strings.Repeat("a", 2<<20)+`"}`, auth("k", true)), 400, "malformed_request")
	wantErr(t, "garbage decline body", do(h, "POST", "/requests/rq_1/decline", "nope", auth("", false)), 400, "malformed_request")
}

func TestRecoverPanics(t *testing.T) {
	h := recoverPanics(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") }))
	wantErr(t, "panic", do(h, "GET", "/x", "", nil), 500, "internal_error")
}

func TestResetRejectsBadFixture(t *testing.T) {
	h, _ := newTestServer(t)
	bad := `{"currency":"EUR","minor_units":2,"users":[{"id":"u","email":"u@example.com","password":"correct horse","display_name":"U","handle":"u","balance":-1}]}`
	wantErr(t, "negative balance", do(h, "POST", "/_test/reset", bad, nil), 422, "validation_failed")
	wantErr(t, "not json", do(h, "POST", "/_test/reset", "nope", nil), 400, "malformed_request")
}
