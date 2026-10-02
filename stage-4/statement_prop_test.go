package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/rand"
	"sort"
	"testing"
	"time"
)

// Property test: random payment / correction / authorization / settlement sequences, with an
// independent brute-force oracle written from the spec text (no MovementsFor, revByPay or HeldAt).
// Everything runs on a virtual clock so instants are exact and ties are common.

var (
	tsUserIDs  = []string{"u_ada", "u_bob", "u_cy", "u_dee"}
	tsHandles  = []string{"ada", "bob", "cy", "dee"}
	tsInfinity = time.Date(9000, 1, 1, 0, 0, 0, 0, time.UTC)
)

type tsWorld struct {
	t      *testing.T
	seed   int64
	r      *rand.Rand
	s      *Store
	vt     time.Time   // virtual now
	pool   []time.Time // instants worth reusing as effective_at / window edges
	seeded int64
	snaps  []tsSnapCheck
	ops    int
}

type tsSnapCheck struct {
	token, user string
	limit       int
	pages       [][]byte
}

func (w *tsWorld) failf(format string, a ...any) {
	w.t.Helper()
	w.t.Fatalf("seed %d, after %d ops: %s", w.seed, w.ops, fmt.Sprintf(format, a...))
}

func (w *tsWorld) with(f func(st *State)) {
	w.s.mu.Lock()
	defer w.s.mu.Unlock()
	f(w.s.st)
}

func (w *tsWorld) tick() time.Time {
	switch w.r.Intn(4) {
	case 0: // same microsecond neighbourhood: stamps must still be strictly increasing
	case 1:
		w.vt = w.vt.Add(time.Duration(w.r.Intn(5)) * time.Microsecond)
	case 2:
		w.vt = w.vt.Add(time.Duration(1+w.r.Intn(2_000_000)) * time.Microsecond)
	default:
		w.vt = w.vt.Add(time.Duration(1+w.r.Intn(20)) * time.Second)
	}
	return w.vt
}

func tsGenFixture(r *rand.Rand) (string, int64, []time.Time) {
	bal := make([]int64, 4)
	for i := range bal {
		bal[i] = int64(300 + r.Intn(1200))
	}
	start := time.Date(2026, 9, 20, 8, 0, 0, 0, time.UTC)
	var pays []string
	var pool []time.Time
	at := start
	for i, n := 1, r.Intn(14); i <= n; i++ {
		if r.Intn(3) > 0 { // ties are common
			at = at.Add(time.Duration(r.Intn(3600)) * time.Second).Add(time.Duration(r.Intn(1000)) * time.Microsecond)
		}
		from := r.Intn(4)
		if bal[from] < 1 {
			continue
		}
		to := (from + 1 + r.Intn(3)) % 4
		amount := int64(1 + r.Intn(int(min(bal[from], 400))))
		bal[from] -= amount
		bal[to] += amount
		form := []string{FormatMicro(at), at.Format(time.RFC3339Nano), at.In(time.FixedZone("z", 7200)).Format("2006-01-02T15:04:05.000000-07:00")}[r.Intn(3)]
		pays = append(pays, tsSeedPay(fmt.Sprintf("p_%d", i), tsHandles[from], tsHandles[to], amount, form))
		pool = append(pool, at)
	}
	var total int64
	for _, b := range bal {
		total += b
	}
	return tsFxU([4]int64{bal[0], bal[1], bal[2], bal[3]}, `"authorization_ttl_seconds":90`, tsPays(pays...)), total, pool
}

func tsNewWorld(t *testing.T, seed int64) *tsWorld {
	r := rand.New(rand.NewSource(seed))
	fixture, total, pool := tsGenFixture(r)
	s := NewStore()
	if e := s.Reset([]byte(fixture)); e != nil {
		t.Fatalf("seed %d: reset: %v\n%s", seed, e.Message, fixture)
	}
	return &tsWorld{t: t, seed: seed, r: r, s: s, vt: time.Now().UTC().Add(time.Minute).Truncate(time.Microsecond), pool: pool, seeded: total}
}

