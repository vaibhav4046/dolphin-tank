package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"
)

func crIn(rev, amount int64, eff, reason string) CorrectionIn {
	return CorrectionIn{ExpectedRevision: rev, Amount: amount, EffectiveAt: eff, Reason: reason}
}

const crT0 = "2026-09-24T13:10:00+00:00"

func crCorrect(st *State, who string, p *Payment, in CorrectionIn, now time.Time) (*Revision, *AppError) {
	return st.Correct("u_"+who, p.PaymentID, in, now)
}

func crMust(t *testing.T, st *State, who string, p *Payment, in CorrectionIn, now time.Time) *Revision {
	t.Helper()
	r, e := crCorrect(st, who, p, in, now)
	if e != nil {
		t.Fatalf("correct %s: %v", p.PaymentID, e)
	}
	return r
}

func crSnapshot(st *State) string { return string(mustJSON(st)) }

func crBalances(st *State) string {
	var out []string
	for _, u := range st.Users {
		out = append(out, fmt.Sprintf("%s=%d", u.Handle, u.Balance))
	}
	return strings.Join(out, " ")
}

func TestCorrectDirectionsZeroAndOriginalUntouched(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	r := crMust(t, st, "ada", p, crIn(1, 1500, crT0, "raise"), hsAt(time.Minute))
	if r.PaymentID != p.PaymentID || r.Revision != 2 || r.Amount != 1500 || r.EffectiveAt != crT0 || r.Reason != "raise" ||
		r.RecordedAt != "2026-09-24T13:11:00.000000+00:00" {
		t.Fatalf("%+v", r)
	}
	if crBalances(st) != "ada=8500 bob=1500 cy=0" {
		t.Fatal("an increase debits the sender:", crBalances(st))
	}
	crMust(t, st, "ada", p, crIn(2, 400, crT0, "lower"), hsAt(2*time.Minute))
	if crBalances(st) != "ada=9600 bob=400 cy=0" {
		t.Fatal("a decrease debits the receiver:", crBalances(st))
	}
	crMust(t, st, "ada", p, crIn(3, 0, crT0, "reverse"), hsAt(3*time.Minute))
	if crBalances(st) != "ada=10000 bob=0 cy=0" {
		t.Fatal("zero reverses the whole payment:", crBalances(st))
	}
	crMust(t, st, "ada", p, crIn(4, 1000, crT0, "restore"), hsAt(4*time.Minute))
	if crBalances(st) != "ada=9000 bob=1000 cy=0" {
		t.Fatal(crBalances(st))
	}
	// the original payment, the feed and the request/split records are untouched; revisions are not payments
	if p.Amount != 1000 || len(st.Payments) != 1 || len(st.Requests) != 0 {
		t.Fatalf("%+v", p)
	}
	feed := st.Activity("u_cy", 50, 0).(paymentPage)
	if len(feed.Payments) != 1 || feed.Payments[0].Amount != 1000 || feed.Payments[0].CreatedAt != p.CreatedAt {
		t.Fatalf("the feed shows the original payment: %+v", feed.Payments)
	}
	revs := st.revByPay[p.PaymentID]
	if len(revs) != 5 || revs[0].Amount != 1000 || revs[0].Reason != "" || revs[0].EffectiveAt != revs[0].RecordedAt || revs[0].EffectiveAt != p.CreatedAt {
		t.Fatalf("%d revisions, first %+v", len(revs), revs[0])
	}
	if got := string(mustJSON(r)); got != `{"payment_id":"p_1","revision":2,"amount":1500,"effective_at":"`+crT0+`","recorded_at":"2026-09-24T13:11:00.000000+00:00","reason":"raise"}` {
		t.Fatal(got)
	}
	// a change of effective time alone, or the same amount, is a valid correction
	crMust(t, st, "ada", p, crIn(5, 1000, "2026-09-24T13:09:00+00:00", "earlier"), hsAt(5*time.Minute))
	if crBalances(st) != "ada=9000 bob=1000 cy=0" {
		t.Fatal(crBalances(st))
	}
}

