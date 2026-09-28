package integration

import (
	"context"
	"encoding/csv"
	"fmt"
	"hash/fnv"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// CanaryConfig controls the endpoint-level canonical read canary. It is
// deliberately separate from the global read mode: enabling it must never make
// CANONICAL globally active, and disabling it must restore 100% LEGACY serving.
type CanaryConfig struct {
	// Enabled is the master switch. Default false.
	Enabled bool
	// Symbols is the explicit allowlist (normalized). Preferred selection method.
	Symbols map[string]bool
	// Percent is an optional deterministic percentage (0-100) using stable
	// hashing of the request key (symbol). Default 0.
	Percent int
	// Verify additionally runs the legacy read for comparison when a canary
	// request is served from canonical. Default false.
	Verify bool
	// Timeout bounds the canonical read before falling back to legacy.
	Timeout time.Duration
}

const (
	envCanaryEnabled  = "CDF_PRICE_HISTORY_CANARY_ENABLED"
	envCanarySymbols  = "CDF_PRICE_HISTORY_CANARY_SYMBOLS"
	envCanaryPercent  = "CDF_PRICE_HISTORY_CANARY_PERCENT"
	envCanaryVerify   = "CDF_PRICE_HISTORY_CANARY_VERIFY"
	envCanaryTimeout  = "CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS"
	defaultCanaryTime = 1500 * time.Millisecond
)

func loadCanaryConfig() CanaryConfig {
	c := CanaryConfig{Symbols: map[string]bool{}, Timeout: defaultCanaryTime}
	c.Enabled = parseBoolEnv(os.Getenv(envCanaryEnabled))
	for _, s := range strings.Split(os.Getenv(envCanarySymbols), ",") {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		c.Symbols[NormalizeText(s)] = true
	}
	if raw := strings.TrimSpace(os.Getenv(envCanaryPercent)); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			if n > 100 {
				n = 100
			}
			c.Percent = n
		}
	}
	c.Verify = parseBoolEnv(os.Getenv(envCanaryVerify))
	if raw := strings.TrimSpace(os.Getenv(envCanaryTimeout)); raw != "" {
		if ms, err := strconv.Atoi(raw); err == nil && ms > 0 {
			c.Timeout = time.Duration(ms) * time.Millisecond
		}
	}
	return c
}

// Fundamentals/score canary env names. Kept separate from the price-history
// canary so enabling one never implicitly enables the other.
const (
	envFundCanaryEnabled = "CDF_FUND_CANARY_ENABLED"
	envFundCanarySymbols = "CDF_FUND_CANARY_COMPANIES"
	envFundCanaryPercent = "CDF_FUND_CANARY_PERCENT"
	envFundCanaryVerify  = "CDF_FUND_CANARY_VERIFY"
	envFundCanaryTimeout = "CDF_FUND_CANARY_TIMEOUT_MS"
)

func loadFundCanaryConfig() CanaryConfig {
	c := CanaryConfig{Symbols: map[string]bool{}, Timeout: 2 * time.Second}
	c.Enabled = parseBoolEnv(os.Getenv(envFundCanaryEnabled))
	for _, s := range strings.Split(os.Getenv(envFundCanarySymbols), ",") {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		c.Symbols[NormalizeText(s)] = true
	}
	if raw := strings.TrimSpace(os.Getenv(envFundCanaryPercent)); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			if n > 100 {
				n = 100
			}
			c.Percent = n
		}
	}
	c.Verify = parseBoolEnv(os.Getenv(envFundCanaryVerify))
	if raw := strings.TrimSpace(os.Getenv(envFundCanaryTimeout)); raw != "" {
		if ms, err := strconv.Atoi(raw); err == nil && ms > 0 {
			c.Timeout = time.Duration(ms) * time.Millisecond
		}
	}
	return c
}

