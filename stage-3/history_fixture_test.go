package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"
)

// POST /_test/reset with history: created_at, opening balances, revision 1, closed_at of seeded holds.

var tsMicroRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$`)

func tsExportState(t testing.TB, s *Store) map[string]any {
	t.Helper()
	return txJSON(t, ttExport(t, s))["state"].(map[string]any)
}

func tsUsers(t testing.TB, st map[string]any) map[string]map[string]any {
	t.Helper()
	out := map[string]map[string]any{}
	for _, u := range st["users"].([]any) {
		m := u.(map[string]any)
		out[m["id"].(string)] = m
	}
	return out
}

func TestResetCreatedAtIsKeptVerbatim(t *testing.T) {
	forms := []string{
		"2026-09-20T10:00:00+00:00", "2026-09-20T10:00:00Z", "2026-09-20T10:00:00z", "2026-09-20T12:00:00+02:00",
		"2026-09-20T05:30:00-04:30", "2026-09-20T10:00:00.5+00:00", "2026-09-20T10:00:00.123456789Z",
		"2000-01-01T00:00:00+00:00", "1999-12-31T23:59:59-00:00",
	}
	var pays []string
	for i, f := range forms {
		pays = append(pays, fmt.Sprintf(`{"id":"p_%d","from_user_id":"u_ada","to_user_id":"u_bob","amount":1,"created_at":%q}`, i+1, f))
	}
	e := tsNew(t, `"payments":[`+strings.Join(pays, ",")+`]`)
	raw := e.do("ada", "GET", "/activity?limit=200", "", "")
	var feed struct {
		Payments []struct {
			ID        string `json:"payment_id"`
			CreatedAt string `json:"created_at"`
		} `json:"payments"`
	}
	if err := json.Unmarshal(txWant(t, "activity", raw, 200), &feed); err != nil {
		t.Fatal(err)
	}
	got := map[string]string{}
	for _, p := range feed.Payments {
		got[p.ID] = p.CreatedAt
	}
	for i, f := range forms {
		if got[fmt.Sprintf("p_%d", i+1)] != f {
			t.Errorf("created_at %q came back as %q", f, got[fmt.Sprintf("p_%d", i+1)])
		}
	}
	// Revision 1 carries the same string as both effective and recorded time.
	rev := txJSON(t, txWant(t, "revisions", e.do("ada", "GET", "/payments/p_4/revisions", "", ""), 200))["revisions"].([]any)
	if len(rev) != 1 {
		t.Fatalf("revisions: %v", rev)
	}
	r := rev[0].(map[string]any)
	if r["revision"] != float64(1) || r["amount"] != float64(1) || r["effective_at"] != forms[3] || r["recorded_at"] != forms[3] || r["reason"] != "" || r["payment_id"] != "p_4" {
		t.Fatalf("revision 1: %v", r)
	}
}

func TestResetOmittedCreatedAtIsResetTimeBeforeLaterPayments(t *testing.T) {
	before := time.Now().UTC().Truncate(time.Microsecond)
	e := tsNew(t, `"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":5},{"id":"p_2","from_user_id":"u_bob","to_user_id":"u_cy","amount":3}]`)
	after := time.Now().UTC()
	feed := txJSON(t, txWant(t, "activity", e.do("ada", "GET", "/activity", "", ""), 200))["payments"].([]any)
	var seeded []string
	for _, p := range feed {
		seeded = append(seeded, p.(map[string]any)["created_at"].(string))
	}
	if len(seeded) == 0 {
		t.Fatal("no seeded payment in the feed")
	}
	for _, c := range seeded {
		if !tsMicroRe.MatchString(c) {
			t.Fatalf("omitted created_at must be a microsecond instant: %q", c)
		}
		if c != seeded[0] {
			t.Fatalf("every omitted created_at is the one reset instant: %v", seeded)
		}
		at, _ := ParseInstant(c)
		if at.Before(before) || at.After(after) {
			t.Fatalf("reset instant %s not within [%s, %s]", c, before, after)
		}
	}
	// A payment made afterwards is strictly later, even within the same clock tick.
	var prev = seeded[0]
	for i := 0; i < 20; i++ {
		p := e.pay("ada", fmt.Sprintf("k%d", i), "bob", 1)
		ca := p["created_at"].(string)
		a, _ := ParseInstant(prev)
		b, _ := ParseInstant(ca)
		if !tsMicroRe.MatchString(ca) || !b.After(a) {
			t.Fatalf("payment %d created_at %q is not after %q", i, ca, prev)
		}
		prev = ca
	}
	// ... and the statement shows the seeded ones first.
	s := e.stmt("ada", "")
	last := s.Entries[len(s.Entries)-1].Payment["created_at"]
	if s.Entries[0].Payment["created_at"] != seeded[0] || last != prev {
		t.Fatalf("statement order: first %v last %v", s.Entries[0].Payment["created_at"], last)
	}
}

func TestResetRejectsBadOrFutureCreatedAtWithoutChange(t *testing.T) {
	future := time.Now().UTC().Add(time.Hour).Format("2006-01-02T15:04:05+00:00")
	pay := func(v string) string {
		return `{"currency":"EUR","minor_units":2,"users":[{"id":"u_a","email":"a@x.io","password":"pw","handle":"a","balance":9},{"id":"u_b","email":"b@x.io","password":"pw","handle":"b","balance":1}],` +
			`"payments":[{"id":"p_1","from_user_id":"u_a","to_user_id":"u_b","amount":1,"created_at":` + v + `}]}`
	}
	for name, v := range map[string]string{
		"one hour ahead":       `"` + future + `"`,
		"a day ahead":          `"` + time.Now().UTC().Add(24*time.Hour).Format(time.RFC3339) + `"`,
		"year 2099":            `"2099-01-01T00:00:00+00:00"`,
		"offset makes it late": `"` + time.Now().UTC().Add(30*time.Minute).In(time.FixedZone("x", -3*3600)).Format(time.RFC3339) + `"`,
		"naive":                `"2026-09-20T10:00:00"`,
		"bare date":            `"2026-09-20"`,
		"empty string":         `""`,
		"space not T":          `"2026-09-20 10:00:00+00:00"`,
		"trailing junk":        `"2026-09-20T10:00:00+00:00 "`,
		"garbage":              `"yesterday"`,
		"number":               `1758362400`,
		"bool":                 `true`,
		"array":                `["2026-09-20T10:00:00+00:00"]`,
		"object":               `{}`,
	} {
		txResetRejected(t, name, pay(v))
	}
	// Absent and null are both "omitted".
	s := txReset(t, pay("null"))
	if e := s.Reset([]byte(pay(`"2026-09-20T10:00:00+00:00"`))); e != nil {
		t.Fatalf("a past created_at: %v", e.Message)
	}
	// The instant "now" itself is fine (not later than the reset instant): one second ago.
	ok := time.Now().UTC().Add(-time.Second).Format(time.RFC3339)
	if e := s.Reset([]byte(pay(`"` + ok + `"`))); e != nil {
		t.Fatalf("created_at a second ago: %v", e.Message)
	}
}

func TestResetBalancesAndOpeningBalances(t *testing.T) {
	s := txReset(t, txFx(tsHistory))
	st := tsExportState(t, s)
	users := tsUsers(t, st)
	for id, want := range map[string][2]float64{"u_ada": {1000, 1111}, "u_bob": {500, 415}, "u_cy": {100, 70}, "u_dee": {0, 4}} {
		if users[id]["balance"] != want[0] || users[id]["opening_balance"] != want[1] {
			t.Errorf("%s: balance %v opening %v, want %v", id, users[id]["balance"], users[id]["opening_balance"], want)
		}
	}
	if st["history_version"] != float64(3) {
		t.Fatalf("history_version %v", st["history_version"])
	}
	if len(st["revisions"].([]any)) != 6 {
		t.Fatalf("one revision 1 per seeded payment: %v", st["revisions"])
	}
	for _, r := range st["revisions"].([]any) {
		m := r.(map[string]any)
		if m["revision"] != float64(1) || m["effective_at"] != m["recorded_at"] || m["reason"] != "" {
			t.Fatalf("revision: %v", m)
		}
	}
	// /me after loading the history is the seeded balance; as_of walks it back to the opening.
	e := tsNew(t, tsHistory)
	for user, want := range map[string]float64{"ada": 1000, "bob": 500, "cy": 100, "dee": 0} {
		if got := e.me(user, "")["balance"]; got != want {
			t.Errorf("/me %s = %v, want %v", user, got, want)
		}
	}
	if got := e.me("ada", tsQ("as_of", "2026-09-20T09:59:59+00:00"))["balance"]; got != float64(1111) {
		t.Errorf("as_of before the first payment is the opening balance: %v", got)
	}
	if got := e.me("ada", tsQ("as_of", "2026-09-20T10:00:00+00:00"))["balance"]; got != float64(1011) {
		t.Errorf("a payment exactly at as_of counts: %v", got)
	}
	// A signed-up user opens at zero.
	ttSignup(t, s, "zero@example.com")
	for id, u := range tsUsers(t, tsExportState(t, s)) {
		if strings.HasPrefix(id, "u_") && u["email"] == "zero@example.com" && u["opening_balance"] != float64(0) {
			t.Fatalf("new account opens at zero: %v", u)
		}
	}
}

func TestResetOpeningBalanceToleratesNegativeDerivedOpening(t *testing.T) {
	// ada's balance is 5 but she is seeded as having paid 20: she opened at 25. bob opened at -20 (tolerated).
	raw := `{"currency":"EUR","minor_units":2,"users":[` +
		`{"id":"u_a","email":"a@x.io","password":"pw","handle":"a","balance":5},` +
		`{"id":"u_b","email":"b@x.io","password":"pw","handle":"b","balance":0}],` +
		`"payments":[{"id":"p_1","from_user_id":"u_b","to_user_id":"u_a","amount":20,"created_at":"2026-09-20T10:00:00+00:00"}]}`
	s := txReset(t, raw)
	users := tsUsers(t, tsExportState(t, s))
	if users["u_a"]["opening_balance"] != float64(-15) || users["u_b"]["opening_balance"] != float64(20) {
		t.Fatalf("openings: %v %v", users["u_a"]["opening_balance"], users["u_b"]["opening_balance"])
	}
}

func TestResetSeededHoldsHaveCreatedAtAndClosedAt(t *testing.T) {
	const past = "2026-09-20T09:00:00+00:00"
	fx := txFx(`"payments":[{"id":"p_cap","from_user_id":"u_ada","to_user_id":"u_bob","amount":30,"created_at":"2026-09-20T10:00:00+00:00","note":"seeded capture"}]`,
		txAuths(
			txA("a_open", "open", 100, txFuture, `"created_at":"`+past+`"`),
			txA("a_open_now", "open", 50, txFuture, ""),
			txA("a_exp", "expired", 10, txPast, `"created_at":"`+past+`"`),
			txA("a_void", "voided", 10, txFuture, `"created_at":"`+past+`"`),
			txA("a_cap", "captured", 30, txFuture, `"created_at":"`+past+`","payment_ids":["p_cap"]`),
			txA("a_exp_open", "open", 20, txPast, `"created_at":"`+past+`"`),
		))
	before := time.Now().UTC().Add(-2 * time.Second)
	s := txReset(t, fx)
	bodies := map[string]map[string]any{}
	for _, a := range txList(t, s, "u_ada", "", "", time.Now()) {
		bodies[a["authorization_id"].(string)] = a
	}
	for id, want := range map[string]any{
		"a_open": nil, "a_open_now": nil,
		"a_exp":      txPast,
		"a_void":     past,
		"a_cap":      past,
		"a_exp_open": txPast, // stored open but past its deadline: derived
	} {
		if got := bodies[id]["closed_at"]; got != want {
			t.Errorf("%s closed_at = %v, want %v", id, got, want)
		}
	}
	if bodies["a_open"]["created_at"] != past || bodies["a_void"]["created_at"] != past {
		t.Errorf("supplied created_at kept verbatim: %v %v", bodies["a_open"]["created_at"], bodies["a_void"]["created_at"])
	}
	// Omitted: the reset instant, whole seconds as in stage 2.
	def := bodies["a_open_now"]["created_at"].(string)
	d, ok := ParseInstant(def)
	if !ok || strings.Contains(def, ".") || d.Before(before) || d.After(time.Now().UTC().Add(time.Second)) {
		t.Fatalf("omitted authorization created_at = %q", def)
	}
	// The export keeps the persisted closed_at: expiry by clock is derived, never stored.
	exp := map[string]map[string]any{}
	for _, a := range tsExportState(t, s)["authorizations"].([]any) {
		m := a.(map[string]any)
		exp[m["authorization_id"].(string)] = m
	}
	if exp["a_exp_open"]["closed_at"] != nil || exp["a_open"]["closed_at"] != nil || exp["a_exp"]["closed_at"] != txPast || exp["a_cap"]["closed_at"] != past {
		t.Fatalf("persisted closed_at: %v", exp)
	}
	// A seeded hold in the future is refused like a future payment.
	txResetRejected(t, "future hold created_at", txFx(txAuths(txA("a_f", "open", 1, txFuture, `"created_at":"2099-01-01T00:00:00+00:00"`))))
	txResetRejected(t, "naive hold created_at", txFx(txAuths(txA("a_f", "open", 1, txFuture, `"created_at":"2026-09-20T10:00:00"`))))
}

func TestResetSeededHoldsInHistoricalViews(t *testing.T) {
	const past = "2026-09-20T09:00:00+00:00"
	e := tsNew(t, txAuths(
		txA("a_open", "open", 100, txFuture, `"created_at":"`+past+`"`),
		txA("a_exp", "expired", 40, txFuture, `"created_at":"`+past+`"`),
	))
	for _, c := range []struct {
		asOf     string
		held     float64
		avail    float64
		scenario string
	}{
		{"2026-09-20T08:59:59+00:00", 0, 1000, "before the hold existed"},
		{past, 100, 900, "at creation (inclusive), the expired one holds nothing"},
		{"2026-10-01T00:00:00+00:00", 100, 900, "still open"},
		{"2100-01-01T00:00:00+00:00", 0, 1000, "past the deadline"},
	} {
		me := e.me("ada", tsQ("as_of", c.asOf))
		if me["held"] != c.held || me["available"] != c.avail || me["total"] != float64(1000) || me["balance"] != float64(1000) {
			t.Errorf("%s: %v", c.scenario, me)
		}
	}
	// Known only before the hold was created in the record: nothing held.
	if me := e.me("ada", tsQ("as_of", "2026-10-01T00:00:00+00:00", "known_at", "2026-09-20T08:00:00+00:00")); me["held"] != float64(0) {
		t.Errorf("hold unknown at known_at: %v", me)
	}
}

func TestResetSeedsEveryStoredFactAndRoundTripsByteForByte(t *testing.T) {
	s := txReset(t, txFx(tsHistory, txAuths(txA("a_1", "open", 100, txFuture, `"created_at":"2026-09-20T09:00:00+00:00"`))))
	e1 := ttExport(t, s)
	if err := s.Import(e1); err != nil {
		t.Fatalf("import of a fresh export: %v", err.Message)
	}
	if e2 := ttExport(t, s); !bytes.Equal(e1, e2) {
		t.Fatalf("export differs after import:\n%s\n%s", e1, e2)
	}
}
