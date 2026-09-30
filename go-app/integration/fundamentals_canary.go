package integration

import (
	"context"
	"fmt"
	"time"
)

// This file adds canonical serving routes and fetch helpers for the
// fundamentals/score endpoints (SalesData2, AllCompanyScores, CompanyScores).
// They reuse the same read-mode contract and identity eligibility guard as the
// price-history canary, with automatic legacy fallback handled by the callers.

// FundCanaryEnabled reports whether the fundamentals/score canary is configured.
func (s *Shadow) FundCanaryEnabled() bool {
	return s != nil && s.cfg.FundCanary.Enabled
}

// FundCanaryVerify reports whether fund-canary responses are also compared.
func (s *Shadow) FundCanaryVerify() bool {
	return s != nil && s.cfg.FundCanary.Verify
}

// FundCanaryTimeout returns the canonical fetch timeout for fund endpoints.
func (s *Shadow) FundCanaryTimeout() time.Duration {
	if s == nil {
		return 2 * time.Second
	}
	return s.cfg.FundCanary.Timeout
}

// fundamentalsRoute applies the shared routing policy for a symbol-keyed fund
// endpoint.
func (s *Shadow) fundamentalsRoute(endpoint, key string) PriceRoute {
	if s == nil {
		return RouteLegacy
	}
	// SQL Server retired: serve canonical (or an explicit canonical error), never
	// attempt an unreachable SQL Server.
	if sqlserverOfflineExpected() {
		return RouteCanary
	}
	mode := s.Mode(endpoint)
	if mode == ModeShadow {
		if s.EligibilityGuardActive() && !s.IsCanonicalEligible(key) {
			return RouteLegacy
		}
		return RouteShadow
	}
	safe := s.IsCanonicalEligible(key)
	if mode == ModeCanonical {
		if safe {
			return RouteCanary
		}
		return RouteLegacy
	}
	if s.cfg.FundCanary.Enabled && s.cfg.FundCanary.Selects(key) {
		if safe {
			return RouteCanary
		}
		return RouteLegacy
	}
	return RouteLegacy
}

// SalesData2Route decides serving for GET /api/SalesData2.
func (s *Shadow) SalesData2Route(companyName string) PriceRoute {
	return s.fundamentalsRoute(EndpointSalesData2, companyName)
}

// CompanyScoresRoute decides serving for GET /api/CompanyScores.
func (s *Shadow) CompanyScoresRoute(companyName string) PriceRoute {
	return s.fundamentalsRoute(EndpointCompanyScores, companyName)
}

// AllCompanyScoresRoute decides serving for GET /api/AllCompanyScores. The
// endpoint is population-wide, so there is no per-request symbol guard; it is
// served canonically only when explicitly configured.
func (s *Shadow) AllCompanyScoresRoute() PriceRoute {
	if s == nil {
		return RouteLegacy
	}
	mode := s.Mode(EndpointAllCompanyScores)
	if mode == ModeShadow {
		return RouteShadow
	}
	if mode == ModeCanonical || s.cfg.FundCanary.Enabled {
		return RouteCanary
	}
	return RouteLegacy
}

func (s *Shadow) withFundTimeout(ctx context.Context) (context.Context, context.CancelFunc) {
	timeout := s.FundCanaryTimeout()
	if sqlserverOfflineExpected() {
		timeout = offlineCanonicalTimeout
	}
	return context.WithTimeout(ctx, timeout)
}

// FetchSalesData2Canonical reads canonical monthly activities for a
// client-visible company/symbol name under the fund-canary timeout.
func (s *Shadow) FetchSalesData2Canonical(ctx context.Context, companyName string) ([]MonthlyInputRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	legacyID, err := s.src.ResolveLegacyCompanyIDByName(tctx, companyName)
	if err != nil {
		return nil, err
	}
	if legacyID == "" {
		return nil, nil
	}
	return s.src.MonthlyActivitiesByLegacyCompanyID(tctx, legacyID, 0)
}

// CompanyNamesRoute decides serving for GET /api/CompanyNames (population-wide).
func (s *Shadow) CompanyNamesRoute() PriceRoute {
	return s.populationRoute(EndpointCompanyNames)
}

// SalesDataRoute decides serving for GET /api/SalesData (symbol-keyed).
func (s *Shadow) SalesDataRoute(companyName string) PriceRoute {
	return s.fundamentalsRoute(EndpointSalesData, companyName)
}

// SummaryRoute decides serving for GET /api/summary (population-wide).
func (s *Shadow) SummaryRoute() PriceRoute {
	return s.populationRoute(EndpointScores)
}

