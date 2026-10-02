package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"
)

// F1 (trace): no seeded or imported value may push the service clock into the future. The clock is
// st.ReadNow/Stamp, which never runs behind lastStamp, and lastStamp is rebuilt from every recorded
// instant by ReindexAt. A seeded stored-expired hold with a future expires_at used to get that
// deadline as its closed_at, so a stage-2 fixture that was valid ratcheted the clock hours ahead.

const crSkewLimit = 100 * time.Millisecond // honest clocks differ by microseconds, the slack is 50ms; the defect was hours

// crSkew is how far ahead of the real clock a read or write would now be stamped.
func crSkew(s *Store) time.Duration {
	now := time.Now()
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.st.ReadNow(now).Sub(now)
}

func crUser(id, handle string, balance int64) string {
	return fmt.Sprintf(`{"id":"u_%s","email":"%s@example.com","password":"correct horse","display_name":"%s","handle":"%s","balance":%d}`,
		id, id, strings.ToUpper(id[:1])+id[1:], handle, balance)
}

func crHold(id, status string, amount int64, expires, rest string) string {
	s := fmt.Sprintf(`{"id":%q,"from_user_id":"u_ada","to_user_id":"u_bob","amount":%d,"note":"seed","visibility":"public","status":%q,"expires_at":%q`, id, amount, status, expires)
	if rest != "" {
		s += "," + rest
	}
	return s + "}"
}

// crJuryFixture is the jury's reproduction: ada 10000, bob 2500, cy 0, an open hold a1 of 2000 and
// a stored-expired hold a4 of 4000, both with the same deadline.
func crJuryFixture(expires string, holds ...string) string {
	if holds == nil {
		holds = []string{crHold("a1", "open", 2000, expires, ""), crHold("a4", "expired", 4000, expires, "")}
	}
	return `{"currency":"EUR","minor_units":2,"users":[` + strings.Join([]string{crUser("ada", "ada", 10000), crUser("bob", "bob", 2500), crUser("cy", "cy", 0)}, ",") +
		`],"authorizations":[` + strings.Join(holds, ",") + `]}`
}

func crServer(t testing.TB, fixture string) (http.Handler, map[string]string, *Store) {
	t.Helper()
	s := NewStore()
	h := NewServer(s)
	if rec := txDo(h, "POST", "/_test/reset", "", "", fixture); rec.Code != 204 {
		t.Fatalf("reset: %d %s", rec.Code, rec.Body)
	}
	tok := map[string]string{}
	for _, n := range []string{"ada", "bob", "cy"} {
		rec := txDo(h, "POST", "/auth/login", "", "", `{"email":"`+n+`@example.com","password":"correct horse"}`)
		tok[n], _ = txJSON(t, rec.Body.Bytes())["token"].(string)
		if rec.Code != 200 || tok[n] == "" {
			t.Fatalf("login %s: %d %s", n, rec.Code, rec.Body)
		}
	}
	return h, tok, s
}

func crNear(t testing.TB, what, instant string) {
	t.Helper()
	at, ok := ParseInstant(instant)
	if !ok {
		t.Fatalf("%s: %q is not an instant", what, instant)
	}
	if d := at.Sub(time.Now()); d > crSkewLimit || d < -time.Minute {
		t.Fatalf("%s = %s is %v from now, want within seconds", what, instant, d)
	}
}

func crHolds(t testing.TB, h http.Handler, token string) map[string]map[string]any {
	t.Helper()
	b := txWant(t, "GET /authorizations", txDo(h, "GET", "/authorizations?limit=100", token, "", ""), 200)
	var out struct {
		Authorizations []map[string]any `json:"authorizations"`
	}
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	byID := map[string]map[string]any{}
	for _, a := range out.Authorizations {
		byID[a["authorization_id"].(string)] = a
	}
	return byID
}

