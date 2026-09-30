package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/rand"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func ttExport(t testing.TB, s *Store) []byte {
	t.Helper()
	b, e := s.Export()
	if e != nil {
		t.Fatalf("export: %v", e.Message)
	}
	return b
}

func ttSignup(t testing.TB, s *Store, email string) (id, token string) {
	t.Helper()
	b, e := s.Signup(email, "long enough pw", "New")
	if e != nil {
		t.Fatalf("signup: %v", e.Message)
	}
	var out struct {
		UserID string `json:"user_id"`
		Token  string `json:"token"`
	}
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out.UserID, out.Token
}

func TestExportImportRoundTrip(t *testing.T) {
	s := ttStore(t)
	_, token := ttSignup(t, s, "new@example.com")
	_, payResp, e := ttPay(t, s, "u_ada", "k1", `{"to_handle":"bob","amount":250}`)
	if e != nil {
		t.Fatal(e.Message)
	}
	_, setResp, e := ttSettle(t, s, "u_ada", "ks", ttTransfers(ttLeg("ada", "bob", 10), ttLeg("bob", "cy", 10)))
	if e != nil {
		t.Fatal(e.Message)
	}
	if _, _, e := ttPay(t, s, "u_dee", "kfail", `{"to_handle":"bob","amount":5000}`); ttCode(e) != "insufficient_funds" {
		t.Fatalf("setup: %v", e)
	}
	e1 := ttExport(t, s)
	if !bytes.Equal(e1, ttExport(t, s)) {
		t.Fatal("two exports of the same state differ")
	}

	ttPay(t, s, "u_ada", "k2", `{"to_handle":"cy","amount":700}`)
	lateID, lateToken := ttSignup(t, s, "late@example.com")
	ttSettle(t, s, "u_ada", "ks2", ttTransfers(ttLeg("ada", "dee", 3)))
	if bytes.Equal(e1, ttExport(t, s)) {
		t.Fatal("mutation did not change the export")
	}

	for i := 0; i < 2; i++ {
		if e := s.Import(e1); e != nil {
			t.Fatalf("import %d: %v", i, e.Message)
		}
		if got := ttExport(t, s); !bytes.Equal(got, e1) {
			t.Fatalf("export after import %d differs:\n%s\n%s", i, e1, got)
		}
	}
	if uid, e := s.Authenticate(token); e != nil || uid == "" {
		t.Fatalf("old token must survive: %v", e)
	}
	if _, e := s.Authenticate(lateToken); e == nil {
		t.Fatal("token created after the export must be gone")
	}
	if _, e := s.Login("late@example.com", "long enough pw"); e == nil {
		t.Fatalf("user %s created after the export must be gone", lateID)
	}
	if _, e := s.Login("new@example.com", "long enough pw"); e != nil {
		t.Fatalf("login after import: %v", e.Message)
	}
	if _, e := s.Login("ada@example.com", "correct horse"); e != nil {
		t.Fatalf("seeded login after import: %v", e.Message)
	}
	if st, b, e := ttPay(t, s, "u_ada", "k1", `{"to_handle":"bob","amount":250}`); e != nil || st != 200 || !bytes.Equal(b, payResp) {
		t.Fatalf("payment replay after import: %d %v", st, e)
	}
	if st, b, e := ttSettle(t, s, "u_ada", "ks", ttTransfers(ttLeg("ada", "bob", 10), ttLeg("bob", "cy", 10))); e != nil || st != 200 || !bytes.Equal(b, setResp) {
		t.Fatalf("settlement replay after import: %d %v", st, e)
	}
	if st, _, e := ttPay(t, s, "u_dee", "kfail", `{"to_handle":"bob","amount":5}`); e != nil || st != 201 {
		t.Fatalf("failed key must stay reusable after import: %d %v", st, e)
	}
	if st, _, e := ttSettle(t, s, "u_ada", "ks3", ttTransfers(ttLeg("ada", "cy", 1))); e != nil || st != 201 {
		t.Fatalf("operator right must survive import: %d %v", st, e)
	}
	if ttSum(s) != ttSeededSum {
		t.Fatalf("sum drifted: %d", ttSum(s))
	}
}

