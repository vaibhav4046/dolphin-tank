package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

var azT0 = time.Date(2026, 9, 24, 13, 10, 0, 0, time.UTC)

func azI64(v int64) *int64 { return &v }

// azEmpty drains a wallet while keeping Balance == OpeningBalance + payments (here the 500 it paid out).
func azEmpty(u *User) { u.Balance, u.OpeningBalance = 0, 500 }

// azRelease gives a hand-built authorization with a closed stored status the closed_at Reindex requires.
func azRelease(a *Authorization) {
	if a.Status != authOpen {
		closed := FormatTime(azT0)
		a.ClosedAt = &closed
	}
}

func azStore(us ...fgU) (*Store, *State) {
	s := fgStore(us...)
	return s, s.st
}

func azAuthorize(t *testing.T, st *State, from, to string, amount int64, now time.Time) *AuthorizationBody {
	t.Helper()
	b, e := st.Authorize("u_"+from, AuthorizeIn{ToHandle: to, Amount: amount, Note: "deposit", Visibility: visPrivate}, now)
	if e != nil {
		t.Fatalf("authorize %s->%s %d: %v", from, to, amount, e)
	}
	return b
}

func azCapture(st *State, caller, id string, amount *int64, final bool, now time.Time) (*Payment, *AppError) {
	return st.Capture("u_"+caller, id, CaptureIn{Amount: amount, Final: final}, now)
}

func azMustCapture(t *testing.T, st *State, caller, id string, amount *int64, final bool, now time.Time) *Payment {
	t.Helper()
	p, e := azCapture(st, caller, id, amount, final, now)
	if e != nil {
		t.Fatalf("capture %s %v final=%v: %v", id, amount, final, e)
	}
	return p
}

func azAvail(st *State, h string, now time.Time) int64 { return st.Available(st.UserByHandle(h), now) }

func azBal(st *State, h string) int64 { return st.UserByHandle(h).Balance }

