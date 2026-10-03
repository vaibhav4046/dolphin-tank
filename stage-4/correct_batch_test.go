package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"
)

// POST /correction-batches through the real HTTP handlers. Every expectation comes from the written
// stage-4 requirements (ledger rows U20-U41), not from the implementation. ada is the settlement operator.

const (
	btT1 = "2026-09-20T10:00:00+00:00"
	btT2 = "2026-09-20T12:00:00+00:00"
	btT3 = "2026-09-21T09:00:00+00:00"
)

var btIDRe = regexp.MustCompile(`^cb_\d+$`)

type btRev struct {
	PaymentID         string  `json:"payment_id"`
	Revision          int64   `json:"revision"`
	Amount            int64   `json:"amount"`
	EffectiveAt       string  `json:"effective_at"`
	RecordedAt        string  `json:"recorded_at"`
	Reason            string  `json:"reason"`
	CorrectionBatchID *string `json:"correction_batch_id"`
}

type btOut struct {
	CorrectionBatchID string  `json:"correction_batch_id"`
	RecordedAt        string  `json:"recorded_at"`
	Revisions         []btRev `json:"revisions"`
}

func btItem(id string, rev int, amount int64, eff string) string {
	return fmt.Sprintf(`{"payment_id":%q,"expected_revision":%d,"amount":%d,"effective_at":%q,"reason":"batch"}`, id, rev, amount, eff)
}

func btRaw(id, rev, amount, eff, reason string) string {
	return fmt.Sprintf(`{"payment_id":%s,"expected_revision":%s,"amount":%s,"effective_at":%s,"reason":%s}`, id, rev, amount, eff, reason)
}

func btBody(items ...string) string { return `{"corrections":[` + strings.Join(items, ",") + `]}` }

func (e *tsEnv) batch(user, key string, items ...string) *httptest.ResponseRecorder {
	return e.do(user, "POST", "/correction-batches", key, btBody(items...))
}

func (e *tsEnv) batchOK(key string, items ...string) btOut {
	e.t.Helper()
	rec := e.batch("ada", key, items...)
	if rec.Code != 201 {
		e.t.Fatalf("batch %s: %d %s", key, rec.Code, rec.Body)
	}
	var out btOut
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		e.t.Fatal(err)
	}
	return out
}

// refuse sends a body, wants the error, and proves nothing moved: the export (balances, revisions,
// idempotency records, id counters) is byte-identical before and after.
func (e *tsEnv) refuseBody(what, key, body string, status int, code string) {
	e.t.Helper()
	before := e.export()
	txWantErr(e.t, what, e.do("ada", "POST", "/correction-batches", key, body), status, code)
	if !bytes.Equal(before, e.export()) {
		e.t.Fatalf("%s: a rejected batch changed the state", what)
	}
}

func (e *tsEnv) refuseBatch(what, key string, status int, code string, items ...string) {
	e.t.Helper()
	e.refuseBody(what, key, btBody(items...), status, code)
}

func (e *tsEnv) sumBalances() int64 {
	var sum int64
	for _, u := range []string{"ada", "bob", "cy", "dee"} {
		sum += txNum(e.me(u, ""), "balance")
	}
	return sum
}

// btBase: ada 1000, bob 500, cy 100, dee 0 after p_1 ada>bob 100 and p_2 ada>cy 50 at T1, p_3 bob>cy 30 at T2.
func btBase(t testing.TB) *tsEnv {
	return tsNewU(t, [4]int64{1000, 500, 100, 0},
		tsPays(tsSeedPay("p_1", "ada", "bob", 100, btT1), tsSeedPay("p_2", "ada", "cy", 50, btT1), tsSeedPay("p_3", "bob", "cy", 30, btT2)))
}

func (e *tsEnv) settle(key string, transfers ...string) []string {
	e.t.Helper()
	rec := e.do("ada", "POST", "/settlements", key, `{"transfers":[`+strings.Join(transfers, ",")+`]}`)
	var out struct {
		Payments []struct {
			PaymentID string `json:"payment_id"`
		} `json:"payments"`
	}
	if err := json.Unmarshal(txWant(e.t, "settlement "+key, rec, 201), &out); err != nil {
		e.t.Fatal(err)
	}
	ids := make([]string, len(out.Payments))
	for i, p := range out.Payments {
		ids[i] = p.PaymentID
	}
	return ids
}

func btLeg(from, to string, amount int) string {
	return fmt.Sprintf(`{"from_handle":%q,"to_handle":%q,"amount":%d}`, from, to, amount)
}

func TestBatchAuthAndKeyOrder(t *testing.T) { // U20
	e := btBase(t)
	body := btBody(btItem("p_1", 1, 90, btT2))
	txWantErr(t, "no token", txDo(e.h, "POST", "/correction-batches", "", "k", body), 401, "unauthenticated")
	txWantErr(t, "bad token", txDo(e.h, "POST", "/correction-batches", "nope", "k", body), 401, "unauthenticated")
	for _, key := range []string{"", "k"} {
		for _, b := range []string{body, "nope", `{}`, ``} {
			txWantErr(t, "non-operator key="+key+" body="+b, e.do("bob", "POST", "/correction-batches", key, b), 403, "forbidden")
		}
	}
	for _, key := range []string{"", strings.Repeat("k", 256)} {
		want := e.do("ada", "POST", "/settlements", key, `{"transfers":[`+btLeg("ada", "bob", 1)+`]}`)
		got := e.do("ada", "POST", "/correction-batches", key, body)
		if want.Code == 201 || got.Code != want.Code || !bytes.Equal(errCode(got.Body.Bytes()), errCode(want.Body.Bytes())) {
			t.Errorf("key %q: settlements answered %d %s, batches %d %s", key, want.Code, want.Body, got.Code, got.Body)
		}
	}
	for _, b := range []string{"nope", `[]`, `"x"`, ``, `{} {}`} {
		txWantErr(t, "malformed body "+b, e.do("ada", "POST", "/correction-batches", "kb", b), 400, "malformed_request")
	}
	if e.do("ada", "POST", "/correction-batches", "k", body).Code != 201 {
		t.Fatal("the operator's valid batch must be accepted")
	}
}

