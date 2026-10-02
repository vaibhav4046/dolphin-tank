package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"
)

// Statements and historical reads under corrections, plus attacks on the correction and hold
// timelines. Every expectation is derived from the written stage-3 requirements.

type tsRev struct {
	PaymentID   string `json:"payment_id"`
	Revision    int64  `json:"revision"`
	Amount      int64  `json:"amount"`
	EffectiveAt string `json:"effective_at"`
	RecordedAt  string `json:"recorded_at"`
	Reason      string `json:"reason"`
}

// tsFxU is a fixture of the four standard users with the given balances (ada, bob, cy, dee).
func tsFxU(bal [4]int64, extra ...string) string {
	var us []string
	for i, n := range []string{"ada", "bob", "cy", "dee"} {
		us = append(us, fmt.Sprintf(`{"id":"u_%s","email":"%s@example.com","password":"correct horse","display_name":%q,"handle":%q,"balance":%d}`,
			n, n, strings.ToUpper(n[:1])+n[1:], n, bal[i]))
	}
	parts := append([]string{`"currency":"EUR"`, `"minor_units":2`, `"settlement_operator_ids":["u_ada"]`, `"users":[` + strings.Join(us, ",") + `]`}, extra...)
	return "{" + strings.Join(parts, ",") + "}"
}

func tsNewU(t testing.TB, bal [4]int64, extra ...string) *tsEnv {
	h, tok := txServerFx(t, tsFxU(bal, extra...))
	return &tsEnv{t: t, h: h, tok: tok}
}

func tsSeedPay(id, from, to string, amount int64, at string) string {
	return fmt.Sprintf(`{"id":%q,"from_user_id":"u_%s","to_user_id":"u_%s","amount":%d,"created_at":%q}`, id, from, to, amount, at)
}

func tsPays(items ...string) string { return `"payments":[` + strings.Join(items, ",") + `]` }

func (e *tsEnv) correct(user, pay, key string, expected int, amount int64, eff, reason string) *httptest.ResponseRecorder {
	body := fmt.Sprintf(`{"expected_revision":%d,"amount":%d,"effective_at":%q,"reason":%q}`, expected, amount, eff, reason)
	return e.do(user, "POST", "/payments/"+pay+"/corrections", key, body)
}

func (e *tsEnv) mustCorrect(user, pay, key string, expected int, amount int64, eff string) tsRev {
	e.t.Helper()
	rec := e.correct(user, pay, key, expected, amount, eff, "fix")
	if rec.Code != 201 {
		e.t.Fatalf("correct %s -> %d at %s: %d %s", pay, amount, eff, rec.Code, rec.Body)
	}
	var r tsRev
	if err := json.Unmarshal(rec.Body.Bytes(), &r); err != nil {
		e.t.Fatal(err)
	}
	return r
}

func (e *tsEnv) refuse(user, pay, key string, expected int, amount int64, eff string, status int, code string) {
	e.t.Helper()
	txWantErr(e.t, fmt.Sprintf("correct %s -> %d at %s", pay, amount, eff), e.correct(user, pay, key, expected, amount, eff, "fix"), status, code)
}

func (e *tsEnv) revs(user, pay string) []tsRev {
	e.t.Helper()
	rec := e.do(user, "GET", "/payments/"+pay+"/revisions", "", "")
	var out struct {
		Revisions []tsRev `json:"revisions"`
	}
	if err := json.Unmarshal(txWant(e.t, "revisions of "+pay, rec, 200), &out); err != nil {
		e.t.Fatal(err)
	}
	return out.Revisions
}

func (e *tsEnv) export() []byte {
	e.t.Helper()
	return txWant(e.t, "export", txDo(e.h, "GET", "/_test/export", "", "", ""), 200)
}

func (e *tsEnv) total(user, query string) int64 {
	e.t.Helper()
	return txNum(e.me(user, query), "total")
}

func (e *tsEnv) sumTotals(query string) int64 {
	var sum int64
	for _, u := range []string{"ada", "bob", "cy", "dee"} {
		sum += e.total(u, query)
	}
	return sum
}

func tsMinus(ts string, d time.Duration) string {
	t, ok := ParseInstant(ts)
	if !ok {
		panic("bad instant " + ts)
	}
	return FormatMicro(t.Add(-d))
}

