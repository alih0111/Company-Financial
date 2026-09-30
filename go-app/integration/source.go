package integration

import "context"

// canonicalSource is the read-only canonical data source consumed by the shadow
// orchestrator. PG implements it; tests inject fakes.
type canonicalSource interface {
	CompanyNames(ctx context.Context) ([]string, error)
	ResolveLegacyCompanyIDByName(ctx context.Context, name string) (string, error)
	PriceHistory(ctx context.Context, symbol string, limit int) ([]MarketInputRow, error)
	SelectScoreRun(ctx context.Context, version string) (ScoreVersionInfo, error)
	ScoresByLegacyIDs(ctx context.Context, version string, ids []string) ([]ScoreInputRow, error)
	MonthlyActivitiesByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]MonthlyInputRow, error)
	FinancialMetricsByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]FinancialInputRow, error)
	NetProfitSeriesByLegacyCompanyID(ctx context.Context, legacyID string) ([]NetProfitPeriodRow, error)
	MonthlyActivitiesByLegacyIDs(ctx context.Context, ids []string, limit int) ([]MonthlyInputRow, error)
	FinancialMetricsByLegacyIDs(ctx context.Context, ids []string, limit int) ([]FinancialInputRow, error)
	FactorScoresByLegacyIDs(ctx context.Context, version string, ids []string) ([]FactorScoreInputRow, error)
	MetricSnapshotsByLegacyIDs(ctx context.Context, version string, ids []string) ([]MetricSnapshotInputRow, error)
	AllScoresCanonical(ctx context.Context, version string) ([]AllScoreInputRow, error)
	CompanyScoreByLegacyID(ctx context.Context, version, legacyID string) (CompanyScoreBundle, error)
	// SymbolPage returns the full canonical bundle for one company: identity,
	// monthly activities, financial periods, market history, scores, factor
	// scores, base-metric snapshots and freshness metadata.
	SymbolPage(ctx context.Context, legacyID string) (SymbolPageCanonical, error)
	// PriceHistoryByLegacyCompanyID returns canonical adjusted daily prices for
	// one company (newest first).
	PriceHistoryByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]MarketInputRow, error)
	// MarketMetaByLegacyCompanyIDs returns the current industry category and the
	// latest share-structure snapshot per company (sector caps + exposure).
	MarketMetaByLegacyCompanyIDs(ctx context.Context, ids []string) ([]MarketMetaRow, error)
	Health(ctx context.Context) error
}
