package integration

import (
	"context"
	"database/sql"
	"fmt"
	"strconv"
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
	// SourceCutoffAt is the point-in-time cutoff the run was computed from.
	SourceCutoffAt string
	// CompletedAt is when the run finished.
	CompletedAt string
}

// FactorScoreInputRow is a canonical analytics factor score. Go consumes these
// rows verbatim; it never recomputes percentile, weight or weighted score.
type FactorScoreInputRow struct {
	LegacyCompanyID    string
	CanonicalCompanyID string
	FactorCode         string
	RawValue           float64
	Percentile         float64
	WeightedScore      float64
	Weight             float64
}

// MetricSnapshotInputRow is a canonical analytics base-metric snapshot. When the
// canonical computation does not materialize snapshots the read returns no rows
// (explicit missing-data behaviour, never fabricated values).
type MetricSnapshotInputRow struct {
	LegacyCompanyID    string
	CanonicalCompanyID string
	MetricCode         string
	AsOfDate           string
	Value              float64
	Unit               string
	CalculationVersion string
}

// CompanyNames returns the canonical company display names.
func (p *PG) CompanyNames(ctx context.Context) ([]string, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	// Union company display/legal names with security aliases so that
	// symbol-named companies match the legacy name set without changing
	// canonical identity.
	const q = `
		SELECT name FROM (
			SELECT COALESCE(NULLIF(BTRIM(display_name), ''), BTRIM(legal_name)) AS name
			FROM core.companies
			WHERE COALESCE(NULLIF(BTRIM(display_name), ''), BTRIM(legal_name)) <> ''
			UNION
			SELECT COALESCE(NULLIF(BTRIM(sec.codal_symbol), ''), BTRIM(sec.brs_name)) AS name
			FROM core.securities sec
			WHERE COALESCE(NULLIF(BTRIM(sec.codal_symbol), ''), BTRIM(sec.brs_name)) <> ''
			UNION
			SELECT BTRIM(sa.alias_value) AS name
			FROM core.security_aliases sa
			WHERE BTRIM(sa.alias_value) <> ''
		) t
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

// ResolveLegacyCompanyIDByName maps a client-visible company/symbol name to a
// canonical legacy company key (32-hex) through company names, security symbols
// and security aliases. Names are lookup values only; the returned key is the
// explicit legacy mapping used by the canonical readers.
func (p *PG) ResolveLegacyCompanyIDByName(ctx context.Context, name string) (string, error) {
	if p == nil || p.db == nil {
		return "", fmt.Errorf("canonical postgres not configured")
	}
	name = NormalizeText(name)
	if name == "" {
		return "", nil
	}
	const q = `
		SELECT lem.legacy_key
		FROM core.legacy_entity_map lem
		JOIN core.companies c ON c.id = lem.target_uuid AND lem.entity_type = 'company'
		LEFT JOIN core.securities sec ON sec.company_id = c.id
		LEFT JOIN core.security_aliases sa ON sa.security_id = sec.id
		WHERE lem.legacy_key ~ '^[0-9a-f]{32}$'
		  AND (BTRIM(c.display_name) = $1 OR BTRIM(c.legal_name) = $1
		       OR sec.codal_symbol = $1 OR sec.brs_name = $1
		       OR sa.alias_value = $1)
		LIMIT 1`
	var id string
	err := p.db.QueryRowContext(ctx, q, name).Scan(&id)
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
		SELECT id::text, score_version, as_of_date::text, COALESCE(code_version, ''), status,
		       COALESCE(source_cutoff_at::text, ''), COALESCE(completed_at::text, '')
		FROM analytics.score_runs
		WHERE score_version = $1 AND status = 'completed'
		ORDER BY as_of_date DESC, started_at DESC
		LIMIT 1`
	var info ScoreVersionInfo
	var status string
	err := p.db.QueryRowContext(ctx, q, version).Scan(
		&info.RunID, &info.Version, &info.AsOfDate, &info.CodeVer, &status,
		&info.SourceCutoffAt, &info.CompletedAt)
	if err == sql.ErrNoRows {
		return ScoreVersionInfo{}, nil
	}
	if err != nil {
		return ScoreVersionInfo{}, err
	}
	info.Completed = status == "completed"
	return info, nil
}

