package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

const (
	txFuture = "2099-01-01T00:00:00+00:00"
	txPast   = "2000-01-01T00:00:00+00:00"
	txSeeded = int64(1600)
	txUsers  = `"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":1000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":500},
 {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":100},
 {"id":"u_dee","email":"dee@example.com","password":"correct horse","display_name":"Dee","handle":"dee","balance":0}]`
)

// txFx builds a fixture: ada is a settlement operator; extra members are raw JSON "key":value pairs.
func txFx(extra ...string) string {
	parts := append([]string{`"currency":"EUR"`, `"minor_units":2`, `"settlement_operator_ids":["u_ada"]`, txUsers}, extra...)
	return "{" + strings.Join(parts, ",") + "}"
}

// txA is one seeded authorization ada -> bob; rest is raw extra members.
func txA(id, status string, amount int64, expires, rest string) string {
	s := fmt.Sprintf(`{"id":%q,"from_user_id":"u_ada","to_user_id":"u_bob","amount":%d,"status":%q,"expires_at":%q`, id, amount, status, expires)
	if rest != "" {
		s += "," + rest
	}
	return s + "}"
}

func txAuths(items ...string) string { return `"authorizations":[` + strings.Join(items, ",") + `]` }

func txReset(t testing.TB, raw string) *Store {
	t.Helper()
	s := NewStore()
	if e := s.Reset([]byte(raw)); e != nil {
		t.Fatalf("reset: %d %s %s", e.Status, e.Code, e.Message)
	}
	return s
}

// txResetRejected resets a store that already holds state and checks 422
// validation_failed with the old state byte-for-byte intact.
func txResetRejected(t testing.TB, name, raw string) {
	t.Helper()
	s := txReset(t, txFx())
	ttSignup(t, s, "keep@example.com")
	before := ttExport(t, s)
	e := s.Reset([]byte(raw))
	if e == nil || e.Status != 422 || e.Code != "validation_failed" {
		t.Errorf("%s: want 422 validation_failed, got %v", name, e)
		return
	}
	if !bytes.Equal(before, ttExport(t, s)) {
		t.Errorf("%s: rejected reset changed state", name)
	}
}

func txMeS(t testing.TB, s *Store, uid string, now time.Time) map[string]any {
	t.Helper()
	b, e := s.Exec(func(st *State) (any, *AppError) { return st.Me(uid, now), nil })
	if e != nil {
		t.Fatalf("me: %v", e.Message)
	}
	return txJSON(t, b)
}

func txList(t testing.TB, s *Store, uid, direction, status string, now time.Time) []map[string]any {
	t.Helper()
	b, e := s.Exec(func(st *State) (any, *AppError) { return st.ListAuthorizations(uid, direction, status, 200, 0, now) })
	if e != nil {
		t.Fatalf("list: %v", e.Message)
	}
	var out struct {
		Authorizations []map[string]any `json:"authorizations"`
	}
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out.Authorizations
}

func TestResetTTLMatrix(t *testing.T) {
	for _, c := range []struct {
		name, val string
		want      int64 // 0 = must be rejected
	}{
		{"omitted", "", 600}, {"null is omission", "null", 600}, {"one", "1", 1}, {"600.0", "600.0", 600},
		{"exponent", "1e3", 1000}, {"max", "1000000000", 1_000_000_000},
		{"zero", "0", 0}, {"negative", "-1", 0}, {"numeric string", `"600"`, 0}, {"text", `"x"`, 0},
		{"fraction", "1.5", 0}, {"over max", "1000000001", 0}, {"bool", "true", 0}, {"array", "[600]", 0},
		{"huge", "1e400", 0}, {"object", "{}", 0},
	} {
		raw := txFx()
		if c.val != "" {
			raw = txFx(`"authorization_ttl_seconds":` + c.val)
		}
		if c.want == 0 {
			txResetRejected(t, c.name, raw)
			continue
		}
		s := txReset(t, raw)
		s.mu.Lock()
		got := s.st.AuthTTLSeconds
		s.mu.Unlock()
		if got != c.want {
			t.Errorf("%s: ttl %d, want %d", c.name, got, c.want)
		}
		var env struct {
			State struct {
				TTL int64 `json:"authorization_ttl_seconds"`
			}
		}
		if err := json.Unmarshal(ttExport(t, s), &env); err != nil || env.State.TTL != c.want {
			t.Errorf("%s: exported ttl %d, want %d", c.name, env.State.TTL, c.want)
		}
	}
}

