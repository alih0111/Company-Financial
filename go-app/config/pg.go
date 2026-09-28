package config

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// Read-write PostgreSQL pool for canonical auth/portfolio persistence.
//
// This is separate from integration.OpenPG (which forces a read-only session).
// The same test/shadow/pilot prefix guard applies unless CDF_ALLOW_NON_TEST_PG=1.
//
// Backend selection:
//   CDF_AUTH_BACKEND      = postgres | sqlserver   (default: sqlserver)
//   CDF_PORTFOLIO_BACKEND = postgres | sqlserver   (default: sqlserver)
//   CDF_SQLSERVER_MODE    = active | fallback | offline_expected (default: active)

var (
	pgOnce   sync.Once
	pgDB     *sql.DB
	pgErr    error
)

var allowedPGPrefixes = []string{
	"company_financial_analytics_shadow_",
	"company_financial_migration_pilot_",
	"company_financial_test_",
}

func pgDSNReadWrite() (string, error) {
	raw := firstEnv("CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "DATABASE_URL")
	if strings.TrimSpace(raw) == "" {
		return "", fmt.Errorf("canonical DATABASE_URL not configured")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("canonical DSN parse error: %w", err)
	}
	scheme := u.Scheme
	if i := strings.Index(scheme, "+"); i >= 0 {
		scheme = scheme[:i]
	}
	if scheme != "postgres" && scheme != "postgresql" {
		return "", fmt.Errorf("canonical DSN must be postgres, got %q", u.Scheme)
	}
	dbName := strings.TrimPrefix(u.Path, "/")
	if ov := firstEnv("CDF_CANONICAL_DB", "CDF_PILOT_DB"); ov != "" {
		dbName = ov
	}
	if dbName == "" {
		return "", fmt.Errorf("canonical DSN has no database name")
	}
	if os.Getenv("CDF_ALLOW_NON_TEST_PG") != "1" && !hasAllowedPrefix(dbName) {
		return "", fmt.Errorf("refusing to write to database %q (not an allowed test/shadow prefix)", dbName)
	}
	u.Path = "/" + dbName
	u.Scheme = "postgres"
	// Writes are required here, so do NOT force default_transaction_read_only.
	return u.String(), nil
}

func hasAllowedPrefix(name string) bool {
	for _, p := range allowedPGPrefixes {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}

func firstEnv(keys ...string) string {
	for _, k := range keys {
		if v := strings.TrimSpace(os.Getenv(k)); v != "" {
			return v
		}
	}
	return ""
}

// GetPG returns a lazily-initialized read-write canonical PostgreSQL pool.
// Returns (nil, error) when not configured; callers must handle nil.
func GetPG() (*sql.DB, error) {
	pgOnce.Do(func() {
		dsn, err := pgDSNReadWrite()
		if err != nil {
			pgErr = err
			return
		}
		db, err := sql.Open("pgx", dsn)
		if err != nil {
			pgErr = err
			return
		}
		db.SetMaxOpenConns(8)
		db.SetMaxIdleConns(2)
		db.SetConnMaxLifetime(30 * time.Minute)
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := db.PingContext(ctx); err != nil {
			db.Close()
			pgErr = fmt.Errorf("ping canonical postgres: %w", err)
			return
		}
		pgDB = db
	})
	return pgDB, pgErr
}

// AuthBackend returns the configured auth backend (default sqlserver).
// When SQL Server is declared offline_expected, PostgreSQL is forced so no
// request can depend on an unreachable SQL Server.
func AuthBackend() string {
	if SQLServerMode() == "offline_expected" {
		return "postgres"
	}
	b := strings.ToLower(strings.TrimSpace(os.Getenv("CDF_AUTH_BACKEND")))
	if b == "postgres" || b == "pg" {
		return "postgres"
	}
	return "sqlserver"
}

// PortfolioBackend returns the configured portfolio backend (default sqlserver).
// Forced to postgres when SQL Server is offline_expected.
func PortfolioBackend() string {
	if SQLServerMode() == "offline_expected" {
		return "postgres"
	}
	b := strings.ToLower(strings.TrimSpace(os.Getenv("CDF_PORTFOLIO_BACKEND")))
	if b == "postgres" || b == "pg" {
		return "postgres"
	}
	return "sqlserver"
}

// FamilyBackend returns postgres | sqlserver | disabled (default sqlserver).
// An explicit CDF_FAMILY_BACKEND=postgres wins even when SQL Server is declared
// offline_expected (the canonical family namespace has no SQL Server dependency).
// In retirement mode with no explicit backend, family defaults to disabled so its
// runtime dependency is explicit instead of an opaque SQL failure.
func FamilyBackend() string {
	b := strings.ToLower(strings.TrimSpace(os.Getenv("CDF_FAMILY_BACKEND")))
	switch b {
	case "postgres", "pg":
		return "postgres"
	case "disabled":
		return "disabled"
	case "sqlserver":
		return "sqlserver"
	}
	if SQLServerMode() == "offline_expected" {
		return "disabled"
	}
	return "sqlserver"
}

// SQLServerMode returns active | fallback | offline_expected (default active).
func SQLServerMode() string {
	m := strings.ToLower(strings.TrimSpace(os.Getenv("CDF_SQLSERVER_MODE")))
	switch m {
	case "fallback", "offline_expected":
		return m
	default:
		return "active"
	}
}

// SQLServerRequired reports whether SQL Server is required for active behavior
// given the current backend/mode configuration.
func SQLServerRequired() bool {
	if SQLServerMode() == "offline_expected" {
		return false
	}
	return AuthBackend() == "sqlserver" || PortfolioBackend() == "sqlserver"
}
