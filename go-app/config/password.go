package config

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"golang.org/x/crypto/argon2"
	"golang.org/x/crypto/bcrypt"
	"strconv"
	"strings"
	"unicode/utf8"
)

func ValidNewPassword(password string) bool {
	if !utf8.ValidString(password) || utf8.RuneCountInString(password) < 15 || len(password) > 72 {
		return false
	}
	characters := []rune(password)
	different := false
	for _, character := range characters[1:] {
		if character != characters[0] {
			different = true
			break
		}
	}
	if !different || strings.TrimSpace(password) == "" {
		return false
	}
	switch strings.ToLower(password) {
	case "passwordpassword", "passwordpasswordpassword", "123456789012345", "1234567890123456", "qwertyuiopasdfgh", "111111111111111", "000000000000000", "abcdefghijklmnop":
		return false
	}
	return true
}

// Memory-hard password hashing for new accounts. Legacy bcrypt hashes remain
// readable; existing account credentials are never rewritten during this task.
func HashPassword(password string) (string, error) {
	var salt [16]byte
	if _, err := rand.Read(salt[:]); err != nil {
		return "", err
	}
	key := argon2.IDKey([]byte(password), salt[:], 3, 64*1024, 1, 32)
	return fmt.Sprintf("$argon2id$v=19$m=65536,t=3,p=1$%s$%s", base64.RawStdEncoding.EncodeToString(salt[:]), base64.RawStdEncoding.EncodeToString(key)), nil
}

func VerifyPassword(encoded, password string) bool {
	if len(password) > 72 || len(encoded) > 256 {
		return false
	}
	if strings.HasPrefix(encoded, "$2a$") || strings.HasPrefix(encoded, "$2b$") || strings.HasPrefix(encoded, "$2y$") {
		return bcrypt.CompareHashAndPassword([]byte(encoded), []byte(password)) == nil
	}
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[1] != "argon2id" || parts[2] != "v=19" {
		return false
	}
	parameters := strings.Split(parts[3], ",")
	if len(parameters) != 3 {
		return false
	}
	parse := func(value, prefix string) (uint64, error) {
		if !strings.HasPrefix(value, prefix) {
			return 0, fmt.Errorf("invalid hash parameters")
		}
		return strconv.ParseUint(strings.TrimPrefix(value, prefix), 10, 32)
	}
	memory, err := parse(parameters[0], "m=")
	if err != nil || memory < 19*1024 || memory > 64*1024 {
		return false
	}
	iterations, err := parse(parameters[1], "t=")
	if err != nil || iterations < 2 || iterations > 3 {
		return false
	}
	parallel, err := parse(parameters[2], "p=")
	if err != nil || parallel != 1 {
		return false
	}
	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil || len(salt) != 16 {
		return false
	}
	want, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil || len(want) != 32 {
		return false
	}
	got := argon2.IDKey([]byte(password), salt, uint32(iterations), uint32(memory), uint8(parallel), 32)
	return subtle.ConstantTimeCompare(got, want) == 1
}
