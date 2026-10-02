package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"testing"
	"time"
)

// Statement behaviour through the real HTTP handlers. History is seeded with explicit past
// created_at values so windows, ties and balances are deterministic; later activity is real.

// tsHistory: ada nets -111 (opening 1111), bob +85 (415), cy +30 (70), dee -4 (4). Ties: p_10 and
// p_9 take effect at the same instant; "p_10" sorts before "p_9" bytewise.
const tsHistory = `"payments":[
 {"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"note":"a","created_at":"2026-09-20T10:00:00+00:00"},
 {"id":"p_2","from_user_id":"u_bob","to_user_id":"u_cy","amount":40,"note":"b","visibility":"private","created_at":"2026-09-20T11:00:00+00:00"},
 {"id":"p_3","from_user_id":"u_ada","to_user_id":"u_bob","amount":25,"created_at":"2026-09-20T13:00:00+02:00"},
 {"id":"p_11","from_user_id":"u_ada","to_user_id":"u_dee","amount":1,"created_at":"2026-09-21T09:00:00.500000+00:00"},
 {"id":"p_9","from_user_id":"u_cy","to_user_id":"u_ada","amount":10,"created_at":"2026-09-22T08:00:00+00:00"},
 {"id":"p_10","from_user_id":"u_dee","to_user_id":"u_ada","amount":5,"created_at":"2026-09-22T10:00:00+02:00"}]`

type tsEntry struct {
	Payment      map[string]any `json:"payment"`
	Delta        int64          `json:"delta"`
	BalanceAfter int64          `json:"balance_after"`
	Revision     int64          `json:"revision"`
	EffectiveAt  string         `json:"effective_at"`
	RecordedAt   string         `json:"recorded_at"`
}

type tsStmt struct {
	OpeningBalance int64     `json:"opening_balance"`
	Entries        []tsEntry `json:"entries"`
	ClosingBalance int64     `json:"closing_balance"`
	HasMore        bool      `json:"has_more"`
	Snapshot       string    `json:"snapshot"`
	raw            []byte
}

func (s tsStmt) ids() []string {
	out := make([]string, len(s.Entries))
	for i, e := range s.Entries {
		out[i], _ = e.Payment["payment_id"].(string)
	}
	return out
}

type tsEnv struct {
	t   testing.TB
	h   http.Handler
	tok map[string]string
}

func tsNew(t testing.TB, extra ...string) *tsEnv {
	h, tok := txServerFx(t, txFx(extra...))
	return &tsEnv{t: t, h: h, tok: tok}
}

func (e *tsEnv) do(user, method, path, key, body string) *httptest.ResponseRecorder {
	return txDo(e.h, method, path, e.tok[user], key, body)
}

func (e *tsEnv) stmt(user, query string) tsStmt {
	e.t.Helper()
	rec := e.do(user, "GET", "/statement"+query, "", "")
	if rec.Code != 200 {
		e.t.Fatalf("GET /statement%s as %s: %d %s", query, user, rec.Code, rec.Body)
	}
	var s tsStmt
	if err := json.Unmarshal(rec.Body.Bytes(), &s); err != nil {
		e.t.Fatalf("statement is not JSON: %v: %s", err, rec.Body)
	}
	s.raw = rec.Body.Bytes()
	return s
}

func (e *tsEnv) stmtErr(user, query string, status int, code string) {
	e.t.Helper()
	txWantErr(e.t, "GET /statement"+query+" as "+user, e.do(user, "GET", "/statement"+query, "", ""), status, code)
}

func (e *tsEnv) me(user, query string) map[string]any {
	e.t.Helper()
	rec := e.do(user, "GET", "/me"+query, "", "")
	if rec.Code != 200 {
		e.t.Fatalf("GET /me%s as %s: %d %s", query, user, rec.Code, rec.Body)
	}
	return txJSON(e.t, rec.Body.Bytes())
}

