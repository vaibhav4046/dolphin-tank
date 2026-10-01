package main

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"
)

type fgU struct {
	h   string
	bal int64
}

// fgStore seeds users with id u_<handle>, email <handle>@example.com.
func fgStore(us ...fgU) *Store {
	st := &State{Currency: "EUR", MinorUnits: 2}
	for _, u := range us {
		st.Users = append(st.Users, &User{ID: "u_" + u.h, Email: u.h + "@example.com", DisplayName: u.h,
			Handle: u.h, PassHash: "x", Balance: u.bal})
	}
	if err := st.Reindex(); err != nil {
		panic(err)
	}
	return &Store{st: st}
}

func fgSum(s *Store) (sum int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, u := range s.st.Users {
		sum += u.Balance
	}
	return sum
}

func fgBal(s *Store, h string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.st.UserByHandle(h).Balance
}

func fgPay(s *Store, from, to string, amount int64, vis string) ([]byte, *AppError) {
	return s.Exec(func(st *State) (any, *AppError) {
		p, e := st.Pay("u_"+from, PaymentIn{ToHandle: to, Amount: amount, Visibility: vis}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
}

func fgReq(s *Store, requester, payer string, amount int64) *Request {
	var out *Request
	_, e := s.Exec(func(st *State) (any, *AppError) {
		r, e := st.CreateRequest("u_"+requester, RequestIn{PayerHandle: payer, Amount: amount, Note: "n"}, time.Now())
		out = r
		if e != nil {
			return nil, e
		}
		return r, nil
	})
	if e != nil {
		panic(e)
	}
	return out
}

func fgPayReq(s *Store, caller, id, vis string) *AppError {
	_, e := s.Exec(func(st *State) (any, *AppError) {
		p, e := st.PayRequest("u_"+caller, id, PayIn{Visibility: vis}, time.Now())
		if e != nil {
			return nil, e
		}
		return p, nil
	})
	return e
}

func fgState(s *Store) (users, payments, requests, splits int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.st.Users), len(s.st.Payments), len(s.st.Requests), len(s.st.Splits)
}

func TestForgePay(t *testing.T) {
	s := fgStore(fgU{"ada", 1000}, fgU{"bob", 0})
	for _, c := range []struct {
		to     string
		amt    int64
		status int
		code   string
	}{
		{"ghost", 10, 404, "not_found"},
		{"ada", 10, 422, "self_payment"},
		{"bob", 1001, 409, "insufficient_funds"},
	} {
		b, e := fgPay(s, "ada", c.to, c.amt, "public")
		if b != nil {
			t.Fatal("bytes with error")
		}
		fgWantErr(t, c.to, e, c.status, c.code)
	}
	if _, p, _, _ := fgState(s); p != 0 || fgBal(s, "ada") != 1000 || fgBal(s, "bob") != 0 {
		t.Fatal("failed payment left a trace")
	}
	b, e := fgPay(s, "ada", "bob", 1000, "private")
	if e != nil {
		t.Fatal(e)
	}
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	if m["payment_id"] != "p_1" || m["from_handle"] != "ada" || m["to_handle"] != "bob" || m["amount"].(float64) != 1000 ||
		m["currency"] != "EUR" || m["visibility"] != "private" || m["request_id"] != nil || m["settlement_id"] != nil {
		t.Fatalf("%s", b)
	}
	if _, has := m["settlement_id"]; !has {
		t.Fatal("settlement_id must always be present")
	}
	if ts, err := time.Parse(time.RFC3339, m["created_at"].(string)); err != nil || ts.IsZero() {
		t.Fatal(m["created_at"], err)
	}
	if fgBal(s, "ada") != 0 || fgBal(s, "bob") != 1000 {
		t.Fatal("balances")
	}
}

func TestForgeNewIDSkipsSeeded(t *testing.T) {
	st := &State{Currency: "EUR", MinorUnits: 2,
		Users:    []*User{{ID: "u_1", Handle: "ada", Balance: 5}, {ID: "u_2", Handle: "bob"}},
		Payments: []*Payment{{PaymentID: "p_1", FromUserID: "u_1", ToUserID: "u_2", Amount: 1}, {PaymentID: "p_2", FromUserID: "u_1", ToUserID: "u_2", Amount: 1}},
		Requests: []*Request{{RequestID: "rq_1", RequesterID: "u_2", PayerID: "u_1", Amount: 3}}}
	if err := st.Reindex(); err != nil {
		t.Fatal(err)
	}
	if id := st.NewID("p"); id != "p_3" {
		t.Fatal(id)
	}
	if id := st.NewID("rq"); id != "rq_2" {
		t.Fatal(id)
	}
	if id := st.NewID("u"); id != "u_3" {
		t.Fatal(id)
	}
	if st.Payments[0].Visibility != "public" || st.Requests[0].Status != "pending" || st.Payments[0].FromHandle != "ada" ||
		st.Requests[0].PayerHandle != "ada" || st.Requests[0].Currency != "EUR" || st.Payments[0].CreatedAt == "" {
		t.Fatalf("defaults/derived fields: %+v %+v", st.Payments[0], st.Requests[0])
	}
}

func TestForgeRequestLifecycle(t *testing.T) {
	s := fgStore(fgU{"ada", 100}, fgU{"bob", 0}, fgU{"cy", 500})
	for _, c := range [][2]string{{"ghost", "404"}, {"bob", "422"}} {
		_, e := s.Exec(func(st *State) (any, *AppError) {
			return st.CreateRequest("u_bob", RequestIn{PayerHandle: c[0], Amount: 5}, time.Now())
		})
		if c[1] == "404" {
			fgWantErr(t, "unknown payer", e, 404, "not_found")
		} else {
			fgWantErr(t, "self", e, 422, "self_request")
		}
	}
	r := fgReq(s, "bob", "ada", 500) // exceeds ada's balance: legal
	if r.Status != "pending" || r.PaymentID != nil || r.RequesterHandle != "bob" || r.PayerHandle != "ada" {
		t.Fatalf("%+v", r)
	}
	// pay order: 404 -> 403 (requester and stranger alike) -> 409 insufficient, nothing changes -> ok
	fgWantErr(t, "unknown", fgPayReq(s, "ada", "rq_nope", "public"), 404, "not_found")
	fgWantErr(t, "requester", fgPayReq(s, "bob", r.RequestID, "public"), 403, "forbidden")
	fgWantErr(t, "stranger", fgPayReq(s, "cy", r.RequestID, "public"), 403, "forbidden")
	fgWantErr(t, "short", fgPayReq(s, "ada", r.RequestID, "public"), 409, "insufficient_funds")
	if _, p, _, _ := fgState(s); p != 0 || r.Status != "pending" || fgBal(s, "ada") != 100 || fgBal(s, "bob") != 0 {
		t.Fatal("failed pay changed state")
	}
	if _, e := fgPay(s, "cy", "ada", 450, "public"); e != nil { // money arrives; same request now payable
		t.Fatal(e)
	}
	if e := fgPayReq(s, "ada", r.RequestID, "private"); e != nil {
		t.Fatal(e)
	}
	pay := s.st.Payments[len(s.st.Payments)-1]
	if r.Status != "paid" || r.PaymentID == nil || *r.PaymentID != pay.PaymentID || pay.RequestID == nil || *pay.RequestID != r.RequestID ||
		pay.Visibility != "private" || pay.Amount != 500 || pay.FromHandle != "ada" || pay.ToHandle != "bob" {
		t.Fatalf("%+v %+v", r, pay)
	}
	fgWantErr(t, "paid twice", fgPayReq(s, "ada", r.RequestID, "public"), 409, "request_not_pending")
	if fgBal(s, "bob") != 500 || fgBal(s, "ada") != 50 {
		t.Fatal("money moved twice")
	}

	// decline / cancel matrix
	call := func(op, who, id string) (*Request, *AppError) {
		var out *Request
		_, e := s.Exec(func(st *State) (any, *AppError) {
			var e *AppError
			if op == "decline" {
				out, e = st.Decline("u_"+who, id)
			} else {
				out, e = st.Cancel("u_"+who, id)
			}
			if e != nil {
				return nil, e
			}
			return out, nil
		})
		return out, e
	}
	d := fgReq(s, "bob", "cy", 5)
	_, e := call("decline", "bob", d.RequestID)
	fgWantErr(t, "requester declines", e, 403, "forbidden")
	_, e = call("decline", "ada", d.RequestID)
	fgWantErr(t, "stranger declines", e, 403, "forbidden")
	_, e = call("cancel", "cy", d.RequestID)
	fgWantErr(t, "payer cancels", e, 403, "forbidden")
	_, e = call("decline", "cy", "nope")
	fgWantErr(t, "unknown", e, 404, "not_found")
	for i := 0; i < 2; i++ {
		if got, e := call("decline", "cy", d.RequestID); e != nil || got.Status != "declined" {
			t.Fatal(got, e)
		}
	}
	_, e = call("cancel", "bob", d.RequestID)
	fgWantErr(t, "cancel declined", e, 409, "request_not_pending")
	fgWantErr(t, "pay declined", fgPayReq(s, "cy", d.RequestID, "public"), 409, "request_not_pending")
	c := fgReq(s, "bob", "cy", 5)
	for i := 0; i < 2; i++ {
		if got, e := call("cancel", "bob", c.RequestID); e != nil || got.Status != "cancelled" {
			t.Fatal(got, e)
		}
	}
	_, e = call("decline", "cy", c.RequestID)
	fgWantErr(t, "decline cancelled", e, 409, "request_not_pending")
	_, e = call("decline", "ada", r.RequestID)
	fgWantErr(t, "decline paid", e, 409, "request_not_pending")
	_, e = call("cancel", "bob", r.RequestID)
	fgWantErr(t, "cancel paid", e, 409, "request_not_pending")
}

func TestForgeFeedAndListing(t *testing.T) {
	s := fgStore(fgU{"ada", 1000}, fgU{"bob", 1000}, fgU{"cy", 1000})
	fgPay(s, "ada", "bob", 1, "private")
	fgPay(s, "ada", "bob", 2, "public")
	fgPay(s, "bob", "cy", 3, "private")
	feed := func(who string, limit, offset int) (amts []int64, more bool) {
		b, _ := s.Exec(func(st *State) (any, *AppError) { return st.Activity("u_"+who, limit, offset), nil })
		var m struct {
			Payments []Payment `json:"payments"`
			HasMore  bool      `json:"has_more"`
		}
		if err := json.Unmarshal(b, &m); err != nil {
			t.Fatal(err, string(b))
		}
		for _, p := range m.Payments {
			amts = append(amts, p.Amount)
		}
		return amts, m.HasMore
	}
	eq := func(what string, got []int64, want ...int64) {
		t.Helper()
		if fmt.Sprint(got) != fmt.Sprint(want) {
			t.Fatalf("%s: got %v want %v", what, got, want)
		}
	}
	a, _ := feed("ada", 50, 0)
	eq("ada sees own private + public, newest first", a, 2, 1)
	a, _ = feed("bob", 50, 0)
	eq("bob", a, 3, 2, 1)
	a, _ = feed("cy", 50, 0)
	eq("cy sees own private + others' public", a, 3, 2)
	a, more := feed("bob", 2, 0)
	if fmt.Sprint(a) != "[3 2]" || !more {
		t.Fatal(a, more)
	}
	a, more = feed("bob", 2, 2)
	if fmt.Sprint(a) != "[1]" || more {
		t.Fatal(a, more)
	}
	a, more = feed("bob", 3, 0)
	if fmt.Sprint(a) != "[3 2 1]" || more {
		t.Fatal("has_more must be false when the page ends exactly at the end", a, more)
	}
	a, more = feed("bob", 5, 99)
	if len(a) != 0 || more {
		t.Fatal(a, more)
	}
	if b, _ := s.Exec(func(st *State) (any, *AppError) { return st.Activity("u_ada", 5, 99), nil }); string(b) != `{"payments":[],"has_more":false}` {
		t.Fatal(string(b))
	}

	r1, r2 := fgReq(s, "ada", "bob", 10), fgReq(s, "bob", "ada", 20)
	fgReq(s, "bob", "cy", 30)
	list := func(who, dir, status string) (ids []string) {
		b, e := s.Exec(func(st *State) (any, *AppError) { return st.ListRequests("u_"+who, dir, status, 50, 0) })
		if e != nil {
			t.Fatal(e)
		}
		var m struct {
			Requests []Request `json:"requests"`
		}
		_ = json.Unmarshal(b, &m)
		for _, r := range m.Requests {
			ids = append(ids, r.RequestID)
		}
		return ids
	}
	if got := list("ada", "", ""); fmt.Sprint(got) != fmt.Sprint([]string{r2.RequestID, r1.RequestID}) {
		t.Fatal(got)
	}
	if got := list("ada", "incoming", ""); fmt.Sprint(got) != fmt.Sprint([]string{r2.RequestID}) {
		t.Fatal(got)
	}
	if got := list("ada", "outgoing", "pending"); fmt.Sprint(got) != fmt.Sprint([]string{r1.RequestID}) {
		t.Fatal(got)
	}
	if got := list("ada", "outgoing", "paid"); len(got) != 0 {
		t.Fatal(got)
	}
	if got := list("cy", "", ""); len(got) != 1 {
		t.Fatal("cy sees only its own request", got)
	}
	for _, c := range [][2]string{{"sideways", ""}, {"", "open"}, {"INCOMING", ""}} {
		_, e := s.Exec(func(st *State) (any, *AppError) { return st.ListRequests("u_ada", c[0], c[1], 50, 0) })
		fgWantErr(t, fmt.Sprint(c), e, 422, "validation_failed")
	}
	b, _ := s.Exec(func(st *State) (any, *AppError) { return st.ListRequests("u_ada", "", "", 1, 0) })
	var page struct {
		Requests []map[string]any `json:"requests"`
		HasMore  bool             `json:"has_more"`
	}
	_ = json.Unmarshal(b, &page)
	if len(page.Requests) != 1 || !page.HasMore {
		t.Fatal(string(b))
	}
	if _, has := page.Requests[0]["visibility"]; has {
		t.Fatal("request must carry no visibility")
	}
}

// 50 goroutines race to overdraw one wallet through Exec: exactly floor(balance/amount) win.
func TestForgeOverdraftRace(t *testing.T) {
	s := fgStore(fgU{"ada", 1000}, fgU{"bob", 7})
	total := fgSum(s)
	var wg sync.WaitGroup
	var mu sync.Mutex
	ok, insufficient := 0, 0
	stop := make(chan struct{})
	pollDone := make(chan struct{})
	go func() { // observer: no balance is ever seen negative
		defer close(pollDone)
		for {
			select {
			case <-stop:
				return
			default:
			}
			s.Exec(func(st *State) (any, *AppError) {
				for _, u := range st.Users {
					if u.Balance < 0 {
						t.Errorf("negative balance seen: %+v", u)
					}
				}
				return nil, nil
			})
		}
	}()
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, e := fgPay(s, "ada", "bob", 300, "public")
			mu.Lock()
			defer mu.Unlock()
			switch {
			case e == nil:
				ok++
			case e.Status == 409 && e.Code == "insufficient_funds":
				insufficient++
			default:
				t.Errorf("unexpected %v", e)
			}
		}()
	}
	wg.Wait()
	close(stop)
	<-pollDone
	if ok != 3 || insufficient != 47 {
		t.Fatalf("ok=%d insufficient=%d", ok, insufficient)
	}
	if fgBal(s, "ada") != 100 || fgBal(s, "bob") != 907 || fgSum(s) != total {
		t.Fatal("balances", fgBal(s, "ada"), fgBal(s, "bob"), fgSum(s))
	}
	if _, p, _, _ := fgState(s); p != 3 {
		t.Fatal("payments", p)
	}
}