func parseBoolEnv(raw string) bool {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

// Selects reports whether a symbol is deterministically routed to the canary.
// Safe default: disabled, or enabled with empty allowlist and 0% => selects
// nothing, so no request is ever served canonically by accident.
func (c CanaryConfig) Selects(symbol string) bool {
	if !c.Enabled {
		return false
	}
	key := NormalizeText(symbol)
	if key == "" {
		return false
	}
	if c.Symbols[key] {
		return true
	}
	if c.Percent > 0 && bucket(key) < c.Percent {
		return true
	}
	return false
}

// Bucket returns the deterministic 0-99 routing bucket for a symbol using the
// same normalized-key FNV-1a hashing as the percentage rollout.
func Bucket(symbol string) int { return bucket(NormalizeText(symbol)) }

// bucket deterministically maps a key to 0-99 using stable FNV-1a hashing. It
// never depends on runtime randomness or process state.
func bucket(key string) int {
	h := fnv.New32a()
	_, _ = h.Write([]byte(key))
	return int(h.Sum32() % 100)
}

// PriceRoute is the routing decision for a price-history request.
type PriceRoute int

const (
	// RouteLegacy serves SQL Server only (and runs shadow comparison only if the
	// endpoint mode is SHADOW).
	RouteLegacy PriceRoute = iota
	// RouteShadow serves SQL Server and compares canonical (SHADOW mode).
	RouteShadow
	// RouteCanary attempts canonical serving with automatic legacy fallback.
	RouteCanary
)

// PriceHistoryRoute determines how the price-history endpoint must be served.
//
// Precedence:
//   - SHADOW always means legacy-served + comparison only (never canonical).
//   - CANONICAL (explicit endpoint mode) serves canonical with fallback.
//   - otherwise, the explicit price-history canary may select a subset.
func (s *Shadow) PriceHistoryRoute(symbol string) PriceRoute {
	if s == nil {
		return RouteLegacy
	}
	// SQL Server retired: canonical only, never legacy fallback.
	if sqlserverOfflineExpected() {
		return RouteCanary
	}
	mode := s.Mode(EndpointPriceHistory)

	// SHADOW is compare-only and never changes the response. It remains routed as
	// before, except that when the eligibility guard is active an ineligible
	// symbol is not compared against canonical either (it would only produce
	// expected-to-fail noise for identities that must never be canonical-served).
	if mode == ModeShadow {
		if s.EligibilityGuardActive() && !s.IsCanonicalEligible(symbol) {
			return RouteLegacy
		}
		return RouteShadow
	}

	// Serving paths (legacy/canonical): an eligibility guard is mandatory. With
	// no loaded registry the guard default-denies canonical serving.
	safe := s.IsCanonicalEligible(symbol)

	if mode == ModeCanonical {
		if safe {
			return RouteCanary
		}
		return RouteLegacy
	}

	if s.cfg.Canary.Selects(symbol) {
		if safe {
			return RouteCanary
		}
		return RouteLegacy
	}
	return RouteLegacy
}

// SetEligibility installs an eligibility registry (used by tests and tooling).
func (s *Shadow) SetEligibility(reg *EligibilityRegistry) {
	if s == nil {
		return
	}
	s.elig = reg
}

// EligibilityGuardActive reports whether a loaded registry is enforcing the guard.
func (s *Shadow) EligibilityGuardActive() bool {
	return s != nil && s.elig != nil && s.elig.Loaded()
}

// EligibilityClass returns the classification for a symbol ("" if unknown).
func (s *Shadow) EligibilityClass(symbol string) string {
	if s == nil || s.elig == nil {
		return ""
	}
	class, _ := s.elig.Class(symbol)
	return class
}

// IsCanonicalEligible reports whether a symbol is explicitly CANONICAL_SAFE.
// Default-deny: unknown symbols and a missing guard are not eligible.
func (s *Shadow) IsCanonicalEligible(symbol string) bool {
	return s.EligibilityGuardActive() && s.elig.IsSafe(symbol)
}

// Registry exposes the loaded registry (may be nil).
func (s *Shadow) Registry() *EligibilityRegistry { return s.elig }

// CanaryEnabled reports whether the price-history canary is configured on.
func (s *Shadow) CanaryEnabled() bool {
	return s != nil && s.cfg.Canary.Enabled
}

// CanaryVerify reports whether canary-served responses are also compared.
func (s *Shadow) CanaryVerify() bool {
	return s != nil && s.cfg.Canary.Verify
}

// CanaryTimeout returns the canonical canary read timeout.
func (s *Shadow) CanaryTimeout() time.Duration {
	if s == nil {
		return defaultCanaryTime
	}
	return s.cfg.Canary.Timeout
}

// CanarySymbolCount returns the number of configured allowlisted symbols.
func (s *Shadow) CanarySymbolCount() int {
	if s == nil {
		return 0
	}
	return len(s.cfg.Canary.Symbols)
}

// FetchPriceHistoryCanonical performs the optimized canonical read under the
// canary timeout. It never falls back itself; the caller decides.
// offlineCanonicalTimeout is used when SQL Server is retired: canonical reads
// are the only source, so a transiently slow first query must not 503 the page.
const offlineCanonicalTimeout = 15 * time.Second

func (s *Shadow) FetchPriceHistoryCanonical(ctx context.Context, symbol string, limit int) ([]MarketInputRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	timeout := s.CanaryTimeout()
	if sqlserverOfflineExpected() {
		timeout = offlineCanonicalTimeout
	}
	tctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return s.src.PriceHistory(tctx, symbol, limit)
}

// --- canary diagnostics -----------------------------------------------------

// Canary counters. Names are stable for machine-readable output.
const (
	CounterCanaryTotal          = "total_requests"
	CounterLegacyServed         = "legacy_served_requests"
	CounterShadowRequests       = "shadow_requests"
	CounterCanarySelected       = "canary_selected"
	CounterCanarySuccess        = "canary_success"
	CounterCanaryFallback       = "canary_fallback"
	CounterCanonicalErrors      = "canonical_errors"
	CounterLegacyFallbackErrors = "legacy_fallback_errors"
	CounterComparisonExact      = "comparison_exact"
	CounterComparisonExpected   = "comparison_expected"
	CounterComparisonUnexpected = "comparison_unexpected"

	// Identity eligibility guard counters.
	CounterCanonicalSafe         = "canonical_safe"
	CounterCanonicalIneligible   = "canonical_ineligible"
	CounterIdentityCollision     = "legacy_identity_collision"
	CounterEligLegacyOnly        = "legacy_only"
	CounterEligCanonicalUnmapped = "canonical_unmapped"
	CounterEligNoMarketData      = "no_market_data"
	CounterEligOtherUnsafe       = "other_unsafe"
	CounterGuardForcedLegacy     = "eligibility_guard_forced_legacy"
)

// CanarySample is one bounded, secret-free diagnostic record.
type CanarySample struct {
	Symbol      string  `json:"symbol"`
	Route       string  `json:"route"`
	Result      string  `json:"result"`
	RowCount    int     `json:"row_count"`
	CanonicalMs float64 `json:"canonical_ms"`
	LegacyMs    float64 `json:"legacy_ms"`
	TotalMs     float64 `json:"total_ms"`
	Fallback    bool    `json:"fallback"`
	Error       string  `json:"error,omitempty"`
}

// SymbolAgg is the per-symbol canary aggregation.
type SymbolAgg struct {
	Requests             int
	CanonicalServed      int
	Fallbacks            int
	CanonicalErrors      int
	ComparisonExact      int
	ComparisonExpected   int
	ComparisonUnexpected int
	CanonMs              []float64
	LegacyMs             []float64
}

// CanaryStats aggregates price-history canary diagnostics.
type CanaryStats struct {
	mu         sync.Mutex
	counters   map[string]int
	samples    []CanarySample
	canonMs    []float64
	legacyMs   []float64
	fallbackMs []float64
	perSymbol  map[string]*SymbolAgg
}

func newCanaryStats() *CanaryStats {
	return &CanaryStats{counters: map[string]int{}, perSymbol: map[string]*SymbolAgg{}}
}

func (c *CanaryStats) inc(key string) {
	c.counters[key]++
}

func (c *CanaryStats) agg(symbol string) *SymbolAgg {
	a, ok := c.perSymbol[symbol]
	if !ok {
		a = &SymbolAgg{}
		c.perSymbol[symbol] = a
	}
	return a
}

// RecordRequest increments the total request counter.
func (s *Shadow) RecordCanaryRequest() {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterCanaryTotal)
}