// FactorScoresByLegacyIDs returns canonical analytics factor scores for the
// given legacy CompanyIDs, resolved through core.legacy_entity_map. Percentile,
// weight and weighted score are canonical stored values; Go never recomputes
// them.
func (p *PG) FactorScoresByLegacyIDs(ctx context.Context, version string, ids []string) ([]FactorScoreInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	const q = `
		WITH run AS (
			SELECT id FROM analytics.score_runs
			WHERE score_version = $1 AND status = 'completed'
			ORDER BY as_of_date DESC, started_at DESC
			LIMIT 1
		),
		wanted AS (SELECT unnest(string_to_array($2, ',')) AS legacy_key)
		SELECT DISTINCT lem.legacy_key, fs.company_id::text, fs.factor_code,
		       COALESCE(fs.raw_value, 0), COALESCE(fs.percentile, 0),
		       COALESCE(fs.weighted_score, 0), COALESCE(fs.weight, 0)
		FROM analytics.factor_scores fs
		JOIN run r ON r.id = fs.run_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = fs.company_id
		 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
		JOIN wanted w ON w.legacy_key = lem.legacy_key
		ORDER BY lem.legacy_key, fs.factor_code`
	rows, err := p.db.QueryContext(ctx, q, version, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]FactorScoreInputRow, 0)
	for rows.Next() {
		var r FactorScoreInputRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.CanonicalCompanyID, &r.FactorCode,
			&r.RawValue, &r.Percentile, &r.WeightedScore, &r.Weight); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// MetricSnapshotsByLegacyIDs returns canonical analytics metric snapshots for the
// given legacy CompanyIDs. The query is version-scoped when the snapshot table
// carries a calculation_version; absent snapshots yield no rows.
func (p *PG) MetricSnapshotsByLegacyIDs(ctx context.Context, version string, ids []string) ([]MetricSnapshotInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	const q = `
		WITH wanted AS (SELECT unnest(string_to_array($2, ',')) AS legacy_key)
		SELECT DISTINCT lem.legacy_key, ms.company_id::text, ms.metric_code,
		       ms.as_of_date::text, COALESCE(ms.value, 0), COALESCE(ms.unit, ''),
		       COALESCE(ms.calculation_version, '')
		FROM analytics.metric_snapshots ms
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = ms.company_id
		 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
		JOIN wanted w ON w.legacy_key = lem.legacy_key
		WHERE ($1 = '' OR ms.calculation_version IS NULL OR ms.calculation_version = $1)
		ORDER BY lem.legacy_key, ms.metric_code`
	rows, err := p.db.QueryContext(ctx, q, version, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]MetricSnapshotInputRow, 0)
	for rows.Next() {
		var r MetricSnapshotInputRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.CanonicalCompanyID, &r.MetricCode,
			&r.AsOfDate, &r.Value, &r.Unit, &r.CalculationVersion); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
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

// MonthlyActivitiesByLegacyIDs is the set-based form of
// MonthlyActivitiesByLegacyCompanyID. It resolves every requested company in a
// single indexed query, eliminating the per-company N+1 pattern.
func (p *PG) MonthlyActivitiesByLegacyIDs(ctx context.Context, ids []string, limit int) ([]MonthlyInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	if limit <= 0 || limit > 2000 {
		limit = 240
	}
	const q = `
		SELECT DISTINCT lem.legacy_key, ma.jalali_period_text,
		       COALESCE(ma.production_quantity, 0),
		       COALESCE(ma.sales_quantity, 0),
		       COALESCE(ma.reported_sales_amount, 0),
		       COALESCE(ma.sales_amount_rial, 0),
		       ma.period_end_date
		FROM fundamentals.monthly_activities ma
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = ma.company_id
		 AND lem.legacy_key = ANY(string_to_array($1, ','))
		WHERE lem.legacy_key ~ '^[0-9a-f]{32}$'
		ORDER BY lem.legacy_key, ma.period_end_date DESC`
	rows, err := p.db.QueryContext(ctx, q, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]MonthlyInputRow, 0)
	perCompany := map[string]int{}
	for rows.Next() {
		var r MonthlyInputRow
		var jalali sql.NullString
		var periodEnd any
		if err := rows.Scan(&r.LegacyCompanyID, &jalali, &r.ProductionQuantity,
			&r.SalesQuantity, &r.ReportedSalesAmount, &r.SalesAmountRial, &periodEnd); err != nil {
			return nil, err
		}
		if perCompany[r.LegacyCompanyID] >= limit {
			continue
		}
		perCompany[r.LegacyCompanyID]++
		r.ReportDate = jalali.String
		out = append(out, r)
	}
	return out, rows.Err()
}