// 30 concurrent pays of one request move money exactly once.
func TestForgePayRequestRace(t *testing.T) {
	s := fgStore(fgU{"ada", 10000}, fgU{"bob", 0})
	total := fgSum(s)
	r := fgReq(s, "bob", "ada", 500)
	var wg sync.WaitGroup
	var mu sync.Mutex
	ok, notPending := 0, 0
	for i := 0; i < 30; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			e := fgPayReq(s, "ada", r.RequestID, "public")
			mu.Lock()
			defer mu.Unlock()
			switch {
			case e == nil:
				ok++
			case e.Code == "request_not_pending":
				notPending++
			default:
				t.Errorf("unexpected %v", e)
			}
		}()
	}
	wg.Wait()
	if ok != 1 || notPending != 29 {
		t.Fatalf("ok=%d notPending=%d", ok, notPending)
	}
	if _, p, _, _ := fgState(s); p != 1 || fgBal(s, "ada") != 9500 || fgBal(s, "bob") != 500 || fgSum(s) != total {
		t.Fatal("state", p, fgBal(s, "ada"), fgBal(s, "bob"))
	}
}

func TestForgeSplitSharesTable(t *testing.T) {
	cases := []struct {
		amount int64
		n      int
		want   string
	}{
		{1000, 3, "[334 333 333]"}, {1, 3, "[1 0 0]"}, {10, 3, "[4 3 3]"}, {999, 3, "[333 333 333]"},
		{5, 5, "[1 1 1 1 1]"}, {7, 1, "[7]"}, {1_000_000_000, 7, ""},
	}
	for _, c := range cases {
		got := SplitShares(c.amount, c.n)
		var sum, lo, hi int64 = 0, got[0], got[0]
		for _, g := range got {
			sum += g
			lo, hi = min(lo, g), max(hi, g)
		}
		if len(got) != c.n || sum != c.amount || hi-lo > 1 || !fgNonIncreasing(got) {
			t.Fatalf("%d/%d: %v", c.amount, c.n, got)
		}
		if c.want != "" && fmt.Sprint(got) != c.want {
			t.Fatalf("%d/%d: got %v want %s", c.amount, c.n, got, c.want)
		}
	}
}