func (e *tsEnv) pay(user, key, to string, amount int) map[string]any {
	e.t.Helper()
	rec := e.do(user, "POST", "/payments", key, fmt.Sprintf(`{"to_handle":%q,"amount":%d}`, to, amount))
	return txJSON(e.t, txWant(e.t, "pay "+key, rec, 201))
}

func tsQ(kv ...string) string {
	v := url.Values{}
	for i := 0; i+1 < len(kv); i += 2 {
		v.Add(kv[i], kv[i+1])
	}
	return "?" + v.Encode()
}

func tsDeltas(s tsStmt) int64 {
	var sum int64
	for _, e := range s.Entries {
		sum += e.Delta
	}
	return sum
}

var tsSnapRe = regexp.MustCompile(`^snap_[0-9a-f]{32}$`)

func TestStatementShapeAndFullWindow(t *testing.T) {
	e := tsNew(t, tsHistory)
	rec := e.do("ada", "GET", "/statement", "", "")
	if rec.Code != 200 {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	var top map[string]json.RawMessage
	_ = json.Unmarshal(rec.Body.Bytes(), &top)
	keys := make([]string, 0, len(top))
	for k := range top {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if !reflect.DeepEqual(keys, []string{"closing_balance", "entries", "has_more", "opening_balance", "snapshot"}) {
		t.Fatalf("top-level keys %v", keys)
	}
	s := e.stmt("ada", "")
	if !tsSnapRe.MatchString(s.Snapshot) {
		t.Fatalf("snapshot token %q", s.Snapshot)
	}
	var first map[string]json.RawMessage
	var entries []json.RawMessage
	_ = json.Unmarshal(top["entries"], &entries)
	_ = json.Unmarshal(entries[0], &first)
	ek := make([]string, 0, len(first))
	for k := range first {
		ek = append(ek, k)
	}
	sort.Strings(ek)
	if !reflect.DeepEqual(ek, []string{"balance_after", "delta", "effective_at", "payment", "recorded_at", "revision"}) {
		t.Fatalf("entry keys %v", ek)
	}

	// Oldest first by effective instant, ties by payment id bytewise ("p_10" < "p_9").
	if got, want := s.ids(), []string{"p_1", "p_3", "p_11", "p_10", "p_9"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("order %v, want %v", got, want)
	}
	wantDelta := []int64{-100, -25, -1, 5, 10}
	wantAfter := []int64{1011, 986, 985, 990, 1000}
	for i, en := range s.Entries {
		if en.Delta != wantDelta[i] || en.BalanceAfter != wantAfter[i] || en.Revision != 1 {
			t.Fatalf("entry %d: delta %d after %d revision %d", i, en.Delta, en.BalanceAfter, en.Revision)
		}
		if en.EffectiveAt != en.RecordedAt || en.EffectiveAt != en.Payment["created_at"] {
			t.Fatalf("entry %d: revision 1 must be effective and recorded at created_at verbatim: %+v", i, en)
		}
	}
	if s.OpeningBalance != 1111 || s.ClosingBalance != 1000 || s.HasMore {
		t.Fatalf("opening %d closing %d has_more %v", s.OpeningBalance, s.ClosingBalance, s.HasMore)
	}
	if s.OpeningBalance+tsDeltas(s) != s.ClosingBalance {
		t.Fatal("opening + deltas != closing")
	}
	if got := s.Entries[3].Payment["created_at"]; got != "2026-09-22T10:00:00+02:00" {
		t.Fatalf("created_at must be echoed exactly as seeded, got %v", got)
	}
	if got := s.Entries[2].Payment["created_at"]; got != "2026-09-21T09:00:00.500000+00:00" {
		t.Fatalf("fractional created_at: %v", got)
	}
}

func TestStatementOnlyOwnPaymentsPrivateIncluded(t *testing.T) {
	e := tsNew(t, tsHistory)
	// p_2 is private bob->cy; p_1 is public ada->bob.
	for user, want := range map[string][]string{
		"ada": {"p_1", "p_3", "p_11", "p_10", "p_9"},
		"bob": {"p_1", "p_2", "p_3"},
		"cy":  {"p_2", "p_9"},
		"dee": {"p_11", "p_10"},
	} {
		if got := e.stmt(user, "").ids(); !reflect.DeepEqual(got, want) {
			t.Errorf("%s: %v, want %v", user, got, want)
		}
	}
	bob := e.stmt("bob", "")
	if bob.OpeningBalance != 415 || bob.ClosingBalance != 500 {
		t.Fatalf("bob opening %d closing %d", bob.OpeningBalance, bob.ClosingBalance)
	}
	if bob.Entries[1].Delta != -40 || bob.Entries[1].Payment["visibility"] != "private" {
		t.Fatalf("bob sees his private payment: %+v", bob.Entries[1])
	}
	// The public payment of strangers never appears, however public.
	if _, ok := e.stmt("dee", "").Entries[0].Payment["note"]; !ok {
		t.Fatal("payment body missing")
	}
}

func TestStatementWindowIsHalfOpen(t *testing.T) {
	e := tsNew(t, tsHistory)
	cases := []struct {
		name, query string
		ids         []string
		opening     int64
		closing     int64
	}{
		{"from inclusive", tsQ("from", "2026-09-20T11:00:00+00:00"), []string{"p_3", "p_11", "p_10", "p_9"}, 1011, 1000},
		{"from just after", tsQ("from", "2026-09-20T11:00:00.000001+00:00"), []string{"p_11", "p_10", "p_9"}, 986, 1000},
		{"to exclusive", tsQ("to", "2026-09-22T08:00:00+00:00"), []string{"p_1", "p_3", "p_11"}, 1111, 985},
		{"to just after", tsQ("to", "2026-09-22T08:00:00.000001+00:00"), []string{"p_1", "p_3", "p_11", "p_10", "p_9"}, 1111, 1000},
		{"both", tsQ("from", "2026-09-20T11:00:00+00:00", "to", "2026-09-22T08:00:00+00:00"), []string{"p_3", "p_11"}, 1011, 985},
		{"offset form", tsQ("from", "2026-09-20T13:00:00+02:00", "to", "2026-09-22T10:00:00+02:00"), []string{"p_3", "p_11"}, 1011, 985},
		{"Z and lowercase z", tsQ("from", "2026-09-20T11:00:00Z", "to", "2026-09-22T08:00:00z"), []string{"p_3", "p_11"}, 1011, 985},
		{"empty window from==to", tsQ("from", "2026-09-21T00:00:00+00:00", "to", "2026-09-21T00:00:00+00:00"), []string{}, 986, 986},
		{"window before everything", tsQ("to", "2026-09-20T10:00:00+00:00"), []string{}, 1111, 1111},
		{"window after everything", tsQ("from", "2026-12-01T00:00:00+00:00", "to", "2027-01-01T00:00:00+00:00"), []string{}, 1000, 1000},
		{"from in the future, to omitted", tsQ("from", "2099-01-01T00:00:00+00:00"), []string{}, 1000, 1000},
		{"to in the future", tsQ("to", "2099-01-01T00:00:00+00:00"), []string{"p_1", "p_3", "p_11", "p_10", "p_9"}, 1111, 1000},
		{"tie group split by from", tsQ("from", "2026-09-22T08:00:00+00:00"), []string{"p_10", "p_9"}, 985, 1000},
	}
	for _, c := range cases {
		s := e.stmt("ada", c.query)
		if got := s.ids(); !reflect.DeepEqual(got, c.ids) {
			t.Errorf("%s: entries %v, want %v", c.name, got, c.ids)
		}
		if s.OpeningBalance != c.opening || s.ClosingBalance != c.closing || s.OpeningBalance+tsDeltas(s) != s.ClosingBalance {
			t.Errorf("%s: opening %d closing %d (deltas %d), want %d and %d", c.name, s.OpeningBalance, s.ClosingBalance, tsDeltas(s), c.opening, c.closing)
		}
		if s.Entries == nil || len(s.raw) == 0 || !strings.Contains(string(s.raw), `"entries":[`) {
			t.Errorf("%s: entries must be an array, got %s", c.name, s.raw)
		}
	}
	// balance_after runs over the window from its opening balance.
	s := e.stmt("ada", tsQ("from", "2026-09-20T11:00:00+00:00"))
	if s.Entries[0].BalanceAfter != 986 || s.Entries[3].BalanceAfter != 1000 {
		t.Fatalf("balance_after in a window: %+v", s.Entries)
	}
}

func TestStatementEdgesMatchMeAsOf(t *testing.T) {
	e := tsNew(t, tsHistory)
	from, to := "2026-09-20T11:00:00+00:00", "2026-09-22T08:00:00+00:00"
	s := e.stmt("ada", tsQ("from", from, "to", to))
	before := func(ts string) string {
		tt, _ := ParseInstant(ts)
		return FormatMicro(tt.Add(-time.Microsecond))
	}
	if got := e.me("ada", tsQ("as_of", before(from)))["total"]; int64(got.(float64)) != s.OpeningBalance {
		t.Fatalf("opening %d != /me just before from: %v", s.OpeningBalance, got)
	}
	if got := e.me("ada", tsQ("as_of", before(to)))["total"]; int64(got.(float64)) != s.ClosingBalance {
		t.Fatalf("closing %d != /me just before to: %v", s.ClosingBalance, got)
	}
	// Each entry that ends a tie group matches /me as_of its effective instant.
	full := e.stmt("ada", "")
	for i, en := range full.Entries {
		this, _ := ParseInstant(en.EffectiveAt)
		next, ok := time.Time{}, false
		if i+1 < len(full.Entries) {
			next, ok = ParseInstant(full.Entries[i+1].EffectiveAt)
		}
		if ok && next.Equal(this) {
			continue
		}
		if got := e.me("ada", tsQ("as_of", en.EffectiveAt))["balance"]; int64(got.(float64)) != en.BalanceAfter {
			t.Errorf("entry %d balance_after %d != /me as_of %s = %v", i, en.BalanceAfter, en.EffectiveAt, got)
		}
	}
}

func TestStatementPagingKeepsEveryValue(t *testing.T) {
	e := tsNew(t, tsHistory)
	full := e.stmt("ada", "")
	var joined []tsEntry
	flags := []bool{}
	for off := 0; off < 8; off += 2 {
		p := e.stmt("ada", tsQ("limit", "2", "offset", fmt.Sprint(off)))
		if p.OpeningBalance != full.OpeningBalance || p.ClosingBalance != full.ClosingBalance {
			t.Fatalf("offset %d changed opening/closing: %d/%d", off, p.OpeningBalance, p.ClosingBalance)
		}
		joined = append(joined, p.Entries...)
		flags = append(flags, p.HasMore)
		if p.Entries == nil || !strings.Contains(string(p.raw), `"entries":[`) {
			t.Fatalf("offset %d: entries must be an array: %s", off, p.raw)
		}
	}
	if !reflect.DeepEqual(joined, full.Entries) {
		t.Fatalf("pages joined differ from the full statement:\n%+v\n%+v", joined, full.Entries)
	}
	// offsets 0, 2: more remain; 4: the last partial page; 6: beyond the end.
	if !reflect.DeepEqual(flags, []bool{true, true, false, false}) {
		t.Fatalf("has_more %v", flags)
	}
	if p := e.stmt("ada", tsQ("limit", "5")); p.HasMore || len(p.Entries) != 5 {
		t.Fatalf("exact fit must not report more: %+v", p)
	}
	if p := e.stmt("ada", tsQ("limit", "4")); !p.HasMore || len(p.Entries) != 4 {
		t.Fatalf("one left over must report more: %+v", p)
	}
	if p := e.stmt("ada", tsQ("limit", "1", "offset", "4")); p.HasMore || len(p.Entries) != 1 {
		t.Fatalf("last entry: %+v", p)
	}
	if p := e.stmt("ada", tsQ("offset", "2147483647")); p.HasMore || len(p.Entries) != 0 || p.ClosingBalance != 1000 {
		t.Fatalf("offset beyond the end: %+v", p)
	}
	for _, bad := range []string{"limit=0", "limit=201", "limit=-1", "limit=x", "limit=", "offset=-1", "offset=1.5", "offset="} {
		e.stmtErr("ada", "?"+bad, 422, "validation_failed")
	}
	if p := e.stmt("ada", tsQ("limit", "200")); len(p.Entries) != 5 {
		t.Fatal("limit 200 is allowed")
	}
}

func TestStatementValidation(t *testing.T) {
	e := tsNew(t, tsHistory)
	for _, name := range []string{"from", "to", "known_at"} {
		for _, bad := range []string{"", "2026-09-20", "2026-09-20T10:00:00", "2026-09-20 10:00:00+00:00", "yesterday",
			"2026-09-20T10:00:00+00:00x", "2026-13-20T10:00:00+00:00", "2026-09-20T25:00:00+00:00", "1758362400", "2026-09-20T10:00:00+0000"} {
			e.stmtErr("ada", tsQ(name, bad), 422, "validation_failed")
		}
	}
	// from after to is a 422; from == to is just empty (covered above).
	e.stmtErr("ada", tsQ("from", "2026-09-22T00:00:00+00:00", "to", "2026-09-21T00:00:00+00:00"), 422, "validation_failed")
	// Offsets, not only UTC, order the instants: 10:00+02:00 is 08:00Z, before 09:00Z.
	e.stmtErr("ada", tsQ("from", "2026-09-22T09:00:00+00:00", "to", "2026-09-22T10:00:00+02:00"), 422, "validation_failed")
	// Unrecognised parameters are ignored.
	if got := e.stmt("ada", tsQ("colour", "red", "limit", "1")); len(got.Entries) != 1 {
		t.Fatal("extra params must be ignored")
	}
	rec := e.h
	for _, c := range []struct {
		token, want string
	}{{"", "unauthenticated"}, {"nope", "unauthenticated"}} {
		r := txDo(rec, "GET", "/statement", c.token, "", "")
		txWantErr(t, "token "+c.token, r, 401, c.want)
	}
}

func TestStatementKnownAtSelectsRecordedRevisions(t *testing.T) {
	e := tsNew(t, tsHistory)
	// Seeded payments were recorded when they happened: before that they contribute nothing.
	none := e.stmt("ada", tsQ("known_at", "2026-09-20T09:59:59+00:00"))
	if len(none.Entries) != 0 || none.OpeningBalance != 1111 || none.ClosingBalance != 1111 {
		t.Fatalf("known before everything: %+v", none)
	}
	one := e.stmt("ada", tsQ("known_at", "2026-09-20T10:00:00+00:00")) // at or before: inclusive
	if !reflect.DeepEqual(one.ids(), []string{"p_1"}) || one.ClosingBalance != 1011 {
		t.Fatalf("known exactly at p_1's recording: %+v", one)
	}
	two := e.stmt("ada", tsQ("known_at", "2026-09-21T10:00:00+00:00"))
	if !reflect.DeepEqual(two.ids(), []string{"p_1", "p_3", "p_11"}) || two.ClosingBalance != 985 {
		t.Fatalf("known mid-history: %+v", two)
	}
	// Future known_at and as_of are allowed and mean everything.
	if got := e.stmt("ada", tsQ("known_at", "2099-01-01T00:00:00+00:00")); got.ClosingBalance != 1000 {
		t.Fatalf("future known_at: %+v", got)
	}
	// The statement and /me agree for the same (to, known_at).
	me := e.me("ada", tsQ("known_at", "2026-09-21T10:00:00+00:00", "as_of", "2026-12-01T00:00:00+00:00"))
	if int64(me["total"].(float64)) != two.ClosingBalance {
		t.Fatalf("/me and statement disagree under known_at: %v vs %d", me["total"], two.ClosingBalance)
	}
	// Sum of every wallet's total is the seeded sum in every view.
	for _, view := range []string{tsQ("known_at", "2026-09-20T10:30:00+00:00"), tsQ("as_of", "2026-09-21T00:00:00+00:00"),
		tsQ("as_of", "2026-09-20T10:00:00+00:00", "known_at", "2026-09-22T00:00:00+00:00"), ""} {
		var sum int64
		for _, u := range []string{"ada", "bob", "cy", "dee"} {
			sum += int64(e.me(u, view)["total"].(float64))
		}
		if sum != txSeeded {
			t.Errorf("view %q: totals sum to %d, want %d", view, sum, txSeeded)
		}
	}
}

func TestStatementSnapshotFreezesTheResult(t *testing.T) {
	e := tsNew(t, tsHistory)
	first := e.stmt("ada", tsQ("limit", "2"))
	if !tsSnapRe.MatchString(first.Snapshot) || len(first.Entries) != 2 || !first.HasMore {
		t.Fatalf("first page: %+v", first)
	}
	full := e.stmt("ada", "")
	if full.Snapshot == first.Snapshot {
		t.Fatal("every read mints its own token")
	}

	// Everything that can change: a payment in, an authorization, a capture, a void, a payment out.
	e.pay("ada", "m1", "bob", 7)
	e.pay("bob", "m2", "ada", 3)
	hold := txJSON(t, txWant(t, "authorize", e.do("ada", "POST", "/authorizations", "m3", `{"to_handle":"bob","amount":50}`), 201))["authorization_id"].(string)
	txWant(t, "capture", e.do("bob", "POST", "/authorizations/"+hold+"/capture", "m4", `{"amount":20,"final":false}`), 201)
	txWant(t, "void", e.do("ada", "POST", "/authorizations/"+hold+"/void", "", ""), 200)

	var joined []tsEntry
	for off := 0; off < 6; off += 2 {
		p := e.stmt("ada", tsQ("snapshot", first.Snapshot, "limit", "2", "offset", fmt.Sprint(off)))
		if p.Snapshot != first.Snapshot {
			t.Fatalf("a snapshot page carries its token: %q", p.Snapshot)
		}
		if p.OpeningBalance != full.OpeningBalance || p.ClosingBalance != full.ClosingBalance {
			t.Fatalf("snapshot offset %d moved opening/closing to %d/%d", off, p.OpeningBalance, p.ClosingBalance)
		}
		if p.HasMore != (off+2 < 5) {
			t.Fatalf("snapshot offset %d has_more %v", off, p.HasMore)
		}
		joined = append(joined, p.Entries...)
	}
	if !reflect.DeepEqual(joined, full.Entries) {
		t.Fatalf("snapshot pages differ from the statement it froze:\n%+v\n%+v", joined, full.Entries)
	}
	// Default limit on a snapshot page.
	if p := e.stmt("ada", tsQ("snapshot", first.Snapshot)); len(p.Entries) != 5 || p.HasMore {
		t.Fatalf("default limit: %+v", p)
	}
	// A fresh read now sees the new world, the old snapshot does not.
	now := e.stmt("ada", "")
	if now.ClosingBalance == full.ClosingBalance || len(now.Entries) != 5+3 {
		t.Fatalf("fresh statement should show the new payments and the capture: %+v", now.ids())
	}
	// Authorize and void are not payments; the capture appears exactly once, with its link.
	links := 0
	for _, en := range now.Entries {
		if en.Payment["authorization_id"] == hold {
			links++
			if en.Delta != -20 {
				t.Fatalf("capture delta %d", en.Delta)
			}
		}
	}
	if links != 1 {
		t.Fatalf("capture appears %d times", links)
	}
}

func TestStatementSnapshotErrors(t *testing.T) {
	e := tsNew(t, tsHistory)
	snap := e.stmt("ada", "").Snapshot
	for _, c := range []struct {
		name, user, query string
		status            int
		code              string
	}{
		{"unknown token", "ada", tsQ("snapshot", "snap_00000000000000000000000000000000"), 404, "not_found"},
		{"garbage token", "ada", tsQ("snapshot", "x"), 404, "not_found"},
		{"another user's token", "bob", tsQ("snapshot", snap), 404, "not_found"},
		{"empty token", "ada", tsQ("snapshot", ""), 422, "validation_failed"},
		{"from with token", "ada", tsQ("snapshot", snap, "from", "2026-09-20T10:00:00+00:00"), 422, "validation_failed"},
		{"to with token", "ada", tsQ("snapshot", snap, "to", "2026-09-20T10:00:00+00:00"), 422, "validation_failed"},
		{"known_at with token", "ada", tsQ("snapshot", snap, "known_at", "2026-09-20T10:00:00+00:00"), 422, "validation_failed"},
		{"even an invalid from with token", "ada", tsQ("snapshot", snap, "from", "junk"), 422, "validation_failed"},
		{"422 beats 404: from with an unknown token", "ada", tsQ("snapshot", "snap_nope", "from", "2026-09-20T10:00:00+00:00"), 422, "validation_failed"},
		{"bad limit beats 404", "ada", tsQ("snapshot", "snap_nope", "limit", "0"), 422, "validation_failed"},
		{"bad offset with a real token", "ada", tsQ("snapshot", snap, "offset", "-1"), 422, "validation_failed"},
	} {
		txWantErr(t, c.name, e.do(c.user, "GET", "/statement"+c.query, "", ""), c.status, c.code)
	}
	// The owner still reads it; limit/offset may accompany it.
	if p := e.stmt("ada", tsQ("snapshot", snap, "limit", "1", "offset", "1")); len(p.Entries) != 1 || p.Entries[0].Payment["payment_id"] != "p_3" {
		t.Fatalf("owner page: %+v", p)
	}
	// Extra params are ignored on a snapshot page too.
	if p := e.stmt("ada", tsQ("snapshot", snap, "colour", "red")); len(p.Entries) != 5 {
		t.Fatalf("extra params: %+v", p)
	}
	// No token at all: 401 before anything else.
	txWantErr(t, "no token", txDo(e.h, "GET", "/statement?snapshot="+snap, "", "", ""), 401, "unauthenticated")
}

func TestStatementSnapshotsDieWithResetAndImport(t *testing.T) {
	h, tok := txServerFx(t, txFx(tsHistory))
	get := func(snap string) *httptest.ResponseRecorder {
		return txDo(h, "GET", "/statement?snapshot="+snap, tok["ada"], "", "")
	}
	read := func() string {
		rec := txDo(h, "GET", "/statement", tok["ada"], "", "")
		return txJSON(t, txWant(t, "statement", rec, 200))["snapshot"].(string)
	}
	a := read()
	txWant(t, "snapshot readable", get(a), 200)
	exp := txWant(t, "export", txDo(h, "GET", "/_test/export", "", "", ""), 200)
	// A rejected import changes nothing, snapshots included.
	if rec := txDo(h, "POST", "/_test/import", "", "", `{"track":"nope"}`); rec.Code != 422 {
		t.Fatalf("bad import: %d", rec.Code)
	}
	txWant(t, "snapshot survives a refused import", get(a), 200)
	if rec := txDo(h, "POST", "/_test/import", "", "", string(exp)); rec.Code != 204 {
		t.Fatalf("import: %d %s", rec.Code, rec.Body)
	}
	txWantErr(t, "snapshot after import", get(a), 404, "not_found")
	// Tokens of the export survive, so the same caller reads again and mints a new snapshot.
	b := read()
	txWant(t, "new snapshot", get(b), 200)
	if rec := txDo(h, "POST", "/_test/reset", "", "", txFx(tsHistory)); rec.Code != 204 {
		t.Fatalf("reset: %d", rec.Code)
	}
	// A reset re-seeds the same users, so the caller logs in again; the old snapshot is gone.
	login := txDo(h, "POST", "/auth/login", "", "", `{"email":"ada@example.com","password":"correct horse"}`)
	fresh := txJSON(t, txWant(t, "login", login, 200))["token"].(string)
	rec := txDo(h, "GET", "/statement?snapshot="+b, fresh, "", "")
	txWantErr(t, "snapshot after reset", rec, 404, "not_found")
	txWantErr(t, "old bearer token after reset", get(b), 401, "unauthenticated")
}

func TestStatementRefusedResetKeepsSnapshots(t *testing.T) {
	s := txReset(t, txFx(tsHistory))
	var snap string
	b, e := s.Exec(func(st *State) (any, *AppError) {
		return st.Statement("u_ada", StatementQuery{Limit: 50}, time.Now())
	})
	if e != nil {
		t.Fatal(e.Message)
	}
	snap = txJSON(t, b)["snapshot"].(string)
	if e := s.Reset([]byte(`{"currency":""}`)); e == nil {
		t.Fatal("reset must be refused")
	}
	if _, e := s.Exec(func(st *State) (any, *AppError) {
		return st.Statement("u_ada", StatementQuery{Snapshot: &snap, Limit: 50}, time.Now())
	}); e != nil {
		t.Fatalf("a refused reset must not drop snapshots: %v", e.Message)
	}
}

func TestStatementEmptyWalletAndNewUser(t *testing.T) {
	e := tsNew(t)
	s := e.stmt("ada", "")
	if len(s.Entries) != 0 || s.OpeningBalance != 1000 || s.ClosingBalance != 1000 || s.HasMore {
		t.Fatalf("wallet without payments: %+v", s)
	}
	// A signed-up user opens at zero and statements follow what they do.
	sign := txDo(e.h, "POST", "/auth/signup", "", "", `{"email":"new@example.com","password":"long enough pw","display_name":"New"}`)
	tok := txJSON(t, txWant(t, "signup", sign, 201))["token"].(string)
	get := func(q string) tsStmt {
		rec := txDo(e.h, "GET", "/statement"+q, tok, "", "")
		var out tsStmt
		if err := json.Unmarshal(txWant(t, "statement", rec, 200), &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	if s := get(""); s.OpeningBalance != 0 || s.ClosingBalance != 0 || len(s.Entries) != 0 {
		t.Fatalf("new user: %+v", s)
	}
	handle := txJSON(t, txWant(t, "me", txDo(e.h, "GET", "/me", tok, "", ""), 200))["handle"].(string)
	e.pay("ada", "g1", handle, 40)
	if s := get(""); s.OpeningBalance != 0 || s.ClosingBalance != 40 || len(s.Entries) != 1 || s.Entries[0].Delta != 40 {
		t.Fatalf("after a payment in: %+v", s)
	}
}

func TestStatementSelfPaymentSeededNetsToZero(t *testing.T) {
	e := tsNew(t, `"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_ada","amount":30,"created_at":"2026-09-20T10:00:00+00:00"}]`)
	s := e.stmt("ada", "")
	if s.OpeningBalance != 1000 || s.ClosingBalance != 1000 || tsDeltas(s) != 0 {
		t.Fatalf("a seeded self payment moves nothing: %+v", s)
	}
}

func TestStatementTwoSnapshotsOfDifferentUsersAreIndependent(t *testing.T) {
	e := tsNew(t, tsHistory)
	a, b := e.stmt("ada", "").Snapshot, e.stmt("bob", "").Snapshot
	if pa := e.stmt("ada", tsQ("snapshot", a)); len(pa.Entries) != 5 {
		t.Fatal("ada's snapshot")
	}
	if pb := e.stmt("bob", tsQ("snapshot", b)); len(pb.Entries) != 3 {
		t.Fatal("bob's snapshot")
	}
	e.stmtErr("ada", tsQ("snapshot", b), 404, "not_found")
	e.stmtErr("bob", tsQ("snapshot", a), 404, "not_found")
}
