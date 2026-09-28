package config

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"strings"
)

// AES-256-GCM secret storage for brokerage credentials.
//
// The 32-byte key is read from CDF_SECRET_KEY as base64 (preferred) or hex.
// Secrets are never logged. When the key is absent, encryption is disabled and
// callers must refuse to persist credentials.

var (
	ErrSecretKeyMissing = errors.New("CDF_SECRET_KEY is not configured (32-byte base64 or hex)")
	ErrSecretKeyInvalid = errors.New("CDF_SECRET_KEY must decode to 32 bytes (AES-256)")
)

// secretKey decodes CDF_SECRET_KEY once per call site invocation.
func secretKey() ([]byte, error) {
	raw := strings.TrimSpace(os.Getenv("CDF_SECRET_KEY"))
	if raw == "" {
		return nil, ErrSecretKeyMissing
	}
	// base64 first (std, then raw), then hex.
	if b, err := base64.StdEncoding.DecodeString(raw); err == nil && len(b) == 32 {
		return b, nil
	}
	if b, err := base64.RawStdEncoding.DecodeString(raw); err == nil && len(b) == 32 {
		return b, nil
	}
	if b, err := hex.DecodeString(raw); err == nil && len(b) == 32 {
		return b, nil
	}
	return nil, ErrSecretKeyInvalid
}

// SecretsEnabled reports whether a valid encryption key is configured.
func SecretsEnabled() bool {
	_, err := secretKey()
	return err == nil
}

// EncryptString returns (ciphertext base64, nonce base64) for the plaintext.
func EncryptString(plain string) (string, string, error) {
	key, err := secretKey()
	if err != nil {
		return "", "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", "", err
	}
	ct := gcm.Seal(nil, nonce, []byte(plain), nil)
	return base64.StdEncoding.EncodeToString(ct), base64.StdEncoding.EncodeToString(nonce), nil
}

// DecryptString reverses EncryptString.
func DecryptString(cipherB64, nonceB64 string) (string, error) {
	key, err := secretKey()
	if err != nil {
		return "", err
	}
	ct, err := base64.StdEncoding.DecodeString(cipherB64)
	if err != nil {
		return "", err
	}
	nonce, err := base64.StdEncoding.DecodeString(nonceB64)
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	plain, err := gcm.Open(nil, nonce, ct, nil)
	if err != nil {
		return "", err
	}
	return string(plain), nil
}