// The jury's fixture, call for call: stage 2 gave held=2000 available=8000, capture 201, pay 8001 -> 409.
func TestSeededExpiredHoldWithFutureDeadlineKeepsStage2Behaviour(t *testing.T) {
	for name, expires := range map[string]string{
		"two hours ahead": FormatTime(time.Now().Add(2 * time.Hour)),
		"far future":      txFuture,
	} {
		t.Run(name, func(t *testing.T) {
			h, tok, s := crServer(t, crJuryFixture(expires))
			if sk := crSkew(s); sk > crSkewLimit {
				t.Fatalf("the clock is %v ahead right after reset", sk)
			}
			me := txMe(t, h, tok["ada"])
			if txNum(me, "held") != 2000 || txNum(me, "available") != 8000 || txNum(me, "total") != 10000 {
				t.Fatalf("/me: %v, want held 2000 available 8000 total 10000", me)
			}
			capRec := txDo(h, "POST", "/authorizations/a1/capture", tok["bob"], "k-cap", `{"amount":800,"final":false}`)
			if capRec.Code != 201 {
				t.Fatalf("capture of the seeded open hold: %d %s, want 201", capRec.Code, capRec.Body)
			}
			txWantErr(t, "pay 8001 with available 8000", txDo(h, "POST", "/payments", tok["ada"], "k-over", `{"to_handle":"cy","amount":8001}`), 409, "insufficient_funds")
			pay := txWant(t, "pay 8000", txDo(h, "POST", "/payments", tok["ada"], "k-fit", `{"to_handle":"cy","amount":8000}`), 201)
			crNear(t, "payment.created_at", txJSON(t, pay)["created_at"].(string))
			if sk := crSkew(s); sk > crSkewLimit {
				t.Fatalf("the clock is %v ahead after the writes", sk)
			}

			// The open hold is still open (it is not read as expired at once) and takes its second capture.
			if st := crHolds(t, h, tok["ada"])["a1"]["status"]; st != "open" {
				t.Fatalf("a1 status %v, want open", st)
			}
			txWant(t, "second capture", txDo(h, "POST", "/authorizations/a1/capture", tok["bob"], "k-cap2", `{"amount":100,"final":false}`), 201)

			// The stored-expired hold reports a closed_at that is not in the future.
			a4 := crHolds(t, h, tok["ada"])["a4"]
			if a4["status"] != "expired" {
				t.Fatalf("a4 status %v, want expired", a4["status"])
			}
			crNear(t, "a4.closed_at", a4["closed_at"].(string))
		})
	}
}

// I2: closed_at of a seeded expired hold is min(expires_at, reset), never before created_at, and the
// hold keeps holding nothing in every view.
func TestSeededExpiredHoldClosedAtNeverAfterReset(t *testing.T) {
	before := time.Now().Add(-time.Second)
	explicitCreated := FormatMicro(time.Now().Add(-1500 * time.Microsecond))
	soonAfter := FormatTime(time.Now().Add(time.Hour + 5*time.Second))
	for _, c := range []struct {
		name, expires, rest string
		wantExpiresAt       bool // closed_at is expires_at exactly as written
	}{
		{"deadline in the past", FormatTime(time.Now().Add(-2 * time.Hour)), "", true},
		{"deadline two hours ahead", FormatTime(time.Now().Add(2 * time.Hour)), "", false},
		{"deadline just over an hour ahead", soonAfter, "", false},
		{"deadline 2099", txFuture, "", false},
		{"explicit created_at with microseconds", FormatTime(time.Now().Add(2 * time.Hour)), `"created_at":"` + explicitCreated + `"`, false},
		{"explicit past created_at", FormatTime(time.Now().Add(2 * time.Hour)), `"created_at":"` + FormatTime(time.Now().Add(-3*time.Hour)) + `"`, false},
	} {
		t.Run(c.name, func(t *testing.T) {
			raw := `{"currency":"EUR","users":[` + crUser("ada", "ada", 10000) + `,` + crUser("bob", "bob", 0) + `],"authorizations":[` + crHold("a_x", "expired", 500, c.expires, c.rest) + `]}`
			s := txReset(t, raw)
			after := time.Now().Add(time.Second)
			s.mu.Lock()
			defer s.mu.Unlock()
			a := s.st.authByID["a_x"]
			if a.Status != authExpired || a.ClosedAt == nil {
				t.Fatalf("stored status %q closed_at %v", a.Status, a.ClosedAt)
			}
			if c.wantExpiresAt {
				if *a.ClosedAt != a.ExpiresAt {
					t.Fatalf("closed_at %s, want expires_at %s as written", *a.ClosedAt, a.ExpiresAt)
				}
				return
			}
			closed, ok := ParseInstant(*a.ClosedAt)
			if !ok {
				t.Fatalf("closed_at %q is not an instant", *a.ClosedAt)
			}
			if closed.Before(before) || closed.After(after) {
				t.Fatalf("closed_at %s is not the reset instant (reset between %s and %s)", *a.ClosedAt, before, after)
			}
			if closed.Before(a.createdTime()) {
				t.Fatalf("closed_at %s is before created_at %s", *a.ClosedAt, a.CreatedAt)
			}
			if a.expiresTime().Before(closed) {
				t.Fatalf("closed_at %s is after expires_at %s", *a.ClosedAt, a.ExpiresAt)
			}
		})
	}
}

