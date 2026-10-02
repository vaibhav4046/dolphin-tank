package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func txNumber(n int64) json.Number { return json.Number(strconv.FormatInt(n, 10)) }

// txAuthorize / txCapture run the new write paths exactly like the handlers do:
// through Store.Idempotent, with the domain call inside the critical section.
func txAuthorize(s *Store, uid, key, to string, amount int64, now time.Time) (int, []byte, *AppError) {
	body := map[string]any{"to_handle": to, "amount": txNumber(amount)}
	return s.Idempotent(uid, "POST", "/authorizations", key, body, func(st *State) (any, *AppError) {
		return st.Authorize(uid, AuthorizeIn{ToHandle: to, Amount: amount, Visibility: visPublic}, now)
	})
}

func txCapture(s *Store, uid, authID, key string, amount *int64, final bool, now time.Time) (int, []byte, *AppError) {
	body := map[string]any{}
	if amount != nil {
		body["amount"] = txNumber(*amount)
	}
	if !final {
		body["final"] = false
	}
	return s.Idempotent(uid, "POST", "/authorizations/"+authID+"/capture", key, body, func(st *State) (any, *AppError) {
		return st.Capture(uid, authID, CaptureIn{Amount: amount, Final: final}, now)
	})
}

func txPay(s *Store, uid, key, to string, amount int64) (int, []byte, *AppError) {
	body := map[string]any{"to_handle": to, "amount": txNumber(amount)}
	return s.Idempotent(uid, "POST", "/payments", key, body, func(st *State) (any, *AppError) {
		return st.Pay(uid, PaymentIn{ToHandle: to, Amount: amount, Visibility: visPublic}, time.Now())
	})
}

func txVoid(s *Store, uid, authID string, now time.Time) (int, []byte, *AppError) {
	b, e := s.Exec(func(st *State) (any, *AppError) { return st.Void(uid, authID, now) })
	if e != nil {
		return 0, nil, e
	}
	return 200, b, nil
}

// txInvariants checks, under the lock, the properties that must hold at every read:
// balances non-negative and summing to the seeded total, Held <= Balance, available >= 0.
func txInvariants(s *Store, seeded int64, now time.Time) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	var sum int64
	for _, u := range s.st.Users {
		held := s.st.Held(u.ID, now)
		switch {
		case u.Balance < 0:
			return fmt.Sprintf("%s balance %d is negative", u.ID, u.Balance)
		case held > u.Balance:
			return fmt.Sprintf("%s held %d exceeds balance %d", u.ID, held, u.Balance)
		case s.st.Available(u, now) < 0:
			return fmt.Sprintf("%s available is negative", u.ID)
		}
		sum += u.Balance
	}
	if sum != seeded {
		return fmt.Sprintf("balances sum to %d, want %d", sum, seeded)
	}
	return ""
}

