package main

import (
	"strconv"
	"strings"
)

func lowerEmail(e string) string { return strings.ToLower(e) }

const (
	statusPending   = "pending"
	statusPaid      = "paid"
	statusDeclined  = "declined"
	statusCancelled = "cancelled"

	visPublic  = "public"
	visPrivate = "private"
)

// State is the whole service state and is exactly the export "state" object.
// Unexported indexes are rebuilt by Reindex and never serialised.
type State struct {
	Currency   string `json:"currency"`
	MinorUnits int    `json:"minor_units"`

	Users    []*User    `json:"users"`
	Payments []*Payment `json:"payments"`
	Requests []*Request `json:"requests"`
	Splits   []*Split   `json:"splits"`

	Authorizations []*Authorization `json:"authorizations"`
	AuthTTLSeconds int64            `json:"authorization_ttl_seconds"` // 0 = unset, see TTL()

	Tokens map[string]string `json:"tokens"` // bearer token -> user id
	Seq    map[string]int64  `json:"seq"`    // id counters per prefix
	Sys    SysState          `json:"sys"`

	usersByID     map[string]*User
	usersByHandle map[string]*User
	usersByEmail  map[string]*User // key: lower-cased email
	reqByID       map[string]*Request
	authByID      map[string]*Authorization
	ids           map[string]struct{} // every id of any kind
}

type User struct {
	ID          string `json:"id"`
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	Handle      string `json:"handle"`
	PassHash    string `json:"pass_hash"`
	Balance     int64  `json:"balance"`
}

type Payment struct {
	PaymentID       string  `json:"payment_id"`
	FromUserID      string  `json:"from_user_id"`
	FromHandle      string  `json:"from_handle"`
	ToUserID        string  `json:"to_user_id"`
	ToHandle        string  `json:"to_handle"`
	Amount          int64   `json:"amount"`
	Currency        string  `json:"currency"`
	Note            string  `json:"note"`
	Visibility      string  `json:"visibility"`
	RequestID       *string `json:"request_id"`
	SettlementID    *string `json:"settlement_id"`
	AuthorizationID *string `json:"authorization_id"`
	CreatedAt       string  `json:"created_at"`
}

type Request struct {
	RequestID       string  `json:"request_id"`
	RequesterID     string  `json:"requester_id"`
	RequesterHandle string  `json:"requester_handle"`
	PayerID         string  `json:"payer_id"`
	PayerHandle     string  `json:"payer_handle"`
	Amount          int64   `json:"amount"`
	Currency        string  `json:"currency"`
	Note            string  `json:"note"`
	Status          string  `json:"status"`
	PaymentID       *string `json:"payment_id"`
	CreatedAt       string  `json:"created_at"`
}

// Split is the persisted record of a bill split; its requests live in State.Requests.
type Split struct {
	SplitID    string   `json:"split_id"`
	CreatorID  string   `json:"creator_id"`
	Amount     int64    `json:"amount"`
	Currency   string   `json:"currency"`
	Note       string   `json:"note"`
	Shares     []Share  `json:"shares"`
	RequestIDs []string `json:"request_ids"`
	CreatedAt  string   `json:"created_at"`
}

type Share struct {
	Handle string `json:"handle"`
	Amount int64  `json:"amount"`
}

func (st *State) UserByHandle(h string) *User { return st.usersByHandle[h] }

func (st *State) userByID(id string) *User { return st.usersByID[id] }

// caller resolves the authenticated user; a token can outlive its user across reset/import.
func (st *State) caller(id string) (*User, *AppError) {
	u := st.usersByID[id]
	if u == nil {
		return nil, errUnauthenticated()
	}
	return u, nil
}

func (st *State) addUser(u *User) {
	st.Users = append(st.Users, u)
	st.usersByID[u.ID] = u
	st.usersByHandle[u.Handle] = u
	if u.Email != "" {
		st.usersByEmail[lowerEmail(u.Email)] = u
	}
}

func (st *State) addRequest(r *Request) {
	st.Requests = append(st.Requests, r)
	st.reqByID[r.RequestID] = r
}

// NewID returns "<prefix>_<n>", skipping every id already in use (seeded ids such as p_1 included).
func (st *State) NewID(prefix string) string {
	if st.Seq == nil {
		st.Seq = map[string]int64{}
	}
	if st.ids == nil {
		st.ids = map[string]struct{}{}
	}
	for {
		st.Seq[prefix]++
		id := prefix + "_" + strconv.FormatInt(st.Seq[prefix], 10)
		if _, used := st.ids[id]; !used {
			st.ids[id] = struct{}{}
			return id
		}
	}
}
