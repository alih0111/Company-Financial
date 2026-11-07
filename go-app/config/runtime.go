package config

import (
	"fmt"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
)

func Production() bool  { return strings.EqualFold(os.Getenv("APP_ENV"), "production") }
func JWTSecret() []byte { return []byte(os.Getenv("JWT_SECRET")) }
func ListenHost() string {
	if value := strings.TrimSpace(os.Getenv("HOST")); value != "" {
		return value
	}
	return "127.0.0.1"
}
func RegistrationEnabled() bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv("CDF_REGISTRATION_ENABLED")))
	return v != "0" && v != "false"
}
func SMTPConfigured() bool { return os.Getenv("SMTP_EMAIL") != "" && os.Getenv("SMTP_PASSWORD") != "" }
func SMTPHost() string {
	if v := strings.TrimSpace(os.Getenv("SMTP_HOST")); v != "" {
		return v
	}
	return "smtp.gmail.com"
}
func SMTPPort() int {
	if n, err := strconv.Atoi(os.Getenv("SMTP_PORT")); err == nil && n > 0 && n < 65536 {
		return n
	}
	return 587
}

// Validate at startup, never during import: CLI tools and tests need no .env.
func ValidateRuntime() error {
	if _, err := DefaultDataLimits(); err != nil {
		return err
	}
	if value := os.Getenv("PORT"); value != "" {
		port, err := strconv.Atoi(value)
		if err != nil || port < 1 || port > 65535 {
			return fmt.Errorf("PORT must be between 1 and 65535")
		}
	}
	if len(JWTSecret()) < 32 {
		return fmt.Errorf("JWT_SECRET must contain at least 32 bytes")
	}
	if !Production() {
		return nil
	}
	for _, proxy := range CSVEnv("TRUSTED_PROXIES") {
		if prefix, err := netip.ParsePrefix(proxy); err == nil && prefix.Bits() == 0 {
			return fmt.Errorf("TRUSTED_PROXIES cannot trust the entire Internet")
		}
	}
	if SQLServerMode() != "offline_expected" {
		return fmt.Errorf("production requires CDF_SQLSERVER_MODE=offline_expected")
	}
	if RegistrationEnabled() && !SMTPConfigured() {
		return fmt.Errorf("registration requires SMTP_EMAIL and SMTP_PASSWORD (or CDF_REGISTRATION_ENABLED=0)")
	}
	if v := os.Getenv("SMTP_PORT"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 65535 {
			return fmt.Errorf("invalid SMTP_PORT")
		}
	}
	if _, err := pgDSNReadWrite(); err != nil {
		return fmt.Errorf("production PostgreSQL configuration is invalid")
	}
	if raw := strings.TrimSpace(os.Getenv("AI_CHAT_URL")); raw != "" {
		u, err := url.Parse(raw)
		if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" {
			return fmt.Errorf("production AI_CHAT_URL requires HTTPS without embedded credentials")
		}
	}
	for _, origin := range CSVEnv("CORS_ALLOWED_ORIGINS") {
		u, err := url.Parse(origin)
		if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" {
			return fmt.Errorf("production CORS_ALLOWED_ORIGINS must contain HTTPS origins")
		}
	}
	return nil
}

func CSVEnv(key string) []string {
	var values []string
	for _, value := range strings.Split(os.Getenv(key), ",") {
		if v := strings.TrimSpace(value); v != "" {
			values = append(values, v)
		}
	}
	return values
}
