package main

import (
	"bytes"
	"fmt"
	"math/rand"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func jRefund(e histEnv, who map[string]string, key, pid string, amount int) (int, []byte) {
	rec := do(e.h, "POST", "/payments/"+pid+"/refunds", `{"amount":`+strconv.Itoa(amount)+`}`, withKey(who, key))
	return rec.Code, rec.Body.Bytes()
}

// J1: the route accepts POST only, on exactly /payments/{id}/refunds; a stranger gets 403 even for a
// private payment; the refund keeps the private visibility and note.
func TestJuryRefundHTTPSurface(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id := p["payment_id"].(string)
	for _, m := range []string{"GET", "PUT", "PATCH", "DELETE"} {
		wantErr(t, m+" refunds", do(e.h, m, "/payments/"+id+"/refunds", `{"amount":1}`, withKey(e.bob, "k")), 404, "not_found")
	}
	for _, path := range []string{"/payments/" + id + "/refunds/x", "/payments//refunds", "/payments/" + id + "/refunds/", "/payments/" + id + "/Refunds"} {
		wantErr(t, "POST "+path, do(e.h, "POST", path, `{"amount":1}`, withKey(e.bob, "k")), 404, "not_found")
	}
	rec := do(e.h, "POST", "/payments", `{"to_handle":"bob","amount":50,"note":"secret","visibility":"private"}`, withKey(e.ada, "pay-priv"))
	pp := decode(t, rec.Body.Bytes())["payment_id"].(string)
	wantErr(t, "stranger on private", do(e.h, "POST", "/payments/"+pp+"/refunds", `{"amount":1}`, withKey(e.cy, "k9")), 403, "forbidden")
	code, raw := jRefund(e, e.bob, "k10", pp, 50)
	if code != 201 {
		t.Fatalf("%d %s", code, raw)
	}
	m := decode(t, raw)
	if m["visibility"] != "private" || m["note"] != "secret" || m["refund_of"] != pp || m["settlement_id"] != nil {
		t.Fatalf("%s", raw)
	}
	// every payment object in the feed carries refund_of; only refunds have a non-null one
	feed := decode(t, do(e.h, "GET", "/activity?limit=100", "", e.ada).Body.Bytes())
	for _, x := range feed["payments"].([]any) {
		pm := x.(map[string]any)
		v, has := pm["refund_of"]
		if !has {
			t.Fatalf("payment without refund_of: %v", pm)
		}
		if (v != nil) != (pm["payment_id"] == m["payment_id"]) {
			t.Fatalf("refund_of %v on %v", v, pm["payment_id"])
		}
	}
	// a refund payment is immutable: its sender is told so, anyone else is forbidden
	rid := m["payment_id"].(string)
	wantErr(t, "correct a refund (sender)", e.correct(e.bob, "c1", rid, correction(1, 10, m["created_at"].(string), "x")), 422, "linked_payment_immutable")
	wantErr(t, "correct a refund (original sender)", e.correct(e.ada, "c2", rid, correction(1, 10, m["created_at"].(string), "x")), 403, "forbidden")
	revs := e.revisions(t, e.bob, rid)
	if len(revs) != 1 {
		t.Fatalf("refund revisions %v", revs)
	}
}

// J2 (lost response): a retry of a refund after the limit was used up and the payment was corrected
// returns the stored 201 body as 200, byte for byte, and moves nothing.
func TestJuryRefundReplayIsStable(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	c1, raw1 := jRefund(e, e.bob, "K1", id, 400)
	c2, raw2 := jRefund(e, e.bob, "K2", id, 600)
	if c1 != 201 || c2 != 201 {
		t.Fatalf("%d %d", c1, c2)
	}
	if c, _ := jRefund(e, e.bob, "K3", id, 1); c != 422 {
		t.Fatalf("limit used up, got %d", c)
	}
	if rec := e.correct(e.ada, "cor-1", id, correction(1, 1500, created, "up")); rec.Code != 201 {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	adaB, bobB := e.balance(t, e.ada), e.balance(t, e.bob)
	for i := 0; i < 3; i++ {
		if c, b := jRefund(e, e.bob, "K1", id, 400); c != 200 || !bytes.Equal(b, raw1) {
			t.Fatalf("replay K1: %d %s", c, b)
		}
		if c, b := jRefund(e, e.bob, "K2", id, 600); c != 200 || !bytes.Equal(b, raw2) {
			t.Fatalf("replay K2: %d %s", c, b)
		}
	}
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != adaB || b != bobB {
		t.Fatalf("replays moved money: %v %v -> %v %v", adaB, bobB, a, b)
	}
	// now correct down to the refunded amount: still allowed, and a replay still returns 200
	if rec := e.correct(e.ada, "cor-2", id, correction(2, 1000, created, "down")); rec.Code != 201 {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	wantErr(t, "below refunded", e.correct(e.ada, "cor-3", id, correction(3, 999, created, "down")), 422, "refund_exceeds_payment")
	if c, b := jRefund(e, e.bob, "K1", id, 400); c != 200 || !bytes.Equal(b, raw1) {
		t.Fatalf("replay after corrections: %d %s", c, b)
	}
	wantErr(t, "same key, other amount", do(e.h, "POST", "/payments/"+id+"/refunds", `{"amount":401}`, withKey(e.bob, "K1")), 409, "idempotency_key_reuse")
}

// J3: concurrency over HTTP. 40 identical retries -> one 201; 30 distinct keys against a limit of 10 refunds.
func TestJuryRefundHTTPConcurrency(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id := p["payment_id"].(string)

	var wg sync.WaitGroup
	type res struct {
		code int
		body []byte
	}
	out := make([]res, 40)
	for i := range out {
		wg.Add(1)
		go func() {
			defer wg.Done()
			c, b := jRefund(e, e.bob, "same", id, 100)
			out[i] = res{c, b}
		}()
	}
	wg.Wait()
	n201, n200 := 0, 0
	var first []byte
	for _, r := range out {
		switch r.code {
		case 201:
			n201++
			first = r.body
		case 200:
			n200++
		default:
			t.Fatalf("%d %s", r.code, r.body)
		}
	}
	for _, r := range out {
		if !bytes.Equal(r.body, first) {
			t.Fatalf("bodies differ: %s vs %s", r.body, first)
		}
	}
	if n201 != 1 || n200 != 39 {
		t.Fatalf("201=%d 200=%d", n201, n200)
	}
	if b := e.balance(t, e.bob); b != 2500+1000-100 {
		t.Fatalf("bob %v", b)
	}

	codes := make([]int, 30)
	for i := range codes {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes[i], _ = jRefund(e, e.bob, fmt.Sprintf("d%d", i), id, 100)
		}()
	}
	wg.Wait()
	tally := map[int]int{}
	for _, c := range codes {
		tally[c]++
	}
	if tally[201] != 9 || tally[422] != 21 {
		t.Fatalf("limit 1000, 100 already refunded: %v", tally)
	}
	if a, b := e.balance(t, e.ada), e.balance(t, e.bob); a != 10000 || b != 2500 {
		t.Fatalf("ada %v bob %v", a, b)
	}
}

// J4: refunds and corrections of one payment race over HTTP; afterwards refunded <= current amount
// and the money is exactly accounted for.
func TestJuryRefundVsCorrectionHTTPRace(t *testing.T) {
	for round := 0; round < 3; round++ {
		e := newHistoryEnv(t)
		p := e.pay(t, e.ada, "pay-1", "bob", 1000)
		id, created := p["payment_id"].(string), p["created_at"].(string)
		var wg sync.WaitGroup
		var mu sync.Mutex
		var refunded int64
		for w := 0; w < 6; w++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for i := 0; i < 30; i++ {
					amt := 1 + (i*13+w*7)%80
					c, _ := jRefund(e, e.bob, fmt.Sprintf("r-%d-%d", w, i), id, amt)
					if c == 201 {
						mu.Lock()
						refunded += int64(amt)
						mu.Unlock()
					} else if c != 422 && c != 409 {
						t.Errorf("refund status %d", c)
					}
				}
			}()
		}
		for w := 0; w < 3; w++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for i := 0; i < 30; i++ {
					revs := e.revisions(t, e.ada, id)
					last := revs[len(revs)-1].(map[string]any)
					amt := (i*97 + w*31) % 1400
					rec := e.correct(e.ada, fmt.Sprintf("c-%d-%d", w, i), id, correction(int(last["revision"].(float64)), amt, created, "r"))
					if rec.Code != 201 && rec.Code != 409 && rec.Code != 422 {
						t.Errorf("correction status %d %s", rec.Code, rec.Body)
					}
				}
			}()
		}
		wg.Wait()
		revs := e.revisions(t, e.ada, id)
		latest := int64(revs[len(revs)-1].(map[string]any)["amount"].(float64))
		if refunded > latest {
			t.Fatalf("round %d: refunded %d of a payment now worth %d", round, refunded, latest)
		}
		if a, b := e.balance(t, e.ada), e.balance(t, e.bob); int64(a) != 10000-latest+refunded || int64(b) != 2500+latest-refunded {
			t.Fatalf("round %d: ada %v bob %v latest %d refunded %d", round, a, b, latest, refunded)
		}
		if len(revs) < 2 || refunded == 0 {
			t.Fatalf("round %d: race did nothing: %d revisions, %d refunded", round, len(revs), refunded)
		}
	}
}

