package main

import (
	"testing"
	"time"
)

// An export of the rejected 3c7c411 build carries a hold's created_at as a whole second and the
// microsecond it was placed in created_exact. Import must place the hold at that microsecond, or a payment
// received earlier in the same second is later than the hold it funds and a view shows available < 0.
func TestImportLegacyCreatedExactPlacesHoldAtTheMicrosecond(t *testing.T) {
	src := fgStore(fgU{"ada", 10000}, fgU{"bob", 6000}, fgU{"cy", 0})
	src.mu.Lock()
	hsPay(t, src.st, "bob", "ada", 5000, hsAt(500*time.Millisecond))
	hold := azAuthorize(t, src.st, "ada", "cy", 12000, hsAt(700*time.Millisecond))
	src.mu.Unlock()
	exact := hold.CreatedAt
	good, ae := src.Export()
	if ae != nil {
		t.Fatal(ae.Message)
	}
	legacy := ttMutateExport(t, good, func(_, st map[string]any) {
		a := st["authorizations"].([]any)[0].(map[string]any)
		a["created_at"], a["created_exact"] = FormatTime(hsAt(0)), exact
	})

	dst := NewStore()
	if e := dst.importAt(legacy, time.Now()); e != nil {
		t.Fatalf("import of a legacy created_exact export: %d %s", e.Status, e.Message)
	}
	dst.mu.Lock()
	a := dst.st.Authorizations[0]
	if a.CreatedAt != exact || !a.placedAt().Equal(hsAt(700*time.Millisecond)) {
		t.Fatalf("created_at %s placedAt %s, want the created_exact instant %s", a.CreatedAt, FormatMicro(a.placedAt()), exact)
	}
	if a.CreatedExact == nil || *a.CreatedExact != a.CreatedAt {
		t.Fatalf("created_exact %v must equal created_at %s after import", a.CreatedExact, a.CreatedAt)
	}
	for name, at := range map[string]time.Time{
		"whole second": hsAt(0), "payment-1us": hsAt(500*time.Millisecond - time.Microsecond), "payment": hsAt(500 * time.Millisecond),
		"hold-1us": hsAt(700*time.Millisecond - time.Microsecond), "hold": hsAt(700 * time.Millisecond),
	} {
		total, held := dst.st.TotalAt("u_ada", at, histInf), dst.st.HeldAt("u_ada", at, histInf)
		if total-held < 0 {
			t.Errorf("as_of %s: total %d held %d available %d", name, total, held, total-held)
		}
	}
	if held := dst.st.HeldAt("u_ada", hsAt(700*time.Millisecond-time.Microsecond), histInf); held != 0 {
		t.Errorf("held %d just before the hold was placed", held)
	}
	if held := dst.st.HeldAt("u_ada", hsAt(700*time.Millisecond), histInf); held != 12000 {
		t.Errorf("held %d at the instant the hold was placed", held)
	}
	dst.mu.Unlock()
	if sk := crSkew(dst); sk > crSkewLimit {
		t.Fatalf("the import moved the clock %v ahead", sk)
	}

	again, ae := dst.Export()
	if ae != nil {
		t.Fatal(ae.Message)
	}
	third := NewStore()
	if e := third.importAt(again, time.Now()); e != nil {
		t.Fatalf("re-import: %d %s", e.Status, e.Message)
	}
	last, _ := third.Export()
	if string(again) != string(last) {
		t.Fatalf("export, import, export is not byte-identical after a legacy import")
	}
	if string(again) != string(good) {
		t.Fatalf("a legacy export, once imported, must export as the current build exports the same state")
	}
}
