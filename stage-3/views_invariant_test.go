package main

import (
	"math/rand"
	"testing"
	"time"
)

// A correction the overdraft check allowed must never leave any (as_of, known_at) view with a negative
// total or negative available.
func TestViewsNeverNegativeUnderCorrections(t *testing.T) {
	var views, negTotal, negAvail, accepted, histRejected int
	for seed := int64(1); seed <= 40; seed++ {
		rng := rand.New(rand.NewSource(seed))
		bal := [3]int64{9000, 6000, 4000}
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
				if len(pays) > 0 {
					p := pays[rng.Intn(len(pays))]
					h := st.revByPay[p.PaymentID]
					eff := FormatMicro(p.created.Add(-time.Duration(rng.Intn(2)) * time.Second))
					in := CorrectionIn{h[len(h)-1].Revision, int64(rng.Intn(12000)), eff, "r"}
					switch _, e := st.Correct(p.FromUserID, p.PaymentID, in, now); {
					case e == nil:
						accepted++
					case e.Code == "historical_overdraft":
						histRejected++
					}
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
				at, known := pick(), pick()
				for _, u := range st.Users {
					views++
					total := st.TotalAt(u.ID, at, known)
					if total < 0 {
						negTotal++
					}
					if total-st.HeldAt(u.ID, at, known) < 0 {
						negAvail++
					}
				}
			}
		}
	}
	t.Logf("views %d, corrections accepted %d, rejected historical_overdraft %d", views, accepted, histRejected)
	if negTotal != 0 || negAvail != 0 {
		t.Errorf("negative views: total %d, available %d of %d", negTotal, negAvail, views)
	}
	if accepted == 0 || histRejected == 0 {
		t.Errorf("run does not exercise the check: accepted %d, rejected %d", accepted, histRejected)
	}
}
