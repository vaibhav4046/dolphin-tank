package main

import (
	"math/rand"
	"testing"
	"time"
)

// A hold's created_at is a whole second while payments carry microseconds. Read literally (rule H on
// created_at), a view taken between the second's start and a payment of the same second can show a
// hold that was only affordable thanks to that payment: negative available with no correction at all.
// Placing the hold at its exact microsecond (what Correct's overdraft check does) never goes negative.
// This test pins both facts over random payment/hold/capture/void/correction histories.

func TestHistoricalViewsNeverNegativeWhenHoldsAreExactlyPlaced(t *testing.T) {
	for _, corrections := range []bool{false, true} {
		name := "no corrections"
		if corrections {
			name = "with corrections"
		}
		t.Run(name, func(t *testing.T) {
			literal, exact, negTotal, views := 0, 0, 0, 0
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
							if total-st.HeldAt(u.ID, T, K) < 0 {
								literal++
							}
							if total-st.heldAt(u.ID, T, K, true) < 0 {
								exact++
								if exact < 4 {
									t.Errorf("seed %d step %d: %s available %d at T=%v K=%v with holds placed exactly", seed, step, u.Handle, total-st.heldAt(u.ID, T, K, true), T, K)
								}
							}
						}
					}
				}
			}
			if negTotal != 0 || exact != 0 {
				t.Fatalf("of %d views: %d negative totals, %d negative available (exact placement)", views, negTotal, exact)
			}
			t.Logf("%d views: 0 negative totals, 0 negative available with exact hold placement; %d negative available under whole-second created_at", views, literal)
		})
	}
}