func errCode(b []byte) []byte {
	var env struct{ Error struct{ Code string } }
	_ = json.Unmarshal(b, &env)
	return []byte(env.Error.Code)
}

func btManyPays(n int) string {
	var ps []string
	for i := 1; i <= n; i++ {
		ps = append(ps, tsSeedPay(fmt.Sprintf("p_%d", i), "ada", "bob", 1, btT1))
	}
	return tsPays(ps...)
}

func TestBatchBodyShape(t *testing.T) { // U21
	e := tsNewU(t, [4]int64{1000, 500, 100, 0}, btManyPays(33))
	one := btItem("p_1", 1, 2, btT2)
	for name, body := range map[string]string{
		"empty object":      `{}`,
		"null":              `{"corrections":null}`,
		"empty array":       `{"corrections":[]}`,
		"object":            `{"corrections":{}}`,
		"string":            `{"corrections":"x"}`,
		"number element":    `{"corrections":[1]}`,
		"string element":    `{"corrections":["p_1"]}`,
		"null element":      `{"corrections":[null]}`,
		"array element":     `{"corrections":[[]]}`,
		"no payment_id":     `{"corrections":[{"expected_revision":1,"amount":2,"effective_at":"` + btT2 + `","reason":"r"}]}`,
		"numeric id":        `{"corrections":[` + btRaw(`1`, `1`, `2`, `"`+btT2+`"`, `"r"`) + `]}`,
		"null id":           `{"corrections":[` + btRaw(`null`, `1`, `2`, `"`+btT2+`"`, `"r"`) + `]}`,
		"duplicate ids":     btBody(one, btItem("p_2", 1, 2, btT2), one),
		"same id other rev": btBody(one, btItem("p_1", 2, 3, btT2)),
	} {
		e.refuseBody(name, "k-"+name, body, 422, "validation_failed")
	}
	var many []string
	for i := 1; i <= 33; i++ {
		many = append(many, btItem(fmt.Sprintf("p_%d", i), 1, 2, btT2))
	}
	e.refuseBatch("33 items", "k33", 422, "validation_failed", many...)
	e.refuseBatch("33 items, the first unknown", "k33b", 422, "validation_failed", append([]string{btItem("p_999", 1, 2, btT2)}, many...)...)

	out := e.batchOK("k32", many[:32]...)
	if len(out.Revisions) != 32 {
		t.Fatalf("32 items answered %d revisions", len(out.Revisions))
	}
	for i, r := range out.Revisions {
		if r.PaymentID != fmt.Sprintf("p_%d", i+1) || r.Revision != 2 || r.Amount != 2 {
			t.Fatalf("revision %d: %+v", i, r)
		}
	}
	e2 := tsNewU(t, [4]int64{1000, 500, 100, 0}, btManyPays(2))
	if got := e2.batchOK("k1", btItem("p_1", 1, 2, btT2)); len(got.Revisions) != 1 {
		t.Fatalf("one item: %+v", got)
	}
}

func TestBatchItemValidationAndUnknownFields(t *testing.T) { // U22, U28, U35
	e := btBase(t)
	eff := `"` + btT2 + `"`
	bad := map[string]string{
		"revision 0":          btRaw(`"p_999"`, `0`, `5`, eff, `"r"`),
		"revision -1":         btRaw(`"p_999"`, `-1`, `5`, eff, `"r"`),
		"revision 1.5":        btRaw(`"p_999"`, `1.5`, `5`, eff, `"r"`),
		"revision string":     btRaw(`"p_999"`, `"1"`, `5`, eff, `"r"`),
		"revision null":       btRaw(`"p_999"`, `null`, `5`, eff, `"r"`),
		"revision bool":       btRaw(`"p_999"`, `true`, `5`, eff, `"r"`),
		"amount -1":           btRaw(`"p_999"`, `1`, `-1`, eff, `"r"`),
		"amount 1.5":          btRaw(`"p_999"`, `1`, `1.5`, eff, `"r"`),
		"amount string":       btRaw(`"p_999"`, `1`, `"5"`, eff, `"r"`),
		"amount null":         btRaw(`"p_999"`, `1`, `null`, eff, `"r"`),
		"amount too large":    btRaw(`"p_999"`, `1`, `1000000001`, eff, `"r"`),
		"amount bool":         btRaw(`"p_999"`, `1`, `false`, eff, `"r"`),
		"effective date only": btRaw(`"p_999"`, `1`, `5`, `"2026-09-20"`, `"r"`),
		"effective naive":     btRaw(`"p_999"`, `1`, `5`, `"2026-09-20T12:00:00"`, `"r"`),
		"effective garbage":   btRaw(`"p_999"`, `1`, `5`, `"garbage"`, `"r"`),
		"effective number":    btRaw(`"p_999"`, `1`, `5`, `1`, `"r"`),
		"effective null":      btRaw(`"p_999"`, `1`, `5`, `null`, `"r"`),
		"effective future":    btRaw(`"p_999"`, `1`, `5`, `"2099-01-01T00:00:00+00:00"`, `"r"`),
		"reason empty":        btRaw(`"p_999"`, `1`, `5`, eff, `""`),
		"reason number":       btRaw(`"p_999"`, `1`, `5`, eff, `1`),
		"reason null":         btRaw(`"p_999"`, `1`, `5`, eff, `null`),
		"reason 201 runes":    btRaw(`"p_999"`, `1`, `5`, eff, `"`+strings.Repeat("é", 201)+`"`),
		"missing revision":    `{"payment_id":"p_999","amount":5,"effective_at":` + eff + `,"reason":"r"}`,
		"missing amount":      `{"payment_id":"p_999","expected_revision":1,"effective_at":` + eff + `,"reason":"r"}`,
		"missing effective":   `{"payment_id":"p_999","expected_revision":1,"amount":5,"reason":"r"}`,
		"missing reason":      `{"payment_id":"p_999","expected_revision":1,"amount":5,"effective_at":` + eff + `}`,
	}
	for name, item := range bad {
		e.refuseBatch(name+" (before the 404)", "kv-"+name, 422, "validation_failed", item)
		e.refuseBatch(name+" on a real payment", "kr-"+name, 422, "validation_failed", strings.Replace(item, "p_999", "p_1", 1))
	}
	// A future effective_at on one item of several refuses the whole batch.
	future := time.Now().UTC().Add(time.Hour).Format("2006-01-02T15:04:05+00:00")
	e.refuseBatch("future in the second item", "kf", 422, "validation_failed", btItem("p_1", 1, 90, btT2), btItem("p_2", 1, 40, future))

	// Range edges and spellings that must be accepted, with unknown fields at both levels ignored.
	body := `{"extra":{"a":1},"corrections":[` +
		`{"payment_id":"p_1","expected_revision":1,"amount":0,"effective_at":"2026-09-20T12:00:00Z","reason":"zero","ignored":[1,2]},` +
		`{"payment_id":"p_2","expected_revision":1,"amount":50,"effective_at":"2026-09-20T14:00:00+02:00","reason":"` + strings.Repeat("é", 200) + `","payment":"p_3"}]}`
	rec := e.do("ada", "POST", "/correction-batches", "ok", body)
	if rec.Code != 201 {
		t.Fatalf("edges and unknown fields: %d %s", rec.Code, rec.Body)
	}
	var out btOut
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	if out.Revisions[0].Amount != 0 || out.Revisions[0].EffectiveAt != "2026-09-20T12:00:00Z" || out.Revisions[1].EffectiveAt != "2026-09-20T14:00:00+02:00" {
		t.Fatalf("effective_at is stored as sent: %+v", out.Revisions)
	}
}