func azJSON(t *testing.T, v any) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(mustJSON(v), &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func azList(t *testing.T, st *State, caller, dir, status string, limit, offset int, now time.Time) ([]string, bool) {
	t.Helper()
	v, e := st.ListAuthorizations("u_"+caller, dir, status, limit, offset, now)
	if e != nil {
		t.Fatalf("list %s %q %q: %v", caller, dir, status, e)
	}
	pg := v.(authorizationPage)
	ids := []string{}
	for _, b := range pg.Authorizations {
		ids = append(ids, b.AuthorizationID)
	}
	return ids, pg.HasMore
}

// azInvariants: wallet sum constant, no negative balance, held <= balance, available >= 0,
// captured == the payments tagged with the authorization, captured <= amount.
func azInvariants(t *testing.T, st *State, seeded int64, now time.Time) {
	t.Helper()
	if err := azCheck(st, seeded, now); err != nil {
		t.Fatal(err)
	}
}

func azCheck(st *State, seeded int64, now time.Time) error {
	var sum int64
	for _, u := range st.Users {
		if u.Balance < 0 {
			return fmt.Errorf("%s: negative balance %d", u.Handle, u.Balance)
		}
		sum += u.Balance
		if h := st.Held(u.ID, now); h > u.Balance || st.Available(u, now) < 0 {
			return fmt.Errorf("%s: held %d exceeds balance %d", u.Handle, h, u.Balance)
		}
	}
	if sum != seeded {
		return fmt.Errorf("wallet sum %d, seeded %d", sum, seeded)
	}
	captured, count := map[string]int64{}, map[string]int{}
	for _, p := range st.Payments {
		if p.AuthorizationID != nil {
			captured[*p.AuthorizationID] += p.Amount
			count[*p.AuthorizationID]++
		}
	}
	for _, a := range st.Authorizations {
		if a.CapturedAmount < 0 || a.CapturedAmount > a.Amount {
			return fmt.Errorf("%s: captured %d of %d", a.AuthorizationID, a.CapturedAmount, a.Amount)
		}
		if captured[a.AuthorizationID] != a.CapturedAmount || count[a.AuthorizationID] != len(a.PaymentIDs) {
			return fmt.Errorf("%s: captured_amount %d / %d ids disagree with payments %d / %d",
				a.AuthorizationID, a.CapturedAmount, len(a.PaymentIDs), captured[a.AuthorizationID], count[a.AuthorizationID])
		}
	}
	return nil
}

func TestAuthzEffectiveExpiry(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	exp := azT0.Add(time.Hour)
	mk := func(id, status string, expires time.Time, amount, captured int64) *Authorization {
		a := &Authorization{AuthorizationID: id, FromUserID: "u_ada", ToUserID: "u_bob", Amount: amount,
			CapturedAmount: captured, Status: status, ExpiresAt: FormatTime(expires)}
		azRelease(a)
		return a
	}
	st.Authorizations = []*Authorization{
		mk("a_future", "open", exp, 2000, 0),
		mk("a_past", "open", azT0.Add(-time.Hour), 4000, 0),
		mk("a_voided", "voided", exp, 500, 0),
		mk("a_captured", "captured", exp, 700, 700),
		mk("a_expired", "expired", exp, 300, 0),
		mk("a_partial", "open", exp, 1000, 400),
	}
	if err := st.ReindexAt(azT0); err != nil {
		t.Fatal(err)
	}
	type row struct {
		now    time.Time
		status map[string]string
		held   int64
	}
	before := map[string]string{"a_future": "open", "a_past": "expired", "a_voided": "voided", "a_captured": "captured", "a_expired": "expired", "a_partial": "open"}
	after := map[string]string{"a_future": "expired", "a_past": "expired", "a_voided": "voided", "a_captured": "captured", "a_expired": "expired", "a_partial": "expired"}
	for _, r := range []row{
		{azT0, before, 2000 + 600},
		{exp.Add(-time.Nanosecond), before, 2000 + 600},
		{exp.Add(-time.Millisecond), before, 2000 + 600},
		{exp, after, 0},
		{exp.Add(time.Nanosecond), after, 0},
		{exp.Add(24 * time.Hour), after, 0},
	} {
		for _, a := range st.Authorizations {
			if got := a.StatusAt(r.now); got != r.status[a.AuthorizationID] {
				t.Errorf("%s at %s: %s, want %s", a.AuthorizationID, r.now.Format(time.RFC3339Nano), got, r.status[a.AuthorizationID])
			}
			if rem := a.RemainingAt(r.now); (a.StatusAt(r.now) != "open" && rem != 0) || (a.StatusAt(r.now) == "open" && rem != a.Amount-a.CapturedAmount) {
				t.Errorf("%s: remaining %d with status %s", a.AuthorizationID, rem, a.StatusAt(r.now))
			}
		}
		if h := st.Held("u_ada", r.now); h != r.held {
			t.Errorf("held at %s = %d, want %d", r.now.Format(time.RFC3339Nano), h, r.held)
		}
	}
	if st.Authorizations[0].Status != "open" || st.Authorizations[1].Status != "open" {
		t.Fatal("the clock must never mutate the stored status")
	}
	// me and the listing reflect expiry with no request at the deadline
	if m := st.Me("u_ada", exp).(meBody); m.Held != 0 || m.Available != 10000 {
		t.Fatalf("%+v", m)
	}
	ids, _ := azList(t, st, "ada", "", "expired", 50, 0, exp)
	if len(ids) != 4 {
		t.Fatalf("expired list %v", ids)
	}
	if ids, _ := azList(t, st, "ada", "", "open", 50, 0, exp); len(ids) != 0 {
		t.Fatalf("open list %v", ids)
	}
}

func TestAuthzTTLBoundary(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	if st.TTL() != 600 {
		t.Fatal("unset ttl must read as 600")
	}
	d := azAuthorize(t, st, "ada", "bob", 100, azT0)
	if d.CreatedAt != "2026-09-24T13:10:00+00:00" || d.ExpiresAt != "2026-09-24T13:20:00+00:00" {
		t.Fatalf("%+v", d)
	}
	st.AuthTTLSeconds = 2
	if st.TTL() != 2 {
		t.Fatal(st.TTL())
	}
	created := azT0.Add(400 * time.Millisecond)
	b := azAuthorize(t, st, "ada", "bob", 100, created)
	b2 := azAuthorize(t, st, "ada", "bob", 100, created)
	if b.CreatedAt != FormatTime(azT0) || b.ExpiresAt != FormatTime(azT0.Add(2*time.Second)) {
		t.Fatalf("expires_at must be created_at + ttl: %+v", b)
	}
	deadline := azT0.Add(2 * time.Second)
	held := func(now time.Time) int64 { return st.Held("u_ada", now) }
	if held(deadline.Add(-time.Nanosecond)) != 300 || held(deadline) != 100 { // the 600 s one stays
		t.Fatalf("held around the deadline: %d / %d", held(deadline.Add(-time.Nanosecond)), held(deadline))
	}
	// writes never run backwards in time, so the last instant before the deadline is used first
	azMustCapture(t, st, "bob", b2.AuthorizationID, nil, true, deadline.Add(-time.Microsecond))
	if _, e := azCapture(st, "bob", b.AuthorizationID, nil, true, deadline); e == nil || e.Code != "authorization_expired" {
		t.Fatal(e)
	}
}

func TestAuthzAuthorize(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	for _, c := range []struct {
		name, to string
		amt      int64
		status   int
		code     string
	}{
		{"unknown payee beats funds", "ghost", 99999999, 404, "not_found"},
		{"self beats funds", "ada", 99999999, 422, "self_payment"},
		{"over balance", "bob", 10001, 409, "insufficient_funds"},
	} {
		b, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: c.to, Amount: c.amt, Visibility: visPublic}, azT0)
		if b != nil {
			t.Fatal("body with error")
		}
		fgWantErr(t, c.name, e, c.status, c.code)
	}
	if len(st.Authorizations) != 0 || len(st.Payments) != 0 || st.Seq["a"] != 0 {
		t.Fatal("failed authorize left a trace")
	}
	b := azAuthorize(t, st, "ada", "bob", 2000, azT0)
	m := azJSON(t, b)
	want := map[string]any{
		"authorization_id": "a_1", "from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob",
		"amount": 2000.0, "captured_amount": 0.0, "remaining_amount": 2000.0, "currency": "EUR", "note": "deposit",
		"visibility": "private", "status": "open", "expires_at": "2026-09-24T13:20:00+00:00", "payment_id": nil,
		"payment_ids": []any{}, "created_at": "2026-09-24T13:10:00+00:00", "closed_at": nil,
	}
	if len(m) != len(want) {
		t.Fatalf("field set: %v", m)
	}
	for k, v := range want {
		if fmt.Sprint(m[k]) != fmt.Sprint(v) {
			t.Errorf("%s = %v, want %v", k, m[k], v)
		}
	}
	if len(st.Payments) != 0 || azBal(st, "ada") != 10000 || azBal(st, "bob") != 0 {
		t.Fatal("a hold must not move money")
	}
	if pg := st.Activity("u_ada", 50, 0).(paymentPage); len(pg.Payments) != 0 {
		t.Fatal("an authorization is not a feed item")
	}
	if me := st.Me("u_ada", azT0).(meBody); me.Held != 2000 || me.Available != 8000 || me.Balance != 10000 || me.Total != 10000 {
		t.Fatalf("%+v", me)
	}
	// the available boundary: 8000 left
	_, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 8001, Visibility: visPublic}, azT0)
	fgWantErr(t, "one over available", e, 409, "insufficient_funds")
	if _, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 8000, Visibility: visPublic}, azT0); e != nil {
		t.Fatal(e)
	}
	if azAvail(st, "ada", azT0) != 0 {
		t.Fatal("available must be exactly zero")
	}
}

