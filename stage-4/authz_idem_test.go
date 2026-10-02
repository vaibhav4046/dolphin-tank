package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// Replay rules of stage-1 section 7 for the two new idempotent write paths,
// driven through the real HTTP handlers.

func txServer(t testing.TB) (http.Handler, map[string]string) {
	t.Helper()
	return txServerFx(t, txFx())
}

func txServerFx(t testing.TB, fixture string) (http.Handler, map[string]string) {
	t.Helper()
	h := NewServer(NewStore())
	if rec := txDo(h, "POST", "/_test/reset", "", "", fixture); rec.Code != 204 {
		t.Fatalf("reset: %d %s", rec.Code, rec.Body)
	}
	tok := map[string]string{}
	for _, n := range []string{"ada", "bob", "cy", "dee"} {
		rec := txDo(h, "POST", "/auth/login", "", "", `{"email":"`+n+`@example.com","password":"correct horse"}`)
		tok[n], _ = txJSON(t, rec.Body.Bytes())["token"].(string)
		if rec.Code != 200 || tok[n] == "" {
			t.Fatalf("login %s: %d %s", n, rec.Code, rec.Body)
		}
	}
	return h, tok
}

func txWantErr(t testing.TB, what string, rec *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	var env struct{ Error struct{ Code string } }
	if rec.Code != status || json.Unmarshal(rec.Body.Bytes(), &env) != nil || env.Error.Code != code {
		t.Fatalf("%s: %d %s, want %d %s", what, rec.Code, rec.Body, status, code)
	}
}

func txWant(t testing.TB, what string, rec *httptest.ResponseRecorder, status int) []byte {
	t.Helper()
	if rec.Code != status {
		t.Fatalf("%s: %d %s, want %d", what, rec.Code, rec.Body, status)
	}
	return rec.Body.Bytes()
}

func txHold(t testing.TB, h http.Handler, tok map[string]string, key, to string, amount string) string {
	t.Helper()
	b := txWant(t, "authorize "+key, txDo(h, "POST", "/authorizations", tok["ada"], key, `{"to_handle":"`+to+`","amount":`+amount+`}`), 201)
	return txJSON(t, b)["authorization_id"].(string)
}

// txConcurrent runs fn n times at once and returns the status codes and bodies.
func txConcurrent(n int, fn func() *httptest.ResponseRecorder) ([]int, [][]byte) {
	codes, bodies := make([]int, n), make([][]byte, n)
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			rec := fn()
			codes[i], bodies[i] = rec.Code, rec.Body.Bytes()
		}(i)
	}
	close(start)
	wg.Wait()
	return codes, bodies
}

func txOneCreated(t testing.TB, what string, codes []int, bodies [][]byte) {
	t.Helper()
	created, replays := 0, 0
	for i, c := range codes {
		switch c {
		case 201:
			created++
		case 200:
			replays++
		default:
			t.Fatalf("%s: unexpected status %d: %s", what, c, bodies[i])
		}
		if !bytes.Equal(bodies[i], bodies[0]) {
			t.Fatalf("%s: bodies differ", what)
		}
	}
	if created != 1 || replays != len(codes)-1 {
		t.Fatalf("%s: %d x 201 and %d x 200, want 1 and %d", what, created, replays, len(codes)-1)
	}
}