func fgNonIncreasing(a []int64) bool {
	for i := 1; i < len(a); i++ {
		if a[i] > a[i-1] {
			return false
		}
	}
	return true
}

func TestForgeSplit(t *testing.T) {
	s := fgStore(fgU{"ada", 0}, fgU{"bob", 0}, fgU{"cy", 0})
	total := fgSum(s)
	split := func(caller string, amount int64, handles ...string) (map[string]any, *AppError) {
		b, e := s.Exec(func(st *State) (any, *AppError) {
			return st.Split("u_"+caller, SplitIn{Amount: amount, Handles: handles, Note: "dinner"}, time.Now())
		})
		if e != nil {
			return nil, e
		}
		var m map[string]any
		if err := json.Unmarshal(b, &m); err != nil {
			t.Fatal(err)
		}
		return m, nil
	}
	shares := func(m map[string]any) (out []string) {
		for _, x := range m["shares"].([]any) {
			sh := x.(map[string]any)
			out = append(out, fmt.Sprintf("%s=%v", sh["handle"], sh["amount"]))
		}
		return out
	}
	reqs := func(m map[string]any) (out []string) {
		for _, x := range m["requests"].([]any) {
			r := x.(map[string]any)
			out = append(out, fmt.Sprintf("%s>%s:%v:%s", r["payer_handle"], r["requester_handle"], r["amount"], r["status"]))
		}
		return out
	}

	m, e := split("ada", 1000, "ada", "bob", "cy") // caller first: extra unit to the caller
	if e != nil || m["split_id"] != "sp_1" || m["currency"] != "EUR" || m["note"] != "dinner" {
		t.Fatal(m, e)
	}
	if fmt.Sprint(shares(m)) != "[ada=334 bob=333 cy=333]" || fmt.Sprint(reqs(m)) != "[bob>ada:333:pending cy>ada:333:pending]" {
		t.Fatal(shares(m), reqs(m))
	}
	m, _ = split("ada", 1000, "cy", "ada", "bob") // caller in the middle, different order -> different extra
	if fmt.Sprint(shares(m)) != "[cy=334 ada=333 bob=333]" || fmt.Sprint(reqs(m)) != "[cy>ada:334:pending bob>ada:333:pending]" {
		t.Fatal(shares(m), reqs(m))
	}
	m, _ = split("ada", 1, "bob", "cy", "ada") // caller last, zero shares still yield requests
	if fmt.Sprint(shares(m)) != "[bob=1 cy=0 ada=0]" || fmt.Sprint(reqs(m)) != "[bob>ada:1:pending cy>ada:0:pending]" {
		t.Fatal(shares(m), reqs(m))
	}
	m, _ = split("ada", 500, "bob", "cy") // caller absent: nobody is skipped, caller is not in shares
	if fmt.Sprint(shares(m)) != "[bob=250 cy=250]" || len(reqs(m)) != 2 {
		t.Fatal(shares(m), reqs(m))
	}
	m, e = split("ada", 42, "ada") // caller only: valid, zero requests
	if e != nil || fmt.Sprint(shares(m)) != "[ada=42]" || string(mustJSON(m["requests"])) != "[]" {
		t.Fatal(m, e)
	}

	u, p, r, sp := fgState(s)
	_, e = split("ada", 100, "bob", "ghost", "cy")
	fgWantErr(t, "unknown handle", e, 404, "not_found")
	if u2, p2, r2, sp2 := fgState(s); u2 != u || p2 != p || r2 != r || sp2 != sp {
		t.Fatal("failed split left a trace")
	}
	if p != 0 || fgSum(s) != total || fgBal(s, "bob") != 0 || fgBal(s, "ada") != 0 {
		t.Fatal("a split must move no money and create no feed item")
	}
	ids := map[string]bool{}
	for _, x := range s.st.Requests {
		if ids[x.RequestID] {
			t.Fatal("duplicate request id")
		}
		ids[x.RequestID] = true
	}
}

