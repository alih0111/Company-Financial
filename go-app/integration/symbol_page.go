package integration

import (
	"context"
	"database/sql"
	"fmt"
	"sync"
	"time"
)

// IdentityRow is the canonical Company/Security identity for a legacy company
// key. Company != Security: the company UUID is the company identity and the
// security UUID is the tradable instrument. Names and symbols are aliases, never
// identity.
type IdentityRow struct {
	CanonicalCompanyID  string
	CanonicalSecurityID string
	LegalName           string
	DisplayName         string
	Symbol              string
	TsetmcInsCode       string
}

// AnalyticsMetadata describes the freshness/version state of a selected score
// run so that stale score state is detectable by the application.
type AnalyticsMetadata struct {
	ScoreVersion   string
	ScoreRunID     string
	ScoreAsOf      string
	SourceCutoffAt string
	CompletedAt    string
	// FundamentalsAsOf is the latest canonical fundamentals period date.
	FundamentalsAsOf string
	// MarketAsOf is the latest canonical market observation trade date.
	MarketAsOf string
	// Stale reports whether canonical data is newer than the score run's source
	// cutoff (i.e. ingestion has advanced past the last score computation).
	Stale bool
}

// SymbolPageCanonical is the canonical application-path payload for one symbol,
// covering identity, fundamentals, market history and canonical analytics.
// Every field is set only from canonical stored data; missing data is represented
// by empty/NULL values, never fabricated.
type SymbolPageCanonical struct {
	Identity             IdentityRow
	Monthly              []MonthlyInputRow
	Financial            []FinancialInputRow
	Market               []MarketInputRow
	Scores               []ScoreInputRow
	FactorScores         []FactorScoreInputRow
	MetricSnapshots      []MetricSnapshotInputRow
	Metadata             AnalyticsMetadata
	IdentityFound        bool
	MonthlyPresent       bool
	FinancialPresent     bool
	MarketPresent        bool
	ScorePresent         bool
	FactorScorePresent   bool
	MetricSnapshotExists bool
}

// IdentityByLegacyCompanyID resolves canonical identity for a legacy 32-hex
// company key through core.legacy_entity_map.
func (p *PG) IdentityByLegacyCompanyID(ctx context.Context, legacyID string) (IdentityRow, bool, error) {
	if p == nil || p.db == nil {
		return IdentityRow{}, false, fmt.Errorf("canonical postgres not configured")
	}
	const q = `
		SELECT c.id::text,
		       COALESCE(sec.id::text, ''),
		       COALESCE(c.legal_name, ''),
		       COALESCE(c.display_name, ''),
		       COALESCE(sec.codal_symbol, ''),
		       COALESCE(sec.tsetmc_ins_code::text, '')
		FROM core.legacy_entity_map lem
		JOIN core.companies c ON c.id = lem.target_uuid
		LEFT JOIN core.securities sec ON sec.company_id = c.id AND sec.is_primary
		WHERE lem.entity_type = 'company' AND lem.legacy_key = $1
		LIMIT 1`
	var r IdentityRow
	err := p.db.QueryRowContext(ctx, q, legacyID).Scan(
		&r.CanonicalCompanyID, &r.CanonicalSecurityID, &r.LegalName,
		&r.DisplayName, &r.Symbol, &r.TsetmcInsCode)
	if err == sql.ErrNoRows {
		return IdentityRow{}, false, nil
	}
	if err != nil {
		return IdentityRow{}, false, err
	}
	return r, true, nil
}

// PriceHistoryByLegacyCompanyID returns canonical adjusted daily prices for a
// legacy company key, resolving the security through core.legacy_entity_map.
func (p *PG) PriceHistoryByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]MarketInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if limit <= 0 || limit > 5000 {
		limit = 365
	}
	ident, found, err := p.IdentityByLegacyCompanyID(ctx, legacyID)
	if err != nil {
		return nil, err
	}
	if !found || ident.CanonicalSecurityID == "" {
		return nil, nil
	}
	secID := ident.CanonicalSecurityID
	const q = `
		SELECT DISTINCT ON (po.trade_date)
		       po.trade_date,
		       COALESCE(po.jalali_date_text, ''),
		       COALESCE(po.closing_price_rial, 0),
		       COALESCE(po.last_price_rial, 0),
		       COALESCE(po.high_price_rial, 0),
		       COALESCE(po.low_price_rial, 0),
		       COALESCE(po.volume, 0),
		       COALESCE(po.trade_value_rial, 0),
		       COALESCE(po.closing_change_percent, 0)
		FROM market.price_observations po
		WHERE po.security_id = $1
		  AND po.price_series = 'adjusted'
		ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
		LIMIT $2`
	rows, err := p.db.QueryContext(ctx, q, secID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]MarketInputRow, 0, limit)
	for rows.Next() {
		var r MarketInputRow
		var tradeDate any
		if err := rows.Scan(&tradeDate, &r.JalaliDate, &r.ClosingPrice, &r.LastPrice,
			&r.HighPrice, &r.LowPrice, &r.Volume, &r.TradeValue, &r.ChangePercent); err != nil {
			return nil, err
		}
		r.Date = formatPGDate(tradeDate)
		out = append(out, r)
	}
	return out, rows.Err()
}

