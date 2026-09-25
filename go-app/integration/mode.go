// Package integration contains the Phase-1 shadow-read integration layer between
// the legacy SQL Server application path and the canonical PostgreSQL schema.
//
// It is strictly read-only with respect to canonical PostgreSQL and never
// changes the user-visible API response. Default mode is LEGACY.
package integration

import (
	"os"
	"strconv"
	"strings"
	"time"
)

// ReadMode is the conceptual read mode for a data dependency.
type ReadMode string

const (
	// ModeLegacy uses the existing SQL Server path only. This is the default.
	ModeLegacy ReadMode = "legacy"
	// ModeShadow runs the legacy read as authoritative and additionally runs the
	// canonical read for comparison only. The canonical result never reaches the
	// caller.
	ModeShadow ReadMode = "shadow"
	// ModeCanonical would serve the canonical result directly. It is reserved for
	// a later cutover and is not enabled as a production default in Phase 1.
	ModeCanonical ReadMode = "canonical"
)

// ParseReadMode normalizes a raw mode string. Unknown values fall back to legacy.
func ParseReadMode(raw string) ReadMode {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "shadow":
		return ModeShadow
	case "canonical":
		return ModeCanonical
	default:
		return ModeLegacy
	}
}

// Config holds the environment-driven configuration of the integration layer.
// No credentials are ever hard-coded; everything comes from the environment.
type Config struct {
	// Mode is the global read mode.
	Mode ReadMode
	// EndpointModes overrides the global mode per endpoint name.
	EndpointModes map[string]ReadMode
	// CanonicalDSN is the normalized PostgreSQL connection string. Empty when not
	// configured.
	CanonicalDSN string
	// ScoreVersion selects the canonical analytics model/score version.
	ScoreVersion string
	// ShadowTimeout bounds the canonical shadow read.
	ShadowTimeout time.Duration
	// OutputDir receives structured shadow diagnostics.
	OutputDir string
	// ReadOnly requests a read-only PostgreSQL session.
	ReadOnly bool
	// MaxCompanies caps how many distinct legacy companies a single fundamentals
	// shadow comparison will query canonically. It bounds shadow cost.
	MaxCompanies int
	// Canary is the endpoint-level price-history canary configuration.
	Canary CanaryConfig
	// EligibilityFile is the price-history identity-eligibility registry CSV.
	EligibilityFile string
}

// Env variable names. Prefixed with CDF_ to match the project's existing
// canonical-data convention (CDF_PILOT_DB, CDF_TEST_DB).
const (
	envReadMode      = "CDF_READ_MODE"
	envShadowDir     = "CDF_SHADOW_OUTPUT_DIR"
	envScoreVersion  = "CDF_CANONICAL_SCORE_VERSION"
	envShadowTimeout = "CDF_SHADOW_TIMEOUT_MS"
	envReadOnly      = "CDF_CANONICAL_READ_ONLY"
	envEndpointMode  = "CDF_READ_MODE_"
	envMaxCompanies  = "CDF_SHADOW_MAX_COMPANIES"
	envEligibility   = "CDF_PRICE_HISTORY_ELIGIBILITY_FILE"

	// DefaultEligibilityFile is relative to go-app/ when the app runs there.
	DefaultEligibilityFile = "../integration_shadow_v1/output/price_history_identity_eligibility.csv"

	// DefaultScoreVersion is the current canonical model. It is version-selected,
	// not hard-coded into repositories.
	DefaultScoreVersion = "canonical-v1-dev"
	// DefaultOutputDir is relative to the repository root when the app is run
	// from go-app/. It can always be overridden.
	DefaultOutputDir = "../integration_shadow_v1/output"
)

// LoadConfig builds a Config from the environment.
func LoadConfig() Config {
	cfg := Config{
		Mode:          ParseReadMode(os.Getenv(envReadMode)),
		EndpointModes: map[string]ReadMode{},
		ScoreVersion:  strings.TrimSpace(os.Getenv(envScoreVersion)),
		ShadowTimeout: 2 * time.Second,
		OutputDir:     strings.TrimSpace(os.Getenv(envShadowDir)),
		ReadOnly:      true,
		MaxCompanies:  25,
	}
	cfg.Canary = loadCanaryConfig()
	cfg.EligibilityFile = strings.TrimSpace(os.Getenv(envEligibility))
	if cfg.EligibilityFile == "" {
		cfg.EligibilityFile = DefaultEligibilityFile
	}
	if raw := strings.TrimSpace(os.Getenv(envMaxCompanies)); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			cfg.MaxCompanies = n
		}
	}
	if cfg.ScoreVersion == "" {
		cfg.ScoreVersion = DefaultScoreVersion
	}
	if cfg.OutputDir == "" {
		cfg.OutputDir = DefaultOutputDir
	}
	if raw := strings.TrimSpace(os.Getenv(envShadowTimeout)); raw != "" {
		if ms, err := strconv.Atoi(raw); err == nil && ms > 0 {
			cfg.ShadowTimeout = time.Duration(ms) * time.Millisecond
		}
	}
	if raw := strings.TrimSpace(os.Getenv(envReadOnly)); raw != "" {
		cfg.ReadOnly = !(raw == "0" || strings.EqualFold(raw, "false") || strings.EqualFold(raw, "no"))
	}

	// Per-endpoint overrides: CDF_READ_MODE_<ENDPOINT> where <ENDPOINT> is the
	// endpoint name uppercased with non-alphanumerics replaced by '_'.
	for _, kv := range os.Environ() {
		parts := strings.SplitN(kv, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key, val := parts[0], parts[1]
		if !strings.HasPrefix(key, envEndpointMode) {
			continue
		}
		name := strings.ToLower(strings.TrimPrefix(key, envEndpointMode))
		if name == "" {
			continue
		}
		cfg.EndpointModes[name] = ParseReadMode(val)
	}

	cfg.CanonicalDSN, _ = buildCanonicalDSN(cfg.ReadOnly)
	return cfg
}

// ModeFor returns the effective mode for an endpoint, applying per-endpoint
// overrides. An unknown endpoint uses the global mode.
func (c Config) ModeFor(endpoint string) ReadMode {
	ep := strings.TrimSpace(endpoint)
	for k, m := range c.EndpointModes {
		if strings.EqualFold(k, ep) {
			return m
		}
	}
	return c.Mode
}

// ShadowEnabled reports whether canonical shadow reads should run for an endpoint.
func (c Config) ShadowEnabled(endpoint string) bool {
	return c.CanonicalDSN != "" && c.ModeFor(endpoint) != ModeLegacy
}

// AnyShadow reports whether any endpoint (or the global default) is configured
// for non-legacy reads OR the price-history canary is enabled. When false, no
// canonical connection is opened at all.
func (c Config) AnyShadow() bool {
	if c.Canary.Enabled {
		return true
	}
	if c.Mode != ModeLegacy {
		return true
	}
	for _, m := range c.EndpointModes {
		if m != ModeLegacy {
			return true
		}
	}
	return false
}

// CanonicalEnabled reports whether canonical results are served directly. In
// Phase 1 this is only true when explicitly configured, never by default.
func (c Config) CanonicalEnabled(endpoint string) bool {
	return c.CanonicalDSN != "" && c.ModeFor(endpoint) == ModeCanonical
}
