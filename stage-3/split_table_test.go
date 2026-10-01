package main

import (
	"encoding/json"
	"os"
	"slices"
	"testing"
)

// TestSplitSharesTable checks SplitShares against jstest/split-table.json, the same table the JS
// splitShares test reads. The table is dealt round-robin, independent of SplitShares' closed form.
func TestSplitSharesTable(t *testing.T) {
	raw, err := os.ReadFile("jstest/split-table.json")
	if err != nil {
		t.Fatal(err)
	}
	var table []struct {
		Amount int64   `json:"amount"`
		N      int     `json:"n"`
		Shares []int64 `json:"shares"`
	}
	if err := json.Unmarshal(raw, &table); err != nil {
		t.Fatal(err)
	}
	if len(table) != 60*8 {
		t.Fatalf("table has %d rows, want %d", len(table), 60*8)
	}
	for _, row := range table {
		if got := SplitShares(row.Amount, row.N); !slices.Equal(got, row.Shares) {
			t.Errorf("SplitShares(%d, %d) = %v, want %v", row.Amount, row.N, got, row.Shares)
		}
	}
	for _, c := range []struct {
		amount int64
		n      int
		want   []int64
	}{{1000, 3, []int64{334, 333, 333}}, {999, 3, []int64{333, 333, 333}}} {
		if got := SplitShares(c.amount, c.n); !slices.Equal(got, c.want) {
			t.Errorf("SplitShares(%d, %d) = %v, want %v", c.amount, c.n, got, c.want)
		}
	}
}