// NetProfitPeriodRow is one reported cumulative net-profit period.
type NetProfitPeriodRow struct {
	LegacyCompanyID string
	JalaliPeriod    string
	PeriodEndDate   string
	FiscalYear      int
	PeriodOrder     int // interim length label: 3 | 6 | 9 | 12
	ReportedMillion float64
	CanonicalRial   float64
	SourceReportID  string
}

// NetProfitSeriesByLegacyCompanyID returns the reported cumulative net-profit
// periods for a legacy company key, using the current valid statement per period
// (period_order=1 = current period of each report). Periods where net_profit was
// not reported are absent (never fabricated, never EPS-substituted).
func (p *PG) NetProfitSeriesByLegacyCompanyID(ctx context.Context, legacyID string) ([]NetProfitPeriodRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	// Current-period selection: one row per (company, period), the current valid
	// fact is the one whose report is most recent (published_at, then version).
	// Duration semantics come from the Codal report TITLE (۳ ماهه/۶ ماهه/…), not
	// from the calendar month, so non-Esfand fiscal years are handled correctly.
	const q = `
		WITH src AS (
			SELECT fs.period_end_date,
			       r.jalali_period_text,
			       COALESCE(cr.title, r.title, '') AS title,
			       COALESCE(cr.published_at, r.published_at) AS published_at,
			       COALESCE(cr.source_report_id, r.source_report_id, '') AS source_report_id,
			       COALESCE(f.reported_value, 0) AS reported_million,
			       COALESCE(f.canonical_value, 0) AS canonical_rial
			FROM fundamentals.financial_facts f
			JOIN fundamentals.financial_statements fs ON fs.id = f.statement_id
			JOIN ingestion.reports r ON r.id = fs.report_id
			LEFT JOIN LATERAL (
				SELECT cr.title, cr.published_at, cr.source_report_id
				FROM ingestion.reports cr
				WHERE cr.company_id = fs.company_id AND cr.source = 'codal'
				  AND cr.period_end_date = fs.period_end_date
				ORDER BY cr.published_at DESC NULLS LAST, cr.created_at DESC
				LIMIT 1
			) cr ON true
			WHERE fs.company_id = (
				SELECT target_uuid FROM core.legacy_entity_map
				WHERE entity_type = 'company' AND legacy_key = $1 LIMIT 1)
			  AND fs.statement_type = 'income_statement'
			  AND f.metric_code = 'net_profit'
			  AND f.period_order = 1
		)
		SELECT DISTINCT ON (period_end_date)
		       COALESCE(jalali_period_text, ''), COALESCE(published_at::text, ''),
		       COALESCE(period_end_date::text, ''),
		       reported_million, canonical_rial, source_report_id, title
		FROM src
		ORDER BY period_end_date, published_at DESC NULLS LAST`
	rows, err := p.db.QueryContext(ctx, q, legacyID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]NetProfitPeriodRow, 0)
	for rows.Next() {
		var r NetProfitPeriodRow
		var published, title string
		if err := rows.Scan(&r.JalaliPeriod, &published, &r.PeriodEndDate,
			&r.ReportedMillion, &r.CanonicalRial, &r.SourceReportID, &title); err != nil {
			return nil, err
		}
		r.LegacyCompanyID = legacyID
		fy, dur := fiscalYearDurationFromTitle(title)
		if fy == 0 {
			r.FiscalYear = jalaliYear(r.JalaliPeriod)
		} else {
			r.FiscalYear = fy
		}
		r.PeriodOrder = dur
		out = append(out, r)
	}
	return out, rows.Err()
}

