package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"reflect"
	"sort"
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
	txStripMigratedHistory(t, gs)
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

	// The migrated history answers every historical read consistently.
	txCheckMigratedReads(t, h, raw, map[string]string{"u_ada": txAdaToken, "u_bob": txBobToken, "u_cy": txCyToken})

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

// txStripMigratedHistory checks the history an import of a stage-1/2 export adds (revision 1 per
// payment with the verbatim created_at, opening balance = balance - net effect of the original
// payments, history_version 3) and removes it, so the rest of the state can be compared to the
// original export key for key.
func txStripMigratedHistory(t testing.TB, gs map[string]any) {
	t.Helper()
	if gs["history_version"] != float64(3) {
		t.Fatalf("history_version %v, want 3", gs["history_version"])
	}
	pays, _ := gs["payments"].([]any)
	revs, _ := gs["revisions"].([]any)
	if len(revs) != len(pays) {
		t.Fatalf("%d revisions for %d payments", len(revs), len(pays))
	}
	net := map[string]float64{}
	for i, p := range pays {
		pm, r := p.(map[string]any), revs[i].(map[string]any)
		if r["payment_id"] != pm["payment_id"] || r["revision"] != float64(1) || r["amount"] != pm["amount"] ||
			r["effective_at"] != pm["created_at"] || r["recorded_at"] != pm["created_at"] || r["reason"] != "" {
			t.Fatalf("revision %d of the migrated state: %v for payment %v", i, r, pm)
		}
		if v, ok := pm["refund_of"]; !ok || v != nil {
			t.Fatalf("an imported payment must expose refund_of null: %v", pm)
		}
		delete(pm, "refund_of") // stage-4 default; a stage-1..3 export has none
		net[pm["from_user_id"].(string)] -= pm["amount"].(float64)
		net[pm["to_user_id"].(string)] += pm["amount"].(float64)
	}
	for _, u := range gs["users"].([]any) {
		um := u.(map[string]any)
		if um["opening_balance"] != um["balance"].(float64)-net[um["id"].(string)] {
			t.Fatalf("opening_balance of %v is %v, want balance %v minus net %v", um["id"], um["opening_balance"], um["balance"], net[um["id"].(string)])
		}
		delete(um, "opening_balance")
	}
	delete(gs, "revisions")
	delete(gs, "history_version")
}

type txOriginalPay struct {
	ID, From, To, Created string
	Amount                float64
	JSON                  map[string]any
}

