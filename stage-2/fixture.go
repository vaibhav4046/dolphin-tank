package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const trMaxFixtureAmount = int64(1) << 53

var trHandleRe = regexp.MustCompile(`^[a-z0-9_]{1,20}$`)

var trDefaultMinor = map[string]int{"EUR": 2, "JPY": 0, "BHD": 3}

func trBad(format string, a ...any) *AppError {
	return NewErr(422, "validation_failed", fmt.Sprintf(format, a...))
}

// Reset replaces all state with the fixture. The new State is built and
// validated off to the side; s.st is swapped under s.mu only when it is valid.
func (s *Store) Reset(raw []byte) *AppError {
	st, e := trBuildFixture(raw, time.Now())
	if e != nil {
		return e
	}
	s.mu.Lock()
	s.st = st
	s.mu.Unlock()
	return nil
}

func trParseObject(raw []byte) (map[string]any, *AppError) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, NewErr(400, "malformed_request", "body is not valid JSON")
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, NewErr(400, "malformed_request", "body is not valid JSON")
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, NewErr(400, "malformed_request", "body must be a JSON object")
	}
	return m, nil
}

func trBuildFixture(raw []byte, now time.Time) (*State, *AppError) {
	root, e := trParseObject(raw)
	if e != nil {
		return nil, e
	}
	cur, minor, e := trFxCurrency(root)
	if e != nil {
		return nil, e
	}
	ids := &trIDs{used: map[string]bool{}, seq: map[string]int64{}}
	users, e := trFxUsers(root, ids)
	if e != nil {
		return nil, e
	}
	byID := make(map[string]*User, len(users))
	for _, u := range users {
		byID[u.ID] = u
	}
	created := FormatTime(now)
	pays, e := trFxPayments(root, ids, byID, cur, created)
	if e != nil {
		return nil, e
	}
	reqs, e := trFxRequests(root, ids, byID, cur, created)
	if e != nil {
		return nil, e
	}
	ops, e := trFxOperators(root)
	if e != nil {
		return nil, e
	}
	ttl, e := trFxTTL(root)
	if e != nil {
		return nil, e
	}
	auths, e := trFxAuthorizations(root, ids, byID, created)
	if e != nil {
		return nil, e
	}
	for _, p := range pays {
		if p.PaymentID == "" {
			p.PaymentID = ids.gen("p")
		}
	}
	for _, r := range reqs {
		if r.RequestID == "" {
			r.RequestID = ids.gen("rq")
		}
	}
	for _, a := range auths {
		if a.AuthorizationID == "" {
			a.AuthorizationID = ids.gen("a")
		}
	}
	st := &State{
		Currency: cur, MinorUnits: minor,
		Users: users, Payments: pays, Requests: reqs, Splits: []*Split{},
		Authorizations: auths, AuthTTLSeconds: ttl,
		Tokens: map[string]string{}, Seq: ids.seq,
		Sys: SysState{Operators: ops, Idem: map[string]*IdemRecord{}},
	}
	if e := trLinkCaptures(st); e != nil {
		return nil, e
	}
	if e := trCheckHolds(st, now); e != nil {
		return nil, e
	}
	if err := trSafeReindex(st, now); err != nil {
		return nil, trBad("invalid fixture: %v", err)
	}
	return st, nil
}

const (
	trDefaultTTL = int64(600)
	trMaxTTL     = int64(1_000_000_000)
)

// trFxTTL reads authorization_ttl_seconds: omitted or null means 600, anything
// else must be an integer from 1 to 1e9.
func trFxTTL(root map[string]any) (int64, *AppError) {
	v, ok := root["authorization_ttl_seconds"]
	if !ok || v == nil {
		return trDefaultTTL, nil
	}
	n, isNum := v.(json.Number)
	if !isNum {
		return 0, trBad("authorization_ttl_seconds must be a positive integer")
	}
	i, ok := trIntFromNumber(n)
	if !ok || i < 1 || i > trMaxTTL {
		return 0, trBad("authorization_ttl_seconds must be an integer from 1 to %d", trMaxTTL)
	}
	return i, nil
}