// J5 (restart/round trip over HTTP): export from one server, import into a fresh one, twice.
// The stored refund keys replay as 200 with the same bytes; the limits survive.
func TestJuryRefundExportImportOverHTTP(t *testing.T) {
	a := newHistoryEnv(t)
	p := a.pay(t, a.ada, "pay-1", "bob", 1000)
	id, created := p["payment_id"].(string), p["created_at"].(string)
	c1, raw1 := jRefund(a, a.bob, "K1", id, 300)
	c2, raw2 := jRefund(a, a.bob, "K2", id, 200)
	if c1 != 201 || c2 != 201 {
		t.Fatal(c1, c2)
	}
	exp := do(a.h, "GET", "/_test/export", "", nil)
	if exp.Code != 200 {
		t.Fatalf("export %d", exp.Code)
	}
	cur := exp.Body.String()
	for hop := 1; hop <= 2; hop++ {
		b := histEnv{h: NewServer(NewStore())}
		if rec := do(b.h, "POST", "/_test/import", cur, nil); rec.Code != 204 {
			t.Fatalf("hop %d import: %d %s", hop, rec.Code, rec.Body)
		}
		b.ada, b.bob = loginAs(t, b.h, "ada@example.com"), loginAs(t, b.h, "bob@example.com")
		if c, body := jRefund(b, b.bob, "K1", id, 300); c != 200 || !bytes.Equal(body, raw1) {
			t.Fatalf("hop %d replay K1: %d %s", hop, c, body)
		}
		if c, body := jRefund(b, b.bob, "K2", id, 200); c != 200 || !bytes.Equal(body, raw2) {
			t.Fatalf("hop %d replay K2: %d %s", hop, c, body)
		}
		wantA, wantB := 9500.0, 3000.0
		if hop == 2 {
			wantA, wantB = 10000, 2500
		}
		if a, bb := b.balance(t, b.ada), b.balance(t, b.bob); a != wantA || bb != wantB {
			t.Fatalf("hop %d balances %v %v", hop, a, bb)
		}
		wantErr(t, "reuse after import", do(b.h, "POST", "/payments/"+id+"/refunds", `{"amount":301}`, withKey(b.bob, "K1")), 409, "idempotency_key_reuse")
		if c, _ := jRefund(b, b.bob, fmt.Sprintf("N%d", hop), id, 501); c != 422 {
			t.Fatalf("hop %d over the remainder: %d", hop, c)
		}
		wantErr(t, "below refunded after import", b.correct(b.ada, fmt.Sprintf("cb%d", hop), id, correction(1, 499, created, "d")), 422, "refund_exceeds_payment")
		rf := decode(t, raw1)["payment_id"].(string)
		wantErr(t, "refund of a refund after import", do(b.h, "POST", "/payments/"+rf+"/refunds", `{"amount":1}`, withKey(b.ada, fmt.Sprintf("rr%d", hop))), 422, "invalid_refund_target")
		if hop == 1 {
			if c, _ := jRefund(b, b.bob, "N-ok", id, 500); c != 201 {
				t.Fatalf("exact remainder after import: %d", c)
			}
			if c, _ := jRefund(b, b.bob, "N-over", id, 1); c != 422 {
				t.Fatalf("one over: %d", c)
			}
			cur = do(b.h, "GET", "/_test/export", "", nil).Body.String()
		} else {
			if c, _ := jRefund(b, b.bob, "N-ok2", id, 1); c != 422 {
				t.Fatalf("hop 2: remainder was used on hop 1, got %d", c)
			}
		}
	}
}