func tsPlus(ts string, d time.Duration) string { return tsMinus(ts, -d) }

const (
	tsT0 = "2026-09-20T09:00:00+00:00"
	tsT1 = "2026-09-20T10:00:00+00:00"
	tsT2 = "2026-09-20T11:00:00+00:00"
	tsT3 = "2026-09-20T12:00:00+00:00"
)

func TestStatementUnderCorrectionsOrdersByEffectiveAndSelectsTheLatest(t *testing.T) {
	e := tsNew(t, tsHistory)
	// p_1: ada->bob 100 @09-20T10:00Z. Correct it to 60, effective 09-21T00:00Z (after p_3, p_2).
	r2 := e.mustCorrect("ada", "p_1", "c1", 1, 60, "2026-09-21T00:00:00+00:00")
	if r2.Revision != 2 || r2.Amount != 60 || r2.EffectiveAt != "2026-09-21T00:00:00+00:00" || r2.Reason != "fix" || r2.PaymentID != "p_1" || !tsMicroRe.MatchString(r2.RecordedAt) {
		t.Fatalf("revision body: %+v", r2)
	}
	ada := e.stmt("ada", "")
	// The payment is counted once, at its selected revision: p_3 (09-20T11:00Z) first, p_1 at 09-21T00:00Z
	// and p_11 at 09-21T09:00:00.5Z next, then the tie p_10/p_9.
	if got, want := ada.ids(), []string{"p_3", "p_1", "p_11", "p_10", "p_9"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("order %v, want %v", got, want)
	}
	en := ada.Entries[1]
	if en.Delta != -60 || en.Revision != 2 || en.EffectiveAt != r2.EffectiveAt || en.RecordedAt != r2.RecordedAt || en.Payment["amount"] != float64(60) || en.Payment["created_at"] != "2026-09-20T10:00:00+00:00" {
		t.Fatalf("corrected entry: %+v", en)
	}
	if ada.OpeningBalance != 1111 || ada.ClosingBalance != 1040 || ada.OpeningBalance+tsDeltas(ada) != ada.ClosingBalance {
		t.Fatalf("ada opening %d closing %d (deltas %d); 100 -> 60 must leave 1040", ada.OpeningBalance, ada.ClosingBalance, tsDeltas(ada))
	}
	if got := ada.Entries[0].BalanceAfter; got != 1086 {
		t.Fatalf("p_3 comes first now: balance_after %d, want 1086", got)
	}
	// The receiver sees the same corrected payment and a balance that moved by the difference.
	bob := e.stmt("bob", "")
	if bob.ClosingBalance != 460 || e.me("bob", "")["balance"] != float64(460) || e.me("ada", "")["balance"] != float64(1040) {
		t.Fatalf("balances after correction: bob %d", bob.ClosingBalance)
	}
	// Windows follow the selected effective time: out of the first day, into the second.
	day1 := e.stmt("ada", tsQ("to", "2026-09-21T00:00:00+00:00"))
	day2 := e.stmt("ada", tsQ("from", "2026-09-21T00:00:00+00:00", "to", "2026-09-22T00:00:00+00:00"))
	if !reflect.DeepEqual(day1.ids(), []string{"p_3"}) || !reflect.DeepEqual(day2.ids(), []string{"p_1", "p_11"}) {
		t.Fatalf("windows: %v %v", day1.ids(), day2.ids())
	}
	// known_at before the correction was recorded shows the original revision, byte for byte.
	before := e.stmt("ada", tsQ("known_at", tsMinus(r2.RecordedAt, time.Microsecond)))
	if !reflect.DeepEqual(before.ids(), []string{"p_1", "p_3", "p_11", "p_10", "p_9"}) || before.Entries[0].Revision != 1 || before.Entries[0].Delta != -100 || before.ClosingBalance != 1000 {
		t.Fatalf("known just before the correction: %+v", before)
	}
	at := e.stmt("ada", tsQ("known_at", r2.RecordedAt))
	if !reflect.DeepEqual(at.ids(), ada.ids()) || at.ClosingBalance != 1040 {
		t.Fatalf("known exactly at the correction (inclusive): %+v", at)
	}
	// /me agrees for every view; the sum of balances never leaves the seeded total.
	for _, q := range []string{"", tsQ("known_at", tsMinus(r2.RecordedAt, time.Microsecond)), tsQ("as_of", "2026-09-20T23:59:59+00:00"), tsQ("as_of", "2026-09-21T00:00:00+00:00")} {
		if got := e.sumTotals(q); got != txSeeded {
			t.Errorf("view %q: totals sum to %d, want %d", q, got, txSeeded)
		}
	}
	if got := e.total("ada", tsQ("as_of", "2026-09-20T23:59:59+00:00")); got != 1111-25 {
		t.Fatalf("before the corrected payment takes effect it is not counted at all: %d", got)
	}
	if got := e.total("ada", tsQ("as_of", "2026-09-21T00:00:00+00:00")); got != 1111-25-60 {
		t.Fatalf("as_of exactly at the corrected effective time includes it: %d", got)
	}
}