// trFxAuthorizations reads the seeded holds. The stored status is taken as
// given; the clock never rewrites it. expires_at is kept exactly as written.
func trFxAuthorizations(root map[string]any, ids *trIDs, byID map[string]*User, created string) ([]*Authorization, *AppError) {
	list, e := trList(root, "authorizations")
	if e != nil {
		return nil, e
	}
	out := make([]*Authorization, 0, len(list))
	for _, v := range list {
		o, ok := v.(map[string]any)
		if !ok {
			return nil, trBad("every authorization must be an object")
		}
		id, e := trOptID(o, ids)
		if e != nil {
			return nil, e
		}
		from, e := trFxUser(o, "from_user_id", byID)
		if e != nil {
			return nil, e
		}
		to, e := trFxUser(o, "to_user_id", byID)
		if e != nil {
			return nil, e
		}
		if from == to {
			return nil, trBad("authorization from_user_id and to_user_id must differ")
		}
		amount, present, e := trOptInt(o, "amount")
		if e != nil {
			return nil, e
		}
		if !present || amount < 1 || amount > trMaxFixtureAmount {
			return nil, trBad("authorization amount must be an integer from 1 to 2^53")
		}
		note, _, e := trOptString(o, "note")
		if e != nil {
			return nil, e
		}
		vis, present, e := trOptString(o, "visibility")
		if e != nil {
			return nil, e
		}
		if !present {
			vis = visPublic
		}
		if !validVisibility(vis) {
			return nil, trBad("visibility must be public or private")
		}
		status, present, e := trOptString(o, "status")
		if e != nil {
			return nil, e
		}
		if !present {
			status = "open"
		}
		switch status {
		case "open", "captured", "voided", "expired":
		default:
			return nil, trBad("authorization status %q is invalid", status)
		}
		exp, present, e := trOptString(o, "expires_at")
		if e != nil {
			return nil, e
		}
		if _, err := time.Parse(time.RFC3339, exp); !present || err != nil {
			return nil, trBad("authorization expires_at must be an RFC 3339 timestamp")
		}
		captured := int64(0)
		if status == "captured" {
			captured = amount
		}
		if c, present, e := trOptInt(o, "captured_amount"); e != nil {
			return nil, e
		} else if present {
			captured = c
		}
		if captured < 0 || captured > amount {
			return nil, trBad("captured_amount must be between 0 and the authorization amount")
		}
		payIDs, e := trFxStrings(o, "payment_ids")
		if e != nil {
			return nil, e
		}
		out = append(out, &Authorization{
			AuthorizationID: id, FromUserID: from.ID, ToUserID: to.ID,
			Amount: amount, CapturedAmount: captured, Note: note, Visibility: vis,
			Status: status, ExpiresAt: exp, PaymentIDs: payIDs, CreatedAt: created,
		})
	}
	return out, nil
}

func trFxStrings(o map[string]any, k string) ([]string, *AppError) {
	list, e := trList(o, k)
	if e != nil {
		return nil, e
	}
	out := make([]string, 0, len(list))
	for _, v := range list {
		s, ok := v.(string)
		if !ok {
			return nil, trBad("%s must contain strings", k)
		}
		out = append(out, s)
	}
	return out, nil
}

// trLinkCaptures checks that every payment_ids entry names a seeded payment and
// marks that payment as made by the authorization, so a seeded capture reads
// like one made through the API.
func trLinkCaptures(st *State) *AppError {
	pays := make(map[string]*Payment, len(st.Payments))
	for _, p := range st.Payments {
		pays[p.PaymentID] = p
	}
	for _, a := range st.Authorizations {
		for _, pid := range a.PaymentIDs {
			p := pays[pid]
			if p == nil {
				return trBad("authorization %s lists unknown payment %q", a.AuthorizationID, pid)
			}
			if p.AuthorizationID == nil {
				id := a.AuthorizationID
				p.AuthorizationID = &id
			}
		}
	}
	return nil
}

