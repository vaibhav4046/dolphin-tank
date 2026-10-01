package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func ttSettle(t testing.TB, s *Store, uid, key, body string) (int, []byte, *AppError) {
	return s.Settle(uid, key, ttBody(t, body))
}

func ttLeg(from, to string, amount int) string {
	return fmt.Sprintf(`{"from_handle":%q,"to_handle":%q,"amount":%d}`, from, to, amount)
}

func ttTransfers(legs ...string) string {
	return `{"transfers":[` + strings.Join(legs, ",") + `]}`
}

func TestSettleChainAffordableByNet(t *testing.T) {
	for _, legs := range [][]string{
		{ttLeg("ada", "bob", 100), ttLeg("bob", "cy", 100)},
		{ttLeg("bob", "cy", 100), ttLeg("ada", "bob", 100)},
	} {
		s := ttStore(t)
		st, body, e := ttSettle(t, s, "u_ada", "k", ttTransfers(legs...))
		if e != nil || st != 201 {
			t.Fatalf("chain: %d %v", st, e)
		}
		var out struct {
			SettlementID string `json:"settlement_id"`
			CommittedAt  string `json:"committed_at"`
			Payments     []struct {
				From         string  `json:"from_handle"`
				To           string  `json:"to_handle"`
				RequestID    *string `json:"request_id"`
				SettlementID *string `json:"settlement_id"`
				CreatedAt    string  `json:"created_at"`
			} `json:"payments"`
		}
		if err := json.Unmarshal(body, &out); err != nil || len(out.Payments) != 2 {
			t.Fatalf("shape: %v %s", err, body)
		}
		for i, p := range out.Payments {
			if p.SettlementID == nil || *p.SettlementID != out.SettlementID || p.RequestID != nil || p.CreatedAt != out.CommittedAt {
				t.Fatalf("member %d malformed: %s", i, body)
			}
		}
		if out.Payments[0].From != legs2from(legs[0]) {
			t.Fatalf("payments must be in input order: %s", body)
		}
		if ttBal(s, "ada") != 9900 || ttBal(s, "bob") != 0 || ttBal(s, "cy") != 100 || ttSum(s) != ttSeededSum {
			t.Fatalf("balances wrong after chain")
		}
		st2, again, e := ttSettle(t, s, "u_ada", "k", ttTransfers(legs...))
		if e != nil || st2 != 200 || !bytes.Equal(body, again) || ttBal(s, "cy") != 100 {
			t.Fatalf("replay: %d %v", st2, e)
		}
	}
}

func legs2from(leg string) string {
	var m map[string]any
	_ = json.Unmarshal([]byte(leg), &m)
	return m["from_handle"].(string)
}

func TestSettleEntryErrorBeatsFundsAndLeavesNoTrace(t *testing.T) {
	cases := []struct {
		legs []string
		code string
	}{
		{[]string{ttLeg("ada", "bob", 999999999), ttLeg("ada", "nobody", 1)}, "not_found"},
		{[]string{ttLeg("ada", "bob", 999999999), ttLeg("ada", "ada", 5)}, "self_payment"},
		{[]string{ttLeg("ada", "bob", 999999999), `{"from_handle":"ada","to_handle":"bob","amount":0}`}, "validation_failed"},
		{[]string{ttLeg("ada", "bob", 999999999), `{"from_handle":7,"to_handle":"bob","amount":5}`}, "validation_failed"},
		{[]string{ttLeg("ada", "bob", 999999999), `{"from_handle":"ada","to_handle":"bob","amount":5,"visibility":"friends"}`}, "validation_failed"},
		{[]string{ttLeg("ada", "bob", 999999999), `{"from_handle":"ada","to_handle":"bob","amount":5,"note":null}`}, "validation_failed"},
		{[]string{ttLeg("ada", "bob", 999999999)}, "insufficient_funds"},
		{[]string{ttLeg("bob", "cy", 1)}, "insufficient_funds"},
	}
	for i, c := range cases {
		s := ttStore(t)
		before := ttPaymentCount(s)
		body := ttTransfers(c.legs...)
		_, _, e := ttSettle(t, s, "u_ada", "k", body)
		if ttCode(e) != c.code {
			t.Fatalf("case %d: got %v want %s", i, e, c.code)
		}
		if ttPaymentCount(s) != before || ttSum(s) != ttSeededSum || ttBal(s, "ada") != 10000 {
			t.Fatalf("case %d left a trace", i)
		}
		st, _, e := ttSettle(t, s, "u_ada", "k", ttTransfers(ttLeg("ada", "bob", 1)))
		if e != nil || st != 201 {
			t.Fatalf("case %d: failed key must be reusable, got %d %v", i, st, e)
		}
	}
}

func TestSettleAllOrNone(t *testing.T) {
	s := ttStore(t)
	_, _, e := ttSettle(t, s, "u_ada", "k", ttTransfers(ttLeg("ada", "bob", 100), ttLeg("ada", "cy", 100), ttLeg("dee", "cy", 101)))
	if ttCode(e) != "insufficient_funds" || ttBal(s, "bob") != 0 || ttBal(s, "cy") != 0 || ttBal(s, "dee") != 100 {
		t.Fatalf("partial commit or wrong error: %v", e)
	}
}

func TestSettleShapeAndPermission(t *testing.T) {
	s := ttStore(t)
	many := make([]string, 33)
	for i := range many {
		many[i] = ttLeg("ada", "bob", 1)
	}
	for _, body := range []string{
		`{}`, `{"transfers":null}`, `{"transfers":"x"}`, `{"transfers":{}}`, `{"transfers":[]}`,
		`{"transfers":[5]}`, `{"transfers":[` + ttLeg("ada", "bob", 1) + `,null]}`, ttTransfers(many...),
	} {
		if _, _, e := ttSettle(t, s, "u_ada", "k", body); ttCode(e) != "validation_failed" || e.Status != 422 {
			t.Fatalf("%.40s: got %v, want 422 validation_failed", body, e)
		}
	}
	if st, _, e := ttSettle(t, s, "u_ada", "k32", ttTransfers(many[:32]...)); e != nil || st != 201 || ttBal(s, "bob") != 32 {
		t.Fatalf("32 transfers must pass: %d %v", st, e)
	}
	if _, _, e := ttSettle(t, s, "u_bob", "kb", ttTransfers(ttLeg("ada", "bob", 1))); ttCode(e) != "forbidden" || e.Status != 403 {
		t.Fatalf("non-operator: %v", e)
	}
	if _, _, e := ttSettle(t, s, "u_ada", "", ttTransfers(ttLeg("ada", "bob", 1))); ttCode(e) != "missing_idempotency_key" {
		t.Fatalf("missing key: %v", e)
	}
	if _, _, e := ttSettle(t, s, "u_ada", "k32", `{"transfers":[]}`); ttCode(e) != "idempotency_key_reuse" {
		t.Fatalf("claimed key resolves before validation: %v", e)
	}
	if _, _, e := ttSettle(t, s, "u_ada", "k2", `{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1,"extra":true}],"more":1}`); e != nil {
		t.Fatalf("unknown fields must be ignored: %v", e)
	}
}