func TestStatementShowsZeroAmountRevisionsAndKeepsTheOriginalInTheFeed(t *testing.T) {
	e := tsNew(t, tsHistory)
	r := e.mustCorrect("ada", "p_3", "z1", 1, 0, "2026-09-20T11:00:00+00:00")
	if r.Amount != 0 {
		t.Fatalf("zero reverses the whole payment: %+v", r)
	}
	ada := e.stmt("ada", "")
	var zero *tsEntry
	for i := range ada.Entries {
		if ada.Entries[i].Payment["payment_id"] == "p_3" {
			zero = &ada.Entries[i]
		}
	}
	if zero == nil || zero.Delta != 0 || zero.Payment["amount"] != float64(0) || zero.Revision != 2 || zero.BalanceAfter != 1011 {
		t.Fatalf("a zero-amount revision stays in the statement with a zero delta: %+v", zero)
	}
	if ada.ClosingBalance != 1025 || e.me("ada", "")["balance"] != float64(1025) || e.me("bob", "")["balance"] != float64(475) {
		t.Fatalf("balances after a full reversal: ada %d", ada.ClosingBalance)
	}
	// The activity feed shows the original payment, never the correction.
	feed := txJSON(t, txWant(t, "activity", e.do("ada", "GET", "/activity?limit=200", "", ""), 200))["payments"].([]any)
	count := 0
	for _, p := range feed {
		pm := p.(map[string]any)
		if pm["payment_id"] == "p_3" {
			count++
			if pm["amount"] != float64(25) {
				t.Fatalf("feed shows %v, the original amount is 25", pm["amount"])
			}
		}
	}
	if count != 1 || len(feed) != 5 {
		t.Fatalf("feed has %d payments (p_3 x%d), corrections are not feed items", len(feed), count)
	}
	// Revision 1 survives untouched in the history.
	rv := e.revs("ada", "p_3")
	if len(rv) != 2 || rv[0].Amount != 25 || rv[0].Reason != "" || rv[1].Amount != 0 {
		t.Fatalf("revisions: %+v", rv)
	}
}

func TestAttackBackDatedCorrectionsAndHistoricalOverdraft(t *testing.T) {
	// bob opens at 0: +100 (p_1 @T1), -100 (p_2 @T2), +100 (p_3 @T3). He holds 100 now.
	e := tsNewU(t, [4]int64{900, 100, 100, 400}, tsPays(
		tsSeedPay("p_1", "ada", "bob", 100, tsT1), tsSeedPay("p_2", "bob", "cy", 100, tsT2), tsSeedPay("p_3", "dee", "bob", 100, tsT3)))
	if e.total("bob", tsQ("as_of", tsT0)) != 0 || e.total("bob", "") != 100 {
		t.Fatal("setup")
	}
	before := e.export()
	// Reversing p_1 leaves bob owing 100 at T2 although he can afford it today.
	e.refuse("ada", "p_1", "rev", 1, 0, tsT1, 409, "historical_overdraft")
	// Same with any effective_at: a reversal contributes nothing at any time.
	e.refuse("ada", "p_1", "rev2", 1, 0, "2026-09-20T13:00:00+00:00", 409, "historical_overdraft")
	// Shrinking it to 99 is no better: at T2 bob would be at -1.
	e.refuse("ada", "p_1", "shr", 1, 99, tsT1, 409, "historical_overdraft")
	// Moving p_2 (same amount!) to before bob was ever paid is a diff-0 correction that must still be refused.
	e.refuse("bob", "p_2", "early", 1, 100, tsT0, 409, "historical_overdraft")
	if after := e.export(); !bytes.Equal(before, after) {
		t.Fatal("a refused correction left a trace (balances, revisions or idempotency record)")
	}
	if rv := e.revs("bob", "p_2"); len(rv) != 1 {
		t.Fatalf("revisions after refusals: %+v", rv)
	}
	// The keys of refused corrections are free: the same key now carries a valid body.
	e.mustCorrect("ada", "p_1", "rev", 1, 100, tsT1)
	// Moving p_2 to after bob's second income keeps every boundary nonnegative: allowed, diff 0.
	r := e.mustCorrect("bob", "p_2", "late", 1, 100, "2026-09-20T12:30:00+00:00")
	if r.Revision != 2 || r.Amount != 100 {
		t.Fatalf("%+v", r)
	}
	bob := e.stmt("bob", "")
	if !reflect.DeepEqual(bob.ids(), []string{"p_1", "p_3", "p_2"}) || bob.ClosingBalance != 100 || bob.OpeningBalance != 0 {
		t.Fatalf("bob after moving p_2 later: %v closing %d", bob.ids(), bob.ClosingBalance)
	}
	if got := e.total("bob", tsQ("as_of", "2026-09-20T12:15:00+00:00")); got != 200 {
		t.Fatalf("bob at 12:15 holds both incomes: %d", got)
	}
	if e.sumTotals("") != 1500 || e.sumTotals(tsQ("as_of", tsT2)) != 1500 {
		t.Fatal("sum of balances left the seeded total")
	}
}

