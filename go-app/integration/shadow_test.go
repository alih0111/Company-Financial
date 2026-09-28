package integration

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

type fakeSource struct {
	names          []string
	prices         []MarketInputRow
	scores         []ScoreInputRow
	monthly        []MonthlyInputRow
	financial      []FinancialInputRow
	err            error
	nameCalls      int
	scoreCalls     int
	priceCalls     int
	monthlyCalls   int
	financialCalls int
	lastVersion    string
	priceDelay     time.Duration
	allScores      []AllScoreInputRow
	bundle         CompanyScoreBundle
	allScoreCalls  int
	bundleCalls    int
	legacyID       string
}

func (f *fakeSource) CompanyNames(context.Context) ([]string, error) {
	f.nameCalls++
	return f.names, f.err
}

func (f *fakeSource) ResolveLegacyCompanyIDByName(context.Context, string) (string, error) {
	return f.legacyID, f.err
}

func (f *fakeSource) PriceHistory(ctx context.Context, _ string, _ int) ([]MarketInputRow, error) {
	f.priceCalls++
	if f.priceDelay > 0 {
		select {
		case <-time.After(f.priceDelay):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return f.prices, f.err
}

func (f *fakeSource) SelectScoreRun(context.Context, string) (ScoreVersionInfo, error) {
	return ScoreVersionInfo{}, f.err
}

func (f *fakeSource) ScoresByLegacyIDs(_ context.Context, version string, _ []string) ([]ScoreInputRow, error) {
	f.scoreCalls++
	f.lastVersion = version
	return f.scores, f.err
}

func (f *fakeSource) MonthlyActivitiesByLegacyCompanyID(context.Context, string, int) ([]MonthlyInputRow, error) {
	f.monthlyCalls++
	return f.monthly, f.err
}

func (f *fakeSource) FinancialMetricsByLegacyCompanyID(context.Context, string, int) ([]FinancialInputRow, error) {
	f.financialCalls++
	return f.financial, f.err
}

func (f *fakeSource) NetProfitSeriesByLegacyCompanyID(context.Context, string) ([]NetProfitPeriodRow, error) {
	return nil, f.err
}

func (f *fakeSource) MonthlyActivitiesByLegacyIDs(context.Context, []string, int) ([]MonthlyInputRow, error) {
	f.monthlyCalls++
	return f.monthly, f.err
}

func (f *fakeSource) FinancialMetricsByLegacyIDs(context.Context, []string, int) ([]FinancialInputRow, error) {
	f.financialCalls++
	return f.financial, f.err
}

func (f *fakeSource) FactorScoresByLegacyIDs(context.Context, string, []string) ([]FactorScoreInputRow, error) {
	return nil, f.err
}

func (f *fakeSource) MetricSnapshotsByLegacyIDs(context.Context, string, []string) ([]MetricSnapshotInputRow, error) {
	return nil, f.err
}

func (f *fakeSource) AllScoresCanonical(_ context.Context, _ string) ([]AllScoreInputRow, error) {
	f.allScoreCalls++
	return f.allScores, f.err
}

func (f *fakeSource) CompanyScoreByLegacyID(_ context.Context, _ string, legacyID string) (CompanyScoreBundle, error) {
	f.bundleCalls++
	b := f.bundle
	b.LegacyCompanyID = legacyID
	return b, f.err
}

func (f *fakeSource) Health(context.Context) error { return f.err }

func testCfg(mode ReadMode) Config {
	return Config{
		Mode:          mode,
		EndpointModes: map[string]ReadMode{},
		ScoreVersion:  DefaultScoreVersion,
		ShadowTimeout: time.Second,
		OutputDir:     "", // no artifacts during unit tests
	}
}

func TestLegacyModeUsesOnlyLegacyResult(t *testing.T) {
	fake := &fakeSource{err: errors.New("canonical should not be called")}
	sh := newShadowForTest(testCfg(ModeLegacy), fake)
	legacy := []ScoreInputRow{{LegacyCompanyID: "abc", QuantScore: 10}}
	res := sh.CompareScores(context.Background(), legacy, 5*time.Millisecond)
	if fake.scoreCalls != 0 {
		t.Fatalf("legacy mode must not query canonical, got %d calls", fake.scoreCalls)
	}
	if res.Endpoint != EndpointScores {
		t.Fatalf("endpoint not set: %q", res.Endpoint)
	}
	if res.Errors != 0 || res.Unexpected != 0 {
		t.Fatalf("legacy mode should be a no-op comparison")
	}
}

func TestShadowReturnsLegacyAndClassifies(t *testing.T) {
	fake := &fakeSource{scores: []ScoreInputRow{
		{LegacyCompanyID: "abc", Symbol: "فولاد", CompanyName: "فولاد", QuantScore: 50, GrowthScore: 5, ScoreVersion: DefaultScoreVersion},
	}}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []ScoreInputRow{{LegacyCompanyID: "abc", Symbol: "فولاد", CompanyName: "فولاد", QuantScore: 42, GrowthScore: 5}}
	before := append([]ScoreInputRow(nil), legacy...)
	res := sh.CompareScores(context.Background(), legacy, time.Millisecond)
	if !reflect.DeepEqual(before, legacy) {
		t.Fatalf("shadow comparison must not mutate the legacy result: %+v", legacy)
	}
	if res.Matched != 1 {
		t.Fatalf("want 1 match, got %d", res.Matched)
	}
	if res.Classifications[ClassExpectedSemantic] < 1 {
		t.Fatalf("score delta should be an expected semantic change: %v", res.Classifications)
	}
	if res.Unexpected != 0 {
		t.Fatalf("no unexpected diffs expected, got %d (%v)", res.Unexpected, res.Classifications)
	}
}

func TestShadowCanonicalFailureDoesNotMutateLegacy(t *testing.T) {
	fake := &fakeSource{err: errors.New("pg down")}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []ScoreInputRow{{LegacyCompanyID: "abc", QuantScore: 42}}
	before := append([]ScoreInputRow(nil), legacy...)
	res := sh.CompareScores(context.Background(), legacy, time.Millisecond)
	if !reflect.DeepEqual(before, legacy) {
		t.Fatalf("legacy result changed on canonical failure")
	}
	if res.Errors != 1 {
		t.Fatalf("want 1 error recorded, got %d", res.Errors)
	}
	if res.Classifications[ClassQueryError] != 1 {
		t.Fatalf("want QUERY_ERROR classification, got %v", res.Classifications)
	}
	if res.IsHealthy() {
		t.Fatalf("result with query error should not be healthy")
	}
}

func TestShadowPriceHistoryFailureIsolated(t *testing.T) {
	fake := &fakeSource{err: errors.New("timeout")}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []MarketInputRow{{Date: "2026-09-24", ClosingPrice: 100}}
	before := append([]MarketInputRow(nil), legacy...)
	res := sh.ComparePriceHistory(context.Background(), "فولاد", 30, legacy, time.Millisecond)
	if !reflect.DeepEqual(before, legacy) {
		t.Fatalf("legacy price rows changed on canonical failure")
	}
	if res.Errors != 1 || res.Classifications[ClassQueryError] != 1 {
		t.Fatalf("canonical failure not isolated: %+v", res)
	}
}

func TestShadowScoreVersionDeterministic(t *testing.T) {
	fake := &fakeSource{}
	cfg := testCfg(ModeShadow)
	cfg.ScoreVersion = "canonical-v2-experiment"
	sh := newShadowForTest(cfg, fake)
	sh.CompareScores(context.Background(), []ScoreInputRow{{LegacyCompanyID: "abc"}}, time.Millisecond)
	if fake.lastVersion != "canonical-v2-experiment" {
		t.Fatalf("score version not passed through: %q", fake.lastVersion)
	}
}

func TestCanonicalModeDoesNotServeCanonical(t *testing.T) {
	// In Phase 1 there is deliberately no code path that replaces the response
	// with canonical data. CANONICAL mode only affects comparison behavior.
	fake := &fakeSource{scores: []ScoreInputRow{{LegacyCompanyID: "abc", QuantScore: 99}}}
	cfg := testCfg(ModeCanonical)
	sh := newShadowForTest(cfg, fake)
	if sh.Mode(EndpointScores) != ModeCanonical {
		t.Fatalf("mode not reported as canonical")
	}
	res := sh.CompareScores(context.Background(), []ScoreInputRow{{LegacyCompanyID: "abc", QuantScore: 1}}, time.Millisecond)
	if res.Matched != 1 {
		t.Fatalf("canonical mode should still compare, got %+v", res)
	}
	// There is no API returning canonical rows for serving; this is by design.
}

func TestLegacyModeSalesData2NoCanonical(t *testing.T) {
	fake := &fakeSource{err: errors.New("must not be called")}
	sh := newShadowForTest(testCfg(ModeLegacy), fake)
	res := sh.CompareSalesData2(context.Background(),
		[]MonthlyInputRow{{LegacyCompanyID: "a", ReportDate: "1405/06/31", ReportedSalesAmount: 10}}, 0)
	if fake.monthlyCalls != 0 {
		t.Fatalf("legacy mode must not call canonical, got %d", fake.monthlyCalls)
	}
	if res.Unexpected != 0 || res.Errors != 0 {
		t.Fatalf("legacy mode should be a no-op")
	}
}

func TestShadowSalesData2UnitAndQuantity(t *testing.T) {
	fake := &fakeSource{monthly: []MonthlyInputRow{{
		LegacyCompanyID: "a", ReportDate: "1405/06/31",
		ProductionQuantity: 100, SalesQuantity: 90,
		ReportedSalesAmount: 5_000_000, SalesAmountRial: 5_000_000_000_000,
	}}}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []MonthlyInputRow{{
		LegacyCompanyID: "a", ReportDate: "1405/06/31",
		ProductionQuantity: 100, SalesQuantity: 90,
		ReportedSalesAmount: 5_000_000, SalesAmountRial: 5_000_000, // million stored
	}}
	before := append([]MonthlyInputRow(nil), legacy...)
	res := sh.CompareSalesData2(context.Background(), legacy, time.Millisecond)
	if !reflect.DeepEqual(before, legacy) {
		t.Fatalf("legacy rows mutated")
	}
	if res.Classifications[ClassExactMatch] < 4 {
		t.Fatalf("want quantities/reported exact matches, got %v", res.Classifications)
	}
	if res.Classifications[ClassExpectedUnit] != 1 {
		t.Fatalf("want 1 expected unit presentation for sales_amount_rial, got %v", res.Classifications)
	}
	if res.Unexpected != 0 {
		t.Fatalf("no unexpected diffs expected, got %d (%v)", res.Unexpected, res.Classifications)
	}
}

func TestShadowSalesData2CanonicalOnlyAllowed(t *testing.T) {
	fake := &fakeSource{monthly: []MonthlyInputRow{
		{LegacyCompanyID: "a", ReportDate: "1405/06/31"},
		{LegacyCompanyID: "a", ReportDate: "1405/05/31"}, // canonical has an extra period
	}}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []MonthlyInputRow{{LegacyCompanyID: "a", ReportDate: "1405/06/31"}}
	res := sh.CompareSalesData2(context.Background(), legacy, time.Millisecond)
	if res.Classifications[ClassCanonicalOnly] != 1 {
		t.Fatalf("want 1 canonical-only, got %v", res.Classifications)
	}
	if res.Unexpected != 0 {
		t.Fatalf("canonical-only must be allowed, got unexpected=%d", res.Unexpected)
	}
}

func TestShadowSalesDataMetricsExact(t *testing.T) {
	fake := &fakeSource{financial: []FinancialInputRow{{
		LegacyCompanyID: "a", ReportDate: "1405/05/31",
		EPS: 255, Revenue: 27083916, OperatingProfit: 25017081, NetProfit: 17208319, Capital: 67500000,
	}}}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []FinancialInputRow{{
		LegacyCompanyID: "a", ReportDate: "1405/05/31",
		EPS: 255, Revenue: 27083916, OperatingProfit: 25017081, NetProfit: 17208319, Capital: 67500000,
	}}
	res := sh.CompareSalesData(context.Background(), legacy, time.Millisecond)
	if res.Unexpected != 0 || res.Errors != 0 {
		t.Fatalf("expected clean financial comparison, got %+v", res)
	}
	if res.Classifications[ClassExactMatch] != 6 {
		t.Fatalf("want 6 exact matches (report_date+5 metrics), got %v", res.Classifications)
	}
}

func TestShadowSalesDataCanonicalFailureIsolated(t *testing.T) {
	fake := &fakeSource{err: errors.New("pg down")}
	sh := newShadowForTest(testCfg(ModeShadow), fake)
	legacy := []FinancialInputRow{{LegacyCompanyID: "a", ReportDate: "1405/05/31", Revenue: 1}}
	before := append([]FinancialInputRow(nil), legacy...)
	res := sh.CompareSalesData(context.Background(), legacy, time.Millisecond)
	if !reflect.DeepEqual(before, legacy) {
		t.Fatalf("legacy mutated on canonical failure")
	}
	if res.Errors != 1 || res.Classifications[ClassQueryError] != 1 {
		t.Fatalf("failure not isolated: %+v", res)
	}
}

func TestMonthlyDateIdentityAndNullComparison(t *testing.T) {
	spec := CompareSpec{KeyField: "row_key", Fields: []FieldSpec{
		{Name: "report_date", Kind: KindText, Identity: true},
		{Name: "production_quantity", Kind: KindNumber},
	}}
	legacy := []Record{{"row_key": TextValue("a|1405/06/31"), "report_date": TextValue("1405/06/31"), "production_quantity": NullValue()}}
	canon := []Record{{"row_key": TextValue("a|1405/06/31"), "report_date": TextValue("1405/06/30"), "production_quantity": NumValue(0)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassNameIdentityMismatch] != 1 {
		t.Fatalf("want date identity mismatch, got %v", res.Classifications)
	}
	if res.Classifications[ClassNameNullSemantics] != 1 {
		t.Fatalf("want null semantics difference, got %v", res.Classifications)
	}
}

func TestEndpointOverride(t *testing.T) {
	cfg := testCfg(ModeLegacy)
	cfg.EndpointModes[EndpointPriceHistory] = ModeShadow
	if cfg.ModeFor(EndpointPriceHistory) != ModeShadow {
		t.Fatalf("endpoint override not applied")
	}
	if cfg.ModeFor(EndpointCompanyNames) != ModeLegacy {
		t.Fatalf("non-overridden endpoint must stay legacy")
	}
	if !cfg.AnyShadow() {
		t.Fatalf("AnyShadow must be true with an endpoint override")
	}
}