func TestSettlementIsHeldAware(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_1", "open", 800, txFuture, ""))))
	settle := func(key string, legs ...string) (int, []byte, *AppError) {
		return s.Settle("u_ada", key, ttBody(t, ttTransfers(legs...)))
	}
	snap := func() []byte { return ttExport(t, s) }

	before := snap()
	if _, _, e := settle("k", ttLeg("ada", "cy", 300)); ttCode(e) != "insufficient_funds" || e.Status != 409 {
		t.Fatalf("a net debit into the held funds must be 409 insufficient_funds, got %v", e)
	}
	if string(before) != string(snap()) {
		t.Fatal("a refused settlement left a trace (state or claimed key)")
	}
	// The failed key is reusable with a body that fits.
	if st, _, e := settle("k", ttLeg("ada", "cy", 200)); e != nil || st != 201 {
		t.Fatalf("key reuse after refusal: %d %v", st, e)
	}
	// ada: 800 balance, 800 held. A batch that nets her to zero passes; so does a net credit.
	if st, body, e := settle("k2", ttLeg("bob", "ada", 400), ttLeg("ada", "cy", 400)); e != nil || st != 201 {
		t.Fatalf("net-zero batch for ada: %d %v", st, e)
	} else {
		var out struct {
			Payments []map[string]any `json:"payments"`
		}
		if err := json.Unmarshal(body, &out); err != nil || len(out.Payments) != 2 {
			t.Fatalf("settlement body %s", body)
		}
		for _, p := range out.Payments {
			if v, ok := p["authorization_id"]; !ok || v != nil {
				t.Fatalf("settlement payment must expose authorization_id null: %v", p)
			}
		}
	}
	if st, _, e := settle("k3", ttLeg("bob", "ada", 100)); e != nil || st != 201 {
		t.Fatalf("a net-credited wallet always passes: %d %v", st, e)
	}
	// ada now holds 900 with 800 reserved: 100 may leave, 101 may not.
	if _, _, e := settle("k4", ttLeg("ada", "dee", 101)); ttCode(e) != "insufficient_funds" {
		t.Fatalf("one unit into the hold must be refused, got %v", e)
	}
	if st, _, e := settle("k5", ttLeg("ada", "dee", 100)); e != nil || st != 201 {
		t.Fatalf("exact boundary: %d %v", st, e)
	}
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}

	// With an injected clock the same debit is refused before the deadline and fits after it.
	body := ttBody(t, ttTransfers(ttLeg("ada", "dee", 800)))
	for _, c := range []struct {
		now     time.Time
		allowed bool
	}{
		{time.Date(2098, 12, 31, 23, 59, 59, 0, time.UTC), false},
		{time.Date(2099, 1, 1, 0, 0, 0, 0, time.UTC), true}, // now == expires_at: released
	} {
		s.mu.Lock()
		_, e := trSettle(s.st, body, c.now)
		s.mu.Unlock()
		if (e == nil) != c.allowed {
			t.Fatalf("settlement at %v: err=%v, allowed=%v", c.now, e, c.allowed)
		}
	}
}

func TestCaptureStormThroughIdempotent(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_1", "open", 1000, txFuture, ""))))
	const n = 100
	type res struct {
		status int
		body   []byte
		err    *AppError
		amount int64
	}
	out := make([]res, n)
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			r := rand.New(rand.NewSource(int64(i)))
			amt := int64(1 + r.Intn(30))
			<-start
			st, b, e := txCapture(s, "u_bob", "a_1", fmt.Sprintf("storm-%d", i), &amt, false, time.Now())
			out[i] = res{st, b, e, amt}
		}(i)
	}
	close(start)
	wg.Wait()

	var moved int64
	ok := 0
	ids := map[string]bool{}
	for _, r := range out {
		if r.err != nil {
			if r.err.Status != 422 && r.err.Status != 409 {
				t.Fatalf("storm produced %d %s", r.err.Status, r.err.Code)
			}
			continue
		}
		if r.status != 201 {
			t.Fatalf("distinct keys must each be a first use, got %d", r.status)
		}
		ok++
		moved += r.amount
		p := txJSON(t, r.body)
		if p["authorization_id"] != "a_1" || p["request_id"] != nil || txNum(p, "amount") != r.amount {
			t.Fatalf("capture payment %v", p)
		}
		id := p["payment_id"].(string)
		if ids[id] {
			t.Fatalf("payment %s created twice", id)
		}
		ids[id] = true
	}
	s.mu.Lock()
	a := s.st.authByID["a_1"]
	captured, listed := a.CapturedAmount, len(a.PaymentIDs)
	linked := 0
	for _, p := range s.st.Payments {
		if p.AuthorizationID != nil && *p.AuthorizationID == "a_1" {
			linked++
		}
	}
	s.mu.Unlock()
	if captured > 1000 || captured != moved || listed != ok || linked != ok {
		t.Fatalf("captured=%d moved=%d successes=%d listed=%d linked=%d (authorized 1000)", captured, moved, ok, listed, linked)
	}
	if ttBal(s, "bob") != 500+moved || ttBal(s, "ada") != 1000-moved {
		t.Fatalf("balances: bob=%d ada=%d moved=%d", ttBal(s, "bob"), ttBal(s, "ada"), moved)
	}
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}
	if ok < 20 || moved < 800 {
		t.Fatalf("storm too weak to mean anything: %d successes, %d moved", ok, moved)
	}
	// Whatever is left is released by one final capture; the hold is then closed for good.
	left := int64(1000) - moved
	if st, _, e := txCapture(s, "u_bob", "a_1", "storm-final", nil, true, time.Now()); left > 0 && (e != nil || st != 201) {
		t.Fatalf("final capture of the remainder %d: %d %v", left, st, e)
	}
	if ttBal(s, "bob") != 1500 || ttBal(s, "ada") != 0 {
		t.Fatalf("after the remainder: bob=%d ada=%d", ttBal(s, "bob"), ttBal(s, "ada"))
	}
	t.Logf("%d of %d captures succeeded, %d moved of 1000", ok, n, moved)
}

