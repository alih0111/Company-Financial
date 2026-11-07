package handlers

import (
	"crypto/sha256"
	"go-app/config"
	"strings"
	"sync"
	"time"
)

// Same password work for a missing account and an incorrect password; prevents
// the easy timing oracle without storing or logging attempted credentials.
var dummyLoginHash, _ = config.HashPassword("unusable-password-for-missing-account")

type loginWindow struct {
	attempts int
	expires  time.Time
}

var loginWindows = struct {
	sync.Mutex
	entries map[[32]byte]loginWindow
}{entries: map[[32]byte]loginWindow{}}

func allowLoginAttempt(identifier string, now time.Time) bool {
	key := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(identifier))))
	loginWindows.Lock()
	defer loginWindows.Unlock()
	if len(loginWindows.entries) >= 10000 {
		for k, v := range loginWindows.entries {
			if !now.Before(v.expires) {
				delete(loginWindows.entries, k)
			}
		}
	}
	v, found := loginWindows.entries[key]
	if !found && len(loginWindows.entries) >= 10000 {
		return false
	}
	if !now.Before(v.expires) {
		v = loginWindow{expires: now.Add(15 * time.Minute)}
	}
	if v.attempts >= 10 {
		return false
	}
	v.attempts++
	loginWindows.entries[key] = v
	return true
}

func clearLoginAttempts(identifier string) {
	key := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(identifier))))
	loginWindows.Lock()
	delete(loginWindows.entries, key)
	loginWindows.Unlock()
}
