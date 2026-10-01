package main

import (
	"encoding/json"
	"net/http"
	"testing"
)

func loginAs(t *testing.T, h http.Handler, email string) map[string]string {
	t.Helper()
	rec := do(h, "POST", "/auth/login", `{"email":"`+email+`","password":"correct horse"}`, nil)
	var out struct{ Token string }
	if err := json.Unmarshal(rec.Body.Bytes(), &out); rec.Code != 200 || err != nil {
		t.Fatalf("login %s: %d %s", email, rec.Code, rec.Body)
	}
	return map[string]string{"Authorization": "Bearer " + out.Token}
}

func withKey(hdr map[string]string, key string) map[string]string {
	out := map[string]string{"Idempotency-Key": key}
	for k, v := range hdr {
		out[k] = v
	}
	return out
}

func decode(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		t.Fatalf("decode %s: %v", body, err)
	}
	return m
}

func TestAuthorizationRoutesRequireAuth(t *testing.T) {
	h, token := newTestServer(t)
	for _, c := range []struct{ method, path string }{
		{"GET", "/authorizations"}, {"POST", "/authorizations"}, {"POST", "/authorizations/a_1/capture"}, {"POST", "/authorizations/a_1/void"},
	} {
		for _, auth := range []string{"", "Bearer nope", token} {
			wantErr(t, c.method+" "+c.path+" auth="+auth, do(h, c.method, c.path, `{}`, map[string]string{"Authorization": auth, "Idempotency-Key": "k"}), 401, "unauthenticated")
		}
	}
	for _, p := range []string{"/authorizations//capture", "/authorizations/a_1/refund", "/authorizations/a_1/capture/x", "/authorizations/a_1"} {
		ada := map[string]string{"Authorization": "Bearer " + token, "Idempotency-Key": "k"}
		wantErr(t, "POST "+p, do(h, "POST", p, `{}`, ada), 404, "not_found")
	}
}