// trCheckHolds rejects a state in which some wallet's effectively open holds
// exceed its balance. It never adds past the balance, so it cannot overflow.
func trCheckHolds(st *State, now time.Time) *AppError {
	bal := make(map[string]int64, len(st.Users))
	for _, u := range st.Users {
		bal[u.ID] = u.Balance
	}
	held := make(map[string]int64, len(st.Authorizations))
	for _, a := range st.Authorizations {
		rem := a.RemainingAt(now)
		if rem <= 0 {
			continue
		}
		if rem > bal[a.FromUserID]-held[a.FromUserID] {
			return trBad("open holds of user %s exceed their balance", a.FromUserID)
		}
		held[a.FromUserID] += rem
	}
	return nil
}

func trFxCurrency(root map[string]any) (string, int, *AppError) {
	cur, present, e := trOptString(root, "currency")
	if e != nil {
		return "", 0, e
	}
	if !present {
		cur = "EUR"
	} else if cur == "" {
		return "", 0, trBad("currency must not be empty")
	}
	minor, ok := trDefaultMinor[cur]
	if !ok {
		minor = 2
	}
	mu, present, e := trOptInt(root, "minor_units")
	if e != nil {
		return "", 0, e
	}
	if present {
		if mu != 0 && mu != 2 && mu != 3 {
			return "", 0, trBad("minor_units must be 0, 2 or 3")
		}
		minor = int(mu)
	}
	return cur, minor, nil
}

// trIDs tracks every id in the fixture (one namespace) and the highest numeric
// suffix per prefix, so Seq starts at or above all of them.
type trIDs struct {
	used map[string]bool
	seq  map[string]int64
}

func (t *trIDs) claim(id string) bool {
	if t.used[id] {
		return false
	}
	t.used[id] = true
	if i := strings.LastIndexByte(id, '_'); i > 0 {
		if n, err := strconv.ParseInt(id[i+1:], 10, 64); err == nil && n > t.seq[id[:i]] {
			t.seq[id[:i]] = n
		}
	}
	return true
}

func (t *trIDs) gen(prefix string) string {
	for {
		t.seq[prefix]++
		id := prefix + "_" + strconv.FormatInt(t.seq[prefix], 10)
		if !t.used[id] {
			t.used[id] = true
			return id
		}
	}
}

func trOptString(o map[string]any, k string) (string, bool, *AppError) {
	v, ok := o[k]
	if !ok || v == nil {
		return "", false, nil
	}
	s, isStr := v.(string)
	if !isStr {
		return "", false, trBad("%s must be a string", k)
	}
	return s, true, nil
}

func trOptInt(o map[string]any, k string) (int64, bool, *AppError) {
	v, ok := o[k]
	if !ok || v == nil {
		return 0, false, nil
	}
	n, isNum := v.(json.Number)
	if !isNum {
		return 0, false, trBad("%s must be an integer", k)
	}
	i, ok := trIntFromNumber(n)
	if !ok {
		return 0, false, trBad("%s must be an integer", k)
	}
	return i, true, nil
}

func trList(o map[string]any, k string) ([]any, *AppError) {
	v, ok := o[k]
	if !ok || v == nil {
		return nil, nil
	}
	l, isList := v.([]any)
	if !isList {
		return nil, trBad("%s must be an array", k)
	}
	return l, nil
}