func TestAttackReversalCannotBypassTheHistoricalCheckByTheReceiverSide(t *testing.T) {
	// Decreasing a payment debits the RECEIVER; a payment shrunk to 0 may not leave the receiver negative in the past.
	// cy receives 100 @T1 and sends 100 to dee @T2; cy holds 0 now. ada may not take back the 100: not affordable today.
	e := tsNewU(t, [4]int64{900, 0, 0, 600}, tsPays(tsSeedPay("p_1", "ada", "cy", 100, tsT1), tsSeedPay("p_2", "cy", "dee", 100, tsT2)))
	e.refuse("ada", "p_1", "k", 1, 0, tsT1, 409, "insufficient_funds")
	// Now cy receives another 100 later: affordable today, but at T2 cy would owe 100.
	e2 := tsNewU(t, [4]int64{900, 0, 100, 500}, tsPays(tsSeedPay("p_1", "ada", "cy", 100, tsT1), tsSeedPay("p_2", "cy", "dee", 100, tsT2), tsSeedPay("p_3", "dee", "cy", 100, tsT3)))
	e2.refuse("ada", "p_1", "k", 1, 0, tsT1, 409, "historical_overdraft")
}

func TestAttackCombinedSameInstantMovementsAreJudgedTogether(t *testing.T) {
	// bob: opening 50; p_0 -10 @T0; at T: p_1 -130 (id order first) and p_2 +100: the boundary at T is 10, not -90.
	e := tsNewU(t, [4]int64{1000, 10, 140, 400}, tsPays(
		tsSeedPay("p_0", "bob", "cy", 10, tsT0), tsSeedPay("p_1", "bob", "cy", 130, tsT2), tsSeedPay("p_2", "dee", "bob", 100, tsT2)))
	if e.total("bob", tsQ("as_of", tsT2)) != 10 || e.total("bob", tsQ("as_of", tsT0)) != 40 {
		t.Fatalf("setup: %v", e.me("bob", tsQ("as_of", tsT2)))
	}
	st := e.stmt("bob", "")
	if !reflect.DeepEqual(st.ids(), []string{"p_0", "p_1", "p_2"}) || st.Entries[1].BalanceAfter != -90 || st.Entries[2].BalanceAfter != 10 {
		t.Fatalf("a tie is ordered by id and balance_after runs entry by entry: %+v", st.Entries)
	}
	// A diff-0 correction elsewhere must pass: judging p_1 before p_2 would see -90.
	e.mustCorrect("bob", "p_0", "k0", 1, 10, tsT0)
	// Moving p_1 (-130) before the income at T leaves bob at 50-10-130 < 0 at T0 and at T1.
	e.refuse("bob", "p_1", "k1", 1, 130, tsT0, 409, "historical_overdraft")
	e.refuse("bob", "p_1", "k2", 1, 130, tsT1, 409, "historical_overdraft")
	// Moving it to exactly the income's instant is fine and changes nothing observable.
	e.mustCorrect("bob", "p_1", "k3", 1, 130, tsT2)
	if got := e.total("bob", tsQ("as_of", tsT2)); got != 10 {
		t.Fatalf("combined boundary: %d", got)
	}
}

