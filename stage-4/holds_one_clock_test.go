package main

import (
	"net/url"
	"regexp"
	"strconv"
	"testing"
	"time"
)

// One clock for money and holds. A client reads an authorization's created_at, closed_at and expires_at
// and each payment's created_at from the API and may ask GET /me for any of those instants. These tests
// rebuild the expected view from those public strings alone (ocWorld) and compare it with what the
// service answers at every event instant and one microsecond either side.

var ocMicro = regexp.MustCompile(`^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$`)

type ocPay struct {
	from, to string
	amount   int64
	at       time.Time
}

type ocCap struct {
	at     time.Time
	amount int64
}

type ocHold struct {
	from             string
	amount           int64
	created, expires time.Time
	closed           *time.Time
	caps             []ocCap
}

type ocWorld struct {
	opening map[string]int64
	pays    []ocPay
	holds   []*ocHold
}

func (w *ocWorld) total(user string, at time.Time) int64 {
	total := w.opening[user]
	for _, p := range w.pays {
		if p.at.After(at) {
			continue
		}
		if p.to == user {
			total += p.amount
		}
		if p.from == user {
			total -= p.amount
		}
	}
	return total
}

// held: a hold counts from created_at, shrinks at each capture, and is gone from closed_at or expires_at.
func (w *ocWorld) held(user string, at time.Time) int64 {
	var held int64
	for _, h := range w.holds {
		if h.from != user || h.created.After(at) || !at.Before(h.expires) {
			continue
		}
		if h.closed != nil && !at.Before(*h.closed) {
			continue
		}
		rem := h.amount
		for _, c := range h.caps {
			if !c.at.After(at) {
				rem -= c.amount
			}
		}
		held += rem
	}
	return held
}

// probes is every event instant of the world, each with one microsecond before and after.
func (w *ocWorld) probes() []time.Time {
	var out []time.Time
	add := func(t time.Time) {
		for _, d := range []time.Duration{-time.Microsecond, 0, time.Microsecond} {
			out = append(out, t.Add(d))
		}
	}
	for _, p := range w.pays {
		add(p.at)
	}
	for _, h := range w.holds {
		add(h.created)
		add(h.expires)
		if h.closed != nil {
			add(*h.closed)
		}
		for _, c := range h.caps {
			add(c.at)
		}
	}
	return out
}

// ocCheck asserts the four money fields of one view are consistent and equal the client's own reading.
func ocCheck(t *testing.T, w *ocWorld, user string, at time.Time, me map[string]any, what string) {
	t.Helper()
	num := func(k string) int64 { return int64(me[k].(float64)) }
	total, held, avail, bal := num("total"), num("held"), num("available"), num("balance")
	if bal != total || held < 0 || held > total || avail != total-held || avail < 0 {
		t.Errorf("%s %s as_of=%s: inconsistent view balance %d total %d held %d available %d", what, user, FormatMicro(at), bal, total, held, avail)
	}
	if want := w.total(user, at); total != want {
		t.Errorf("%s %s as_of=%s: total %d, want %d", what, user, FormatMicro(at), total, want)
	}
	if want := w.held(user, at); held != want {
		t.Errorf("%s %s as_of=%s: held %d, want %d", what, user, FormatMicro(at), held, want)
	}
}

func ocInstant(t *testing.T, s string) time.Time {
	t.Helper()
	if !ocMicro.MatchString(s) {
		t.Errorf("%q is not a microsecond UTC instant", s)
	}
	return hsInstant(t, s)
}

const ocFixture = `{"currency":"EUR","minor_units":2,"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":500000},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":0},
 {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":0}]}`

