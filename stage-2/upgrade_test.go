package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strconv"
	"strings"
	"testing"
)

// testdata/stage1-export.json was produced by the accepted stage-1 server (see
// testdata/stage1-export.notes.txt for the scenario, tokens, keys and bodies).
const (
	txAdaToken = "441c63c9604c9c8ac56c49fcb30d4ed3c3da57d88ab76f5f8a1949dd67d7c82c"
	txBobToken = "da64f1b94fbef36ce158a61137ac2906d1af58236a2ab20f10b2b2f6ec0b427f"
	txCyToken  = "038ca6bdccbbfc7b4af96c7603eaccb0aa25b67ea31499519ddef22ca015ab6d"

	txK1Resp = `{"payment_id":"p_2","from_user_id":"u_ada","from_handle":"ada","to_user_id":"u_bob","to_handle":"bob","amount":700,"currency":"EUR","note":"lunch","visibility":"public","request_id":null,"settlement_id":null,"created_at":"2026-10-01T10:15:37+00:00"}`
	txK2Resp = `{"payment_id":"p_3","from_user_id":"u_ada","from_handle":"ada","to_user_id":"u_cy","to_handle":"cy","amount":300,"currency":"EUR","note":"lost response","visibility":"public","request_id":null,"settlement_id":null,"created_at":"2026-10-01T10:15:37+00:00"}`
)

func txDo(h http.Handler, method, path, token, key, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func txJSON(t testing.TB, b []byte) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatalf("not a JSON object: %v: %s", err, b)
	}
	return m
}

func txNum(m map[string]any, k string) int64 { n, _ := m[k].(float64); return int64(n) }

func txMe(t testing.TB, h http.Handler, token string) map[string]any {
	t.Helper()
	rec := txDo(h, "GET", "/me", token, "", "")
	if rec.Code != 200 {
		t.Fatalf("GET /me: %d %s", rec.Code, rec.Body)
	}
	return txJSON(t, rec.Body.Bytes())
}

// txParseIdemKey undoes trIdemKey: quoted user, method, quoted path, quoted key.
func txParseIdemKey(t testing.TB, k string) (user, method, path, key string) {
	t.Helper()
	next := func(s string) (string, string) {
		q, err := strconv.QuotedPrefix(s)
		if err != nil {
			t.Fatalf("bad idempotency map key %q", k)
		}
		v, _ := strconv.Unquote(q)
		return v, strings.TrimPrefix(s[len(q):], " ")
	}
	user, rest := next(k)
	i := strings.IndexByte(rest, ' ')
	method, rest = rest[:i], rest[i+1:]
	path, rest = next(rest)
	key, _ = next(rest)
	return
}