func TestAPICreatedAuthorizationUsesFixtureTTL(t *testing.T) {
	s := txReset(t, txFx(`"authorization_ttl_seconds":2`))
	now := time.Date(2030, 5, 6, 7, 8, 9, 0, time.UTC)
	b, e := s.Exec(func(st *State) (any, *AppError) {
		return st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 100, Visibility: "public"}, now)
	})
	if e != nil {
		t.Fatal(e.Message)
	}
	a := txJSON(t, b)
	if a["created_at"] != "2030-05-06T07:08:09+00:00" || a["expires_at"] != "2030-05-06T07:08:11+00:00" {
		t.Fatalf("created_at/expires_at: %v / %v", a["created_at"], a["expires_at"])
	}
}

func TestSeededAuthorizationStatusMatrix(t *testing.T) {
	raw := txFx(`"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"note":"first part"}]`,
		txAuths(
			txA("a_open", "open", 100, txFuture, ""),
			txA("a_cap", "captured", 200, txFuture, ""),
			txA("a_void", "voided", 300, txFuture, ""),
			txA("a_exp", "expired", 400, txFuture, ""),
			txA("a_past", "open", 500, txPast, ""),
			txA("a_part", "open", 250, txFuture, `"captured_amount":100,"payment_ids":["p_1"],"note":"deposit","visibility":"private"`),
			`{"from_user_id":"u_bob","to_user_id":"u_ada","amount":50,"expires_at":"`+txFuture+`"}`,
		))
	s := txReset(t, raw)
	now := time.Now()
	type want struct {
		status    string
		captured  int64
		remaining int64
	}
	wants := map[string]want{
		"a_open": {"open", 0, 100}, "a_cap": {"captured", 200, 0}, "a_void": {"voided", 0, 0},
		"a_exp": {"expired", 0, 0}, "a_past": {"expired", 0, 0}, "a_part": {"open", 100, 150},
	}
	all := txList(t, s, "u_ada", "", "", now)
	if len(all) != 7 {
		t.Fatalf("ada should see 7 authorizations, sees %d", len(all))
	}
	for _, a := range all {
		id := a["authorization_id"].(string)
		w, ok := wants[id]
		if !ok { // the generated one from bob
			if id != "a_1" || a["status"] != "open" || a["note"] != "" || a["visibility"] != "public" || txNum(a, "remaining_amount") != 50 {
				t.Errorf("generated authorization %v", a)
			}
			continue
		}
		if a["status"] != w.status || txNum(a, "captured_amount") != w.captured || txNum(a, "remaining_amount") != w.remaining {
			t.Errorf("%s: %v, want %+v", id, a, w)
		}
		if a["created_at"] == "" || a["expires_at"] == "" {
			t.Errorf("%s: missing timestamps", id)
		}
	}
	// ada holds 100 + 150; the 50 hold belongs to bob.
	me := txMeS(t, s, "u_ada", now)
	if txNum(me, "balance") != 1000 || txNum(me, "total") != 1000 || txNum(me, "held") != 250 || txNum(me, "available") != 750 {
		t.Fatalf("ada /me: %v", me)
	}
	if me := txMeS(t, s, "u_bob", now); txNum(me, "held") != 50 || txNum(me, "available") != 450 {
		t.Fatalf("bob /me: %v", me)
	}
	if open := txList(t, s, "u_ada", "", "open", now); len(open) != 3 {
		t.Fatalf("status=open should list a_open, a_part and bob's hold, got %d", len(open))
	}
	if exp := txList(t, s, "u_ada", "outgoing", "expired", now); len(exp) != 2 {
		t.Fatalf("an authorization expired by the clock matches expired: got %d", len(exp))
	}
	// A seeded capture reads like an API one: the payment names its authorization.
	var env struct {
		State struct {
			Payments []struct {
				ID   string  `json:"payment_id"`
				Auth *string `json:"authorization_id"`
			}
		}
	}
	if err := json.Unmarshal(ttExport(t, s), &env); err != nil || len(env.State.Payments) != 1 ||
		env.State.Payments[0].Auth == nil || *env.State.Payments[0].Auth != "a_part" {
		t.Fatalf("seeded capture payment not linked: %+v %v", env.State.Payments, err)
	}
}

