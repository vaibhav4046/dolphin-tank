package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

// Imports attack the strictness of ReindexAt: whatever is wrong with an export, the answer is a clean
// 400/422 with no state change, never a panic or a 500. An export that is accepted must behave: its
// own export re-imports byte for byte and every read and write on it stays a clean answer.

// tyRichState is the imported stage-2 export plus API activity of this run: a payment and its
// correction, a partially captured hold, a voided hold and an open one (all with created_exact).
func tyRichState(t testing.TB) (*Store, []byte) {
	t.Helper()
	s := NewStore()
	if e := s.Import(tyReadExport(t)); e != nil {
		t.Fatalf("import of the stage-2 export: %v", e.Message)
	}
	now := time.Now()
	_, e := s.Exec(func(st *State) (any, *AppError) {
		p, e := st.Pay("u_ada", PaymentIn{ToHandle: "bob", Amount: 100, Visibility: visPublic}, now)
		if e != nil {
			return nil, e
		}
		a, e := st.Authorize("u_bob", AuthorizeIn{ToHandle: "cy", Amount: 300, Visibility: visPublic}, now)
		if e != nil {
			return nil, e
		}
		amt := int64(100)
		if _, e = st.Capture("u_cy", a.AuthorizationID, CaptureIn{Amount: &amt}, now); e != nil {
			return nil, e
		}
		b, e := st.Authorize("u_cy", AuthorizeIn{ToHandle: "ada", Amount: 50, Visibility: visPublic}, now)
		if e != nil {
			return nil, e
		}
		if _, e = st.Void("u_cy", b.AuthorizationID, now); e != nil {
			return nil, e
		}
		if _, e = st.Authorize("u_ada", AuthorizeIn{ToHandle: "cy", Amount: 70, Visibility: visPublic}, now); e != nil {
			return nil, e
		}
		_, e = st.Correct("u_ada", p.PaymentID, CorrectionIn{ExpectedRevision: 1, Amount: 60, EffectiveAt: FormatMicro(now), Reason: "attack setup"}, now)
		return struct{}{}, e
	})
	if e != nil {
		t.Fatalf("setup: %v", e.Message)
	}
	good, ae := s.Export()
	if ae != nil {
		t.Fatalf("export: %v", ae.Message)
	}
	return s, good
}

func TestExportWithExactHoldsRoundTripsByteForByte(t *testing.T) {
	_, good := tyRichState(t)
	if n := bytes.Count(good, []byte(`"created_exact"`)); n != 3 {
		t.Fatalf("expected 3 API-created holds to carry created_exact, found %d", n)
	}
	s2 := NewStore()
	if e := s2.Import(good); e != nil {
		t.Fatalf("import of a stage-3 export with created_exact: %v", e.Message)
	}
	if again := ttExport(t, s2); !bytes.Equal(again, good) {
		t.Fatalf("export -> import -> export differs:\n%s\n%s", good, again)
	}
	// A stage-2 export never has the field and still imports (the first lines of this test's setup).
	if bytes.Contains(tyReadExport(t), []byte("created_exact")) {
		t.Fatal("the stage-2 fixture must not mention created_exact")
	}
}

func TestImportRejectsBadCreatedExact(t *testing.T) {
	s, good := tyRichState(t)
	holds := func(st map[string]any, f func(a map[string]any)) {
		for _, a := range st["authorizations"].([]any) {
			if a.(map[string]any)["created_exact"] != nil {
				f(a.(map[string]any))
			}
		}
	}
	for name, mut := range map[string]func(a map[string]any){
		"another second":  func(a map[string]any) { a["created_exact"] = "2020-01-01T00:00:00.500000+00:00" },
		"not an instant":  func(a map[string]any) { a["created_exact"] = "soon" },
		"empty":           func(a map[string]any) { a["created_exact"] = "" },
		"a number":        func(a map[string]any) { a["created_exact"] = 5 },
		"naive":           func(a map[string]any) { a["created_exact"] = "2026-10-02T07:45:21.500000" },
		"before created":  func(a map[string]any) { a["created_exact"] = shiftSecond(a["created_at"].(string), -1) },
		"past its second": func(a map[string]any) { a["created_exact"] = shiftSecond(a["created_at"].(string), 1) },
	} {
		body := ttMutateExport(t, good, func(_, st map[string]any) { holds(st, mut) })
		e := s.Import(body)
		if e == nil || e.Status != 422 {
			t.Errorf("%s: got %v, want 422", name, e)
		}
		if after := ttExport(t, s); !bytes.Equal(after, good) {
			t.Errorf("%s: a refused import changed the state", name)
		}
	}
}

// shiftSecond moves an RFC 3339 instant by whole seconds, keeping the +00:00 layout.
func shiftSecond(s string, d int) string {
	t, ok := ParseInstant(s)
	if !ok {
		return s
	}
	return FormatMicro(t.Add(time.Duration(d) * time.Second))
}