func TestAttackHoldUnderflowAtAPastBoundary(t *testing.T) {
	// ada opens at 150, paid bob 50 @T1 (balance 100). A hold of 80 is placed and voided right away:
	// today nothing is held, but at the hold's creation her available amount is total - 80.
	e := tsNewU(t, [4]int64{100, 50, 0, 0}, tsPays(tsSeedPay("p_1", "ada", "bob", 50, tsT1)))
	a := txJSON(t, txWant(t, "authorize", e.do("ada", "POST", "/authorizations", "h1", `{"to_handle":"cy","amount":80}`), 201))
	id := a["authorization_id"].(string)
	void := txJSON(t, txWant(t, "void", e.do("ada", "POST", "/authorizations/"+id+"/void", "", ""), 200))
	if void["closed_at"] == nil || a["closed_at"] != nil {
		t.Fatalf("closed_at is null while open and the void instant afterwards: %v / %v", a["closed_at"], void["closed_at"])
	}
	if e.me("ada", "")["held"] != float64(0) {
		t.Fatal("setup: the hold is released")
	}
	before := e.export()
	// +41 -> total 59 while the hold existed: refused as historical (she can afford it today).
	e.refuse("ada", "p_1", "u1", 1, 91, tsT1, 409, "historical_overdraft")
	if !bytes.Equal(before, e.export()) {
		t.Fatal("refused correction left a trace")
	}
	// +20 -> total 80 = held 80: available 0 is allowed (nonnegative).
	e.mustCorrect("ada", "p_1", "u2", 1, 70, tsT1)
	// One more cent makes available -1 at the creation boundary.
	e.refuse("ada", "p_1", "u3", 2, 71, tsT1, 409, "historical_overdraft")
	// The hold's own history is unchanged: held 80 between creation and void, never more.
	if got := e.me("ada", tsQ("as_of", void["closed_at"].(string)))["held"]; got != float64(0) {
		t.Fatalf("released at closed_at: %v", got)
	}
	if got := e.me("ada", tsQ("as_of", tsMinus(void["closed_at"].(string), time.Microsecond))); got["held"] != float64(80) || got["available"] != float64(0) || got["total"] != float64(80) {
		t.Fatalf("just before the void: %v", got)
	}
}

