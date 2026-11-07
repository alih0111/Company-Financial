package handlers

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"fmt"
	"go-app/config"
	"math/big"
	"net/mail"
	"strings"
	"sync"
	"time"
	"unicode"
)

type signupCode struct {
	hash     [32]byte
	sentAt   time.Time
	attempts int
}
type signupCodeStore struct {
	sync.Mutex
	codes map[string]signupCode
}

var signupCodes = signupCodeStore{codes: make(map[string]signupCode)}

func normalizeEmail(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	a, err := mail.ParseAddress(value)
	if err != nil || a.Address != value || len(value) > 254 {
		return ""
	}
	return value
}

func validRegistration(email, username, password string) bool {
	if email == "" || !config.ValidNewPassword(password) || len([]rune(username)) < 3 || len([]rune(username)) > 64 {
		return false
	}
	for _, c := range username {
		if !unicode.IsLetter(c) && !unicode.IsDigit(c) && c != '_' && c != '-' && c != '.' {
			return false
		}
	}
	return true
}

func (s *signupCodeStore) issue(email string, now time.Time) (string, error) {
	s.Lock()
	defer s.Unlock()
	for key, code := range s.codes {
		if now.Sub(code.sentAt) >= 10*time.Minute {
			delete(s.codes, key)
		}
	}
	if old, ok := s.codes[email]; ok && now.Sub(old.sentAt) < time.Minute {
		return "", errors.New("cooldown")
	}
	if len(s.codes) >= 10000 {
		return "", errors.New("capacity")
	}
	n, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		return "", err
	}
	code := fmt.Sprintf("%06d", n.Int64())
	s.codes[email] = signupCode{hash: sha256.Sum256([]byte(code)), sentAt: now}
	return code, nil
}

// Consuming a code is atomic. At most one concurrent registration can use it.
func (s *signupCodeStore) consume(email, code string, now time.Time) bool {
	s.Lock()
	defer s.Unlock()
	old, ok := s.codes[email]
	if !ok {
		return false
	}
	if now.Sub(old.sentAt) >= 10*time.Minute || old.attempts >= 5 {
		delete(s.codes, email)
		return false
	}
	hash := sha256.Sum256([]byte(code))
	if subtle.ConstantTimeCompare(hash[:], old.hash[:]) != 1 {
		old.attempts++
		s.codes[email] = old
		return false
	}
	delete(s.codes, email)
	return true
}

func (s *signupCodeStore) discard(email string) { s.Lock(); delete(s.codes, email); s.Unlock() }