func txReadExport(t testing.TB) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/stage1-export.json")
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestUpgradeFromStage1Export(t *testing.T) {
	raw := txReadExport(t)
	s := NewStore()
	h := NewServer(s)

	if rec := txDo(h, "POST", "/_test/import", "", "", string(raw)); rec.Code != 204 {
		t.Fatalf("import of a stage-1 export: %d %s", rec.Code, rec.Body)
	}

	// Existing bearer tokens still authenticate; Me has the stage-2 shape with no holds.
	for tok, want := range map[string]int64{txAdaToken: 8750, txBobToken: 3400, txCyToken: 1850} {
		me := txMe(t, h, tok)
		if txNum(me, "balance") != want || txNum(me, "total") != want || txNum(me, "available") != want || txNum(me, "held") != 0 {
			t.Fatalf("/me after import: %v, want balance=total=available=%d held=0", me, want)
		}
	}

	// Nothing was regenerated: the re-exported state is the stage-1 one plus the
	// stage-2 defaults and nothing else.
	e1 := txExport(t, s)
	got, want := txJSON(t, e1), txJSON(t, raw)
	gs := got["state"].(map[string]any)
	if a, _ := gs["authorizations"].([]any); a == nil || len(a) != 0 || txNum(gs, "authorization_ttl_seconds") != 600 {
		t.Fatalf("stage-2 defaults missing: authorizations=%v ttl=%v", gs["authorizations"], gs["authorization_ttl_seconds"])
	}
	delete(gs, "authorizations")
	delete(gs, "authorization_ttl_seconds")
	for _, p := range gs["payments"].([]any) {
		pm := p.(map[string]any)
		if v, ok := pm["authorization_id"]; !ok || v != nil {
			t.Fatalf("imported payment must expose authorization_id null: %v", pm)
		}
		delete(pm, "authorization_id")
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ids, timestamps, tokens, receipts, operators or counters changed across the upgrade (got %d bytes, want %d)", len(e1), len(raw))
	}

	// Export -> Import -> Export is byte-identical for the imported state.
	if rec := txDo(h, "POST", "/_test/import", "", "", string(e1)); rec.Code != 204 {
		t.Fatalf("re-import: %d %s", rec.Code, rec.Body)
	}
	if e2 := txExport(t, s); !bytes.Equal(e1, e2) {
		t.Fatalf("export differs after import of an export:\n%s\n%s", e1, e2)
	}

	// The two named receipts replay with the original bytes and no extra money.
	for _, c := range []struct{ key, body, resp string }{
		{"k1", `{"to_handle":"bob","amount":700,"note":"lunch"}`, txK1Resp},
		{"k2", `{"to_handle":"cy","amount":300,"note":"lost response","visibility":"public"}`, txK2Resp},
	} {
		rec := txDo(h, "POST", "/payments", txAdaToken, c.key, c.body)
		if rec.Code != 200 || rec.Body.String() != c.resp {
			t.Fatalf("replay %s: %d %s\nwant %s", c.key, rec.Code, rec.Body, c.resp)
		}
	}
	// Every receipt in the export replays: all five stage-1 write paths.
	owners := map[string]string{}
	for tok, uid := range txTokens(t, raw) {
		owners[uid] = tok
	}
	var sys struct {
		State struct {
			Sys struct {
				Idem map[string]struct {
					Body string
					Resp json.RawMessage
				}
			}
		}
	}
	if err := json.Unmarshal(raw, &sys); err != nil {
		t.Fatal(err)
	}
	if len(sys.State.Sys.Idem) != 6 {
		t.Fatalf("scenario should hold 6 receipts, has %d", len(sys.State.Sys.Idem))
	}
	for mk, rec := range sys.State.Sys.Idem {
		user, method, path, key := txParseIdemKey(t, mk)
		r := txDo(h, method, path, owners[user], key, rec.Body)
		if r.Code != 200 || !bytes.Equal(r.Body.Bytes(), rec.Resp) {
			t.Fatalf("replay %s: %d %s, want 200 %s", mk, r.Code, r.Body, rec.Resp)
		}
	}
	if e3 := txExport(t, s); !bytes.Equal(e1, e3) {
		t.Fatalf("replays changed state")
	}

	// Seeded users log in with their passwords (this mints new tokens, so it
	// comes after the byte-for-byte checks).
	for _, email := range []string{"ada@example.com", "bob@example.com", "cy@example.com"} {
		rec := txDo(h, "POST", "/auth/login", "", "", `{"email":"`+email+`","password":"correct horse"}`)
		if rec.Code != 200 || txJSON(t, rec.Body.Bytes())["token"] == "" {
			t.Fatalf("login %s: %d %s", email, rec.Code, rec.Body)
		}
	}

	// New stage-2 features work on the imported state.
	a := txDo(h, "POST", "/authorizations", txAdaToken, "auth-1", `{"to_handle":"bob","amount":2000,"note":"deposit"}`)
	if a.Code != 201 {
		t.Fatalf("authorize on imported state: %d %s", a.Code, a.Body)
	}
	ab := txJSON(t, a.Body.Bytes())
	if me := txMe(t, h, txAdaToken); txNum(me, "total") != 8750 || txNum(me, "held") != 2000 || txNum(me, "available") != 6750 {
		t.Fatalf("/me after hold: %v", me)
	}
	capRec := txDo(h, "POST", "/authorizations/"+ab["authorization_id"].(string)+"/capture", txBobToken, "cap-1", `{"amount":1500}`)
	if capRec.Code != 201 {
		t.Fatalf("capture: %d %s", capRec.Code, capRec.Body)
	}
	if pm := txJSON(t, capRec.Body.Bytes()); pm["authorization_id"] != ab["authorization_id"] || txNum(pm, "amount") != 1500 {
		t.Fatalf("capture payment: %v", pm)
	}
	if me := txMe(t, h, txAdaToken); txNum(me, "total") != 7250 || txNum(me, "held") != 0 || txNum(me, "available") != 7250 {
		t.Fatalf("/me after capture: %v", me)
	}

	// The stage-1 pending request is payable by its payer; the operator's
	// permission survived; money is conserved.
	if rec := txDo(h, "POST", "/requests/rq_1/pay", txAdaToken, "upg-pay", `{}`); rec.Code != 201 || txJSON(t, rec.Body.Bytes())["request_id"] != "rq_1" {
		t.Fatalf("pay imported request: %d %s", rec.Code, rec.Body)
	}
	set := `{"transfers":[{"from_handle":"bob","to_handle":"cy","amount":10}]}`
	if rec := txDo(h, "POST", "/settlements", txCyToken, "upg-set", set); rec.Code != 201 {
		t.Fatalf("operator settlement after import: %d %s", rec.Code, rec.Body)
	}
	if rec := txDo(h, "POST", "/settlements", txBobToken, "upg-set-bob", set); rec.Code != 403 {
		t.Fatalf("non-operator settlement: %d %s", rec.Code, rec.Body)
	}
	var sum int64
	for _, tok := range []string{txAdaToken, txBobToken, txCyToken} {
		sum += txNum(txMe(t, h, tok), "total")
	}
	if sum != 14000 {
		t.Fatalf("sum of totals %d, want 14000", sum)
	}
}

func txTokens(t testing.TB, raw []byte) map[string]string {
	t.Helper()
	out := map[string]string{}
	for tok, uid := range txJSON(t, raw)["state"].(map[string]any)["tokens"].(map[string]any) {
		out[tok] = uid.(string)
	}
	return out
}

func txExport(t testing.TB, s *Store) []byte {
	t.Helper()
	b, e := s.Export()
	if e != nil {
		t.Fatalf("export: %v", e.Message)
	}
	return b
}