func tsFormatInstant(r *rand.Rand, at time.Time) string {
	switch r.Intn(3) {
	case 0:
		return FormatMicro(at)
	case 1:
		return at.Format("2006-01-02T15:04:05.000000Z")
	}
	return at.In(time.FixedZone("z", 3600*(r.Intn(9)-4))).Format("2006-01-02T15:04:05.000000-07:00")
}

func (w *tsWorld) someInstant() time.Time {
	var at time.Time
	switch w.r.Intn(5) {
	case 0, 1:
		if len(w.pool) > 0 {
			at = w.pool[w.r.Intn(len(w.pool))]
			break
		}
		fallthrough
	case 2:
		at = time.Date(2026, 9, 20, 7, 0, 0, 0, time.UTC).Add(time.Duration(w.r.Int63n(int64(w.vt.Sub(time.Date(2026, 9, 20, 7, 0, 0, 0, time.UTC))))))
	case 3:
		at = w.vt.Add(-time.Duration(w.r.Intn(30)) * time.Second)
	default:
		at = w.vt
	}
	at = at.Add(time.Duration(w.r.Intn(3)-1) * time.Microsecond).UTC().Truncate(time.Microsecond)
	if at.After(w.vt) {
		at = w.vt
	}
	return at
}

// step performs one random operation on the virtual clock and checks failures leave no trace.
func (w *tsWorld) step() {
	w.ops++
	now := w.tick()
	w.pool = append(w.pool, now)
	var before []byte
	if b, e := w.s.Export(); e == nil {
		before = b
	}
	var aerr *AppError
	op := w.r.Intn(100)
	w.with(func(st *State) {
		switch {
		case op < 28:
			from, to := w.r.Intn(4), w.r.Intn(4)
			if from == to {
				to = (to + 1) % 4
			}
			_, aerr = st.Pay(tsUserIDs[from], PaymentIn{ToHandle: tsHandles[to], Amount: int64(1 + w.r.Intn(300)), Visibility: visPublic}, now)
		case op < 62:
			aerr = w.correctRandom(st, now)
		case op < 72:
			from, to := w.r.Intn(4), w.r.Intn(4)
			if from == to {
				to = (to + 1) % 4
			}
			_, aerr = st.Authorize(tsUserIDs[from], AuthorizeIn{ToHandle: tsHandles[to], Amount: int64(1 + w.r.Intn(250)), Visibility: visPublic}, now)
		case op < 82:
			aerr = w.captureRandom(st, now)
		case op < 88:
			if len(st.Authorizations) > 0 {
				a := st.Authorizations[w.r.Intn(len(st.Authorizations))]
				_, aerr = st.Void(a.FromUserID, a.AuthorizationID, now)
			}
		case op < 94:
			_, aerr = trSettle(st, ttBody(w.t, w.settlementBody()), now)
		default:
			// a read: statements and /me never change money
		}
	})
	if aerr != nil {
		switch aerr.Code {
		case "insufficient_funds", "historical_overdraft", "stale_revision", "linked_payment_immutable",
			"authorization_expired", "authorization_not_open", "capture_exceeds_authorization":
		default:
			w.failf("unexpected error %d %s: %s (op %d)", aerr.Status, aerr.Code, aerr.Message, op)
		}
		if after, e := w.s.Export(); e != nil || !bytes.Equal(before, after) {
			w.failf("a refused operation (%s, op %d) left a trace in the exported state", aerr.Code, op)
		}
	}
}

func (w *tsWorld) settlementBody() string {
	n := 1 + w.r.Intn(3)
	var legs []string
	for i := 0; i < n; i++ {
		from, to := w.r.Intn(4), w.r.Intn(4)
		if from == to {
			to = (to + 1) % 4
		}
		legs = append(legs, ttLeg(tsHandles[from], tsHandles[to], 1+w.r.Intn(120)))
	}
	return ttTransfers(legs...)
}