func TestBatchItemErrorsInInputOrder(t *testing.T) { // U23, U29
	e := btBase(t)
	unknown := btItem("p_999", 1, 5, btT2)
	ok1 := btItem("p_1", 1, 90, btT2)
	stale := btItem("p_3", 4, 5, btT2)
	badAmount := btRaw(`"p_2"`, `1`, `-1`, `"`+btT2+`"`, `"r"`)
	for _, c := range []struct {
		name   string
		items  []string
		status int
		code   string
	}{
		{"unknown after valid", []string{ok1, unknown}, 404, "not_found"},
		{"unknown before valid", []string{unknown, ok1}, 404, "not_found"},
		{"stale after valid", []string{ok1, stale}, 409, "stale_revision"},
		{"stale before unknown", []string{stale, unknown}, 409, "stale_revision"},
		{"unknown before stale", []string{unknown, stale}, 404, "not_found"},
		{"validation before unknown", []string{badAmount, unknown}, 422, "validation_failed"},
		{"unknown before validation", []string{unknown, badAmount}, 404, "not_found"},
		{"stale before validation", []string{stale, badAmount}, 409, "stale_revision"},
		{"validation before stale", []string{badAmount, stale}, 422, "validation_failed"},
		{"one item: validation before 404", []string{btRaw(`"p_999"`, `7`, `-3`, `"`+btT2+`"`, `"r"`)}, 422, "validation_failed"},
		{"one item: 404 before stale", []string{btItem("p_999", 7, 3, btT2)}, 404, "not_found"},
	} {
		e.refuseBatch(c.name, "k-"+c.name, c.status, c.code, c.items...)
	}
}

func TestBatchLinkedPaymentsAndOperatorScope(t *testing.T) { // U24, U30
	e := btBase(t)
	// A capture (bob captures ada's hold), a refund (bob refunds part of p_1) and a request payment.
	hold := txHold(t, e.h, e.tok, "auth-1", "bob", "200")
	capture := txJSON(t, txWant(t, "capture", e.do("bob", "POST", "/authorizations/"+hold+"/capture", "cap-1", `{}`), 201))["payment_id"].(string)
	refund := txJSON(t, txWant(t, "refund", e.do("bob", "POST", "/payments/p_1/refunds", "ref-1", `{"amount":10}`), 201))["payment_id"].(string)
	rq := txJSON(t, txWant(t, "request", e.do("bob", "POST", "/requests", "rq-1", `{"payer_handle":"cy","amount":20}`), 201))["request_id"].(string)
	reqPay := txJSON(t, txWant(t, "pay request", e.do("cy", "POST", "/requests/"+rq+"/pay", "rqp-1", `{}`), 201))["payment_id"].(string)

	e.refuseBatch("a capture", "k-cap", 422, "linked_payment_immutable", btItem(capture, 1, 5, btT2))
	e.refuseBatch("a refund", "k-ref", 422, "linked_payment_immutable", btItem(refund, 1, 5, btT2))
	e.refuseBatch("capture among valid items", "k-mix", 422, "linked_payment_immutable", btItem("p_2", 1, 40, btT2), btItem(capture, 1, 5, btT2))
	e.refuseBatch("linked before stale on one item", "k-lst", 422, "linked_payment_immutable", btItem(capture, 9, 5, btT2))
	e.refuseBatch("a stale item before a capture", "k-stc", 409, "stale_revision", btItem("p_3", 7, 5, btT2), btItem(capture, 1, 5, btT2))

	// The operator is not a party to p_3 (bob>cy) or the request payment (cy>bob) and may correct both.
	before := e.sumBalances()
	out := e.batchOK("k-ok", btItem("p_3", 1, 20, btT2), btItem(reqPay, 1, 10, btT2))
	if len(out.Revisions) != 2 || out.Revisions[0].PaymentID != "p_3" || out.Revisions[1].PaymentID != reqPay {
		t.Fatalf("%+v", out)
	}
	if e.sumBalances() != before {
		t.Fatal("a batch must preserve the sum of balances")
	}
	// A third user cannot use the route.
	txWantErr(t, "non-operator", e.batch("cy", "k-cy", btItem("p_3", 2, 25, btT2)), 403, "forbidden")
}