// RecordEligibility records the eligibility decision for a request. It is a
// no-op when the guard is inactive. It never exposes internal IDs.
func (s *Shadow) RecordEligibility(symbol string) {
	if s == nil || s.canary == nil || !s.EligibilityGuardActive() {
		return
	}
	class := s.EligibilityClass(symbol)
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	if class == EligibleSafe {
		s.canary.inc(CounterCanonicalSafe)
		return
	}
	s.canary.inc(CounterCanonicalIneligible)
	switch class {
	case CollisionLegacy:
		s.canary.inc(CounterIdentityCollision)
	case LegacyOnly:
		s.canary.inc(CounterEligLegacyOnly)
	case CanonicalUnmapped:
		s.canary.inc(CounterEligCanonicalUnmapped)
	case NoMarketData:
		s.canary.inc(CounterEligNoMarketData)
	default:
		s.canary.inc(CounterEligOtherUnsafe)
	}
	// Did serving routing get forcibly downgraded to legacy?
	servingRequested := s.Mode(EndpointPriceHistory) == ModeCanonical ||
		(s.cfg.Canary.Enabled && s.cfg.Canary.Selects(symbol))
	if servingRequested {
		s.canary.inc(CounterGuardForcedLegacy)
	}
}

// RecordLegacyServed records a legacy-served request.
func (s *Shadow) RecordLegacyServed(sample CanarySample) {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterLegacyServed)
	a := s.canary.agg(sample.Symbol)
	a.Requests++
	if sample.LegacyMs > 0 {
		s.canary.legacyMs = append(s.canary.legacyMs, sample.LegacyMs)
		a.LegacyMs = append(a.LegacyMs, sample.LegacyMs)
	}
	s.canary.samples = append(s.canary.samples, sample)
}