func (w *tsWorld) correctRandom(st *State, now time.Time) *AppError {
	if len(st.Payments) == 0 {
		return nil
	}
	p := st.Payments[w.r.Intn(len(st.Payments))]
	hist := st.revByPay[p.PaymentID]
	latest := hist[len(hist)-1]
	expected := latest.Revision
	if w.r.Intn(10) == 0 {
		expected += int64(1 + w.r.Intn(2))
	}
	var amount int64
	switch w.r.Intn(5) {
	case 0:
		amount = 0
	case 1:
		amount = latest.Amount
	default:
		amount = int64(w.r.Intn(int(2*latest.Amount) + 2))
	}
	eff := tsFormatInstant(w.r, w.someInstant())
	effT, _ := ParseInstant(eff)
	want := w.oVerdict(st, p, expected, amount, effT, now)
	rev, e := st.Correct(p.FromUserID, p.PaymentID, CorrectionIn{ExpectedRevision: expected, Amount: amount, EffectiveAt: eff, Reason: "r"}, now)
	tsVerdicts[want]++
	if got := tsCode(e); got != want {
		w.failf("correct %s (expected_revision %d, amount %d, effective_at %s): got %q, the oracle says %q", p.PaymentID, expected, amount, eff, got, want)
	}
	if e == nil {
		w.pool = append(w.pool, rev.rec)
		if rev.Revision != latest.Revision+1 || rev.EffectiveAt != eff || rev.Amount != amount {
			w.failf("revision returned %+v for expected %d amount %d eff %s", rev, expected, amount, eff)
		}
	}
	return e
}

func (w *tsWorld) captureRandom(st *State, now time.Time) *AppError {
	if len(st.Authorizations) == 0 {
		return nil
	}
	a := st.Authorizations[w.r.Intn(len(st.Authorizations))]
	in := CaptureIn{Final: w.r.Intn(3) == 0}
	if w.r.Intn(3) > 0 {
		amt := int64(1 + w.r.Intn(int(a.Amount)))
		if rem := a.Amount - a.CapturedAmount; amt > rem && rem > 0 {
			amt = rem
		}
		in.Amount = &amt
	}
	_, e := st.Capture(a.ToUserID, a.AuthorizationID, in, now)
	return e
}

// ---- the oracle: straight from the spec text -------------------------------------------------

// tsVerdicts tallies what the oracle decided for every random correction, so the test can prove it
// exercised accepts and every refusal.
var tsVerdicts = map[string]int{}

func tsCode(e *AppError) string {
	if e == nil {
		return ""
	}
	return e.Code
}

// oVerdict is what Correct must answer, decided without Correct's helpers: refusal order is linked,
// stale, current funds, then the historical check of both wallets with the candidate applied.
func (w *tsWorld) oVerdict(st *State, p *Payment, expected, amount int64, eff, now time.Time) string {
	stamp := now.UTC().Truncate(time.Microsecond)
	if floor := st.lastStamp.Add(time.Microsecond); floor.After(stamp) {
		stamp = floor
	}
	if p.SettlementID != nil || p.AuthorizationID != nil {
		return "linked_payment_immutable"
	}
	latest := w.oSel(st, p.PaymentID, tsInfinity)
	if expected != latest.Revision {
		return "stale_revision"
	}
	debited, moved := p.FromUserID, amount-latest.Amount
	if moved < 0 {
		debited, moved = p.ToUserID, -moved
	}
	if moved > 0 && w.oTotal(st, debited, tsInfinity, tsInfinity)-w.oHeldPlaced(st, debited, stamp, tsInfinity, true) < moved {
		return "insufficient_funds"
	}
	for _, wallet := range []string{p.FromUserID, p.ToUserID} {
		if w.oOverdrawn(st, wallet, p, amount, eff, stamp) {
			return "historical_overdraft"
		}
	}
	return ""
}

