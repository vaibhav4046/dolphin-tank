package main

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"slices"
	"strings"
	"testing"
	"time"
)

var hsT0 = time.Date(2026, 9, 24, 13, 10, 0, 0, time.UTC)

func hsAt(d time.Duration) time.Time { return hsT0.Add(d) }

func hsP(s string) *string { return &s }

// hsSeed is a seeded payment of a hand-built state.
type hsSeed struct {
	id, from, to string
	amount       int64
	at           string
}

// hsState builds a consistent state whose users end with the given balances after the seeded
// payments, deriving revision 1 of each and every opening balance (what a fixture loader does).
func hsState(t testing.TB, us []fgU, seeds ...hsSeed) *State {
	t.Helper()
	st := &State{Currency: "EUR", MinorUnits: 2, HistoryVersion: historyVersion}
	net := map[string]int64{}
	for _, s := range seeds {
		st.Payments = append(st.Payments, &Payment{PaymentID: s.id, FromUserID: "u_" + s.from, ToUserID: "u_" + s.to,
			Amount: s.amount, Visibility: visPublic, CreatedAt: s.at})
		st.Revisions = append(st.Revisions, &Revision{PaymentID: s.id, Revision: 1, Amount: s.amount, EffectiveAt: s.at, RecordedAt: s.at})
		net["u_"+s.from] -= s.amount
		net["u_"+s.to] += s.amount
	}
	for _, u := range us {
		id := "u_" + u.h
		st.Users = append(st.Users, &User{ID: id, Email: u.h + "@example.com", DisplayName: u.h, Handle: u.h,
			PassHash: "x", Balance: u.bal, OpeningBalance: u.bal - net[id]})
	}
	if err := st.ReindexAt(hsT0); err != nil {
		t.Fatal(err)
	}
	return st
}

func hsPay(t testing.TB, st *State, from, to string, amount int64, now time.Time) *Payment {
	t.Helper()
	p, e := st.Pay("u_"+from, PaymentIn{ToHandle: to, Amount: amount, Visibility: visPublic}, now)
	if e != nil {
		t.Fatalf("pay %s->%s %d: %v", from, to, amount, e)
	}
	return p
}

func hsMe(t testing.TB, st *State, user string, asOf, knownAt *string, now time.Time) map[string]any {
	t.Helper()
	v, e := st.MeAt("u_"+user, MeQuery{AsOf: asOf, KnownAt: knownAt}, now)
	if e != nil {
		t.Fatalf("me %s as_of=%v known_at=%v: %v", user, asOf, knownAt, e)
	}
	return azJSON(t, v)
}

func hsInstant(t testing.TB, s string) time.Time {
	t.Helper()
	v, ok := ParseInstant(s)
	if !ok {
		t.Fatalf("not an instant: %q", s)
	}
	return v
}

func TestHistoryInstants(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"2026-09-24T13:20:00+00:00", "2026-09-24T13:20:00.000000+00:00"},
		{"2026-09-24T13:20:00Z", "2026-09-24T13:20:00.000000+00:00"},
		{"2026-09-24T13:20:00z", "2026-09-24T13:20:00.000000+00:00"},
		{"2026-09-24t13:20:00Z", "2026-09-24T13:20:00.000000+00:00"},
		{"2026-09-24T15:20:00.5+02:00", "2026-09-24T13:20:00.500000+00:00"},
		{"2026-09-24T13:20:00.123456789-00:00", "2026-09-24T13:20:00.123456+00:00"},
		{"2026-09-24T13:20:00-05:30", "2026-09-24T18:50:00.000000+00:00"},
	} {
		got, ok := ParseInstant(c.in)
		if !ok || FormatMicro(got) != c.want {
			t.Errorf("%q -> %v %v, want %s", c.in, got, ok, c.want)
		}
	}
	for _, in := range []string{
		"", " ", "2026-09-24", "2026-09-24T13:20:00", "2026-09-24 13:20:00Z", "2026-09-24T13:20:00Zjunk",
		"2026-09-24T13:20:00+0200", "2026-09-24T13:20:00+02", "2026-09-24T25:00:00Z", "2026-02-30T00:00:00Z",
		"2026-09-24T13:20:00.Z", "2026-09-24T13:20:00+24:00", "2026-09-24T13:20:00+02:60", " 2026-09-24T13:20:00Z",
		"2026-09-24T13:20:00Z ", "２０２６-09-24T13:20:00Z", "1758719400", "2026-09-24T13:20Z", "2026-09-24T13:20:00,5Z",
	} {
		if got, ok := ParseInstant(in); ok {
			t.Errorf("%q must not be an instant, got %v", in, got)
		}
	}
	if FormatMicro(time.Date(2026, 9, 24, 15, 0, 0, 999, time.FixedZone("x", 7200))) != "2026-09-24T13:00:00.000000+00:00" {
		t.Error("FormatMicro must convert to UTC and truncate to microseconds")
	}
}