// RecordShadowServed records a shadow comparison request.
func (s *Shadow) RecordShadowServed() {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterShadowRequests)
}

// RecordCanarySelected records that a request was routed to the canary.
func (s *Shadow) RecordCanarySelected() {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterCanarySelected)
}

// RecordCanarySuccess records a canonical-served canary request.
func (s *Shadow) RecordCanarySuccess(sample CanarySample) {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterCanarySuccess)
	a := s.canary.agg(sample.Symbol)
	a.Requests++
	a.CanonicalServed++
	if sample.CanonicalMs > 0 {
		s.canary.canonMs = append(s.canary.canonMs, sample.CanonicalMs)
		a.CanonMs = append(a.CanonMs, sample.CanonicalMs)
	}
	if sample.LegacyMs > 0 {
		a.LegacyMs = append(a.LegacyMs, sample.LegacyMs)
	}
	s.canary.samples = append(s.canary.samples, sample)
}

// RecordCanaryFallback records a canary request that fell back to legacy.
func (s *Shadow) RecordCanaryFallback(sample CanarySample) {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterCanaryFallback)
	a := s.canary.agg(sample.Symbol)
	a.Requests++
	a.Fallbacks++
	if sample.Fallback && sample.Error != "" {
		s.canary.inc(CounterCanonicalErrors)
		a.CanonicalErrors++
	}
	if sample.TotalMs > 0 {
		s.canary.fallbackMs = append(s.canary.fallbackMs, sample.TotalMs)
	}
	s.canary.samples = append(s.canary.samples, sample)
}

