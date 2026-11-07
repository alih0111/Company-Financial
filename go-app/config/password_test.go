package config

import (
	"golang.org/x/crypto/bcrypt"
	"strings"
	"testing"
)

func TestNewPasswordHashAndLegacyCompatibility(t *testing.T) {
	password := "a-long-password-for-test"
	hash, err := HashPassword(password)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(hash, "$argon2id$") || !VerifyPassword(hash, password) || VerifyPassword(hash, "incorrect") {
		t.Fatal("password verification failed")
	}
	legacy, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil || !VerifyPassword(string(legacy), password) {
		t.Fatal("existing bcrypt account locked out")
	}
}

func TestMalformedPasswordHashesCannotRequestUnboundedMemory(t *testing.T) {
	for _, hash := range []string{"", "$argon2id$v=19$m=999999999,t=3,p=1$AAAA$AAAA", "$argon2id$v=19$m=65536,t=99999,p=1$AAAA$AAAA", "$argon2id$v=19$m=65536,t=3,p=1$invalid$invalid"} {
		if VerifyPassword(hash, "password") {
			t.Fatal("invalid hash accepted")
		}
	}
}
