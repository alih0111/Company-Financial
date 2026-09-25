package integration

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

// Allowed canonical/test database prefixes. The integration layer refuses to
// connect to any database that does not look like a test/shadow/pilot database,
// which prevents accidentally pointing shadow reads at a production PostgreSQL.
var allowedDBPrefixes = []string{
	"company_financial_analytics_shadow_",
	"company_financial_migration_pilot_",
	"company_financial_test_",
}

const envAllowNonTestPG = "CDF_ALLOW_NON_TEST_PG"

// buildCanonicalDSN resolves the canonical PostgreSQL DSN from the environment,
// normalizes the SQLAlchemy dialect prefix, applies the database override used by
// the migration tooling and enforces the test-database prefix guard.
//
// It returns ("", nil) when no URL is configured, which is a valid "shadow
// disabled" state.
func buildCanonicalDSN(readOnly bool) (string, error) {
	raw := firstNonEmpty(
		os.Getenv("CANONICAL_DATABASE_URL"),
		os.Getenv("CDF_CANONICAL_URL"),
		os.Getenv("DATABASE_URL"),
	)
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", nil
	}

	u, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("canonical DSN parse error: %w", err)
	}
	// Strip SQLAlchemy driver suffixes: postgresql+psycopg -> postgresql.
	scheme := u.Scheme
	if i := strings.Index(scheme, "+"); i >= 0 {
		scheme = scheme[:i]
	}
	if scheme != "postgres" && scheme != "postgresql" {
		return "", fmt.Errorf("canonical DSN must be a postgres URL, got scheme %q", u.Scheme)
	}

	dbName := strings.TrimPrefix(u.Path, "/")
	if override := firstNonEmpty(os.Getenv("CDF_CANONICAL_DB"), os.Getenv("CDF_PILOT_DB")); override != "" {
		dbName = override
	}
	if dbName == "" {
		return "", fmt.Errorf("canonical DSN has no database name")
	}
	if !isAllowedDB(dbName) {
		return "", fmt.Errorf("refusing to use database %q: it does not match an allowed test/shadow/pilot prefix (set %s=1 to override)", dbName, envAllowNonTestPG)
	}
	u.Path = "/" + dbName
	u.Scheme = "postgres"

	q := u.Query()
	// Force a read-only session so that no canonical write can occur even by
	// accident. pgx/libpq pass "options" through as server startup parameters.
	if readOnly {
		existing := strings.TrimSpace(q.Get("options"))
		ro := "-c default_transaction_read_only=on"
		if existing == "" {
			q.Set("options", ro)
		} else if !strings.Contains(existing, "default_transaction_read_only") {
			q.Set("options", existing+" "+ro)
		}
	}
	u.RawQuery = q.Encode()
	return u.String(), nil
}

func isAllowedDB(name string) bool {
	if v := strings.TrimSpace(os.Getenv(envAllowNonTestPG)); v == "1" || strings.EqualFold(v, "true") {
		return true
	}
	for _, p := range allowedDBPrefixes {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

// PG wraps a canonical PostgreSQL connection pool. It is intentionally small:
// connection, health and context-aware query helpers only.
type PG struct {
	db  *sql.DB
	dsn string
}

// OpenPG opens the canonical PostgreSQL pool. When no DSN is configured it
// returns (nil, nil) so callers can treat shadow reads as disabled.
func OpenPG(cfg Config) (*PG, error) {
	if cfg.CanonicalDSN == "" {
		return nil, nil
	}
	db, err := sql.Open("pgx", cfg.CanonicalDSN)
	if err != nil {
		return nil, fmt.Errorf("open canonical postgres: %w", err)
	}
	db.SetMaxOpenConns(4)
	db.SetMaxIdleConns(2)
	db.SetConnMaxLifetime(30 * time.Minute)
	db.SetConnMaxIdleTime(5 * time.Minute)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping canonical postgres: %w", err)
	}
	return &PG{db: db, dsn: cfg.CanonicalDSN}, nil
}

// DB returns the underlying pool (may be nil).
func (p *PG) DB() *sql.DB {
	if p == nil {
		return nil
	}
	return p.db
}

// Health verifies the pool is reachable.
func (p *PG) Health(ctx context.Context) error {
	if p == nil || p.db == nil {
		return fmt.Errorf("canonical postgres not configured")
	}
	return p.db.PingContext(ctx)
}

// Close releases the pool.
func (p *PG) Close() error {
	if p == nil || p.db == nil {
		return nil
	}
	return p.db.Close()
}

// safeDSN strips credentials for logging.
func safeDSN(dsn string) string {
	if dsn == "" {
		return ""
	}
	u, err := url.Parse(dsn)
	if err != nil {
		return "<unparseable>"
	}
	if u.User != nil {
		u.User = url.User(u.User.Username())
	}
	if u.RawQuery != "" {
		q := u.Query()
		q.Del("password")
		u.RawQuery = q.Encode()
	}
	return u.String()
}

var (
	defaultOnce sync.Once
	defaultInst *Shadow
)

// Default returns the process-wide shadow integration singleton. It is safe to
// call from handlers; initialization failures degrade to a disabled instance and
// never fail the request.
func Default() *Shadow {
	defaultOnce.Do(func() {
		defaultInst = newShadowFromEnv()
	})
	return defaultInst
}