// Stored-expired holds hold nothing in any view: the states with and without a4 answer HeldAt alike.
func TestSeededExpiredHoldHoldsNothingInAnyView(t *testing.T) {
	expires := FormatTime(time.Now().Add(2 * time.Hour))
	with := txReset(t, crJuryFixture(expires))
	without := txReset(t, crJuryFixture(expires, crHold("a1", "open", 2000, expires, "")))
	now := time.Now()
	instants := []time.Time{now.Add(-3 * time.Hour), now.Add(-time.Second), now, now.Add(time.Second), now.Add(time.Hour), now.Add(2*time.Hour - time.Second), now.Add(2 * time.Hour), now.Add(3 * time.Hour), histInf}
	with.mu.Lock()
	defer with.mu.Unlock()
	without.mu.Lock()
	defer without.mu.Unlock()
	for _, u := range []string{"u_ada", "u_bob", "u_cy"} {
		for _, at := range instants {
			for _, k := range instants {
				if a, b := with.st.HeldAt(u, at, k), without.st.HeldAt(u, at, k); a != b {
					t.Fatalf("HeldAt(%s, %s, %s) = %d with the expired hold, %d without", u, FormatMicro(at), FormatMicro(k), a, b)
				}
			}
		}
		if a, b := with.st.Held(u, now), without.st.Held(u, now); a != b {
			t.Fatalf("Held(%s) = %d with the expired hold, %d without", u, a, b)
		}
	}
	if with.st.Held("u_ada", now.Add(3*time.Hour)) != 0 {
		t.Fatal("every hold has expired three hours on")
	}
	if with.st.Held("u_ada", now) != 2000 {
		t.Fatalf("held now %d, want only the open hold's 2000", with.st.Held("u_ada", now))
	}
}

// A stored-open hold whose deadline passes keeps deriving closed_at = expires_at at read time and
// never changes the stored hold.
func TestStoredOpenHoldStillDerivesClosedAtFromItsDeadline(t *testing.T) {
	expires := FormatTime(time.Now().Add(2 * time.Hour))
	s := txReset(t, crJuryFixture(expires))
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.st.authByID["a1"]
	before := *a
	late := time.Now().Add(3 * time.Hour)
	b := s.st.authBody(a, late)
	if b.Status != authExpired || b.ClosedAt == nil || *b.ClosedAt != expires {
		t.Fatalf("a1 read three hours on: status %s closed_at %v, want expired at %s", b.Status, b.ClosedAt, expires)
	}
	if a.Status != authOpen || a.ClosedAt != nil || a.closed != before.closed {
		t.Fatalf("reading a hold past its deadline changed the stored hold: %+v", a)
	}
	if now := time.Now(); s.st.authBody(a, now).ClosedAt != nil || s.st.authBody(a, now).Status != authOpen {
		t.Fatal("a1 must still be open now")
	}
}