func TestBatchBelowRefundedAmount(t *testing.T) { // U30 refund_exceeds_payment
	e := btBase(t)
	txWant(t, "refund", e.do("bob", "POST", "/payments/p_1/refunds", "ref-1", `{"amount":40}`), 201)
	e.refuseBatch("one below refunded", "k39", 422, "refund_exceeds_payment", btItem("p_1", 1, 39, btT2))
	e.refuseBatch("a stale revision is reported first", "kst", 409, "stale_revision", btItem("p_1", 5, 39, btT2))
	e.refuseBatch("the second item is below", "k2nd", 422, "refund_exceeds_payment", btItem("p_2", 1, 40, btT2), btItem("p_1", 1, 0, btT2))
	e.batchOK("k40", btItem("p_1", 1, 40, btT2))
	txWantErr(t, "nothing left to refund", e.do("bob", "POST", "/payments/p_1/refunds", "ref-2", `{"amount":1}`), 422, "refund_exceeds_payment")
}

func TestBatchSettlementRules(t *testing.T) { // U25, U26, U27, U29, U39
	e := btBase(t)
	st1 := e.settle("st-1", btLeg("ada", "bob", 100), btLeg("bob", "cy", 40), btLeg("cy", "dee", 10))
	st2 := e.settle("st-2", btLeg("ada", "cy", 5), btLeg("ada", "dee", 5))
	a, b, c := st1[0], st1[1], st1[2]
	d := st2[0]
	spell := []string{"2026-09-20T10:00:00+00:00", "2026-09-20T12:00:00+02:00", "2026-09-20T10:00:00Z"}

	e.refuseBatch("one of three members", "k1", 422, "incomplete_settlement", btItem(a, 1, 90, btT1))
	e.refuseBatch("two of three members", "k2", 422, "incomplete_settlement", btItem(a, 1, 90, btT1), btItem(b, 1, 30, btT1))
	e.refuseBatch("a member of each of two settlements", "k3", 422, "incomplete_settlement",
		btItem(a, 1, 90, btT1), btItem(b, 1, 30, btT1), btItem(c, 1, 5, btT1), btItem(d, 1, 4, btT1))
	e.refuseBatch("different instants", "k4", 422, "validation_failed", btItem(a, 1, 90, btT1), btItem(b, 1, 30, btT2), btItem(c, 1, 5, btT1))
	e.refuseBatch("instants a second apart", "k5", 422, "validation_failed",
		btItem(a, 1, 90, btT1), btItem(b, 1, 30, "2026-09-20T10:00:01+00:00"), btItem(c, 1, 5, btT1))
	e.refuseBatch("incomplete and different instants: completeness first", "k6", 422, "incomplete_settlement",
		btItem(a, 1, 90, btT1), btItem(b, 1, 30, btT2))
	e.refuseBatch("an item error beats completeness (404)", "k7", 404, "not_found", btItem(a, 1, 90, btT1), btItem("p_999", 1, 1, btT1))
	e.refuseBatch("an item error beats completeness (stale)", "k8", 409, "stale_revision", btItem(a, 1, 90, btT1), btItem("p_3", 5, 1, btT1))
	e.refuseBatch("completeness beats current funds", "k9", 422, "incomplete_settlement", btItem(a, 1, 1000000000, btT1))
	e.refuseBatch("completeness beats historical overdraft", "k10", 422, "incomplete_settlement", btItem(a, 1, 100, "2000-01-01T00:00:00+00:00"))
	e.refuseBatch("instants beat current funds", "k11", 422, "validation_failed",
		btItem(a, 1, 1000000000, btT1), btItem(b, 1, 30, btT2), btItem(c, 1, 5, btT1))

	// Single corrections: members stay refused (stage 3), nonmembers stay available (U27).
	txWantErr(t, "single correction of a member", e.correct("ada", a, "s-1", 1, 50, btT1, "x"), 422, "linked_payment_immutable")
	e.mustCorrect("ada", "p_1", "s-2", 1, 90, btT2)

	// A refund of a member is allowed and is not a member: the settlement is still the original three.
	ref := txJSON(t, txWant(t, "refund of a member", e.do("bob", "POST", "/payments/"+a+"/refunds", "ref-a", `{"amount":30}`), 201))
	if ref["settlement_id"] != nil || ref["refund_of"] != a {
		t.Fatalf("a refund never joins the settlement: %v", ref)
	}
	out := e.batchOK("ok", btItem(c, 1, 5, spell[2]), btItem(a, 1, 80, spell[0]), btItem(b, 1, 35, spell[1]), btItem("p_3", 1, 25, btT3))
	if len(out.Revisions) != 4 || out.Revisions[0].PaymentID != c || out.Revisions[3].PaymentID != "p_3" {
		t.Fatalf("input order: %+v", out)
	}
	e.refuseBatch("a member below its refunded amount", "k12", 422, "refund_exceeds_payment", btItem(a, 2, 29, btT1), btItem(b, 2, 35, btT1), btItem(c, 2, 5, btT1))
	e.batchOK("again", btItem(b, 2, 36, btT2), btItem(a, 2, 30, btT2), btItem(c, 2, 6, btT2))
	// The other settlement is independent and complete with its own two members.
	e.batchOK("second", btItem(st2[1], 1, 4, btT3), btItem(d, 1, 6, btT3))
	// Nothing changed membership: the payments still name their settlement.
	feed := e.do("ada", "GET", "/activity?limit=200", "", "").Body.String()
	if strings.Count(feed, `"settlement_id":"st_1"`) != 3 || strings.Count(feed, `"settlement_id":"st_2"`) != 2 {
		t.Fatalf("settlement membership changed: %s", feed)
	}
}