func TestAttackReplayAfterNewerRevisionsAndKeyReuse(t *testing.T) {
	e := tsNew(t, tsHistory)
	first := e.correct("ada", "p_1", "k1", 1, 90, tsT1, "first")
	body1 := txWant(t, "first", first, 201)
	second := e.correct("ada", "p_1", "k2", 2, 80, tsT1, "second")
	body2 := txWant(t, "second", second, 201)
	third := e.correct("ada", "p_1", "k3", 3, 70, tsT1, "third")
	txWant(t, "third", third, 201)
	snapshot := e.export()

	// Replaying the first correction after two newer revisions returns that revision with 200.
	rep := e.correct("ada", "p_1", "k1", 1, 90, tsT1, "first")
	if !bytes.Equal(txWant(t, "replay k1", rep, 200), body1) {
		t.Fatalf("replay body differs: %s vs %s", rep.Body, body1)
	}
	if rep := e.correct("ada", "p_1", "k2", 2, 80, tsT1, "second"); !bytes.Equal(txWant(t, "replay k2", rep, 200), body2) {
		t.Fatal("replay of the second differs")
	}
	if !bytes.Equal(snapshot, e.export()) {
		t.Fatal("replays changed state")
	}
	if rv := e.revs("ada", "p_1"); len(rv) != 4 || rv[3].Amount != 70 || rv[1].Reason != "first" {
		t.Fatalf("revisions: %+v", rv)
	}
	// The same key with a different body is a conflict, whatever the difference, and even if the new body is invalid.
	for name, body := range map[string]string{
		"amount":    `{"expected_revision":1,"amount":91,"effective_at":"` + tsT1 + `","reason":"first"}`,
		"reason":    `{"expected_revision":1,"amount":90,"effective_at":"` + tsT1 + `","reason":"First"}`,
		"effective": `{"expected_revision":1,"amount":90,"effective_at":"` + tsT2 + `","reason":"first"}`,
		"revision":  `{"expected_revision":4,"amount":90,"effective_at":"` + tsT1 + `","reason":"first"}`,
		"invalid":   `{"expected_revision":"x"}`,
		"extra":     `{"expected_revision":1,"amount":90,"effective_at":"` + tsT1 + `","reason":"first","note":"x"}`,
	} {
		txWantErr(t, "key reuse with a different "+name, e.do("ada", "POST", "/payments/p_1/corrections", "k1", body), 409, "idempotency_key_reuse")
	}
	// The same body with the keys in another order and spacing is the same body.
	same := `{ "reason":"first", "effective_at":"` + tsT1 + `", "amount":9e1, "expected_revision":1 }`
	if rep := e.do("ada", "POST", "/payments/p_1/corrections", "k1", same); rep.Code != 200 || !bytes.Equal(rep.Body.Bytes(), body1) {
		t.Fatalf("an equivalent body must replay: %d %s", rep.Code, rep.Body)
	}
	// Keys are scoped: the same key on another payment is a fresh correction, not a conflict.
	if rec := e.correct("ada", "p_3", "k1", 1, 20, tsT1, "other payment"); rec.Code != 201 {
		t.Fatalf("key scoped per path: %d %s", rec.Code, rec.Body)
	}
	if len(e.revs("ada", "p_1")) != 4 {
		t.Fatal("a correction on another payment must not touch p_1")
	}
	// A stale expected revision is a 409 stale_revision and does not claim the key.
	e.refuse("ada", "p_1", "stale", 1, 10, tsT1, 409, "stale_revision")
	e.mustCorrect("ada", "p_1", "stale", 4, 10, tsT1)
	// No key at all is refused before anything else.
	txWantErr(t, "no key", e.do("ada", "POST", "/payments/p_1/corrections", "", `{}`), 400, "missing_idempotency_key")
}

