package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"
)

const ttFixture = `{"currency":"EUR","minor_units":2,"settlement_operator_ids":["u_ada"],
"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":0},
 {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":0},
 {"id":"u_dee","email":"dee@example.com","password":"correct horse","display_name":"Dee","handle":"dee","balance":100}],
"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":500,"note":"coffee","visibility":"public"}],
"requests":[{"id":"rq_1","requester_id":"u_bob","payer_id":"u_ada","amount":1200,"note":"taxi","status":"pending"}]}`

const ttSeededSum = int64(10100)

func ttStore(t testing.TB) *Store {
	t.Helper()
	s := NewStore()
	if e := s.Reset([]byte(ttFixture)); e != nil {
		t.Fatalf("reset: %v", e.Message)
	}
	return s
}

func ttBody(t testing.TB, js string) map[string]any {
	t.Helper()
	var m map[string]any
	dec := json.NewDecoder(strings.NewReader(js))
	dec.UseNumber()
	if err := dec.Decode(&m); err != nil {
		t.Fatalf("bad test json %q: %v", js, err)
	}
	return m
}

func ttPay(t testing.TB, s *Store, uid, key, body string) (int, []byte, *AppError) {
	b := ttBody(t, body)
	return s.Idempotent(uid, "POST", "/payments", key, b, func(st *State) (any, *AppError) {
		amt, e := ReqAmount(b, "amount")
		if e != nil {
			return nil, e
		}
		to, _ := b["to_handle"].(string)
		return st.Pay(uid, PaymentIn{ToHandle: to, Amount: amt, Visibility: "public"}, time.Now())
	})
}

func ttBal(s *Store, handle string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.st.UserByHandle(handle).Balance
}

func ttSum(s *Store) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	var sum int64
	for _, u := range s.st.Users {
		if u.Balance < 0 {
			panic("negative balance")
		}
		sum += u.Balance
	}
	return sum
}

func ttPaymentCount(s *Store) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.st.Payments)
}

func ttCode(e *AppError) string {
	if e == nil {
		return ""
	}
	return e.Code
}

func TestIdemConcurrentIdentical(t *testing.T) {
	s := ttStore(t)
	const n = 100
	type res struct {
		status int
		body   []byte
		err    *AppError
	}
	out := make([]res, n)
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			st, b, e := ttPay(t, s, "u_ada", "same-key", `{"to_handle":"bob","amount":100}`)
			out[i] = res{st, b, e}
		}(i)
	}
	close(start)
	wg.Wait()
	created, replays := 0, 0
	for _, r := range out {
		if r.err != nil {
			t.Fatalf("unexpected error %v", r.err.Code)
		}
		switch r.status {
		case 201:
			created++
		case 200:
			replays++
		}
		if !bytes.Equal(r.body, out[0].body) {
			t.Fatalf("bodies differ:\n%s\n%s", r.body, out[0].body)
		}
	}
	if created != 1 || replays != n-1 {
		t.Fatalf("want 1x201 + %dx200, got %d x201, %d x200", n-1, created, replays)
	}
	if ttBal(s, "ada") != 9900 || ttBal(s, "bob") != 100 || ttSum(s) != ttSeededSum {
		t.Fatalf("money moved more than once: ada=%d bob=%d", ttBal(s, "ada"), ttBal(s, "bob"))
	}
}

func TestIdemChangedBodyIs409BeforeValidation(t *testing.T) {
	s := ttStore(t)
	if st, _, e := ttPay(t, s, "u_ada", "k", `{"to_handle":"bob","amount":100}`); e != nil || st != 201 {
		t.Fatalf("first use: %d %v", st, e)
	}
	for _, body := range []string{
		`{"to_handle":"bob","amount":101}`,
		`{"to_handle":"bob","amount":"oops"}`,
		`{"to_handle":"nobody","amount":-5}`,
		`{}`,
	} {
		calls := 0
		_, _, e := s.Idempotent("u_ada", "POST", "/payments", "k", ttBody(t, body), func(*State) (any, *AppError) {
			calls++
			return nil, NewErr(422, "validation_failed", "must not run")
		})
		if ttCode(e) != "idempotency_key_reuse" || e.Status != 409 || calls != 0 {
			t.Fatalf("body %s: got %v (calls=%d), want 409 idempotency_key_reuse", body, e, calls)
		}
	}
}

func TestIdemFailedKeyStaysReusable(t *testing.T) {
	s := ttStore(t)
	_, _, e := ttPay(t, s, "u_dee", "k", `{"to_handle":"bob","amount":500}`)
	if ttCode(e) != "insufficient_funds" {
		t.Fatalf("want insufficient_funds, got %v", e)
	}
	_, _, e = ttPay(t, s, "u_dee", "k", `{"to_handle":"bob","amount":"x"}`)
	if ttCode(e) != "validation_failed" {
		t.Fatalf("a failed key must not be claimed, got %v", e)
	}
	st, _, e := ttPay(t, s, "u_dee", "k", `{"to_handle":"bob","amount":50}`)
	if e != nil || st != 201 || ttBal(s, "dee") != 50 {
		t.Fatalf("retry with new body on failed key: %d %v dee=%d", st, e, ttBal(s, "dee"))
	}
}

func TestIdemScopedPerUserAndPath(t *testing.T) {
	s := ttStore(t)
	body := `{"to_handle":"cy","amount":10}`
	if st, _, e := ttPay(t, s, "u_ada", "shared", body); e != nil || st != 201 {
		t.Fatalf("ada: %d %v", st, e)
	}
	if st, _, e := ttPay(t, s, "u_dee", "shared", body); e != nil || st != 201 {
		t.Fatalf("same key, other user must be a first use: %d %v", st, e)
	}
	calls := 0
	st, _, e := s.Idempotent("u_ada", "POST", "/requests", "shared", ttBody(t, body), func(*State) (any, *AppError) {
		calls++
		return map[string]any{"ok": true}, nil
	})
	if e != nil || st != 201 || calls != 1 {
		t.Fatalf("same key+body on another path must succeed: %d %v calls=%d", st, e, calls)
	}
	if ttBal(s, "cy") != 20 {
		t.Fatalf("cy should hold 20, has %d", ttBal(s, "cy"))
	}
}

func TestIdemReplayIsByJSONValueAndSurvivesChange(t *testing.T) {
	s := ttStore(t)
	_, first, e := ttPay(t, s, "u_ada", "k", `{"to_handle":"bob","amount":1000}`)
	if e != nil {
		t.Fatal(e.Message)
	}
	if _, _, e := ttPay(t, s, "u_ada", "other", `{"to_handle":"cy","amount":9000}`); e != nil {
		t.Fatal(e.Message)
	}
	for _, body := range []string{
		`{"amount":1000,"to_handle":"bob"}`,
		`{ "amount" : 1.0e3 , "to_handle" : "bob" }`,
		`{"to_handle":"bob","amount":1000.000}`,
	} {
		st, again, e := ttPay(t, s, "u_ada", "k", body)
		if e != nil || st != 200 || !bytes.Equal(first, again) {
			t.Fatalf("replay %s: status=%d err=%v same=%v", body, st, e, bytes.Equal(first, again))
		}
	}
	if ttBal(s, "bob") != 1000 || ttBal(s, "ada") != 0 {
		t.Fatalf("replays moved money: bob=%d ada=%d", ttBal(s, "bob"), ttBal(s, "ada"))
	}
}
