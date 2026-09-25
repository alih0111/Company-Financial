package integration

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func canaryCfg(enabled bool, symbols ...string) CanaryConfig {
	c := CanaryConfig{Enabled: enabled, Symbols: map[string]bool{}, Timeout: 200 * time.Millisecond}
	for _, s := range symbols {
		c.Symbols[NormalizeText(s)] = true
	}
	return c
}

func TestCanaryDefaultsOff(t *testing.T) {
	clearCanonicalEnv(t)
	for _, k := range []string{envCanaryEnabled, envCanarySymbols, envCanaryPercent, envCanaryVerify, envCanaryTimeout} {
		t.Setenv(k, "")
	}
	cfg := LoadConfig()
	if cfg.Canary.Enabled {
		t.Fatalf("canary must default to disabled")
	}
	if cfg.Canary.Selects("فولاد") {
		t.Fatalf("disabled canary must never select")
	}
	sh := newShadowForTest(cfg, &fakeSource{})
	if sh.PriceHistoryRoute("فولاد") != RouteLegacy {
		t.Fatalf("default route must be legacy")
	}
}

func TestCanaryDisabledNeverSelectsEvenWithAllowlist(t *testing.T) {
	c := canaryCfg(false, "فولاد")
	if c.Selects("فولاد") {
		t.Fatalf("disabled canary must not select even allowlisted symbols")
	}
}

func TestCanaryAllowlistDeterministic(t *testing.T) {
	c := canaryCfg(true, "فولاد", "خودرو")
	for i := 0; i < 5; i++ {
		if !c.Selects("فولاد") || !c.Selects("خودرو") {
			t.Fatalf("allowlisted symbols must always be selected")
		}
		if c.Selects("شپنا") {
			t.Fatalf("non-allowlisted symbol must never be selected")
		}
	}
}

func TestCanaryPercentDeterministic(t *testing.T) {
	none := CanaryConfig{Enabled: true, Symbols: map[string]bool{}, Percent: 0}
	if none.Selects("فولاد") {
		t.Fatalf("0%% must select nothing")
	}
	all := CanaryConfig{Enabled: true, Symbols: map[string]bool{}, Percent: 100}
	if !all.Selects("فولاد") {
		t.Fatalf("100%% must select everything")
	}
	part := CanaryConfig{Enabled: true, Symbols: map[string]bool{}, Percent: 37}
	first := part.Selects("فولاد")
	for i := 0; i < 10; i++ {
		if part.Selects("فولاد") != first {
			t.Fatalf("percentage selection must be deterministic for a key")
		}
	}
}

func safeRegistry(symbols ...string) *EligibilityRegistry {
	reg := NewEligibilityRegistry()
	for _, s := range symbols {
		reg.Add(EligibilityEntry{Symbol: s, Classification: EligibleSafe})
	}
	return reg
}

func TestPriceHistoryRouteMatrix(t *testing.T) {
	cases := []struct {
		mode     ReadMode
		canary   CanaryConfig
		registry *EligibilityRegistry
		want     PriceRoute
		note     string
	}{
		{ModeLegacy, canaryCfg(false), safeRegistry("فولاد"), RouteLegacy, "legacy default"},
		{ModeLegacy, canaryCfg(true, "فولاد"), safeRegistry("فولاد"), RouteCanary, "allowlisted safe canary in legacy mode"},
		{ModeLegacy, canaryCfg(true, "فولاد"), nil, RouteLegacy, "no registry default-denies serving"},
		{ModeLegacy, canaryCfg(true, "خودرو"), safeRegistry("فولاد"), RouteLegacy, "non-allowlisted stays legacy"},
		{ModeShadow, canaryCfg(true, "فولاد"), safeRegistry("فولاد"), RouteShadow, "shadow never serves canonical"},
		{ModeShadow, canaryCfg(true, "فولاد"), safeRegistry("فولاد"), RouteShadow, "shadow unchanged for safe"},
		{ModeCanonical, canaryCfg(false), safeRegistry("فولاد"), RouteCanary, "explicit canonical mode with safe registry"},
		{ModeCanonical, canaryCfg(false), nil, RouteLegacy, "explicit canonical mode denied without registry"},
	}
	for _, tc := range cases {
		cfg := testCfg(tc.mode)
		cfg.Canary = tc.canary
		sh := newShadowForTest(cfg, &fakeSource{})
		sh.SetEligibility(tc.registry)
		if got := sh.PriceHistoryRoute("فولاد"); got != tc.want {
			t.Fatalf("%s: got %v want %v", tc.note, got, tc.want)
		}
	}
}