func TestIdempotencyOnAuthorizePath(t *testing.T) {
	h, tok := txServer(t)
	body := `{"to_handle":"bob","amount":400,"note":"deposit"}`
	for key, status := range map[string]int{"": 400, strings.Repeat("k", 256): 422} {
		rec := txDo(h, "POST", "/authorizations", tok["ada"], key, body)
		if rec.Code != status {
			t.Fatalf("key of %d chars: %d %s, want %d", len(key), rec.Code, rec.Body, status)
		}
	}
	first := txWant(t, "first use", txDo(h, "POST", "/authorizations", tok["ada"], "k1", body), 201)
	for _, replay := range []string{
		body, `{"note":"deposit","amount":4e2,"to_handle":"bob"}`, ` { "to_handle" : "bob", "amount": 400.0, "note":"deposit" } `,
	} {
		if got := txWant(t, "replay "+replay, txDo(h, "POST", "/authorizations", tok["ada"], "k1", replay), 200); !bytes.Equal(got, first) {
			t.Fatalf("replay bytes differ:\n%s\n%s", got, first)
		}
	}
	if me := txMe(t, h, tok["ada"]); txNum(me, "held") != 400 {
		t.Fatalf("replays placed more holds: %v", me)
	}
	// Changed bodies, including invalid ones, are key reuse: a claimed key is resolved before field validation.
	for _, other := range []string{
		`{"to_handle":"bob","amount":401,"note":"deposit"}`, `{"to_handle":"bob","amount":400,"note":"x"}`,
		`{"to_handle":"bob","amount":400,"note":"deposit","visibility":"private"}`, `{}`,
		`{"to_handle":"bob","amount":"x"}`, `{"to_handle":"nobody","amount":-1}`,
	} {
		txWantErr(t, "reuse "+other, txDo(h, "POST", "/authorizations", tok["ada"], "k1", other), 409, "idempotency_key_reuse")
	}
	// The original response survives the hold closing.
	txWant(t, "void", txDo(h, "POST", "/authorizations/a_1/void", tok["ada"], "", ""), 200)
	if got := txWant(t, "replay after void", txDo(h, "POST", "/authorizations", tok["ada"], "k1", body), 200); !bytes.Equal(got, first) {
		t.Fatalf("replay after void changed: %s", got)
	}
	if me := txMe(t, h, tok["ada"]); txNum(me, "held") != 0 {
		t.Fatalf("void did not release: %v", me)
	}
	// A key that failed with 4xx is unclaimed.
	for _, c := range []struct {
		key, bad, good string
		status         int
		code           string
	}{
		{"kf", `{"to_handle":"bob","amount":5000}`, `{"to_handle":"bob","amount":100}`, 409, "insufficient_funds"},
		{"kv", `{"to_handle":"bob","amount":0}`, `{"to_handle":"bob","amount":10}`, 422, "validation_failed"},
		{"kn", `{"to_handle":"nobody","amount":10}`, `{"to_handle":"bob","amount":10}`, 404, "not_found"},
		{"ks", `{"to_handle":"ada","amount":10}`, `{"to_handle":"bob","amount":10}`, 422, "self_payment"},
	} {
		txWantErr(t, c.key+" failure", txDo(h, "POST", "/authorizations", tok["ada"], c.key, c.bad), c.status, c.code)
		txWant(t, c.key+" retry", txDo(h, "POST", "/authorizations", tok["ada"], c.key, c.good), 201)
	}
	// Scope: per user. Path: part of the identity.
	shared := `{"to_handle":"cy","amount":20}`
	txWant(t, "ada shared", txDo(h, "POST", "/authorizations", tok["ada"], "shared", shared), 201)
	txWant(t, "bob same key", txDo(h, "POST", "/authorizations", tok["bob"], "shared", shared), 201)
	pay := `{"to_handle":"cy","amount":5}`
	txWant(t, "authorize pk", txDo(h, "POST", "/authorizations", tok["ada"], "pk", pay), 201)
	txWant(t, "payment with the same key and body", txDo(h, "POST", "/payments", tok["ada"], "pk", pay), 201)
	txWant(t, "authorize replay", txDo(h, "POST", "/authorizations", tok["ada"], "pk", pay), 200)

	// Twenty identical requests at once: one hold.
	before := txNum(txMe(t, h, tok["ada"]), "held")
	same := `{"to_handle":"dee","amount":50}`
	codes, bodies := txConcurrent(20, func() *httptest.ResponseRecorder {
		return txDo(h, "POST", "/authorizations", tok["ada"], "cc", same)
	})
	txOneCreated(t, "concurrent authorize", codes, bodies)
	if after := txNum(txMe(t, h, tok["ada"]), "held"); after != before+50 {
		t.Fatalf("held %d -> %d, want exactly +50", before, after)
	}
}