func TestAttackMicrosecondTiesAtEveryBoundary(t *testing.T) {
	e := tsNew(t)
	p := e.pay("ada", "m1", "bob", 40)
	c := p["created_at"].(string)
	if !tsMicroRe.MatchString(c) {
		t.Fatalf("created_at %q", c)
	}
	// as_of is inclusive at the instant, exclusive one microsecond earlier.
	if got := e.total("ada", tsQ("as_of", c)); got != 960 {
		t.Fatalf("as_of = created_at counts the payment: %d", got)
	}
	if got := e.total("ada", tsQ("as_of", tsMinus(c, time.Microsecond))); got != 1000 {
		t.Fatalf("one microsecond before: %d", got)
	}
	// ... and the same instant written in another offset and with extra zeros is the same instant.
	ct, _ := ParseInstant(c)
	alt := ct.In(time.FixedZone("x", 5*3600+30*60)).Format("2006-01-02T15:04:05.000000000-07:00")
	if got := e.total("ada", tsQ("as_of", alt)); got != 960 {
		t.Fatalf("as_of in a +05:30 offset with nanoseconds: %d", got)
	}
	if got := e.me("ada", tsQ("as_of", alt))["as_of"]; got != alt {
		t.Fatalf("as_of must be echoed exactly as given: %v vs %v", got, alt)
	}
	// A nanosecond before the instant is before it.
	if got := e.total("ada", tsQ("as_of", ct.Add(-time.Nanosecond).Format("2006-01-02T15:04:05.000000000Z"))); got != 1000 {
		t.Fatalf("one nanosecond before: %d", got)
	}
	// Statement window: from inclusive, to exclusive, at the same instant.
	in := e.stmt("ada", tsQ("from", c))
	out := e.stmt("ada", tsQ("to", c))
	if len(in.Entries) != 1 || in.OpeningBalance != 1000 || len(out.Entries) != 0 || out.ClosingBalance != 1000 {
		t.Fatalf("from=c %+v / to=c %+v", in, out)
	}
	if after := e.stmt("ada", tsQ("from", tsPlus(c, time.Microsecond))); len(after.Entries) != 0 || after.OpeningBalance != 960 {
		t.Fatalf("from just after: %+v", after)
	}
	if upTo := e.stmt("ada", tsQ("to", tsPlus(c, time.Microsecond))); len(upTo.Entries) != 1 || upTo.ClosingBalance != 960 {
		t.Fatalf("to just after: %+v", upTo)
	}
	// A correction effective at the original instant (a tie with revision 1's instant) is accepted;
	// known_at is inclusive of its recording instant.
	r2 := e.mustCorrect("ada", p["payment_id"].(string), "t1", 1, 25, c)
	if got := e.stmt("ada", tsQ("known_at", r2.RecordedAt)); got.ClosingBalance != 975 || got.Entries[0].Revision != 2 {
		t.Fatalf("known_at = recorded_at selects the new revision: %+v", got)
	}
	if got := e.stmt("ada", tsQ("known_at", tsMinus(r2.RecordedAt, time.Microsecond))); got.ClosingBalance != 960 || got.Entries[0].Revision != 1 {
		t.Fatalf("known_at one microsecond earlier selects the old one: %+v", got)
	}
	if got := e.total("ada", tsQ("as_of", c, "known_at", tsMinus(r2.RecordedAt, time.Microsecond))); got != 960 {
		t.Fatalf("/me under the old knowledge: %d", got)
	}
	if got := e.total("ada", tsQ("as_of", tsMinus(c, time.Nanosecond), "known_at", r2.RecordedAt)); got != 1000 {
		t.Fatalf("a payment at c is not counted just before c: %d", got)
	}
	// A payment that was not yet recorded at known_at contributes nothing at all.
	if got := e.total("ada", tsQ("known_at", tsMinus(c, time.Microsecond))); got != 1000 {
		t.Fatalf("known before the payment existed: %d", got)
	}
	// Back-to-back corrections are strictly ordered in recorded time.
	r3 := e.mustCorrect("ada", p["payment_id"].(string), "t2", 2, 26, c)
	r4 := e.mustCorrect("ada", p["payment_id"].(string), "t3", 3, 27, c)
	a, _ := ParseInstant(r2.RecordedAt)
	b, _ := ParseInstant(r3.RecordedAt)
	d, _ := ParseInstant(r4.RecordedAt)
	if !b.After(a) || !d.After(b) {
		t.Fatalf("recorded_at must strictly increase: %s %s %s", r2.RecordedAt, r3.RecordedAt, r4.RecordedAt)
	}
	if got := e.sumTotals(tsQ("known_at", r3.RecordedAt)); got != 1600 {
		t.Fatalf("sum: %d", got)
	}
}