func TestHistoryStampAdvancesReadNowDoesNot(t *testing.T) {
	_, st := azStore(fgU{"ada", 1})
	a := st.Stamp(hsT0)
	b := st.Stamp(hsT0)
	c := st.Stamp(hsT0.Add(-time.Hour))
	if !a.Equal(hsT0) || !b.Equal(hsT0.Add(time.Microsecond)) || !c.Equal(hsT0.Add(2*time.Microsecond)) {
		t.Fatalf("stamps %v %v %v", a, b, c)
	}
	r1, r2 := st.ReadNow(hsT0), st.ReadNow(hsT0)
	if !r1.Equal(c.Add(time.Microsecond)) || !r1.Equal(r2) {
		t.Fatalf("ReadNow must sit one microsecond after the last stamp and not advance: %v %v", r1, r2)
	}
	if far := st.ReadNow(hsT0.Add(time.Hour + 7*time.Nanosecond)); !far.Equal(hsT0.Add(time.Hour)) {
		t.Fatalf("a clock ahead of the stamps is used, truncated to the microsecond: %v", far)
	}
	if got := st.Stamp(hsT0.Add(time.Hour + 5*time.Nanosecond)); !got.Equal(hsT0.Add(time.Hour)) {
		t.Fatal(got)
	}
}

func TestHistoryMeAsOfMatrix(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 500})
	p1 := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	hsPay(t, st, "bob", "ada", 200, hsAt(10*time.Second))
	now := hsAt(time.Minute)

	cur, e := st.MeAt("u_ada", MeQuery{}, now)
	if e != nil || string(mustJSON(cur)) != string(mustJSON(st.Me("u_ada", now))) {
		t.Fatalf("no temporal params must be Me byte for byte: %s", mustJSON(cur))
	}
	if p1.CreatedAt != "2026-09-24T13:10:00.000000+00:00" {
		t.Fatal(p1.CreatedAt)
	}
	for _, c := range []struct {
		asOf string
		want int64
	}{
		{"1990-01-01T00:00:00+00:00", 10000},
		{"2026-09-24T13:09:59.999999+00:00", 10000},
		{"2026-09-24T13:10:00.000000+00:00", 9000}, // exactly at: counts
		{"2026-09-24T13:10:00.000001+00:00", 9000},
		{"2026-09-24T15:10:00+02:00", 9000}, // the same instant in another offset
		{"2026-09-24T13:10:09.999999Z", 9000},
		{"2026-09-24T13:10:10.000000Z", 9200},
		{"2026-09-24T13:10:10+00:00", 9200},
		{"2099-01-01T00:00:00+00:00", 9200},
	} {
		m := hsMe(t, st, "ada", hsP(c.asOf), nil, now)
		if m["balance"] != float64(c.want) || m["total"] != float64(c.want) || m["available"] != float64(c.want) || m["held"] != 0.0 || m["as_of"] != c.asOf {
			t.Errorf("as_of %s: %v, want %d", c.asOf, m, c.want)
		}
		if _, has := m["known_at"]; has {
			t.Errorf("known_at must be echoed only when supplied: %v", m)
		}
	}
	// the far future equals the current balance; bob sees the mirror image
	if m := hsMe(t, st, "bob", hsP("2099-01-01T00:00:00Z"), nil, now); m["balance"] != float64(500+1000-200) {
		t.Fatal(m)
	}
	for _, bad := range []string{"", "2026-09-24T13:10:00", "2026-09-24", "2026-09-24 13:10:00Z", "yesterday", "2026-09-24T13:10:00Zx"} {
		if _, e := st.MeAt("u_ada", MeQuery{AsOf: hsP(bad)}, now); e == nil || e.Status != 422 || e.Code != "validation_failed" {
			t.Errorf("as_of %q: %v", bad, e)
		}
		if _, e := st.MeAt("u_ada", MeQuery{KnownAt: hsP(bad)}, now); e == nil || e.Status != 422 {
			t.Errorf("known_at %q: %v", bad, e)
		}
	}
	if _, e := st.MeAt("u_nobody", MeQuery{AsOf: hsP("2026-09-24T13:10:00Z")}, now); e == nil || e.Status != 401 {
		t.Fatal(e)
	}
}