// populationRoute is the shared policy for endpoints without a single symbol.
func (s *Shadow) populationRoute(endpoint string) PriceRoute {
	if s == nil {
		return RouteLegacy
	}
	if sqlserverOfflineExpected() {
		return RouteCanary
	}
	mode := s.Mode(endpoint)
	if mode == ModeShadow {
		return RouteShadow
	}
	if mode == ModeCanonical || s.cfg.FundCanary.Enabled {
		return RouteCanary
	}
	return RouteLegacy
}

// FetchCompanyNamesCanonical reads canonical company/symbol names.
func (s *Shadow) FetchCompanyNamesCanonical(ctx context.Context) ([]string, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	return s.src.CompanyNames(tctx)
}

// FetchSalesDataCanonical reads canonical income-statement metrics for a name.
func (s *Shadow) FetchSalesDataCanonical(ctx context.Context, companyName string) ([]FinancialInputRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	legacyID, err := s.src.ResolveLegacyCompanyIDByName(tctx, companyName)
	if err != nil {
		return nil, err
	}
	if legacyID == "" {
		return nil, nil
	}
	return s.src.FinancialMetricsByLegacyCompanyID(tctx, legacyID, 0)
}

// FetchCumulativeProfitCanonical reads the reported cumulative net-profit
// periods (oldest->newest) for the upper chart. Periods without reported
// net_profit are absent; EPS is never substituted.
func (s *Shadow) FetchCumulativeProfitCanonical(ctx context.Context, companyName string) ([]NetProfitPeriodRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	legacyID, err := s.src.ResolveLegacyCompanyIDByName(tctx, companyName)
	if err != nil {
		return nil, err
	}
	if legacyID == "" {
		return nil, nil
	}
	return s.src.NetProfitSeriesByLegacyCompanyID(tctx, legacyID)
}

// FetchSummaryCanonical reads the latest completed canonical score run for the
// summary endpoint.
func (s *Shadow) FetchSummaryCanonical(ctx context.Context) ([]AllScoreInputRow, error) {
	return s.FetchAllScoresCanonical(ctx)
}

// FetchAllScoresCanonical reads the latest completed canonical score run.
func (s *Shadow) FetchAllScoresCanonical(ctx context.Context) ([]AllScoreInputRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	return s.src.AllScoresCanonical(tctx, s.cfg.ScoreVersion)
}

// FetchCompanyScoreCanonical reads the canonical score bundle for one company.
func (s *Shadow) FetchCompanyScoreCanonical(ctx context.Context, companyName string) (CompanyScoreBundle, error) {
	if s == nil || s.src == nil {
		return CompanyScoreBundle{}, fmt.Errorf("canonical source not configured")
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	legacyID, err := s.src.ResolveLegacyCompanyIDByName(tctx, companyName)
	if err != nil {
		return CompanyScoreBundle{}, err
	}
	if legacyID == "" {
		return CompanyScoreBundle{}, nil
	}
	return s.src.CompanyScoreByLegacyID(tctx, s.cfg.ScoreVersion, legacyID)
}

// SymbolPageCanonical reads the full canonical bundle for one company by its
// legacy 32-hex CompanyID: identity, monthly activities, financial periods,
// market history, scores, factor scores and base-metric snapshots.
func (s *Shadow) FetchSymbolPageCanonical(ctx context.Context, legacyID string) (SymbolPageCanonical, error) {
	if s == nil || s.src == nil {
		return SymbolPageCanonical{}, fmt.Errorf("canonical source not configured")
	}
	if legacyID == "" {
		return SymbolPageCanonical{}, nil
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	return s.src.SymbolPage(tctx, legacyID)
}

// FetchPriceSeriesCanonical reads canonical adjusted daily prices for one
// company by legacy 32-hex CompanyID (newest first), which is what the risk and
// portfolio math consumes.
func (s *Shadow) FetchPriceSeriesCanonical(ctx context.Context, legacyID string, limit int) ([]MarketInputRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	if legacyID == "" {
		return nil, nil
	}
	if limit <= 0 || limit > 2000 {
		limit = 400
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	return s.src.PriceHistoryByLegacyCompanyID(tctx, legacyID, limit)
}

// FetchMarketMetaCanonical reads industry/share-structure metadata for the given
// legacy company ids.
func (s *Shadow) FetchMarketMetaCanonical(ctx context.Context, ids []string) ([]MarketMetaRow, error) {
	if s == nil || s.src == nil {
		return nil, fmt.Errorf("canonical source not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	tctx, cancel := s.withFundTimeout(ctx)
	defer cancel()
	return s.src.MarketMetaByLegacyCompanyIDs(tctx, ids)
}