func TestAttackFutureAsOfPastAHoldDeadlineAndKnownAtBetweenEvents(t *testing.T) {
	// Seeded: a hold that expires at 2099-01-01.
	e := tsNew(t, txAuths(txA("a_far", "open", 300, txFuture, `"created_at":"`+tsT0+`"`)))
	for _, c := range []struct {
		asOf string
		held float64
	}{
		{"2098-12-31T23:59:59+00:00", 300},
		{"2098-12-31T23:59:59.999999+00:00", 300},
		{txFuture, 0}, // expiry takes effect at expires_at
		{"2099-01-01T00:00:00.000001+00:00", 0},
		{"2200-01-01T00:00:00+00:00", 0},
	} {
		me := e.me("ada", tsQ("as_of", c.asOf))
		if me["held"] != c.held || me["available"] != 1000-c.held || me["total"] != float64(1000) {
			t.Errorf("as_of %s: %v", c.asOf, me)
		}
	}
	// An API hold: partial capture, then void; query around each event, with and without knowledge of it.
	e2 := tsNew(t)
	a := txJSON(t, txWant(t, "authorize", e2.do("ada", "POST", "/authorizations", "a1", `{"to_handle":"bob","amount":300}`), 201))
	id := a["authorization_id"].(string)
	expires := a["expires_at"].(string)
	capP := txJSON(t, txWant(t, "capture", e2.do("bob", "POST", "/authorizations/"+id+"/capture", "c1", `{"amount":100,"final":false}`), 201))
	cAt := capP["created_at"].(string)
	void := txJSON(t, txWant(t, "void", e2.do("ada", "POST", "/authorizations/"+id+"/void", "", ""), 200))
	vAt := void["closed_at"].(string)
	if void["status"] != "voided" || vAt == "" || a["closed_at"] != nil {
		t.Fatalf("lifecycle bodies: %v %v", a, void)
	}
	held := func(q string) any { return e2.me("ada", q)["held"] }
	for _, c := range []struct {
		name, q string
		want    float64
	}{
		{"after creation, before the capture", tsQ("as_of", tsMinus(cAt, time.Microsecond)), 300},
		{"at the capture", tsQ("as_of", cAt), 200},
		{"just before the void", tsQ("as_of", tsMinus(vAt, time.Microsecond)), 200},
		{"at the void", tsQ("as_of", vAt), 0},
		{"now", "", 0},
		// Knowledge: the void was unknown before vAt, so a future reader still sees the remainder held until the deadline.
		{"future as_of, void not yet known", tsQ("as_of", tsPlus(vAt, time.Second), "known_at", tsMinus(vAt, time.Microsecond)), 200},
		{"future as_of, void known", tsQ("as_of", tsPlus(vAt, time.Second), "known_at", vAt), 0},
		// The deadline is known as soon as the hold is: past it nothing is held even without knowing the void.
		{"past the deadline, void unknown", tsQ("as_of", expires, "known_at", tsMinus(vAt, time.Microsecond)), 0},
		{"just before the deadline, void unknown", tsQ("as_of", tsMinus(expires, time.Microsecond), "known_at", tsMinus(vAt, time.Microsecond)), 200},
		{"capture unknown yet", tsQ("as_of", tsPlus(vAt, time.Second), "known_at", tsMinus(cAt, time.Microsecond)), 300},
		{"hold unknown yet", tsQ("as_of", tsPlus(vAt, time.Second), "known_at", tsMinus(a["created_at"].(string), time.Microsecond)), 0},
	} {
		if got := held(c.q); got != c.want {
			t.Errorf("%s (%s): held %v, want %v", c.name, c.q, got, c.want)
		}
	}
	// All four fields describe one view.
	me := e2.me("ada", tsQ("as_of", tsMinus(vAt, time.Microsecond)))
	if me["balance"] != me["total"] || me["total"].(float64)-me["held"].(float64) != me["available"].(float64) || me["total"] != float64(900) {
		t.Fatalf("one view: %v", me)
	}
	// Expiry by the clock: an authorization with a short TTL is closed at expires_at without any event.
	e3 := tsNew(t, `"authorization_ttl_seconds":2`)
	b := txJSON(t, txWant(t, "authorize", e3.do("ada", "POST", "/authorizations", "b1", `{"to_handle":"bob","amount":50}`), 201))
	exp := b["expires_at"].(string)
	if e3.me("ada", tsQ("as_of", tsMinus(exp, time.Microsecond)))["held"] != float64(50) || e3.me("ada", tsQ("as_of", exp))["held"] != float64(0) {
		t.Fatal("a future as_of past the deadline releases the hold")
	}
}

// Reading A of the spec (what the service implements): a payment is exactly its selected revision, so
// a correction with a later effective_at moves the whole movement later, and the original amount is no
// longer anywhere before it. The other reading (apply only the difference at effective_at, keep the
// original at created_at) would accept the first correction below; this pins the behaviour so a change
// of reading is a conscious one.
func TestAttackLaterEffectiveDecreaseMovesTheWholeMovement(t *testing.T) {
	// bob: +500 (p_1 @T1), -450 (p_2 @T2), holds 50 now. ada's p_1 -> 450, effective T3 (after p_2).
	setup := func() *tsEnv {
		return tsNewU(t, [4]int64{500, 50, 450, 0}, tsPays(tsSeedPay("p_1", "ada", "bob", 500, tsT1), tsSeedPay("p_2", "bob", "cy", 450, tsT2)))
	}
	e := setup()
	before := e.export()
	e.refuse("ada", "p_1", "later", 1, 450, tsT3, 409, "historical_overdraft")
	if !bytes.Equal(before, e.export()) {
		t.Fatal("the refusal left a trace")
	}
	e = setup()
	r := e.mustCorrect("ada", "p_1", "same", 1, 450, tsT1) // same effective time: only the difference moves
	if r.Amount != 450 || e.total("bob", "") != 0 {
		t.Fatalf("revision %+v, bob now %d (50 less the 50 taken back)", r, e.total("bob", ""))
	}
	if got := e.total("bob", tsQ("as_of", tsT2)); got != 0 {
		t.Fatalf("bob at T2: %d, want 450-450 = 0", got)
	}
}
