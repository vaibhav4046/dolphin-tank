//go:build ignore

// gen_stage1_export drives the ACCEPTED stage-1 server over HTTP and writes the
// export plus a notes file for TestUpgradeFromStage1Export.
//
//	PORT=18081 stage1.exe &
//	go run testdata/gen_stage1_export.go http://127.0.0.1:18081 testdata
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
 "payments":[{"id":"p_1","from_user_id":"u_ada","to_user_id":"u_bob","amount":500,"note":"coffee","visibility":"public"}],
 "requests":[{"id":"rq_1","requester_id":"u_bob","payer_id":"u_ada","amount":1200,"note":"taxi","status":"pending"}],
 "settlement_operator_ids":["u_cy"]}`
	c, b := do("POST", "/_test/reset", "", "", fixture)
	must(c, 204, b)
	ada, bob, cy := login("ada@example.com"), login("bob@example.com"), login("cy@example.com")

	notes := &bytes.Buffer{}
	fmt.Fprintf(notes, "stage1-export.json: export of the accepted stage-1 server (commit 0024598 sources).\n")
	fmt.Fprintf(notes, "Regenerate: PORT=<p> stage1.exe; go run testdata/gen_stage1_export.go http://127.0.0.1:<p> testdata\n\n")
	fmt.Fprintf(notes, "FIXTURE\n%s\n\n", fixture)
	fmt.Fprintf(notes, "PASSWORD (all users): correct horse\nTOKEN ada=%s\nTOKEN bob=%s\nTOKEN cy=%s\n\n", ada, bob, cy)

	rec := func(label, who, method, path, key, body string, want int) string {
		tok := map[string]string{"ada": ada, "bob": bob, "cy": cy}[who]
		c, r := do(method, path, tok, key, body)
		must(c, want, r)
		fmt.Fprintf(notes, "%s\n  caller=%s %s %s key=%q\n  body=%s\n  response(%d)=%s\n\n", label, who, method, path, key, body, c, r)
		return r
	}
	rec("K1 completed idempotent payment", "ada", "POST", "/payments", "k1", `{"to_handle":"bob","amount":700,"note":"lunch"}`, 201)
	rec("K2 response treated as LOST; retry later with SAME key and body", "ada", "POST", "/payments", "k2", `{"to_handle":"cy","amount":300,"note":"lost response","visibility":"public"}`, 201)
	rec("PRIVATE payment ada->bob", "ada", "POST", "/payments", "kp1", `{"to_handle":"bob","amount":150,"note":"secret","visibility":"private"}`, 201)
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
	if err := os.WriteFile(filepath.Join(outDir, "stage1-export.json"), []byte(exp), 0o644); err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(outDir, "stage1-export.notes.txt"), notes.Bytes(), 0o644); err != nil {
		panic(err)
	}
}
