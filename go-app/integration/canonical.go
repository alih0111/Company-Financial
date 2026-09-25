package integration

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
)

// MarketInputRow is the normalized market-price shape used for comparison. It
// mirrors the legacy /api/price-history response fields.
type MarketInputRow struct {
	Date          string
	JalaliDate    string
	ClosingPrice  float64
	LastPrice     float64
	HighPrice     float64
	LowPrice      float64
	Volume        float64
	TradeValue    float64
	ChangePercent float64
}

// ScoreInputRow is the normalized analytics-score shape used for comparison. It
// mirrors the legacy vw_AIStockMetrics subset consumed by /api/summary.
type ScoreInputRow struct {
	LegacyCompanyID    string
	CanonicalCompanyID string
	Symbol             string
	CompanyName        string
	QuantScore         float64
	DataQualityScore   float64
	GrowthScore        float64
	ProfitabilityScore float64
	ValuationScore     float64
	MarketScore        float64
	ScoreVersion       string
}

// ScoreVersionInfo describes the selected canonical score run.
type ScoreVersionInfo struct {
	Version   string
	AsOfDate  string
	RunID     string
	CodeVer   string
	Completed bool
}

// CompanyNames returns the canonical company display names.
func (p *PG) CompanyNames(ctx context.Context) ([]string, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	const q = `
		SELECT DISTINCT COALESCE(NULLIF(BTRIM(display_name), ''), BTRIM(legal_name)) AS name
		FROM core.companies
		WHERE COALESCE(NULLIF(BTRIM(display_name), ''), BTRIM(legal_name)) <> ''
		ORDER BY 1`
	rows, err := p.db.QueryContext(ctx, q)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		out = append(out, name)
	}
	return out, rows.Err()
}

// ResolveSecurityID resolves a legacy symbol/display name to a single canonical
// security UUID through aliases or the security's own symbol fields. It returns
// "" when no security matches.
func (p *PG) ResolveSecurityID(ctx context.Context, symbol string) (string, error) {
	if p == nil || p.db == nil {
		return "", fmt.Errorf("canonical postgres not configured")
	}
	const q = `
		SELECT security_id::text FROM core.security_aliases WHERE alias_value = $1
		UNION
		SELECT id::text FROM core.securities WHERE codal_symbol = $1 OR brs_name = $1
		LIMIT 1`
	var id string
	err := p.db.QueryRowContext(ctx, q, symbol).Scan(&id)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return id, nil
}