func TestAuthzCaptureRules(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	a := azAuthorize(t, st, "ada", "bob", 2000, azT0)
	id := a.AuthorizationID
	now := azT0.Add(time.Minute)

	_, e := azCapture(st, "bob", "a_nope", nil, true, now)
	fgWantErr(t, "unknown", e, 404, "not_found")
	for _, who := range []string{"ada", "cy"} {
		_, e = azCapture(st, who, id, nil, true, now)
		fgWantErr(t, who+" is not the receiver", e, 403, "forbidden")
	}
	_, e = azCapture(st, "bob", id, azI64(2001), true, now)
	fgWantErr(t, "above remaining", e, 422, "capture_exceeds_authorization")
	if len(st.Payments) != 0 || st.Authorizations[0].CapturedAmount != 0 {
		t.Fatal("refused capture left a trace")
	}

	p := azMustCapture(t, st, "bob", id, azI64(1500), true, now)
	m := azJSON(t, p)
	if m["authorization_id"] != id || m["request_id"] != nil || m["settlement_id"] != nil || m["amount"] != 1500.0 ||
		m["note"] != "deposit" || m["visibility"] != "private" || m["from_handle"] != "ada" || m["to_handle"] != "bob" ||
		m["currency"] != "EUR" || !strings.HasPrefix(m["created_at"].(string), "2026-09-24T13:11:00.0000") {
		t.Fatalf("%v", m)
	}
	if body := azJSON(t, st.authBody(st.Authorizations[0], now)); body["closed_at"] != p.CreatedAt {
		t.Fatalf("a final capture closes the hold at the capture's created_at: %v", body)
	}
	if azBal(st, "ada") != 8500 || azBal(st, "bob") != 1500 {
		t.Fatal("balances")
	}
	if got := azAvail(st, "ada", now); got != 8500 {
		t.Fatalf("a final capture releases the remainder at once: available %d", got)
	}
	body := azJSON(t, st.authBody(st.Authorizations[0], now))
	if body["status"] != "captured" || body["captured_amount"] != 1500.0 || body["remaining_amount"] != 0.0 || body["payment_id"] != p.PaymentID {
		t.Fatalf("%v", body)
	}
	if pg := st.Activity("u_cy", 50, 0).(paymentPage); len(pg.Payments) != 0 {
		t.Fatal("a private capture must not be visible to a stranger")
	}
	_, e = azCapture(st, "bob", id, azI64(1), true, now)
	fgWantErr(t, "second capture after a final one", e, 409, "authorization_not_open")
	_, e = azCapture(st, "bob", id, nil, true, now)
	fgWantErr(t, "default amount on a closed one", e, 409, "authorization_not_open")
	azInvariants(t, st, 10000, now)

	// public authorizations produce public payments
	pub, _ := st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 100, Visibility: visPublic}, now)
	pp := azMustCapture(t, st, "bob", pub.AuthorizationID, nil, true, now)
	if pp.Visibility != visPublic || pp.Amount != 100 || pp.Note != "" {
		t.Fatalf("%+v", pp)
	}
	if pg := st.Activity("u_cy", 50, 0).(paymentPage); len(pg.Payments) != 1 {
		t.Fatal("public capture visible to everyone")
	}
}

func TestAuthzCapturePrecedence(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	exp := azT0.Add(time.Hour)
	st.Authorizations = []*Authorization{
		{AuthorizationID: "a_void", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 100, Status: "voided", ExpiresAt: FormatTime(exp)},
		{AuthorizationID: "a_stored_exp", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 100, Status: "expired", ExpiresAt: FormatTime(exp)},
		{AuthorizationID: "a_capd_old", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 100, CapturedAmount: 40, Status: "captured", ExpiresAt: FormatTime(azT0.Add(-time.Hour))},
		{AuthorizationID: "a_open_old", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 100, Status: "open", ExpiresAt: FormatTime(azT0.Add(-time.Hour))},
		{AuthorizationID: "a_open", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 100, Status: "open", ExpiresAt: FormatTime(exp)},
	}
	for _, a := range st.Authorizations {
		azRelease(a)
	}
	if err := st.ReindexAt(azT0); err != nil {
		t.Fatal(err)
	}
	type row struct {
		id, who string
		amt     *int64
		status  int
		code    string
	}
	for _, r := range []row{
		{"a_void", "cy", nil, 403, "forbidden"},
		{"a_void", "ada", nil, 403, "forbidden"},
		{"a_void", "bob", nil, 409, "authorization_not_open"},
		{"a_stored_exp", "bob", nil, 409, "authorization_expired"},
		{"a_capd_old", "bob", nil, 409, "authorization_not_open"}, // stored status first
		{"a_open_old", "bob", nil, 409, "authorization_expired"},
		{"a_open_old", "bob", azI64(5000), 409, "authorization_expired"}, // state before amount
		{"a_open_old", "cy", nil, 403, "forbidden"},
		{"a_open", "bob", azI64(101), 422, "capture_exceeds_authorization"},
	} {
		_, e := azCapture(st, r.who, r.id, r.amt, true, azT0)
		fgWantErr(t, fmt.Sprintf("%s by %s", r.id, r.who), e, r.status, r.code)
	}
	if len(st.Payments) != 0 {
		t.Fatal("refused captures moved money")
	}
}

func TestAuthzExtendedCapture(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	id := azAuthorize(t, st, "ada", "bob", 2000, azT0).AuthorizationID
	now := azT0.Add(time.Second)
	p1 := azMustCapture(t, st, "bob", id, azI64(700), false, now)
	a := st.authBody(st.Authorizations[0], now)
	if a.Status != "open" || a.CapturedAmount != 700 || a.RemainingAmount != 1300 || *a.PaymentID != p1.PaymentID || !slices.Equal(a.PaymentIDs, []string{p1.PaymentID}) {
		t.Fatalf("%+v", a)
	}
	if azAvail(st, "ada", now) != 10000-700-1300 || st.Held("u_ada", now) != 1300 {
		t.Fatal("the remainder must stay held after a non-final capture")
	}
	_, e := azCapture(st, "bob", id, azI64(1301), false, now)
	fgWantErr(t, "exceeds the remaining amount, not the original", e, 422, "capture_exceeds_authorization")
	_, e = azCapture(st, "bob", id, azI64(2000), true, now)
	fgWantErr(t, "original amount no longer fits", e, 422, "capture_exceeds_authorization")
	p2 := azMustCapture(t, st, "bob", id, azI64(300), false, now.Add(time.Second))
	p3 := azMustCapture(t, st, "bob", id, nil, false, now.Add(2*time.Second)) // the whole remainder closes it even with final:false
	a = st.authBody(st.Authorizations[0], now)
	if a.Status != "captured" || a.CapturedAmount != 2000 || a.RemainingAmount != 0 || *a.PaymentID != p3.PaymentID ||
		!slices.Equal(a.PaymentIDs, []string{p1.PaymentID, p2.PaymentID, p3.PaymentID}) || p3.Amount != 1000 {
		t.Fatalf("%+v", a)
	}
	_, e = azCapture(st, "bob", id, azI64(1), false, now)
	fgWantErr(t, "closed", e, 409, "authorization_not_open")
	if azBal(st, "ada") != 8000 || azBal(st, "bob") != 2000 {
		t.Fatal("balances")
	}

	// non-final then final: the final capture releases what is left
	id2 := azAuthorize(t, st, "ada", "bob", 3000, now).AuthorizationID
	azMustCapture(t, st, "bob", id2, azI64(1000), false, now)
	if azAvail(st, "ada", now) != 8000-1000-2000 {
		t.Fatal("hold", azAvail(st, "ada", now))
	}
	azMustCapture(t, st, "bob", id2, azI64(500), true, now)
	b := st.authBody(st.Authorizations[1], now)
	if b.Status != "captured" || b.CapturedAmount != 1500 || b.RemainingAmount != 0 || len(b.PaymentIDs) != 2 {
		t.Fatalf("%+v", b)
	}
	if azAvail(st, "ada", now) != 8000-1500 {
		t.Fatalf("final capture releases the uncaptured remainder: %d", azAvail(st, "ada", now))
	}
	azInvariants(t, st, 10000, now)
}