// metadataTTL bounds the freshness metadata cache. Metadata changes only when a
// new score run is completed or new canonical data lands, so a short TTL removes
// repeated full-table max() scans without hiding staleness for long.
const metadataTTL = 60 * time.Second

var (
	metaCacheMu      sync.Mutex
	metaCacheVersion string
	metaCacheAt      time.Time
	metaCacheValue   AnalyticsMetadata
)

// Metadata returns analytics freshness/version metadata for a score version.
// Results are cached briefly (metadataTTL) because the underlying max() scans
// are expensive and hourly-scale freshness does not need per-request precision.
func (p *PG) Metadata(ctx context.Context, version string) (AnalyticsMetadata, error) {
	if p == nil || p.db == nil {
		return AnalyticsMetadata{}, fmt.Errorf("canonical postgres not configured")
	}
	metaCacheMu.Lock()
	if metaCacheVersion == version && time.Since(metaCacheAt) < metadataTTL {
		cached := metaCacheValue
		metaCacheMu.Unlock()
		return cached, nil
	}
	metaCacheMu.Unlock()

	info, err := p.SelectScoreRun(ctx, version)
	if err != nil {
		return AnalyticsMetadata{}, err
	}
	m := AnalyticsMetadata{
		ScoreVersion:   info.Version,
		ScoreRunID:     info.RunID,
		ScoreAsOf:      info.AsOfDate,
		SourceCutoffAt: info.SourceCutoffAt,
		CompletedAt:    info.CompletedAt,
	}
	const q = `
		SELECT COALESCE((SELECT max(period_end_date)::text FROM fundamentals.monthly_activities), ''),
		       COALESCE((SELECT max(trade_date)::text FROM market.price_observations), '')`
	if err := p.db.QueryRowContext(ctx, q).Scan(&m.FundamentalsAsOf, &m.MarketAsOf); err != nil {
		return m, err
	}
	if info.SourceCutoffAt != "" {
		if cutoff, err := parsePGTime(info.SourceCutoffAt); err == nil {
			if fa, err := parsePGTime(m.FundamentalsAsOf); err == nil && fa.After(cutoff) {
				m.Stale = true
			}
			if ma, err := parsePGTime(m.MarketAsOf); err == nil && ma.After(cutoff) {
				m.Stale = true
			}
		}
	}
	metaCacheMu.Lock()
	metaCacheVersion = version
	metaCacheAt = time.Now()
	metaCacheValue = m
	metaCacheMu.Unlock()
	return m, nil
}

func parsePGTime(s string) (time.Time, error) {
	if s == "" {
		return time.Time{}, fmt.Errorf("empty time")
	}
	layouts := []string{
		"2006-01-02 15:04:05.999999-07:00",
		"2006-01-02 15:04:05-07:00",
		"2006-01-02T15:04:05Z07:00",
		"2006-01-02",
	}
	var lastErr error
	for _, l := range layouts {
		if t, err := time.Parse(l, s); err == nil {
			return t, nil
		} else {
			lastErr = err
		}
	}
	return time.Time{}, lastErr
}

// SymbolPage assembles the canonical symbol-page payload from canonical storage
// only. It performs no writes and never derives values with Go arithmetic.
func (p *PG) SymbolPage(ctx context.Context, legacyID string) (SymbolPageCanonical, error) {
	var page SymbolPageCanonical
	ident, found, err := p.IdentityByLegacyCompanyID(ctx, legacyID)
	if err != nil {
		return page, err
	}
	page.Identity = ident
	page.IdentityFound = found
	if !found {
		return page, nil
	}

	monthly, err := p.MonthlyActivitiesByLegacyCompanyID(ctx, legacyID, 240)
	if err != nil {
		return page, err
	}
	page.Monthly = monthly
	page.MonthlyPresent = len(monthly) > 0

	financial, err := p.FinancialMetricsByLegacyCompanyID(ctx, legacyID, 120)
	if err != nil {
		return page, err
	}
	page.Financial = financial
	page.FinancialPresent = len(financial) > 0

	market, err := p.PriceHistoryByLegacyCompanyID(ctx, legacyID, 365)
	if err != nil {
		return page, err
	}
	page.Market = market
	page.MarketPresent = len(market) > 0

	version := DefaultScoreVersion
	scores, err := p.ScoresByLegacyIDs(ctx, version, []string{legacyID})
	if err != nil {
		return page, err
	}
	page.Scores = scores
	page.ScorePresent = len(scores) > 0

	factors, err := p.FactorScoresByLegacyIDs(ctx, version, []string{legacyID})
	if err != nil {
		return page, err
	}
	page.FactorScores = factors
	page.FactorScorePresent = len(factors) > 0

	snaps, err := p.MetricSnapshotsByLegacyIDs(ctx, version, []string{legacyID})
	if err != nil {
		return page, err
	}
	page.MetricSnapshots = snaps
	page.MetricSnapshotExists = len(snaps) > 0

	meta, err := p.Metadata(ctx, version)
	if err != nil {
		return page, err
	}
	page.Metadata = meta
	return page, nil
}
