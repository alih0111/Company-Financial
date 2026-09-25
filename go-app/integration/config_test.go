package integration

import (
	"strings"
	"testing"
)

func clearCanonicalEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{"CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "DATABASE_URL", "CDF_CANONICAL_DB", "CDF_PILOT_DB", envAllowNonTestPG} {
		t.Setenv(k, "")
	}
}

func TestBuildCanonicalDSNEmpty(t *testing.T) {
	clearCanonicalEnv(t)
	dsn, err := buildCanonicalDSN(true)
	if err != nil || dsn != "" {
		t.Fatalf("want empty dsn and nil error, got %q %v", dsn, err)
	}
}

func TestBuildCanonicalDSNStripsDialectAndOverridesDB(t *testing.T) {
	clearCanonicalEnv(t)
	t.Setenv("DATABASE_URL", "postgresql+psycopg://postgres:secret@localhost:5432/postgres")
	t.Setenv("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
	dsn, err := buildCanonicalDSN(true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.Contains(dsn, "+psycopg") {
		t.Fatalf("dialect prefix not stripped: %s", dsn)
	}
	if !strings.HasPrefix(dsn, "postgres://") {
		t.Fatalf("scheme not normalized: %s", dsn)
	}
	if !strings.Contains(dsn, "company_financial_analytics_shadow_v121") {
		t.Fatalf("database override not applied: %s", dsn)
	}
	if !strings.Contains(dsn, "default_transaction_read_only") {
		t.Fatalf("read-only session not requested: %s", dsn)
	}
}

func TestSafeDSNStripsCredentials(t *testing.T) {
	got := safeDSN("postgresql://postgres:secret@localhost:5432/db?options=x")
	if strings.Contains(got, "secret") {
		t.Fatalf("safeDSN leaked credentials: %s", got)
	}
}

func TestBuildCanonicalDSNRefusesNonTestDB(t *testing.T) {
	clearCanonicalEnv(t)
	t.Setenv("DATABASE_URL", "postgresql://postgres:secret@localhost:5432/production_pg")
	if _, err := buildCanonicalDSN(true); err == nil {
		t.Fatalf("must refuse a database that does not match the test/shadow prefix")
	}
}

func TestBuildCanonicalDSNAllowsOverrideFlag(t *testing.T) {
	clearCanonicalEnv(t)
	t.Setenv("DATABASE_URL", "postgresql://postgres:secret@localhost:5432/production_pg")
	t.Setenv(envAllowNonTestPG, "1")
	if _, err := buildCanonicalDSN(false); err != nil {
		t.Fatalf("explicit override should bypass the prefix guard: %v", err)
	}
}

func TestLoadConfigDefaultsToLegacy(t *testing.T) {
	clearCanonicalEnv(t)
	t.Setenv(envReadMode, "")
	t.Setenv(envScoreVersion, "")
	t.Setenv(envShadowDir, "")
	cfg := LoadConfig()
	if cfg.Mode != ModeLegacy {
		t.Fatalf("default read mode must be legacy, got %s", cfg.Mode)
	}
	if cfg.ScoreVersion != DefaultScoreVersion {
		t.Fatalf("default score version wrong: %s", cfg.ScoreVersion)
	}
	if cfg.AnyShadow() {
		t.Fatalf("default config must not enable any shadow read")
	}
}

func TestReadModeParsing(t *testing.T) {
	for raw, want := range map[string]ReadMode{
		"":          ModeLegacy,
		"legacy":    ModeLegacy,
		"SHADOW":    ModeShadow,
		" shadow ":  ModeShadow,
		"canonical": ModeCanonical,
		"bogus":     ModeLegacy,
	} {
		if got := ParseReadMode(raw); got != want {
			t.Fatalf("ParseReadMode(%q)=%s want %s", raw, got, want)
		}
	}
}