// An import of a stage-2 style export: an expired-status hold with a deadline two hours ahead.
func TestImportedExpiredHoldWithFutureDeadlineKeepsClockAndHolds(t *testing.T) {
	for name, expires := range map[string]string{
		"two hours ahead": FormatTime(time.Now().Add(2 * time.Hour)),
		"far future":      txFuture,
	} {
		t.Run(name, func(t *testing.T) {
			created := FormatTime(time.Now().Add(-time.Minute))
			body := ttMutateExport(t, tyReadExport(t), func(_, st map[string]any) {
				st["authorizations"] = append(st["authorizations"].([]any), map[string]any{
					"authorization_id": "a_exp_future", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100,
					"captured_amount": 0, "note": "", "visibility": "public", "status": "expired", "expires_at": expires,
					"payment_ids": []any{}, "created_at": created,
				})
			})
			s := NewStore()
			h := NewServer(s)
			txWant(t, "import", txDo(h, "POST", "/_test/import", "", "", string(body)), 204)
			if sk := crSkew(s); sk > crSkewLimit {
				t.Fatalf("the clock is %v ahead right after import", sk)
			}
			pay := txWant(t, "next payment", txDo(h, "POST", "/payments", tyAdaToken, "k-next", `{"to_handle":"bob","amount":1}`), 201)
			crNear(t, "payment.created_at", txJSON(t, pay)["created_at"].(string))
			hold := txWant(t, "next authorization", txDo(h, "POST", "/authorizations", tyAdaToken, "k-auth", `{"to_handle":"bob","amount":1}`), 201)
			crNear(t, "authorization.created_at", txJSON(t, hold)["created_at"].(string))
			txWant(t, "capture of the seeded open hold", txDo(h, "POST", "/authorizations/a_seed_open/capture", tyCyToken, "k-cap", `{"amount":50,"final":false}`), 201)

			a := crHolds(t, h, tyAdaToken)["a_exp_future"]
			if a["status"] != "expired" || a["closed_at"] == nil {
				t.Fatalf("a_exp_future: %v", a)
			}
			closed := a["closed_at"].(string)
			crNear(t, "a_exp_future.closed_at", closed)
			if c, _ := ParseInstant(closed); c.Before(hsInstant(t, created)) {
				t.Fatalf("closed_at %s is before created_at %s", closed, created)
			}

			// The migrated state round-trips byte for byte and the hold stays out of every held figure.
			e1 := txExport(t, s)
			txWant(t, "re-import", txDo(h, "POST", "/_test/import", "", "", string(e1)), 204)
			if e2 := txExport(t, s); string(e1) != string(e2) {
				t.Fatal("export -> import -> export differs after the migration")
			}
			if sk := crSkew(s); sk > crSkewLimit {
				t.Fatalf("the clock is %v ahead after re-import", sk)
			}
		})
	}
}

// crReport records one probe in the sweep's table.
type crReport struct{ rejected, accepted []string }

func (r *crReport) log(t *testing.T, title string) {
	t.Helper()
	t.Logf("%s\n  rejected 422 (%d): %s\n  accepted    (%d): %s", title, len(r.rejected), strings.Join(r.rejected, "; "), len(r.accepted), strings.Join(r.accepted, "; "))
}

// I1 on Reset: whatever a fixture seeds, the clock right after reset is the real clock.
func TestResetNeverMovesTheClockAhead(t *testing.T) {
	now := time.Now()
	fut, past := FormatTime(now.Add(2*time.Hour)), FormatTime(now.Add(-2*time.Hour))
	paid := func(rest string) string {
		return `"payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":100` + rest + `}]`
	}
	base := func(extra ...string) string {
		parts := append([]string{`"currency":"EUR"`, `"users":[` + crUser("ada", "ada", 10000) + `,` + crUser("bob", "bob", 2500) + `]`}, extra...)
		return "{" + strings.Join(parts, ",") + "}"
	}
	auths := func(items ...string) string { return `"authorizations":[` + strings.Join(items, ",") + `]` }
	cases := []struct {
		name, raw  string
		wantReject bool
	}{
		{"expired deadline +2h", base(auths(crHold("a", "expired", 10, fut, ""))), false},
		{"expired deadline 2099", base(auths(crHold("a", "expired", 10, txFuture, ""))), false},
		{"expired deadline -2h", base(auths(crHold("a", "expired", 10, past, ""))), false},
		{"open deadline +2h", base(auths(crHold("a", "open", 10, fut, ""))), false},
		{"open deadline -2h", base(auths(crHold("a", "open", 10, past, ""))), false},
		{"captured deadline +2h", base(auths(crHold("a", "captured", 10, fut, ""))), false},
		{"captured deadline 2099", base(auths(crHold("a", "captured", 10, txFuture, ""))), false},
		{"voided deadline +2h", base(auths(crHold("a", "voided", 10, fut, ""))), false},
		{"voided deadline 2099", base(auths(crHold("a", "voided", 10, txFuture, ""))), false},
		{"expired +2h with past created_at", base(auths(crHold("a", "expired", 10, fut, `"created_at":"`+past+`"`))), false},
		{"payment created_at +2h", base(paid(`,"created_at":"` + fut + `"`)), true},
		{"payment created_at 2099", base(paid(`,"created_at":"` + txFuture + `"`)), true},
		{"hold created_at +2h", base(auths(crHold("a", "open", 10, fut, `"created_at":"`+fut+`"`))), true},
		{"hold created_at +2h, expired", base(auths(crHold("a", "expired", 10, fut, `"created_at":"`+fut+`"`))), true},
		{"hold created_at 2099, voided", base(auths(crHold("a", "voided", 10, txFuture, `"created_at":"`+txFuture+`"`))), true},
	}
	var rep crReport
	for _, c := range cases {
		s := NewStore()
		e := s.Reset([]byte(c.raw))
		if c.wantReject {
			if e == nil || e.Status != 422 {
				t.Errorf("%s: want 422, got %v", c.name, e)
			}
			rep.rejected = append(rep.rejected, c.name)
			continue
		}
		if e != nil {
			t.Errorf("%s: reset refused: %d %s", c.name, e.Status, e.Message)
			continue
		}
		sk := crSkew(s)
		rep.accepted = append(rep.accepted, fmt.Sprintf("%s (skew %v)", c.name, sk.Round(time.Millisecond)))
		if sk > crSkewLimit {
			t.Errorf("%s: the clock is %v ahead of the real clock right after reset", c.name, sk)
		}
	}
	rep.log(t, "Reset: fixtures with a future value")
}

