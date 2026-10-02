package main

import (
	"math"
	"strings"
	"testing"
)

func correctionObj(t *testing.T, body string) map[string]any {
	t.Helper()
	obj, e := parseObject([]byte(body), false)
	if e != nil {
		t.Fatalf("parseObject(%s): %v", body, e)
	}
	return obj
}

func TestParseCorrectionBodyAccepts(t *testing.T) {
	const tail = `,"effective_at":"2026-09-20T12:00:00+02:00","reason":"typo"}`
	for _, c := range []struct {
		name, head  string
		rev, amount int64
	}{
		{"plain", `{"expected_revision":1,"amount":400`, 1, 400},
		{"zero reverses", `{"expected_revision":1,"amount":0`, 1, 0},
		{"zero as 0.0", `{"expected_revision":1,"amount":0.0`, 1, 0},
		{"zero as 0e5", `{"expected_revision":1,"amount":0e5`, 1, 0},
		{"minus zero is zero", `{"expected_revision":1,"amount":-0`, 1, 0},
		{"max amount", `{"expected_revision":3,"amount":1000000000`, 3, 1_000_000_000},
		{"integral spellings", `{"expected_revision":2.0,"amount":4e2`, 2, 400},
		{"revision beyond a billion", `{"expected_revision":5000000000,"amount":1`, 5_000_000_000, 1},
		{"revision beyond int64 clamps", `{"expected_revision":1e30,"amount":1`, math.MaxInt64, 1},
	} {
		in, e := ParseCorrectionBody(correctionObj(t, c.head+tail))
		if e != nil {
			t.Errorf("%s: %v", c.name, e)
			continue
		}
		if in.ExpectedRevision != c.rev || in.Amount != c.amount || in.EffectiveAt != "2026-09-20T12:00:00+02:00" || in.Reason != "typo" {
			t.Errorf("%s: %+v", c.name, in)
		}
	}
}

func TestParseCorrectionBodyRejects(t *testing.T) {
	const eff, reason = `"effective_at":"2026-09-20T12:00:00+00:00"`, `"reason":"why"`
	long := `"` + strings.Repeat("x", 201) + `"`
	multi := `"` + strings.Repeat("é", 200) + `"` // 200 runes, 400 bytes: allowed
	for _, c := range []struct{ name, body, wantMsg string }{
		{"empty object", `{}`, "expected_revision"},
		{"revision missing", `{"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision zero", `{"expected_revision":0,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision negative", `{"expected_revision":-1,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision fractional", `{"expected_revision":1.5,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision string", `{"expected_revision":"1","amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision null", `{"expected_revision":null,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision bool", `{"expected_revision":true,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"revision enormous literal", `{"expected_revision":1` + strings.Repeat("0", 80) + `,"amount":1,` + eff + `,` + reason + `}`, "expected_revision"},
		{"amount missing", `{"expected_revision":1,` + eff + `,` + reason + `}`, "amount"},
		{"amount negative", `{"expected_revision":1,"amount":-5,` + eff + `,` + reason + `}`, "amount"},
		{"amount over max", `{"expected_revision":1,"amount":1000000001,` + eff + `,` + reason + `}`, "amount"},
		{"amount fractional", `{"expected_revision":1,"amount":400.5,` + eff + `,` + reason + `}`, "amount"},
		{"amount string", `{"expected_revision":1,"amount":"400",` + eff + `,` + reason + `}`, "amount"},
		{"amount null", `{"expected_revision":1,"amount":null,` + eff + `,` + reason + `}`, "amount"},
		{"amount bool", `{"expected_revision":1,"amount":false,` + eff + `,` + reason + `}`, "amount"},
		{"amount array", `{"expected_revision":1,"amount":[1],` + eff + `,` + reason + `}`, "amount"},
		{"effective missing", `{"expected_revision":1,"amount":1,` + reason + `}`, "effective_at"},
		{"effective naive", `{"expected_revision":1,"amount":1,"effective_at":"2026-09-20T12:00:00",` + reason + `}`, "effective_at"},
		{"effective bare date", `{"expected_revision":1,"amount":1,"effective_at":"2026-09-20",` + reason + `}`, "effective_at"},
		{"effective space", `{"expected_revision":1,"amount":1,"effective_at":"2026-09-20 12:00:00+00:00",` + reason + `}`, "effective_at"},
		{"effective number", `{"expected_revision":1,"amount":1,"effective_at":1790000000,` + reason + `}`, "effective_at"},
		{"effective null", `{"expected_revision":1,"amount":1,"effective_at":null,` + reason + `}`, "effective_at"},
		{"reason missing", `{"expected_revision":1,"amount":1,` + eff + `}`, "reason"},
		{"reason empty", `{"expected_revision":1,"amount":1,` + eff + `,"reason":""}`, "reason"},
		{"reason 201 runes", `{"expected_revision":1,"amount":1,` + eff + `,"reason":` + long + `}`, "reason"},
		{"reason number", `{"expected_revision":1,"amount":1,` + eff + `,"reason":7}`, "reason"},
		{"reason null", `{"expected_revision":1,"amount":1,` + eff + `,"reason":null}`, "reason"},
		{"first error wins", `{"expected_revision":0,"amount":-1,"effective_at":"x","reason":""}`, "expected_revision"},
		{"second error wins", `{"expected_revision":1,"amount":-1,"effective_at":"x","reason":""}`, "amount"},
		{"third error wins", `{"expected_revision":1,"amount":1,"effective_at":"x","reason":""}`, "effective_at"},
	} {
		_, e := ParseCorrectionBody(correctionObj(t, c.body))
		if e == nil || e.Status != 422 || e.Code != "validation_failed" || !strings.Contains(e.Message, c.wantMsg) {
			t.Errorf("%s: %v, want 422 validation_failed about %s", c.name, e, c.wantMsg)
		}
	}
	ok := `{"expected_revision":1,"amount":1,` + eff + `,"reason":` + multi + `}`
	if _, e := ParseCorrectionBody(correctionObj(t, ok)); e != nil {
		t.Errorf("200 multibyte runes must be allowed: %v", e)
	}
}