func TestCorrectErrorPrecedence(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	linked := hsPay(t, st, "ada", "cy", 10, hsAt(time.Second))
	sid := "st_1"
	linked.SettlementID = &sid
	capt := hsPay(t, st, "ada", "cy", 10, hsAt(2*time.Second))
	aid := "a_1"
	capt.AuthorizationID = &aid
	now := hsAt(time.Minute)
	before := crSnapshot(st)

	cases := []struct {
		name   string
		who    string
		pid    string
		in     CorrectionIn
		status int
		code   string
	}{
		{"naive effective_at beats unknown payment", "cy", "p_999", crIn(1, 5, "2026-09-24T13:10:00", "x"), 422, "validation_failed"},
		{"future effective_at", "ada", p.PaymentID, crIn(1, 5, "2026-09-24T13:11:01+00:00", "x"), 422, "validation_failed"},
		{"empty effective_at", "ada", p.PaymentID, crIn(1, 5, "", "x"), 422, "validation_failed"},
		{"empty reason", "ada", p.PaymentID, crIn(1, 5, crT0, ""), 422, "validation_failed"},
		{"reason over 200", "ada", p.PaymentID, crIn(1, 5, crT0, strings.Repeat("x", 201)), 422, "validation_failed"},
		{"amount over a billion", "ada", p.PaymentID, crIn(1, 1_000_000_001, crT0, "x"), 422, "validation_failed"},
		{"negative amount", "ada", p.PaymentID, crIn(1, -1, crT0, "x"), 422, "validation_failed"},
		{"revision zero", "ada", p.PaymentID, crIn(0, 5, crT0, "x"), 422, "validation_failed"},
		{"unknown payment", "ada", "p_999", crIn(1, 5, crT0, "x"), 404, "not_found"},
		{"unknown payment beats not sender", "cy", "p_999", crIn(1, 5, crT0, "x"), 404, "not_found"},
		{"receiver", "bob", p.PaymentID, crIn(1, 5, crT0, "x"), 403, "forbidden"},
		{"stranger", "cy", p.PaymentID, crIn(1, 5, crT0, "x"), 403, "forbidden"},
		{"forbidden beats linked", "cy", linked.PaymentID, crIn(1, 5, crT0, "x"), 403, "forbidden"},
		{"settlement member", "ada", linked.PaymentID, crIn(1, 5, crT0, "x"), 422, "linked_payment_immutable"},
		{"settlement member beats stale", "ada", linked.PaymentID, crIn(9, 5, crT0, "x"), 422, "linked_payment_immutable"},
		{"capture", "ada", capt.PaymentID, crIn(1, 5, crT0, "x"), 422, "linked_payment_immutable"},
		{"stale", "ada", p.PaymentID, crIn(2, 5, crT0, "x"), 409, "stale_revision"},
		{"stale beats insufficient funds", "ada", p.PaymentID, crIn(2, 1_000_000_000, crT0, "x"), 409, "stale_revision"},
		{"insufficient funds", "ada", p.PaymentID, crIn(1, 1_000_000_000, crT0, "x"), 409, "insufficient_funds"},
	}
	for _, c := range cases {
		r, e := st.Correct("u_"+c.who, c.pid, c.in, now)
		if r != nil {
			t.Errorf("%s: revision with an error", c.name)
		}
		fgWantErr(t, c.name, e, c.status, c.code)
	}
	if crSnapshot(st) != before {
		t.Fatal("refused corrections changed the state")
	}
	if _, e := st.Correct("u_nobody", p.PaymentID, crIn(1, 5, crT0, "x"), now); e == nil || e.Status != 401 {
		t.Fatal(e)
	}
}