func TestAuthzVoid(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0}, fgU{"cy", 0})
	id := azAuthorize(t, st, "ada", "bob", 2000, azT0).AuthorizationID
	now := azT0.Add(time.Second)

	_, e := st.Void("u_ada", "a_nope", now)
	fgWantErr(t, "unknown", e, 404, "not_found")
	for _, who := range []string{"bob", "cy"} {
		_, e = st.Void("u_"+who, id, now)
		fgWantErr(t, who+" voiding", e, 403, "forbidden")
	}
	if st.Held("u_ada", now) != 2000 {
		t.Fatal("refused void released the hold")
	}
	b, e := st.Void("u_ada", id, now)
	if e != nil || b.Status != "voided" || b.RemainingAmount != 0 || b.CapturedAmount != 0 || st.Held("u_ada", now) != 0 {
		t.Fatalf("%+v %v", b, e)
	}
	if b2, e := st.Void("u_ada", id, now); e != nil || b2.Status != "voided" || b2.ClosedAt == nil || *b2.ClosedAt != *b.ClosedAt {
		t.Fatalf("void twice must be 200 with the current state: %+v %v", b2, e)
	}
	_, e = azCapture(st, "bob", id, nil, true, now)
	fgWantErr(t, "capture after void", e, 409, "authorization_not_open")

	// void after a partial capture releases only the remainder and keeps the captures
	id2 := azAuthorize(t, st, "ada", "bob", 3000, now).AuthorizationID
	p := azMustCapture(t, st, "bob", id2, azI64(1000), false, now)
	v, e := st.Void("u_ada", id2, now)
	if e != nil || v.Status != "voided" || v.CapturedAmount != 1000 || v.RemainingAmount != 0 || !slices.Equal(v.PaymentIDs, []string{p.PaymentID}) || *v.PaymentID != p.PaymentID {
		t.Fatalf("%+v %v", v, e)
	}
	if azBal(st, "ada") != 9000 || azAvail(st, "ada", now) != 9000 {
		t.Fatal("only the remainder is released")
	}

	// captured and clock-expired authorizations cannot be voided
	id3 := azAuthorize(t, st, "ada", "bob", 100, now).AuthorizationID
	azMustCapture(t, st, "bob", id3, nil, true, now)
	_, e = st.Void("u_ada", id3, now)
	fgWantErr(t, "void captured", e, 409, "authorization_not_open")
	id4 := azAuthorize(t, st, "ada", "bob", 100, now).AuthorizationID
	_, e = st.Void("u_ada", id4, now.Add(601*time.Second))
	fgWantErr(t, "void clock-expired", e, 409, "authorization_not_open")
	if st.Authorizations[3].Status != "open" {
		t.Fatal("a refused void must leave the stored status alone")
	}
	st.Authorizations[3].Status = "expired" // stored expired
	_, e = st.Void("u_ada", id4, now)
	fgWantErr(t, "void stored-expired", e, 409, "authorization_not_open")
	azInvariants(t, st, 10000, now)
}

func TestAuthzHeldFundsCannotFundNewPayments(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 500}, fgU{"cy", 0})
	now := azT0
	id := azAuthorize(t, st, "ada", "cy", 8000, now).AuthorizationID

	if _, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 2001, Visibility: visPublic}, now); e == nil || e.Code != "insufficient_funds" {
		t.Fatal("held funds funded a payment", e)
	}
	r, _ := st.CreateRequest("u_bob", RequestIn{PayerHandle: "ada", Amount: 2001}, now)
	if _, e := st.PayRequest("u_ada", r.RequestID, PayIn{Visibility: visPublic}, now); e == nil || e.Code != "insufficient_funds" {
		t.Fatal("held funds funded a request payment", e)
	}
	if r.Status != "pending" {
		t.Fatal("refused request payment changed the request")
	}
	if _, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: "bob", Amount: 2001, Visibility: visPublic}, now); e == nil || e.Code != "insufficient_funds" {
		t.Fatal("held funds funded a second hold", e)
	}
	if _, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 2000, Visibility: visPublic}, now); e != nil {
		t.Fatal(e)
	}
	if _, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 1, Visibility: visPublic}, now); e == nil {
		t.Fatal("paid beyond available")
	}
	// the capture spends exactly the reserved money, though available is zero
	if azAvail(st, "ada", now) != 0 {
		t.Fatal(azAvail(st, "ada", now))
	}
	azMustCapture(t, st, "cy", id, nil, true, now)
	if azBal(st, "ada") != 0 || azBal(st, "cy") != 8000 || azBal(st, "bob") != 2500 {
		t.Fatal("balances after capture")
	}
	azInvariants(t, st, 10500, now)

	// after expiry the released remainder is spendable again
	_, st2 := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	id2 := azAuthorize(t, st2, "ada", "bob", 4000, azT0).AuthorizationID
	azMustCapture(t, st2, "bob", id2, azI64(1000), false, azT0)
	later := azT0.Add(601 * time.Second)
	if _, e := st2.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 9000, Visibility: visPublic}, azT0); e == nil {
		t.Fatal("spent held money before expiry")
	}
	if _, e := st2.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 9000, Visibility: visPublic}, later); e != nil {
		t.Fatalf("remainder not released by expiry: %v", e)
	}
	b := st2.authBody(st2.Authorizations[0], later)
	if b.Status != "expired" || b.CapturedAmount != 1000 || len(b.PaymentIDs) != 1 || b.RemainingAmount != 0 {
		t.Fatalf("expiry keeps capture records: %+v", b)
	}
}