// oOverdrawn: with payment p replaced by (amount, eff) and everything else at its latest revision, is
// the wallet's total or available negative at any boundary up to now?
func (w *tsWorld) oOverdrawn(st *State, uid string, p *Payment, amount int64, eff, now time.Time) bool {
	type move struct {
		at    time.Time
		delta int64
	}
	var moves []move
	for _, q := range st.Payments {
		if q.FromUserID != uid && q.ToUserID != uid {
			continue
		}
		amt, at := w.oSel(st, q.PaymentID, tsInfinity).Amount, oInstant(w, w.oSel(st, q.PaymentID, tsInfinity).EffectiveAt)
		if q == p {
			amt, at = amount, eff
		}
		var d int64
		if q.ToUserID == uid {
			d += amt
		}
		if q.FromUserID == uid {
			d -= amt
		}
		moves = append(moves, move{at, d})
	}
	var bounds []time.Time
	for _, m := range moves {
		bounds = append(bounds, m.at)
	}
	for _, a := range st.Authorizations {
		if a.FromUserID != uid {
			continue
		}
		created := oInstant(w, a.CreatedAt)
		if a.CreatedExact != nil {
			created = oInstant(w, *a.CreatedExact)
		}
		bounds = append(bounds, created, oInstant(w, a.ExpiresAt))
		if a.ClosedAt != nil {
			bounds = append(bounds, oInstant(w, *a.ClosedAt))
		}
		for _, pid := range a.PaymentIDs {
			bounds = append(bounds, oInstant(w, st.payByID[pid].CreatedAt))
		}
	}
	for _, b := range bounds {
		if b.After(now) {
			continue
		}
		total := st.userByID(uid).OpeningBalance
		for _, m := range moves {
			if !m.at.After(b) {
				total += m.delta
			}
		}
		if total < 0 || total-w.oHeldPlaced(st, uid, b, tsInfinity, true) < 0 {
			return true
		}
	}
	return false
}

type oEntry struct {
	id           string
	delta, after int64
	rev          int64
	eff, rec     string
	amount       int64
}

func oInstant(w *tsWorld, s string) time.Time {
	t, ok := ParseInstant(s)
	if !ok {
		w.failf("stored instant %q does not parse", s)
	}
	return t
}

// oSel is sel(p, k): the latest revision of the payment recorded at or before k.
func (w *tsWorld) oSel(st *State, pid string, k time.Time) *Revision {
	var sel *Revision
	for _, r := range st.Revisions {
		if r.PaymentID == pid && !oInstant(w, r.RecordedAt).After(k) {
			sel = r
		}
	}
	return sel
}

type oMove struct {
	p     *Payment
	r     *Revision
	delta int64
	eff   time.Time
}

func (w *tsWorld) oMoves(st *State, uid string, k time.Time) []oMove {
	var out []oMove
	for _, p := range st.Payments {
		if p.FromUserID != uid && p.ToUserID != uid {
			continue
		}
		r := w.oSel(st, p.PaymentID, k)
		if r == nil {
			continue
		}
		var d int64
		if p.ToUserID == uid {
			d += r.Amount
		}
		if p.FromUserID == uid {
			d -= r.Amount
		}
		out = append(out, oMove{p, r, d, oInstant(w, r.EffectiveAt)})
	}
	sort.SliceStable(out, func(i, j int) bool {
		if !out[i].eff.Equal(out[j].eff) {
			return out[i].eff.Before(out[j].eff)
		}
		return out[i].p.PaymentID < out[j].p.PaymentID
	})
	return out
}

func (w *tsWorld) oTotal(st *State, uid string, t, k time.Time) int64 {
	total := st.userByID(uid).OpeningBalance
	for _, m := range w.oMoves(st, uid, k) {
		if !m.eff.After(t) {
			total += m.delta
		}
	}
	return total
}

// oHeld is rule H of the stage-3 spec, per authorization the user placed.
func (w *tsWorld) oHeld(st *State, uid string, t, k time.Time) int64 {
	return w.oHeldPlaced(st, uid, t, k, false)
}