func TestCorrectHistoricalOverdraftAndFunds(t *testing.T) {
	// bob is paid 1000 at +0, pays cy 800 at +10 s and is paid 800 back at +20 s
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	p1 := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	p2 := hsPay(t, st, "bob", "cy", 800, hsAt(10*time.Second))
	hsPay(t, st, "cy", "bob", 800, hsAt(20*time.Second))
	now := hsAt(time.Minute)
	before := crSnapshot(st)

	_, e := crCorrect(st, "ada", p1, crIn(1, 0, crT0, "back-dated reversal"), now)
	fgWantErr(t, "bob would be negative at +10 s", e, 409, "historical_overdraft")
	_, e = crCorrect(st, "ada", p1, crIn(1, 200, crT0, "back-dated cut"), now)
	fgWantErr(t, "800 spent against a corrected 200", e, 409, "historical_overdraft")
	// a later effective time moves the whole payment later, which also leaves bob short at +10 s
	_, e = crCorrect(st, "ada", p1, crIn(1, 2000, "2026-09-24T13:10:15+00:00", "later"), now)
	fgWantErr(t, "effective later than the spending", e, 409, "historical_overdraft")
	if crSnapshot(st) != before {
		t.Fatal("a refused correction left a trace")
	}
	// the refused correction left the key free; a harmless one succeeds
	crMust(t, st, "ada", p1, crIn(1, 800, crT0, "ok"), now)

	// current funds are judged first: cy now holds 0 after paying back, bob cannot fund a big decrease
	_, st2 := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	q1 := hsPay(t, st2, "ada", "bob", 1000, hsAt(0))
	hsPay(t, st2, "bob", "cy", 800, hsAt(10*time.Second))
	_, e = crCorrect(st2, "ada", q1, crIn(1, 0, crT0, "reverse"), now)
	fgWantErr(t, "insufficient funds also negative in the past: funds win", e, 409, "insufficient_funds")
	_, e = crCorrect(st2, "ada", q1, crIn(1, 1_000_000_000, crT0, "raise"), now)
	fgWantErr(t, "sender cannot fund an increase", e, 409, "insufficient_funds")
	_ = p2
}

func TestCorrectCombinedInstantAndHoldBoundary(t *testing.T) {
	// two movements at one instant net to a nonnegative wallet, whatever order their ids sort in
	st := hsState(t, []fgU{{"ada", 5000}, {"bob", 500}, {"cy", 1000}},
		hsSeed{"p_1", "bob", "cy", 1000, crT0}, // bob pays first by id, but is paid at the same instant
		hsSeed{"p_2", "ada", "bob", 1000, crT0},
		hsSeed{"p_3", "cy", "bob", 500, "2026-09-24T13:10:10+00:00"}) // so bob can fund a later decrease
	if _, e := st.Correct("u_ada", "p_2", crIn(1, 1000, crT0, "no-op at the same instant"), hsAt(time.Minute)); e != nil {
		t.Fatalf("combined movements at one instant must be judged together: %v", e)
	}
	if _, e := st.Correct("u_ada", "p_2", crIn(2, 900, crT0, "lower"), hsAt(2*time.Minute)); e == nil || e.Code != "historical_overdraft" {
		t.Fatalf("100 short after the instant's movements: %v", e)
	}

	// a hold makes available negative at a past boundary although the total never is
	run := func(withHold bool) *AppError {
		_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
		p := hsPay(t, st, "ada", "bob", 3000, hsAt(0))
		if withHold {
			a := azAuthorize(t, st, "bob", "cy", 3000, hsAt(10*time.Second))
			if _, e := st.Void("u_bob", a.AuthorizationID, hsAt(20*time.Second)); e != nil {
				t.Fatal(e)
			}
		}
		_, e := crCorrect(st, "ada", p, crIn(1, 0, crT0, "reverse"), hsAt(time.Minute))
		return e
	}
	if e := run(false); e != nil {
		t.Fatalf("without the hold the reversal is fine: %v", e)
	}
	if e := run(true); e == nil || e.Code != "historical_overdraft" {
		t.Fatalf("bob reserved 3000 at +10 s, which the corrected history never gave him: %v", e)
	}

	// moving a payment across a hold boundary: the hold fits the old history and the new one
	_, st3 := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p := hsPay(t, st3, "ada", "bob", 1000, hsAt(0))
	a := azAuthorize(t, st3, "ada", "bob", 8000, hsAt(10*time.Second))
	if _, e := crCorrect(st3, "ada", p, crIn(1, 2000, crT0, "up"), hsAt(time.Minute)); e != nil { // 8000 held, 1000 available, +1000
		t.Fatalf("exactly enough: %v", e)
	}
	if _, e := crCorrect(st3, "ada", p, crIn(2, 2001, crT0, "up"), hsAt(2*time.Minute)); e == nil || e.Code != "insufficient_funds" {
		t.Fatalf("one over the available amount: %v", e)
	}
	if _, e := st3.Void("u_ada", a.AuthorizationID, hsAt(3*time.Minute)); e != nil {
		t.Fatal(e)
	}
	if _, e := crCorrect(st3, "ada", p, crIn(2, 2600, crT0, "up"), hsAt(4*time.Minute)); e == nil || e.Code != "historical_overdraft" {
		t.Fatalf("7400 left at +0 s cannot cover the 8000 hold placed at +10 s: %v", e)
	}
	if _, e := crCorrect(st3, "ada", p, crIn(2, 2000, crT0, "same"), hsAt(5*time.Minute)); e != nil {
		t.Fatal(e)
	}
}

