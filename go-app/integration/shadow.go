package integration

import (
	"context"
	"log"
	"sync"
	"time"
)

// Endpoint identifiers used across handlers and diagnostics.
const (
	EndpointCompanyNames = "GET /api/CompanyNames"
	EndpointPriceHistory = "GET /api/price-history"
	EndpointScores       = "GET /api/summary"
	EndpointSalesData    = "GET /api/SalesData"
	EndpointSalesData2   = "GET /api/SalesData2"
)

// Shadow is the central shadow-read orchestrator. Handlers call it with the
// legacy result they already computed; it never mutates or replaces that result.
type Shadow struct {
	cfg       Config
	src       canonicalSource
	collector *Collector
	canary    *CanaryStats
	elig      *EligibilityRegistry

	mu     sync.Mutex
	status Status
}

// Status is the safe observability view (no connection strings or secrets).
type Status struct {
	ReadMode             string `json:"read_mode"`
	CanonicalConfigured  bool   `json:"canonical_configured"`
	CanonicalReachable   bool   `json:"canonical_reachable"`
	CanonicalError       string `json:"canonical_error,omitempty"`
	ScoreVersion         string `json:"score_version"`
	ScoreRunID           string `json:"score_run_id,omitempty"`
	ScoreAsOf            string `json:"score_as_of,omitempty"`
	ComparisonRules      string `json:"comparison_rules"`
	ShadowTimeoutMS      int    `json:"shadow_timeout_ms"`

	CanaryEnabled     bool `json:"price_history_canary_enabled"`
	CanarySymbolCount int  `json:"price_history_canary_symbol_count"`
	CanaryPercent     int  `json:"price_history_canary_percent"`
	CanaryVerify      bool `json:"price_history_canary_verify"`
	CanaryTimeoutMS   int  `json:"price_history_canary_timeout_ms"`
}

func newShadowFromEnv() *Shadow {
	cfg := LoadConfig()
	s := &Shadow{cfg: cfg, collector: NewCollector(cfg.OutputDir), canary: newCanaryStats()}
	s.status = Status{
		ReadMode:        string(cfg.Mode),
		ScoreVersion:    cfg.ScoreVersion,
		ComparisonRules: ComparisonRulesVersion,
		ShadowTimeoutMS: int(cfg.ShadowTimeout / time.Millisecond),
	}
	s.startCanaryFlusher()
	if reg, err := LoadEligibility(cfg.EligibilityFile); err != nil {
		log.Printf("[eligibility] failed to load registry %s: %v", cfg.EligibilityFile, err)
	} else if reg != nil {
		s.elig = reg
	}
	if !cfg.AnyShadow() {
		// Default LEGACY: never even attempt a canonical connection.
		return s
	}
	if cfg.CanonicalDSN == "" {
		s.status.CanonicalError = "canonical DSN not configured"
		return s
	}
	pg, err := OpenPG(cfg)
	if err != nil {
		// Canonical availability must never fail startup or requests.
		log.Printf("[shadow] canonical postgres unavailable, shadow reads disabled: %v", err)
		s.status.CanonicalError = err.Error()
		return s
	}
	s.src = pg
	s.status.CanonicalConfigured = true
	return s
}

// newShadowForTest builds a shadow instance with an explicit config/pg.
func newShadowForTest(cfg Config, src canonicalSource) *Shadow {
	s := &Shadow{cfg: cfg, src: src, collector: NewCollector(cfg.OutputDir), canary: newCanaryStats()}
	s.status = Status{
		ReadMode:        string(cfg.Mode),
		ScoreVersion:    cfg.ScoreVersion,
		ComparisonRules: ComparisonRulesVersion,
		ShadowTimeoutMS: int(cfg.ShadowTimeout / time.Millisecond),
	}
	if src != nil {
		s.status.CanonicalConfigured = true
	}
	return s
}

// Enabled reports whether shadow reads should run at all.
func (s *Shadow) Enabled() bool {
	return s != nil && s.src != nil
}

// Config exposes the loaded configuration (read-only use).
func (s *Shadow) Config() Config { return s.cfg }

// Collector exposes the diagnostics collector.
func (s *Shadow) Collector() *Collector { return s.collector }