// oHeldPlaced is oHeld; placed puts each hold at the microsecond it was made rather than its
// whole-second created_at (a payment and a hold within one second would otherwise look like a
// hold that was never affordable, with no correction involved).
func (w *tsWorld) oHeldPlaced(st *State, uid string, t, k time.Time, placed bool) int64 {
	known := t
	if k.Before(known) {
		known = k
	}
	var held int64
	for _, a := range st.Authorizations {
		if a.FromUserID != uid {
			continue
		}
		created := oInstant(w, a.CreatedAt)
		if placed && a.CreatedExact != nil {
			created = oInstant(w, *a.CreatedExact)
		}
		if created.After(t) || created.After(k) {
			continue
		}
		if !t.Before(oInstant(w, a.ExpiresAt)) {
			continue
		}
		if a.Status != authOpen && a.ClosedAt != nil && !oInstant(w, *a.ClosedAt).After(known) {
			continue
		}
		rem := a.Amount
		for _, pid := range a.PaymentIDs {
			for _, p := range st.Payments {
				if p.PaymentID == pid && !oInstant(w, p.CreatedAt).After(known) {
					rem -= p.Amount
				}
			}
		}
		held += rem
	}
	return held
}

func (w *tsWorld) oStatement(st *State, uid string, from *time.Time, to, k time.Time) (opening, closing int64, entries []oEntry) {
	opening = st.userByID(uid).OpeningBalance
	bal := opening
	for _, m := range w.oMoves(st, uid, k) {
		if !m.eff.Before(to) {
			continue
		}
		bal += m.delta
		if from != nil && m.eff.Before(*from) {
			opening = bal
			continue
		}
		entries = append(entries, oEntry{m.p.PaymentID, m.delta, bal, m.r.Revision, m.r.EffectiveAt, m.r.RecordedAt, m.r.Amount})
	}
	return opening, bal, entries
}

// ---- checks ---------------------------------------------------------------------------------

func (w *tsWorld) statement(st *State, uid string, q StatementQuery) tsStmt {
	body, e := st.Statement(uid, q, w.vt)
	if e != nil {
		w.failf("statement %s: %v", tsQueryString(q), e.Message)
	}
	b, err := MarshalJSON(body)
	if err != nil {
		w.failf("marshal: %v", err)
	}
	var out tsStmt
	if err := json.Unmarshal(b, &out); err != nil {
		w.failf("unmarshal: %v", err)
	}
	out.raw = b
	return out
}

func strp(s string) *string { return &s }

func tsQueryString(q StatementQuery) string {
	val := func(p *string) string {
		if p == nil {
			return "-"
		}
		return *p
	}
	return fmt.Sprintf("{from %s to %s known_at %s snapshot %s limit %d offset %d}", val(q.From), val(q.To), val(q.KnownAt), val(q.Snapshot), q.Limit, q.Offset)
}