func ttMutateExport(t testing.TB, raw []byte, fn func(top, state map[string]any)) []byte {
	var top map[string]any
	if err := json.Unmarshal(raw, &top); err != nil {
		t.Fatal(err)
	}
	fn(top, top["state"].(map[string]any))
	out, _ := json.Marshal(top)
	return out
}

func TestImportGarbageLeavesStateIntact(t *testing.T) {
	s := ttStore(t)
	ttSignup(t, s, "new@example.com")
	good := ttExport(t, s)
	user := func(st map[string]any, i int) map[string]any { return st["users"].([]any)[i].(map[string]any) }
	cases := []struct {
		name   string
		body   []byte
		status int
	}{
		{"not json", []byte(`{"track":`), 400},
		{"trailing junk", append(append([]byte{}, good...), `x`...), 400},
		{"empty", nil, 400},
		{"array", []byte(`[]`), 422},
		{"empty object", []byte(`{}`), 422},
		{"missing state", []byte(`{"track":"pocketful","format_version":1}`), 422},
		{"null state", []byte(`{"track":"pocketful","format_version":1,"state":null}`), 422},
		{"string state", []byte(`{"track":"pocketful","format_version":1,"state":"x"}`), 422},
		{"empty state", []byte(`{"track":"pocketful","format_version":1,"state":{}}`), 422},
		{"missing track", ttMutateExport(t, good, func(top, _ map[string]any) { delete(top, "track") }), 422},
		{"wrong track", ttMutateExport(t, good, func(top, _ map[string]any) { top["track"] = "other" }), 422},
		{"wrong version", ttMutateExport(t, good, func(top, _ map[string]any) { top["format_version"] = 2 }), 422},
		{"string version", ttMutateExport(t, good, func(top, _ map[string]any) { top["format_version"] = "1" }), 422},
		{"missing version", ttMutateExport(t, good, func(top, _ map[string]any) { delete(top, "format_version") }), 422},
		{"negative balance", ttMutateExport(t, good, func(_, st map[string]any) { user(st, 0)["balance"] = -1 }), 422},
		{"fractional balance", ttMutateExport(t, good, func(_, st map[string]any) { user(st, 0)["balance"] = 1.5 }), 422},
		{"empty currency", ttMutateExport(t, good, func(_, st map[string]any) { st["currency"] = "" }), 422},
		{"bad minor units", ttMutateExport(t, good, func(_, st map[string]any) { st["minor_units"] = 7 }), 422},
		{"duplicate handle", ttMutateExport(t, good, func(_, st map[string]any) { user(st, 1)["handle"] = user(st, 0)["handle"] }), 422},
		{"null user", ttMutateExport(t, good, func(_, st map[string]any) { st["users"] = []any{nil} }), 422},
		{"token of nobody", ttMutateExport(t, good, func(_, st map[string]any) {
			st["Tokens"] = map[string]any{"x": "u_ghost"}
			st["tokens"] = map[string]any{"x": "u_ghost"}
		}), 422},
		{"payment of nobody", ttMutateExport(t, good, func(_, st map[string]any) { st["payments"].([]any)[0].(map[string]any)["from_user_id"] = "u_ghost" }), 422},
	}
	for _, c := range cases {
		if e := s.Import(c.body); e == nil || e.Status != c.status {
			t.Errorf("%s: got %v, want status %d", c.name, e, c.status)
		}
		if got := ttExport(t, s); !bytes.Equal(got, good) {
			t.Errorf("%s: a rejected import changed the state", c.name)
		}
	}
}