// trOptID returns the id of a fixture item; "" with no error means "absent,
// generate one". A present id must be 1..64 characters and unused.
func trOptID(o map[string]any, ids *trIDs) (string, *AppError) {
	id, present, e := trOptString(o, "id")
	if e != nil || !present {
		return "", e
	}
	if id == "" || utf8.RuneCountInString(id) > 64 {
		return "", trBad("id must be 1 to 64 characters")
	}
	if !ids.claim(id) {
		return "", trBad("duplicate id %q", id)
	}
	return id, nil
}

func trEmailOK(e string) bool {
	i := strings.IndexByte(e, '@')
	return i > 0 && i < len(e)-1 && strings.Count(e, "@") == 1 && !strings.ContainsAny(e, " \t\r\n")
}

func trFxUsers(root map[string]any, ids *trIDs) ([]*User, *AppError) {
	list, e := trList(root, "users")
	if e != nil {
		return nil, e
	}
	out := make([]*User, 0, len(list))
	pws := make([]string, 0, len(list))
	handles := map[string]bool{}
	for _, v := range list {
		o, ok := v.(map[string]any)
		if !ok {
			return nil, trBad("every user must be an object")
		}
		id, e := trOptID(o, ids)
		if e != nil {
			return nil, e
		}
		if id == "" {
			return nil, trBad("user id is required")
		}
		email, present, e := trOptString(o, "email")
		if e != nil || !present || !trEmailOK(email) {
			return nil, trBad("user %s: email must be local@domain", id)
		}
		pw, present, e := trOptString(o, "password")
		if e != nil || !present {
			return nil, trBad("user %s: password is required", id)
		}
		dn, _, e := trOptString(o, "display_name")
		if e != nil {
			return nil, e
		}
		h, present, e := trOptString(o, "handle")
		if e != nil {
			return nil, e
		}
		if !present {
			h = DeriveHandle(email)
		}
		if !trHandleRe.MatchString(h) || handles[h] {
			return nil, trBad("user %s: handle %q is invalid or duplicate", id, h)
		}
		handles[h] = true
		bal, _, e := trOptInt(o, "balance")
		if e != nil {
			return nil, e
		}
		if bal < 0 || bal > trMaxFixtureAmount {
			return nil, trBad("user %s: balance out of range", id)
		}
		out = append(out, &User{ID: id, Email: email, DisplayName: dn, Handle: h, Balance: bal})
		pws = append(pws, pw)
	}
	hashes := trHashAll(pws)
	for i, u := range out {
		u.PassHash = hashes[pws[i]]
	}
	return out, nil
}

// trHashAll hashes each distinct password once, in parallel across CPUs. Seeded
// users who share a password share a hash within one reset; this keeps a
// 500-user reset fast. Signup hashes every password with its own salt.
func trHashAll(pws []string) map[string]string {
	out := make(map[string]string, len(pws))
	distinct := make([]string, 0, len(pws))
	for _, p := range pws {
		if _, seen := out[p]; !seen {
			out[p] = ""
			distinct = append(distinct, p)
		}
	}
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, runtime.NumCPU())
	for _, p := range distinct {
		wg.Add(1)
		sem <- struct{}{}
		go func(p string) {
			defer wg.Done()
			h := HashPassword(p)
			mu.Lock()
			out[p] = h
			mu.Unlock()
			<-sem
		}(p)
	}
	wg.Wait()
	return out
}

func trFxAmount(o map[string]any) (int64, *AppError) {
	a, present, e := trOptInt(o, "amount")
	if e != nil {
		return 0, e
	}
	if !present || a < 0 || a > trMaxFixtureAmount {
		return 0, trBad("amount must be an integer from 0 to 2^53")
	}
	return a, nil
}

func trFxUser(o map[string]any, k string, byID map[string]*User) (*User, *AppError) {
	id, present, e := trOptString(o, k)
	if e != nil {
		return nil, e
	}
	u := byID[id]
	if !present || u == nil {
		return nil, trBad("%s refers to an unknown user", k)
	}
	return u, nil
}