func TestHistoryKnownAtMatrix(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 500})
	p1 := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	p2 := hsPay(t, st, "bob", "ada", 200, hsAt(10*time.Second))
	// ada reduces p1 to 400 keeping its effective time; bob raises p2 to 300 effective later than created
	if _, e := st.Correct("u_ada", p1.PaymentID, CorrectionIn{1, 400, "2026-09-24T13:10:00+00:00", "typo"}, hsAt(time.Minute)); e != nil {
		t.Fatal(e)
	}
	if _, e := st.Correct("u_bob", p2.PaymentID, CorrectionIn{1, 300, "2026-09-24T13:10:30+00:00", "late"}, hsAt(2*time.Minute)); e != nil {
		t.Fatal(e)
	}
	now := hsAt(5 * time.Minute)
	far := "2099-01-01T00:00:00Z"
	for _, c := range []struct {
		knownAt string
		want    int64
	}{
		{"2026-09-24T13:09:59.999999Z", 10000}, // nothing recorded yet
		{"2026-09-24T13:10:00Z", 9000},         // p1 rev 1
		{"2026-09-24T13:10:10Z", 9200},         // + p2 rev 1
		{"2026-09-24T13:10:59.999999Z", 9200},
		{"2026-09-24T13:11:00Z", 9800}, // p1 rev 2 (1000 -> 400)
		{"2026-09-24T13:11:59Z", 9800}, // p2 still rev 1
		{"2026-09-24T13:12:00Z", 9900}, // p2 rev 2 (200 -> 300)
		{"2099-01-01T00:00:00Z", 9900}, // future known_at allowed
		{"2026-09-24T15:12:00+02:00", 9900},
	} {
		m := hsMe(t, st, "ada", hsP(far), hsP(c.knownAt), now)
		if m["balance"] != float64(c.want) || m["known_at"] != c.knownAt || m["as_of"] != far {
			t.Errorf("known_at %s: %v, want %d", c.knownAt, m, c.want)
		}
	}
	if m := hsMe(t, st, "ada", nil, hsP("2026-09-24T13:10:10Z"), now); m["balance"] != 9200.0 {
		t.Fatalf("known_at alone: as_of defaults to now: %v", m)
	}
	if m := hsMe(t, st, "ada", nil, nil, now); m["balance"] != 9900.0 || st.UserByHandle("ada").Balance != 9900 {
		t.Fatalf("default is the current corrected value: %v", m)
	}
	// p2's corrected revision takes effect at 13:10:30, so at 13:10:20 it contributes nothing (not its old 200)
	if m := hsMe(t, st, "ada", hsP("2026-09-24T13:10:20Z"), nil, now); m["balance"] != 9600.0 {
		t.Fatalf("a correction is never counted alongside the revision it replaces: %v", m)
	}
	if m := hsMe(t, st, "ada", hsP("2026-09-24T13:10:20Z"), hsP("2026-09-24T13:11:30Z"), now); m["balance"] != 9800.0 {
		t.Fatalf("before the correction was recorded the old revision still applies: %v", m)
	}
	if m := hsMe(t, st, "ada", hsP("2026-09-24T13:10:30Z"), nil, now); m["balance"] != 9900.0 {
		t.Fatal(m)
	}
	// the sum of the wallets is the seeded total in every view
	rng := rand.New(rand.NewSource(7))
	for i := 0; i < 300; i++ {
		tt := hsAt(time.Duration(rng.Intn(400)-100) * time.Second).Add(time.Duration(rng.Intn(3)) * time.Microsecond)
		kk := hsAt(time.Duration(rng.Intn(400)-100) * time.Second)
		var sum int64
		for _, u := range st.Users {
			sum += st.TotalAt(u.ID, tt, kk)
		}
		if sum != 10500 {
			t.Fatalf("sum %d at t=%v k=%v", sum, tt, kk)
		}
	}
}