func TestAuthzList(t *testing.T) {
	_, st := azStore(fgU{"ada", 100000}, fgU{"bob", 100000}, fgU{"cy", 100000})
	st.AuthTTLSeconds = 60
	var ids []string
	for i, c := range [][2]string{{"ada", "bob"}, {"bob", "ada"}, {"ada", "cy"}, {"cy", "bob"}, {"ada", "bob"}, {"bob", "ada"}} {
		ids = append(ids, azAuthorize(t, st, c[0], c[1], int64(100*(i+1)), azT0.Add(time.Duration(i)*time.Second)).AuthorizationID)
	}
	now := azT0.Add(10 * time.Second)
	if _, e := st.Void("u_ada", ids[0], now); e != nil {
		t.Fatal(e)
	}
	azMustCapture(t, st, "ada", ids[1], nil, true, now)
	// a1 voided, a2 captured, a3 a4 a5 a6 open; a4 (cy->bob) is not ada's

	if got, more := azList(t, st, "ada", "", "", 50, 0, now); !slices.Equal(got, []string{ids[5], ids[4], ids[2], ids[1], ids[0]}) || more {
		t.Fatalf("ada all: %v %v", got, more)
	}
	if got, _ := azList(t, st, "ada", "outgoing", "", 50, 0, now); !slices.Equal(got, []string{ids[4], ids[2], ids[0]}) {
		t.Fatalf("ada outgoing: %v", got)
	}
	if got, _ := azList(t, st, "ada", "incoming", "", 50, 0, now); !slices.Equal(got, []string{ids[5], ids[1]}) {
		t.Fatalf("ada incoming: %v", got)
	}
	if got, _ := azList(t, st, "ada", "", "open", 50, 0, now); !slices.Equal(got, []string{ids[5], ids[4], ids[2]}) {
		t.Fatalf("ada open: %v", got)
	}
	if got, _ := azList(t, st, "ada", "outgoing", "voided", 50, 0, now); !slices.Equal(got, []string{ids[0]}) {
		t.Fatalf("ada outgoing voided: %v", got)
	}
	if got, _ := azList(t, st, "ada", "", "captured", 50, 0, now); !slices.Equal(got, []string{ids[1]}) {
		t.Fatalf("ada captured: %v", got)
	}
	if got, _ := azList(t, st, "cy", "", "", 50, 0, now); !slices.Equal(got, []string{ids[3], ids[2]}) {
		t.Fatalf("cy: %v", got)
	}
	// paging and has_more, exactly like requests
	got, more := azList(t, st, "ada", "", "", 2, 0, now)
	if !slices.Equal(got, []string{ids[5], ids[4]}) || !more {
		t.Fatalf("page 1: %v %v", got, more)
	}
	got, more = azList(t, st, "ada", "", "", 2, 2, now)
	if !slices.Equal(got, []string{ids[2], ids[1]}) || !more {
		t.Fatalf("page 2: %v %v", got, more)
	}
	got, more = azList(t, st, "ada", "", "", 2, 4, now)
	if !slices.Equal(got, []string{ids[0]}) || more {
		t.Fatalf("page 3: %v %v", got, more)
	}
	if got, more = azList(t, st, "ada", "", "", 5, 0, now); len(got) != 5 || more {
		t.Fatalf("exact fit must not report more: %v %v", got, more)
	}
	if got, more = azList(t, st, "ada", "", "", 2, 99, now); len(got) != 0 || more {
		t.Fatalf("past the end: %v %v", got, more)
	}
	// a clock-expired hold matches expired and never open
	late := azT0.Add(66 * time.Second) // a1..a6 created at +0..+5 s with a 60 s lifetime
	if got, _ := azList(t, st, "ada", "", "open", 50, 0, late); len(got) != 0 {
		t.Fatalf("expired by the clock must not match open: %v", got)
	}
	if got, _ := azList(t, st, "ada", "", "expired", 50, 0, late); !slices.Equal(got, []string{ids[5], ids[4], ids[2]}) {
		t.Fatalf("expired: %v", got)
	}
	for _, bad := range [][2]string{{"sideways", ""}, {"", "pending"}, {"", "Open"}, {emptyParam, ""}, {"", emptyParam}} {
		_, e := st.ListAuthorizations("u_ada", bad[0], bad[1], 50, 0, now)
		fgWantErr(t, fmt.Sprint(bad), e, 422, "validation_failed")
	}
	if _, e := st.ListAuthorizations("u_nobody", "", "", 50, 0, now); e == nil || e.Status != 401 {
		t.Fatal(e)
	}
	empty := mustJSON(st.mustList("u_cy", "outgoing", "voided", now))
	if string(empty) != `{"authorizations":[],"has_more":false}` {
		t.Fatalf("%s", empty)
	}
}

func (st *State) mustList(caller, dir, status string, now time.Time) any {
	v, e := st.ListAuthorizations(caller, dir, status, 50, 0, now)
	if e != nil {
		panic(e)
	}
	return v
}

func TestAuthzMe(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	m := azJSON(t, st.Me("u_ada", azT0))
	want := map[string]any{"user_id": "u_ada", "display_name": "ada", "handle": "ada", "balance": 10000.0, "total": 10000.0,
		"available": 10000.0, "held": 0.0, "currency": "EUR", "minor_units": 2.0}
	if fmt.Sprint(m) != fmt.Sprint(want) {
		t.Fatalf("%v", m)
	}
	azAuthorize(t, st, "ada", "bob", 2000, azT0)
	m = azJSON(t, st.Me("u_ada", azT0))
	if m["balance"] != 10000.0 || m["total"] != 10000.0 || m["available"] != 8000.0 || m["held"] != 2000.0 {
		t.Fatalf("%v", m)
	}
	if m = azJSON(t, st.Me("u_bob", azT0)); m["held"] != 0.0 || m["available"] != 0.0 {
		t.Fatalf("a receiver holds nothing: %v", m)
	}
	if m = azJSON(t, st.Me("u_ada", azT0.Add(10*time.Minute))); m["held"] != 0.0 || m["available"] != 10000.0 {
		t.Fatalf("expiry released the hold: %v", m)
	}
}

