//go:build ignore

// gen_stage2_export drives the ACCEPTED stage-2 server (commit 17aa87e sources) over HTTP
// and writes its export plus a notes file for the stage-2 upgrade tests.
//
//	PORT=18082 stage2.exe &
//	go run testdata/gen_stage2_export.go http://127.0.0.1:18082 testdata
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

var base string

func do(method, path, token, key, body string) (int, string) {
	req, _ := http.NewRequest(method, base+path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, strings.TrimSpace(string(b))
}

func must(code int, want int, body string) string {
	if code != want {
		panic(fmt.Sprintf("want %d got %d: %s", want, code, body))
	}
	return body
}

func login(email string) string {
	c, b := do("POST", "/auth/login", "", "", `{"email":"`+email+`","password":"correct horse"}`)
	must(c, 200, b)
	var v struct{ Token string }
	json.Unmarshal([]byte(b), &v)
	return v.Token
}

func main() {
	base = os.Args[1]
	outDir := os.Args[2]
	fixture := `{
 "currency":"EUR","minor_units":2,
 "users":[
  {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
  {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":2500},
  {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":1500}],
 "payments":[
  {"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":500,"note":"coffee","visibility":"public"},
  {"id":"p_seedcap","from_user_id":"u_ada","to_user_id":"u_cy","amount":100,"note":"seeded capture","visibility":"public"}],
 "requests":[{"id":"rq_1","requester_id":"u_bob","payer_id":"u_ada","amount":1200,"note":"taxi","status":"pending"}],
 "authorizations":[
  {"id":"a_seed_open","from_user_id":"u_ada","to_user_id":"u_cy","amount":200,"status":"open","expires_at":"2099-01-01T00:00:00+00:00"},
  {"id":"a_seed_exp","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"status":"expired","expires_at":"2026-01-01T00:00:00+00:00"},
  {"id":"a_seed_void","from_user_id":"u_bob","to_user_id":"u_cy","amount":50,"status":"voided","expires_at":"2099-01-01T00:00:00+00:00"},
  {"id":"a_seed_cap","from_user_id":"u_ada","to_user_id":"u_cy","amount":100,"status":"captured","payment_ids":["p_seedcap"],"expires_at":"2099-01-01T00:00:00+00:00"}],
 "settlement_operator_ids":["u_cy"]}`
	c, b := do("POST", "/_test/reset", "", "", fixture)
	must(c, 204, b)
	ada, bob, cy := login("ada@example.com"), login("bob@example.com"), login("cy@example.com")

	notes := &bytes.Buffer{}
	fmt.Fprintf(notes, "stage2-export.json: export of the accepted stage-2 server (commit 17aa87e sources, built to stage2.exe).\n")
	fmt.Fprintf(notes, "Regenerate: PORT=<p> stage2.exe; go run testdata/gen_stage2_export.go http://127.0.0.1:<p> testdata\n\n")
	fmt.Fprintf(notes, "FIXTURE\n%s\n\n", fixture)
	fmt.Fprintf(notes, "PASSWORD (all users): correct horse\nTOKEN ada=%s\nTOKEN bob=%s\nTOKEN cy=%s\n\n", ada, bob, cy)

	rec := func(label, who, method, path, key, body string, want int) string {
		tok := map[string]string{"ada": ada, "bob": bob, "cy": cy}[who]
		c, r := do(method, path, tok, key, body)
		must(c, want, r)
		fmt.Fprintf(notes, "%s\n  caller=%s %s %s key=%q\n  body=%s\n  response(%d)=%s\n\n", label, who, method, path, key, body, c, r)
		return r
	}
	authID := func(resp string) string {
		var v struct {
			ID string `json:"authorization_id"`
		}
		json.Unmarshal([]byte(resp), &v)
		return v.ID
	}

	rec("K1 completed idempotent payment", "ada", "POST", "/payments", "k1", `{"to_handle":"bob","amount":700,"note":"lunch"}`, 201)
	rec("K2 response treated as LOST; retry later with SAME key and body", "ada", "POST", "/payments", "k2", `{"to_handle":"cy","amount":300,"note":"lost response","visibility":"public"}`, 201)
	rec("PRIVATE payment ada->bob", "ada", "POST", "/payments", "kp1", `{"to_handle":"bob","amount":150,"note":"secret","visibility":"private"}`, 201)

	a1 := authID(rec("AUTH A1 ada->bob (partial then final capture)", "ada", "POST", "/authorizations", "auth-1", `{"to_handle":"bob","amount":2000,"note":"deposit"}`, 201))
	rec("PARTIAL capture of A1 by bob (final=false)", "bob", "POST", "/authorizations/"+a1+"/capture", "cap-1", `{"amount":500,"final":false}`, 201)
	rec("FINAL capture of A1 by bob (releases the remaining 900)", "bob", "POST", "/authorizations/"+a1+"/capture", "cap-2", `{"amount":600,"final":true}`, 201)

	a2 := authID(rec("AUTH A2 ada->cy (voided)", "ada", "POST", "/authorizations", "auth-2", `{"to_handle":"cy","amount":800,"note":"later","visibility":"private"}`, 201))
	c, r := do("POST", "/authorizations/"+a2+"/void", ada, "", "")
	must(c, 200, r)
	fmt.Fprintf(notes, "VOID A2 by ada\n  response(%d)=%s\n\n", c, r)

	a3 := authID(rec("AUTH A3 ada->bob (captured in one go)", "ada", "POST", "/authorizations", "auth-3", `{"to_handle":"bob","amount":300,"note":"one go"}`, 201))
	rec("WHOLE-REMAINDER capture of A3 by bob", "bob", "POST", "/authorizations/"+a3+"/capture", "cap-3", `{}`, 201)

	rec("AUTH A4 ada->cy (left open)", "ada", "POST", "/authorizations", "auth-4", `{"to_handle":"cy","amount":400,"note":"still open"}`, 201)

	rec("API request cy->bob", "cy", "POST", "/requests", "kr1", `{"payer_handle":"bob","amount":400,"note":"api request"}`, 201)
	rec("SPLIT by ada", "ada", "POST", "/splits", "ksp1", `{"amount":900,"participant_handles":["ada","bob","cy"],"note":"dinner"}`, 201)
	rec("SETTLEMENT by operator cy", "cy", "POST", "/settlements", "kst1", `{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":100,"note":"net a"},{"from_handle":"bob","to_handle":"cy","amount":50,"visibility":"private"}]}`, 201)

	for _, u := range []struct{ n, t string }{{"ada", ada}, {"bob", bob}, {"cy", cy}} {
		c, r := do("GET", "/me", u.t, "", "")
		must(c, 200, r)
		fmt.Fprintf(notes, "EXPECTED /me %s = %s\n", u.n, r)
	}
	c, exp := do("GET", "/_test/export", "", "", "")
	must(c, 200, exp)
	if err := os.WriteFile(filepath.Join(outDir, "stage2-export.json"), []byte(exp), 0o644); err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(outDir, "stage2-export.notes.txt"), notes.Bytes(), 0o644); err != nil {
		panic(err)
	}
}