func TestBatchCombinedAffordability(t *testing.T) { // U31
	// bob has 100: p_1 bob>cy 100 and p_2 ada>bob 100. Raising p_1 debits bob, lowering p_2 debits bob.
	fx := func(extra ...string) *tsEnv {
		return tsNewU(t, [4]int64{1000, 100, 100, 0}, append([]string{tsPays(tsSeedPay("p_1", "bob", "cy", 100, btT1), tsSeedPay("p_2", "ada", "bob", 100, btT1))}, extra...)...)
	}
	e := fx()
	e.refuseBatch("alone: bob short by 100", "a", 409, "insufficient_funds", btItem("p_1", 1, 300, btT1))
	e.refuseBatch("net -200 against 100", "b", 409, "insufficient_funds", btItem("p_1", 1, 400, btT1), btItem("p_2", 1, 200, btT1))
	e.refuseBatch("two debits of 100", "c", 409, "insufficient_funds", btItem("p_1", 1, 200, btT1), btItem("p_2", 1, 0, btT1))
	e.refuseBatch("the order of items does not matter", "d", 409, "insufficient_funds", btItem("p_2", 1, 0, btT1), btItem("p_1", 1, 200, btT1))
	// One item's credit pays for the other's debit: item by item the first would fail.
	before := e.sumBalances()
	e.batchOK("net-zero", btItem("p_1", 1, 300, btT1), btItem("p_2", 1, 300, btT1))
	if got := txNum(e.me("bob", ""), "balance"); got != 100 || txNum(e.me("cy", ""), "balance") != 300 || txNum(e.me("ada", ""), "balance") != 800 || e.sumBalances() != before {
		t.Fatalf("balances after the net-zero batch: bob %d", got)
	}
	// Spending exactly all of the available funds is allowed.
	e2 := fx()
	e2.batchOK("exact", btItem("p_2", 1, 0, btT1))
	if got := e2.me("bob", ""); txNum(got, "available") != 0 || txNum(got, "balance") != 0 {
		t.Fatalf("bob after spending everything: %v", got)
	}

	// Held funds do not count toward the combined effect.
	e3 := fx()
	txWant(t, "bob's hold", e3.do("bob", "POST", "/authorizations", "h-1", `{"to_handle":"dee","amount":60}`), 201)
	e3.refuseBatch("balance 100 but available 40", "h", 409, "insufficient_funds", btItem("p_1", 1, 150, btT1))
	e3.batchOK("exactly the available 40", btItem("p_1", 1, 140, btT1))
}

func TestBatchHistoricalOverdraftAndPrecedence(t *testing.T) { // U29, U30
	// bob receives 100 at T1 and pays 100 at T2 (opening 0, balance 0).
	e := tsNewU(t, [4]int64{1000, 0, 100, 0}, tsPays(tsSeedPay("p_1", "ada", "bob", 100, btT1), tsSeedPay("p_2", "bob", "cy", 100, btT2)))
	// Same amount, received after the payment it funds: nothing is owed now, the past is negative.
	e.refuseBatch("moving the funding later", "h1", 409, "historical_overdraft", btItem("p_1", 1, 100, btT3))
	e.refuseBatch("a larger funding amount, received later (balances move, then roll back)", "h1b", 409, "historical_overdraft", btItem("p_1", 1, 150, btT3))
	e.refuseBatch("a lower funding amount at the same instant", "h2", 409, "insufficient_funds", btItem("p_1", 1, 50, btT1))
	// Both payments move to the same later instant: the boundary is judged after both.
	e.batchOK("together", btItem("p_1", 1, 100, btT3), btItem("p_2", 1, 100, btT3))

	// Current funds beat the past: this change is also negative at T1 but bob cannot afford it now.
	f := tsNewU(t, [4]int64{1000, 100, 100, 0}, tsPays(tsSeedPay("p_1", "bob", "cy", 100, btT1), tsSeedPay("p_2", "ada", "bob", 100, btT1)))
	f.refuseBatch("funds before history", "h3", 409, "insufficient_funds", btItem("p_1", 1, 400, btT1))

	// Available (total less holds), not only the total, is checked at a hold's creation.
	g := tsNewU(t, [4]int64{1000, 100, 100, 0}, tsPays(tsSeedPay("p_1", "ada", "bob", 100, btT1)))
	txWant(t, "bob's hold", g.do("bob", "POST", "/authorizations", "h-1", `{"to_handle":"cy","amount":60}`), 201)
	time.Sleep(5 * time.Millisecond)
	afterHold := time.Now().UTC().Format("2006-01-02T15:04:05.000000+00:00")
	g.refuseBatch("funding arrives after the hold exists", "h4", 409, "historical_overdraft", btItem("p_1", 1, 100, afterHold))
}

func TestBatchRejectionsLeaveNoTraceAndTheKeyStaysFree(t *testing.T) { // U32
	e := btBase(t)
	e.refuseBatch("unknown", "same", 404, "not_found", btItem("p_999", 1, 1, btT2))
	e.refuseBatch("unaffordable", "same", 409, "insufficient_funds", btItem("p_1", 1, 1000000, btT2))
	out := e.batchOK("same", btItem("p_1", 1, 90, btT2))
	if out.CorrectionBatchID != "cb_1" {
		t.Fatalf("rejected batches consumed an id: %s", out.CorrectionBatchID)
	}
}

