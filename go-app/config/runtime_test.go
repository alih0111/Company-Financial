package config

import "testing"

func TestDevelopmentBindsToLoopbackByDefault(t *testing.T) {
	t.Setenv("HOST", "")
	if ListenHost() != "127.0.0.1" {
		t.Fatal("development exposed on all interfaces")
	}
}

func TestProductionConfiguration(t *testing.T) {
	t.Setenv("APP_ENV", "production")
	t.Setenv("JWT_SECRET", "test-only-production-secret-32-bytes-minimum")
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	t.Setenv("CDF_REGISTRATION_ENABLED", "0")
	t.Setenv("DATABASE_URL", "postgresql://user:password@localhost/company_financial_test_config")
	for _, key := range []string{"CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "CDF_CANONICAL_DB", "CDF_PILOT_DB", "CORS_ALLOWED_ORIGINS", "SMTP_PORT", "AI_CHAT_URL", "TRUSTED_PROXIES"} {
		t.Setenv(key, "")
	}
	if err := ValidateRuntime(); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CORS_ALLOWED_ORIGINS", "*")
	if ValidateRuntime() == nil {
		t.Fatal("wildcard CORS accepted")
	}
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	t.Setenv("JWT_SECRET", "short")
	if ValidateRuntime() == nil {
		t.Fatal("weak JWT key accepted")
	}
	t.Setenv("JWT_SECRET", "test-only-production-secret-32-bytes-minimum")
	t.Setenv("CDF_REGISTRATION_ENABLED", "1")
	t.Setenv("SMTP_EMAIL", "")
	t.Setenv("SMTP_PASSWORD", "")
	if ValidateRuntime() == nil {
		t.Fatal("registration enabled without email provider")
	}
}
