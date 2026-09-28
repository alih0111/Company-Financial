package integration

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
)

// AllScoreInputRow is the normalized all-companies score shape. The leading
// compatibility fields mirror the legacy /api/AllCompanyScores payload; the
// canonical_* fields are additive and consumed by the current React table.
//
// Compatibility mappings (documented in ANALYTICS_READ_MIGRATION.md):
//
//	SalesGrowth <- canonical factor SalesGrowth.raw_value
//	EPSGrowth   <- canonical factor NetProfitGrowth.raw_value (substitute; not EPS-specific)
//	PE          <- canonical factor PE.raw_value
//	Operation   <- canonical factor OperatingMargin.raw_value
//	Price       <- latest canonical closing price (rial)
//	Stable      <- legacy-only heuristic; no canonical equivalent (never fabricated)
type AllScoreInputRow struct {
	LegacyCompanyID string
	CanonicalID     string
	CompanyName     string
	Symbol          string

	SalesGrowth float64
	EPSGrowth   float64
	PE          float64
	Price       float64
	Operation   float64
	Stable      bool

	QuantScore         float64
	DataQualityScore   float64
	GrowthScore        float64
	ProfitabilityScore float64
	ValuationScore     float64
	MarketScore        float64
	ScoreVersion       string

	// FactorRanks maps canonical factor_code -> percentile (0..1).
	FactorRanks map[string]float64
	// FactorRaw maps canonical factor_code -> raw_value when materialized.
	FactorRaw map[string]float64
}

// CompanyScoreInputRow is the legacy /api/CompanyScores per-company shape used
// for comparison. It carries only display/presentation values; the canonical
// bundle is the analytics source of truth.
type CompanyScoreInputRow struct {
	LegacyCompanyID string
	CompanyName     string
	SalesGrowth     float64
	EPSGrowth       float64
	Operation       float64
	FinalScore      float64
	PE              float64
	Price           float64
}

// CompanyScoreBundle is the canonical per-company score payload: base score,
// category scores, factor scores and freshness metadata. It never contains a
// Go-recomputed score.
type CompanyScoreBundle struct {
	LegacyCompanyID    string
	CanonicalID        string
	CompanyName        string
	Symbol             string
	QuantScore         float64
	DataQualityScore   float64
	GrowthScore        float64
	ProfitabilityScore float64
	ValuationScore     float64
	MarketScore        float64
	ScoreVersion       string
	Factors            []FactorScoreInputRow
	LatestPrice        float64
	HasScore           bool
	HasPrice           bool
	Metadata           AnalyticsMetadata
}

var scoreFactorCodes = []string{
	"SalesGrowth", "SalesGrowth3M", "RevenueGrowth", "OperatingProfitGrowth",
	"NetProfitGrowth", "OperatingMargin", "NetMargin", "PE", "PS", "PB",
}

