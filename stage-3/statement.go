package main

import (
	"crypto/rand"
	"encoding/hex"
	"time"
)

// StatementQuery is the raw query of GET /statement: nil = parameter absent, a
// pointer to "" = present but empty (422). Limit and Offset are already parsed.
type StatementQuery struct {
	From, To, KnownAt, Snapshot *string
	Limit, Offset               int
}

// stmtEntry is one statement line. Payment is a frozen copy whose Amount is the
// selected revision's amount.
type stmtEntry struct {
	Payment      Payment `json:"payment"`
	Delta        int64   `json:"delta"`
	BalanceAfter int64   `json:"balance_after"`
	Revision     int64   `json:"revision"`
	EffectiveAt  string  `json:"effective_at"`
	RecordedAt   string  `json:"recorded_at"`
}

// stmtSnapshot is a frozen full-window statement. Nothing in it is ever modified
// after creation and it holds no pointer into live revisions, so later payments,
// corrections and lifecycle events cannot change what it pages.
type stmtSnapshot struct {
	owner            string
	opening, closing int64
	entries          []stmtEntry
}

type statementBody struct {
	OpeningBalance int64       `json:"opening_balance"`
	Entries        []stmtEntry `json:"entries"`
	ClosingBalance int64       `json:"closing_balance"`
	HasMore        bool        `json:"has_more"`
	Snapshot       string      `json:"snapshot"`
}

func (sn *stmtSnapshot) page(token string, limit, offset int) statementBody {
	entries, more := pageEntries(sn.entries, limit, offset)
	return statementBody{OpeningBalance: sn.opening, Entries: entries, ClosingBalance: sn.closing, HasMore: more, Snapshot: token}
}

// pageEntries returns the [offset, offset+limit) slice (never nil) and whether entries remain after it.
func pageEntries(all []stmtEntry, limit, offset int) ([]stmtEntry, bool) {
	if offset >= len(all) {
		return []stmtEntry{}, false
	}
	end := min(offset+limit, len(all))
	return all[offset:end:end], end < len(all)
}

func newSnapshotToken() (string, bool) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", false
	}
	return "snap_" + hex.EncodeToString(b[:]), true
}

// Statement is GET /statement. A read: it never stamps, only stores the snapshot.
// Validation order: snapshot combination, instants, window order, then the token lookup (404).
func (st *State) Statement(caller string, q StatementQuery, now time.Time) (any, *AppError) {
	u, e := st.caller(caller)
	if e != nil {
		return nil, e
	}
	if q.Snapshot != nil {
		if q.From != nil || q.To != nil || q.KnownAt != nil {
			return nil, errValidation("snapshot cannot be combined with from, to or known_at")
		}
		if *q.Snapshot == "" {
			return nil, errValidation("snapshot must not be empty")
		}
		sn := st.snaps[*q.Snapshot]
		if sn == nil || sn.owner != u.ID {
			return nil, errNotFound("no such statement snapshot")
		}
		return sn.page(*q.Snapshot, q.Limit, q.Offset), nil
	}

	from, hasFrom, e := optInstant(q.From, "from")
	if e != nil {
		return nil, e
	}
	to, hasTo, e := optInstant(q.To, "to")
	if e != nil {
		return nil, e
	}
	readNow := st.ReadNow(now)
	k, hasK, e := optInstant(q.KnownAt, "known_at")
	if e != nil {
		return nil, e
	}
	if !hasK {
		k = readNow
	}
	if hasFrom && hasTo && from.After(to) {
		return nil, errValidation("from must not be after to")
	}
	if !hasTo {
		// An omitted to is "now"; a from beyond it is an empty window, not an inverted one.
		to = readNow
		if hasFrom && from.After(to) {
			to = from
		}
	}

	opening := u.OpeningBalance
	bal := opening
	entries := []stmtEntry{}
	for _, m := range st.MovementsFor(u.ID, k) {
		if !m.Rev.eff.Before(to) {
			break // movements are in effective order
		}
		bal += m.Delta
		if hasFrom && m.Rev.eff.Before(from) {
			opening = bal
			continue
		}
		p := *m.Payment
		p.Amount = m.Rev.Amount
		entries = append(entries, stmtEntry{
			Payment: p, Delta: m.Delta, BalanceAfter: bal,
			Revision: m.Rev.Revision, EffectiveAt: m.Rev.EffectiveAt, RecordedAt: m.Rev.RecordedAt,
		})
	}

	token, ok := newSnapshotToken()
	if !ok {
		return nil, NewErr(500, "internal_error", "could not create a snapshot token")
	}
	sn := &stmtSnapshot{owner: u.ID, opening: opening, closing: bal, entries: entries}
	if st.snaps == nil {
		st.snaps = map[string]*stmtSnapshot{}
	}
	st.snaps[token] = sn
	return sn.page(token, q.Limit, q.Offset), nil
}

// optInstant parses an optional raw instant parameter; a present but empty or
// malformed value is a 422.
func optInstant(p *string, name string) (time.Time, bool, *AppError) {
	if p == nil {
		return time.Time{}, false, nil
	}
	t, ok := ParseInstant(*p)
	if !ok {
		return time.Time{}, false, errValidation(name + " must be an RFC 3339 instant with an offset")
	}
	return t, true, nil
}