// PriceHistory returns canonical adjusted daily prices for a symbol resolved
// through security aliases or the security's own symbol fields. Values are
// canonical IRR / share counts, with no scale guessing.
//
// Performance note (Phase 2): the original implementation joined
// market.daily_prices (a DISTINCT ON view) and let the security predicate apply
// after the view had already ranked all observations (~780 ms). This version
// resolves the security once, then reads the append-only market.price_observations
// directly with DISTINCT ON (trade_date) scoped to that security. It preserves
// the view's deterministic "latest adjusted observation" semantics
// (collected_at DESC, id DESC) and was verified row-for-row equivalent.
func (p *PG) PriceHistory(ctx context.Context, symbol string, limit int) ([]MarketInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if limit <= 0 || limit > 5000 {
		limit = 365
	}
	securityID, err := p.ResolveSecurityID(ctx, symbol)
	if err != nil {
		return nil, err
	}
	if securityID == "" {
		return nil, nil
	}
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
	rows, err := p.db.QueryContext(ctx, q, securityID, limit)
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

// SelectScoreRun returns the latest completed run for a score version.
func (p *PG) SelectScoreRun(ctx context.Context, version string) (ScoreVersionInfo, error) {
	if p == nil || p.db == nil {
		return ScoreVersionInfo{}, fmt.Errorf("canonical postgres not configured")
	}
	const q = `
		SELECT id::text, score_version, as_of_date::text, COALESCE(code_version, ''), status
		FROM analytics.score_runs
		WHERE score_version = $1 AND status = 'completed'
		ORDER BY as_of_date DESC, started_at DESC
		LIMIT 1`
	var info ScoreVersionInfo
	var status string
	err := p.db.QueryRowContext(ctx, q, version).Scan(&info.RunID, &info.Version, &info.AsOfDate, &info.CodeVer, &status)
	if err == sql.ErrNoRows {
		return ScoreVersionInfo{}, nil
	}
	if err != nil {
		return ScoreVersionInfo{}, err
	}
	info.Completed = status == "completed"
	return info, nil
}

// ScoresByLegacyIDs returns canonical company scores for the given legacy
// CompanyIDs (32-hex keys resolved through core.legacy_entity_map).
func (p *PG) ScoresByLegacyIDs(ctx context.Context, version string, ids []string) ([]ScoreInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	const q = `
		WITH run AS (
			SELECT id, score_version FROM analytics.score_runs
			WHERE score_version = $1 AND status = 'completed'
			ORDER BY as_of_date DESC, started_at DESC
			LIMIT 1
		),
		wanted AS (SELECT unnest(string_to_array($2, ',')) AS legacy_key)
		SELECT DISTINCT
		       lem.legacy_key,
		       cs.company_id::text,
		       COALESCE(sec.codal_symbol, ''),
		       COALESCE(NULLIF(BTRIM(c.display_name), ''), BTRIM(c.legal_name)),
		       COALESCE(cs.quant_score, 0),
		       COALESCE(cs.data_quality_score, 0),
		       COALESCE(cs.growth_score, 0),
		       COALESCE(cs.profitability_score, 0),
		       COALESCE(cs.valuation_score, 0),
		       COALESCE(cs.market_score, 0),
		       r.score_version
		FROM analytics.company_scores cs
		JOIN run r ON r.id = cs.run_id
		JOIN core.companies c ON c.id = cs.company_id
		LEFT JOIN core.securities sec ON sec.id = cs.primary_security_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = cs.company_id
		 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
		JOIN wanted w ON w.legacy_key = lem.legacy_key
		ORDER BY COALESCE(cs.quant_score, 0) DESC`
	rows, err := p.db.QueryContext(ctx, q, version, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]ScoreInputRow, 0, len(ids))
	for rows.Next() {
		var r ScoreInputRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.CanonicalCompanyID, &r.Symbol, &r.CompanyName,
			&r.QuantScore, &r.DataQualityScore, &r.GrowthScore, &r.ProfitabilityScore,
			&r.ValuationScore, &r.MarketScore, &r.ScoreVersion); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// MonthlyInputRow is the normalized monthly-activity shape used for comparison.
// Legacy miandore2/mahane values are in their stored units; canonical rows carry
// both reported (million_rial) and canonical (rial) amounts.
type MonthlyInputRow struct {
	LegacyCompanyID     string
	ReportDate          string // Jalali period text, e.g. 1405/06/31
	ProductionQuantity  float64
	SalesQuantity       float64
	ReportedSalesAmount float64 // million_rial (reported unit)
	SalesAmountRial     float64 // rial (canonical unit)
}

// FinancialInputRow is the normalized income-statement metric shape used for
// comparison. Money values are expressed in million_rial (the legacy reported
// unit); EPS is rial_per_share. This mirrors the canonical migration's FACT_MAP
// and never re-derives legacy product heuristics.
type FinancialInputRow struct {
	LegacyCompanyID string
	ReportDate      string // Jalali period text
	EPS             float64
	Revenue         float64 // million_rial
	OperatingProfit float64 // million_rial
	NetProfit       float64 // million_rial
	Capital         float64 // million_rial
}

// MonthlyActivitiesByLegacyCompanyID returns canonical monthly activities for a
// legacy 32-hex CompanyID, resolved through core.legacy_entity_map.
func (p *PG) MonthlyActivitiesByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]MonthlyInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if limit <= 0 || limit > 2000 {
		limit = 240
	}
	const q = `
		SELECT ma.jalali_period_text,
		       COALESCE(ma.production_quantity, 0),
		       COALESCE(ma.sales_quantity, 0),
		       COALESCE(ma.reported_sales_amount, 0),
		       COALESCE(ma.sales_amount_rial, 0)
		FROM fundamentals.monthly_activities ma
		WHERE ma.company_id = (
			SELECT target_uuid FROM core.legacy_entity_map
			WHERE entity_type = 'company' AND legacy_key = $1
			LIMIT 1)
		ORDER BY ma.period_end_date DESC
		LIMIT $2`
	rows, err := p.db.QueryContext(ctx, q, legacyID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]MonthlyInputRow, 0, limit)
	for rows.Next() {
		r := MonthlyInputRow{LegacyCompanyID: legacyID}
		var jalali sql.NullString
		if err := rows.Scan(&jalali, &r.ProductionQuantity, &r.SalesQuantity,
			&r.ReportedSalesAmount, &r.SalesAmountRial); err != nil {
			return nil, err
		}
		r.ReportDate = jalali.String
		out = append(out, r)
	}
	return out, rows.Err()
}

// FinancialMetricsByLegacyCompanyID returns canonical current-period
// income-statement metrics for a legacy CompanyID, pivoted one row per Jalali
// period. Values use the canonical reported unit (million_rial for money,
// rial_per_share for EPS).
func (p *PG) FinancialMetricsByLegacyCompanyID(ctx context.Context, legacyID string, limit int) ([]FinancialInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if limit <= 0 || limit > 2000 {
		limit = 120
	}
	const q = `
		SELECT r.jalali_period_text, f.metric_code, COALESCE(f.reported_value, 0)
		FROM fundamentals.financial_facts f
		JOIN fundamentals.financial_statements fs ON fs.id = f.statement_id
		JOIN ingestion.reports r ON r.id = fs.report_id
		WHERE fs.company_id = (
			SELECT target_uuid FROM core.legacy_entity_map
			WHERE entity_type = 'company' AND legacy_key = $1
			LIMIT 1)
		  AND f.period_order = 1
		  AND f.metric_code IN ('eps','revenue','operating_profit','net_profit','capital')
		ORDER BY r.jalali_period_text DESC`
	rows, err := p.db.QueryContext(ctx, q, legacyID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	byPeriod := map[string]*FinancialInputRow{}
	order := []string{}
	for rows.Next() {
		var period, metric string
		var value float64
		if err := rows.Scan(&period, &metric, &value); err != nil {
			return nil, err
		}
		rec, ok := byPeriod[period]
		if !ok {
			rec = &FinancialInputRow{LegacyCompanyID: legacyID, ReportDate: period}
			byPeriod[period] = rec
			order = append(order, period)
		}
		switch metric {
		case "eps":
			rec.EPS = value
		case "revenue":
			rec.Revenue = value
		case "operating_profit":
			rec.OperatingProfit = value
		case "net_profit":
			rec.NetProfit = value
		case "capital":
			rec.Capital = value
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := make([]FinancialInputRow, 0, len(order))
	for i, period := range order {
		if i >= limit {
			break
		}
		out = append(out, *byPeriod[period])
	}
	return out, nil
}

func formatPGDate(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return NormalizeDate(t)
	case []byte:
		return NormalizeDate(string(t))
	case interface{ Format(string) string }:
		return t.Format("2006-01-02")
	default:
		return fmt.Sprint(v)
	}
}