// J6: a statement snapshot token keeps paging its frozen entries after a refund; a new statement shows it.
func TestJuryRefundSnapshotTokenStaysFrozen(t *testing.T) {
	e := newHistoryEnv(t)
	p := e.pay(t, e.ada, "pay-1", "bob", 1000)
	id := p["payment_id"].(string)
	first := decode(t, do(e.h, "GET", "/statement?limit=50", "", e.bob).Body.Bytes())
	tok := first["snapshot"].(string)
	if len(first["entries"].([]any)) != 1 {
		t.Fatalf("%v", first)
	}
	if c, b := jRefund(e, e.bob, "K1", id, 250); c != 201 {
		t.Fatalf("%d %s", c, b)
	}
	frozen := decode(t, do(e.h, "GET", "/statement?snapshot="+tok+"&limit=50", "", e.bob).Body.Bytes())
	if len(frozen["entries"].([]any)) != 1 || frozen["closing_balance"] != first["closing_balance"] {
		t.Fatalf("snapshot moved: %v", frozen)
	}
	fresh := decode(t, do(e.h, "GET", "/statement?limit=50", "", e.bob).Body.Bytes())
	ents := fresh["entries"].([]any)
	if len(ents) != 2 || fresh["closing_balance"] != first["closing_balance"].(float64)-250 {
		t.Fatalf("fresh statement: %v", fresh)
	}
	last := ents[1].(map[string]any)
	if pm := last["payment"].(map[string]any); pm["refund_of"] != id || last["delta"] != -250.0 {
		t.Fatalf("%v", last)
	}
	if ents[0].(map[string]any)["payment"].(map[string]any)["refund_of"] != nil {
		t.Fatal("ordinary entry must carry refund_of null")
	}
}

