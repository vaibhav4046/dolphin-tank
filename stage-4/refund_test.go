package main

import (
	"bytes"
	"strings"
	"sync"
	"testing"
	"time"
)

func rfRefund(st *State, who, pid string, amount int64, now time.Time) (*Payment, *AppError) {
	return st.Refund("u_"+who, pid, RefundIn{Amount: amount}, now)
}

func rfMust(t *testing.T, st *State, who, pid string, amount int64, now time.Time) *Payment {
	t.Helper()
	r, e := rfRefund(st, who, pid, amount, now)
	if e != nil {
		t.Fatalf("refund %s by %s %d: %v", pid, who, amount, e)
	}
	return r
}

func rfSum(st *State) (sum int64) {
	for _, u := range st.Users {
		sum += u.Balance
	}
	return sum
}

// U02, U04, U06, U09 and the order of checks: nothing changes on any error.
func TestRefundErrorOrderAndAtomicity(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0}, fgU{"dee", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	small := hsPay(t, st, "ada", "dee", 100, hsAt(time.Second))
	refund := rfMust(t, st, "bob", p.PaymentID, 100, hsAt(2*time.Second))
	hsPay(t, st, "bob", "cy", 900, hsAt(3*time.Second)) // bob holds nothing now
	now := hsAt(time.Minute)
	before := crSnapshot(st)

	cases := []struct {
		name   string
		who    string
		pid    string
		amount int64
		status int
		code   string
	}{
		{"zero amount", "bob", p.PaymentID, 0, 422, "validation_failed"},
		{"negative amount", "bob", p.PaymentID, -1, 422, "validation_failed"},
		{"amount over a billion", "bob", p.PaymentID, 1_000_000_001, 422, "validation_failed"},
		{"validation beats unknown payment", "bob", "p_999", 0, 422, "validation_failed"},
		{"validation beats not receiver", "ada", p.PaymentID, 0, 422, "validation_failed"},
		{"unknown payment", "bob", "p_999", 5, 404, "not_found"},
		{"unknown payment beats not receiver", "cy", "p_999", 5, 404, "not_found"},
		{"sender", "ada", p.PaymentID, 5, 403, "forbidden"},
		{"third party", "cy", p.PaymentID, 5, 403, "forbidden"},
		{"not receiver beats refund target", "bob", refund.PaymentID, 5, 403, "forbidden"},
		{"refund of a refund", "ada", refund.PaymentID, 5, 422, "invalid_refund_target"},
		{"refund of a refund beats the limit", "ada", refund.PaymentID, 1_000_000_000, 422, "invalid_refund_target"},
		{"one over the remainder", "bob", p.PaymentID, 901, 422, "refund_exceeds_payment"},
		{"limit beats insufficient funds", "dee", small.PaymentID, 101, 422, "refund_exceeds_payment"},
		{"spent funds", "bob", p.PaymentID, 900, 409, "insufficient_funds"},
	}
	for _, c := range cases {
		r, e := rfRefund(st, c.who, c.pid, c.amount, now)
		if r != nil {
			t.Errorf("%s: payment with an error", c.name)
		}
		fgWantErr(t, c.name, e, c.status, c.code)
	}
	if crSnapshot(st) != before {
		t.Fatal("refused refunds changed the state")
	}
	if _, e := st.Refund("u_nobody", p.PaymentID, RefundIn{Amount: 5}, now); e == nil || e.Status != 401 {
		t.Fatal(e)
	}
}