// crRichState is a stage-3 export with API activity of this run: payments, a correction (revision 2),
// holds with created_exact in every closed shape, and an open one.
func crRichExport(t testing.TB) []byte {
	t.Helper()
	_, good := tyRichState(t)
	return good
}

type crPosition struct{ coll, field string }

var crInstantPositions = []crPosition{
	{"payments", "created_at"},
	{"requests", "created_at"},
	{"revisions", "recorded_at"},
	{"revisions", "effective_at"},
	{"authorizations", "created_at"},
	{"authorizations", "closed_at"},
	{"authorizations", "expires_at"},
	{"authorizations", "created_exact"},
}

// crFutureEach calls fn once per (collection item, field) of every position that is present on that
// item, with the item's field set to value in a copy of raw, and gives fn the position's label.
func crFutureEach(t testing.TB, raw []byte, value string, fn func(label string, body []byte)) {
	t.Helper()
	var probe map[string]any
	if err := json.Unmarshal(raw, &probe); err != nil {
		t.Fatal(err)
	}
	st := probe["state"].(map[string]any)
	for _, pos := range crInstantPositions {
		items, _ := st[pos.coll].([]any)
		for i, it := range items {
			if m, _ := it.(map[string]any); m == nil || m[pos.field] == nil {
				continue
			}
			label := fmt.Sprintf("%s[%d].%s", pos.coll, i, pos.field)
			body := ttMutateExport(t, raw, func(_, state map[string]any) {
				item := state[pos.coll].([]any)[i].(map[string]any)
				item[pos.field] = value
				// A held created_exact must stay inside created_at's second; move both together.
				if pos.coll == "authorizations" && pos.field == "created_at" && item["created_exact"] != nil {
					item["created_exact"] = value
				}
				if pos.coll == "authorizations" && pos.field == "created_exact" {
					item["created_at"] = value
				}
			})
			fn(label, body)
		}
	}
}

// I1 on Import (stage-3 export): every instant-bearing field of the export set two hours ahead, one
// at a time. Whatever is accepted must not move the clock.
func TestImportNeverMovesTheClockAheadStage3Export(t *testing.T) {
	good := crRichExport(t)
	fut := FormatMicro(time.Now().Add(2 * time.Hour))
	s := NewStore()
	if e := s.Import(good); e != nil {
		t.Fatal(e.Message)
	}
	var rep crReport
	n := 0
	crFutureEach(t, good, fut, func(label string, body []byte) {
		n++
		e := s.importAt(body, time.Now())
		if e != nil {
			if e.Status != 422 {
				t.Errorf("%s: want 422 or success, got %d %s", label, e.Status, e.Message)
			}
			rep.rejected = append(rep.rejected, label)
		} else {
			sk := crSkew(s)
			rep.accepted = append(rep.accepted, fmt.Sprintf("%s (skew %v)", label, sk.Round(time.Millisecond)))
			if sk > crSkewLimit {
				t.Errorf("%s: imported with a future value, the clock is now %v ahead", label, sk)
			}
		}
		if e := s.Import(good); e != nil {
			t.Fatalf("restore after %s: %v", label, e.Message)
		}
	})
	if n < 20 {
		t.Fatalf("sweep visited only %d positions", n)
	}
	rep.log(t, fmt.Sprintf("Import of a stage-3 export, %d positions set to +2h", n))
}