// A hold's created_at is the microsecond it was placed: money received earlier in the same second is
// there when the hold exists, and a correction is judged against that one instant.
func TestCorrectSameSecondPaymentThenHold(t *testing.T) {
	setup := func() (*State, *Payment, *AuthorizationBody) {
		_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
		p := hsPay(t, st, "ada", "bob", 3000, hsAt(500*time.Millisecond))
		a := azAuthorize(t, st, "bob", "cy", 3000, hsAt(700*time.Millisecond))
		if a.CreatedAt != "2026-09-24T13:10:00.700000+00:00" || p.CreatedAt != "2026-09-24T13:10:00.500000+00:00" {
			t.Fatal(a.CreatedAt, p.CreatedAt)
		}
		return st, p, a
	}
	st, p, a := setup()
	if got := st.HeldAt("u_bob", hsAt(0), hsAt(time.Hour)); got != 0 {
		t.Fatalf("the hold does not exist at :00.0: %d", got)
	}
	if got := st.HeldAt("u_bob", hsAt(700*time.Millisecond), hsAt(time.Hour)); got != 3000 {
		t.Fatalf("as_of = created_at counts the hold: %d", got)
	}
	if _, e := crCorrect(st, "ada", p, crIn(1, 3500, p.CreatedAt, "up"), hsAt(time.Minute)); e != nil {
		t.Fatalf("bob held 3000 only after receiving it: %v", e)
	}
	if _, e := crCorrect(st, "ada", p, crIn(2, 3000, p.CreatedAt, "down"), hsAt(2*time.Minute)); e != nil {
		t.Fatalf("3000 received covers the 3000 held, down to the last unit: %v", e)
	}
	if _, e := crCorrect(st, "ada", p, crIn(3, 2999, p.CreatedAt, "one too few"), hsAt(3*time.Minute)); e == nil || e.Code != "insufficient_funds" {
		t.Fatalf("%v", e)
	}
	// but a correction that takes the money away from the moment the hold was placed is refused
	st, p, a = setup()
	if _, e := st.Void("u_bob", a.AuthorizationID, hsAt(900*time.Millisecond)); e != nil {
		t.Fatal(e)
	}
	if _, e := crCorrect(st, "ada", p, crIn(1, 0, p.CreatedAt, "reverse"), hsAt(time.Minute)); e == nil || e.Code != "historical_overdraft" {
		t.Fatalf("the hold was placed at +0.7 s when bob would hold nothing: %v", e)
	}
	// the instant survives an export; created_exact (vestigial) is neither needed nor consulted
	raw, _ := json.Marshal(st)
	var back State
	if err := json.Unmarshal(raw, &back); err != nil || back.ReindexAt(hsAt(time.Hour)) != nil {
		t.Fatal(err)
	}
	if got := back.Authorizations[0].placedAt(); !got.Equal(hsAt(700 * time.Millisecond)) {
		t.Fatal(got)
	}
	back.Authorizations[0].CreatedExact = nil
	if err := back.ReindexAt(hsAt(time.Hour)); err != nil || !back.Authorizations[0].placedAt().Equal(hsAt(700*time.Millisecond)) {
		t.Fatal(err)
	}
	// an export of the rejected 3c7c411 build: whole-second created_at plus created_exact. Import places the
	// hold at created_exact, the microsecond it was placed, and rewrites created_at to match.
	back.Authorizations[0].CreatedAt = FormatTime(hsAt(0))
	exact := FormatMicro(hsAt(700 * time.Millisecond))
	back.Authorizations[0].CreatedExact = &exact
	if err := back.ReindexAt(hsAt(time.Hour)); err != nil || !back.Authorizations[0].placedAt().Equal(hsAt(700*time.Millisecond)) ||
		back.Authorizations[0].CreatedAt != exact {
		t.Fatalf("legacy created_exact export: %v placed at %s created_at %s", err, back.Authorizations[0].placedAt(), back.Authorizations[0].CreatedAt)
	}
}