// fiscalYearDurationFromTitle deterministically parses the Codal report title,
// e.g. "... دوره ۳ ماهه منتهی به ۱۴۰۴/۰۶/۳۱ ..." -> fiscal year 1404, duration 6.
// It never infers duration from the calendar month. Returns (0,0) when absent.
func fiscalYearDurationFromTitle(title string) (int, int) {
	if strings.TrimSpace(title) == "" {
		return 0, 0
	}
	t := normalizePersianDigits(title)
	dur := 0
	for _, d := range []int{12, 9, 6, 3} {
		if strings.Contains(t, fmt.Sprintf("%d ماهه", d)) {
			dur = d
			break
		}
	}
	if dur == 0 && (strings.Contains(t, "سال مالی") || strings.Contains(t, "12 ماهه")) {
		dur = 12
	}
	fy := 0
	// "منتهی به 1404/06/31"
	if i := strings.Index(t, "منتهی به"); i >= 0 {
		rest := strings.TrimSpace(t[i+len("منتهی به"):])
		if j := strings.Index(rest, "/"); j >= 4 {
			if v, err := strconv.Atoi(rest[j-4 : j]); err == nil {
				fy = v
			}
		}
	}
	return fy, dur
}

func normalizePersianDigits(s string) string {
	repl := map[rune]rune{'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
		'۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'}
	var b strings.Builder
	for _, r := range s {
		if d, ok := repl[r]; ok {
			b.WriteRune(d)
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func jalaliYear(period string) int {
	parts := strings.SplitN(strings.TrimSpace(period), "/", 2)
	if len(parts) == 0 {
		return 0
	}
	y, _ := strconv.Atoi(parts[0])
	return y
}

func jalaliMonth(period string) int {
	parts := strings.SplitN(strings.TrimSpace(period), "/", 3)
	if len(parts) < 2 {
		return 0
	}
	m, _ := strconv.Atoi(parts[1])
	return m
}

// periodOrderFromMonth maps a Jalali month to the conventional interim length
// (3M/6M/9M/12M) for an Esfand-ending fiscal year. Non-standard fiscal years are
// documented as a limitation (canonical migrated statements carry no fiscal
// metadata).
func periodOrderFromMonth(month int) int {
	switch {
	case month <= 3:
		return 3
	case month <= 6:
		return 6
	case month <= 9:
		return 9
	default:
		return 12
	}
}

// FinancialMetricsByLegacyIDs is the set-based form of
// FinancialMetricsByLegacyCompanyID, pivoting one row per company/period in Go
// from a single indexed query.
func (p *PG) FinancialMetricsByLegacyIDs(ctx context.Context, ids []string, limit int) ([]FinancialInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	if limit <= 0 || limit > 2000 {
		limit = 120
	}
	const q = `
		SELECT DISTINCT lem.legacy_key, r.jalali_period_text, f.metric_code, COALESCE(f.reported_value, 0)
		FROM fundamentals.financial_facts f
		JOIN fundamentals.financial_statements fs ON fs.id = f.statement_id
		JOIN ingestion.reports r ON r.id = fs.report_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = fs.company_id
		 AND lem.legacy_key = ANY(string_to_array($1, ','))
		WHERE lem.legacy_key ~ '^[0-9a-f]{32}$'
		  AND f.period_order = 1
		  AND f.metric_code IN ('eps','revenue','operating_profit','net_profit','capital')
		ORDER BY lem.legacy_key, r.jalali_period_text DESC`
	rows, err := p.db.QueryContext(ctx, q, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	byPeriod := map[string]*FinancialInputRow{}
	order := []string{}
	perCompany := map[string]int{}
	for rows.Next() {
		var legacyID, period, metric string
		var value float64
		if err := rows.Scan(&legacyID, &period, &metric, &value); err != nil {
			return nil, err
		}
		key := legacyID + "|" + period
		rec, ok := byPeriod[key]
		if !ok {
			if perCompany[legacyID] >= limit {
				continue
			}
			perCompany[legacyID]++
			rec = &FinancialInputRow{LegacyCompanyID: legacyID, ReportDate: period}
			byPeriod[key] = rec
			order = append(order, key)
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
	for _, key := range order {
		out = append(out, *byPeriod[key])
	}
	return out, nil
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