func TestSeededHoldSumAgainstBalance(t *testing.T) {
	for _, c := range []struct {
		name string
		ok   bool
		auth []string
	}{
		{"sum equals balance", true, []string{txA("a_1", "open", 600, txFuture, ""), txA("a_2", "open", 400, txFuture, "")}},
		{"sum one above balance", false, []string{txA("a_1", "open", 600, txFuture, ""), txA("a_2", "open", 401, txFuture, "")}},
		{"single hold above balance", false, []string{txA("a_1", "open", 1001, txFuture, "")}},
		{"closed and expired holds do not count", true, []string{
			txA("a_1", "open", 600, txFuture, ""), txA("a_2", "open", 600, txPast, ""),
			txA("a_3", "voided", 600, txFuture, ""), txA("a_4", "expired", 600, txFuture, ""), txA("a_5", "captured", 600, txFuture, "")}},
		{"captured part is not held", true, []string{txA("a_1", "open", 1500, txFuture, `"captured_amount":600`)}},
		{"partial remainder above balance", false, []string{txA("a_1", "open", 1500, txFuture, `"captured_amount":400`)}},
		{"many small holds above balance", false, func() []string {
			var l []string
			for i := 0; i < 101; i++ {
				l = append(l, txA(fmt.Sprintf("a_%d", i+1), "open", 10, txFuture, ""))
			}
			return l
		}()},
	} {
		raw := txFx(txAuths(c.auth...))
		if !c.ok {
			txResetRejected(t, c.name, raw)
			continue
		}
		s := txReset(t, raw)
		me := txMeS(t, s, "u_ada", time.Now())
		if txNum(me, "available") < 0 || txNum(me, "available")+txNum(me, "held") != 1000 {
			t.Errorf("%s: /me %v", c.name, me)
		}
	}
	// ADDITIONAL: a hold whose deadline passed long ago holds nothing.
	s := txReset(t, txFx(txAuths(txA("a_1", "open", 900, txPast, ""))))
	if me := txMeS(t, s, "u_ada", time.Now()); txNum(me, "held") != 0 || txNum(me, "available") != 1000 {
		t.Fatalf("expired-in-the-past hold must hold nothing: %v", me)
	}
	if l := txList(t, s, "u_ada", "", "", time.Now()); len(l) != 1 || l[0]["status"] != "expired" || txNum(l[0], "remaining_amount") != 0 {
		t.Fatalf("list: %v", l)
	}
}