func TestBatchResponseHistoryAndFrozenViews(t *testing.T) { // U33, U34, U36, U37, U38
	e := btBase(t)
	api := e.do("ada", "POST", "/payments", "pay-1", `{"to_handle":"bob","amount":60,"note":"api"}`)
	apiBody := txWant(t, "payment", api, 201)
	apiID := txJSON(t, apiBody)["payment_id"].(string)
	stBody := txWant(t, "settlement", e.do("ada", "POST", "/settlements", "st-1", `{"transfers":[`+btLeg("ada", "bob", 20)+`,`+btLeg("bob", "cy", 10)+`]}`), 201)
	var settled struct {
		Payments []struct {
			PaymentID string `json:"payment_id"`
		}
	}
	_ = json.Unmarshal(stBody, &settled)
	m1, m2 := settled.Payments[0].PaymentID, settled.Payments[1].PaymentID

	snap := e.stmt("bob", tsQ("limit", "2"))
	frozen := func() []string {
		var pages []string
		for off := 0; off < 20; off += 2 {
			p := e.stmt("bob", tsQ("snapshot", snap.Snapshot, "limit", "2", "offset", fmt.Sprint(off)))
			pages = append(pages, string(p.raw))
			if !p.HasMore {
				break
			}
		}
		return pages
	}
	pagesBefore := frozen()
	feedBefore := e.do("ada", "GET", "/activity?limit=200", "", "").Body.String()
	sumBefore := e.sumBalances()
	exportBefore := e.export()
	prev := map[string]string{}
	for _, id := range []string{"p_1", "p_3", apiID, m1, m2} {
		revs := e.revsAny(id)
		prev[id] = revs[len(revs)-1].RecordedAt
	}

	items := []string{btItem(m2, 1, 12, btT2), btItem("p_1", 1, 90, "2026-09-20T14:00:00+02:00"), btItem(apiID, 1, 55, btT3), btItem(m1, 1, 22, btT2), btItem("p_3", 1, 25, btT3)}
	rec := e.batch("ada", "batch-1", items...)
	raw := txWant(t, "batch", rec, 201)
	var top map[string]json.RawMessage
	_ = json.Unmarshal(raw, &top)
	if len(top) != 3 || top["correction_batch_id"] == nil || top["recorded_at"] == nil || top["revisions"] == nil {
		t.Fatalf("body keys: %s", raw)
	}
	var out btOut
	_ = json.Unmarshal(raw, &out)
	if !btIDRe.MatchString(out.CorrectionBatchID) || !tsMicroRe.MatchString(out.RecordedAt) {
		t.Fatalf("id or recorded_at: %s", raw)
	}
	wantIDs, wantAmt, wantEff := []string{m2, "p_1", apiID, m1, "p_3"}, []int64{12, 90, 55, 22, 25}, []string{btT2, "2026-09-20T14:00:00+02:00", btT3, btT2, btT3}
	if len(out.Revisions) != 5 {
		t.Fatalf("%s", raw)
	}
	for i, r := range out.Revisions {
		if r.PaymentID != wantIDs[i] || r.Revision != 2 || r.Amount != wantAmt[i] || r.EffectiveAt != wantEff[i] || r.Reason != "batch" ||
			r.RecordedAt != out.RecordedAt || r.CorrectionBatchID == nil || *r.CorrectionBatchID != out.CorrectionBatchID {
			t.Fatalf("revision %d: %+v", i, r)
		}
		if p, _ := ParseInstant(prev[r.PaymentID]); !p.Before(mustInstant(t, out.RecordedAt)) {
			t.Fatalf("recorded_at %s is not later than the member's previous %s", out.RecordedAt, prev[r.PaymentID])
		}
		stored := e.revsAny(r.PaymentID)
		if len(stored) != 2 || stored[0].CorrectionBatchID != nil || stored[1].CorrectionBatchID == nil || *stored[1].CorrectionBatchID != out.CorrectionBatchID {
			t.Fatalf("revisions of %s: %+v", r.PaymentID, stored)
		}
		s1, r1 := stored[1], r
		s1.CorrectionBatchID, r1.CorrectionBatchID = nil, nil
		if s1 != r1 {
			t.Fatalf("the revisions endpoint differs from the batch response: %+v vs %+v", s1, r1)
		}
	}
	if e.sumBalances() != sumBefore {
		t.Fatal("the sum of balances must not change")
	}

	// Original receipts: the payment and settlement keys replay their original bytes; the feed shows the originals.
	if rp := e.do("ada", "POST", "/payments", "pay-1", `{"to_handle":"bob","amount":60,"note":"api"}`); rp.Code != 200 || !bytes.Equal(rp.Body.Bytes(), apiBody) {
		t.Fatalf("payment replay: %d %s", rp.Code, rp.Body)
	}
	if rp := e.do("ada", "POST", "/settlements", "st-1", `{"transfers":[`+btLeg("ada", "bob", 20)+`,`+btLeg("bob", "cy", 10)+`]}`); rp.Code != 200 || !bytes.Equal(rp.Body.Bytes(), stBody) {
		t.Fatalf("settlement replay: %d %s", rp.Code, rp.Body)
	}
	if feed := e.do("ada", "GET", "/activity?limit=200", "", "").Body.String(); feed != feedBefore {
		t.Fatal("the feed must keep showing the original payments")
	}
	if strings.Contains(string(e.export()), `"correction_batch_id":"`) == false || bytes.Equal(exportBefore, e.export()) {
		t.Fatal("the batch must be in the export")
	}

	// Earlier snapshot tokens page what they froze; a new statement shows the corrected world.
	if after := frozen(); strings.Join(after, "|") != strings.Join(pagesBefore, "|") {
		t.Fatalf("the snapshot changed:\n%v\n%v", pagesBefore, after)
	}
	fresh := e.stmt("bob", tsQ("limit", "50"))
	seen := map[string]int64{}
	for _, en := range fresh.Entries {
		seen[en.Payment["payment_id"].(string)] = en.Revision
	}
	if seen[apiID] != 2 || seen[m1] != 2 || seen["p_1"] != 2 {
		t.Fatalf("a new statement must select the batch revisions: %v", seen)
	}

	// Replay: 200 with the original bytes, nothing moves; the same key with another body is refused.
	exportMid := e.export()
	if rp := e.batch("ada", "batch-1", items...); rp.Code != 200 || !bytes.Equal(rp.Body.Bytes(), raw) {
		t.Fatalf("replay: %d %s", rp.Code, rp.Body)
	}
	txWantErr(t, "same key, another body", e.batch("ada", "batch-1", btItem("p_1", 2, 91, btT2)), 409, "idempotency_key_reuse")
	if !bytes.Equal(exportMid, e.export()) {
		t.Fatal("replays and reuse must not change the state")
	}

	// A second batch gets a new id and a strictly later recorded_at.
	out2 := e.batchOK("batch-2", btItem("p_1", 2, 91, btT2))
	if out2.CorrectionBatchID == out.CorrectionBatchID || !btIDRe.MatchString(out2.CorrectionBatchID) || out2.RecordedAt <= out.RecordedAt {
		t.Fatalf("second batch: %+v after %+v", out2, out)
	}
	// A replay still returns the first body after later batches.
	if rp := e.batch("ada", "batch-1", items...); rp.Code != 200 || !bytes.Equal(rp.Body.Bytes(), raw) {
		t.Fatalf("late replay: %d %s", rp.Code, rp.Body)
	}
}