type nodeRef struct {
	parent any // map[string]any or []any
	key    any // string or int
}

func (r nodeRef) get() any {
	if m, ok := r.parent.(map[string]any); ok {
		return m[r.key.(string)]
	}
	return r.parent.([]any)[r.key.(int)]
}

func (r nodeRef) set(v any) {
	if m, ok := r.parent.(map[string]any); ok {
		m[r.key.(string)] = v
		return
	}
	r.parent.([]any)[r.key.(int)] = v
}

func collectNodes(v any, path string, out *[]nodeRef, paths *[]string) {
	switch x := v.(type) {
	case map[string]any:
		for k, c := range x {
			p := path + "/" + k
			if strings.HasPrefix(p, "/state/sys") || strings.HasPrefix(p, "/state/tokens") {
				continue // opaque stored receipts and credentials: nothing derived from them
			}
			*out = append(*out, nodeRef{x, k})
			*paths = append(*paths, p)
			collectNodes(c, p, out, paths)
		}
	case []any:
		for i, c := range x {
			p := fmt.Sprintf("%s/%d", path, i)
			*out = append(*out, nodeRef{x, i})
			*paths = append(*paths, p)
			collectNodes(c, p, out, paths)
		}
	}
}

func guardedImport(s *Store, body []byte, now time.Time) (e *AppError, panicked any) {
	defer func() { panicked = recover() }()
	return s.importAt(body, now), nil
}

// guardedReads drives every read and write family over whatever state was accepted.
func guardedReads(s *Store) (panicked any) {
	defer func() { panicked = recover() }()
	now := time.Now()
	s.Exec(func(st *State) (any, *AppError) {
		inst := func(d time.Duration) *string { return strp(FormatMicro(now.Add(d))) }
		for _, u := range st.Users {
			st.Me(u.ID, now)
			st.MeAt(u.ID, MeQuery{AsOf: inst(-time.Hour)}, now)
			st.MeAt(u.ID, MeQuery{AsOf: inst(time.Hour), KnownAt: inst(-time.Hour)}, now)
			st.Statement(u.ID, StatementQuery{Limit: 100}, now)
			st.Statement(u.ID, StatementQuery{From: inst(-48 * time.Hour), To: inst(time.Hour), KnownAt: inst(time.Hour), Limit: 100}, now)
			st.ListAuthorizations(u.ID, "", "", 100, 0, now)
		}
		for _, p := range st.Payments {
			st.PaymentRevisions(p.FromUserID, p.PaymentID)
			st.Correct(p.FromUserID, p.PaymentID, CorrectionIn{ExpectedRevision: 1, Amount: 1, EffectiveAt: FormatMicro(now), Reason: "probe"}, now)
		}
		for _, a := range st.Authorizations {
			st.Capture(a.ToUserID, a.AuthorizationID, CaptureIn{}, now)
			st.Void(a.FromUserID, a.AuthorizationID, now)
		}
		if len(st.Users) > 1 {
			st.Pay(st.Users[0].ID, PaymentIn{ToHandle: st.Users[1].Handle, Amount: 1, Visibility: visPublic}, now)
			st.Authorize(st.Users[1].ID, AuthorizeIn{ToHandle: st.Users[0].Handle, Amount: 1, Visibility: visPublic}, now)
		}
		return struct{}{}, nil
	})
	return nil
}

type sweepTarget struct {
	attempt  func(body []byte) (*AppError, any) // the guarded import or reset; any is a recovered panic
	state    func() []byte                      // the exported state, for "nothing half applied"
	restore  func()                             // back to the good state after an accepted mutation
	accepted func(label string, report func(format string, a ...any))
}

