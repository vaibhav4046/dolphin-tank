package main

import (
	"math/rand"
	"testing"
	"time"
)

// A hold's created_at has the same microsecond precision as payments, so no (as_of, known_at) view
// shows a hold without the money that paid for it. This test checks that over random
// payment/hold/capture/void/correction histories.

func TestHistoricalViewsNeverNegative(t *testing.T) {
	for _, corrections := range []bool{false, true} {
		name := "no corrections"
		if corrections {
			name = "with corrections"
		}
		t.Run(name, func(t *testing.T) {
			negAvail, negTotal, views := 0, 0, 0
			for seed := int64(1); seed <= 40; seed++ {
				rng := rand.New(rand.NewSource(seed))
				bal := [3]int64{9000, 6000, 4000}
				if seed%2 == 0 {
					bal = [3]int64{50000, 30000, 20000}
				}
				_, st := azStore(fgU{"ada", bal[0]}, fgU{"bob", bal[1]}, fgU{"cy", bal[2]})
				handles := []string{"ada", "bob", "cy"}
				now := hsAt(0)
				var pays []*Payment
				var instants []time.Time
				for step := 0; step < 300; step++ {
					now = now.Add(time.Duration(rng.Intn(1500)) * time.Millisecond)
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
							st.Capture(a.ToUserID, a.AuthorizationID, CaptureIn{Amount: &amt, Final: rng.Intn(2) == 0}, now)
						}
					case 4:
						if len(st.Authorizations) > 0 {
							a := st.Authorizations[rng.Intn(len(st.Authorizations))]
							st.Void(a.FromUserID, a.AuthorizationID, now)
						}
					case 5:
						if corrections && len(pays) > 0 {
							p := pays[rng.Intn(len(pays))]
							h := st.revByPay[p.PaymentID]
							eff := FormatMicro(p.created.Add(-time.Duration(rng.Intn(2)) * time.Second))
							st.Correct(p.FromUserID, p.PaymentID, CorrectionIn{h[len(h)-1].Revision, int64(rng.Intn(12000)), eff, "r"}, now)
						}
					}
					instants = append(instants, st.lastStamp)
					for _, a := range st.Authorizations {
						instants = append(instants, a.createdTime(), a.expiresTime())
					}
					for _, r := range st.Revisions[max(0, len(st.Revisions)-3):] {
						instants = append(instants, r.eff, r.rec)
					}
					if step%5 != 0 {
						continue
					}
					pick := func() time.Time {
						return instants[rng.Intn(len(instants))].Add(time.Duration(rng.Intn(3)-1) * time.Microsecond)
					}
					for i := 0; i < 25; i++ {
						T, K := pick(), pick()
						for _, u := range st.Users {
							views++
							total := st.TotalAt(u.ID, T, K)
							if total < 0 {
								negTotal++
							}
							if avail := total - st.HeldAt(u.ID, T, K); avail < 0 {
								negAvail++
								if negAvail < 4 {
									t.Errorf("seed %d step %d: %s available %d at T=%v K=%v", seed, step, u.Handle, avail, T, K)
								}
							}
						}
					}
				}
			}
			if negTotal != 0 || negAvail != 0 {
				t.Fatalf("of %d views: %d negative totals, %d negative available", views, negTotal, negAvail)
			}
			t.Logf("%d views: 0 negative totals, 0 negative available", views)
		})
	}
}

// The smallest case, no correction involved: bob is paid at :00.5 and places a hold at :00.7. The hold's
// created_at is that microsecond, so no view shows the hold without the payment that funded it.
func TestHoldNeverAppearsBeforeTheMoneyThatPaidForIt(t *testing.T) {
	_, st := azStore(fgU{"ada", 1000}, fgU{"bob", 0})
	hsPay(t, st, "ada", "bob", 500, hsAt(500*time.Millisecond))
	a, e := st.Authorize("u_bob", AuthorizeIn{ToHandle: "ada", Amount: 500, Visibility: visPublic}, hsAt(700*time.Millisecond))
	if e != nil {
		t.Fatalf("authorize: %v", e)
	}
	if a.CreatedAt != FormatMicro(hsAt(700*time.Millisecond)) {
		t.Fatalf("created_at %s is not the microsecond the hold was placed", a.CreatedAt)
	}
	now := hsAt(5 * time.Second)
	for _, c := range []struct {
		at                  string
		total, held, avails float64
	}{
		{FormatMicro(hsAt(0)), 0, 0, 0},
		{FormatMicro(hsAt(500 * time.Millisecond)), 500, 0, 500},
		{FormatMicro(hsAt(699999 * time.Microsecond)), 500, 0, 500},
		{a.CreatedAt, 500, 500, 0},
	} {
		me := hsMe(t, st, "bob", hsP(c.at), nil, now)
		if me["total"] != c.total || me["held"] != c.held || me["available"] != c.avails {
			t.Errorf("bob as_of=%s: %v, want total %v held %v available %v", c.at, me, c.total, c.held, c.avails)
		}
	}
	if got := st.AvailableAt("u_bob", hsAt(0), hsAt(5*time.Second)); got != 0 {
		t.Fatalf("AvailableAt at :00.0 = %d", got)
	}
}