func TestAuthzPaymentJSONHasAuthorizationID(t *testing.T) {
	_, st := azStore(fgU{"ada", 1000}, fgU{"bob", 0})
	p, _ := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 10, Visibility: visPublic}, azT0)
	m := azJSON(t, p)
	if v, has := m["authorization_id"]; !has || v != nil {
		t.Fatalf("authorization_id must always be present and null for a plain payment: %v", m)
	}
}

func TestAuthzReindex(t *testing.T) {
	_, st := azStore(fgU{"ada", 5000}, fgU{"bob", 0})
	azAuthorize(t, st, "ada", "bob", 2000, azT0)
	azMustCapture(t, st, "bob", "a_1", azI64(500), false, azT0)
	st.AuthTTLSeconds = 90
	raw, err := json.Marshal(st)
	if err != nil {
		t.Fatal(err)
	}
	var back State
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatal(err)
	}
	if err := back.ReindexAt(azT0); err != nil {
		t.Fatal(err)
	}
	if raw2, _ := json.Marshal(&back); string(raw) != string(raw2) {
		t.Fatalf("round trip differs:\n%s\n%s", raw, raw2)
	}
	if back.TTL() != 90 || back.NewID("a") != "a_2" || back.Held("u_ada", azT0) != 1500 || back.NewID("p") != "p_2" {
		t.Fatal("ttl, counters or holds not restored")
	}
	// a stage-1 export has no authorizations and no ttl
	var old State
	if err := json.Unmarshal([]byte(`{"currency":"EUR","minor_units":2,"users":[{"id":"u_1","handle":"ada","balance":5,"opening_balance":5}]}`), &old); err != nil {
		t.Fatal(err)
	}
	if err := old.Reindex(); err != nil || old.Authorizations == nil || old.TTL() != 600 {
		t.Fatal(err, old.TTL())
	}
	if s := string(mustJSON(old.Authorizations)); s != "[]" {
		t.Fatal(s)
	}

	mutate := map[string]func(st *State){
		"duplicate id": func(st *State) {
			dup := *st.Authorizations[0]
			st.Authorizations = append(st.Authorizations, &dup)
		},
		"empty id":          func(st *State) { st.Authorizations[0].AuthorizationID = "" },
		"null entry":        func(st *State) { st.Authorizations[0] = nil },
		"unknown payer":     func(st *State) { st.Authorizations[0].FromUserID = "u_none" },
		"unknown receiver":  func(st *State) { st.Authorizations[0].ToUserID = "u_none" },
		"zero amount":       func(st *State) { st.Authorizations[0].Amount = 0 },
		"negative captured": func(st *State) { st.Authorizations[0].CapturedAmount = -1 },
		"captured > amount": func(st *State) { st.Authorizations[0].CapturedAmount = 2001 },
		"bad status":        func(st *State) { st.Authorizations[0].Status = "pending" },
		"bad visibility":    func(st *State) { st.Authorizations[0].Visibility = "friends" },
		"bad expires_at":    func(st *State) { st.Authorizations[0].ExpiresAt = "tomorrow" },
		"missing expiry":    func(st *State) { st.Authorizations[0].ExpiresAt = "" },
		"dangling payment":  func(st *State) { st.Authorizations[0].PaymentIDs = []string{"p_none"} },
		"hold > balance":    func(st *State) { st.Users[0].Balance = 1499 },
		"ttl negative":      func(st *State) { st.AuthTTLSeconds = -1 },
		"ttl too large":     func(st *State) { st.AuthTTLSeconds = 1_000_000_001 },
		"two holds overdraw": func(st *State) {
			dup := *st.Authorizations[0]
			dup.AuthorizationID = "a_x"
			dup.Amount, dup.CapturedAmount = 3600, 0
			st.Authorizations = append(st.Authorizations, &dup)
		},
	}
	for name, mut := range mutate {
		var c State
		if err := json.Unmarshal(raw, &c); err != nil {
			t.Fatal(err)
		}
		mut(&c)
		if err := c.ReindexAt(azT0); err == nil {
			t.Errorf("%s: ReindexAt accepted an invalid state", name)
		}
	}
	// holds that no longer hold funds do not count: expired, voided, captured
	for name, mut := range map[string]func(st *State){
		"expired by the clock": func(st *State) { azEmpty(st.Users[0]) },
		"voided": func(st *State) {
			azEmpty(st.Users[0])
			st.Authorizations[0].Status = "voided"
			azRelease(st.Authorizations[0])
		},
		"captured": func(st *State) {
			azEmpty(st.Users[0])
			st.Authorizations[0].Status = "captured"
			azRelease(st.Authorizations[0])
		},
	} {
		var c State
		_ = json.Unmarshal(raw, &c)
		mut(&c)
		at := azT0
		if name == "expired by the clock" {
			at = azT0.Add(time.Hour)
		}
		if err := c.ReindexAt(at); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	// defaults for seeded rows
	var d State
	_ = json.Unmarshal([]byte(`{"currency":"EUR","minor_units":2,"users":[{"id":"u_1","handle":"ada","balance":500,"opening_balance":500},{"id":"u_2","handle":"bob"}],
		"authorizations":[{"authorization_id":"a_1","from_user_id":"u_1","to_user_id":"u_2","amount":200,"expires_at":"2026-09-24T14:20:00+00:00"}]}`), &d)
	if err := d.ReindexAt(azT0); err != nil {
		t.Fatal(err)
	}
	a := d.Authorizations[0]
	if a.Status != "open" || a.Visibility != "public" || a.CreatedAt != FormatTime(azT0) || a.PaymentIDs == nil || a.Note != "" || d.NewID("a") != "a_2" {
		t.Fatalf("%+v", a)
	}
}

