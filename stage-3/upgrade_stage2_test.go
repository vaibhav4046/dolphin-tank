package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"reflect"
	"testing"
)

// testdata/stage2-export.json was produced by the accepted stage-2 server binary (see
// testdata/stage2-export.notes.txt for the scenario: partial and final capture, void, a request,
// a split, a settlement, seeded holds in every stored status).
const (
	tyAdaToken = "f04d259e4c6ce3bafceb003d9df155d2540af8fb6d0decae11ae926b27f3aff0"
	tyBobToken = "2389eb79b3330f2f82ff8d41a3b9f6c09a491bf01f860d237030c6b159c69711"
	tyCyToken  = "574809ccb54d212743bd353ff820f265efd46dc240a848bc574208dd6fa7ac56"
)

var tyTokens = map[string]string{"u_ada": tyAdaToken, "u_bob": tyBobToken, "u_cy": tyCyToken}

func tyReadExport(t testing.TB) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/stage2-export.json")
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func tyImported(t testing.TB) (*Store, http.Handler, []byte) {
	t.Helper()
	raw := tyReadExport(t)
	s := NewStore()
	h := NewServer(s)
	if rec := txDo(h, "POST", "/_test/import", "", "", string(raw)); rec.Code != 204 {
		t.Fatalf("import of a stage-2 export: %d %s", rec.Code, rec.Body)
	}
	return s, h, raw
}

func TestUpgradeFromStage2Export(t *testing.T) {
	s, h, raw := tyImported(t)

	for tok, want := range map[string]int64{tyAdaToken: 7350, tyBobToken: 4800, tyCyToken: 1850} {
		me := txMe(t, h, tok)
		if txNum(me, "balance") != want || txNum(me, "total") != want || txNum(me, "available")+txNum(me, "held") != want {
			t.Fatalf("/me after import: %v, want total %d", me, want)
		}
	}

	// Nothing but the history was added; every stage-2 fact is intact.
	e1 := txExport(t, s)
	got, want := txJSON(t, e1), txJSON(t, raw)
	gs, ws := got["state"].(map[string]any), want["state"].(map[string]any)
	pays := map[string]map[string]any{}
	for _, p := range ws["payments"].([]any) {
		pays[p.(map[string]any)["payment_id"].(string)] = p.(map[string]any)
	}
	for _, a := range gs["authorizations"].([]any) {
		am := a.(map[string]any)
		var wantClosed any
		ids, _ := am["payment_ids"].([]any)
		switch am["status"] {
		case "captured":
			wantClosed = am["created_at"]
			if len(ids) > 0 {
				wantClosed = pays[ids[len(ids)-1].(string)]["created_at"]
			}
		case "voided":
			wantClosed = am["created_at"]
		case "expired":
			wantClosed = am["expires_at"]
		}
		if am["closed_at"] != wantClosed {
			t.Errorf("authorization %v (%v) closed_at = %v, want %v", am["authorization_id"], am["status"], am["closed_at"], wantClosed)
		}
		delete(am, "closed_at")
	}
	txStripMigratedHistory(t, gs)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ids, timestamps, tokens, receipts, operators, holds or counters changed across the upgrade (got %d bytes, want %d)", len(e1), len(raw))
	}

	// Export -> import -> export is byte-identical for the migrated state.
	e1 = txExport(t, s)
	if rec := txDo(h, "POST", "/_test/import", "", "", string(e1)); rec.Code != 204 {
		t.Fatalf("re-import: %d %s", rec.Code, rec.Body)
	}
	if e2 := txExport(t, s); !bytes.Equal(e1, e2) {
		t.Fatalf("export differs after import of an export")
	}

	// Every stage-2 receipt replays with the original bytes and moves no money.
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
	if len(sys.State.Sys.Idem) != 13 {
		t.Fatalf("scenario should hold 13 receipts, has %d", len(sys.State.Sys.Idem))
	}
	for mk, rec := range sys.State.Sys.Idem {
		user, method, path, key := txParseIdemKey(t, mk)
		r := txDo(h, method, path, owners[user], key, rec.Body)
		if r.Code != 200 || !bytes.Equal(r.Body.Bytes(), rec.Resp) {
			t.Fatalf("replay %s: %d %s, want 200 %s", mk, r.Code, r.Body, rec.Resp)
		}
	}
	if e3 := txExport(t, s); !bytes.Equal(e1, e3) {
		t.Fatal("replays changed state")
	}

	txCheckMigratedReads(t, h, raw, tyTokens)

	// Captures appear exactly once in the statement of both parties, with their link: a_1 had a
	// partial and a final capture, a_3 one, a_2 was voided without any.
	for _, tok := range []string{tyAdaToken, tyBobToken} {
		var st tsStmt
		if err := json.Unmarshal(txWant(t, "statement", txDo(h, "GET", "/statement?limit=200", tok, "", ""), 200), &st); err != nil {
			t.Fatal(err)
		}
		links := map[string]int{}
		for _, en := range st.Entries {
			if a, _ := en.Payment["authorization_id"].(string); a != "" {
				links[a]++
			}
		}
		if links["a_1"] != 2 || links["a_3"] != 1 || links["a_2"] != 0 {
			t.Fatalf("capture links in the statement: %v", links)
		}
	}

	// The lifecycle keeps working on the migrated state, and the new payment is a microsecond one.
	p := txJSON(t, txWant(t, "pay after import", txDo(h, "POST", "/payments", tyBobToken, "after-1", `{"to_handle":"cy","amount":10}`), 201))
	if !tsMicroRe.MatchString(p["created_at"].(string)) {
		t.Fatalf("new payment created_at: %v", p["created_at"])
	}
	var st tsStmt
	_ = json.Unmarshal(txWant(t, "statement", txDo(h, "GET", "/statement?limit=200", tyBobToken, "", ""), 200), &st)
	if last := st.Entries[len(st.Entries)-1]; last.Payment["payment_id"] != p["payment_id"] || st.ClosingBalance != 4790 {
		t.Fatalf("the new payment is the last entry and moves the balance: %+v closing %d", last, st.ClosingBalance)
	}
}