// J7: a request payment stays correctable (stage 3) around refunds; the request never changes.
func TestJuryRequestPaymentCorrectionAroundRefunds(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	rq, e := st.CreateRequest("u_ada", RequestIn{PayerHandle: "bob", Amount: 500, Note: "rq"}, hsAt(0))
	if e != nil {
		t.Fatal(e)
	}
	hsPay(t, st, "ada", "bob", 2000, hsAt(time.Second))
	rp, e := st.PayRequest("u_bob", rq.RequestID, PayIn{Visibility: visPublic}, hsAt(2*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	rfMust(t, st, "ada", rp.PaymentID, 200, hsAt(3*time.Second))
	before := string(mustJSON(rq))
	effMid := FormatMicro(hsAt(2*time.Second + 500*time.Millisecond))
	_, e = crCorrect(st, "bob", rp, crIn(1, 199, effMid, "below"), hsAt(time.Minute))
	fgWantErr(t, "request payment sender is bob; below refunded", e, 422, "refund_exceeds_payment")
	r, e := crCorrect(st, "bob", rp, crIn(1, 200, effMid, "to refunded"), hsAt(time.Minute))
	if e != nil {
		t.Fatal(e)
	}
	if r.Revision != 2 || string(mustJSON(rq)) != before || rq.Status != statusPaid {
		t.Fatalf("%+v %s", r, mustJSON(rq))
	}
	_, e = rfRefund(st, "ada", rp.PaymentID, 1, hsAt(2*time.Minute))
	fgWantErr(t, "nothing left", e, 422, "refund_exceeds_payment")
	if err := hsCheck(st, 10000, hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
}

type jOutcome struct{ ok, err int }

// J8: independent oracle for Refund plus global invariants, over random mixed histories with holds,
// captures, settlements, corrections (stale, backdated, below refunded) and refunds. Every rejected
// operation must leave the serialised state untouched.
func TestJuryRefundFuzz(t *testing.T) {
	var refundOK, refundErr, corrOK, corrErr, capOK int
	codes := map[string]int{}
	for seed := int64(1); seed <= 30; seed++ {
		a, b, c, d, e := juryFuzz(t, seed, codes)
		refundOK += a
		refundErr += b
		corrOK += c
		corrErr += d
		capOK += e
	}
	t.Logf("refunds ok=%d rejected=%d; corrections ok=%d rejected=%d; captures ok=%d; codes=%v", refundOK, refundErr, corrOK, corrErr, capOK, codes)
	if refundOK < 100 || refundErr < 100 || corrOK < 100 || corrErr < 100 || capOK < 10 {
		t.Fatal("the fuzz did not reach the interesting states")
	}
	for _, code := range []string{"refund_exceeds_payment", "insufficient_funds", "invalid_refund_target", "forbidden", "not_found", "validation_failed", "stale_revision", "linked_payment_immutable", "historical_overdraft"} {
		if codes[code] == 0 {
			t.Errorf("fuzz never produced %s", code)
		}
	}
}

func juryFuzz(t *testing.T, seed int64, codes map[string]int) (rOK, rErr, cOK, cErr, capOK int) {
	t.Helper()
	rng := rand.New(rand.NewSource(seed))
	hs := []string{"ada", "bob", "cy"}
	_, st := azStore(fgU{"ada", 5000}, fgU{"bob", 3000}, fgU{"cy", 2000})
	const total = 10000
	var pays []*Payment
	var auths []*AuthorizationBody
	var off time.Duration
	for step := 0; step < 300; step++ {
		off += time.Duration(rng.Intn(3)) * time.Second
		at := hsAt(off)
		before := crSnapshot(st)
		fail := func(f string, a ...any) {
			t.Helper()
			t.Fatalf("seed %d step %d: %s", seed, step, fmt.Sprintf(f, a...))
		}
		unchangedOnError := func(what string) {
			if crSnapshot(st) != before {
				fail("%s was refused but changed the state", what)
			}
		}
		from := hs[rng.Intn(3)]
		to := hs[(rng.Intn(2)+1+indexOf(hs, from))%3]
		switch k := rng.Intn(20); {
		case k < 4: // pay
			p, e := st.Pay("u_"+from, PaymentIn{ToHandle: to, Amount: int64(1 + rng.Intn(1200)), Note: "n" + strconv.Itoa(step), Visibility: []string{visPublic, visPrivate}[rng.Intn(2)]}, at)
			if e != nil {
				unchangedOnError("pay")
			} else {
				pays = append(pays, p)
			}
		case k < 5: // request + pay it
			rq, e := st.CreateRequest("u_"+from, RequestIn{PayerHandle: to, Amount: int64(1 + rng.Intn(600)), Note: "rq"}, at)
			if e == nil {
				if p, e := st.PayRequest("u_"+to, rq.RequestID, PayIn{Visibility: visPublic}, at); e == nil {
					pays = append(pays, p)
				}
			}
		case k < 6: // settlement of two transfers
			out, e := trSettle(st, map[string]any{"transfers": []any{
				map[string]any{"from_handle": from, "to_handle": to, "amount": float64(1 + rng.Intn(300))},
				map[string]any{"from_handle": to, "to_handle": from, "amount": float64(1 + rng.Intn(100))},
			}}, at)
			if e != nil {
				unchangedOnError("settle")
			} else {
				pays = append(pays, out.(trSettlementOut).Payments...)
			}
		case k < 7: // authorize
			amt := int64(1 + rng.Intn(500))
			if st.Available(st.UserByHandle(from), st.ReadNow(at)) >= amt {
				auths = append(auths, azAuthorize(t, st, from, to, amt, at))
			}
		case k < 8: // capture or void
			if len(auths) > 0 {
				a := auths[rng.Intn(len(auths))]
				recv := a.ToHandle
				if rng.Intn(4) == 0 {
					st.Void("u_"+a.FromHandle, a.AuthorizationID, at)
				} else {
					amt := int64(1 + rng.Intn(300))
					if p, e := azCapture(st, recv, a.AuthorizationID, &amt, rng.Intn(2) == 0, at); e == nil {
						pays = append(pays, p)
						capOK++
					}
				}
			}
		case k < 14: // refund
			var pid string
			var target *Payment
			if len(pays) > 0 && rng.Intn(12) != 0 {
				target = pays[rng.Intn(len(pays))]
				pid = target.PaymentID
			} else {
				pid = "p_999"
			}
			caller := hs[rng.Intn(3)]
			if target != nil && rng.Intn(4) != 0 {
				caller = target.ToHandle // mostly the right caller
			}
			amt := int64(rng.Intn(500)) - 1
			if target != nil && rng.Intn(3) == 0 {
				h := st.revByPay[pid]
				amt = h[len(h)-1].Amount - jRefunded(st, pid) + int64(rng.Intn(3)) - 1 // around the exact limit
			}
			wantStatus, wantCode := juryRefundOracle(st, caller, pid, amt, at)
			bal0 := rfSum(st)
			r, e := st.Refund("u_"+caller, pid, RefundIn{Amount: amt}, at)
			switch {
			case wantStatus == 201 && e != nil:
				fail("refund %s by %s %d: oracle accepts, got %v", pid, caller, amt, e)
			case wantStatus != 201 && e == nil:
				fail("refund %s by %s %d: oracle says %d %s, got a payment", pid, caller, amt, wantStatus, wantCode)
			case e != nil && (e.Status != wantStatus || e.Code != wantCode):
				fail("refund %s by %s %d: oracle %d %s, got %d %s", pid, caller, amt, wantStatus, wantCode, e.Status, e.Code)
			}
			if e != nil {
				rErr++
				codes[e.Code]++
				unchangedOnError("refund")
			} else {
				rOK++
				pays = append(pays, r)
				juryCheckRefundPayment(fail, st, target, r, amt)
			}
			if rfSum(st) != bal0 {
				fail("money created or destroyed by a refund")
			}
		default: // correction
			var p *Payment
			if len(pays) == 0 {
				continue
			}
			p = pays[rng.Intn(len(pays))]
			who := p.FromHandle
			if rng.Intn(10) == 0 {
				who = hs[rng.Intn(3)]
			}
			h := st.revByPay[p.PaymentID]
			rev := h[len(h)-1].Revision
			if rng.Intn(8) == 0 {
				rev++
			}
			refunded := jRefunded(st, p.PaymentID)
			var amt int64
			switch rng.Intn(4) {
			case 0:
				amt = refunded
			case 1:
				amt = refunded - 1
				if amt < 0 {
					amt = 0
				}
			default:
				amt = int64(rng.Intn(1500))
			}
			eff := FormatMicro(hsAt(time.Duration(rng.Intn(int(off/time.Second)+1)) * time.Second))
			rv, e := st.Correct("u_"+who, p.PaymentID, crIn(rev, amt, eff, "fz"), at)
			linked := p.SettlementID != nil || p.AuthorizationID != nil || p.isRefund()
			if e == nil {
				cOK++
				if linked {
					fail("linked payment %s was corrected", p.PaymentID)
				}
				if rv.Amount < refunded {
					fail("correction of %s to %d is below refunded %d", p.PaymentID, rv.Amount, refunded)
				}
			} else {
				cErr++
				codes[e.Code]++
				unchangedOnError("correction")
				if who == p.FromHandle && !linked && rev == h[len(h)-1].Revision && amt < refunded && e.Code != "refund_exceeds_payment" {
					fail("amount %d below refunded %d on %s gave %s", amt, refunded, p.PaymentID, e.Code)
				}
				if linked && who == p.FromHandle && e.Code != "linked_payment_immutable" {
					fail("linked payment %s gave %s", p.PaymentID, e.Code)
				}
			}
		}
		if err := hsCheck(st, total, at); err != nil {
			fail("%v", err)
		}
		for _, p := range st.Payments {
			if p.isRefund() {
				if o := st.payByID[*p.RefundOf]; o == nil || o.isRefund() {
					fail("refund %s points at %v", p.PaymentID, o)
				}
				continue
			}
			h := st.revByPay[p.PaymentID]
			if got := jRefunded(st, p.PaymentID); got > h[len(h)-1].Amount {
				fail("%s refunded %d above its current amount %d", p.PaymentID, got, h[len(h)-1].Amount)
			}
		}
	}
	return
}

func indexOf(hs []string, h string) int {
	for i, x := range hs {
		if x == h {
			return i
		}
	}
	return -1
}

func jRefunded(st *State, pid string) (sum int64) {
	for _, p := range st.Payments {
		if p.RefundOf != nil && *p.RefundOf == pid {
			sum += p.Amount
		}
	}
	return
}

// juryRefundOracle restates the spec's refund rules without the implementation's code.
func juryRefundOracle(st *State, caller, pid string, amt int64, at time.Time) (int, string) {
	if amt < 1 || amt > 1_000_000_000 {
		return 422, "validation_failed"
	}
	p := st.payByID[pid]
	if p == nil {
		return 404, "not_found"
	}
	if p.ToHandle != caller && p.ToUserID != "u_"+caller {
		return 403, "forbidden"
	}
	if p.RefundOf != nil {
		return 422, "invalid_refund_target"
	}
	h := st.revByPay[pid]
	if amt > h[len(h)-1].Amount-jRefunded(st, pid) {
		return 422, "refund_exceeds_payment"
	}
	if st.Available(st.UserByHandle(caller), st.ReadNow(at)) < amt {
		return 409, "insufficient_funds"
	}
	return 201, ""
}

func juryCheckRefundPayment(fail func(string, ...any), st *State, target, r *Payment, amt int64) {
	switch {
	case r.Amount != amt || r.FromUserID != target.ToUserID || r.ToUserID != target.FromUserID,
		r.FromHandle != target.ToHandle || r.ToHandle != target.FromHandle,
		r.Note != target.Note || r.Visibility != target.Visibility,
		r.RequestID != nil || r.AuthorizationID != nil || r.SettlementID != nil,
		r.RefundOf == nil || *r.RefundOf != target.PaymentID,
		len(st.revByPay[r.PaymentID]) != 1 || st.revByPay[r.PaymentID][0].Revision != 1:
		fail("refund payment fields wrong: %+v of %+v", r, target)
	}
	if !r.created.After(target.created) {
		fail("refund created %s not after target %s", r.CreatedAt, target.CreatedAt)
	}
	for _, rv := range st.revByPay[target.PaymentID] {
		if !r.created.After(rv.rec) {
			fail("refund created %s not after the target's revision recorded %s", r.CreatedAt, rv.RecordedAt)
		}
	}
	_ = strings.TrimSpace
}
