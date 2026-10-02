package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestForgeDeriveHandle(t *testing.T) {
	cases := map[string]string{
		"A.B-c@x.com":                            "a_b_c",
		strings.Repeat("a", 25) + "@x.com":       strings.Repeat("a", 20),
		"ada@example.com":                        "ada",
		"Ünï+tag@x.com":                          "_n_" + "_tag",
		"x" + strings.Repeat("y", 30) + "@x.com": "x" + strings.Repeat("y", 19),
		strings.Repeat("ü", 25) + "@x.com":       strings.Repeat("_", 20),
		"UPPER_Case9@x.com":                      "upper_case9",
	}
	for email, want := range cases {
		got := DeriveHandle(email)
		if got != want || !validHandle(got) {
			t.Errorf("%q: got %q want %q", email, got, want)
		}
	}
}

func TestForgePasswordHash(t *testing.T) {
	start := time.Now()
	h1, h2 := HashPassword("correct horse"), HashPassword("correct horse")
	t.Logf("2 hashes in %v (%s)", time.Since(start), h1[:30])
	if h1 == h2 {
		t.Fatal("hash is not salted")
	}
	if strings.Contains(h1, "correct horse") {
		t.Fatal("plaintext in hash")
	}
	if !CheckPassword(h1, "correct horse") || CheckPassword(h1, "correct horsE") {
		t.Fatal("check wrong")
	}
	for _, bad := range []string{"", "x", "pbkdf2-sha256$0$aa$bb", "pbkdf2-sha256$99999999$aa$bb", "pbkdf2-sha256$1$zz$bb", "a$1$aa$bb"} {
		if CheckPassword(bad, "x") {
			t.Fatalf("accepted malformed %q", bad)
		}
	}
}

func fgSignup(t *testing.T, s *Store, email, pw, name string) (map[string]string, *AppError) {
	t.Helper()
	b, e := s.Signup(email, pw, name)
	if e != nil {
		if b != nil {
			t.Fatal("bytes returned with error")
		}
		return nil, e
	}
	var m map[string]string
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m, nil
}

func TestForgeSignupLogin(t *testing.T) {
	s := fgStore(fgU{"ada", 100})
	m, e := fgSignup(t, s, "A.B-c@x.com", "correct horse", "Abc")
	if e != nil || m["display_name"] != "Abc" || len(m["token"]) != 64 || m["user_id"] == "" || len(m) != 3 {
		t.Fatal(m, e)
	}
	uid, e := s.Authenticate(m["token"])
	if e != nil || uid != m["user_id"] {
		t.Fatal(uid, e)
	}
	if _, e = s.Authenticate("nope"); e == nil || e.Status != 401 {
		t.Fatal(e)
	}
	if me := s.st.Me(uid, time.Now()).(meBody); me.Handle != "a_b_c" || me.Balance != 0 || me.Total != 0 || me.Available != 0 || me.Held != 0 {
		t.Fatalf("%+v", me)
	}
	if s.st.usersByID[uid].PassHash == "correct horse" || strings.Contains(s.st.usersByID[uid].PassHash, "correct horse") {
		t.Fatal("plaintext stored")
	}

	// 422 rows, then 409 email_taken (case-insensitive), then 409 handle_taken with no account created.
	for _, c := range [][3]string{{"a@b", "", "N"}, {"no-at.com", "correct horse", "N"}, {"@x.com", "correct horse", "N"},
		{"a@", "correct horse", "N"}, {"a@@x.com", "correct horse", "N"}, {"a b@x.com", "correct horse", "N"},
		{"n@x.com", "short", "N"}, {"n@x.com", "correct horse", ""}} {
		_, e = fgSignup(t, s, c[0], c[1], c[2])
		fgWantErr(t, c[0]+"/"+c[1], e, 422, "validation_failed")
	}
	_, e = fgSignup(t, s, "a.b-C@X.COM", "correct horse", "Abc")
	fgWantErr(t, "email_taken", e, 409, "email_taken")
	n := len(s.st.Users)
	_, e = fgSignup(t, s, "a-b.c@y.com", "correct horse", "Other")
	fgWantErr(t, "handle_taken", e, 409, "handle_taken")
	_, e = fgSignup(t, s, "ada@y.com", "correct horse", "Other")
	fgWantErr(t, "handle_taken seeded", e, 409, "handle_taken")
	if len(s.st.Users) != n {
		t.Fatal("account created on failure")
	}
	if _, e = s.Login("a-b.c@y.com", "correct horse"); e == nil || e.Status != 401 {
		t.Fatal("failed signup must not register the email", e)
	}

	// Login: case-insensitive email, many valid tokens, wrong/unknown -> 401.
	var tokens []string
	for i := 0; i < 2; i++ {
		b, e := s.Login("A.B-C@x.com", "correct horse")
		if e != nil {
			t.Fatal(e)
		}
		var lm map[string]string
		_ = json.Unmarshal(b, &lm)
		if lm["user_id"] != m["user_id"] || lm["display_name"] != "Abc" {
			t.Fatal(lm)
		}
		tokens = append(tokens, lm["token"])
	}
	tokens = append(tokens, m["token"])
	for _, tok := range tokens {
		if u, e := s.Authenticate(tok); e != nil || u != m["user_id"] {
			t.Fatal("token not valid", e)
		}
	}
	if tokens[0] == tokens[1] {
		t.Fatal("tokens repeat")
	}
	for _, c := range [][2]string{{"a.b-c@x.com", "wrong password"}, {"ghost@x.com", "correct horse"}, {"", ""}} {
		if _, e := s.Login(c[0], c[1]); e == nil || e.Status != 401 || e.Code != "unauthenticated" {
			t.Fatalf("%v: %v", c, e)
		}
	}
}