func TestUpgradeFromStage2PendingRequestAndSettlementStillWork(t *testing.T) {
	_, h, _ := tyImported(t)
	if rec := txDo(h, "POST", "/requests/rq_1/pay", tyAdaToken, "upg-pay", `{}`); rec.Code != 201 {
		t.Fatalf("pay imported request: %d %s", rec.Code, rec.Body)
	}
	set := txDo(h, "POST", "/settlements", tyCyToken, "upg-set", `{"transfers":[{"from_handle":"bob","to_handle":"cy","amount":10},{"from_handle":"ada","to_handle":"cy","amount":5}]}`)
	var out trSettlementOut
	if err := json.Unmarshal(txWant(t, "settlement after import", set, 201), &out); err != nil {
		t.Fatal(err)
	}
	if !tsMicroRe.MatchString(out.CommittedAt) || len(out.Payments) != 2 || out.Payments[0].CreatedAt != out.CommittedAt || out.Payments[1].CreatedAt != out.CommittedAt {
		t.Fatalf("settlement members share committed_at: %+v", out)
	}
	for _, p := range out.Payments {
		rv := txJSON(t, txWant(t, "revisions", txDo(h, "GET", "/payments/"+p.PaymentID+"/revisions", tyCyToken, "", ""), 200))["revisions"].([]any)
		r := rv[0].(map[string]any)
		if len(rv) != 1 || r["effective_at"] != out.CommittedAt || r["recorded_at"] != out.CommittedAt {
			t.Fatalf("settlement member revision: %v", rv)
		}
	}
}