func TestHistoryHoldTimeline(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	a1 := azAuthorize(t, st, "ada", "bob", 3000, hsAt(0))
	c1 := azMustCapture(t, st, "bob", a1.AuthorizationID, azI64(1000), false, hsAt(10*time.Second))
	c2 := azMustCapture(t, st, "bob", a1.AuthorizationID, azI64(500), true, hsAt(20*time.Second))
	a2 := azAuthorize(t, st, "ada", "bob", 2000, hsAt(30*time.Second))
	v, e := st.Void("u_ada", a2.AuthorizationID, hsAt(40*time.Second))
	if e != nil {
		t.Fatal(e)
	}
	st.AuthTTLSeconds = 60
	a3 := azAuthorize(t, st, "ada", "bob", 100, hsAt(50*time.Second))
	inf := hsAt(24 * time.Hour)

	held := func(d time.Duration, k time.Time) int64 { return st.HeldAt("u_ada", hsAt(d), k) }
	for _, c := range []struct {
		d    time.Duration
		want int64
	}{
		{-time.Second, 0}, // before creation
		{0, 3000},         // creation
		{10*time.Second - time.Microsecond, 3000},
		{10 * time.Second, 2000}, // non-final capture reduces the hold at capture time
		{20*time.Second - time.Microsecond, 2000},
		{20 * time.Second, 0},    // the final capture releases the remainder
		{30 * time.Second, 2000}, // second hold
		{40*time.Second - time.Microsecond, 2000},
		{40 * time.Second, 0},   // void
		{50 * time.Second, 100}, // third hold
		{110*time.Second - time.Microsecond, 100},
		{110 * time.Second, 0}, // expiry takes effect at expires_at
		{24 * time.Hour, 0},
	} {
		if got := held(c.d, inf); got != c.want {
			t.Errorf("held at +%v = %d, want %d", c.d, got, c.want)
		}
	}
	// known_at: events other than expiry are known at their event time
	for _, c := range []struct {
		d, k time.Duration
		want int64
	}{
		{25 * time.Second, 15 * time.Second, 2000}, // the final capture is not yet known
		{25 * time.Second, 20 * time.Second, 0},    // now it is
		{45 * time.Second, 35 * time.Second, 2000}, // the void is not yet known: still held
		{45 * time.Second, 40 * time.Second, 0},
		{5 * time.Second, -time.Second, 0},       // creation unknown
		{5 * time.Second, 0, 3000},               // creation known
		{200 * time.Second, 55 * time.Second, 0}, // the deadline (13:11:50) is known with the creation
	} {
		if got := held(c.d, hsAt(c.k)); got != c.want {
			t.Errorf("held at +%v known at +%v = %d, want %d", c.d, c.k, got, c.want)
		}
	}
	// four fields describe one view
	m := hsMe(t, st, "ada", hsP(FormatTime(hsAt(15*time.Second))), nil, hsAt(time.Hour))
	if m["total"] != 9000.0 || m["balance"] != 9000.0 || m["held"] != 2000.0 || m["available"] != 7000.0 {
		t.Fatalf("%v", m)
	}
	// without as_of the hold is judged at the instant the read began, and agrees with the plain /me
	for _, now := range []time.Time{hsAt(60 * time.Second), hsAt(200 * time.Second)} {
		plain, view := azJSON(t, st.Me("u_ada", now)), hsMe(t, st, "ada", nil, hsP(FormatTime(now)), now)
		for _, k := range []string{"balance", "total", "held", "available"} {
			if plain[k] != view[k] {
				t.Errorf("at %v %s: me %v, view %v", now, k, plain[k], view[k])
			}
		}
	}

	// closed_at
	if b := st.authBody(st.Authorizations[0], hsAt(time.Minute)); b.ClosedAt == nil || *b.ClosedAt != c2.CreatedAt || c1.CreatedAt == c2.CreatedAt {
		t.Errorf("a final capture closes at that capture's created_at: %v", b.ClosedAt)
	}
	if v.ClosedAt == nil || *v.ClosedAt != "2026-09-24T13:10:40.000000+00:00" {
		t.Errorf("void: %v", v.ClosedAt)
	}
	if b := st.authBody(st.Authorizations[2], hsAt(60*time.Second)); b.ClosedAt != nil || b.Status != "open" {
		t.Errorf("open: %+v", b)
	}
	b3 := st.authBody(st.Authorizations[2], hsAt(2*time.Minute))
	if b3.Status != "expired" || b3.ClosedAt == nil || *b3.ClosedAt != a3.ExpiresAt || st.Authorizations[2].Status != "open" || st.Authorizations[2].ClosedAt != nil {
		t.Errorf("clock expiry derives closed_at = expires_at and never changes the stored hold: %+v", b3)
	}
	pg, e := st.ListAuthorizations("u_ada", "", "", 50, 0, hsAt(2*time.Minute))
	if e != nil {
		t.Fatal(e)
	}
	for _, b := range pg.(authorizationPage).Authorizations {
		if (b.Status == "open") != (b.ClosedAt == nil) {
			t.Errorf("list: %s %s closed_at %v", b.AuthorizationID, b.Status, b.ClosedAt)
		}
	}
	raw := string(mustJSON(st.authBody(st.Authorizations[2], hsAt(60*time.Second))))
	if !strings.Contains(raw, `"closed_at":null`) {
		t.Errorf("closed_at must be present as null: %s", raw)
	}
}