// Jury H5: bob is paid 5000 and at once authorizes 4000. The authorization's own created_at, handed back
// by the API, must show total 5000, held 4000, available 1000 - never a hold funded by money that "arrived"
// later. Repeated back to back, then every event instant of the whole run is checked against the client's
// own reading of the public timestamps.
func TestHoldIsAffordableAtItsCreatedAtOverHTTP(t *testing.T) {
	h := NewServer(NewStore())
	if rec := do(h, "POST", "/_test/reset", ocFixture, nil); rec.Code != 204 {
		t.Fatalf("reset: %d %s", rec.Code, rec.Body)
	}
	tok := map[string]map[string]string{"ada": loginAs(t, h, "ada@example.com"), "bob": loginAs(t, h, "bob@example.com"), "cy": loginAs(t, h, "cy@example.com")}
	w := &ocWorld{opening: map[string]int64{"u_ada": 500000}}
	uid := map[string]string{"ada": "u_ada", "bob": "u_bob", "cy": "u_cy"}
	post := func(who, path, body, key string) map[string]any {
		t.Helper()
		rec := do(h, "POST", path, body, withKey(tok[who], key))
		if rec.Code != 200 && rec.Code != 201 {
			t.Fatalf("POST %s %s: %d %s", path, body, rec.Code, rec.Body)
		}
		return decode(t, rec.Body.Bytes())
	}
	me := func(who string, at time.Time) map[string]any {
		t.Helper()
		rec := do(h, "GET", "/me?as_of="+url.QueryEscape(FormatMicro(at)), "", tok[who])
		if rec.Code != 200 {
			t.Fatalf("GET /me as_of=%s: %d %s", FormatMicro(at), rec.Code, rec.Body)
		}
		return decode(t, rec.Body.Bytes())
	}
	const rounds = 30
	for i := 1; i <= rounds; i++ {
		n := strconv.Itoa(i)
		pay := post("ada", "/payments", `{"to_handle":"bob","amount":5000}`, "pay-"+n)
		w.pays = append(w.pays, ocPay{"u_ada", "u_bob", 5000, ocInstant(t, pay["created_at"].(string))})
		auth := post("bob", "/authorizations", `{"to_handle":"cy","amount":4000}`, "auth-"+n)
		created, expires := ocInstant(t, auth["created_at"].(string)), ocInstant(t, auth["expires_at"].(string))
		if expires.Sub(created) != 600*time.Second {
			t.Fatalf("round %d: expires_at %s is not created_at %s plus the 600 s ttl", i, auth["expires_at"], auth["created_at"])
		}
		hold := &ocHold{from: "u_bob", amount: 4000, created: created, expires: expires}
		w.holds = append(w.holds, hold)

		got := me("bob", created)
		wantTotal := 5000 * int64(i)
		for j := 1; j < i; j++ {
			if j%2 == 0 {
				wantTotal -= 1000
			}
		}
		if int64(got["total"].(float64)) != wantTotal || got["held"] != float64(4000) || int64(got["available"].(float64)) != wantTotal-4000 || got["balance"] != got["total"] {
			t.Fatalf("round %d: bob as_of=created_at %s: %v, want total %d held 4000 available %d", i, auth["created_at"], got, wantTotal, wantTotal-4000)
		}
		ocCheck(t, w, "u_bob", created, got, "created_at")
		if before := me("bob", created.Add(-time.Microsecond)); before["held"] != float64(0) {
			t.Fatalf("round %d: one microsecond before created_at the hold must not exist: %v", i, before)
		}

		id := auth["authorization_id"].(string)
		if i%2 == 0 {
			c := post("cy", "/authorizations/"+id+"/capture", `{"amount":1000,"final":false}`, "cap-"+n)
			at := ocInstant(t, c["created_at"].(string))
			w.pays = append(w.pays, ocPay{"u_bob", "u_cy", 1000, at})
			hold.caps = append(hold.caps, ocCap{at, 1000})
		}
		rec := do(h, "POST", "/authorizations/"+id+"/void", "", tok["bob"])
		if rec.Code != 200 {
			t.Fatalf("void: %d %s", rec.Code, rec.Body)
		}
		closed := ocInstant(t, decode(t, rec.Body.Bytes())["closed_at"].(string))
		hold.closed = &closed
	}
	views := 0
	for _, at := range w.probes() {
		for who, id := range uid {
			ocCheck(t, w, id, at, me(who, at), "sweep")
			views++
		}
	}
	t.Logf("%d rounds, %d views at event instants +-1us, all consistent with the public timestamps", rounds, views)
}