func TestIdempotencyOnCapturePath(t *testing.T) {
	h, tok := txServer(t)
	capture := func(who, id, key, body string) *httptest.ResponseRecorder {
		return txDo(h, "POST", "/authorizations/"+id+"/capture", tok[who], key, body)
	}
	a1 := txHold(t, h, tok, "h1", "bob", "300")
	a2 := txHold(t, h, tok, "h2", "bob", "200")
	a3 := txHold(t, h, tok, "h3", "bob", "100")
	a4 := txHold(t, h, tok, "h4", "bob", "50")
	a5 := txHold(t, h, tok, "h5", "bob", "100")
	a6 := txHold(t, h, tok, "h6", "bob", "100")

	if rec := capture("bob", a1, "", `{}`); rec.Code != 400 {
		t.Fatalf("capture without a key: %d %s", rec.Code, rec.Body)
	}
	first := txWant(t, "first capture", capture("bob", a1, "c1", `{}`), 201)
	if p := txJSON(t, first); p["authorization_id"] != a1 || p["request_id"] != nil || txNum(p, "amount") != 300 {
		t.Fatalf("capture payment: %s", first)
	}
	if got := txWant(t, "replay", capture("bob", a1, "c1", ` { } `), 200); !bytes.Equal(got, first) {
		t.Fatalf("replay bytes differ:\n%s\n%s", got, first)
	}
	// {} and {"amount":N} are different JSON values even when they mean the same capture.
	for _, other := range []string{`{"amount":300}`, `{"final":true}`, `{"amount":300,"final":true}`} {
		txWantErr(t, "reuse "+other, capture("bob", a1, "c1", other), 409, "idempotency_key_reuse")
	}
	txWantErr(t, "closed hold, new key", capture("bob", a1, "c1b", `{"amount":300}`), 409, "authorization_not_open")
	txWant(t, "replay after the hold closed", capture("bob", a1, "c1", `{}`), 200)

	// Extended mode and path identity.
	partial := `{"amount":100,"final":false}`
	kc := txWant(t, "non-final capture", capture("bob", a2, "kc", partial), 201)
	if got := txWant(t, "replay", capture("bob", a2, "kc", partial), 200); !bytes.Equal(got, kc) {
		t.Fatal("non-final replay differs")
	}
	txWantErr(t, "final differs", capture("bob", a2, "kc", `{"amount":100}`), 409, "idempotency_key_reuse")
	txWant(t, "same key and body, other path", capture("bob", a3, "kc", partial), 201)
	kz := txWant(t, "remainder", capture("bob", a2, "kz", `{}`), 201)
	if txNum(txJSON(t, kz), "amount") != 100 {
		t.Fatalf("remainder capture: %s", kz)
	}
	if got := txWant(t, "replay of the earlier capture on a closed hold", capture("bob", a2, "kc", partial), 200); !bytes.Equal(got, kc) {
		t.Fatal("replay on a closed hold differs")
	}
	txWant(t, "replay of the closing capture", capture("bob", a2, "kz", `{}`), 200)

	// A claimed key is resolved before 403/404/409 checks, and only for its own user.
	txWantErr(t, "stranger, same key", capture("cy", a1, "c1", `{}`), 403, "forbidden")
	txWantErr(t, "stranger again: the key was never claimed", capture("cy", a1, "c1", `{}`), 403, "forbidden")
	txWantErr(t, "payer is not the receiver", capture("ada", a4, "cp", `{}`), 403, "forbidden")
	txWantErr(t, "unknown authorization", capture("bob", "a_999", "cu", `{}`), 404, "not_found")
	txWant(t, "same key after the 404", capture("bob", a4, "cu", `{}`), 201)

	// Failed 4xx keys are reusable.
	txWantErr(t, "above remainder", capture("bob", a5, "ce", `{"amount":9999}`), 422, "capture_exceeds_authorization")
	txWant(t, "same key, valid amount", capture("bob", a5, "ce", `{"amount":50,"final":false}`), 201)

	// Field validation comes first, even for a resource that does not exist.
	for _, c := range []struct {
		body   string
		status int
		code   string
	}{
		{`{"amount":"x"}`, 422, "validation_failed"}, {`{"amount":0}`, 422, "validation_failed"}, {`{"amount":1.5}`, 422, "validation_failed"},
		{`{"amount":true}`, 422, "validation_failed"}, {`{"amount":null}`, 422, "validation_failed"}, {`{"amount":1000000001}`, 422, "validation_failed"},
		{`{"final":"yes"}`, 400, "malformed_request"}, {`{"final":null}`, 400, "malformed_request"}, {`{"final":1}`, 400, "malformed_request"},
		{`{}`, 404, "not_found"},
	} {
		txWantErr(t, "unknown id "+c.body, capture("bob", "a_999", "cv", c.body), c.status, c.code)
	}

	// Twenty identical captures at once: one payment.
	codes, bodies := txConcurrent(20, func() *httptest.ResponseRecorder {
		return capture("bob", a6, "cc", `{"amount":50,"final":false}`)
	})
	txOneCreated(t, "concurrent capture", codes, bodies)
	var list struct {
		Authorizations []struct {
			ID         string   `json:"authorization_id"`
			Captured   int64    `json:"captured_amount"`
			Remaining  int64    `json:"remaining_amount"`
			Status     string   `json:"status"`
			PaymentIDs []string `json:"payment_ids"`
		}
	}
	if err := json.Unmarshal(txWant(t, "list", txDo(h, "GET", "/authorizations?direction=incoming", tok["bob"], "", ""), 200), &list); err != nil {
		t.Fatal(err)
	}
	found := false
	for _, a := range list.Authorizations {
		if a.ID == a6 {
			found = true
			if a.Captured != 50 || a.Remaining != 50 || a.Status != "open" || len(a.PaymentIDs) != 1 {
				t.Fatalf("a6 after 20 identical captures: %+v", a)
			}
		}
	}
	if !found {
		t.Fatal("a6 missing from the list")
	}
	var sum int64
	for _, n := range []string{"ada", "bob", "cy", "dee"} {
		sum += txNum(txMe(t, h, tok[n]), "total")
	}
	if sum != txSeeded {
		t.Fatalf("sum of totals %d, want %d", sum, txSeeded)
	}
}