// checkStatement compares a statement with the oracle and the /me history primitives.
func (w *tsWorld) checkStatement(st *State, uid string, from, to, known *time.Time) {
	q := StatementQuery{Limit: 200}
	if from != nil {
		q.From = strp(tsFormatInstant(w.r, *from))
	}
	if to != nil {
		q.To = strp(tsFormatInstant(w.r, *to))
	}
	k := st.ReadNow(w.vt)
	if known != nil {
		q.KnownAt = strp(tsFormatInstant(w.r, *known))
		k = *known
	}
	got := w.statement(st, uid, q)
	toT := st.ReadNow(w.vt)
	if to != nil {
		toT = *to
	}
	fromT := from
	if from != nil && to == nil && from.After(toT) {
		toT = *from
	}
	opening, closing, want := w.oStatement(st, uid, fromT, toT, k)
	label := fmt.Sprintf("user %s window [%v, %v) known %v", uid, q.From, q.To, q.KnownAt)
	if got.OpeningBalance != opening || got.ClosingBalance != closing {
		w.failf("%s: opening/closing %d/%d, oracle %d/%d", label, got.OpeningBalance, got.ClosingBalance, opening, closing)
	}
	if len(got.Entries) != len(want) || got.HasMore {
		w.failf("%s: %d entries (has_more %v), oracle %d", label, len(got.Entries), got.HasMore, len(want))
	}
	var sum int64
	for i, en := range got.Entries {
		o := want[i]
		sum += en.Delta
		if en.Payment["payment_id"] != o.id || en.Delta != o.delta || en.BalanceAfter != o.after || en.Revision != o.rev ||
			en.EffectiveAt != o.eff || en.RecordedAt != o.rec || int64(en.Payment["amount"].(float64)) != o.amount {
			w.failf("%s: entry %d is %+v, oracle %+v", label, i, en, o)
		}
	}
	if got.OpeningBalance+sum != got.ClosingBalance {
		w.failf("%s: opening %d + deltas %d != closing %d", label, got.OpeningBalance, sum, got.ClosingBalance)
	}
	// Edges equal /me as_of one microsecond before (every instant here is a whole microsecond).
	me := func(t time.Time) int64 {
		body, e := st.MeAt(uid, MeQuery{AsOf: strp(FormatMicro(t)), KnownAt: strp(FormatMicro(k))}, w.vt)
		if e != nil {
			w.failf("MeAt: %v", e.Message)
		}
		b, _ := MarshalJSON(body)
		var m map[string]any
		_ = json.Unmarshal(b, &m)
		return int64(m["total"].(float64))
	}
	if from != nil && me(from.Add(-time.Microsecond)) != got.OpeningBalance {
		w.failf("%s: opening %d != /me as_of from-1us (%d)", label, got.OpeningBalance, me(from.Add(-time.Microsecond)))
	}
	if from == nil && got.OpeningBalance != st.userByID(uid).OpeningBalance {
		w.failf("%s: default opening %d is not the wallet's opening balance", label, got.OpeningBalance)
	}
	if to != nil && !(from != nil && to.Before(*from)) && me(to.Add(-time.Microsecond)) != got.ClosingBalance {
		w.failf("%s: closing %d != /me as_of to-1us (%d)", label, got.ClosingBalance, me(to.Add(-time.Microsecond)))
	}
	if to == nil && from == nil && known == nil && got.ClosingBalance != st.userByID(uid).Balance {
		w.failf("%s: default closing %d is not the balance %d", label, got.ClosingBalance, st.userByID(uid).Balance)
	}
	// Entries ending a tie group: balance_after is the wallet total at that instant.
	for i, en := range got.Entries {
		this := oInstant(w, en.EffectiveAt)
		if i+1 < len(got.Entries) && oInstant(w, got.Entries[i+1].EffectiveAt).Equal(this) {
			continue
		}
		if from != nil && this.Before(*from) {
			continue
		}
		if tot := w.oTotal(st, uid, this, k); tot != en.BalanceAfter && from == nil {
			w.failf("%s: entry %d balance_after %d != total at its instant %d", label, i, en.BalanceAfter, tot)
		}
	}
}

