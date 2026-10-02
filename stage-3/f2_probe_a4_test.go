package main

import (
	"testing"
	"time"
)

// Probe A4 (report only, asserts nothing about the answer): a seeded open hold without created_at takes the
// reset's whole second (fixture.go FormatTime(now)) while a seeded payment without created_at takes the reset
// instant in microseconds. For a user whose seeded payments changed the opening balance, a view between the
// two can show the hold without the money. Run with -v to read the verdict.
func TestProbeA4SeededHoldDefaultsToTruncatedResetSecond(t *testing.T) {
	fixture := `{"currency":"EUR","minor_units":2,"users":[
 {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":4200},
 {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":1000}],
 "payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":800}],
 "authorizations":[{"id":"a_1","from_user_id":"u_bob","to_user_id":"u_ada","amount":500,"status":"open","expires_at":"` +
		FormatTime(time.Now().Add(2*time.Hour)) + `"}]}`
	s := NewStore()
	if e := s.Reset([]byte(fixture)); e != nil {
		t.Fatalf("reset: %v", e.Message)
	}
	var holdAt, payAt string
	s.mu.Lock()
	holdAt, payAt = s.st.Authorizations[0].CreatedAt, s.st.Payments[0].CreatedAt
	s.mu.Unlock()
	view := func(asOf string) map[string]any {
		out, e := s.Exec(func(st *State) (any, *AppError) {
			return st.MeAt("u_bob", MeQuery{AsOf: &asOf}, time.Now())
		})
		if e != nil {
			t.Fatalf("me as_of=%s: %v", asOf, e.Message)
		}
		return decode(t, out)
	}
	t.Logf("seeded payment created_at %s, seeded hold created_at %s (bob balance 1000 = opening 200 + 800 seeded, hold 500)", payAt, holdAt)
	for _, c := range []struct{ name, at string }{{"hold created_at (floor of the reset second)", holdAt}, {"payment created_at (reset instant)", payAt}} {
		v := view(c.at)
		t.Logf("as_of=%s [%s]: total %v held %v available %v", c.at, c.name, v["total"], v["held"], v["available"])
	}
	hold, pay := hsInstant(t, holdAt), hsInstant(t, payAt)
	switch {
	case !hold.Before(pay):
		t.Log("VERDICT: not reproducible on this run (reset landed on a whole second)")
	case view(holdAt)["available"].(float64) < 0:
		t.Log("VERDICT: YES - a view inside [floor(reset second), reset instant) shows available < 0")
	default:
		t.Log("VERDICT: NO")
	}
}