func trFxPayments(root map[string]any, ids *trIDs, byID map[string]*User, cur, created string) ([]*Payment, *AppError) {
	list, e := trList(root, "payments")
	if e != nil {
		return nil, e
	}
	out := make([]*Payment, 0, len(list))
	for _, v := range list {
		o, ok := v.(map[string]any)
		if !ok {
			return nil, trBad("every payment must be an object")
		}
		id, e := trOptID(o, ids)
		if e != nil {
			return nil, e
		}
		from, e := trFxUser(o, "from_user_id", byID)
		if e != nil {
			return nil, e
		}
		to, e := trFxUser(o, "to_user_id", byID)
		if e != nil {
			return nil, e
		}
		amount, e := trFxAmount(o)
		if e != nil {
			return nil, e
		}
		note, _, e := trOptString(o, "note")
		if e != nil {
			return nil, e
		}
		vis, present, e := trOptString(o, "visibility")
		if e != nil {
			return nil, e
		}
		if !present {
			vis = "public"
		}
		if vis != "public" && vis != "private" {
			return nil, trBad("visibility must be public or private")
		}
		var reqID *string
		if r, present, e := trOptString(o, "request_id"); e != nil {
			return nil, e
		} else if present {
			reqID = &r
		}
		out = append(out, &Payment{
			PaymentID: id, FromUserID: from.ID, FromHandle: from.Handle,
			ToUserID: to.ID, ToHandle: to.Handle, Amount: amount, Currency: cur,
			Note: note, Visibility: vis, RequestID: reqID, CreatedAt: created,
		})
	}
	return out, nil
}

func trFxRequests(root map[string]any, ids *trIDs, byID map[string]*User, cur, created string) ([]*Request, *AppError) {
	list, e := trList(root, "requests")
	if e != nil {
		return nil, e
	}
	out := make([]*Request, 0, len(list))
	for _, v := range list {
		o, ok := v.(map[string]any)
		if !ok {
			return nil, trBad("every request must be an object")
		}
		id, e := trOptID(o, ids)
		if e != nil {
			return nil, e
		}
		requester, e := trFxUser(o, "requester_id", byID)
		if e != nil {
			return nil, e
		}
		payer, e := trFxUser(o, "payer_id", byID)
		if e != nil {
			return nil, e
		}
		amount, e := trFxAmount(o)
		if e != nil {
			return nil, e
		}
		note, _, e := trOptString(o, "note")
		if e != nil {
			return nil, e
		}
		status, present, e := trOptString(o, "status")
		if e != nil {
			return nil, e
		}
		if !present {
			status = "pending"
		}
		switch status {
		case "pending", "paid", "declined", "cancelled":
		default:
			return nil, trBad("request status %q is invalid", status)
		}
		var payID *string
		if p, present, e := trOptString(o, "payment_id"); e != nil {
			return nil, e
		} else if present {
			payID = &p
		}
		out = append(out, &Request{
			RequestID: id, RequesterID: requester.ID, RequesterHandle: requester.Handle,
			PayerID: payer.ID, PayerHandle: payer.Handle, Amount: amount, Currency: cur,
			Note: note, Status: status, PaymentID: payID, CreatedAt: created,
		})
	}
	return out, nil
}

// trFxOperators reads settlement_operator_ids (default []). Ids that match no
// user are tolerated.
func trFxOperators(root map[string]any) (map[string]bool, *AppError) {
	list, e := trList(root, "settlement_operator_ids")
	if e != nil {
		return nil, e
	}
	ops := make(map[string]bool, len(list))
	for _, v := range list {
		id, ok := v.(string)
		if !ok {
			return nil, trBad("settlement_operator_ids must be strings")
		}
		ops[id] = true
	}
	return ops, nil
}

// trSafeReindex turns a panic on a malformed State into an error so imports
// and resets can never crash the service.
func trSafeReindex(st *State, now time.Time) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("inconsistent state: %v", r)
		}
	}()
	return st.ReindexAt(now)
}