func TestResolveCanonicalServed(t *testing.T) {
	sh := newShadowForTest(testCfg(ModeLegacy), &fakeSource{})
	canon := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 1}}
	res := sh.ResolvePriceHistory(context.Background(),
		func(context.Context) ([]MarketInputRow, error) { return canon, nil },
		func() ([]MarketInputRow, error) { return nil, errors.New("legacy must not be called") },
	)
	if res.Outcome != OutcomeCanonicalServed || len(res.Rows) != 1 {
		t.Fatalf("expected canonical served, got %+v", res)
	}
}

func TestResolveFallbackOnCanonicalError(t *testing.T) {
	sh := newShadowForTest(testCfg(ModeLegacy), &fakeSource{})
	legacy := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 2}}
	res := sh.ResolvePriceHistory(context.Background(),
		func(context.Context) ([]MarketInputRow, error) { return nil, errors.New("pg down") },
		func() ([]MarketInputRow, error) { return legacy, nil },
	)
	if res.Outcome != OutcomeFallbackServed || len(res.Rows) != 1 {
		t.Fatalf("expected fallback served, got %+v", res)
	}
	if res.CanonicalErr == nil {
		t.Fatalf("canonical error must be recorded, not swallowed")
	}
}

func TestResolveFallbackOnEmptyCanonical(t *testing.T) {
	sh := newShadowForTest(testCfg(ModeLegacy), &fakeSource{})
	legacy := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 2}}
	res := sh.ResolvePriceHistory(context.Background(),
		func(context.Context) ([]MarketInputRow, error) { return nil, nil },
		func() ([]MarketInputRow, error) { return legacy, nil },
	)
	if res.Outcome != OutcomeFallbackServed {
		t.Fatalf("empty canonical must fall back, got %+v", res)
	}
	if res.CanonicalErr == nil {
		t.Fatalf("empty canonical must be recorded as a canonical issue")
	}
}

func TestResolveFallbackFailed(t *testing.T) {
	sh := newShadowForTest(testCfg(ModeLegacy), &fakeSource{})
	res := sh.ResolvePriceHistory(context.Background(),
		func(context.Context) ([]MarketInputRow, error) { return nil, errors.New("pg down") },
		func() ([]MarketInputRow, error) { return nil, errors.New("sqlserver down") },
	)
	if res.Outcome != OutcomeFallbackFailed {
		t.Fatalf("expected fallback failed, got %+v", res)
	}
	if res.CanonicalErr == nil || res.LegacyErr == nil {
		t.Fatalf("both errors must be surfaced for diagnostics")
	}
}

func TestResolveCanonicalTimeoutFallsBack(t *testing.T) {
	fake := &fakeSource{prices: []MarketInputRow{{Date: "2026-09-24"}}, priceDelay: 100 * time.Millisecond}
	cfg := testCfg(ModeLegacy)
	cfg.Canary = CanaryConfig{Enabled: true, Symbols: map[string]bool{"فولاد": true}, Timeout: 10 * time.Millisecond}
	sh := newShadowForTest(cfg, fake)
	legacy := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 2}}
	res := sh.ResolvePriceHistory(context.Background(),
		func(ctx context.Context) ([]MarketInputRow, error) {
			return sh.FetchPriceHistoryCanonical(ctx, "فولاد", 30)
		},
		func() ([]MarketInputRow, error) { return legacy, nil },
	)
	if res.Outcome != OutcomeFallbackServed {
		t.Fatalf("timeout must fall back, got %+v", res)
	}
	if res.CanonicalErr == nil {
		t.Fatalf("timeout must be recorded")
	}
}