// A hundred final captures with distinct keys: exactly one wins, the rest see a closed hold.
func TestFinalCaptureRaceExactlyOne(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_1", "open", 1000, txFuture, ""))))
	var created, notOpen, other atomic.Int64
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			amt := int64(10 + i)
			<-start
			st, _, e := txCapture(s, "u_bob", "a_1", fmt.Sprintf("final-%d", i), &amt, true, time.Now())
			switch {
			case e == nil && st == 201:
				created.Add(1)
			case ttCode(e) == "authorization_not_open":
				notOpen.Add(1)
			default:
				other.Add(1)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	if created.Load() != 1 || notOpen.Load() != 99 || other.Load() != 0 {
		t.Fatalf("created=%d not_open=%d other=%d", created.Load(), notOpen.Load(), other.Load())
	}
	if ttPaymentCount(s) != 1 || ttSum(s) != txSeeded {
		t.Fatalf("payments=%d sum=%d", ttPaymentCount(s), ttSum(s))
	}
	if me := txMeS(t, s, "u_ada", time.Now()); txNum(me, "held") != 0 || txNum(me, "available") != txNum(me, "total") {
		t.Fatalf("the remainder must be released: %v", me)
	}
}

// ada has exactly 1000. Authorize 400, pay 300 and settle 250 all fight for it.
func TestAuthorizePaySettleRaceAtAvailableBoundary(t *testing.T) {
	s := txReset(t, txFx())
	stop := make(chan struct{})
	var wg, obs sync.WaitGroup
	var bad atomic.Value
	obs.Add(1)
	go func() {
		defer obs.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
				bad.CompareAndSwap(nil, msg)
				return
			}
		}
	}()
	var seq atomic.Int64
	for w := 0; w < 60; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			key := fmt.Sprintf("race-%d-%d", w, seq.Add(1))
			switch w % 3 {
			case 0:
				txAuthorize(s, "u_ada", key, "bob", 400, time.Now())
			case 1:
				ttPay(t, s, "u_ada", key, `{"to_handle":"cy","amount":300}`)
			default:
				s.Settle("u_ada", key, ttBody(t, ttTransfers(ttLeg("ada", "dee", 250))))
			}
		}(w)
	}
	wg.Wait()
	close(stop)
	obs.Wait()
	if v := bad.Load(); v != nil {
		t.Fatal(v)
	}
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}
	s.mu.Lock()
	held, bal := s.st.Held("u_ada", time.Now()), s.st.UserByHandle("ada").Balance
	s.mu.Unlock()
	if held+(1000-bal) > 1000 {
		t.Fatalf("overspent: held %d + moved out %d exceeds the 1000 ada started with", held, 1000-bal)
	}
}

// txMixedWriters makes random authorize/capture/void/pay calls among the four
// fixture users until stop is closed.
func txMixedWriters(s *Store, n int, stop <-chan struct{}, wg *sync.WaitGroup, created, captured *atomic.Int64) {
	handles := []string{"ada", "bob", "cy", "dee"}
	ids := map[string]string{"ada": "u_ada", "bob": "u_bob", "cy": "u_cy", "dee": "u_dee"}
	var seq atomic.Int64
	for w := 0; w < n; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			r := rand.New(rand.NewSource(int64(w) + 100))
			for {
				select {
				case <-stop:
					return
				default:
				}
				from, to := handles[r.Intn(4)], handles[r.Intn(4)]
				key := fmt.Sprintf("m%d-%d", w, seq.Add(1))
				var authID, rcv, payer string
				s.mu.Lock()
				if l := len(s.st.Authorizations); l > 0 {
					a := s.st.Authorizations[r.Intn(l)]
					authID, rcv, payer = a.AuthorizationID, a.ToUserID, a.FromUserID
				}
				s.mu.Unlock()
				amt := int64(1 + r.Intn(80))
				switch op := r.Intn(10); {
				case op < 4:
					if st, _, e := txAuthorize(s, ids[from], key, to, amt, time.Now()); e == nil && st == 201 {
						created.Add(1)
					}
				case op < 7 && authID != "":
					if st, _, e := txCapture(s, rcv, authID, key, &amt, r.Intn(3) == 0, time.Now()); e == nil && st == 201 {
						captured.Add(1)
					}
				case op < 8 && authID != "":
					txVoid(s, payer, authID, time.Now())
				default:
					txPay(s, ids[from], key, to, amt)
				}
			}
		}(w)
	}
}