// AllScoresCanonical returns every company score in the latest completed run for
// the given version, plus the canonical factors needed for API compatibility.
// Go performs no scoring arithmetic; it only reads stored values.
func (p *PG) AllScoresCanonical(ctx context.Context, version string) ([]AllScoreInputRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	// Single indexed query: run selection + score pivot + one lateral price
	// lookup per primary security. Avoids the per-factor/per-price N+1 and the
	// full price_observations scan.
	const baseQ = `
		WITH run AS (
			SELECT id, score_version FROM analytics.score_runs
			WHERE score_version = $1 AND status = 'completed'
			ORDER BY as_of_date DESC, started_at DESC
			LIMIT 1
		)
		SELECT DISTINCT lem.legacy_key, cs.company_id::text,
		       COALESCE(NULLIF(BTRIM(c.display_name), ''), BTRIM(c.legal_name)),
		       COALESCE(sec.codal_symbol, ''),
		       COALESCE(cs.quant_score, 0), COALESCE(cs.data_quality_score, 0),
		       COALESCE(cs.growth_score, 0), COALESCE(cs.profitability_score, 0),
		       COALESCE(cs.valuation_score, 0), COALESCE(cs.market_score, 0),
		       r.score_version,
		       COALESCE(fs_sg.raw_value, 0), COALESCE(fs_npg.raw_value, 0),
		       COALESCE(fs_pe.raw_value, 0), COALESCE(fs_om.raw_value, 0),
		       COALESCE(lp.closing_price_rial, 0)
		FROM analytics.company_scores cs
		JOIN run r ON r.id = cs.run_id
		JOIN core.companies c ON c.id = cs.company_id
		LEFT JOIN core.securities sec ON sec.id = cs.primary_security_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = cs.company_id
		 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
		LEFT JOIN analytics.factor_scores fs_sg
		  ON fs_sg.run_id = cs.run_id AND fs_sg.company_id = cs.company_id
		 AND fs_sg.factor_code = 'SalesGrowth'
		LEFT JOIN analytics.factor_scores fs_npg
		  ON fs_npg.run_id = cs.run_id AND fs_npg.company_id = cs.company_id
		 AND fs_npg.factor_code = 'NetProfitGrowth'
		LEFT JOIN analytics.factor_scores fs_pe
		  ON fs_pe.run_id = cs.run_id AND fs_pe.company_id = cs.company_id
		 AND fs_pe.factor_code = 'PE'
		LEFT JOIN analytics.factor_scores fs_om
		  ON fs_om.run_id = cs.run_id AND fs_om.company_id = cs.company_id
		 AND fs_om.factor_code = 'OperatingMargin'
		LEFT JOIN LATERAL (
			SELECT po.closing_price_rial
			FROM market.price_observations po
			WHERE po.security_id = cs.primary_security_id
			  AND po.price_series = 'adjusted'
			ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
			LIMIT 1
		) lp ON true`
	rows, err := p.db.QueryContext(ctx, baseQ, version)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]AllScoreInputRow, 0)
	index := map[string]int{}
	for rows.Next() {
		var r AllScoreInputRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.CanonicalID, &r.CompanyName, &r.Symbol,
			&r.QuantScore, &r.DataQualityScore, &r.GrowthScore, &r.ProfitabilityScore,
			&r.ValuationScore, &r.MarketScore, &r.ScoreVersion,
			&r.SalesGrowth, &r.EPSGrowth, &r.PE, &r.Operation, &r.Price); err != nil {
			return nil, err
		}
		index[r.LegacyCompanyID] = len(out)
		out = append(out, r)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return out, nil
	}

	// Attach the full canonical factor percentile set (progress-bar ranks) and
	// any materialized raw values. Ranks come directly from analytics.factor_scores.
	frows, err := p.db.QueryContext(ctx, `
		WITH run AS (
			SELECT id FROM analytics.score_runs
			WHERE score_version = $1 AND status = 'completed'
			ORDER BY as_of_date DESC, started_at DESC LIMIT 1
		)
		SELECT lem.legacy_key, fs.factor_code,
		       COALESCE(fs.percentile, 0), fs.raw_value
		FROM analytics.factor_scores fs
		JOIN run r ON r.id = fs.run_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company' AND lem.target_uuid = fs.company_id
		 AND lem.legacy_key ~ '^[0-9a-f]{32}$'`, version)
	if err != nil {
		return nil, err
	}
	defer frows.Close()
	for frows.Next() {
		var key, code string
		var pct float64
		var raw sql.NullFloat64
		if err := frows.Scan(&key, &code, &pct, &raw); err != nil {
			return nil, err
		}
		i, ok := index[key]
		if !ok {
			continue
		}
		if out[i].FactorRanks == nil {
			out[i].FactorRanks = map[string]float64{}
			out[i].FactorRaw = map[string]float64{}
		}
		out[i].FactorRanks[code] = pct
		if raw.Valid {
			out[i].FactorRaw[code] = raw.Float64
		}
	}
	return out, frows.Err()
}

func keysOfAll(rows []AllScoreInputRow) []string {
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		if r.LegacyCompanyID != "" {
			ids = append(ids, r.LegacyCompanyID)
		}
	}
	return ids
}