func TestImportHistoryVersionRules(t *testing.T) {
	s := NewStore()
	if e := s.Import(tyReadExport(t)); e != nil {
		t.Fatalf("import: %v", e.Message)
	}
	good := ttExport(t, s)
	mut := func(f func(top, st map[string]any)) []byte { return ttMutateExport(t, good, f) }
	rev0 := func(st map[string]any) map[string]any { return st["revisions"].([]any)[0].(map[string]any) }
	holds := func(st map[string]any, status string, f func(a map[string]any)) {
		for _, a := range st["authorizations"].([]any) {
			if a.(map[string]any)["status"] == status {
				f(a.(map[string]any))
			}
		}
	}
	reject := map[string][]byte{
		"version 1":                    mut(func(_, st map[string]any) { st["history_version"] = 1 }),
		"version 2":                    mut(func(_, st map[string]any) { st["history_version"] = 2 }),
		"version 4":                    mut(func(_, st map[string]any) { st["history_version"] = 4 }),
		"negative version":             mut(func(_, st map[string]any) { st["history_version"] = -3 }),
		"string version":               mut(func(_, st map[string]any) { st["history_version"] = "3" }),
		"null version":                 mut(func(_, st map[string]any) { st["history_version"] = nil }),
		"fractional version":           mut(func(_, st map[string]any) { st["history_version"] = 3.5 }),
		"bool version":                 mut(func(_, st map[string]any) { st["history_version"] = true }),
		"v3 without revisions":         mut(func(_, st map[string]any) { delete(st, "revisions") }),
		"v3 null revisions":            mut(func(_, st map[string]any) { st["revisions"] = nil }),
		"v3 empty revisions":           mut(func(_, st map[string]any) { st["revisions"] = []any{} }),
		"v3 revision gap":              mut(func(_, st map[string]any) { rev0(st)["revision"] = 2 }),
		"v3 revision of nobody":        mut(func(_, st map[string]any) { rev0(st)["payment_id"] = "p_ghost" }),
		"v3 opening balance lies":      mut(func(_, st map[string]any) { st["users"].([]any)[0].(map[string]any)["opening_balance"] = 1 }),
		"v3 revision 1 amount differs": mut(func(_, st map[string]any) { rev0(st)["amount"] = 1 }),
		"v3 revision instant junk":     mut(func(_, st map[string]any) { rev0(st)["effective_at"] = "yesterday" }),
		"v3 closed hold lacks closed_at": mut(func(_, st map[string]any) {
			holds(st, "voided", func(a map[string]any) { a["closed_at"] = nil })
		}),
		"v3 open hold has closed_at": mut(func(_, st map[string]any) {
			holds(st, "open", func(a map[string]any) { a["closed_at"] = "2026-09-20T10:00:00+00:00" })
		}),
		"payment without created_at": mut(func(_, st map[string]any) {
			st["payments"].([]any)[0].(map[string]any)["created_at"] = ""
		}),
	}
	for name, body := range reject {
		e := s.Import(body)
		if e == nil || e.Status != 422 || e.Code != "validation_failed" {
			t.Errorf("%s: got %v, want 422 validation_failed", name, e)
		}
		if after := ttExport(t, s); !bytes.Equal(after, good) {
			t.Errorf("%s: a refused import changed the state", name)
		}
	}
	// History version 0 or absent migrates; migrating an export without corrections reproduces it
	// (compared as JSON values: the mutation helper re-orders keys inside stored receipts).
	zero := bytes.Replace(good, []byte(`"history_version":3`), []byte(`"history_version":0`), 1)
	if bytes.Equal(zero, good) {
		t.Fatal("export carries no history_version")
	}
	absent := mut(func(_, st map[string]any) {
		delete(st, "history_version")
		delete(st, "revisions")
		for _, u := range st["users"].([]any) {
			delete(u.(map[string]any), "opening_balance")
		}
		for _, a := range st["authorizations"].([]any) {
			delete(a.(map[string]any), "closed_at")
		}
	})
	for name, body := range map[string][]byte{"explicit 0": zero, "absent": absent} {
		if e := s.Import(body); e != nil {
			t.Fatalf("%s: %v", name, e.Message)
		}
		if after := ttExport(t, s); !reflect.DeepEqual(txJSON(t, after), txJSON(t, good)) {
			t.Errorf("%s: migrating an export without corrections must reproduce it", name)
		}
	}
	if e := s.Import(zero); e != nil || !bytes.Equal(ttExport(t, s), good) {
		t.Errorf("explicit 0 must reproduce the export byte for byte: %v", e)
	}
}