func TestCanaryKillSwitch(t *testing.T) {
	on := testCfg(ModeLegacy)
	on.Canary = canaryCfg(true, "فولاد")
	shOn := newShadowForTest(on, &fakeSource{})
	shOn.SetEligibility(safeRegistry("فولاد"))
	if shOn.PriceHistoryRoute("فولاد") != RouteCanary {
		t.Fatalf("canary should be on")
	}
	off := testCfg(ModeLegacy)
	off.Canary = canaryCfg(false, "فولاد")
	shOff := newShadowForTest(off, &fakeSource{})
	shOff.SetEligibility(safeRegistry("فولاد"))
	if shOff.PriceHistoryRoute("فولاد") != RouteLegacy {
		t.Fatalf("kill switch must restore legacy serving")
	}
}

func TestCanaryVerifyWorksInLegacyMode(t *testing.T) {
	fake := &fakeSource{prices: []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 10}}}
	cfg := testCfg(ModeLegacy)
	cfg.Canary = CanaryConfig{Enabled: true, Symbols: map[string]bool{"فولاد": true}, Verify: true, Timeout: time.Second}
	sh := newShadowForTest(cfg, fake)
	legacy := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 10}}
	res := sh.VerifyCanaryPriceHistory(context.Background(), "فولاد", 30, legacy, time.Millisecond)
	if res.Classifications[ClassExactMatch] == 0 {
		t.Fatalf("verify must compare even in legacy mode, got %v", res.Classifications)
	}
}

func TestCanaryDiagnosticsFlush(t *testing.T) {
	dir := t.TempDir()
	cfg := testCfg(ModeLegacy)
	cfg.OutputDir = dir
	cfg.Canary = canaryCfg(true, "فولاد")
	sh := newShadowForTest(cfg, &fakeSource{})
	sh.RecordCanaryRequest()
	sh.RecordCanarySelected()
	sh.RecordCanarySuccess(CanarySample{Symbol: "فولاد", Route: "canonical", Result: "served", RowCount: 30, CanonicalMs: 5})
	sh.RecordCanaryFallback(CanarySample{Symbol: "x", Route: "fallback", Result: "legacy", Fallback: true, Error: "pg down"})
	sh.RecordCanaryComparison("?????", EndpointResult{Classifications: map[string]int{ClassExactMatch: 7}, ExpectedDiffs: 1, Unexpected: 0})

	if err := sh.FlushCanary(); err != nil {
		t.Fatalf("flush: %v", err)
	}
	for _, name := range []string{"price_history_canary_summary.json", "price_history_canary_samples.csv"} {
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			t.Fatalf("expected %s: %v", name, err)
		}
	}
	data, _ := os.ReadFile(filepath.Join(dir, "price_history_canary_summary.json"))
	if len(data) == 0 {
		t.Fatalf("summary empty")
	}
}

func TestCanaryDoesNotAffectOtherEndpoints(t *testing.T) {
	cfg := testCfg(ModeLegacy)
	cfg.Canary = canaryCfg(true, "فولاد")
	sh := newShadowForTest(cfg, &fakeSource{})
	// Only price-history is affected; other endpoints resolve by global mode.
	for _, ep := range []string{EndpointCompanyNames, EndpointScores, EndpointSalesData, EndpointSalesData2} {
		if sh.Mode(ep) != ModeLegacy {
			t.Fatalf("endpoint %s should remain legacy", ep)
		}
	}
}