func TestHistorySeededHolds(t *testing.T) {
	// a stored-expired hold seeded with a future deadline, a voided one and a partially captured one
	closed := FormatTime(hsT0)
	exp := FormatTime(hsT0.Add(time.Hour))
	st := hsState(t, []fgU{{"ada", 10000}, {"bob", 0}})
	st.Authorizations = []*Authorization{
		{AuthorizationID: "a_exp", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 300, Status: authExpired, ExpiresAt: exp, CreatedAt: closed, ClosedAt: hsP(exp)},
		{AuthorizationID: "a_void", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 500, Status: authVoided, ExpiresAt: exp, CreatedAt: closed, ClosedAt: hsP(closed)},
		{AuthorizationID: "a_part", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 1000, CapturedAmount: 400, Status: authOpen, ExpiresAt: exp, CreatedAt: closed},
	}
	if err := st.ReindexAt(hsT0); err != nil {
		t.Fatal(err)
	}
	for _, d := range []time.Duration{0, time.Second, 30 * time.Minute} {
		if got := st.HeldAt("u_ada", hsAt(d), hsAt(d)); got != 600 {
			t.Errorf("+%v: held %d, want 600 (only the open remainder)", d, got)
		}
		if st.Held("u_ada", hsAt(d)) != 600 {
			t.Error("Held and HeldAt must agree at the same instant")
		}
	}
	if st.HeldAt("u_ada", hsAt(-time.Second), hsAt(time.Hour)) != 0 || st.HeldAt("u_ada", hsAt(time.Hour), hsAt(time.Hour)) != 0 {
		t.Error("before creation and after the deadline nothing is held")
	}
	if b := st.authBody(st.Authorizations[0], hsAt(time.Minute)); b.ClosedAt == nil || *b.ClosedAt != exp {
		t.Errorf("stored expired: closed_at = expires_at: %v", b.ClosedAt)
	}
}

