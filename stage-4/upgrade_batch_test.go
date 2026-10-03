package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// The stage-4 service accepts the real exports of the same team's earlier builds, keeps settlement
// membership, revisions and receipts, and then corrects the imported payments in batches.
// testdata/stage{1,2,3}-export.json were written by the accepted builds themselves (see the notes files);
// POCKETFUL_EXTRA_EXPORTS may name more export files (path list) for the same checks.

func upgradeExports(t *testing.T) []string {
	t.Helper()
	files := []string{"testdata/stage1-export.json", "testdata/stage2-export.json", "testdata/stage3-export.json"}
	for _, p := range filepath.SplitList(os.Getenv("POCKETFUL_EXTRA_EXPORTS")) {
		if p != "" {
			files = append(files, p)
		}
	}
	return files
}

func TestBatchOnImportedOlderExports(t *testing.T) { // U41
	for _, file := range upgradeExports(t) {
		t.Run(filepath.Base(file), func(t *testing.T) {
			raw, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			var src struct {
				State struct {
					Tokens   map[string]string `json:"tokens"`
					Sys      struct{ Operators map[string]bool }
					Payments []struct {
						PaymentID       string  `json:"payment_id"`
						SettlementID    *string `json:"settlement_id"`
						AuthorizationID *string `json:"authorization_id"`
						Amount          int64   `json:"amount"`
					}
					Revisions []struct {
						PaymentID string `json:"payment_id"`
						Revision  int64  `json:"revision"`
					}
					Users []struct {
						ID      string `json:"id"`
						Balance int64  `json:"balance"`
					}
				}
			}
			if err := json.Unmarshal(raw, &src); err != nil {
				t.Fatal(err)
			}
			owners, opTok := map[string]string{}, ""
			for tok, uid := range src.State.Tokens {
				owners[uid] = tok
				if src.State.Sys.Operators[uid] {
					opTok = tok
				}
			}
			if opTok == "" {
				t.Fatal("the export holds no operator session")
			}
			latest := map[string]int64{}
			for _, r := range src.State.Revisions {
				latest[r.PaymentID] = max(latest[r.PaymentID], r.Revision)
			}
			rev := func(id string) int { return int(max(latest[id], 1)) }

			s := NewStore()
			h := NewServer(s)
			txWant(t, "import", txDo(h, "POST", "/_test/import", "", "", string(raw)), 204)
			sumUsers := func() int64 {
				var sum int64
				for _, u := range src.State.Users {
					sum += txNum(txMe(t, h, owners[u.ID]), "balance")
				}
				return sum
			}
			sum := sumUsers()

			// Every earlier receipt still replays byte for byte; replays change nothing.
			var sys struct {
				State struct {
					Sys struct {
						Idem map[string]struct {
							Body string
							Resp json.RawMessage
						}
					}
				}
			}
			_ = json.Unmarshal(raw, &sys)
			before := txExport(t, s)
			for mk, rec := range sys.State.Sys.Idem {
				user, method, path, key := txParseIdemKey(t, mk)
				r := txDo(h, method, path, owners[user], key, rec.Body)
				if r.Code != 200 || !bytes.Equal(r.Body.Bytes(), rec.Resp) {
					t.Fatalf("replay %s: %d %s", mk, r.Code, r.Body)
				}
			}
			if !bytes.Equal(before, txExport(t, s)) {
				t.Fatal("replays changed the state")
			}

			// A stage-3 export gains exactly refund_of and correction_batch_id, nothing else.
			if strings.HasSuffix(file, "stage3-export.json") {
				got, want := txJSON(t, before), txJSON(t, raw)
				for _, p := range got["state"].(map[string]any)["payments"].([]any) {
					m := p.(map[string]any)
					if v, ok := m["refund_of"]; !ok || v != nil {
						t.Fatalf("payment %v: refund_of must be present and null", m["payment_id"])
					}
					delete(m, "refund_of")
				}
				for _, r := range got["state"].(map[string]any)["revisions"].([]any) {
					m := r.(map[string]any)
					if v, ok := m["correction_batch_id"]; !ok || v != nil {
						t.Fatalf("revision %v: correction_batch_id must be present and null", m)
					}
					delete(m, "correction_batch_id")
				}
				if !reflect.DeepEqual(got, want) {
					t.Fatal("a stage-3 export changed beyond refund_of and correction_batch_id on import")
				}
			}

			post := func(key string, items ...string) (int, []byte) {
				r := txDo(h, "POST", "/correction-batches", opTok, key, btBody(items...))
				return r.Code, r.Body.Bytes()
			}
			want := func(what, key string, status int, code string, items ...string) {
				t.Helper()
				e0 := txExport(t, s)
				c, b := post(key, items...)
				var env struct{ Error struct{ Code string } }
				_ = json.Unmarshal(b, &env)
				if c != status || env.Error.Code != code {
					t.Fatalf("%s: %d %s, want %d %s", what, c, b, status, code)
				}
				if !bytes.Equal(e0, txExport(t, s)) {
					t.Fatalf("%s: a rejected batch changed the state", what)
				}
			}
			const eff = "2026-09-27T10:00:00+00:00"

			members := map[string][]string{}
			var order []string
			var ordinary, captures []string
			for _, p := range src.State.Payments {
				switch {
				case p.SettlementID != nil:
					if _, seen := members[*p.SettlementID]; !seen {
						order = append(order, *p.SettlementID)
					}
					members[*p.SettlementID] = append(members[*p.SettlementID], p.PaymentID)
				case p.AuthorizationID != nil:
					captures = append(captures, p.PaymentID)
				case p.Amount > 0:
					ordinary = append(ordinary, p.PaymentID)
				}
			}
			if len(order) == 0 {
				t.Fatal("the export holds no settlement")
			}
			for i, c := range captures {
				want("capture "+c, "cap"+string(rune('a'+i)), 422, "linked_payment_immutable", btItem(c, rev(c), 1, eff))
			}
			for _, sid := range order {
				ids := members[sid]
				var partial []string
				for _, id := range ids[:len(ids)-1] {
					partial = append(partial, btItem(id, rev(id), 1, eff))
				}
				want("settlement "+sid+" missing its last member", "inc-"+sid, 422, "incomplete_settlement", partial...)
				var apart []string
				for i, id := range ids {
					at := eff
					if i == len(ids)-1 {
						at = "2026-09-27T10:00:01+00:00"
					}
					apart = append(apart, btItem(id, rev(id), 1, at))
				}
				want("settlement "+sid+" with one member a second off", "ins-"+sid, 422, "validation_failed", apart...)
			}
			// All members of every settlement, different offset spellings of one instant, plus ordinary payments.
			var items []string
			spell := []string{"2026-09-27T10:00:00+00:00", "2026-09-27T12:00:00+02:00", "2026-09-27T10:00:00Z", "2026-09-27T05:00:00-05:00"}
			for _, sid := range order {
				for i, id := range members[sid] {
					items = append(items, btItem(id, rev(id), 1, spell[i%len(spell)]))
				}
			}
			for _, id := range ordinary {
				items = append(items, btItem(id, rev(id), 1, eff))
			}
			if len(items) > 32 {
				items = items[:32]
			}
			t.Logf("%d settlements, %d ordinary payments, %d captures, %d batch items, %d receipts replayed", len(order), len(ordinary), len(captures), len(items), len(sys.State.Sys.Idem))
			c, b := post("all", items...)
			if c != 201 {
				t.Fatalf("batch over every imported settlement member and ordinary payment: %d %s", c, b)
			}
			var out btOut
			_ = json.Unmarshal(b, &out)
			if !btIDRe.MatchString(out.CorrectionBatchID) || len(out.Revisions) != len(items) {
				t.Fatalf("batch response: %s", b)
			}
			for _, r := range out.Revisions {
				if r.RecordedAt != out.RecordedAt || r.CorrectionBatchID == nil || *r.CorrectionBatchID != out.CorrectionBatchID || r.Revision != int64(rev(r.PaymentID))+1 {
					t.Fatalf("revision %+v of batch %s", r, out.CorrectionBatchID)
				}
			}
			if sumUsers() != sum {
				t.Fatal("the sum of balances changed")
			}
			// The imported history is intact and old revisions carry a null batch id.
			for _, r := range out.Revisions[:1] {
				var found bool
				for _, tok := range owners {
					rec := txDo(h, "GET", "/payments/"+r.PaymentID+"/revisions", tok, "", "")
					if rec.Code != 200 {
						continue
					}
					var hist struct{ Revisions []btRev }
					_ = json.Unmarshal(rec.Body.Bytes(), &hist)
					if n := len(hist.Revisions); n != rev(r.PaymentID)+1 || hist.Revisions[0].CorrectionBatchID != nil || hist.Revisions[n-1].CorrectionBatchID == nil {
						t.Fatalf("history of %s: %+v", r.PaymentID, hist.Revisions)
					}
					found = true
					break
				}
				if !found {
					t.Fatalf("nobody can read the revisions of %s", r.PaymentID)
				}
			}
			// The first batch replays, and the imported service round-trips its own new state byte for byte.
			if c2, b2 := post("all", items...); c2 != 200 || !bytes.Equal(b, b2) {
				t.Fatalf("replay: %d %s", c2, b2)
			}
			e1 := txExport(t, s)
			txWant(t, "re-import", txDo(h, "POST", "/_test/import", "", "", string(e1)), 204)
			if e2 := txExport(t, s); !bytes.Equal(e1, e2) {
				t.Fatal("export -> import -> export is not byte-identical after a batch on imported state")
			}
		})
	}
}