// Status returns a safe observability snapshot.
func (s *Shadow) Status() Status {
	if s == nil {
		return Status{ReadMode: string(ModeLegacy)}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	st := s.status
	st.CanaryEnabled = s.cfg.Canary.Enabled
	st.CanarySymbolCount = len(s.cfg.Canary.Symbols)
	st.CanaryPercent = s.cfg.Canary.Percent
	st.CanaryVerify = s.cfg.Canary.Verify
	st.CanaryTimeoutMS = int(s.cfg.Canary.Timeout / time.Millisecond)
	return st
}

// FlushCanaryDiagnostics writes the price-history canary artifacts.
func (s *Shadow) FlushCanaryDiagnostics() error { return s.FlushCanary() }

// RefreshStatus pings the canonical backend and records score-run selection.
func (s *Shadow) RefreshStatus(ctx context.Context) Status {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status.CanaryEnabled = s.cfg.Canary.Enabled
	s.status.CanarySymbolCount = len(s.cfg.Canary.Symbols)
	s.status.CanaryPercent = s.cfg.Canary.Percent
	s.status.CanaryVerify = s.cfg.Canary.Verify
	s.status.CanaryTimeoutMS = int(s.cfg.Canary.Timeout / time.Millisecond)
	if s.src == nil {
		return s.status
	}
	if err := s.src.Health(ctx); err != nil {
		s.status.CanonicalReachable = false
		s.status.CanonicalError = err.Error()
		return s.status
	}
	s.status.CanonicalReachable = true
	s.status.CanonicalError = ""
	info, err := s.src.SelectScoreRun(ctx, s.cfg.ScoreVersion)
	if err != nil {
		s.status.CanonicalError = "score run selection failed: " + err.Error()
		return s.status
	}
	if info.RunID != "" {
		s.status.ScoreRunID = info.RunID
		s.status.ScoreAsOf = info.AsOfDate
	}
	return s.status
}

// Mode returns the effective read mode for an endpoint.
func (s *Shadow) Mode(endpoint string) ReadMode {
	if s == nil {
		return ModeLegacy
	}
	return s.cfg.ModeFor(endpoint)
}

// CompareCompanyNames runs a shadow comparison of company identity names.
func (s *Shadow) CompareCompanyNames(ctx context.Context, legacy []string, legacyLatency time.Duration) EndpointResult {
	const ep = EndpointCompanyNames
	if !s.Enabled() || s.Mode(ep) == ModeLegacy {
		return EndpointResult{Endpoint: ep}
	}
	start := time.Now()
	canonNames, err := s.fetchWithTimeout(ctx, func(ctx context.Context) ([]Record, error) {
		names, err := s.src.CompanyNames(ctx)
		if err != nil {
			return nil, err
		}
		recs := make([]Record, 0, len(names))
		for _, n := range names {
			recs = append(recs, Record{"name": TextValue(n)})
		}
		return recs, nil
	})
	legacyRecs := make([]Record, 0, len(legacy))
	for _, n := range legacy {
		legacyRecs = append(legacyRecs, Record{"name": TextValue(n)})
	}
	spec := CompareSpec{
		KeyField:        "name",
		AllowLegacyOnly: true,
		AllowCanonOnly:  true,
		Fields:          []FieldSpec{{Name: "name", Kind: KindText, Identity: true}},
	}
	res := CompareRecords(ep, legacyRecs, canonNames, spec)
	res = s.finish(ep, res, legacyLatency, time.Since(start), err, true)
	return res
}

// ComparePriceHistory runs a shadow comparison of daily market prices. It obeys
// the endpoint mode (SHADOW only).
func (s *Shadow) ComparePriceHistory(ctx context.Context, symbol string, limit int, legacy []MarketInputRow, legacyLatency time.Duration) EndpointResult {
	const ep = EndpointPriceHistory
	if !s.Enabled() || s.Mode(ep) == ModeLegacy {
		return EndpointResult{Endpoint: ep}
	}
	return s.comparePriceHistory(ctx, symbol, limit, legacy, legacyLatency, true)
}

// VerifyCanaryPriceHistory compares a canary-served canonical result against the
// legacy read unconditionally (used only for controlled canary verification).
// It never changes the served response.
func (s *Shadow) VerifyCanaryPriceHistory(ctx context.Context, symbol string, limit int, legacy []MarketInputRow, legacyLatency time.Duration) EndpointResult {
	if s == nil || s.src == nil {
		return EndpointResult{Endpoint: EndpointPriceHistory}
	}
	return s.comparePriceHistory(ctx, symbol, limit, legacy, legacyLatency, false)
}

func (s *Shadow) comparePriceHistory(ctx context.Context, symbol string, limit int, legacy []MarketInputRow, legacyLatency time.Duration, record bool) EndpointResult {
	const ep = EndpointPriceHistory
	start := time.Now()
	canonRows, err := s.fetchWithTimeout(ctx, func(ctx context.Context) ([]Record, error) {
		rows, err := s.src.PriceHistory(ctx, symbol, limit)
		if err != nil {
			return nil, err
		}
		recs := make([]Record, 0, len(rows))
		for _, r := range rows {
			recs = append(recs, marketRecord(r))
		}
		return recs, nil
	})
	legacyRecs := make([]Record, 0, len(legacy))
	for _, r := range legacy {
		legacyRecs = append(legacyRecs, marketRecord(r))
	}
	spec := CompareSpec{
		KeyField:        "date",
		AllowLegacyOnly: true,
		AllowCanonOnly:  true,
		MaxMissingDetail: 10,
		Fields: []FieldSpec{
			{Name: "closing_price", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
			{Name: "last_price", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
			{Name: "high_price", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
			{Name: "low_price", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
			{Name: "volume", Kind: KindNumber, Tolerance: 1e-6},
			{Name: "trade_value", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
			{Name: "change_percent", Kind: KindNumber, Tolerance: 1e-3},
		},
	}
	res := CompareRecords(ep, legacyRecs, canonRows, spec)
	res = s.finish(ep, res, legacyLatency, time.Since(start), err, record)
	return res
}

// CompareScores runs a shadow comparison of canonical analytics scores against
// the legacy v3.7 metrics. Semantic score differences are expected and
// classified; they are never resolved by deforming canonical data.
func (s *Shadow) CompareScores(ctx context.Context, legacy []ScoreInputRow, legacyLatency time.Duration) EndpointResult {
	const ep = EndpointScores
	if !s.Enabled() || s.Mode(ep) == ModeLegacy {
		return EndpointResult{Endpoint: ep}
	}
	ids := make([]string, 0, len(legacy))
	for _, r := range legacy {
		if r.LegacyCompanyID != "" {
			ids = append(ids, r.LegacyCompanyID)
		}
	}
	start := time.Now()
	canonRows, err := s.fetchWithTimeout(ctx, func(ctx context.Context) ([]Record, error) {
		rows, err := s.src.ScoresByLegacyIDs(ctx, s.cfg.ScoreVersion, ids)
		if err != nil {
			return nil, err
		}
		recs := make([]Record, 0, len(rows))
		for _, r := range rows {
			recs = append(recs, scoreRecord(r))
		}
		return recs, nil
	})
	legacyRecs := make([]Record, 0, len(legacy))
	for _, r := range legacy {
		legacyRecs = append(legacyRecs, scoreRecord(r))
	}
	spec := CompareSpec{
		KeyField:        "legacy_company_id",
		AllowLegacyOnly: true,
		AllowCanonOnly:  false,
		MaxMissingDetail: 20,
		Fields: []FieldSpec{
			{Name: "symbol", Kind: KindText, Identity: true},
			{Name: "company_name", Kind: KindText, Identity: true},
			{Name: "quant_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
			{Name: "data_quality_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
			{Name: "growth_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
			{Name: "profitability_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
			{Name: "valuation_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
			{Name: "market_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
		},
	}
	res := CompareRecords(ep, legacyRecs, canonRows, spec)
	res = s.finish(ep, res, legacyLatency, time.Since(start), err, true)
	return res
}

// CompareSalesData runs a shadow comparison of income-statement metrics
// (miandore2 -> fundamentals.financial_facts). The legacy derived product
// heuristics (EPS x Capital, mixed scale) have no canonical counterpart and are
// deliberately NOT compared or re-derived.
func (s *Shadow) CompareSalesData(ctx context.Context, legacy []FinancialInputRow, legacyLatency time.Duration) EndpointResult {
	const ep = EndpointSalesData
	if !s.Enabled() || s.Mode(ep) == ModeLegacy {
		return EndpointResult{Endpoint: ep}
	}
	ids := capIDs(financialIDs(legacy), s.cfg.MaxCompanies)
	bounded := selectFinancial(legacy, ids)
	start := time.Now()
	canonRows, err := s.fetchWithTimeout(ctx, func(ctx context.Context) ([]Record, error) {
		recs := make([]Record, 0, len(bounded))
		for _, id := range ids {
			rows, err := s.src.FinancialMetricsByLegacyCompanyID(ctx, id, 0)
			if err != nil {
				return nil, err
			}
			for _, r := range rows {
				recs = append(recs, financialRecord(r))
			}
		}
		return recs, nil
	})
	legacyRecs := make([]Record, 0, len(bounded))
	for _, r := range bounded {
		legacyRecs = append(legacyRecs, financialRecord(r))
	}
	spec := CompareSpec{
		KeyField:         "row_key",
		AllowLegacyOnly:  true,
		AllowCanonOnly:   true,
		MaxMissingDetail: 20,
		Fields: []FieldSpec{
			{Name: "report_date", Kind: KindText, Identity: true},
			{Name: "eps", Kind: KindNumber, Tolerance: 1e-6},
			{Name: "revenue", Kind: KindNumber, Money: true, Tolerance: 1e-6},
			{Name: "operating_profit", Kind: KindNumber, Money: true, Tolerance: 1e-6},
			{Name: "net_profit", Kind: KindNumber, Money: true, Tolerance: 1e-6},
			{Name: "capital", Kind: KindNumber, Money: true, Tolerance: 1e-6},
		},
	}
	res := CompareRecords(ep, legacyRecs, canonRows, spec)
	res = s.finish(ep, res, legacyLatency, time.Since(start), err, true)
	return res
}

// CompareSalesData2 runs a shadow comparison of monthly activities
// (mahane -> fundamentals.monthly_activities). Quantities compare directly;
// Value3 (reported million_rial) compares exactly to reported_sales_amount and
// is classified EXPECTED_UNIT_PRESENTATION against canonical sales_amount_rial.
func (s *Shadow) CompareSalesData2(ctx context.Context, legacy []MonthlyInputRow, legacyLatency time.Duration) EndpointResult {
	const ep = EndpointSalesData2
	if !s.Enabled() || s.Mode(ep) == ModeLegacy {
		return EndpointResult{Endpoint: ep}
	}
	ids := capIDs(monthlyIDs(legacy), s.cfg.MaxCompanies)
	bounded := selectMonthly(legacy, ids)
	start := time.Now()
	canonRows, err := s.fetchWithTimeout(ctx, func(ctx context.Context) ([]Record, error) {
		recs := make([]Record, 0, len(bounded))
		for _, id := range ids {
			rows, err := s.src.MonthlyActivitiesByLegacyCompanyID(ctx, id, 0)
			if err != nil {
				return nil, err
			}
			for _, r := range rows {
				recs = append(recs, monthlyRecord(r))
			}
		}
		return recs, nil
	})
	legacyRecs := make([]Record, 0, len(bounded))
	for _, r := range bounded {
		legacyRecs = append(legacyRecs, monthlyRecord(r))
	}
	spec := CompareSpec{
		KeyField:         "row_key",
		AllowLegacyOnly:  true,
		AllowCanonOnly:   true,
		MaxMissingDetail: 20,
		Fields: []FieldSpec{
			{Name: "report_date", Kind: KindText, Identity: true},
			{Name: "production_quantity", Kind: KindNumber, Tolerance: 1e-6},
			{Name: "sales_quantity", Kind: KindNumber, Tolerance: 1e-6},
			{Name: "reported_sales_amount", Kind: KindNumber, Money: true, Tolerance: 1e-6},
			{Name: "sales_amount_rial", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
		},
	}
	res := CompareRecords(ep, legacyRecs, canonRows, spec)
	res = s.finish(ep, res, legacyLatency, time.Since(start), err, true)
	return res
}

func financialIDs(rows []FinancialInputRow) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, r := range rows {
		if r.LegacyCompanyID != "" && !seen[r.LegacyCompanyID] {
			seen[r.LegacyCompanyID] = true
			out = append(out, r.LegacyCompanyID)
		}
	}
	return out
}

func monthlyIDs(rows []MonthlyInputRow) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, r := range rows {
		if r.LegacyCompanyID != "" && !seen[r.LegacyCompanyID] {
			seen[r.LegacyCompanyID] = true
			out = append(out, r.LegacyCompanyID)
		}
	}
	return out
}

func capIDs(ids []string, max int) []string {
	if max <= 0 || len(ids) <= max {
		return ids
	}
	return ids[:max]
}

func selectFinancial(rows []FinancialInputRow, ids []string) []FinancialInputRow {
	if len(ids) == 0 {
		return nil
	}
	want := map[string]bool{}
	for _, id := range ids {
		want[id] = true
	}
	out := make([]FinancialInputRow, 0, len(rows))
	for _, r := range rows {
		if want[r.LegacyCompanyID] {
			out = append(out, r)
		}
	}
	return out
}

func selectMonthly(rows []MonthlyInputRow, ids []string) []MonthlyInputRow {
	if len(ids) == 0 {
		return nil
	}
	want := map[string]bool{}
	for _, id := range ids {
		want[id] = true
	}
	out := make([]MonthlyInputRow, 0, len(rows))
	for _, r := range rows {
		if want[r.LegacyCompanyID] {
			out = append(out, r)
		}
	}
	return out
}

func monthlyRecord(r MonthlyInputRow) Record {
	return Record{
		"row_key":               TextValue(r.LegacyCompanyID + "|" + r.ReportDate),
		"legacy_company_id":     TextValue(r.LegacyCompanyID),
		"report_date":           TextValue(r.ReportDate),
		"production_quantity":   NumValue(r.ProductionQuantity),
		"sales_quantity":        NumValue(r.SalesQuantity),
		"reported_sales_amount": NumValue(r.ReportedSalesAmount),
		"sales_amount_rial":     NumValue(r.SalesAmountRial),
	}
}

func financialRecord(r FinancialInputRow) Record {
	return Record{
		"row_key":           TextValue(r.LegacyCompanyID + "|" + r.ReportDate),
		"legacy_company_id": TextValue(r.LegacyCompanyID),
		"report_date":       TextValue(r.ReportDate),
		"eps":               NumValue(r.EPS),
		"revenue":           NumValue(r.Revenue),
		"operating_profit":  NumValue(r.OperatingProfit),
		"net_profit":        NumValue(r.NetProfit),
		"capital":           NumValue(r.Capital),
	}
}

// fetchWithTimeout runs a canonical fetch under the configured shadow timeout.
// A timeout or error is returned, never panicked, so LEGACY responses survive.
func (s *Shadow) fetchWithTimeout(ctx context.Context, fn func(context.Context) ([]Record, error)) ([]Record, error) {
	tctx, cancel := context.WithTimeout(ctx, s.cfg.ShadowTimeout)
	defer cancel()
	type outcome struct {
		recs []Record
		err  error
	}
	ch := make(chan outcome, 1)
	go func() {
		recs, err := fn(tctx)
		ch <- outcome{recs, err}
	}()
	select {
	case o := <-ch:
		return o.recs, o.err
	case <-tctx.Done():
		return nil, tctx.Err()
	}
}

func (s *Shadow) finish(endpoint string, res EndpointResult, legacyLatency, total time.Duration, canonErr error, record bool) EndpointResult {
	if canonErr != nil {
		res.Errors = 1
		res.CanonicalErr = canonErr
		res.Diffs = append(res.Diffs, DiffRecord{
			Endpoint: endpoint, Field: "canonical_query", Class: ClassQueryError,
			Detail: asciiSafe(canonErr.Error()),
		})
		if res.Classifications == nil {
			res.Classifications = map[string]int{}
		}
		res.Classifications[ClassQueryError]++
	}
	res.LatencyLegacy = legacyLatency
	res.LatencyCanonical = total
	res.LatencyTotal = legacyLatency + total
	if record && s.collector != nil {
		s.collector.Record(string(s.Mode(endpoint)), res)
		if err := s.collector.Flush(); err != nil {
			log.Printf("[shadow] failed to flush diagnostics: %v", err)
		}
	}
	return res
}

func marketRecord(r MarketInputRow) Record {
	return Record{
		"date":           DateValue(r.Date),
		"jalali_date":    TextValue(r.JalaliDate),
		"closing_price":  NumValue(r.ClosingPrice),
		"last_price":     NumValue(r.LastPrice),
		"high_price":     NumValue(r.HighPrice),
		"low_price":      NumValue(r.LowPrice),
		"volume":         NumValue(r.Volume),
		"trade_value":    NumValue(r.TradeValue),
		"change_percent": NumValue(r.ChangePercent),
	}
}

func scoreRecord(r ScoreInputRow) Record {
	return Record{
		"legacy_company_id":    TextValue(r.LegacyCompanyID),
		"canonical_company_id": TextValue(r.CanonicalCompanyID),
		"symbol":               TextValue(r.Symbol),
		"company_name":         TextValue(r.CompanyName),
		"quant_score":          NumValue(r.QuantScore),
		"data_quality_score":   NumValue(r.DataQualityScore),
		"growth_score":         NumValue(r.GrowthScore),
		"profitability_score":  NumValue(r.ProfitabilityScore),
		"valuation_score":      NumValue(r.ValuationScore),
		"market_score":         NumValue(r.MarketScore),
	}
}
