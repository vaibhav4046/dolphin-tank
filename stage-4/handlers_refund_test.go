package main

import (
	"strings"
	"testing"
)

func TestRefundRoute(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id := p["payment_id"].(string)
	url := "/payments/" + id + "/refunds"
	post := func(who map[string]string, key, target, body string) (int, string) {
		r := do(e.h, "POST", "/payments/"+target+"/refunds", body, withKey(who, key))
		return r.Code, r.Body.String()
	}
	wantRec := func(what, target string, who map[string]string, key, body string, status int, code string) {
		t.Helper()
		wantErr(t, what, do(e.h, "POST", "/payments/"+target+"/refunds", body, withKey(who, key)), status, code)
	}

	if v, ok := p["refund_of"]; !ok || v != nil {
		t.Errorf("U11: a direct payment must carry refund_of null, got %v (present=%v)", v, ok)
	}

	wantErr(t, "U01 no token", do(e.h, "POST", url, `{"amount":100}`, withKey(nil, "k")), 401, "unauthenticated")
	wantErr(t, "U01 missing key", do(e.h, "POST", url, `{"amount":100}`, e.bob), 400, "missing_idempotency_key")
	wantErr(t, "U01 key too long", do(e.h, "POST", url, `{"amount":100}`, withKey(e.bob, strings.Repeat("k", 256))), 422, "validation_failed")
	wantRec("U01 not json", id, e.bob, "k1", `nope`, 400, "malformed_request")
	wantRec("U01 array body", id, e.bob, "k2", `[]`, 400, "malformed_request")
	wantRec("U01 empty body", id, e.bob, "k3", ``, 400, "malformed_request")

	for name, body := range map[string]string{
		"missing":    `{}`,
		"zero":       `{"amount":0}`,
		"negative":   `{"amount":-5}`,
		"fractional": `{"amount":1.5}`,
		"string":     `{"amount":"100"}`,
		"null":       `{"amount":null}`,
		"over max":   `{"amount":1000000001}`,
		"bool":       `{"amount":true}`,
	} {
		wantRec("U04 "+name, id, e.bob, "kv-"+name, body, 422, "validation_failed")
	}
	wantRec("U04 validation before 404", "p_999", e.bob, "kv-404", `{}`, 422, "validation_failed")
	wantRec("U04 validation before 403", id, e.ada, "kv-403", `{}`, 422, "validation_failed")

	wantRec("U02 unknown payment", "p_999", e.bob, "k4", `{"amount":100}`, 404, "not_found")
	wantRec("U02 sender", id, e.ada, "k5", `{"amount":100}`, 403, "forbidden")
	wantRec("U02 stranger", id, e.cy, "k6", `{"amount":100}`, 403, "forbidden")
	wantRec("U02 404 before 403", "p_999", e.ada, "k7", `{"amount":100}`, 404, "not_found")

	code, raw := post(e.bob, "ref-1", id, `{"amount":400,"ignored":"x"}`)
	if code != 201 {
		t.Fatalf("U08 refund: %d %s", code, raw)
	}
	refund := decode(t, []byte(raw))
	if refund["refund_of"] != id || refund["amount"] != float64(400) || refund["from_handle"] != "bob" || refund["to_handle"] != "ada" ||
		refund["request_id"] != nil || refund["authorization_id"] != nil || refund["note"] != p["note"] || refund["visibility"] != p["visibility"] {
		t.Errorf("U11 refund body: %s", raw)
	}
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != 9400 || b != 3100 {
		t.Errorf("balances after refund 400 of 1000: ada %v bob %v, want 9400 and 3100", a, b)
	}

	if code, again := post(e.bob, "ref-1", id, `{"amount":400,"ignored":"x"}`); code != 200 || again != raw {
		t.Errorf("U08 replay must be 200 with the original body: %d %s", code, again)
	}
	wantRec("U01 same key other amount", id, e.bob, "ref-1", `{"amount":401}`, 409, "idempotency_key_reuse")
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != 9400 || b != 3100 {
		t.Errorf("replays and reuse must not move money: ada %v bob %v", a, b)
	}

	wantRec("refund of a refund", refund["payment_id"].(string), e.ada, "k8", `{"amount":100}`, 422, "invalid_refund_target")
	wantRec("over the remainder", id, e.bob, "k9", `{"amount":601}`, 422, "refund_exceeds_payment")
	if code, raw := post(e.bob, "ref-2", id, `{"amount":600}`); code != 201 {
		t.Errorf("exact remainder: %d %s", code, raw)
	}

	feed := do(e.h, "GET", "/activity", "", e.ada).Body.String()
	if !strings.Contains(feed, `"refund_of":null`) || !strings.Contains(feed, `"refund_of":"`+id+`"`) {
		t.Errorf("U11 /activity must carry refund_of null and the target id: %s", feed)
	}
}
