package config

import (
	"encoding/base64"
	"os"
	"testing"
)

func TestSecretsRoundTrip(t *testing.T) {
	key := make([]byte, 32)
	for i := range key {
		key[i] = byte(i + 1)
	}
	t.Setenv("CDF_SECRET_KEY", base64.StdEncoding.EncodeToString(key))

	if !SecretsEnabled() {
		t.Fatal("SecretsEnabled() = false with a valid key")
	}
	plain := "رمز عبور من !@# 123"
	ct, nonce, err := EncryptString(plain)
	if err != nil {
		t.Fatalf("EncryptString: %v", err)
	}
	if ct == plain || ct == "" {
		t.Fatal("ciphertext looks wrong")
	}
	got, err := DecryptString(ct, nonce)
	if err != nil {
		t.Fatalf("DecryptString: %v", err)
	}
	if got != plain {
		t.Fatalf("round-trip mismatch: %q", got)
	}
}

func TestSecretsInvalidKey(t *testing.T) {
	t.Setenv("CDF_SECRET_KEY", "not-a-valid-key")
	if SecretsEnabled() {
		t.Fatal("SecretsEnabled() = true with an invalid key")
	}
	if _, _, err := EncryptString("x"); err == nil {
		t.Fatal("EncryptString should fail without a valid key")
	}
}

func TestSecretsMissingKey(t *testing.T) {
	os.Unsetenv("CDF_SECRET_KEY")
	if _, err := secretKey(); err == nil {
		t.Fatal("secretKey should fail when unset")
	}
}