// U05, U07, U09, U16: exact limit, one over, partials, fields of the refund payment.
func TestRefundFieldsPartialsAndExactLimit(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 1000, Note: "lunch", Visibility: visPrivate}, hsAt(0))
	if e != nil {
		t.Fatal(e)
	}
	at := hsAt(10*time.Second + 123456*time.Microsecond)
	r1 := rfMust(t, st, "bob", p.PaymentID, 300, at)
	m := azJSON(t, r1)
	if m["refund_of"] != p.PaymentID || m["request_id"] != nil || m["authorization_id"] != nil || m["settlement_id"] != nil ||
		m["from_handle"] != "bob" || m["to_handle"] != "ada" || m["from_user_id"] != "u_bob" || m["to_user_id"] != "u_ada" ||
		m["amount"] != 300.0 || m["note"] != "lunch" || m["visibility"] != "private" || m["currency"] != "EUR" ||
		m["created_at"] != "2026-09-24T13:10:10.123456+00:00" || m["payment_id"] == p.PaymentID {
		t.Fatalf("%v", m)
	}
	if hs := st.revByPay[r1.PaymentID]; len(hs) != 1 || hs[0].Revision != 1 || hs[0].Amount != 300 ||
		hs[0].EffectiveAt != r1.CreatedAt || hs[0].RecordedAt != r1.CreatedAt {
		t.Fatalf("a refund has revision 1 at its own created_at: %+v", hs)
	}
	if azJSON(t, p)["refund_of"] != nil {
		t.Fatal("an ordinary payment carries refund_of null")
	}
	if _, has := azJSON(t, p)["refund_of"]; !has {
		t.Fatal("refund_of must always be present")
	}
	if crBalances(st) != "ada=9300 bob=700" || st.refundedAmount(p.PaymentID) != 300 || !r1.isRefund() || p.isRefund() {
		t.Fatal(crBalances(st), st.refundedAmount(p.PaymentID))
	}
	rfMust(t, st, "bob", p.PaymentID, 300, hsAt(20*time.Second))
	rfMust(t, st, "bob", p.PaymentID, 400, hsAt(30*time.Second)) // exactly the remainder
	if crBalances(st) != "ada=10000 bob=0" || st.refundedAmount(p.PaymentID) != 1000 {
		t.Fatal(crBalances(st))
	}
	_, e = rfRefund(st, "bob", p.PaymentID, 1, hsAt(40*time.Second))
	fgWantErr(t, "one unit over", e, 422, "refund_exceeds_payment")
	if err := hsCheck(st, 10000, hsAt(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if st.refundedAmount("p_999") != 0 {
		t.Fatal("nothing is refunded against an unknown id")
	}
}

// U05, U14: the limit is the corrected amount; a correction may not go below what is refunded.
func TestRefundAndCorrectionLimits(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	crMust(t, st, "ada", p, crIn(1, 600, crT0, "down"), hsAt(time.Minute))
	rfMust(t, st, "bob", p.PaymentID, 600, hsAt(2*time.Minute))
	_, e := rfRefund(st, "bob", p.PaymentID, 1, hsAt(3*time.Minute))
	fgWantErr(t, "corrected down: limit is 600", e, 422, "refund_exceeds_payment")

	crMust(t, st, "ada", p, crIn(2, 900, crT0, "up"), hsAt(4*time.Minute))
	rfMust(t, st, "bob", p.PaymentID, 300, hsAt(5*time.Minute))
	_, e = rfRefund(st, "bob", p.PaymentID, 1, hsAt(6*time.Minute))
	fgWantErr(t, "corrected up: limit is 900", e, 422, "refund_exceeds_payment")

	before := crSnapshot(st)
	_, e = crCorrect(st, "ada", p, crIn(3, 899, crT0, "below refunded"), hsAt(7*time.Minute))
	fgWantErr(t, "one below refunded", e, 422, "refund_exceeds_payment")
	_, e = crCorrect(st, "ada", p, crIn(3, 0, crT0, "zero"), hsAt(7*time.Minute))
	fgWantErr(t, "zero below refunded", e, 422, "refund_exceeds_payment")
	_, e = crCorrect(st, "ada", p, crIn(2, 0, crT0, "stale first"), hsAt(7*time.Minute))
	fgWantErr(t, "stale beats refund_exceeds", e, 409, "stale_revision")
	if crSnapshot(st) != before {
		t.Fatal("refused corrections changed the state")
	}
	crMust(t, st, "ada", p, crIn(3, 900, crT0, "exactly refunded"), hsAt(8*time.Minute))
	crMust(t, st, "ada", p, crIn(4, 5000, crT0, "up again"), hsAt(9*time.Minute))
	rfMust(t, st, "bob", p.PaymentID, 4100, hsAt(10*time.Minute)) // bob holds 5000 - 1200 + ... enough
	_, e = rfRefund(st, "bob", p.PaymentID, 1, hsAt(11*time.Minute))
	fgWantErr(t, "refunded to the corrected amount", e, 422, "refund_exceeds_payment")

	// a payment corrected to 0 refuses every refund
	z := hsPay(t, st, "ada", "cy", 50, hsAt(12*time.Minute))
	crMust(t, st, "ada", z, crIn(1, 0, crT0, "reverse"), hsAt(13*time.Minute))
	_, e = rfRefund(st, "cy", z.PaymentID, 1, hsAt(14*time.Minute))
	fgWantErr(t, "corrected to zero", e, 422, "refund_exceeds_payment")

	// refund_exceeds_payment comes before insufficient_funds, which comes before historical_overdraft
	_, st2 := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	q := hsPay(t, st2, "ada", "bob", 1000, hsAt(0))
	rfMust(t, st2, "bob", q.PaymentID, 400, hsAt(time.Second))
	hsPay(t, st2, "bob", "cy", 600, hsAt(2*time.Second))
	_, e = crCorrect(st2, "ada", q, crIn(1, 300, crT0, "below"), hsAt(time.Minute))
	fgWantErr(t, "refund_exceeds_payment beats insufficient_funds", e, 422, "refund_exceeds_payment")
	_, e = crCorrect(st2, "ada", q, crIn(1, 400, crT0, "to refunded"), hsAt(time.Minute))
	fgWantErr(t, "bob cannot fund the 600 decrease", e, 409, "insufficient_funds")
	if err := hsCheck(st, 10000, hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
}

// U13: refunds, captures and settlement members are not correctable; the sender check still comes first.
func TestRefundPaymentsAreImmutable(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	refund := rfMust(t, st, "bob", p.PaymentID, 400, hsAt(time.Second))
	before := crSnapshot(st)
	_, e := crCorrect(st, "bob", refund, crIn(1, 100, crT0, "x"), hsAt(time.Minute))
	fgWantErr(t, "correct a refund", e, 422, "linked_payment_immutable")
	_, e = crCorrect(st, "bob", refund, crIn(9, 100, crT0, "x"), hsAt(time.Minute))
	fgWantErr(t, "linked beats stale", e, 422, "linked_payment_immutable")
	_, e = crCorrect(st, "ada", refund, crIn(1, 100, crT0, "x"), hsAt(time.Minute))
	fgWantErr(t, "only the refund's sender is asked, so the original sender is refused first", e, 403, "forbidden")
	if crSnapshot(st) != before {
		t.Fatal("refused corrections changed the state")
	}
}

// U03, U10: a request payment, a capture and a settlement member can be refunded and stay untouched.
func TestRefundOfRequestCaptureAndSettlementMember(t *testing.T) {
	_, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0})

	rq, e := st.CreateRequest("u_ada", RequestIn{PayerHandle: "bob", Amount: 500, Note: "rq"}, hsAt(0))
	if e != nil {
		t.Fatal(e)
	}
	hsPay(t, st, "ada", "bob", 5000, hsAt(time.Second))
	rp, e := st.PayRequest("u_bob", rq.RequestID, PayIn{Visibility: visPublic}, hsAt(2*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	reqBefore := string(mustJSON(rq))
	r1 := rfMust(t, st, "ada", rp.PaymentID, 500, hsAt(3*time.Second))
	if r1.RequestID != nil || r1.RefundOf == nil || *r1.RefundOf != rp.PaymentID || r1.Note != "rq" {
		t.Fatalf("%+v", r1)
	}
	if string(mustJSON(rq)) != reqBefore || rq.Status != statusPaid || rq.PaymentID == nil || *rq.PaymentID != rp.PaymentID {
		t.Fatal("a refund never reopens a request:", string(mustJSON(rq)))
	}

	a := azAuthorize(t, st, "ada", "bob", 3000, hsAt(10*time.Second))
	c := azMustCapture(t, st, "bob", a.AuthorizationID, azI64(1000), true, hsAt(11*time.Second)) // final: 2000 released
	authBefore, heldBefore := string(mustJSON(st.authBody(st.authByID[a.AuthorizationID], hsAt(time.Minute)))), st.Held("u_ada", hsAt(time.Minute))
	r2 := rfMust(t, st, "bob", c.PaymentID, 1000, hsAt(12*time.Second))
	if r2.AuthorizationID != nil || r2.RefundOf == nil || *r2.RefundOf != c.PaymentID {
		t.Fatalf("%+v", r2)
	}
	if got := string(mustJSON(st.authBody(st.authByID[a.AuthorizationID], hsAt(time.Minute)))); got != authBefore || st.Held("u_ada", hsAt(time.Minute)) != heldBefore {
		t.Fatalf("a refund neither reopens an authorization nor restores a released hold:\n%s\n%s", authBefore, got)
	}
	if st.authByID[a.AuthorizationID].Status != authCaptured || len(st.authByID[a.AuthorizationID].PaymentIDs) != 1 {
		t.Fatal("authorization changed")
	}
	_, e = rfRefund(st, "bob", c.PaymentID, 1, hsAt(13*time.Second))
	fgWantErr(t, "capture limit is its amount", e, 422, "refund_exceeds_payment")

	out, e := trSettle(st, map[string]any{"transfers": []any{
		map[string]any{"from_handle": "ada", "to_handle": "bob", "amount": float64(700)},
		map[string]any{"from_handle": "bob", "to_handle": "ada", "amount": float64(100)},
	}}, hsAt(20*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	members := out.(trSettlementOut).Payments
	sid := *members[0].SettlementID
	r3 := rfMust(t, st, "bob", members[0].PaymentID, 700, hsAt(21*time.Second))
	if r3.SettlementID != nil || *members[0].SettlementID != sid {
		t.Fatalf("a refund never changes settlement membership: %+v", r3)
	}
	n := 0
	for _, p := range st.Payments {
		if p.SettlementID != nil {
			n++
		}
	}
	if n != 2 {
		t.Fatalf("settlement members: %d", n)
	}
	if err := hsCheck(st, 100000, hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
}

// U09: funds held for an authorization do not count; a refund that does not fit changes nothing.
func TestRefundUsesAvailableNotHeldFunds(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	a := azAuthorize(t, st, "bob", "cy", 900, hsAt(time.Second))
	before := crSnapshot(st)
	_, e := rfRefund(st, "bob", p.PaymentID, 101, hsAt(2*time.Second))
	fgWantErr(t, "1000 total, 900 held", e, 409, "insufficient_funds")
	if crSnapshot(st) != before {
		t.Fatal("a refused refund left a trace")
	}
	rfMust(t, st, "bob", p.PaymentID, 100, hsAt(3*time.Second)) // exactly the available amount
	if st.Held("u_bob", hsAt(time.Minute)) != 900 || azBal(st, "bob") != 900 || azAvail(st, "bob", hsAt(time.Minute)) != 0 {
		t.Fatal("hold disturbed")
	}
	_, e = rfRefund(st, "bob", p.PaymentID, 1, hsAt(4*time.Second))
	fgWantErr(t, "nothing available", e, 409, "insufficient_funds")
	if _, e := st.Void("u_bob", a.AuthorizationID, hsAt(5*time.Second)); e != nil {
		t.Fatal(e)
	}
	rfMust(t, st, "bob", p.PaymentID, 800, hsAt(6*time.Second))
	if err := hsCheck(st, 10000, hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
}

// U07, U11, U16: refunds are ordinary payments in /me, /activity and /statement, as_of and known_at.
func TestRefundAppearsInViews(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	pub := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	priv, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 200, Visibility: visPrivate}, hsAt(time.Second))
	if e != nil {
		t.Fatal(e)
	}
	rp := rfMust(t, st, "bob", pub.PaymentID, 400, hsAt(10*time.Second))
	rv := rfMust(t, st, "bob", priv.PaymentID, 50, hsAt(11*time.Second))
	now := hsAt(time.Minute)

	asStr := func(d time.Duration) *string { return hsP(FormatMicro(hsAt(d))) }
	if m := hsMe(t, st, "bob", nil, nil, now); m["balance"] != 750.0 || m["total"] != 750.0 {
		t.Fatal(m)
	}
	if m := hsMe(t, st, "bob", asStr(5*time.Second), nil, now); m["total"] != 1200.0 {
		t.Fatalf("as_of before the refund: %v", m)
	}
	if m := hsMe(t, st, "bob", asStr(10*time.Second+500*time.Millisecond), nil, now); m["total"] != 800.0 {
		t.Fatalf("as_of between the refunds: %v", m)
	}
	if m := hsMe(t, st, "bob", asStr(30*time.Second), asStr(5*time.Second), now); m["total"] != 1200.0 {
		t.Fatalf("known_at before the refund: %v", m)
	}
	if m := hsMe(t, st, "ada", nil, nil, now); m["balance"] != 9250.0 {
		t.Fatal(m)
	}

	ids := func(caller string) []string {
		var out []string
		for _, p := range st.Activity(caller, 50, 0).(paymentPage).Payments {
			out = append(out, p.PaymentID)
		}
		return out
	}
	if got := strings.Join(ids("u_cy"), ","); got != rp.PaymentID+","+pub.PaymentID {
		t.Fatalf("a stranger sees the public refund only: %s", got)
	}
	if got := strings.Join(ids("u_ada"), ","); got != strings.Join([]string{rv.PaymentID, rp.PaymentID, priv.PaymentID, pub.PaymentID}, ",") {
		t.Fatalf("a party sees its private refund: %s", got)
	}
	if rv.Visibility != visPrivate || rp.Visibility != visPublic {
		t.Fatal("refund visibility follows the original")
	}

	stmt := func(who string, knownAt *string) statementBody {
		v, e := st.Statement("u_"+who, StatementQuery{KnownAt: knownAt, Limit: 50}, now)
		if e != nil {
			t.Fatal(e)
		}
		return v.(statementBody)
	}
	for _, c := range []struct {
		who     string
		deltas  []int64
		closing int64
	}{{"bob", []int64{1000, 200, -400, -50}, 750}, {"ada", []int64{-1000, -200, 400, 50}, 9250}} {
		s := stmt(c.who, nil)
		if len(s.Entries) != 4 || s.ClosingBalance != c.closing {
			t.Fatalf("%s: %+v", c.who, s)
		}
		for i, en := range s.Entries {
			if en.Delta != c.deltas[i] || en.Revision != 1 {
				t.Fatalf("%s entry %d: %+v", c.who, i, en)
			}
		}
		en := s.Entries[2]
		if en.Payment.PaymentID != rp.PaymentID || en.Payment.RefundOf == nil || *en.Payment.RefundOf != pub.PaymentID ||
			en.Payment.CreatedAt != rp.CreatedAt || en.EffectiveAt != rp.CreatedAt || en.RecordedAt != rp.CreatedAt {
			t.Fatalf("%s: %+v", c.who, en)
		}
		if s.Entries[0].Payment.RefundOf != nil {
			t.Fatal("an ordinary payment's statement entry carries refund_of null")
		}
	}
	if s := stmt("bob", asStr(5*time.Second)); len(s.Entries) != 2 || s.ClosingBalance != 1200 {
		t.Fatalf("known_at before the refunds: %+v", s)
	}
}

// U08 and the store's replay contract: the stored body carries refund_of and replays byte-identically.
func TestRefundReplayReturnsTheStoredBody(t *testing.T) {
	s, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	path := "/payments/" + p.PaymentID + "/refunds"
	call := func(key string, amount int64) (int, []byte, *AppError) {
		return s.Idempotent("u_bob", "POST", path, key, map[string]any{"amount": amount}, func(st *State) (any, *AppError) {
			r, e := st.Refund("u_bob", p.PaymentID, RefundIn{Amount: amount}, time.Now())
			if e != nil {
				return nil, e
			}
			return r, nil
		})
	}
	status, first, e := call("k1", 300)
	if e != nil || status != 201 || !bytes.Contains(first, []byte(`"refund_of":"`+p.PaymentID+`"`)) {
		t.Fatal(status, string(first), e)
	}
	if status, _, e = call("k2", 200); e != nil || status != 201 {
		t.Fatal(status, e)
	}
	status, again, e := call("k1", 300)
	if e != nil || status != 200 || !bytes.Equal(first, again) {
		t.Fatalf("replay: %d %s", status, again)
	}
	if _, _, e = call("k1", 301); e == nil || e.Code != "idempotency_key_reuse" {
		t.Fatal(e)
	}
	if st.refundedAmount(p.PaymentID) != 500 {
		t.Fatal("a replay must not refund twice")
	}
	// a refused refund consumes no key
	if _, _, e = call("k3", 501); e == nil || e.Code != "refund_exceeds_payment" {
		t.Fatal(e)
	}
	if status, _, e = call("k3", 500); e != nil || status != 201 {
		t.Fatal(status, e)
	}
}

// Refunds survive export -> import -> export byte for byte, and keep their limits afterwards.
func TestRefundExportImportRoundTrip(t *testing.T) {
	s, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	crMust(t, st, "ada", p, crIn(1, 800, crT0, "down"), hsAt(time.Second))
	r1 := rfMust(t, st, "bob", p.PaymentID, 500, hsAt(2*time.Second))
	crMust(t, st, "ada", p, crIn(2, 900, crT0, "up"), hsAt(3*time.Second))
	rq, _ := st.CreateRequest("u_cy", RequestIn{PayerHandle: "bob", Amount: 50, Note: "rq"}, hsAt(4*time.Second))
	rp, e := st.PayRequest("u_bob", rq.RequestID, PayIn{Visibility: visPrivate}, hsAt(5*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	r2 := rfMust(t, st, "cy", rp.PaymentID, 20, hsAt(6*time.Second))
	a := azAuthorize(t, st, "ada", "cy", 300, hsAt(7*time.Second))
	c := azMustCapture(t, st, "cy", a.AuthorizationID, azI64(100), false, hsAt(8*time.Second))
	r3 := rfMust(t, st, "cy", c.PaymentID, 100, hsAt(9*time.Second))
	out, e := trSettle(st, map[string]any{"transfers": []any{map[string]any{"from_handle": "ada", "to_handle": "cy", "amount": float64(60)}}}, hsAt(10*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	r4 := rfMust(t, st, "cy", out.(trSettlementOut).Payments[0].PaymentID, 60, hsAt(11*time.Second))

	raw, ae := s.Export()
	if ae != nil {
		t.Fatal(ae)
	}
	if !bytes.Contains(raw, []byte(`"refund_of":"`+p.PaymentID+`"`)) {
		t.Fatal("export carries refund_of")
	}
	s2 := fgStore()
	if ae := s2.importAt(raw, hsAt(time.Hour)); ae != nil {
		t.Fatal(ae)
	}
	raw2, ae := s2.Export()
	if ae != nil || !bytes.Equal(raw, raw2) {
		t.Fatal("export -> import -> export is not byte-identical")
	}
	st2 := s2.st
	for _, r := range []*Payment{r1, r2, r3, r4} {
		if got := st2.payByID[r.PaymentID]; got == nil || got.RefundOf == nil || *got.RefundOf != *r.RefundOf || !got.isRefund() {
			t.Fatalf("%s lost refund_of", r.PaymentID)
		}
	}
	if st2.refundedAmount(p.PaymentID) != 500 || st2.refundedAmount(rp.PaymentID) != 20 || st2.refundedAmount(c.PaymentID) != 100 {
		t.Fatal("refunded amounts did not survive the import")
	}
	_, e = rfRefund(st2, "bob", p.PaymentID, 401, hsAt(2*time.Hour))
	fgWantErr(t, "limit after import is the corrected 900", e, 422, "refund_exceeds_payment")
	rfMust(t, st2, "bob", p.PaymentID, 350, hsAt(2*time.Hour)) // all bob still holds: 900 - 500 - 50
	_, e = crCorrect(st2, "ada", p, crIn(3, 849, crT0, "below"), hsAt(3*time.Hour))
	fgWantErr(t, "correction below refunded after import", e, 422, "refund_exceeds_payment")
	_, e = rfRefund(st2, "ada", r1.PaymentID, 1, hsAt(3*time.Hour))
	fgWantErr(t, "refund of a refund after import", e, 422, "invalid_refund_target")
	if err := hsCheck(st2, 100000, hsAt(4*time.Hour)); err != nil {
		t.Fatal(err)
	}
}

// An export written before refunds existed has no refund_of: it imports, every payment is not a refund.
func TestRefundLegacyExportWithoutRefundOf(t *testing.T) {
	s, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	raw, ae := s.Export()
	if ae != nil {
		t.Fatal(ae)
	}
	legacy := bytes.ReplaceAll(raw, []byte(`"refund_of":null,`), nil)
	if bytes.Equal(legacy, raw) || bytes.Contains(legacy, []byte("refund_of")) {
		t.Fatal("test setup: refund_of not stripped")
	}
	s2 := fgStore()
	if ae := s2.importAt(legacy, hsAt(time.Hour)); ae != nil {
		t.Fatal(ae)
	}
	raw2, _ := s2.Export()
	if !bytes.Equal(raw2, raw) {
		t.Fatal("a legacy export re-exports with refund_of null")
	}
	rfMust(t, s2.st, "bob", p.PaymentID, 1000, hsAt(2*time.Hour))
}

// Concurrent refunds of one payment share one limit; the Store lock makes them a serial order.
func TestRefundRaceSharedLimit(t *testing.T) {
	s, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	const n = 64
	var wg sync.WaitGroup
	codes := make(chan string, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, e := s.Exec(func(st *State) (any, *AppError) {
				r, e := st.Refund("u_bob", p.PaymentID, RefundIn{Amount: 100}, time.Now())
				if e != nil {
					return nil, e
				}
				return r, nil
			})
			if e != nil {
				codes <- e.Code
				return
			}
			codes <- "ok"
		}()
	}
	wg.Wait()
	close(codes)
	tally := map[string]int{}
	for c := range codes {
		tally[c]++
	}
	if tally["ok"] != 10 || tally["refund_exceeds_payment"] != n-10 {
		t.Fatalf("exactly ten refunds of 100 fit in 1000: %v", tally)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if st.refundedAmount(p.PaymentID) != 1000 || crBalances(st) != "ada=100000 bob=0" {
		t.Fatal(crBalances(st))
	}
	if err := hsCheck(st, 100000, time.Now()); err != nil {
		t.Fatal(err)
	}
}

// Refunds racing corrections of the same payment never leave refunded above the payment's current amount.
func TestRefundRacesCorrections(t *testing.T) {
	s, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	var wg sync.WaitGroup
	for w := 0; w < 4; w++ {
		wg.Add(2)
		go func() {
			defer wg.Done()
			for i := 0; i < 60; i++ {
				s.Exec(func(st *State) (any, *AppError) {
					return st.Refund("u_bob", p.PaymentID, RefundIn{Amount: int64(1 + i%40)}, time.Now())
				})
			}
		}()
		go func(w int) {
			defer wg.Done()
			for i := 0; i < 60; i++ {
				s.Exec(func(st *State) (any, *AppError) {
					h := st.revByPay[p.PaymentID]
					return st.Correct("u_ada", p.PaymentID, crIn(h[len(h)-1].Revision, int64((i*37+w*11)%1500), crT0, "c"), time.Now())
				})
			}
		}(w)
	}
	wg.Wait()
	s.mu.Lock()
	defer s.mu.Unlock()
	h := st.revByPay[p.PaymentID]
	if got, limit := st.refundedAmount(p.PaymentID), h[len(h)-1].Amount; got > limit {
		t.Fatalf("refunded %d of a payment now worth %d", got, limit)
	}
	if err := hsCheck(st, 100000, time.Now()); err != nil {
		t.Fatal(err)
	}
	if len(h) < 2 || st.refundedAmount(p.PaymentID) == 0 {
		t.Fatalf("the race did nothing: %d revisions, %d refunded", len(h), st.refundedAmount(p.PaymentID))
	}
}

// U15 and the historical check with a refund in the history: correction debits use available funds
// (held funds do not count), and a refund already paid out does not hide a past overdraft.
func TestCorrectionDebitsAvailableAndRefundHistory(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	azAuthorize(t, st, "bob", "cy", 900, hsAt(time.Second))
	before := crSnapshot(st)
	_, e := crCorrect(st, "ada", p, crIn(1, 500, crT0, "debit 500"), hsAt(time.Minute))
	fgWantErr(t, "1000 total, 900 held, 500 debit", e, 409, "insufficient_funds")
	if crSnapshot(st) != before {
		t.Fatal("a refused correction changed the state")
	}
	crMust(t, st, "ada", p, crIn(1, 900, crT0, "debit exactly the available 100"), hsAt(time.Minute))

	_, st2 := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 1000}, fgU{"dee", 0})
	q := hsPay(t, st2, "ada", "bob", 1000, hsAt(0))
	hsPay(t, st2, "bob", "dee", 600, hsAt(time.Second))
	rfMust(t, st2, "bob", q.PaymentID, 400, hsAt(2*time.Second))
	hsPay(t, st2, "cy", "bob", 1000, hsAt(3*time.Second))
	before = crSnapshot(st2)
	_, e = crCorrect(st2, "ada", q, crIn(1, 400, crT0, "to refunded, effective at creation"), hsAt(time.Minute))
	fgWantErr(t, "bob would have been 200 short when paying dee", e, 409, "historical_overdraft")
	if crSnapshot(st2) != before {
		t.Fatal("a refused correction changed the state")
	}
	_, e = crCorrect(st2, "ada", q, crIn(1, 600, crT0, "enough for dee, not for the refund"), hsAt(time.Minute))
	fgWantErr(t, "bob would have been 400 short when refunding", e, 409, "historical_overdraft")
	if crSnapshot(st2) != before {
		t.Fatal("a refused correction changed the state")
	}
	crMust(t, st2, "ada", q, crIn(1, 1100, crT0, "up"), hsAt(time.Minute))
	if err := hsCheck(st2, 11000, hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
}