func TestExportDuringAuthorizationWritersKeepsInvariants(t *testing.T) {
	s := txReset(t, txFx())
	stop := make(chan struct{})
	var wg sync.WaitGroup
	var created, captured atomic.Int64
	txMixedWriters(s, 50, stop, &wg, &created, &captured)
	deadline := time.Now().Add(900 * time.Millisecond)
	exports := 0
	for time.Now().Before(deadline) {
		raw := ttExport(t, s)
		var env struct {
			State struct {
				Users []struct {
					ID      string `json:"id"`
					Balance int64  `json:"balance"`
				} `json:"users"`
				Authorizations []struct {
					From     string `json:"from_user_id"`
					Amount   int64  `json:"amount"`
					Captured int64  `json:"captured_amount"`
					Status   string `json:"status"`
				} `json:"authorizations"`
			} `json:"state"`
		}
		if err := json.Unmarshal(raw, &env); err != nil {
			t.Fatal(err)
		}
		held := map[string]int64{}
		for _, a := range env.State.Authorizations {
			if a.Captured < 0 || a.Captured > a.Amount {
				t.Fatalf("export %d: captured %d outside 0..%d", exports, a.Captured, a.Amount)
			}
			if a.Status == "open" { // ttl is 600s: nothing expires during the test
				held[a.From] += a.Amount - a.Captured
			}
		}
		var sum int64
		for _, u := range env.State.Users {
			if u.Balance < 0 || held[u.ID] > u.Balance {
				t.Fatalf("export %d: %s balance %d held %d", exports, u.ID, u.Balance, held[u.ID])
			}
			sum += u.Balance
		}
		if sum != txSeeded {
			t.Fatalf("export %d: balances sum to %d, want %d", exports, sum, txSeeded)
		}
		if exports%8 == 0 { // every snapshot must also be importable
			if e := txReset(t, txFx()).Import(raw); e != nil {
				t.Fatalf("export %d does not import: %v", exports, e.Message)
			}
		}
		exports++
	}
	close(stop)
	wg.Wait()
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}
	if exports == 0 || created.Load() == 0 || captured.Load() == 0 {
		t.Fatalf("not enough activity: exports=%d created=%d captured=%d", exports, created.Load(), captured.Load())
	}
	t.Logf("%d exports, %d authorizations created, %d captures under 50 writers", exports, created.Load(), captured.Load())
}

func TestImportAndResetDuringAuthorizationWritersNeverPanic(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_seed", "open", 300, txFuture, ""))))
	snap := ttExport(t, s)
	stop := make(chan struct{})
	var wg sync.WaitGroup
	var created, captured atomic.Int64
	txMixedWriters(s, 50, stop, &wg, &created, &captured)
	deadline := time.Now().Add(900 * time.Millisecond)
	imports := 0
	for time.Now().Before(deadline) {
		if e := s.Import(snap); e != nil {
			t.Fatal(e.Message)
		}
		if imports%5 == 0 {
			if e := s.Reset([]byte(txFx(txAuths(txA("a_seed", "open", 300, txFuture, ""))))); e != nil {
				t.Fatal(e.Message)
			}
		}
		if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
			t.Fatalf("after import/reset %d: %s", imports, msg)
		}
		imports++
	}
	close(stop)
	wg.Wait()
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}
	t.Logf("%d imports under 50 writers (created %d, captured %d)", imports, created.Load(), captured.Load())
}