func TestCorrectBackToBackRecordedTimesRise(t *testing.T) {
	_, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	now := hsAt(time.Minute) // one frozen clock tick for all of them
	prev := hsInstant(t, p.CreatedAt)
	for i := 1; i <= 50; i++ {
		r := crMust(t, st, "ada", p, crIn(int64(i), int64(1000+i), crT0, fmt.Sprintf("n%d", i)), now)
		rec := hsInstant(t, r.RecordedAt)
		if !rec.After(prev) || r.Revision != int64(i+1) {
			t.Fatalf("revision %d recorded %s after %s", r.Revision, r.RecordedAt, prev)
		}
		prev = rec
	}
	if crBalances(st) != "ada=98950 bob=1050" {
		t.Fatal(crBalances(st))
	}
	back := &State{}
	raw, _ := json.Marshal(st)
	if err := json.Unmarshal(raw, back); err != nil || back.ReindexAt(now) != nil {
		t.Fatal("history must reindex:", err)
	}
}

func TestCorrectBoundaryAmountsAndReasons(t *testing.T) {
	_, st := azStore(fgU{"ada", 3_000_000_000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	crMust(t, st, "ada", p, crIn(1, 1_000_000_000, crT0, "max"), hsAt(time.Minute))
	if st.UserByHandle("bob").Balance != 1_000_000_000 {
		t.Fatal(crBalances(st))
	}
	crMust(t, st, "ada", p, crIn(2, 0, crT0, "zero"), hsAt(2*time.Minute))
	long := strings.Repeat("日", 200)
	r := crMust(t, st, "ada", p, crIn(3, 7, crT0, long), hsAt(3*time.Minute))
	if r.Reason != long || len(r.Reason) != 600 {
		t.Fatal("a 200-character reason of multi-byte characters is stored verbatim")
	}
	if _, e := crCorrect(st, "ada", p, crIn(4, 7, crT0, long+"日"), hsAt(4*time.Minute)); e == nil || e.Code != "validation_failed" {
		t.Fatal(e)
	}
	if _, e := crCorrect(st, "ada", p, crIn(4, 1_000_000_001, crT0, "x"), hsAt(4*time.Minute)); e == nil || e.Code != "validation_failed" {
		t.Fatal(e)
	}
	// a client instant is stored and echoed exactly as written, with its offset
	r = crMust(t, st, "ada", p, crIn(4, 9, "2026-09-24T15:09:00.5+02:00", "offset"), hsAt(5*time.Minute))
	if r.EffectiveAt != "2026-09-24T15:09:00.5+02:00" || st.revByPay[p.PaymentID][4].EffectiveAt != r.EffectiveAt {
		t.Fatal(r.EffectiveAt)
	}
}

func TestCorrectRaceSameExpectedRevision(t *testing.T) {
	s, st := azStore(fgU{"ada", 100000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	const n = 100
	var wg sync.WaitGroup
	codes := make(chan string, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			status, _, e := s.Idempotent("u_ada", "POST", "/payments/"+p.PaymentID+"/corrections", fmt.Sprintf("key-%d", i),
				map[string]any{"expected_revision": 1, "amount": 2000 + i}, func(st *State) (any, *AppError) {
					r, e := st.Correct("u_ada", p.PaymentID, crIn(1, int64(2000+i), crT0, "race"), time.Now())
					if e != nil {
						return nil, e
					}
					return r, nil
				})
			if e != nil {
				codes <- e.Code
				return
			}
			codes <- fmt.Sprint(status)
		}(i)
	}
	wg.Wait()
	close(codes)
	tally := map[string]int{}
	for c := range codes {
		tally[c]++
	}
	if tally["201"] != 1 || tally["stale_revision"] != n-1 {
		t.Fatalf("exactly one correction may win: %v", tally)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(st.revByPay[p.PaymentID]) != 2 || st.UserByHandle("ada").Balance+st.UserByHandle("bob").Balance != 100000 {
		t.Fatal("history or balances damaged by the race")
	}
}

// Corrections, payments, holds, captures and voids from many goroutines behave like some serial order.
func TestCorrectConcurrentWithEverythingElse(t *testing.T) {
	s, st := azStore(fgU{"ada", 200000}, fgU{"bob", 200000}, fgU{"cy", 200000})
	const total = 600000
	seed := []*Payment{hsPay(t, st, "ada", "bob", 5000, hsAt(0)), hsPay(t, st, "bob", "cy", 5000, hsAt(time.Second)), hsPay(t, st, "cy", "ada", 5000, hsAt(2*time.Second))}
	stop := make(chan struct{})
	var wg sync.WaitGroup
	worker := func(f func(i int)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; ; i++ {
				select {
				case <-stop:
					return
				default:
					f(i)
				}
			}
		}()
	}
	handles := []string{"ada", "bob", "cy"}
	for w := 0; w < 3; w++ {
		w := w
		worker(func(i int) { // corrections of one's own seeded payment
			s.Exec(func(st *State) (any, *AppError) {
				p := seed[w]
				h := st.revByPay[p.PaymentID]
				return st.Correct(p.FromUserID, p.PaymentID, crIn(h[len(h)-1].Revision, int64(1000+i%7000), p.CreatedAt, "c"), time.Now())
			})
		})
		worker(func(i int) {
			s.Exec(func(st *State) (any, *AppError) {
				return st.Pay("u_"+handles[w], PaymentIn{ToHandle: handles[(w+1)%3], Amount: int64(1 + i%500), Visibility: visPublic}, time.Now())
			})
		})
		worker(func(i int) {
			s.Exec(func(st *State) (any, *AppError) {
				a, e := st.Authorize("u_"+handles[w], AuthorizeIn{ToHandle: handles[(w+2)%3], Amount: int64(1 + i%300), Visibility: visPublic}, time.Now())
				if e != nil {
					return nil, e
				}
				amt := int64(1)
				if i%2 == 0 {
					st.Capture("u_"+handles[(w+2)%3], a.AuthorizationID, CaptureIn{Amount: &amt, Final: i%4 == 0}, time.Now())
				} else {
					st.Void("u_"+handles[w], a.AuthorizationID, time.Now())
				}
				return a, nil
			})
		})
	}
	var checkErr error
	worker(func(i int) {
		s.mu.Lock()
		defer s.mu.Unlock()
		if checkErr == nil {
			checkErr = hsCheck(st, total, time.Now())
		}
	})
	time.Sleep(700 * time.Millisecond)
	close(stop)
	wg.Wait()
	if checkErr != nil {
		t.Fatal(checkErr)
	}
	if err := hsCheck(st, total, time.Now()); err != nil {
		t.Fatal(err)
	}
	if len(st.Payments) < 10 || len(st.Revisions) <= len(st.Payments) {
		t.Fatalf("the storm did nothing: %d payments, %d revisions", len(st.Payments), len(st.Revisions))
	}
}