// txCheckMigratedReads drives /statement, /me and /payments/{id}/revisions over an imported
// stage-1/2 state and checks them against the original export's payments.
func txCheckMigratedReads(t testing.TB, h http.Handler, original []byte, tokens map[string]string) {
	t.Helper()
	st := txJSON(t, original)["state"].(map[string]any)
	var pays []txOriginalPay
	for _, p := range st["payments"].([]any) {
		pm := p.(map[string]any)
		if _, ok := pm["authorization_id"]; !ok {
			pm["authorization_id"] = nil // a stage-1 payment gains the stage-2 field
		}
		if _, ok := pm["refund_of"]; !ok {
			pm["refund_of"] = nil // a stage-1..3 payment gains the stage-4 field
		}
		pays = append(pays, txOriginalPay{pm["payment_id"].(string), pm["from_user_id"].(string), pm["to_user_id"].(string),
			pm["created_at"].(string), pm["amount"].(float64), pm})
	}
	balance := map[string]int64{}
	var seeded int64
	for _, u := range st["users"].([]any) {
		um := u.(map[string]any)
		balance[um["id"].(string)] = int64(um["balance"].(float64))
		seeded += balance[um["id"].(string)]
	}
	for uid, tok := range tokens {
		var mine []txOriginalPay
		opening := balance[uid]
		for _, p := range pays {
			switch uid {
			case p.From:
				mine = append(mine, p)
				opening += int64(p.Amount)
			case p.To:
				mine = append(mine, p)
				opening -= int64(p.Amount)
			}
		}
		sort.SliceStable(mine, func(i, j int) bool {
			a, _ := ParseInstant(mine[i].Created)
			b, _ := ParseInstant(mine[j].Created)
			if !a.Equal(b) {
				return a.Before(b)
			}
			return mine[i].ID < mine[j].ID
		})
		rec := txDo(h, "GET", "/statement?limit=200", tok, "", "")
		if rec.Code != 200 {
			t.Fatalf("statement of %s: %d %s", uid, rec.Code, rec.Body)
		}
		var s tsStmt
		if err := json.Unmarshal(rec.Body.Bytes(), &s); err != nil {
			t.Fatal(err)
		}
		if s.OpeningBalance != opening || s.ClosingBalance != balance[uid] || s.OpeningBalance+tsDeltas(s) != s.ClosingBalance || len(s.Entries) != len(mine) || s.HasMore {
			t.Fatalf("statement of %s: opening %d closing %d entries %d, want %d %d %d", uid, s.OpeningBalance, s.ClosingBalance, len(s.Entries), opening, balance[uid], len(mine))
		}
		running := opening
		for i, en := range s.Entries {
			p := mine[i]
			if en.Payment["payment_id"] != p.ID || en.Revision != 1 || en.EffectiveAt != p.Created || en.RecordedAt != p.Created {
				t.Fatalf("%s entry %d: %+v, want payment %s created %s", uid, i, en, p.ID, p.Created)
			}
			if !reflect.DeepEqual(en.Payment, p.JSON) {
				t.Fatalf("%s entry %d: payment body changed by the migration:\n%v\n%v", uid, i, en.Payment, p.JSON)
			}
			if uid == p.From {
				running -= int64(p.Amount)
			} else {
				running += int64(p.Amount)
			}
			if en.BalanceAfter != running {
				t.Fatalf("%s entry %d balance_after %d, want %d", uid, i, en.BalanceAfter, running)
			}
		}
		// As-of reads: before everything is the opening balance; far future the current balance
		// and no hold; each payment's own instant includes it.
		me := func(q string) map[string]any {
			return txJSON(t, txWant(t, "me"+q, txDo(h, "GET", "/me"+q, tok, "", ""), 200))
		}
		if m := me("?as_of=2000-01-01T00:00:00%2B00:00"); txNum(m, "balance") != opening || txNum(m, "held") != 0 || m["as_of"] != "2000-01-01T00:00:00+00:00" {
			t.Fatalf("%s as_of before everything: %v", uid, m)
		}
		if m := me("?as_of=2200-01-01T00:00:00%2B00:00"); txNum(m, "balance") != balance[uid] || txNum(m, "total") != balance[uid] || txNum(m, "held") != 0 || txNum(m, "available") != balance[uid] {
			t.Fatalf("%s as_of far future: %v", uid, m)
		}
		if m := me("?known_at=2000-01-01T00:00:00%2B00:00"); txNum(m, "balance") != opening {
			t.Fatalf("%s known before everything: %v", uid, m)
		}
		for i, en := range s.Entries {
			if i+1 < len(s.Entries) && s.Entries[i+1].EffectiveAt == en.EffectiveAt {
				continue
			}
			if m := me("?as_of=" + url.QueryEscape(en.EffectiveAt)); txNum(m, "balance") != en.BalanceAfter {
				t.Fatalf("%s as_of %s: %v, want %d", uid, en.EffectiveAt, m, en.BalanceAfter)
			}
		}
		for _, p := range mine {
			if uid != p.From {
				continue
			}
			rv := txJSON(t, txWant(t, "revisions", txDo(h, "GET", "/payments/"+p.ID+"/revisions", tok, "", ""), 200))["revisions"].([]any)
			want := map[string]any{"payment_id": p.ID, "revision": float64(1), "amount": p.Amount, "effective_at": p.Created, "recorded_at": p.Created, "reason": ""}
			if len(rv) != 1 || !reflect.DeepEqual(rv[0], want) {
				t.Fatalf("revisions of %s: %v, want %v", p.ID, rv, want)
			}
		}
	}
	// The sum of every wallet equals the seeded sum in every view.
	for _, q := range []string{"", "?as_of=2000-01-01T00:00:00%2B00:00", "?as_of=2200-01-01T00:00:00%2B00:00", "?known_at=2000-01-01T00:00:00%2B00:00"} {
		var sum int64
		for _, tok := range tokens {
			sum += txNum(txJSON(t, txWant(t, "me", txDo(h, "GET", "/me"+q, tok, "", ""), 200)), "total")
		}
		if len(tokens) == len(balance) && sum != seeded {
			t.Fatalf("view %q: totals sum to %d, want %d", q, sum, seeded)
		}
	}
}