func TestCaptureReplaySurvivesExportImport(t *testing.T) {
	s := txReset(t, txFx(txAuths(txA("a_1", "open", 400, txFuture, ""))))
	amt := int64(150)
	st, first, e := txCapture(s, "u_bob", "a_1", "cap-lost", &amt, true, time.Now())
	if e != nil || st != 201 {
		t.Fatalf("capture: %d %v", st, e)
	}
	snap := ttExport(t, s)
	d := txReset(t, txFx())
	if e := d.Import(snap); e != nil {
		t.Fatal(e.Message)
	}
	st, again, e := txCapture(d, "u_bob", "a_1", "cap-lost", &amt, true, time.Now())
	if e != nil || st != 200 || string(again) != string(first) {
		t.Fatalf("replay after state round trip: %d %v\n%s\n%s", st, e, again, first)
	}
	// ada got her remainder back at the final capture; nothing moved twice.
	if ttBal(d, "bob") != 650 || ttBal(d, "ada") != 850 || ttSum(d) != txSeeded || ttPaymentCount(d) != 1 {
		t.Fatalf("replay moved money: bob=%d ada=%d payments=%d", ttBal(d, "bob"), ttBal(d, "ada"), ttPaymentCount(d))
	}
	if me := txMeS(t, d, "u_ada", time.Now()); txNum(me, "held") != 0 || txNum(me, "available") != 850 {
		t.Fatalf("ada /me after final capture: %v", me)
	}
	if _, _, e := txCapture(d, "u_bob", "a_1", "cap-new", &amt, true, time.Now()); ttCode(e) != "authorization_not_open" {
		t.Fatalf("a closed hold cannot be captured again: %v", e)
	}
}

func TestShortTTLWithInjectedClock(t *testing.T) {
	s := txReset(t, txFx(`"authorization_ttl_seconds":2`))
	t0 := time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	at := func(d time.Duration) time.Time { return t0.Add(d) }

	st, b, e := txAuthorize(s, "u_ada", "auth-1", "bob", 400, t0)
	if e != nil || st != 201 {
		t.Fatalf("authorize: %d %v", st, e)
	}
	if a := txJSON(t, b); a["expires_at"] != "2030-01-01T00:00:02.000000+00:00" || a["created_at"] != "2030-01-01T00:00:00.000000+00:00" || a["status"] != "open" {
		t.Fatalf("authorization: %v", a)
	}
	if me := txMeS(t, s, "u_ada", at(time.Second)); txNum(me, "held") != 400 || txNum(me, "available") != 600 {
		t.Fatalf("one second in: %v", me)
	}
	part := int64(100)
	st, capBody, e := txCapture(s, "u_bob", "a_1", "cap-1", &part, false, at(time.Second))
	if e != nil || st != 201 {
		t.Fatalf("partial capture before the deadline: %d %v", st, e)
	}
	if me := txMeS(t, s, "u_ada", at(1999*time.Millisecond)); txNum(me, "held") != 300 || txNum(me, "available") != 600 {
		t.Fatalf("one millisecond before expiry the remainder is still held: %v", me)
	}

	// now == expires_at: expired, remainder released, no request needed to notice.
	dead := at(2 * time.Second)
	if me := txMeS(t, s, "u_ada", dead); txNum(me, "held") != 0 || txNum(me, "available") != 900 || txNum(me, "total") != 900 {
		t.Fatalf("at the deadline: %v", me)
	}
	l := txList(t, s, "u_bob", "incoming", "", dead)
	if len(l) != 1 || l[0]["status"] != "expired" || txNum(l[0], "remaining_amount") != 0 ||
		txNum(l[0], "captured_amount") != 100 || len(l[0]["payment_ids"].([]any)) != 1 {
		t.Fatalf("expired authorization must keep its capture records: %v", l)
	}
	if n := len(txList(t, s, "u_bob", "", "open", dead)); n != 0 {
		t.Fatalf("an expired authorization matches expired, never open: %d", n)
	}
	s.mu.Lock()
	stored := s.st.Authorizations[0].Status
	s.mu.Unlock()
	if stored != "open" {
		t.Fatalf("the clock must never mutate the stored status, got %q", stored)
	}
	rest := int64(50)
	if _, _, e := txCapture(s, "u_bob", "a_1", "cap-2", &rest, true, dead); ttCode(e) != "authorization_expired" || e.Status != 409 {
		t.Fatalf("capture at the deadline: %v", e)
	}
	if _, _, e := txVoid(s, "u_ada", "a_1", dead); ttCode(e) != "authorization_not_open" {
		t.Fatalf("void of an expired authorization: %v", e)
	}
	// A replay of the earlier capture is a replay, not a state check.
	st, again, e := txCapture(s, "u_bob", "a_1", "cap-1", &part, false, at(time.Hour))
	if e != nil || st != 200 || string(again) != string(capBody) {
		t.Fatalf("replay after expiry: %d %v", st, e)
	}
	// The released money can be authorized again; one unit more cannot.
	if _, _, e := txAuthorize(s, "u_ada", "auth-2", "cy", 901, dead); ttCode(e) != "insufficient_funds" {
		t.Fatalf("901 of 900 available: %v", e)
	}
	if st, _, e := txAuthorize(s, "u_ada", "auth-3", "cy", 900, dead); e != nil || st != 201 {
		t.Fatalf("900 of 900 available: %d %v", st, e)
	}
}