func TestAuthzOptValidators(t *testing.T) {
	for _, c := range []struct {
		body string
		want int64 // 0 = nil
		code string
	}{
		{`{}`, 0, ""}, {`{"amount":1500}`, 1500, ""}, {`{"amount":1e3}`, 1000, ""}, {`{"amount":1000000000}`, 1000000000, ""},
		{`{"amount":null}`, 0, "validation_failed"}, {`{"amount":"5"}`, 0, "validation_failed"}, {`{"amount":true}`, 0, "validation_failed"},
		{`{"amount":1.5}`, 0, "validation_failed"}, {`{"amount":0}`, 0, "validation_failed"}, {`{"amount":-3}`, 0, "validation_failed"},
		{`{"amount":1000000001}`, 0, "validation_failed"}, {`{"amount":[1]}`, 0, "validation_failed"},
	} {
		got, e := OptCaptureAmount(fgObj(t, c.body))
		if c.code != "" {
			fgWantErr(t, c.body, e, 422, c.code)
			continue
		}
		if e != nil || (c.want == 0) != (got == nil) || (got != nil && *got != c.want) {
			t.Errorf("%s: %v %v", c.body, got, e)
		}
	}
	for _, c := range []struct {
		body string
		want bool
		bad  bool
	}{{`{}`, true, false}, {`{"final":true}`, true, false}, {`{"final":false}`, false, false},
		{`{"final":"false"}`, false, true}, {`{"final":0}`, false, true}, {`{"final":null}`, false, true}, {`{"final":[]}`, false, true}} {
		got, e := OptFinal(fgObj(t, c.body))
		if c.bad {
			fgWantErr(t, c.body, e, 400, "malformed_request")
		} else if e != nil || got != c.want {
			t.Errorf("%s: %v %v", c.body, got, e)
		}
	}
}

// Fifty captures race for one authorization: only what fits succeeds and each success moved money once.
func TestAuthzCaptureRace(t *testing.T) {
	s := fgStore(fgU{"ada", 10000}, fgU{"bob", 0})
	var id string
	s.Exec(func(st *State) (any, *AppError) {
		b := azAuthorize(t, st, "ada", "bob", 2000, time.Now())
		id = b.AuthorizationID
		return b, nil
	})
	var wg sync.WaitGroup
	var mu sync.Mutex
	var oks int
	var sum int64
	codes := map[string]int{}
	start := make(chan struct{})
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			amt := int64(100)
			<-start
			var moved int64
			_, e := s.Exec(func(st *State) (any, *AppError) {
				p, e := st.Capture("u_bob", id, CaptureIn{Amount: &amt, Final: false}, time.Now())
				if e != nil {
					return nil, e
				}
				moved = p.Amount
				return p, nil
			})
			mu.Lock()
			defer mu.Unlock()
			if e == nil {
				oks++
				sum += moved
			} else {
				codes[e.Code]++
			}
		}(i)
	}
	close(start)
	wg.Wait()
	if oks != 20 || sum != 2000 || codes["authorization_not_open"] != 30 || len(codes) != 1 {
		t.Fatalf("ok=%d sum=%d codes=%v", oks, sum, codes)
	}
	if azBal(s.st, "ada") != 8000 || azBal(s.st, "bob") != 2000 || s.st.Authorizations[0].CapturedAmount != 2000 || len(s.st.Authorizations[0].PaymentIDs) != 20 {
		t.Fatal("state after race")
	}
	azInvariants(t, s.st, 10000, time.Now())
}

// Fifty captures of random sizes, some final: whatever wins moved exactly captured_amount, never above amount.
func TestAuthzFinalCaptureRaceMixedAmounts(t *testing.T) {
	for round := 0; round < 20; round++ {
		s := fgStore(fgU{"ada", 10000}, fgU{"bob", 0})
		var id string
		s.Exec(func(st *State) (any, *AppError) {
			b := azAuthorize(t, st, "ada", "bob", 2000, time.Now())
			id = b.AuthorizationID
			return b, nil
		})
		var wg sync.WaitGroup
		var mu sync.Mutex
		var sum int64
		start := make(chan struct{})
		rng := rand.New(rand.NewSource(int64(round)))
		for i := 0; i < 50; i++ {
			amt := int64(1 + rng.Intn(400))
			final := rng.Intn(5) == 0
			wg.Add(1)
			go func() {
				defer wg.Done()
				<-start
				var moved int64
				_, e := s.Exec(func(st *State) (any, *AppError) {
					p, e := st.Capture("u_bob", id, CaptureIn{Amount: &amt, Final: final}, time.Now())
					if e != nil {
						return nil, e
					}
					moved = p.Amount
					return p, nil
				})
				if e != nil && e.Status >= 500 {
					t.Error(e)
				}
				mu.Lock()
				sum += moved
				mu.Unlock()
			}()
		}
		close(start)
		wg.Wait()
		a := s.st.Authorizations[0]
		if sum != a.CapturedAmount || sum > 2000 || azBal(s.st, "bob") != sum {
			t.Fatalf("round %d: moved %d, captured %d", round, sum, a.CapturedAmount)
		}
		azInvariants(t, s.st, 10000, time.Now())
	}
}

// Pays and authorizations race at the available boundary: never overspend, observers never see a bad state.
func TestAuthzAuthorizePayRace(t *testing.T) {
	s := fgStore(fgU{"ada", 1000}, fgU{"bob", 0}, fgU{"cy", 0})
	stop := make(chan struct{})
	var obs sync.WaitGroup
	obs.Add(1)
	go func() {
		defer obs.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			s.mu.Lock()
			err := azCheck(s.st, 1000, time.Now())
			s.mu.Unlock()
			if err != nil {
				t.Error(err)
				return
			}
		}
	}()
	var wg sync.WaitGroup
	var mu sync.Mutex
	var payOK, authOK int
	start := make(chan struct{})
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			if i%2 == 0 {
				_, e := s.Exec(func(st *State) (any, *AppError) {
					p, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 100, Visibility: visPublic}, time.Now())
					if e != nil {
						return nil, e
					}
					return p, nil
				})
				mu.Lock()
				defer mu.Unlock()
				if e == nil {
					payOK++
				} else if e.Code != "insufficient_funds" {
					t.Error(e)
				}
				return
			}
			_, e := s.Exec(func(st *State) (any, *AppError) {
				b, e := st.Authorize("u_ada", AuthorizeIn{ToHandle: "cy", Amount: 100, Visibility: visPublic}, time.Now())
				if e != nil {
					return nil, e
				}
				return b, nil
			})
			mu.Lock()
			defer mu.Unlock()
			if e == nil {
				authOK++
			} else if e.Code != "insufficient_funds" {
				t.Error(e)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	close(stop)
	obs.Wait()
	if payOK+authOK != 10 {
		t.Fatalf("pay %d + authorize %d must exactly use the 1000 available", payOK, authOK)
	}
	if azAvail(s.st, "ada", time.Now()) != 0 || azBal(s.st, "ada") != int64(1000-100*payOK) || s.st.Held("u_ada", time.Now()) != int64(100*authOK) {
		t.Fatal("final state")
	}
	// every reserved hundred can still be captured: holds guarantee the money
	for _, a := range append([]*Authorization(nil), s.st.Authorizations...) {
		if _, e := s.Exec(func(st *State) (any, *AppError) {
			p, e := st.Capture("u_cy", a.AuthorizationID, CaptureIn{Final: true}, time.Now())
			if e != nil {
				return nil, e
			}
			return p, nil
		}); e != nil {
			t.Fatal(e)
		}
	}
	if azBal(s.st, "ada") != 0 || azBal(s.st, "cy") != int64(100*authOK) {
		t.Fatal("captures")
	}
	azInvariants(t, s.st, 1000, time.Now())
}