// I1 on Import (stage-2 export, migrated): a payment's or a hold's created_at and a deadline two hours
// ahead, plus an expired-status hold with a future deadline.
func TestImportNeverMovesTheClockAheadStage2Export(t *testing.T) {
	raw := tyReadExport(t)
	fut := FormatTime(time.Now().Add(2 * time.Hour))
	s := NewStore()
	var rep crReport
	n := 0
	crFutureEach(t, raw, fut, func(label string, body []byte) {
		n++
		e := s.importAt(body, time.Now())
		if e != nil {
			if e.Status != 422 {
				t.Errorf("%s: want 422 or success, got %d %s", label, e.Status, e.Message)
			}
			rep.rejected = append(rep.rejected, label)
			return
		}
		sk := crSkew(s)
		rep.accepted = append(rep.accepted, fmt.Sprintf("%s (skew %v)", label, sk.Round(time.Millisecond)))
		if sk > crSkewLimit {
			t.Errorf("%s: imported with a future value, the clock is now %v ahead", label, sk)
		}
	})
	// Every closed shape of hold with a future deadline in a stage-2 export (expired is the one that broke).
	for _, status := range []string{"expired", "captured", "voided", "open"} {
		for _, exp := range []string{fut, txFuture} {
			label := fmt.Sprintf("new %s hold, deadline %s", status, exp[:4])
			body := ttMutateExport(t, raw, func(_, st map[string]any) {
				st["authorizations"] = append(st["authorizations"].([]any), map[string]any{
					"authorization_id": "a_new", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 10,
					"captured_amount": 0, "note": "", "visibility": "public", "status": status, "expires_at": exp,
					"payment_ids": []any{}, "created_at": FormatTime(time.Now().Add(-time.Minute)),
				})
			})
			n++
			if e := s.importAt(body, time.Now()); e != nil {
				rep.rejected = append(rep.rejected, label)
				continue
			}
			sk := crSkew(s)
			rep.accepted = append(rep.accepted, fmt.Sprintf("%s (skew %v)", label, sk.Round(time.Millisecond)))
			if sk > crSkewLimit {
				t.Errorf("%s: the clock is now %v ahead", label, sk)
			}
		}
	}
	rep.log(t, fmt.Sprintf("Import of a stage-2 export, %d probes", n))
}

