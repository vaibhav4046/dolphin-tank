package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"testing"
	"time"
)

// F1b (trace): a seeded hold that omits created_at is assumed created at reset, the same instant seeded
// payments that omit created_at get. Both must be the reset instant to the microsecond, or a view inside
// [floor(reset second), reset instant) counts the hold without the payments that funded it.

var (
	crMicroRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$`)
	crWholeRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$`)
)

func crHoldBetween(id, from, to, status string, amount int64, expires, rest string) string {
	s := fmt.Sprintf(`{"id":%q,"from_user_id":"u_%s","to_user_id":"u_%s","amount":%d,"status":%q,"expires_at":%q`, id, from, to, amount, status, expires)
	if rest != "" {
		s += "," + rest
	}
	return s + "}"
}

func crPayment(id, from, to string, amount int64, rest string) string {
	s := fmt.Sprintf(`{"id":%q,"from_user_id":"u_%s","to_user_id":"u_%s","amount":%d`, id, from, to, amount)
	if rest != "" {
		s += "," + rest
	}
	return s + "}"
}

// crAround is the instant and one microsecond either side of it.
func crAround(t testing.TB, instant string) []string {
	t.Helper()
	at, ok := ParseInstant(instant)
	if !ok {
		t.Fatalf("%q is not an instant", instant)
	}
	return []string{FormatMicro(at.Add(-time.Microsecond)), FormatMicro(at), FormatMicro(at.Add(time.Microsecond))}
}

// crViewsSound reads GET /me?as_of=I for every user and instant: the four money fields must describe one
// sound view (available = total - held, held within [0, total]).
func crViewsSound(t testing.TB, h http.Handler, tokens map[string]string, instants []string, label string) {
	t.Helper()
	sort.Strings(instants)
	var seen string
	for _, at := range instants {
		if at == seen {
			continue
		}
		seen = at
		for user, tok := range tokens {
			rec := txDo(h, "GET", "/me?as_of="+url.QueryEscape(at), tok, "", "")
			if rec.Code != 200 {
				t.Fatalf("%s: GET /me?as_of=%s as %s: %d %s", label, at, user, rec.Code, rec.Body)
			}
			me := txJSON(t, rec.Body.Bytes())
			total, held, avail := txNum(me, "total"), txNum(me, "held"), txNum(me, "available")
			if avail < 0 || held < 0 || held > total || avail != total-held || txNum(me, "balance") != total {
				t.Errorf("%s: %s as_of=%s: total %d held %d available %d (available must be total - held and never negative)", label, user, at, total, held, avail)
			}
		}
	}
}

// crSeededInstants gathers every created_at of the exported payments and holds, each with its second's
// floor, plus a microsecond either side of all of them.
func crSeededInstants(t testing.TB, export []byte) []string {
	t.Helper()
	var env struct {
		State struct {
			Payments []struct {
				CreatedAt string `json:"created_at"`
			}
			Authorizations []struct {
				CreatedAt string `json:"created_at"`
			}
		}
	}
	if err := json.Unmarshal(export, &env); err != nil {
		t.Fatal(err)
	}
	var base []string
	for _, p := range env.State.Payments {
		base = append(base, p.CreatedAt)
	}
	for _, a := range env.State.Authorizations {
		base = append(base, a.CreatedAt)
	}
	var out []string
	for _, b := range base {
		at, ok := ParseInstant(b)
		if !ok {
			t.Fatalf("exported created_at %q is not an instant", b)
		}
		out = append(out, crAround(t, b)...)
		out = append(out, crAround(t, FormatMicro(at.Truncate(time.Second)))...)
	}
	return out
}

func crExportOf(t testing.TB, h http.Handler) []byte {
	t.Helper()
	return txWant(t, "GET /_test/export", txDo(h, "GET", "/_test/export", "", "", ""), 200)
}

// Forge's probe A4, as an assertion: bob's balance 1000 is opening 200 plus a seeded 800 and he holds 500.
func TestSeededHoldWithoutCreatedAtIsPlacedAtTheResetInstant(t *testing.T) {
	exp := FormatTime(time.Now().Add(2 * time.Hour))
	fixture := `{"currency":"EUR","minor_units":2,"users":[` + strings.Join([]string{crUser("ada", "ada", 4200), crUser("bob", "bob", 1000), crUser("cy", "cy", 0)}, ",") +
		`],"payments":[` + crPayment("p_1", "ada", "bob", 800, "") + `],"authorizations":[` + crHoldBetween("a_1", "bob", "ada", "open", 500, exp, "") +
		`],"requests":[{"id":"r_1","requester_id":"u_ada","payer_id":"u_bob","amount":100}]}`
	h, tok, s := crServer(t, fixture)

	s.mu.Lock()
	holdAt, payAt, reqAt := s.st.Authorizations[0].CreatedAt, s.st.Payments[0].CreatedAt, s.st.Requests[0].CreatedAt
	s.mu.Unlock()
	if holdAt != payAt || !crMicroRe.MatchString(holdAt) {
		t.Fatalf("seeded hold created_at %q, seeded payment created_at %q: both must be the reset instant in microseconds", holdAt, payAt)
	}
	if !crWholeRe.MatchString(reqAt) {
		t.Fatalf("a seeded request's created_at stays a whole second (stage 1), got %q", reqAt)
	}

	crViewsSound(t, h, map[string]string{"ada": tok["ada"], "bob": tok["bob"]}, crSeededInstants(t, crExportOf(t, h)), "reset")

	floor := FormatMicro(hsInstant(t, holdAt).Truncate(time.Second))
	me := txJSON(t, txDo(h, "GET", "/me?as_of="+url.QueryEscape(floor), tok["bob"], "", "").Body.Bytes())
	if txNum(me, "available") < 0 {
		t.Fatalf("bob at the floor of the reset second: %v", me)
	}
}