// Void and capture of the same authorization race: exactly one outcome per round, invariants hold.
func TestAuthzVoidCaptureRace(t *testing.T) {
	var voidWon, captureWon int
	for round := 0; round < 300; round++ {
		s := fgStore(fgU{"ada", 5000}, fgU{"bob", 0})
		var id string
		s.Exec(func(st *State) (any, *AppError) {
			b := azAuthorize(t, st, "ada", "bob", 2000, time.Now())
			id = b.AuthorizationID
			return b, nil
		})
		var wg sync.WaitGroup
		var capErr, voidErr *AppError
		start := make(chan struct{})
		wg.Add(2)
		go func() {
			defer wg.Done()
			<-start
			_, capErr = s.Exec(func(st *State) (any, *AppError) {
				p, e := st.Capture("u_bob", id, CaptureIn{Amount: azI64(700), Final: round%2 == 0}, time.Now())
				if e != nil {
					return nil, e
				}
				return p, nil
			})
		}()
		go func() {
			defer wg.Done()
			<-start
			_, voidErr = s.Exec(func(st *State) (any, *AppError) {
				b, e := st.Void("u_ada", id, time.Now())
				if e != nil {
					return nil, e
				}
				return b, nil
			})
		}()
		close(start)
		wg.Wait()
		a := s.st.Authorizations[0]
		now := time.Now()
		switch {
		case capErr == nil && voidErr == nil: // capture first (non-final), then void of the remainder
			if round%2 == 0 || a.Status != "voided" || a.CapturedAmount != 700 || azBal(s.st, "bob") != 700 {
				t.Fatalf("round %d: %+v", round, a)
			}
			captureWon++
		case capErr == nil && voidErr != nil: // final capture first: void is refused
			if round%2 != 0 || voidErr.Code != "authorization_not_open" || a.Status != "captured" || azBal(s.st, "bob") != 700 {
				t.Fatalf("round %d: %+v %v", round, a, voidErr)
			}
			captureWon++
		case capErr != nil && voidErr == nil: // void first: capture is refused, nothing moved
			if capErr.Code != "authorization_not_open" || a.Status != "voided" || azBal(s.st, "bob") != 0 || a.CapturedAmount != 0 {
				t.Fatalf("round %d: %+v %v", round, a, capErr)
			}
			voidWon++
		default:
			t.Fatalf("round %d: both refused: %v %v", round, capErr, voidErr)
		}
		if st := s.st; st.Held("u_ada", now) != 0 {
			t.Fatalf("round %d: hold left behind: %d", round, st.Held("u_ada", now))
		}
		azInvariants(t, s.st, 5000, now)
	}
	t.Logf("void won %d, capture won %d", voidWon, captureWon)
}

// A seeded random walk over every money operation with a moving clock: no 5xx, invariants after each step.
func TestAuthzRandomWalk(t *testing.T) {
	rng := rand.New(rand.NewSource(20260924))
	handles := []string{"ada", "bob", "cy", "di"}
	_, st := azStore(fgU{"ada", 5000}, fgU{"bob", 3000}, fgU{"cy", 700}, fgU{"di", 0})
	st.AuthTTLSeconds = 120
	const seeded = 8700
	now := azT0
	counts := map[string]int{}
	for step := 0; step < 4000; step++ {
		now = now.Add(time.Duration(rng.Intn(12)) * time.Second)
		who := "u_" + handles[rng.Intn(4)]
		other := handles[rng.Intn(4)]
		amt := int64(1 + rng.Intn(1500))
		var e *AppError
		var op string
		switch rng.Intn(6) {
		case 0:
			op = "pay"
			_, e = st.Pay(who, PaymentIn{ToHandle: other, Amount: amt, Visibility: visPublic}, now)
		case 1, 2:
			op = "authorize"
			_, e = st.Authorize(who, AuthorizeIn{ToHandle: other, Amount: amt, Visibility: visPrivate}, now)
		case 3, 4:
			op = "capture"
			if n := len(st.Authorizations); n > 0 {
				a := st.Authorizations[n-1-rng.Intn(min(n, 8))]
				if rng.Intn(10) > 0 {
					who = a.ToUserID
				}
				var amount *int64
				if rng.Intn(3) > 0 {
					amount = azI64(1 + amt%600)
				}
				_, e = st.Capture(who, a.AuthorizationID, CaptureIn{Amount: amount, Final: rng.Intn(3) == 0}, now)
			}
		case 5:
			op = "void"
			if n := len(st.Authorizations); n > 0 {
				a := st.Authorizations[n-1-rng.Intn(min(n, 8))]
				if rng.Intn(10) > 0 {
					who = a.FromUserID
				}
				_, e = st.Void(who, a.AuthorizationID, now)
			}
		}
		if e != nil && e.Status >= 500 {
			t.Fatalf("step %d %s: %v", step, op, e)
		}
		if e == nil {
			counts[op]++
		}
		if err := azCheck(st, seeded, now); err != nil {
			t.Fatalf("step %d %s: %v", step, op, err)
		}
	}
	if counts["pay"] < 20 || counts["authorize"] < 100 || counts["capture"] < 100 || counts["void"] < 20 {
		t.Fatalf("walk too thin to mean anything: %v", counts)
	}
	t.Logf("successful ops: %v", counts)
}