// checkWorld verifies the invariants that must hold after every operation.
func (w *tsWorld) checkWorld() {
	w.with(func(st *State) {
		rn := st.ReadNow(w.vt)
		var sum int64
		for _, u := range st.Users {
			if u.Balance < 0 {
				w.failf("negative balance %d for %s", u.Balance, u.ID)
			}
			sum += u.Balance
			if st.Held(u.ID, rn) > u.Balance {
				w.failf("held %d above balance %d for %s", st.Held(u.ID, rn), u.Balance, u.ID)
			}
			if st.HeldAt(u.ID, rn, rn) != st.Held(u.ID, rn) {
				w.failf("HeldAt(now,now) %d != Held(now) %d for %s", st.HeldAt(u.ID, rn, rn), st.Held(u.ID, rn), u.ID)
			}
		}
		if sum != w.seeded {
			w.failf("sum of balances %d, seeded %d", sum, w.seeded)
		}
		// Revision history shape.
		next := map[string]int64{}
		lastRec := map[string]time.Time{}
		for _, r := range st.Revisions {
			next[r.PaymentID]++
			if r.Revision != next[r.PaymentID] {
				w.failf("revisions of %s are not 1..n: %d at position %d", r.PaymentID, r.Revision, next[r.PaymentID])
			}
			rec := oInstant(w, r.RecordedAt)
			if r.Revision > 1 && !rec.After(lastRec[r.PaymentID]) {
				w.failf("recorded_at of %s does not strictly increase", r.PaymentID)
			}
			lastRec[r.PaymentID] = rec
		}
		for _, p := range st.Payments {
			if next[p.PaymentID] == 0 {
				w.failf("payment %s has no revision", p.PaymentID)
			}
		}
		// Latest revisions + opening = balance.
		for _, u := range st.Users {
			if w.oTotal(st, u.ID, tsInfinity, tsInfinity) != u.Balance {
				w.failf("opening + latest revisions %d != balance %d for %s", w.oTotal(st, u.ID, tsInfinity, tsInfinity), u.Balance, u.ID)
			}
		}
		// Nobody was ever negative: total and available at every past boundary under all known revisions.
		for _, u := range st.Users {
			var bounds []time.Time
			for _, m := range w.oMoves(st, u.ID, tsInfinity) {
				bounds = append(bounds, m.eff)
			}
			for _, a := range st.Authorizations {
				if a.FromUserID != u.ID {
					continue
				}
				bounds = append(bounds, oInstant(w, a.CreatedAt), oInstant(w, a.ExpiresAt))
				if a.CreatedExact != nil {
					bounds = append(bounds, oInstant(w, *a.CreatedExact))
				}
				if a.ClosedAt != nil {
					bounds = append(bounds, oInstant(w, *a.ClosedAt))
				}
				for _, pid := range a.PaymentIDs {
					bounds = append(bounds, oInstant(w, st.payByID[pid].CreatedAt))
				}
			}
			for _, b := range bounds {
				if b.After(rn) {
					continue
				}
				total, held := w.oTotal(st, u.ID, b, tsInfinity), w.oHeldPlaced(st, u.ID, b, tsInfinity, true)
				if total < 0 || total-held < 0 {
					w.failf("%s at %s: total %d held %d (negative total or available in the past)", u.ID, FormatMicro(b), total, held)
				}
				if got := st.TotalAt(u.ID, b, tsInfinity); got != total {
					w.failf("TotalAt %d != oracle %d for %s at %s", got, total, u.ID, FormatMicro(b))
				}
				if got, want := st.HeldAt(u.ID, b, tsInfinity), w.oHeld(st, u.ID, b, tsInfinity); got != want {
					w.failf("HeldAt %d != oracle %d for %s at %s", got, want, u.ID, FormatMicro(b))
				}
			}
		}
		// Random views: totals conserve money, HeldAt/TotalAt agree with the oracle.
		for i := 0; i < 4; i++ {
			t, k := w.someInstant(), w.someInstant()
			if w.r.Intn(4) == 0 {
				t = tsInfinity.Add(-time.Hour)
			}
			if w.r.Intn(4) == 0 {
				k = tsInfinity
			}
			var viewSum int64
			for _, u := range st.Users {
				got, want := st.TotalAt(u.ID, t, k), w.oTotal(st, u.ID, t, k)
				if got != want {
					w.failf("TotalAt(%s, %s, %s) = %d, oracle %d", u.ID, FormatMicro(t), FormatMicro(k), got, want)
				}
				if h, o := st.HeldAt(u.ID, t, k), w.oHeld(st, u.ID, t, k); h != o {
					w.failf("HeldAt(%s, %s, %s) = %d, oracle %d", u.ID, FormatMicro(t), FormatMicro(k), h, o)
				}
				viewSum += got
			}
			if viewSum != w.seeded {
				w.failf("view as_of %s known_at %s: totals sum to %d, seeded %d", FormatMicro(t), FormatMicro(k), viewSum, w.seeded)
			}
		}
		// Statements: default, random window, random known_at.
		for _, uid := range tsUserIDs {
			w.checkStatement(st, uid, nil, nil, nil)
			a, b := w.someInstant(), w.someInstant()
			if b.Before(a) {
				a, b = b, a
			}
			k := w.someInstant()
			w.checkStatement(st, uid, &a, &b, nil)
			w.checkStatement(st, uid, &a, nil, nil)
			w.checkStatement(st, uid, nil, &b, &k)
			w.checkStatement(st, uid, &a, &b, &k)
			w.checkStatement(st, uid, &a, &a, nil)
		}
	})
}