func mustJSON(v any) []byte {
	b, err := MarshalJSON(v)
	if err != nil {
		panic(err)
	}
	return b
}

// Repeated splits fully paid keep the wallet sum constant.
func TestForgeSplitsPaidInFull(t *testing.T) {
	s := fgStore(fgU{"ada", 100000}, fgU{"bob", 100000}, fgU{"cy", 100000})
	total := fgSum(s)
	for i, amt := range []int64{1000, 1, 10, 999, 7} {
		_, e := s.Exec(func(st *State) (any, *AppError) {
			return st.Split("u_ada", SplitIn{Amount: amt, Handles: []string{"bob", "ada", "cy"}}, time.Now())
		})
		if e != nil {
			t.Fatal(i, e)
		}
	}
	for _, r := range append([]*Request(nil), s.st.Requests...) {
		if e := fgPayReq(s, r.PayerHandle, r.RequestID, "public"); e != nil {
			t.Fatal(e)
		}
	}
	if fgSum(s) != total {
		t.Fatal("sum drifted", fgSum(s), total)
	}
}

func TestForgeExportRoundTripAndReindexRejects(t *testing.T) {
	s := fgStore(fgU{"ada", 1000}, fgU{"bob", 0})
	fgPay(s, "ada", "bob", 100, "private")
	r := fgReq(s, "bob", "ada", 200)
	fgPayReq(s, "ada", r.RequestID, "public")
	s.Exec(func(st *State) (any, *AppError) {
		return st.Split("u_ada", SplitIn{Amount: 10, Handles: []string{"ada", "bob"}}, time.Now())
	})
	fgSignup(t, s, "new@x.com", "correct horse", "New")
	raw, err := json.Marshal(s.st)
	if err != nil {
		t.Fatal(err)
	}
	var back State
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatal(err)
	}
	if err := back.Reindex(); err != nil {
		t.Fatal(err)
	}
	raw2, _ := json.Marshal(&back)
	if string(raw) != string(raw2) {
		t.Fatalf("round trip differs:\n%s\n%s", raw, raw2)
	}
	if back.UserByHandle("new") == nil || back.NewID("p") != "p_3" || back.NewID("rq") != "rq_3" {
		t.Fatal("indexes/counters not restored")
	}

	mutate := map[string]func(st *State){
		"negative balance":  func(st *State) { st.Users[0].Balance = -1 },
		"duplicate handle":  func(st *State) { st.Users[1].Handle = st.Users[0].Handle },
		"bad handle":        func(st *State) { st.Users[0].Handle = "Bad-Handle" },
		"long handle":       func(st *State) { st.Users[0].Handle = "aaaaaaaaaaaaaaaaaaaaa" },
		"duplicate email":   func(st *State) { st.Users[1].Email = "ADA@example.com" },
		"duplicate user id": func(st *State) { st.Users[1].ID = st.Users[0].ID },
		"dangling payment":  func(st *State) { st.Payments[0].ToUserID = "u_none" },
		"dup payment id":    func(st *State) { st.Payments[1].PaymentID = st.Payments[0].PaymentID },
		"bad visibility":    func(st *State) { st.Payments[0].Visibility = "friends" },
		"dangling request":  func(st *State) { st.Requests[0].PayerID = "u_none" },
		"bad status":        func(st *State) { st.Requests[0].Status = "open" },
		"dangling paymentid": func(st *State) {
			x := "p_none"
			st.Requests[0].PaymentID = &x
		},
		"dangling token":  func(st *State) { st.Tokens["t"] = "u_none" },
		"dangling split":  func(st *State) { st.Splits[0].RequestIDs = []string{"rq_none"} },
		"null user":       func(st *State) { st.Users[0] = nil },
		"bad minor units": func(st *State) { st.MinorUnits = 1 },
		"no currency":     func(st *State) { st.Currency = "" },
	}
	for name, mut := range mutate {
		var c State
		if err := json.Unmarshal(raw, &c); err != nil {
			t.Fatal(err)
		}
		mut(&c)
		if err := c.Reindex(); err == nil {
			t.Errorf("%s: Reindex accepted an invalid state", name)
		}
	}
}