func mustInstant(t testing.TB, s string) time.Time {
	t.Helper()
	v, ok := ParseInstant(s)
	if !ok {
		t.Fatalf("not an instant: %q", s)
	}
	return v
}

// revsAny reads a payment's revisions as whichever party can see them.
func (e *tsEnv) revsAny(id string) []btRev {
	e.t.Helper()
	for _, u := range []string{"ada", "bob", "cy", "dee"} {
		rec := e.do(u, "GET", "/payments/"+id+"/revisions", "", "")
		if rec.Code != 200 {
			continue
		}
		var out struct {
			Revisions []btRev `json:"revisions"`
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
			e.t.Fatal(err)
		}
		return out.Revisions
	}
	e.t.Fatalf("no party can read the revisions of %s", id)
	return nil
}

func TestBatchRecordedAtPastAnImportedFutureRevision(t *testing.T) { // U34 with an imported member recorded ahead of the clock
	e := btBase(t)
	future := time.Now().UTC().Add(time.Hour).Truncate(time.Microsecond)
	top := txJSON(t, e.export())
	for _, r := range top["state"].(map[string]any)["revisions"].([]any) {
		if m := r.(map[string]any); m["payment_id"] == "p_1" {
			m["recorded_at"] = FormatMicro(future)
		}
	}
	raw, _ := json.Marshal(top)
	txWant(t, "import", e.do("ada", "POST", "/_test/import", "", string(raw)), 204)
	f := e
	out := f.batchOK("k", btItem("p_1", 1, 90, btT2), btItem("p_2", 1, 40, btT2))
	if want := FormatMicro(future.Add(time.Microsecond)); out.RecordedAt != want {
		t.Fatalf("recorded_at %s, want %s (one microsecond after the member recorded ahead of the clock)", out.RecordedAt, want)
	}
	for _, r := range out.Revisions {
		if r.RecordedAt != out.RecordedAt {
			t.Fatalf("all revisions share recorded_at: %+v", out)
		}
	}
	// A read that begins after the batch returned sees it.
	seen := map[string]int64{}
	for _, en := range f.stmt("bob", tsQ("limit", "50")).Entries {
		seen[en.Payment["payment_id"].(string)] = en.Revision
	}
	if seen["p_1"] != 2 {
		t.Fatalf("a read after the batch must see its revisions: %v", seen)
	}
}

func TestBatchConcurrentSharedRevisions(t *testing.T) { // U40
	count := func(codes []int) (created, stale int) {
		for _, c := range codes {
			switch c {
			case 201:
				created++
			case 409:
				stale++
			default:
				t.Fatalf("unexpected status %d in %v", c, codes)
			}
		}
		return
	}
	t.Run("one shared payment, many batches", func(t *testing.T) {
		e := tsNewU(t, [4]int64{100000, 500, 100, 0}, btManyPays(9))
		sum := e.sumBalances()
		var mu sync.Mutex
		var results []int
		var wg sync.WaitGroup
		start := make(chan struct{})
		for i := 0; i < 16; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				<-start
				rec := e.batch("ada", fmt.Sprintf("c-%d", i), btItem("p_1", 1, int64(2+i), btT2), btItem(fmt.Sprintf("p_%d", 2+i%8), 1, 5, btT2))
				mu.Lock()
				results = append(results, rec.Code)
				mu.Unlock()
			}(i)
		}
		close(start)
		wg.Wait()
		if created, stale := count(results); created != 1 || stale != 15 {
			t.Fatalf("%d batches won, %d stale (want 1 and 15)", created, stale)
		}
		if revs := e.revsAny("p_1"); len(revs) != 2 {
			t.Fatalf("p_1 has %d revisions", len(revs))
		}
		if e.sumBalances() != sum {
			t.Fatal("sum of balances changed")
		}
	})
	t.Run("a ring of overlapping batches", func(t *testing.T) {
		for round := 0; round < 12; round++ {
			e := tsNewU(t, [4]int64{100000, 500, 100, 0}, btManyPays(3))
			sets := [][2]string{{"p_1", "p_2"}, {"p_2", "p_3"}, {"p_3", "p_1"}}
			var mu sync.Mutex
			var results []int
			var wg sync.WaitGroup
			start := make(chan struct{})
			for i, s := range sets {
				wg.Add(1)
				go func(i int, s [2]string) {
					defer wg.Done()
					<-start
					rec := e.batch("ada", fmt.Sprintf("r-%d", i), btItem(s[0], 1, 2, btT2), btItem(s[1], 1, 3, btT2))
					mu.Lock()
					results = append(results, rec.Code)
					mu.Unlock()
				}(i, s)
			}
			close(start)
			wg.Wait()
			if created, stale := count(results); created != 1 || stale != 2 {
				t.Fatalf("round %d: %d won, %d stale (the three batches overlap pairwise)", round, created, stale)
			}
			total := 0
			for _, id := range []string{"p_1", "p_2", "p_3"} {
				total += len(e.revsAny(id)) - 1
			}
			if total != 2 {
				t.Fatalf("round %d: %d new revisions, want exactly the winner's 2", round, total)
			}
		}
	})
	t.Run("a batch against a single correction", func(t *testing.T) {
		for round := 0; round < 12; round++ {
			e := tsNewU(t, [4]int64{100000, 500, 100, 0}, btManyPays(2))
			var mu sync.Mutex
			var results []int
			var wg sync.WaitGroup
			start := make(chan struct{})
			wg.Add(2)
			go func() {
				defer wg.Done()
				<-start
				rec := e.batch("ada", "b", btItem("p_1", 1, 2, btT2), btItem("p_2", 1, 2, btT2))
				mu.Lock()
				results = append(results, rec.Code)
				mu.Unlock()
			}()
			go func() {
				defer wg.Done()
				<-start
				rec := e.correct("ada", "p_1", "s", 1, 7, btT2, "single")
				mu.Lock()
				results = append(results, rec.Code)
				mu.Unlock()
			}()
			close(start)
			wg.Wait()
			if created, stale := count(results); created != 1 || stale != 1 {
				t.Fatalf("round %d: %v", round, results)
			}
		}
	})
	t.Run("one key sent many times", func(t *testing.T) {
		e := tsNewU(t, [4]int64{100000, 500, 100, 0}, btManyPays(2))
		codes, bodies := txConcurrent(12, func() *httptest.ResponseRecorder {
			return e.batch("ada", "same", btItem("p_1", 1, 2, btT2), btItem("p_2", 1, 3, btT2))
		})
		txOneCreated(t, "same batch key", codes, bodies)
		if revs := e.revsAny("p_1"); len(revs) != 2 {
			t.Fatalf("exactly one effect: %d revisions", len(revs))
		}
	})
	t.Run("a refund against a correction of the same payment", func(t *testing.T) {
		for round := 0; round < 12; round++ {
			e := btBase(t)
			var mu sync.Mutex
			var results []int
			var wg sync.WaitGroup
			start := make(chan struct{})
			wg.Add(2)
			go func() {
				defer wg.Done()
				<-start
				rec := e.batch("ada", "b", btItem("p_1", 1, 50, btT2))
				mu.Lock()
				results = append(results, rec.Code)
				mu.Unlock()
			}()
			go func() {
				defer wg.Done()
				<-start
				rec := e.do("bob", "POST", "/payments/p_1/refunds", "r", `{"amount":60}`)
				mu.Lock()
				results = append(results, rec.Code)
				mu.Unlock()
			}()
			close(start)
			wg.Wait()
			if created, refused := func() (int, int) {
				c, r := 0, 0
				for _, code := range results {
					switch code {
					case 201:
						c++
					case 422:
						r++
					}
				}
				return c, r
			}(); created != 1 || refused != 1 {
				t.Fatalf("round %d: %v (the refund of 60 and a correction to 50 exclude each other)", round, results)
			}
		}
	})
}