// takeSnapshot reads a whole statement through paging and remembers the exact bytes.
func (w *tsWorld) takeSnapshot() {
	uid := tsUserIDs[w.r.Intn(4)]
	limit := 1 + w.r.Intn(5)
	var sc tsSnapCheck
	w.with(func(st *State) {
		first := w.statement(st, uid, StatementQuery{Limit: limit})
		sc = tsSnapCheck{token: first.Snapshot, user: uid, limit: limit}
	})
	sc.pages = w.pageSnapshot(sc)
	w.snaps = append(w.snaps, sc)
}

func (w *tsWorld) pageSnapshot(sc tsSnapCheck) [][]byte {
	var pages [][]byte
	w.with(func(st *State) {
		for off := 0; ; off += sc.limit {
			p := w.statement(st, sc.user, StatementQuery{Snapshot: &sc.token, Limit: sc.limit, Offset: off})
			pages = append(pages, p.raw)
			if !p.HasMore {
				break
			}
		}
	})
	return pages
}

func (w *tsWorld) checkSnapshots() {
	for _, sc := range w.snaps {
		got := w.pageSnapshot(sc)
		if len(got) != len(sc.pages) {
			w.failf("snapshot %s of %s now has %d pages, had %d", sc.token, sc.user, len(got), len(sc.pages))
		}
		for i := range got {
			if !bytes.Equal(got[i], sc.pages[i]) {
				w.failf("snapshot %s of %s page %d changed:\n%s\n%s", sc.token, sc.user, i, sc.pages[i], got[i])
			}
		}
	}
}

func TestStatementPropertyRandomSequences(t *testing.T) {
	seeds, steps := 14, 90
	if testing.Short() {
		seeds, steps = 4, 40
	}
	clear(tsVerdicts)
	for seed := int64(1); seed <= int64(seeds); seed++ {
		w := tsNewWorld(t, seed)
		w.checkWorld()
		for i := 0; i < steps; i++ {
			w.step()
			if i%3 == 0 {
				w.checkWorld()
			}
			if w.r.Intn(6) == 0 {
				w.takeSnapshot()
			}
			if i%10 == 0 {
				w.checkSnapshots()
			}
		}
		w.checkWorld()
		w.checkSnapshots()
		// An export of any state imports back byte for byte.
		e1, _ := w.s.Export()
		s2 := NewStore()
		if e := s2.importAt(e1, w.s.st.ReadNow(w.vt)); e != nil {
			w.failf("import of the final export: %v", e.Message)
		}
		if e2, _ := s2.Export(); !bytes.Equal(e1, e2) {
			w.failf("export -> import -> export differs")
		}
		corrections := 0
		w.with(func(st *State) { corrections = len(st.Revisions) - len(st.Payments) })
		t.Logf("seed %d: %d payments, %d corrections, %d authorizations, %d snapshots", seed, ttPaymentCount(w.s), corrections, len(w.s.st.Authorizations), len(w.snaps))
	}
	t.Logf("oracle verdicts over every random correction attempt: %v", tsVerdicts)
	if !testing.Short() {
		for _, code := range []string{"", "historical_overdraft", "insufficient_funds", "stale_revision", "linked_payment_immutable"} {
			if tsVerdicts[code] < 5 {
				t.Errorf("the random corrections hardly ever end in %q (%d): the differential check proves little", code, tsVerdicts[code])
			}
		}
	}
}

func TestStatementPropertyMarkerForEmptyHistory(t *testing.T) {
	// Degenerate worlds (no seeded payments) still satisfy every invariant.
	w := tsNewWorld(t, 4242)
	w.pool = nil
	w.checkWorld()
	for i := 0; i < 30; i++ {
		w.step()
	}
	w.checkWorld()
}