func TestHistoryActivityOrder(t *testing.T) {
	st := hsState(t, []fgU{{"ada", 100}, {"bob", 100}},
		hsSeed{"p_1", "ada", "bob", 1, "2026-09-24T14:00:00+02:00"}, // 12:00Z
		hsSeed{"p_2", "ada", "bob", 1, "2026-09-24T11:00:00+00:00"}, // earliest, inserted second
		hsSeed{"p_3", "bob", "ada", 1, "2026-09-24T12:00:00+00:00"}, // same instant as p_1, later insertion
		hsSeed{"p_4", "bob", "ada", 1, "2026-09-24T13:00:00.5+00:00"},
	)
	ids := func(limit, offset int) ([]string, bool) {
		pg := st.Activity("u_ada", limit, offset).(paymentPage)
		var out []string
		for _, p := range pg.Payments {
			out = append(out, p.PaymentID)
		}
		return out, pg.HasMore
	}
	if got, more := ids(50, 0); !slices.Equal(got, []string{"p_4", "p_3", "p_1", "p_2"}) || more {
		t.Fatalf("%v %v", got, more)
	}
	if got, more := ids(2, 1); !slices.Equal(got, []string{"p_3", "p_1"}) || !more {
		t.Fatalf("%v %v", got, more)
	}
	// payments made through the API are newer than every seeded one
	p := hsPay(t, st, "ada", "bob", 1, hsT0)
	if got, _ := ids(1, 0); !slices.Equal(got, []string{p.PaymentID}) {
		t.Fatalf("%v", got)
	}
	if st.Payments[0].Amount != 1 || len(st.Payments) != 5 {
		t.Fatal("activity must not reorder the stored payments")
	}
}