func TestBatchStateRoundTripsThroughExportImport(t *testing.T) { // U41, stage-4 export -> import -> export
	e := btBase(t)
	st1 := e.settle("st-1", btLeg("ada", "bob", 100), btLeg("bob", "cy", 40))
	txWant(t, "refund", e.do("bob", "POST", "/payments/p_1/refunds", "ref-1", `{"amount":10}`), 201)
	first := e.batchOK("b-1", btItem(st1[0], 1, 90, btT1), btItem(st1[1], 1, 35, btT1), btItem("p_3", 1, 25, btT2))
	e.mustCorrect("ada", "p_1", "c-1", 1, 95, btT2)
	e.batchOK("b-2", btItem("p_3", 2, 20, btT3))

	e1 := e.export()
	if !bytes.Contains(e1, []byte(`"refund_of":"p_1"`)) || !bytes.Contains(e1, []byte(`"correction_batch_id":"`+first.CorrectionBatchID+`"`)) {
		t.Fatalf("the export must carry the refund and the batch id")
	}
	firstRaw := e.batch("ada", "b-1", btItem(st1[0], 1, 90, btT1), btItem(st1[1], 1, 35, btT1), btItem("p_3", 1, 25, btT2)).Body.Bytes()

	for round := 0; round < 2; round++ {
		txWant(t, "import", e.do("ada", "POST", "/_test/import", "", string(e1)), 204)
		if e2 := e.export(); !bytes.Equal(e1, e2) {
			t.Fatalf("round %d: export -> import -> export is not byte-identical", round)
		}
	}
	// The imported service keeps working where the exporter left off.
	if rp := e.batch("ada", "b-1", btItem(st1[0], 1, 90, btT1), btItem(st1[1], 1, 35, btT1), btItem("p_3", 1, 25, btT2)); rp.Code != 200 || !bytes.Equal(rp.Body.Bytes(), firstRaw) {
		t.Fatalf("replay after import: %d %s", rp.Code, rp.Body)
	}
	e.refuseBatch("settlement membership survived the import", "m", 422, "incomplete_settlement", btItem(st1[0], 2, 80, btT1))
	next := e.batchOK("b-3", btItem(st1[0], 2, 80, btT1), btItem(st1[1], 2, 30, btT1))
	if next.CorrectionBatchID == first.CorrectionBatchID || next.CorrectionBatchID == "cb_2" {
		t.Fatalf("an imported batch id was issued again: %s", next.CorrectionBatchID)
	}
	if revs := e.revsAny(st1[0]); len(revs) != 3 || revs[0].CorrectionBatchID != nil || *revs[1].CorrectionBatchID != first.CorrectionBatchID {
		t.Fatalf("history after import: %+v", revs)
	}
	// An imported batch id is never issued again even when the id counters were lost.
	top := txJSON(t, e.export())
	top["state"].(map[string]any)["seq"] = map[string]any{}
	raw, _ := json.Marshal(top)
	g := &tsEnv{t: t, h: NewServer(NewStore()), tok: e.tok}
	txWant(t, "import without counters", txDo(g.h, "POST", "/_test/import", "", "", string(raw)), 204)
	seen := map[string]bool{}
	for _, r := range g.revsAny(st1[0]) {
		if r.CorrectionBatchID != nil {
			seen[*r.CorrectionBatchID] = true
		}
	}
	fresh := g.batchOK("b-4", btItem("p_3", 3, 19, btT3))
	if seen[fresh.CorrectionBatchID] || fresh.CorrectionBatchID == "cb_1" || fresh.CorrectionBatchID == "cb_2" || fresh.CorrectionBatchID == "cb_3" {
		t.Fatalf("batch id %s collides with an imported one", fresh.CorrectionBatchID)
	}
}