// RecordLegacyBaselineLatency records a legacy-only latency measurement without
// affecting request/serving counters. Used to characterize the legacy baseline
// for the same canary symbols.
func (s *Shadow) RecordLegacyBaselineLatency(ms float64) {
	if s == nil || s.canary == nil || ms <= 0 {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.legacyMs = append(s.canary.legacyMs, ms)
}

// RecordLegacyFallbackError records that fallback itself failed.
func (s *Shadow) RecordLegacyFallbackError() {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	s.canary.inc(CounterLegacyFallbackErrors)
}

// RecordCanaryComparison records comparison classifications for canary verify,
// both globally and per symbol.
func (s *Shadow) RecordCanaryComparison(symbol string, res EndpointResult) {
	if s == nil || s.canary == nil {
		return
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	exact := res.Classifications[ClassExactMatch]
	s.canary.counters[CounterComparisonExact] += exact
	s.canary.counters[CounterComparisonExpected] += res.ExpectedDiffs
	s.canary.counters[CounterComparisonUnexpected] += res.Unexpected
	a := s.canary.agg(symbol)
	a.ComparisonExact += exact
	a.ComparisonExpected += res.ExpectedDiffs
	a.ComparisonUnexpected += res.Unexpected
}

// CanaryOutcome classifies how a canary-selected request was served.
type CanaryOutcome string

const (
	// OutcomeCanonicalServed: canonical succeeded and passed validity checks.
	OutcomeCanonicalServed CanaryOutcome = "canonical_served"
	// OutcomeFallbackServed: canonical failed/empty; legacy served the request.
	OutcomeFallbackServed CanaryOutcome = "fallback_served"
	// OutcomeFallbackFailed: canonical failed and legacy also failed.
	OutcomeFallbackFailed CanaryOutcome = "fallback_failed"
)

// CanaryResult is the deterministic outcome of a canary-selected request.
type CanaryResult struct {
	Rows         []MarketInputRow
	Outcome      CanaryOutcome
	CanonicalErr error
	LegacyErr    error
	CanonicalMs  float64
	LegacyMs     float64
}

// ResolvePriceHistory applies the canary serving policy to injected fetch
// functions. It is pure orchestration (no DB coupling) so it can be tested
// deterministically. canonicalFetch is expected to already apply the canary
// timeout. Validity: canonical must succeed and be non-empty; otherwise the
// legacy fetch is used. If legacy also fails, the request fails.
func (s *Shadow) ResolvePriceHistory(
	ctx context.Context,
	canonicalFetch func(context.Context) ([]MarketInputRow, error),
	legacyFetch func() ([]MarketInputRow, error),
) CanaryResult {
	res := CanaryResult{}

	canonStart := time.Now()
	canon, cErr := canonicalFetch(ctx)
	res.CanonicalMs = float64(time.Since(canonStart).Microseconds()) / 1000.0
	res.CanonicalErr = cErr

	if cErr == nil && len(canon) > 0 {
		res.Rows = canon
		res.Outcome = OutcomeCanonicalServed
		return res
	}
	if cErr == nil {
		res.CanonicalErr = fmt.Errorf("canonical result empty")
	}

	legacyStart := time.Now()
	legacy, lErr := legacyFetch()
	res.LegacyMs = float64(time.Since(legacyStart).Microseconds()) / 1000.0
	res.LegacyErr = lErr
	if lErr != nil {
		res.Outcome = OutcomeFallbackFailed
		return res
	}
	res.Rows = legacy
	res.Outcome = OutcomeFallbackServed
	return res
}

// startCanaryFlusher periodically persists canary diagnostics so a running
// canary deployment has live observability without flushing on every request.
func (s *Shadow) startCanaryFlusher() {
	if s == nil || !s.cfg.Canary.Enabled {
		return
	}
	go func() {
		t := time.NewTicker(5 * time.Second)
		defer t.Stop()
		for range t.C {
			if err := s.FlushCanary(); err != nil {
				log.Printf("[canary] failed to flush diagnostics: %v", err)
			}
		}
	}()
}

type canarySummary struct {
	GeneratedAt  string                     `json:"generated_at"`
	Enabled      bool                       `json:"enabled"`
	SymbolCount  int                        `json:"symbol_count"`
	Symbols      []string                   `json:"symbols"`
	Percent      int                        `json:"percent"`
	Verify       bool                       `json:"verify"`
	TimeoutMs    int                        `json:"timeout_ms"`
	Counters     map[string]int             `json:"counters"`
	Latency      canaryLatencyStat          `json:"latency"`
	PerSymbol    map[string]symbolSummary   `json:"per_symbol"`
	SampleCount  int                        `json:"sample_count"`
	Unexpected   int                        `json:"unexpected_differences"`
	CanonicalErr int                        `json:"canonical_errors"`
}

type symbolSummary struct {
	Requests             int     `json:"requests"`
	CanonicalServed      int     `json:"canonical_served"`
	Fallbacks            int     `json:"fallbacks"`
	CanonicalErrors      int     `json:"canonical_errors"`
	ComparisonExact      int     `json:"comparison_exact"`
	ComparisonExpected   int     `json:"comparison_expected"`
	ComparisonUnexpected int     `json:"comparison_unexpected"`
	CanonicalMedianMs    float64 `json:"canonical_median_ms"`
	CanonicalP95Ms       float64 `json:"canonical_p95_ms"`
	LegacyMedianMs       float64 `json:"legacy_median_ms"`
	LegacyP95Ms          float64 `json:"legacy_p95_ms"`
}

type canaryLatencyStat struct {
	CanonicalMedianMs float64 `json:"canonical_median_ms"`
	CanonicalP95Ms    float64 `json:"canonical_p95_ms"`
	LegacyMedianMs    float64 `json:"legacy_median_ms"`
	LegacyP95Ms       float64 `json:"legacy_p95_ms"`
	FallbackMedianMs  float64 `json:"fallback_median_ms"`
	FallbackP95Ms     float64 `json:"fallback_p95_ms"`
}

// FlushCanary writes price_history_canary_summary.json and
// price_history_canary_samples.csv. It is deterministic and contains no secrets.
func (s *Shadow) FlushCanary() error {
	if s == nil || s.canary == nil || s.cfg.OutputDir == "" {
		return nil
	}
	s.canary.mu.Lock()
	defer s.canary.mu.Unlock()
	if err := os.MkdirAll(s.cfg.OutputDir, 0o755); err != nil {
		return err
	}
	symbols := make([]string, 0, len(s.cfg.Canary.Symbols))
	for k := range s.cfg.Canary.Symbols {
		symbols = append(symbols, k)
	}
	sortStrings(symbols)
	perSymbol := make(map[string]symbolSummary, len(s.canary.perSymbol))
	for sym, a := range s.canary.perSymbol {
		perSymbol[sym] = symbolSummary{
			Requests:             a.Requests,
			CanonicalServed:      a.CanonicalServed,
			Fallbacks:            a.Fallbacks,
			CanonicalErrors:      a.CanonicalErrors,
			ComparisonExact:      a.ComparisonExact,
			ComparisonExpected:   a.ComparisonExpected,
			ComparisonUnexpected: a.ComparisonUnexpected,
			CanonicalMedianMs:    median(a.CanonMs),
			CanonicalP95Ms:       percentile(a.CanonMs, 0.95),
			LegacyMedianMs:       median(a.LegacyMs),
			LegacyP95Ms:          percentile(a.LegacyMs, 0.95),
		}
	}

	summary := canarySummary{
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
		Enabled:     s.cfg.Canary.Enabled,
		SymbolCount: len(s.cfg.Canary.Symbols),
		Symbols:     symbols,
		Percent:     s.cfg.Canary.Percent,
		Verify:      s.cfg.Canary.Verify,
		TimeoutMs:   int(s.cfg.Canary.Timeout / time.Millisecond),
		Counters:    copyCounters(s.canary.counters),
		PerSymbol:   perSymbol,
		Latency: canaryLatencyStat{
			CanonicalMedianMs: median(s.canary.canonMs),
			CanonicalP95Ms:    percentile(s.canary.canonMs, 0.95),
			LegacyMedianMs:    median(s.canary.legacyMs),
			LegacyP95Ms:       percentile(s.canary.legacyMs, 0.95),
			FallbackMedianMs:  median(s.canary.fallbackMs),
			FallbackP95Ms:     percentile(s.canary.fallbackMs, 0.95),
		},
		SampleCount:  len(s.canary.samples),
		Unexpected:   s.canary.counters[CounterComparisonUnexpected],
		CanonicalErr: s.canary.counters[CounterCanonicalErrors],
	}
	if err := writeJSON(filepath.Join(s.cfg.OutputDir, "price_history_canary_summary.json"), summary); err != nil {
		return err
	}
	return writeCanarySamples(filepath.Join(s.cfg.OutputDir, "price_history_canary_samples.csv"), s.canary.samples)
}

func copyCounters(in map[string]int) map[string]int {
	out := make(map[string]int, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

func writeCanarySamples(path string, samples []CanarySample) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"symbol", "route", "result", "row_count", "canonical_ms", "legacy_ms", "total_ms", "fallback", "error"})
	for _, s := range samples {
		_ = w.Write([]string{
			asciiSafe(s.Symbol), s.Route, s.Result,
			strconv.Itoa(s.RowCount),
			fmt.Sprintf("%.3f", s.CanonicalMs),
			fmt.Sprintf("%.3f", s.LegacyMs),
			fmt.Sprintf("%.3f", s.TotalMs),
			strconv.FormatBool(s.Fallback),
			asciiSafe(s.Error),
		})
	}
	return w.Error()
}

func median(v []float64) float64 {
	if len(v) == 0 {
		return 0
	}
	return percentile(v, 0.5)
}

func percentile(v []float64, p float64) float64 {
	if len(v) == 0 {
		return 0
	}
	cp := append([]float64(nil), v...)
	sortFloat64(cp)
	if p <= 0 {
		return cp[0]
	}
	if p >= 1 {
		return cp[len(cp)-1]
	}
	idx := int(p * float64(len(cp)-1))
	return cp[idx]
}

func sortStrings(v []string) {
	for i := 1; i < len(v); i++ {
		for j := i; j > 0 && v[j-1] > v[j]; j-- {
			v[j-1], v[j] = v[j], v[j-1]
		}
	}
}

func sortFloat64(v []float64) {
	for i := 1; i < len(v); i++ {
		for j := i; j > 0 && v[j-1] > v[j]; j-- {
			v[j-1], v[j] = v[j], v[j-1]
		}
	}
}