// LatestClosingPricesByLegacyIDs returns the latest adjusted closing price per
// legacy company key, resolved through core.legacy_entity_map. Missing companies
// are absent from the map (explicit, never fabricated).
func (p *PG) LatestClosingPricesByLegacyIDs(ctx context.Context, ids []string) (map[string]float64, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	out := map[string]float64{}
	if len(ids) == 0 {
		return out, nil
	}
	const q = `
		SELECT DISTINCT ON (lem.legacy_key)
		       lem.legacy_key, COALESCE(po.closing_price_rial, 0)
		FROM market.price_observations po
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'security'
		 AND lem.target_uuid = po.security_id
		 AND lem.legacy_key = ANY(string_to_array($1, ','))
		WHERE lem.legacy_key ~ '^[0-9a-f]{32}$'
		  AND po.price_series = 'adjusted'
		ORDER BY lem.legacy_key, po.trade_date DESC, po.collected_at DESC, po.id DESC`
	rows, err := p.db.QueryContext(ctx, q, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var key string
		var price float64
		if err := rows.Scan(&key, &price); err != nil {
			return nil, err
		}
		out[key] = price
	}
	return out, rows.Err()
}

// CompanyScoreByLegacyID returns the canonical score bundle for one legacy
// company key. Identity is resolved through core.legacy_entity_map; names are
// never used as identity.
func (p *PG) CompanyScoreByLegacyID(ctx context.Context, version, legacyID string) (CompanyScoreBundle, error) {
	var b CompanyScoreBundle
	if p == nil || p.db == nil {
		return b, fmt.Errorf("canonical postgres not configured")
	}
	b.LegacyCompanyID = legacyID
	const q = `
		WITH run AS (
			SELECT id, score_version FROM analytics.score_runs
			WHERE score_version = $1 AND status = 'completed'
			ORDER BY as_of_date DESC, started_at DESC
			LIMIT 1
		)
		SELECT cs.company_id::text,
		       COALESCE(NULLIF(BTRIM(c.display_name), ''), BTRIM(c.legal_name)),
		       COALESCE(sec.codal_symbol, ''),
		       COALESCE(cs.quant_score, 0), COALESCE(cs.data_quality_score, 0),
		       COALESCE(cs.growth_score, 0), COALESCE(cs.profitability_score, 0),
		       COALESCE(cs.valuation_score, 0), COALESCE(cs.market_score, 0),
		       r.score_version,
		       COALESCE(lp.closing_price_rial, 0)
		FROM analytics.company_scores cs
		JOIN run r ON r.id = cs.run_id
		JOIN core.companies c ON c.id = cs.company_id
		LEFT JOIN core.securities sec ON sec.id = cs.primary_security_id
		JOIN core.legacy_entity_map lem
		  ON lem.entity_type = 'company'
		 AND lem.target_uuid = cs.company_id
		 AND lem.legacy_key = $2
		LEFT JOIN LATERAL (
			SELECT po.closing_price_rial
			FROM market.price_observations po
			WHERE po.security_id = cs.primary_security_id
			  AND po.price_series = 'adjusted'
			ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
			LIMIT 1
		) lp ON true
		LIMIT 1`
	err := p.db.QueryRowContext(ctx, q, version, legacyID).Scan(
		&b.CanonicalID, &b.CompanyName, &b.Symbol,
		&b.QuantScore, &b.DataQualityScore, &b.GrowthScore, &b.ProfitabilityScore,
		&b.ValuationScore, &b.MarketScore, &b.ScoreVersion, &b.LatestPrice)
	if err == sql.ErrNoRows {
		return b, nil
	}
	if err != nil {
		return b, err
	}
	b.HasScore = true
	b.HasPrice = b.LatestPrice != 0

	factors, err := p.FactorScoresByLegacyIDs(ctx, version, []string{legacyID})
	if err != nil {
		return b, err
	}
	b.Factors = factors

	meta, err := p.Metadata(ctx, version)
	if err != nil {
		return b, err
	}
	b.Metadata = meta
	return b, nil
}

// FactorValue returns a canonical factor raw value by code, if present.
func (b CompanyScoreBundle) FactorValue(code string) (float64, bool) {
	return b.factorValue(code)
}

// factorValue returns a canonical factor raw value by code, if present.
func (b CompanyScoreBundle) factorValue(code string) (float64, bool) {
	for _, f := range b.Factors {
		if f.FactorCode == code {
			return f.RawValue, true
		}
	}
	return 0, false
}