// The same lifecycle, in process, with every call made at one clock instant (stamps advance one
// microsecond per write) and at clock offsets around a second boundary: pay -> authorize -> capture ->
// void, and pay -> authorize -> final capture.
func TestHoldInstantsAcrossBackToBackLifecycle(t *testing.T) {
	_, st := azStore(fgU{"ada", 500000}, fgU{"bob", 0}, fgU{"cy", 0})
	w := &ocWorld{opening: map[string]int64{"u_ada": 500000}}
	offsets := []time.Duration{0, 1, 499999, 500000, 999995, 999997, 999998, 999999, 1000000, 1234567, 2999999}
	readAt := hsAt(1000 * time.Hour)
	for k, off := range offsets {
		now := hsAt(time.Duration(k)*time.Hour + off*time.Microsecond)
		p := hsPay(t, st, "ada", "bob", 5000, now)
		w.pays = append(w.pays, ocPay{"u_ada", "u_bob", 5000, ocInstant(t, FormatMicro(p.created))})
		a := azAuthorize(t, st, "bob", "cy", 4000, now)
		hold := &ocHold{from: "u_bob", amount: 4000, created: ocInstant(t, a.CreatedAt), expires: ocInstant(t, a.ExpiresAt)}
		w.holds = append(w.holds, hold)
		amount, final := int64(1500), k%2 == 1
		if final {
			amount = 2500
		}
		c := azMustCapture(t, st, "cy", a.AuthorizationID, &amount, final, now)
		at := ocInstant(t, c.CreatedAt)
		w.pays = append(w.pays, ocPay{"u_bob", "u_cy", amount, at})
		hold.caps = append(hold.caps, ocCap{at, amount})
		if final {
			hold.closed = &at
		} else {
			v, e := st.Void("u_bob", a.AuthorizationID, now)
			if e != nil {
				t.Fatalf("void: %v", e)
			}
			closed := ocInstant(t, *v.ClosedAt)
			hold.closed = &closed
		}
		// the view at the authorization's own created_at, taken right after, is the jury's H5 shape
		asOf := a.CreatedAt
		got := hsMe(t, st, "bob", &asOf, nil, readAt)
		ocCheck(t, w, "u_bob", hold.created, got, "created_at")
		if got["held"] != float64(4000) || got["available"] != float64(int64(got["total"].(float64))-4000) {
			t.Fatalf("offset %v: %v", off, got)
		}
	}
	views := 0
	for _, at := range w.probes() {
		asOf := FormatMicro(at)
		for _, u := range []string{"ada", "bob", "cy"} {
			ocCheck(t, w, "u_"+u, at, hsMe(t, st, u, &asOf, nil, readAt), "sweep")
			views++
		}
	}
	t.Logf("%d lifecycles, %d views at event instants +-1us", len(offsets), views)
}

// created_at and expires_at are microsecond instants and expires_at - created_at is exactly the
// configured lifetime; the hold is released at expires_at and not one microsecond before.
func TestAuthorizeStampsMicrosecondsWithExactTTL(t *testing.T) {
	for _, ttl := range []int64{0, 1, 2, 59, 600, 3600, 86400, 1_000_000_000} {
		_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
		st.AuthTTLSeconds = ttl
		want := ttl
		if ttl == 0 {
			want = 600
		}
		clock := hsAt(123456*time.Microsecond + 789*time.Nanosecond)
		a := azAuthorize(t, st, "ada", "bob", 2500, clock)
		created, expires := ocInstant(t, a.CreatedAt), ocInstant(t, a.ExpiresAt)
		if a.CreatedAt != FormatMicro(hsAt(123456*time.Microsecond)) || expires.Sub(created) != time.Duration(want)*time.Second || a.ExpiresAt != FormatMicro(created.Add(time.Duration(want)*time.Second)) {
			t.Errorf("ttl %d: created_at %s expires_at %s", ttl, a.CreatedAt, a.ExpiresAt)
		}
		if stored := st.Authorizations[0]; stored.CreatedAt != a.CreatedAt || stored.ExpiresAt != a.ExpiresAt || !stored.createdTime().Equal(created) || !stored.expiresTime().Equal(expires) {
			t.Errorf("ttl %d: stored instants differ from the body", ttl)
		}
		now := expires.Add(time.Hour)
		for _, c := range []struct {
			at   time.Time
			held int64
		}{{created.Add(-time.Microsecond), 0}, {created, 2500}, {expires.Add(-time.Microsecond), 2500}, {expires, 0}} {
			asOf := FormatMicro(c.at)
			if me := hsMe(t, st, "ada", &asOf, nil, now); me["held"] != float64(c.held) || me["available"] != float64(10000-c.held) {
				t.Errorf("ttl %d as_of=%s: %v, want held %d", ttl, asOf, me, c.held)
			}
		}
	}
}
