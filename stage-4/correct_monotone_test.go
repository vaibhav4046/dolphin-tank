package main

import (
	"encoding/json"
	"testing"
	"time"
)

// cmFutureStore imports the rich state with the latest revision of one corrected payment recorded an
// hour in the future (hand-crafted state: the clock does not follow it) and returns the store, that
// payment's id, its sender and its latest amount.
func cmFutureStore(t *testing.T, ahead time.Duration) (s *Store, pid, owner string, amount int64, futureRec string) {
	t.Helper()
	good := crRichExport(t)
	futureRec = FormatMicro(time.Now().Add(ahead))
	body := ttMutateExport(t, good, func(_, st map[string]any) {
		revs := st["revisions"].([]any)
		for i := len(revs) - 1; i >= 0; i-- {
			if m := revs[i].(map[string]any); m["revision"].(float64) >= 2 {
				pid = m["payment_id"].(string)
				m["recorded_at"] = futureRec
				return
			}
		}
	})
	if pid == "" {
		t.Fatal("the rich export has no corrected payment")
	}
	s = NewStore()
	if e := s.importAt(body, time.Now()); e != nil {
		t.Fatalf("import of a revision recorded at %s: %v", futureRec, e.Message)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, p := range s.st.Payments {
		if p.PaymentID == pid {
			owner = p.FromUserID
		}
	}
	h := s.st.revByPay[pid]
	return s, pid, owner, h[len(h)-1].Amount, futureRec
}

func cmCorrect(s *Store, owner, pid string, expected, amount int64, now time.Time) (*Revision, *AppError) {
	var rev *Revision
	_, e := s.Exec(func(st *State) (any, *AppError) {
		r, e := st.Correct(owner, pid, CorrectionIn{ExpectedRevision: expected, Amount: amount, EffectiveAt: FormatMicro(now), Reason: "monotone"}, now)
		rev = r
		return r, e
	})
	return rev, e
}

func cmRecorded(t *testing.T, s *Store, pid string) []time.Time {
	t.Helper()
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []time.Time
	for _, r := range s.st.revByPay[pid] {
		out = append(out, hsInstant(t, r.RecordedAt))
	}
	return out
}

func cmAssertIncreasing(t *testing.T, got []time.Time) {
	t.Helper()
	for i := 1; i < len(got); i++ {
		if !got[i].After(got[i-1]) {
			t.Fatalf("recorded times do not strictly increase: %v", got)
		}
	}
}

// Spec: "Recorded times for one payment strictly increase." An import may carry a revision recorded in
// the future; correcting that payment must still append a later revision, and the result must export
// and re-import.
func TestCorrectAfterFutureRecordedRevisionStaysStrictlyIncreasing(t *testing.T) {
	s, pid, owner, amount, futureRec := cmFutureStore(t, time.Hour)
	prev := hsInstant(t, futureRec)
	for step, expected := 0, int64(len(cmRecorded(t, s, pid))); step < 3; step, expected = step+1, expected+1 {
		now := time.Now()
		amount--
		if amount < 0 {
			amount = 1
		}
		rev, e := cmCorrect(s, owner, pid, expected, amount, now)
		if e != nil {
			t.Fatalf("step %d: correction of a payment whose latest revision is recorded in the future: %d %s", step, e.Status, e.Message)
		}
		rec := hsInstant(t, rev.RecordedAt)
		if !rec.After(prev) {
			t.Fatalf("step %d: recorded_at %s is not after the previous revision's %s", step, rev.RecordedAt, FormatMicro(prev))
		}
		if rev.Revision != expected+1 || rev.Amount != amount {
			t.Fatalf("step %d: revision %d amount %d, want %d amount %d", step, rev.Revision, rev.Amount, expected+1, amount)
		}
		prev = rec
	}
	cmAssertIncreasing(t, cmRecorded(t, s, pid))

	out, ae := s.Export()
	if ae != nil {
		t.Fatal(ae.Message)
	}
	if e := NewStore().importAt(out, time.Now()); e != nil {
		t.Fatalf("export after the corrections does not re-import: %d %s", e.Status, e.Message)
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	latest := s.st.revByPay[pid][len(s.st.revByPay[pid])-1]
	if got := s.st.ReadNow(time.Now()); !got.After(latest.rec) {
		t.Fatalf("a read beginning after the 201 starts at %s, which does not see the revision recorded at %s", FormatMicro(got), latest.RecordedAt)
	}
	if sel := s.st.selected(pid, s.st.ReadNow(time.Now())); sel != latest {
		t.Fatalf("a read after the correction selects revision %d, want %d", sel.Revision, latest.Revision)
	}
}

// A rejected correction leaves no trace: it must not carry the clock out to a future recorded time.
func TestRejectedCorrectionDoesNotMoveClockToFutureRevision(t *testing.T) {
	s, pid, owner, amount, _ := cmFutureStore(t, time.Hour)
	before := crSkew(s)
	if _, e := cmCorrect(s, owner, pid, 1, amount+1, time.Now()); e == nil || e.Status != 409 {
		t.Fatalf("stale expected_revision must be 409, got %v", e)
	}
	if sk := crSkew(s); sk > crSkewLimit {
		t.Fatalf("a rejected correction left the clock %v ahead (was %v)", sk, before)
	}
}

// A normal payment keeps the stamp as its recorded time and the clock stays on the stamp.
func TestCorrectPastRevisionRecordsAtTheStamp(t *testing.T) {
	_, st := azStore(fgU{"ada", 10000}, fgU{"bob", 0})
	p := hsPay(t, st, "ada", "bob", 1000, hsAt(0))
	r := crMust(t, st, "ada", p, crIn(1, 1500, crT0, "raise"), hsAt(time.Minute))
	if want := FormatMicro(hsAt(time.Minute)); r.RecordedAt != want {
		t.Fatalf("recorded_at %s, want the stamp %s", r.RecordedAt, want)
	}
	if !st.lastStamp.Equal(hsAt(time.Minute)) {
		t.Fatalf("lastStamp %s moved off the stamp", FormatMicro(st.lastStamp))
	}
	// Two corrections inside one clock tick are still strictly ordered.
	r2 := crMust(t, st, "ada", p, crIn(2, 1400, crT0, "lower"), hsAt(time.Minute))
	if !hsInstant(t, r2.RecordedAt).After(hsInstant(t, r.RecordedAt)) {
		t.Fatalf("same-tick corrections: %s then %s", r.RecordedAt, r2.RecordedAt)
	}
	if !st.lastStamp.Equal(hsInstant(t, r2.RecordedAt)) {
		t.Fatalf("lastStamp %s is not the newest recorded instant %s", FormatMicro(st.lastStamp), r2.RecordedAt)
	}
}

// The fixed-up recorded time is a whole microsecond even when the stored previous one is finer.
func TestCorrectAfterNanosecondRecordedRevisionIsStrictlyLater(t *testing.T) {
	s, pid, owner, amount, _ := cmFutureStore(t, time.Hour)
	s.mu.Lock()
	h := s.st.revByPay[pid]
	last := h[len(h)-1]
	last.rec = last.rec.Add(123 * time.Nanosecond)
	last.RecordedAt = last.rec.Format(time.RFC3339Nano)
	s.mu.Unlock()
	next := amount - 1
	if amount == 0 {
		next = 1
	}
	rev, e := cmCorrect(s, owner, pid, last.Revision, next, time.Now())
	if e != nil {
		t.Fatalf("%d %s", e.Status, e.Message)
	}
	if !hsInstant(t, rev.RecordedAt).After(last.rec) {
		t.Fatalf("recorded_at %s is not after %s", rev.RecordedAt, last.RecordedAt)
	}
	raw, _ := json.Marshal(rev)
	if got := decode(t, raw)["recorded_at"]; got != rev.RecordedAt {
		t.Fatalf("wire recorded_at %v != %s", got, rev.RecordedAt)
	}
}