// Several seeded payments and holds without created_at, mixed with explicit ones: no read at any seeded
// instant (or a microsecond off it) may show a negative available or held above total.
func TestSeededViewsNeverNegativeAtAnySeededInstant(t *testing.T) {
	now := time.Now()
	exp := FormatTime(now.Add(2 * time.Hour))
	past := FormatMicro(now.Add(-time.Hour))
	fixture := `{"currency":"EUR","minor_units":2,"users":[` + strings.Join([]string{crUser("ada", "ada", 4200), crUser("bob", "bob", 1000), crUser("cy", "cy", 500)}, ",") +
		`],"payments":[` + strings.Join([]string{
		crPayment("p_1", "ada", "bob", 800, ""),
		crPayment("p_2", "bob", "cy", 300, ""),
		crPayment("p_3", "cy", "ada", 50, ""),
		crPayment("p_4", "ada", "cy", 20, `"created_at":"`+past+`"`),
	}, ",") + `],"authorizations":[` + strings.Join([]string{
		crHoldBetween("a_ada", "ada", "cy", "open", 300, exp, ""),
		crHoldBetween("a_bob", "bob", "ada", "open", 700, exp, ""),
		crHoldBetween("a_cy", "cy", "bob", "open", 100, exp, ""),
		crHoldBetween("a_old", "ada", "bob", "open", 50, exp, `"created_at":"`+past+`"`),
		crHoldBetween("a_cap", "ada", "bob", "captured", 100, exp, ""),
		crHoldBetween("a_void", "bob", "cy", "voided", 100, exp, ""),
		crHoldBetween("a_exp", "bob", "cy", "expired", 100, exp, ""),
	}, ",") + `]}`
	h, tok, _ := crServer(t, fixture)
	crViewsSound(t, h, tok, crSeededInstants(t, crExportOf(t, h)), "reset")
}

// The import default: payments and holds that omit created_at in a stage-1/2 style export both get the
// import's whole second, so no view in [floor(import second), import instant) can show a hold without
// the money behind it. (A pin: the same probe as the reset one, on the migrating import.)
func TestImportedHoldWithoutCreatedAtKeepsViewsSound(t *testing.T) {
	exp := FormatTime(time.Now().Add(2 * time.Hour))
	src := txReset(t, `{"currency":"EUR","minor_units":2,"users":[`+strings.Join([]string{crUser("ada", "ada", 4200), crUser("bob", "bob", 1000), crUser("cy", "cy", 0)}, ",")+
		`],"payments":[`+crPayment("p_1", "ada", "bob", 800, "")+`],"authorizations":[`+crHoldBetween("a_1", "bob", "ada", "open", 700, exp, "")+`]}`)
	body := ttMutateExport(t, ttExport(t, src), func(_, st map[string]any) {
		delete(st, "history_version")
		delete(st, "revisions")
		for _, u := range st["users"].([]any) {
			delete(u.(map[string]any), "opening_balance")
		}
		for _, p := range st["payments"].([]any) {
			delete(p.(map[string]any), "created_at")
		}
		for _, a := range st["authorizations"].([]any) {
			for _, k := range []string{"created_at", "closed_at", "created_exact"} {
				delete(a.(map[string]any), k)
			}
		}
	})
	s := NewStore()
	h := NewServer(s)
	before := time.Now()
	txWant(t, "import", txDo(h, "POST", "/_test/import", "", "", string(body)), 204)
	after := time.Now()
	tokens := map[string]string{}
	for _, n := range []string{"ada", "bob"} {
		rec := txDo(h, "POST", "/auth/login", "", "", `{"email":"`+n+`@example.com","password":"correct horse"}`)
		tokens[n], _ = txJSON(t, rec.Body.Bytes())["token"].(string)
	}
	var instants []string
	for _, at := range []time.Time{before, after, before.Truncate(time.Second), after.Truncate(time.Second)} {
		instants = append(instants, crAround(t, FormatMicro(at))...)
	}
	instants = append(instants, crSeededInstants(t, crExportOf(t, h))...)
	crViewsSound(t, h, tokens, instants, "import")
}