// ada can afford exactly ten 100-unit commitments. Half the callers authorize, half pay.
func TestConcurrentAuthorizeAndPayExactlyTenWin(t *testing.T) {
	s := txReset(t, txFx())
	var wins atomic.Int64
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			var st int
			var e *AppError
			if i%2 == 0 {
				st, _, e = txAuthorize(s, "u_ada", fmt.Sprintf("x-%d", i), "bob", 100, time.Now())
			} else {
				st, _, e = txPay(s, "u_ada", fmt.Sprintf("x-%d", i), "cy", 100)
			}
			if e == nil && st == 201 {
				wins.Add(1)
			} else if ttCode(e) != "insufficient_funds" {
				t.Errorf("caller %d: %d %v", i, st, e)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	if wins.Load() != 10 {
		t.Fatalf("%d commitments succeeded, want exactly 10", wins.Load())
	}
	if msg := txInvariants(s, txSeeded, time.Now()); msg != "" {
		t.Fatal(msg)
	}
	s.mu.Lock()
	held, bal := s.st.Held("u_ada", time.Now()), s.st.UserByHandle("ada").Balance
	s.mu.Unlock()
	if held+(1000-bal) != 1000 {
		t.Fatalf("held %d + paid %d should use up all 1000", held, 1000-bal)
	}
}

// The handlers read the real clock. With a one second lifetime expires_at is exactly one second after
// created_at, so once the wall clock has moved past it (the margin covers the coarse Windows wall
// clock) the hold is gone although no request touched it at the deadline.
func TestRealClockExpiryNeedsNoRequestAtTheDeadline(t *testing.T) {
	h, tok := txServerFx(t, txFx(`"authorization_ttl_seconds":1`))
	b := txWant(t, "authorize", txDo(h, "POST", "/authorizations", tok["ada"], "rc", `{"to_handle":"bob","amount":400}`), 201)
	id := txJSON(t, b)["authorization_id"].(string)
	time.Sleep(1100 * time.Millisecond)

	if me := txMe(t, h, tok["ada"]); txNum(me, "held") != 0 || txNum(me, "available") != 1000 || txNum(me, "total") != 1000 {
		t.Fatalf("/me after the deadline: %v", me)
	}
	var list struct{ Authorizations []map[string]any }
	if err := json.Unmarshal(txWant(t, "list", txDo(h, "GET", "/authorizations?status=expired", tok["bob"], "", ""), 200), &list); err != nil ||
		len(list.Authorizations) != 1 || list.Authorizations[0]["status"] != "expired" || txNum(list.Authorizations[0], "remaining_amount") != 0 {
		t.Fatalf("expired list: %v %v", list, err)
	}
	if err := json.Unmarshal(txWant(t, "open list", txDo(h, "GET", "/authorizations?status=open", tok["bob"], "", ""), 200), &list); err != nil || len(list.Authorizations) != 0 {
		t.Fatalf("an expired authorization must not match open: %v", list)
	}
	txWantErr(t, "capture", txDo(h, "POST", "/authorizations/"+id+"/capture", tok["bob"], "rc-cap", `{}`), 409, "authorization_expired")
	txWantErr(t, "void", txDo(h, "POST", "/authorizations/"+id+"/void", tok["ada"], "", ""), 409, "authorization_not_open")
	// The released funds are spendable at once.
	txWant(t, "pay the full balance", txDo(h, "POST", "/payments", tok["ada"], "rc-pay", `{"to_handle":"cy","amount":1000}`), 201)
}