func TestResetRejectsAndKeepsState(t *testing.T) {
	s := ttStore(t)
	_, token := ttSignup(t, s, "new@example.com")
	ttPay(t, s, "u_ada", "k", `{"to_handle":"bob","amount":5}`)
	good := ttExport(t, s)
	u := func(extra string) string {
		return `{"currency":"EUR","minor_units":2,"users":[{"id":"u_a","email":"a@x.io","password":"pw","handle":"a","balance":5}` + extra + `]}`
	}
	cases := []struct {
		name, body string
		status     int
	}{
		{"negative balance", u(`,{"id":"u_b","email":"b@x.io","password":"pw","handle":"b","balance":-1}`), 422},
		{"fractional balance", u(`,{"id":"u_b","email":"b@x.io","password":"pw","handle":"b","balance":1.5}`), 422},
		{"string balance", u(`,{"id":"u_b","email":"b@x.io","password":"pw","handle":"b","balance":"5"}`), 422},
		{"duplicate handle", u(`,{"id":"u_b","email":"b@x.io","password":"pw","handle":"a"}`), 422},
		{"duplicate id", u(`,{"id":"u_a","email":"b@x.io","password":"pw","handle":"b"}`), 422},
		{"duplicate email", u(`,{"id":"u_b","email":"A@x.io","password":"pw","handle":"b"}`), 422},
		{"bad handle", u(`,{"id":"u_b","email":"b@x.io","password":"pw","handle":"Bad!"}`), 422},
		{"bad email", u(`,{"id":"u_b","email":"nope","password":"pw","handle":"b"}`), 422},
		{"payment of nobody", `{"currency":"EUR","minor_units":2,"payments":[{"id":"p","from_user_id":"x","to_user_id":"y","amount":1}]}`, 422},
		{"bad visibility", u(``)[:len(u(``))-2] + `],"payments":[{"id":"p","from_user_id":"u_a","to_user_id":"u_a","amount":1,"visibility":"x"}]}`, 422},
		{"bad status", u(``)[:len(u(``))-2] + `],"requests":[{"id":"r","requester_id":"u_a","payer_id":"u_a","amount":1,"status":"x"}]}`, 422},
		{"minor units 1", `{"currency":"EUR","minor_units":1}`, 422},
		{"empty currency", `{"currency":"","minor_units":2}`, 422},
		{"operators not array", `{"currency":"EUR","minor_units":2,"settlement_operator_ids":"u"}`, 422},
		{"not json", `{"currency":`, 400},
		{"not an object", `[]`, 400},
	}
	for _, c := range cases {
		if e := s.Reset([]byte(c.body)); e == nil || e.Status != c.status {
			t.Errorf("%s: got %v, want status %d", c.name, e, c.status)
		}
		if got := ttExport(t, s); !bytes.Equal(got, good) {
			t.Errorf("%s: a rejected reset changed the state", c.name)
		}
	}
	if _, e := s.Authenticate(token); e != nil {
		t.Fatal("token lost by a rejected reset")
	}
	for _, cur := range []struct {
		code  string
		minor int
	}{{"JPY", 0}, {"BHD", 3}, {"EUR", 2}} {
		body := fmt.Sprintf(`{"currency":%q,"minor_units":%d,"users":[{"id":"u_a","email":"a@x.io","password":"pw","handle":"a","balance":5}]}`, cur.code, cur.minor)
		if e := s.Reset([]byte(body)); e != nil {
			t.Fatalf("%s: %v", cur.code, e.Message)
		}
	}
	if _, e := s.Authenticate(token); e == nil {
		t.Fatal("reset must clear tokens")
	}
	if st, _, e := ttPay(t, s, "u_a", "k", `{"to_handle":"a","amount":1}`); e == nil {
		t.Fatalf("idempotency records must be cleared by reset, got status %d", st)
	}
	if s.IsOperator("u_ada") {
		t.Fatal("reset must clear operators")
	}
}