func TestSeededAuthorizationRejections(t *testing.T) {
	okA := txA("a_1", "open", 100, txFuture, "")
	pay := `"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":1}]`
	bad := func(rest string) string { // an authorization ada->bob with members replaced/added
		return `{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"expires_at":"` + txFuture + `",` + rest + `}`
	}
	for name, raw := range map[string]string{
		"authorizations not an array": txFx(`"authorizations":{}`),
		"element not an object":       txFx(txAuths(`7`)),
		"unknown from":                txFx(txAuths(`{"id":"a_x","from_user_id":"u_zzz","to_user_id":"u_bob","amount":1,"expires_at":"` + txFuture + `"}`)),
		"unknown to":                  txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_zzz","amount":1,"expires_at":"` + txFuture + `"}`)),
		"from equals to":              txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_ada","amount":1,"expires_at":"` + txFuture + `"}`)),
		"missing from":                txFx(txAuths(`{"id":"a_x","to_user_id":"u_bob","amount":1,"expires_at":"` + txFuture + `"}`)),
		"bad status":                  txFx(txAuths(bad(`"status":"bogus"`))),
		"capitalised status":          txFx(txAuths(bad(`"status":"Open"`))),
		"status not a string":         txFx(txAuths(bad(`"status":1`))),
		"bad visibility":              txFx(txAuths(bad(`"visibility":"secret"`))),
		"missing expires_at":          txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":1}`)),
		"expires_at not a time":       txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":1,"expires_at":"tomorrow"}`)),
		"expires_at not a string":     txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":1,"expires_at":123}`)),
		"amount zero":                 txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":0,"expires_at":"` + txFuture + `"}`)),
		"amount negative":             txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":-5,"expires_at":"` + txFuture + `"}`)),
		"amount fractional":           txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":1.5,"expires_at":"` + txFuture + `"}`)),
		"amount string":               txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","amount":"5","expires_at":"` + txFuture + `"}`)),
		"amount missing":              txFx(txAuths(`{"id":"a_x","from_user_id":"u_ada","to_user_id":"u_bob","expires_at":"` + txFuture + `"}`)),
		"captured above amount":       txFx(txAuths(bad(`"captured_amount":101`))),
		"captured negative":           txFx(txAuths(bad(`"captured_amount":-1`))),
		"captured fractional":         txFx(txAuths(bad(`"captured_amount":1.5`))),
		"duplicate authorization id":  txFx(txAuths(okA, okA)),
		"id clashes with a payment":   txFx(pay, txAuths(txA("p_1", "open", 1, txFuture, ""))),
		"id clashes with a user":      txFx(txAuths(txA("u_ada", "open", 1, txFuture, ""))),
		"payment_ids unknown payment": txFx(pay, txAuths(bad(`"payment_ids":["p_9"]`))),
		"payment_ids not strings":     txFx(pay, txAuths(bad(`"payment_ids":[1]`))),
		"payment_ids not an array":    txFx(pay, txAuths(bad(`"payment_ids":"p_1"`))),
		"note not a string":           txFx(txAuths(bad(`"note":5`))),
	} {
		txResetRejected(t, name, raw)
	}
	// An earlier fixture may omit authorizations, or give an empty list.
	for _, raw := range []string{txFx(), txFx(`"authorizations":[]`), txFx(`"authorizations":null`)} {
		s := txReset(t, raw)
		if l := txList(t, s, "u_ada", "", "", time.Now()); len(l) != 0 {
			t.Fatalf("expected no authorizations: %v", l)
		}
	}
	// Generated ids never collide with seeded ones, and the API continues after them.
	s := txReset(t, txFx(txAuths(txA("a_7", "voided", 5, txFuture, ""), `{"from_user_id":"u_ada","to_user_id":"u_bob","amount":5,"expires_at":"`+txFuture+`"}`)))
	b, e := s.Exec(func(st *State) (any, *AppError) {
		return st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 1, Visibility: "public"}, time.Now())
	})
	if e != nil || txJSON(t, b)["authorization_id"] != "a_9" {
		t.Fatalf("next id after seeded a_7 and generated a_8: %s %v", b, e)
	}
}

