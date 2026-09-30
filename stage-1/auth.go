package main

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"strconv"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"
)

const (
	pbkdf2Iter    = 20000 // ~10 ms per hash on a current x86 core
	pbkdf2MaxIter = 1_000_000
	saltLen       = 16
	keyLen        = 32
	minPassword   = 8
	tokenBytes    = 32
	hashScheme    = "pbkdf2-sha256"
)

type authBody struct {
	UserID      string `json:"user_id"`
	DisplayName string `json:"display_name"`
	Token       string `json:"token"`
}

func pbkdf2Key(pw string, salt []byte, iter, n int) []byte {
	k, err := pbkdf2.Key(sha256.New, pw, salt, iter, n)
	if err != nil {
		panic(err) // only possible under FIPS-only parameter limits, never in this image
	}
	return k
}

// HashPassword returns a self-describing salted hash: "pbkdf2-sha256$<iter>$<salt hex>$<key hex>".
func HashPassword(pw string) string {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		panic(err)
	}
	return hashScheme + "$" + strconv.Itoa(pbkdf2Iter) + "$" + hex.EncodeToString(salt) + "$" +
		hex.EncodeToString(pbkdf2Key(pw, salt, pbkdf2Iter, keyLen))
}

// CheckPassword compares in constant time; any malformed stored value simply fails.
func CheckPassword(stored, pw string) bool {
	parts := strings.Split(stored, "$")
	if len(parts) != 4 || parts[0] != hashScheme {
		return false
	}
	iter, err := strconv.Atoi(parts[1])
	if err != nil || iter < 1 || iter > pbkdf2MaxIter {
		return false
	}
	salt, err1 := hex.DecodeString(parts[2])
	want, err2 := hex.DecodeString(parts[3])
	if err1 != nil || err2 != nil || len(want) == 0 || len(want) > 64 {
		return false
	}
	return subtle.ConstantTimeCompare(pbkdf2Key(pw, salt, iter, len(want)), want) == 1
}

// DeriveHandle is the §4 rule: local part, lower-cased, every char outside [a-z0-9_] -> "_", first 20.
func DeriveHandle(email string) string {
	local, _, _ := strings.Cut(email, "@")
	var b strings.Builder
	for _, r := range strings.ToLower(local) {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteByte('_')
		}
		if b.Len() == 20 {
			break
		}
	}
	return b.String()
}

func validEmail(e string) bool {
	if strings.Count(e, "@") != 1 || strings.IndexFunc(e, unicode.IsSpace) >= 0 {
		return false
	}
	local, domain, _ := strings.Cut(e, "@")
	return local != "" && domain != ""
}

func (st *State) newToken(userID string) string {
	b := make([]byte, tokenBytes)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	tok := hex.EncodeToString(b)
	st.Tokens[tok] = userID
	return tok
}

var (
	dummyHashOnce sync.Once
	dummyHash     string
)

// Signup: field rules 422, then email_taken 409, then handle_taken 409; nothing is created on failure.
func (s *Store) Signup(email, password, displayName string) ([]byte, *AppError) {
	if !validEmail(email) {
		return nil, errValidation("email must be of the form local@domain")
	}
	if utf8.RuneCountInString(password) < minPassword {
		return nil, errValidation("password must be at least 8 characters")
	}
	if displayName == "" {
		return nil, errValidation("display_name must not be empty")
	}
	hash := HashPassword(password) // outside the lock
	handle := DeriveHandle(email)

	s.mu.Lock()
	defer s.mu.Unlock()
	st := s.st
	if st.usersByEmail[lowerEmail(email)] != nil {
		return nil, NewErr(409, "email_taken", "email is already registered")
	}
	if st.usersByHandle[handle] != nil {
		return nil, NewErr(409, "handle_taken", "the handle derived from this email is already taken")
	}
	u := &User{ID: st.NewID("u"), Email: email, DisplayName: displayName, Handle: handle, PassHash: hash}
	st.addUser(u)
	return marshalBody(authBody{UserID: u.ID, DisplayName: u.DisplayName, Token: st.newToken(u.ID)})
}

// Login verifies the password outside the lock, then re-checks the user under it (state may have been replaced).
func (s *Store) Login(email, password string) ([]byte, *AppError) {
	s.mu.Lock()
	var id, stored string
	if u := s.st.usersByEmail[lowerEmail(email)]; u != nil {
		id, stored = u.ID, u.PassHash
	}
	s.mu.Unlock()

	if id == "" {
		dummyHashOnce.Do(func() { dummyHash = HashPassword("dummy-password") })
		CheckPassword(dummyHash, password) // equalise timing for unknown emails
		return nil, errUnauthenticated()
	}
	if !CheckPassword(stored, password) {
		return nil, errUnauthenticated()
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	u := s.st.usersByID[id]
	if u == nil || u.PassHash != stored {
		return nil, errUnauthenticated()
	}
	return marshalBody(authBody{UserID: u.ID, DisplayName: u.DisplayName, Token: s.st.newToken(u.ID)})
}