func TestResetManyUsersIsFast(t *testing.T) {
	users := make([]string, 500)
	for i := range users {
		users[i] = fmt.Sprintf(`{"id":"u_%d","email":"u%d@x.io","password":"correct horse","handle":"h%d","balance":100}`, i, i, i)
	}
	body := `{"currency":"EUR","minor_units":2,"users":[` + ttJoin(users) + `]}`
	s := NewStore()
	start := time.Now()
	if e := s.Reset([]byte(body)); e != nil {
		t.Fatal(e.Message)
	}
	if d := time.Since(start); d > 3*time.Second {
		t.Fatalf("500-user reset took %v", d)
	}
	if _, e := s.Login("u499@x.io", "correct horse"); e != nil {
		t.Fatalf("seeded login: %v", e.Message)
	}
	if _, e := s.Login("u499@x.io", "wrong horse!"); e == nil {
		t.Fatal("wrong password accepted")
	}
	for i := range users {
		users[i] = fmt.Sprintf(`{"id":"u_%d","email":"u%d@x.io","password":"pw number %d","handle":"h%d","balance":100}`, i, i, i, i)
	}
	body = `{"currency":"EUR","minor_units":2,"users":[` + ttJoin(users) + `]}`
	start = time.Now()
	if e := s.Reset([]byte(body)); e != nil {
		t.Fatal(e.Message)
	}
	t.Logf("500 users with 500 distinct passwords: %v", time.Since(start))
}

func ttJoin(parts []string) string {
	var b bytes.Buffer
	for i, p := range parts {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(p)
	}
	return b.String()
}

// ttWriters runs n goroutines that make random payments among the fixture
// users until stop is closed.
func ttWriters(t testing.TB, s *Store, n int, stop <-chan struct{}, wg *sync.WaitGroup) {
	handles := []string{"ada", "bob", "cy", "dee"}
	ids := map[string]string{"ada": "u_ada", "bob": "u_bob", "cy": "u_cy", "dee": "u_dee"}
	var seq atomic.Int64
	for w := 0; w < n; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			r := rand.New(rand.NewSource(int64(w)))
			for {
				select {
				case <-stop:
					return
				default:
				}
				from, to := handles[r.Intn(4)], handles[r.Intn(4)]
				key := fmt.Sprintf("w%d-%d", w, seq.Add(1))
				body := fmt.Sprintf(`{"to_handle":%q,"amount":%d}`, to, 1+r.Intn(60))
				ttPay(t, s, ids[from], key, body)
			}
		}(w)
	}
}

func TestExportDuringWritersKeepsSumInvariant(t *testing.T) {
	s := ttStore(t)
	stop := make(chan struct{})
	var wg sync.WaitGroup
	ttWriters(t, s, 50, stop, &wg)
	deadline := time.Now().Add(700 * time.Millisecond)
	exports := 0
	for time.Now().Before(deadline) {
		var env struct {
			State struct {
				Users []struct {
					Balance int64 `json:"balance"`
				} `json:"users"`
			} `json:"state"`
		}
		if err := json.Unmarshal(ttExport(t, s), &env); err != nil {
			t.Fatal(err)
		}
		var sum int64
		for _, u := range env.State.Users {
			if u.Balance < 0 {
				t.Fatalf("export shows a negative balance")
			}
			sum += u.Balance
		}
		if sum != ttSeededSum {
			t.Fatalf("export %d: balances sum to %d, want %d", exports, sum, ttSeededSum)
		}
		exports++
	}
	close(stop)
	wg.Wait()
	t.Logf("%d exports taken while 50 writers ran", exports)
	if ttSum(s) != ttSeededSum {
		t.Fatal("final sum drifted")
	}
}

func TestImportAndResetDuringWritersNeverPanic(t *testing.T) {
	s := ttStore(t)
	snap := ttExport(t, s)
	stop := make(chan struct{})
	var wg sync.WaitGroup
	ttWriters(t, s, 50, stop, &wg)
	deadline := time.Now().Add(700 * time.Millisecond)
	imports := 0
	for time.Now().Before(deadline) {
		if e := s.Import(snap); e != nil {
			t.Fatal(e.Message)
		}
		if imports%5 == 0 {
			if e := s.Reset([]byte(ttFixture)); e != nil {
				t.Fatal(e.Message)
			}
		}
		if ttSum(s) != ttSeededSum {
			t.Fatalf("sum %d after import/reset", ttSum(s))
		}
		imports++
	}
	close(stop)
	wg.Wait()
	if ttSum(s) != ttSeededSum {
		t.Fatal("final sum drifted")
	}
	t.Logf("%d imports under 50 writers", imports)
}
