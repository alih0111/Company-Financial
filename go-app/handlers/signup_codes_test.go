package handlers

import (
	"go-app/config"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestSignupCodeExpiryReplayAndAttempts(t *testing.T) {
	for _, scenario := range []string{"expired", "replay", "attempts"} {
		t.Run(scenario, func(t *testing.T) {
			store := signupCodeStore{codes: map[string]signupCode{}}
			now := time.Now()
			code, err := store.issue("user@example.com", now)
			if err != nil || len(code) != 6 {
				t.Fatal("code generation failed")
			}
			if _, err := store.issue("user@example.com", now.Add(10*time.Second)); err == nil {
				t.Fatal("resend cooldown bypassed")
			}
			switch scenario {
			case "expired":
				if store.consume("user@example.com", code, now.Add(10*time.Minute)) {
					t.Fatal("expired code accepted")
				}
			case "replay":
				if !store.consume("user@example.com", code, now) {
					t.Fatal("valid code rejected")
				}
				if store.consume("user@example.com", code, now) {
					t.Fatal("code reused")
				}
			case "attempts":
				for i := 0; i < 5; i++ {
					store.consume("user@example.com", "invalid", now)
				}
				if store.consume("user@example.com", code, now) {
					t.Fatal("attempt limit bypassed")
				}
			}
		})
	}
}

func TestSignupCodeConcurrentConsumption(t *testing.T) {
	store := signupCodeStore{codes: map[string]signupCode{}}
	now := time.Now()
	code, _ := store.issue("user@example.com", now)
	var count atomic.Int32
	var workers sync.WaitGroup
	for i := 0; i < 30; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			if store.consume("user@example.com", code, now) {
				count.Add(1)
			}
		}()
	}
	workers.Wait()
	if count.Load() != 1 {
		t.Fatalf("code accepted %d times", count.Load())
	}
}

func TestSignupValidation(t *testing.T) {
	if normalizeEmail("  User@Example.com ") != "user@example.com" {
		t.Fatal("email not normalized")
	}
	for _, email := range []string{"x", "Name <a@b.com>", "a@b.com\r\nBcc: victim@b.com"} {
		if normalizeEmail(email) != "" {
			t.Fatal("invalid address accepted")
		}
	}
	for _, username := range []string{"ab", "user@example.com", "user name", "a\nb"} {
		if validRegistration("user@example.com", username, "a-long-test-password123") {
			t.Fatal("ambiguous username accepted")
		}
	}
	if validRegistration("user@example.com", "user", "short") || validRegistration("user@example.com", "user", string(make([]byte, 73))) {
		t.Fatal("invalid password accepted")
	}
	if !validRegistration("user@example.com", "کاربر۱", "a-long-test-password123") {
		t.Fatal("Persian username rejected")
	}
}

func TestNewPasswordsCannotUseShortUnicodeOrCommonPatterns(t *testing.T) {
	for _, password := range []string{"رمزکوتاه", "password123", "123456789012345", "passwordpassword"} {
		if config.ValidNewPassword(password) {
			t.Fatal("weak password accepted")
		}
	}
	if !config.ValidNewPassword("یک عبارت طولانی و امن") {
		t.Fatal("Unicode passphrase rejected")
	}
}