// sweepMutations changes one node of a good document at a time (deleted, nulled, retyped, zeroed, made
// huge, shifted) and requires: no panic, a refusal is 400/422 and leaves the state byte for byte, and an
// accepted document behaves.
func sweepMutations(t *testing.T, top map[string]any, tg sweepTarget) {
	t.Helper()
	var nodes []nodeRef
	var paths []string
	collectNodes(top, "", &nodes, &paths)
	stride := 1
	if testing.Short() {
		stride = 4
	}
	failures := 0
	report := func(format string, a ...any) {
		failures++
		if failures <= 25 {
			t.Errorf(format, a...)
		}
	}
	good := tg.state()
	type mutation struct {
		name string
		v    any
		del  bool
	}
	imports, refused, accepted := 0, 0, 0
	for i := 0; i < len(nodes); i += stride {
		ref, path := nodes[i], paths[i]
		orig := ref.get()
		mutations := []mutation{
			{name: "delete", del: true}, {name: "null"}, {name: "empty string", v: ""}, {name: "zero", v: float64(0)},
			{name: "minus one", v: float64(-1)}, {name: "one", v: float64(1)}, {name: "huge", v: 1e300}, {name: "text", v: "x"},
			{name: "true", v: true}, {name: "empty array", v: []any{}}, {name: "empty object", v: map[string]any{}},
			{name: "valid instant", v: "2026-09-24T13:10:00+00:00"}, {name: "future instant", v: "2999-01-01T00:00:00+00:00"},
		}
		if f, ok := orig.(float64); ok {
			mutations = append(mutations, mutation{name: "plus one", v: f + 1}, mutation{name: "value minus one", v: f - 1})
		}
		for _, m := range mutations {
			removed := false
			switch p := ref.parent.(type) {
			case map[string]any:
				if m.del {
					delete(p, ref.key.(string))
					removed = true
				} else {
					p[ref.key.(string)] = m.v
				}
			case []any:
				if m.del {
					continue // dropping an array element is covered by the per-collection tests
				}
				p[ref.key.(int)] = m.v
			}
			body, err := json.Marshal(top)
			if removed {
				ref.parent.(map[string]any)[ref.key.(string)] = orig
			} else {
				ref.set(orig)
			}
			if err != nil {
				t.Fatal(err)
			}
			imports++
			label := path + " <- " + m.name
			e, pan := tg.attempt(body)
			switch {
			case pan != nil:
				report("%s: PANICKED: %v", label, pan)
				tg.restore()
			case e != nil:
				refused++
				if e.Status != 400 && e.Status != 422 {
					report("%s: refused with %d %s", label, e.Status, e.Code)
				}
				if !bytes.Equal(tg.state(), good) {
					report("%s: a refused request changed the state", label)
					tg.restore()
				}
			default:
				accepted++
				tg.accepted(label, report)
				tg.restore()
			}
		}
	}
	t.Logf("%d mutated documents over %d nodes: %d refused cleanly, %d accepted", imports, len(nodes)/stride, refused, accepted)
	if failures > 0 {
		t.Fatalf("%d failures", failures)
	}
}

// acceptedBehaves: the export of an accepted state re-imports byte for byte and every read and write
// family answers cleanly on it.
func acceptedBehaves(s *Store, now time.Time) func(label string, report func(format string, a ...any)) {
	return func(label string, report func(format string, a ...any)) {
		e1, ae := s.Export()
		if ae != nil {
			report("%s: export after an accepted document: %v", label, ae.Message)
		} else {
			s2 := NewStore()
			if e := s2.importAt(e1, now); e != nil {
				report("%s: the export of an accepted document does not re-import: %v", label, e.Message)
			} else if e2, _ := s2.Export(); !bytes.Equal(e1, e2) {
				report("%s: export -> import -> export differs after an accepted document", label)
			}
		}
		if pan := guardedReads(s); pan != nil {
			report("%s: an accepted document makes a read or write PANIC: %v", label, pan)
		}
	}
}

func TestImportMutationSweepNeverPanicsAndNeverHalfApplies(t *testing.T) {
	s, good := tyRichState(t)
	var top map[string]any
	if err := json.Unmarshal(good, &top); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	sweepMutations(t, top, sweepTarget{
		attempt: func(body []byte) (*AppError, any) { return guardedImport(s, body, now) },
		state:   func() []byte { return ttExport(t, s) },
		restore: func() {
			if e := s.Import(good); e != nil {
				t.Fatalf("restoring the good export failed: %v", e.Message)
			}
		},
		accepted: acceptedBehaves(s, now),
	})
}

// A fixture with seeded history and holds in every stored status, then the same sweep over Reset.
func TestResetMutationSweepNeverPanicsAndNeverHalfApplies(t *testing.T) {
	const past = "2026-09-20T09:00:00+00:00"
	fixture := txFx(tsHistory, txAuths(
		txA("a_open", "open", 100, txFuture, `"created_at":"`+past+`"`),
		txA("a_open_now", "open", 50, txFuture, ""),
		txA("a_exp", "expired", 10, txPast, `"created_at":"`+past+`"`),
		txA("a_void", "voided", 10, txFuture, `"created_at":"`+past+`"`),
		txA("a_cap", "captured", 30, txFuture, `"created_at":"`+past+`","payment_ids":["p_1"]`),
	))
	s := txReset(t, fixture)
	good := ttExport(t, s)
	var top map[string]any
	if err := json.Unmarshal([]byte(fixture), &top); err != nil {
		t.Fatal(err)
	}
	guardedReset := func(body []byte) (e *AppError, panicked any) {
		defer func() { panicked = recover() }()
		return s.Reset(body), nil
	}
	sweepMutations(t, top, sweepTarget{
		attempt: guardedReset,
		state:   func() []byte { return ttExport(t, s) },
		restore: func() {
			if e := s.Import(good); e != nil {
				t.Fatalf("restoring the good state failed: %v", e.Message)
			}
		},
		accepted: acceptedBehaves(s, time.Now()),
	})
}