func TestHistoryReindexVerifiesHistory(t *testing.T) {
	_, st := azStore(fgU{"ada", 5000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 700, hsAt(0))
	if _, e := st.Correct("u_ada", p.PaymentID, CorrectionIn{1, 500, FormatTime(hsAt(0)), "fix"}, hsAt(time.Minute)); e != nil {
		t.Fatal(e)
	}
	raw, err := json.Marshal(st)
	if err != nil {
		t.Fatal(err)
	}
	var back State
	if err := json.Unmarshal(raw, &back); err != nil {
		t.Fatal(err)
	}
	if err := back.ReindexAt(hsAt(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if raw2, _ := json.Marshal(&back); string(raw) != string(raw2) {
		t.Fatalf("round trip differs:\n%s\n%s", raw, raw2)
	}
	if !back.lastStamp.Equal(st.lastStamp) {
		t.Fatalf("lastStamp %v, want %v", back.lastStamp, st.lastStamp)
	}
	if nxt := back.Stamp(hsAt(0)); !nxt.After(hsAt(time.Minute)) {
		t.Fatalf("stamps resume after the newest recorded instant: %v", nxt)
	}
	for name, mut := range map[string]func(st *State){
		"history_version":     func(st *State) { st.HistoryVersion = 2 },
		"missing revision 1":  func(st *State) { st.Revisions = st.Revisions[1:] },
		"revision gap":        func(st *State) { st.Revisions[1].Revision = 3 },
		"unknown payment":     func(st *State) { st.Revisions[0].PaymentID = "p_none" },
		"null revision":       func(st *State) { st.Revisions[0] = nil },
		"negative amount":     func(st *State) { st.Revisions[1].Amount = -1 },
		"correction too big":  func(st *State) { st.Revisions[1].Amount = maxAmount + 1 },
		"revision 1 amount":   func(st *State) { st.Revisions[0].Amount = 699 },
		"bad effective_at":    func(st *State) { st.Revisions[1].EffectiveAt = "2026-09-24" },
		"bad recorded_at":     func(st *State) { st.Revisions[1].RecordedAt = "" },
		"recorded not rising": func(st *State) { st.Revisions[1].RecordedAt = st.Revisions[0].RecordedAt },
		"payment created_at":  func(st *State) { st.Payments[0].CreatedAt = "yesterday" },
		"opening balance":     func(st *State) { st.Users[0].OpeningBalance++ },
		"balance":             func(st *State) { st.Users[1].Balance++ },
	} {
		var c State
		if err := json.Unmarshal(raw, &c); err != nil {
			t.Fatal(err)
		}
		mut(&c)
		if err := c.ReindexAt(hsAt(time.Hour)); err == nil {
			t.Errorf("%s: ReindexAt accepted an invalid state", name)
		}
	}
	// a payment without any revision cannot be reindexed: history is supplied, never derived here
	noHist := &State{Currency: "EUR", MinorUnits: 2,
		Users:    []*User{{ID: "u_1", Handle: "ada", Balance: 4}, {ID: "u_2", Handle: "bob", Balance: 1}},
		Payments: []*Payment{{PaymentID: "p_1", FromUserID: "u_1", ToUserID: "u_2", Amount: 1, CreatedAt: "2026-09-24T13:10:00+00:00"}}}
	if err := noHist.ReindexAt(hsT0); err == nil {
		t.Error("a payment with no revision 1 must be refused")
	}
	// closed_at must agree with the stored status
	for name, mut := range map[string]func(a *Authorization){
		"open with closed_at":       func(a *Authorization) { a.ClosedAt = hsP("2026-09-24T13:10:00+00:00") },
		"voided without":            func(a *Authorization) { a.Status = authVoided },
		"closed_at not instant":     func(a *Authorization) { a.Status, a.ClosedAt = authVoided, hsP("soon") },
		"created_exact elsewhere":   func(a *Authorization) { a.CreatedExact = hsP("2026-09-24T13:10:01.000000+00:00") },
		"created_exact not instant": func(a *Authorization) { a.CreatedExact = hsP("now") },
	} {
		s2 := hsState(t, []fgU{{"ada", 100}, {"bob", 0}})
		a := &Authorization{AuthorizationID: "a_1", FromUserID: "u_ada", ToUserID: "u_bob", Amount: 10, Status: authOpen,
			ExpiresAt: FormatTime(hsAt(time.Hour)), CreatedAt: FormatTime(hsT0)}
		mut(a)
		s2.Authorizations = []*Authorization{a}
		if err := s2.ReindexAt(hsT0); err == nil {
			t.Errorf("%s: ReindexAt accepted it", name)
		}
	}
}

// brute force of the overdraft rule from the public primitives only.
func hsBruteOverdrawn(st *State, userID string, now time.Time) bool {
	bounds := []time.Time{}
	for _, m := range st.MovementsFor(userID, histInf) {
		bounds = append(bounds, m.Rev.eff)
	}
	for _, a := range st.Authorizations {
		if a.FromUserID != userID {
			continue
		}
		bounds = append(bounds, a.placedAt(), a.expiresTime())
		if c, ok := a.closedTime(); ok {
			bounds = append(bounds, c)
		}
		for _, pid := range a.PaymentIDs {
			bounds = append(bounds, st.payByID[pid].created)
		}
	}
	for _, t := range bounds {
		if !t.After(now) && (st.TotalAt(userID, t, histInf) < 0 || st.TotalAt(userID, t, histInf)-st.heldAt(userID, t, histInf, true) < 0) {
			return true
		}
	}
	return false
}

// A random walk of every operation under a monotone clock keeps every invariant, and the sweep that
// guards corrections agrees with its brute-force definition on arbitrary (even invalid) revisions.
func TestHistoryRandomWalkInvariants(t *testing.T) {
	for seed := int64(1); seed <= 16; seed++ {
		rng := rand.New(rand.NewSource(seed))
		bal := [3]int64{50000, 30000, 20000}
		if seed > 8 { // poor wallets: payments, holds and corrections keep brushing against zero
			bal = [3]int64{9000, 6000, 4000}
		}
		_, st := azStore(fgU{"ada", bal[0]}, fgU{"bob", bal[1]}, fgU{"cy", bal[2]})
		total := bal[0] + bal[1] + bal[2]
		handles := []string{"ada", "bob", "cy"}
		now := hsAt(0)
		var pays []*Payment
		for step := 0; step < 400; step++ {
			now = now.Add(time.Duration(rng.Intn(3000)) * time.Millisecond)
			who, other := handles[rng.Intn(3)], handles[rng.Intn(3)]
			switch rng.Intn(6) {
			case 0, 1:
				if p, e := st.Pay("u_"+who, PaymentIn{ToHandle: other, Amount: int64(1 + rng.Intn(9000)), Visibility: visPublic}, now); e == nil {
					pays = append(pays, p)
				}
			case 2:
				st.Authorize("u_"+who, AuthorizeIn{ToHandle: other, Amount: int64(1 + rng.Intn(9000)), Visibility: visPublic}, now)
			case 3:
				if len(st.Authorizations) > 0 {
					a := st.Authorizations[rng.Intn(len(st.Authorizations))]
					amt := int64(1 + rng.Intn(3000))
					st.Capture(st.usersByID[a.ToUserID].ID, a.AuthorizationID, CaptureIn{Amount: &amt, Final: rng.Intn(2) == 0}, now)
				}
			case 4:
				if len(st.Authorizations) > 0 {
					a := st.Authorizations[rng.Intn(len(st.Authorizations))]
					st.Void(a.FromUserID, a.AuthorizationID, now)
				}
			case 5:
				if len(pays) > 0 {
					p := pays[rng.Intn(len(pays))]
					h := st.revByPay[p.PaymentID]
					eff := FormatMicro(p.created.Add(-time.Duration(rng.Intn(2)) * time.Second))
					st.Correct(p.FromUserID, p.PaymentID, CorrectionIn{h[len(h)-1].Revision, int64(rng.Intn(12000)), eff, "r"}, now)
				}
			}
			if err := hsCheck(st, total, now); err != nil {
				t.Fatalf("seed %d step %d: %v", seed, step, err)
			}
		}
		// the fast sweep equals the brute force on candidate revisions that were never validated
		for i := 0; i < 60 && len(pays) > 0; i++ {
			p := pays[rng.Intn(len(pays))]
			h := st.revByPay[p.PaymentID]
			at := st.ReadNow(now)
			st.appendRevision(&Revision{PaymentID: p.PaymentID, Revision: h[len(h)-1].Revision + 1, Amount: int64(rng.Intn(40000)),
				EffectiveAt: FormatMicro(at), RecordedAt: FormatMicro(at), eff: at.Add(-time.Duration(rng.Intn(120)) * time.Second), rec: at})
			for _, u := range st.Users {
				if got, want := st.overdrawnInThePast(u.ID, at), hsBruteOverdrawn(st, u.ID, at); got != want {
					t.Fatalf("seed %d: sweep %v, brute force %v for %s", seed, got, want, u.Handle)
				}
			}
			st.dropLastRevision(p.PaymentID)
		}
	}
}

// hsCheck verifies the invariants that must hold after every operation.
func hsCheck(st *State, total int64, now time.Time) error {
	read := st.ReadNow(now)
	var sum, openings int64
	for _, u := range st.Users {
		sum += u.Balance
		openings += u.OpeningBalance
		if u.Balance < 0 {
			return fmt.Errorf("%s negative balance", u.Handle)
		}
		if got := st.TotalAt(u.ID, histInf, histInf); got != u.Balance {
			return fmt.Errorf("%s: latest revisions give %d, balance %d", u.Handle, got, u.Balance)
		}
		if got := st.TotalAt(u.ID, read, read); got != u.Balance {
			return fmt.Errorf("%s: view at read-now gives %d, balance %d", u.Handle, got, u.Balance)
		}
		if st.Available(u, read) < 0 || st.AvailableAt(u.ID, read, read) != st.Available(u, read) {
			return fmt.Errorf("%s: available %d vs %d", u.Handle, st.AvailableAt(u.ID, read, read), st.Available(u, read))
		}
		open := u.OpeningBalance
		mv := st.MovementsFor(u.ID, histInf)
		for i, m := range mv {
			open += m.Delta
			if i > 0 && mv[i-1].Rev.eff.After(m.Rev.eff) {
				return fmt.Errorf("%s: movements out of order", u.Handle)
			}
		}
		if open != u.Balance {
			return fmt.Errorf("%s: opening + deltas %d != balance %d", u.Handle, open, u.Balance)
		}
		if st.overdrawnInThePast(u.ID, read) {
			return fmt.Errorf("%s was overdrawn at a past boundary", u.Handle)
		}
	}
	if sum != total || openings != total {
		return fmt.Errorf("balances %d / openings %d, want %d", sum, openings, total)
	}
	raw, err := json.Marshal(st)
	if err != nil {
		return err
	}
	var back State
	if err := json.Unmarshal(raw, &back); err != nil {
		return err
	}
	if err := back.ReindexAt(read); err != nil {
		return fmt.Errorf("state no longer reindexes: %w", err)
	}
	return nil
}
