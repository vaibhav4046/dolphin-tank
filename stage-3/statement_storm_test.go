package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/rand"
	"reflect"
	"sync"
	"testing"
	"time"
)

// Statements and snapshot pages read while payments, corrections, holds, captures and voids run from
// many goroutines. Observers fail on: a sum of balances that moved, a negative total or available,
// opening + deltas != closing, an entry whose balance_after is not the running total, and a snapshot
// page that differs from its first read.

type stormSnap struct {
	token, user string
	full        tsStmt // the whole frozen statement, first read
}

func TestStatementSnapshotStorm(t *testing.T) {
	handles := []string{"ada", "bob", "cy", "dee"}
	s, _ := azStore(fgU{"ada", 400000}, fgU{"bob", 400000}, fgU{"cy", 400000}, fgU{"dee", 400000})
	const total = 1600000
	dur := 600 * time.Millisecond
	if testing.Short() {
		dur = 250 * time.Millisecond
	}

	stop := make(chan struct{})
	var stopOnce sync.Once
	var failMu sync.Mutex
	failure := ""
	fail := func(format string, a ...any) {
		failMu.Lock()
		if failure == "" {
			failure = fmt.Sprintf(format, a...)
		}
		failMu.Unlock()
		stopOnce.Do(func() { close(stop) })
	}
	var wg sync.WaitGroup
	worker := func(seed int64, pause time.Duration, f func(r *rand.Rand, i int)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r := rand.New(rand.NewSource(seed))
			for i := 0; ; i++ {
				select {
				case <-stop:
					return
				default:
					f(r, i)
					time.Sleep(pause)
				}
			}
		}()
	}

	var counts struct {
		sync.Mutex
		pays, corrections, auths, snaps, pages int
	}
	bump := func(f func()) { counts.Lock(); f(); counts.Unlock() }
	tolerated := map[string]bool{
		"insufficient_funds": true, "historical_overdraft": true, "stale_revision": true, "linked_payment_immutable": true,
		"authorization_expired": true, "authorization_not_open": true, "capture_exceeds_authorization": true,
	}
	check := func(what string, e *AppError) bool {
		if e == nil {
			return true
		}
		if !tolerated[e.Code] {
			fail("%s: unexpected %d %s: %s", what, e.Status, e.Code, e.Message)
		}
		return false
	}

	read := func(user string, q StatementQuery) (tsStmt, *AppError) {
		b, e := s.Exec(func(st *State) (any, *AppError) { return st.Statement(user, q, time.Now()) })
		if e != nil {
			return tsStmt{}, e
		}
		var out tsStmt
		if err := json.Unmarshal(b, &out); err != nil {
			fail("unmarshal statement: %v", err)
		}
		out.raw = b
		return out, nil
	}
	checkStatement := func(label string, st tsStmt) {
		run := st.OpeningBalance
		var prevAt time.Time
		prevID := ""
		for i, en := range st.Entries {
			run += en.Delta
			if run != en.BalanceAfter {
				fail("%s: entry %d balance_after %d, running total %d", label, i, en.BalanceAfter, run)
				return
			}
			at, ok := ParseInstant(en.EffectiveAt)
			id, _ := en.Payment["payment_id"].(string)
			if !ok || at.Before(prevAt) || (at.Equal(prevAt) && id < prevID) {
				fail("%s: entry %d (%s at %s) out of order after %s at %v", label, i, id, en.EffectiveAt, prevID, prevAt)
				return
			}
			prevAt, prevID = at, id
		}
		if run != st.ClosingBalance {
			fail("%s: opening %d + deltas = %d, closing %d", label, st.OpeningBalance, run, st.ClosingBalance)
		}
	}

	for w := 0; w < 4; w++ {
		w := w
		worker(int64(100+w), 2*time.Millisecond, func(r *rand.Rand, i int) {
			_, e := s.Exec(func(st *State) (any, *AppError) {
				return st.Pay("u_"+handles[w], PaymentIn{ToHandle: handles[(w+1+r.Intn(3))%4], Amount: int64(1 + r.Intn(60)), Visibility: visPublic}, time.Now())
			})
			if check("pay", e) {
				bump(func() { counts.pays++ })
			}
		})
	}
	for w := 0; w < 3; w++ {
		w := w
		worker(int64(200+w), time.Millisecond, func(r *rand.Rand, i int) {
			_, e := s.Exec(func(st *State) (any, *AppError) {
				if len(st.Payments) == 0 {
					return struct{}{}, nil
				}
				p := st.Payments[r.Intn(len(st.Payments))]
				h := st.revByPay[p.PaymentID]
				expected := h[len(h)-1].Revision
				if r.Intn(8) == 0 {
					expected++
				}
				eff := p.CreatedAt
				if r.Intn(2) == 0 {
					eff = FormatMicro(time.Now().Add(-time.Duration(r.Intn(400)) * time.Millisecond))
				}
				return st.Correct(p.FromUserID, p.PaymentID, CorrectionIn{ExpectedRevision: expected, Amount: int64(r.Intn(150)), EffectiveAt: eff, Reason: "storm"}, time.Now())
			})
			if check("correct", e) {
				bump(func() { counts.corrections++ })
			}
		})
	}
	for w := 0; w < 2; w++ {
		w := w
		worker(int64(300+w), 2*time.Millisecond, func(r *rand.Rand, i int) {
			_, e := s.Exec(func(st *State) (any, *AppError) {
				from, to := handles[w], handles[(w+2)%4]
				a, e := st.Authorize("u_"+from, AuthorizeIn{ToHandle: to, Amount: int64(1 + r.Intn(300)), Visibility: visPublic}, time.Now())
				if e != nil {
					return nil, e
				}
				amt := int64(1 + r.Intn(100))
				switch r.Intn(3) {
				case 0:
					st.Capture("u_"+to, a.AuthorizationID, CaptureIn{Amount: &amt, Final: r.Intn(2) == 0}, time.Now())
				case 1:
					st.Void("u_"+from, a.AuthorizationID, time.Now())
				}
				return a, nil
			})
			if check("authorize", e) {
				bump(func() { counts.auths++ })
			}
		})
	}

	var snapMu sync.Mutex
	var snaps []*stormSnap
	for w := 0; w < 3; w++ {
		w := w
		worker(int64(400+w), 2*time.Millisecond, func(r *rand.Rand, i int) {
			user := "u_" + handles[r.Intn(4)]
			q := StatementQuery{Limit: 1 + r.Intn(4)}
			if r.Intn(2) == 0 { // a recent window keeps the snapshots small; the other half is the whole history
				q.From = strp(FormatMicro(time.Now().Add(-200 * time.Millisecond)))
			}
			first, e := read(user, q)
			if e != nil {
				fail("first statement read: %v", e)
				return
			}
			full, e := read(user, StatementQuery{Snapshot: &first.Snapshot, Limit: 1 << 30})
			if e != nil {
				fail("snapshot read: %v", e)
				return
			}
			checkStatement("snapshot", full)
			if full.OpeningBalance != first.OpeningBalance || full.ClosingBalance != first.ClosingBalance ||
				!reflect.DeepEqual(first.Entries, full.Entries[:min(len(first.Entries), len(full.Entries))]) {
				fail("first page of snapshot %s is not the head of the snapshot", first.Snapshot)
				return
			}
			snapMu.Lock()
			snaps = append(snaps, &stormSnap{token: first.Snapshot, user: user, full: full})
			snapMu.Unlock()
			bump(func() { counts.snaps++ })
		})
	}
	for w := 0; w < 4; w++ {
		worker(int64(500+w), time.Millisecond, func(r *rand.Rand, i int) {
			snapMu.Lock()
			if len(snaps) == 0 {
				snapMu.Unlock()
				return
			}
			sn := snaps[r.Intn(len(snaps))]
			snapMu.Unlock()
			again, e := read(sn.user, StatementQuery{Snapshot: &sn.token, Limit: 1 << 30})
			if e != nil {
				fail("snapshot %s vanished: %v", sn.token, e)
				return
			}
			if !bytes.Equal(again.raw, sn.full.raw) {
				fail("snapshot %s changed:\n%s\n%s", sn.token, sn.full.raw, again.raw)
				return
			}
			limit, offset := 1+r.Intn(5), r.Intn(len(sn.full.Entries)+3)
			page, e := read(sn.user, StatementQuery{Snapshot: &sn.token, Limit: limit, Offset: offset})
			if e != nil {
				fail("snapshot page: %v", e)
				return
			}
			n := len(sn.full.Entries)
			want := []tsEntry{}
			if offset < n {
				want = sn.full.Entries[offset:min(offset+limit, n)]
			}
			if !reflect.DeepEqual(page.Entries, want) || page.HasMore != (offset+limit < n) ||
				page.OpeningBalance != sn.full.OpeningBalance || page.ClosingBalance != sn.full.ClosingBalance {
				fail("snapshot %s page limit %d offset %d of %d entries differs from its first read (has_more %v)", sn.token, limit, offset, n, page.HasMore)
				return
			}
			bump(func() { counts.pages++ })
		})
	}
	for w := 0; w < 2; w++ {
		worker(int64(600+w), time.Millisecond, func(r *rand.Rand, i int) {
			_, e := s.Exec(func(st *State) (any, *AppError) {
				if err := hsCheck(st, total, time.Now()); err != nil {
					fail("observer: %v", err)
				}
				return struct{}{}, nil
			})
			check("observer", e)
			user := "u_" + handles[r.Intn(4)]
			q := StatementQuery{Limit: 1 << 30}
			if r.Intn(4) > 0 {
				q.From = strp(FormatMicro(time.Now().Add(-time.Duration(r.Intn(300)) * time.Millisecond)))
			}
			full, e := read(user, q)
			if e != nil {
				fail("observer statement: %v", e)
				return
			}
			checkStatement("observer", full)
		})
	}

	time.AfterFunc(dur, func() { stopOnce.Do(func() { close(stop) }) })
	wg.Wait()
	if failure != "" {
		t.Fatal(failure)
	}
	if err := func() error {
		s.mu.Lock()
		defer s.mu.Unlock()
		return hsCheck(s.st, total, time.Now())
	}(); err != nil {
		t.Fatal(err)
	}
	counts.Lock()
	defer counts.Unlock()
	t.Logf("storm: %d payments, %d corrections, %d authorizations, %d snapshots, %d snapshot page checks", counts.pays, counts.corrections, counts.auths, counts.snaps, counts.pages)
	if counts.pays < 30 || counts.corrections < 3 || counts.auths < 3 || counts.snaps < 10 || counts.pages < 30 {
		t.Fatalf("storm too weak to mean anything: %+v", struct{ P, C, A, S, G int }{counts.pays, counts.corrections, counts.auths, counts.snaps, counts.pages})
	}
}