func TestStage2ExportRoundTripAndImportRejections(t *testing.T) {
	s := txReset(t, txFx(`"authorization_ttl_seconds":900`, txAuths(
		txA("a_seed", "open", 300, txFuture, ""), txA("a_old", "voided", 40, txPast, `"captured_amount":10`))))
	now := time.Now()
	if _, e := s.Exec(func(st *State) (any, *AppError) {
		a, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: "cy", Amount: 200, Visibility: "private"}, now)
		if e != nil {
			return nil, e
		}
		amt := int64(50)
		_, e = st.Capture("u_cy", a.AuthorizationID, CaptureIn{Amount: &amt, Final: false}, now)
		return nil, e
	}); e != nil {
		t.Fatal(e.Message)
	}
	good := ttExport(t, s)

	d := txReset(t, txFx())
	if e := d.Import(good); e != nil {
		t.Fatalf("import of own export: %v", e.Message)
	}
	if again := ttExport(t, d); !bytes.Equal(good, again) {
		t.Fatalf("export -> import -> export not byte-identical:\n%s\n%s", good, again)
	}
	if me := txMeS(t, d, "u_ada", now); txNum(me, "held") != 450 || txNum(me, "total") != 950 {
		t.Fatalf("holds not preserved: %v", me)
	}

	auth := func(st map[string]any, i int) map[string]any { return st["authorizations"].([]any)[i].(map[string]any) }
	for name, mutate := range map[string]func(top, st map[string]any){
		"unknown payer":           func(_, st map[string]any) { auth(st, 0)["from_user_id"] = "u_zzz" },
		"unknown receiver":        func(_, st map[string]any) { auth(st, 0)["to_user_id"] = "u_zzz" },
		"bad status":              func(_, st map[string]any) { auth(st, 0)["status"] = "bogus" },
		"holds above balance":     func(_, st map[string]any) { auth(st, 0)["amount"] = 99999999 },
		"ttl negative":            func(_, st map[string]any) { st["authorization_ttl_seconds"] = -5 },
		"ttl above max":           func(_, st map[string]any) { st["authorization_ttl_seconds"] = int64(1) << 40 },
		"ttl not a number":        func(_, st map[string]any) { st["authorization_ttl_seconds"] = "600" },
		"null authorization":      func(_, st map[string]any) { st["authorizations"] = []any{nil} },
		"expires_at garbage":      func(_, st map[string]any) { auth(st, 0)["expires_at"] = "garbage" },
		"payment_ids unknown":     func(_, st map[string]any) { auth(st, 0)["payment_ids"] = []any{"p_nope"} },
		"payment names unknown a": func(_, st map[string]any) { st["payments"].([]any)[0].(map[string]any)["authorization_id"] = "a_nope" },
		"captured above amount":   func(_, st map[string]any) { auth(st, 0)["captured_amount"] = 99999999 },
		"captured negative":       func(_, st map[string]any) { auth(st, 1)["captured_amount"] = -1 },
		"amount zero":             func(_, st map[string]any) { auth(st, 0)["amount"] = 0 },
		"bad visibility":          func(_, st map[string]any) { auth(st, 0)["visibility"] = "secret" },
		"duplicate id":            func(_, st map[string]any) { auth(st, 1)["authorization_id"] = auth(st, 0)["authorization_id"] },
		"authorizations a string": func(_, st map[string]any) { st["authorizations"] = "none" },
	} {
		bad := ttMutateExport(t, good, mutate)
		before := ttExport(t, d)
		e := d.Import(bad)
		if e == nil || e.Status != 422 {
			t.Errorf("%s: want 422, got %v", name, e)
			continue
		}
		if !bytes.Equal(before, ttExport(t, d)) {
			t.Errorf("%s: rejected import changed the destination", name)
		}
	}
}

// An imported state whose counters lag its records must never hand out an id that is already taken.
func TestImportWithStaleCountersNeverReusesIDs(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_5", "open", 10, txFuture, ""))))
	good := ttExport(t, s)
	stale := ttMutateExport(t, good, func(_, st map[string]any) { st["seq"] = map[string]any{} })
	d := txReset(t, txFx())
	if e := d.Import(stale); e != nil {
		t.Fatalf("import with an empty seq: %v", e.Message)
	}
	now := time.Now()
	seen := map[string]bool{"a_5": true}
	for i := 0; i < 8; i++ {
		b, e := d.Exec(func(st *State) (any, *AppError) {
			return st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 1, Visibility: "public"}, now)
		})
		if e != nil {
			t.Fatal(e.Message)
		}
		id := txJSON(t, b)["authorization_id"].(string)
		if seen[id] {
			t.Fatalf("authorization id %s handed out twice", id)
		}
		seen[id] = true
	}
}
