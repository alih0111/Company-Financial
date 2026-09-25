package integration

import "context"

// canonicalSource is the read-only canonical data source consumed by the shadow
// orchestrator. PG implements it; tests inject fakes.
type canonicalSource interface {
	CompanyNames(ctx context.Context) ([]string, error)
	PriceHistory(ctx context.Context, symbol string, limit int) ([]MarketInputRow, error)
	SelectScoreRun(ctx context.Context, version string) (ScoreVersionInfo, error)
	ScoresByLegacyIDs(ctx context.Context, version string, ids []string) ([]ScoreInputRow, error)
	MonthlyActivitiesByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]MonthlyInputRow, error)
	FinancialMetricsByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]FinancialInputRow, error)
	Health(ctx context.Context) error
}