func TestAuthorizationHTTPLifecycle(t *testing.T) {
	h, _ := newTestServer(t)
	ada, bob := loginAs(t, h, "ada@example.com"), loginAs(t, h, "bob@example.com")

	rec := do(h, "POST", "/authorizations", `{"to_handle":"bob","amount":2000,"note":"deposit"}`, ada)
	wantErr(t, "authorize without key", rec, 400, "missing_idempotency_key")
	rec = do(h, "POST", "/authorizations", `{"to_handle":"bob","amount":2000,"note":"deposit","visibility":"private"}`, withKey(ada, "auth-1"))
	a := decode(t, rec.Body.Bytes())
	if rec.Code != 201 || a["status"] != "open" || a["remaining_amount"] != float64(2000) || a["payment_id"] != nil {
		t.Fatalf("authorize: %d %s", rec.Code, rec.Body)
	}
	id := a["authorization_id"].(string)
	if replay := do(h, "POST", "/authorizations", `{"visibility":"private","note":"deposit","amount":2000,"to_handle":"bob"}`, withKey(ada, "auth-1")); replay.Code != 200 || replay.Body.String() != rec.Body.String() {
		t.Errorf("authorize replay: %d %s", replay.Code, replay.Body)
	}
	wantErr(t, "authorize key reuse", do(h, "POST", "/authorizations", `{"to_handle":"bob","amount":2001}`, withKey(ada, "auth-1")), 409, "idempotency_key_reuse")
	wantErr(t, "authorize self", do(h, "POST", "/authorizations", `{"to_handle":"ada","amount":5}`, withKey(ada, "auth-2")), 422, "self_payment")
	wantErr(t, "authorize over available", do(h, "POST", "/authorizations", `{"to_handle":"bob","amount":8001}`, withKey(ada, "auth-3")), 409, "insufficient_funds")

	me := decode(t, do(h, "GET", "/me", "", ada).Body.Bytes())
	if me["balance"] != float64(10000) || me["total"] != float64(10000) || me["available"] != float64(8000) || me["held"] != float64(2000) {
		t.Errorf("/me with a hold: %v", me)
	}
	if feed := do(h, "GET", "/activity", "", ada).Body.String(); feed != `{"payments":[],"has_more":false}` {
		t.Errorf("an open hold must not be a feed item: %s", feed)
	}
	for who, hdr := range map[string]map[string]string{"payer": ada, "receiver": bob} {
		list := decode(t, do(h, "GET", "/authorizations?status=open", "", hdr).Body.Bytes())
		if items, _ := list["authorizations"].([]any); len(items) != 1 || list["has_more"] != false {
			t.Errorf("%s list: %v", who, list)
		}
	}
	for _, q := range []string{"direction=sideways", "status=nope", "limit=0", "offset=-1", "direction="} {
		wantErr(t, "GET /authorizations?"+q, do(h, "GET", "/authorizations?"+q, "", ada), 422, "validation_failed")
	}

	wantErr(t, "payer captures", do(h, "POST", "/authorizations/"+id+"/capture", `{}`, withKey(ada, "cap-0")), 403, "forbidden")
	wantErr(t, "capture without key", do(h, "POST", "/authorizations/"+id+"/capture", `{}`, bob), 400, "missing_idempotency_key")
	wantErr(t, "capture bad final", do(h, "POST", "/authorizations/"+id+"/capture", `{"final":"no"}`, withKey(bob, "cap-1")), 400, "malformed_request")
	wantErr(t, "capture too much", do(h, "POST", "/authorizations/"+id+"/capture", `{"amount":2001}`, withKey(bob, "cap-2")), 422, "capture_exceeds_authorization")
	rec = do(h, "POST", "/authorizations/"+id+"/capture", `{"amount":700,"final":false}`, withKey(bob, "cap-3"))
	p := decode(t, rec.Body.Bytes())
	if rec.Code != 201 || p["authorization_id"] != id || p["request_id"] != nil || p["amount"] != float64(700) || p["visibility"] != "private" || p["note"] != "deposit" {
		t.Fatalf("capture: %d %s", rec.Code, rec.Body)
	}
	if replay := do(h, "POST", "/authorizations/"+id+"/capture", `{"amount":700,"final":false}`, withKey(bob, "cap-3")); replay.Code != 200 || replay.Body.String() != rec.Body.String() {
		t.Errorf("capture replay: %d %s", replay.Code, replay.Body)
	}
	wantErr(t, "capture body reuse", do(h, "POST", "/authorizations/"+id+"/capture", `{"amount":700}`, withKey(bob, "cap-3")), 409, "idempotency_key_reuse")
	if me := decode(t, do(h, "GET", "/me", "", ada).Body.Bytes()); me["total"] != float64(9300) || me["held"] != float64(1300) || me["available"] != float64(8000) {
		t.Errorf("/me after partial capture: %v", me)
	}

	wantErr(t, "receiver voids", do(h, "POST", "/authorizations/"+id+"/void", `{}`, bob), 403, "forbidden")
	wantErr(t, "void garbage body", do(h, "POST", "/authorizations/"+id+"/void", `{`, ada), 400, "malformed_request")
	for i := 0; i < 2; i++ {
		v := decode(t, do(h, "POST", "/authorizations/"+id+"/void", "", ada).Body.Bytes())
		if v["status"] != "voided" || v["remaining_amount"] != float64(0) || v["captured_amount"] != float64(700) {
			t.Fatalf("void #%d: %v", i, v)
		}
	}
	wantErr(t, "capture after void", do(h, "POST", "/authorizations/"+id+"/capture", `{}`, withKey(bob, "cap-4")), 409, "authorization_not_open")
	wantErr(t, "unknown authorization", do(h, "POST", "/authorizations/a_999/void", `{}`, ada), 404, "not_found")
	if me := decode(t, do(h, "GET", "/me", "", ada).Body.Bytes()); me["held"] != float64(0) || me["available"] != float64(9300) {
		t.Errorf("/me after void: %v", me)
	}
}