// The reindex itself, below the import checks: a hand-built state with any recorded instant in the
// future gets a clock that is not ahead of the reindex instant, and an honest state keeps resuming
// strictly after its newest recorded instant.
func TestReindexClockIgnoresInstantsAfterNow(t *testing.T) {
	good := crRichExport(t)
	load := func() *State {
		var env trEnvelope
		if err := json.Unmarshal(good, &env); err != nil {
			t.Fatal(err)
		}
		return env.State
	}
	now := time.Now()
	fut := FormatMicro(now.Add(2 * time.Hour))

	honest := load()
	if err := honest.ReindexAt(now); err != nil {
		t.Fatal(err)
	}
	newest := time.Time{}
	for _, p := range honest.Payments {
		newest = laterOf(newest, p.created)
	}
	for _, r := range honest.Revisions {
		newest = laterOf(newest, r.rec)
	}
	for _, a := range honest.Authorizations {
		newest = laterOf(newest, a.created)
		newest = laterOf(newest, a.closed)
	}
	if got := honest.Stamp(now.Add(-time.Hour)); !got.After(newest) {
		t.Fatalf("an honest state must stamp after its newest recorded instant %s, got %s", newest, got)
	}

	// Honest stamps may lead a coarse wall clock by a few microseconds: reindexed at an instant
	// just before its newest write, the state must still stamp and read after that write.
	burst := load()
	justBefore := newest.Add(-3 * time.Microsecond)
	if err := burst.ReindexAt(justBefore); err != nil {
		t.Fatal(err)
	}
	if got := burst.ReadNow(justBefore); !got.After(newest) {
		t.Fatalf("a read just before the newest write (%s) must still follow it, got %s", newest, got)
	}

	set := map[string]func(st *State){
		"payment created_at":   func(st *State) { st.Payments[0].CreatedAt = fut },
		"revision recorded_at": func(st *State) { st.Revisions[len(st.Revisions)-1].RecordedAt = fut },
		"hold created_at": func(st *State) {
			st.Authorizations[len(st.Authorizations)-1].CreatedAt, st.Authorizations[len(st.Authorizations)-1].CreatedExact = fut, &fut
		},
		"voided hold closed_at":   func(st *State) { crCloseLast(st, authVoided, fut) },
		"captured hold closed_at": func(st *State) { crCloseLast(st, authCaptured, fut) },
		"expired hold closed_at":  func(st *State) { crCloseLast(st, authExpired, fut) },
	}
	for name, mut := range set {
		st := load()
		mut(st)
		if err := st.ReindexAt(now); err != nil {
			t.Logf("%s: rejected by ReindexAt (%v)", name, err)
			continue
		}
		if st.lastStamp.After(now.Add(clockSlack)) {
			t.Errorf("%s: lastStamp %s is after the reindex instant %s plus the %v slack", name, st.lastStamp.Format(time.RFC3339Nano), now.Format(time.RFC3339Nano), clockSlack)
		}
		if got := st.ReadNow(now); got.Sub(now) > crSkewLimit {
			t.Errorf("%s: ReadNow is %v ahead", name, got.Sub(now))
		}
	}
}

func laterOf(a, b time.Time) time.Time {
	if b.After(a) {
		return b
	}
	return a
}

// crCloseLast closes the last hold with the given stored status at the given instant.
func crCloseLast(st *State, status, at string) {
	a := st.Authorizations[len(st.Authorizations)-1]
	a.Status, a.ClosedAt = status, &at
}

// Probe (report only, asserts nothing about the answer): an import may carry a revision recorded in the
// future; the clock no longer follows it, so a later correction of that payment is recorded earlier than
// that revision and the export of the result no longer re-imports. Run with -v to read the verdict.
func TestProbeFutureRecordedRevisionThenCorrection(t *testing.T) {
	good := crRichExport(t)
	fut := FormatMicro(time.Now().Add(2 * time.Hour))
	var top map[string]any
	if err := json.Unmarshal(good, &top); err != nil {
		t.Fatal(err)
	}
	idx, pid := -1, ""
	for i, r := range top["state"].(map[string]any)["revisions"].([]any) {
		if m := r.(map[string]any); m["revision"].(float64) == 2 {
			idx, pid = i, m["payment_id"].(string)
		}
	}
	if idx < 0 {
		t.Fatal("the rich export has no corrected payment")
	}
	body := ttMutateExport(t, good, func(_, st map[string]any) {
		st["revisions"].([]any)[idx].(map[string]any)["recorded_at"] = fut
	})
	s := NewStore()
	if e := s.importAt(body, time.Now()); e != nil {
		t.Fatalf("import of a revision recorded at %s: %v", fut, e.Message)
	}
	var owner string
	var amount int64
	s.mu.Lock()
	for _, p := range s.st.Payments {
		if p.PaymentID == pid {
			owner, amount = p.FromUserID, p.Amount
		}
	}
	s.mu.Unlock()
	now := time.Now()
	if _, e := s.Exec(func(st *State) (any, *AppError) {
		return st.Correct(owner, pid, CorrectionIn{ExpectedRevision: 2, Amount: amount - 1, EffectiveAt: FormatMicro(now), Reason: "probe"}, now)
	}); e != nil {
		t.Logf("PROBE: correction after the import: %d %s", e.Status, e.Message)
	}
	out, ae := s.Export()
	if ae != nil {
		t.Fatal(ae.Message)
	}
	if e := NewStore().importAt(out, time.Now()); e != nil {
		t.Logf("PROBE: VERDICT YES - re-import of the exported state after the correction: %d %s", e.Status, e.Message)
	} else {
		t.Log("PROBE: VERDICT NO - the exported state re-imports")
	}
}
