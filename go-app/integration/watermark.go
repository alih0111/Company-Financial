package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// InputWatermark is the run-level input fingerprint written by
// compute_metrics.store_run (via orchestrate_refresh.py). A run records what existed
// when it computed; staleness is "the fingerprint moved".
//
// The HTTP freshness badge compares the cheap fields (date / arrival / rows), which
// catch every add-only change without a multi-second content scan. The `digest` is
// the orchestrator's authority for the actual recompute decision. Domain keys must
// stay in sync with compute_metrics.INPUT_DOMAIN_AGGREGATES and
// integration_shadow_v1/ANALYTICS_REFRESH_CONTRACT.md.
type InputWatermark struct {
	V       int                        `json:"v"`
	Domains map[string]WatermarkDomain `json:"domains"`
	Digest  string                     `json:"digest"`
}

// WatermarkDomain is one input domain's cheap fingerprint.
type WatermarkDomain struct {
	// Date is the newest PIT-visible period/trade date (empty for reports).
	Date string `json:"date"`
	// Arrival is the newest insertion timestamp in the domain.
	Arrival string `json:"arrival"`
	// Rows is the row count.
	Rows *int64 `json:"rows"`
}

// cheapWatermarkSQL mirrors the cheap subset of compute_metrics.INPUT_DOMAIN_AGGREGATES
// (data date, arrival, row count per domain). Keep the two in sync; the contract file
// is the source of truth for the domain list.
const cheapWatermarkSQL = `
	SELECT
	  COALESCE((SELECT max(period_end_date)::text FROM fundamentals.monthly_activities), ''),
	  COALESCE((SELECT max(created_at)::text FROM fundamentals.monthly_activities), ''),
	  (SELECT count(*) FROM fundamentals.monthly_activities),
	  COALESCE((SELECT max(period_end_date)::text FROM fundamentals.financial_statements), ''),
	  COALESCE((SELECT max(created_at)::text FROM fundamentals.financial_facts), ''),
	  (SELECT count(*) FROM fundamentals.financial_facts),
	  COALESCE((SELECT max(trade_date)::text FROM market.price_observations), ''),
	  COALESCE((SELECT max(collected_at)::text FROM market.price_observations), ''),
	  (SELECT count(*) FROM market.price_observations),
	  COALESCE((SELECT max(as_of_date)::text FROM core.share_structure), ''),
	  COALESCE((SELECT greatest((SELECT max(collected_at) FROM core.share_structure),
	                            (SELECT max(collected_at) FROM market.tsetmc_current_shares))::text), ''),
	  (SELECT (SELECT count(*) FROM core.share_structure)
	        + (SELECT count(*) FROM market.tsetmc_current_shares)),
	  COALESCE((SELECT greatest(max(created_at), max(updated_at))::text FROM ingestion.reports), ''),
	  (SELECT count(*) FROM ingestion.reports)`

func (p *PG) currentCheapWatermark(ctx context.Context) (InputWatermark, error) {
	var monthlyDate, monthlyArr string
	var monthlyRows int64
	var finDate, finArr string
	var finRows int64
	var mktDate, mktArr string
	var mktRows int64
	var shrDate, shrArr string
	var shrRows int64
	var repArr string
	var repRows int64
	err := p.db.QueryRowContext(ctx, cheapWatermarkSQL).Scan(
		&monthlyDate, &monthlyArr, &monthlyRows,
		&finDate, &finArr, &finRows,
		&mktDate, &mktArr, &mktRows,
		&shrDate, &shrArr, &shrRows,
		&repArr, &repRows,
	)
	if err != nil {
		return InputWatermark{}, err
	}
	return InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly":   {Date: monthlyDate, Arrival: monthlyArr, Rows: &monthlyRows},
		"financial": {Date: finDate, Arrival: finArr, Rows: &finRows},
		"market":    {Date: mktDate, Arrival: mktArr, Rows: &mktRows},
		"shares":    {Date: shrDate, Arrival: shrArr, Rows: &shrRows},
		"reports":   {Date: "", Arrival: repArr, Rows: &repRows},
	}}, nil
}

// stalenessFromWatermark reports whether the inputs that exist now differ from the
// fingerprint the run recorded. Conservative by design: a run whose watermark was
// never recorded (pre-migration) is reported stale rather than silently fresh — the
// exact failure that let /api/health/shadow print score_stale=false for a stale score.
func stalenessFromWatermark(runWM string, current InputWatermark) (bool, []string) {
	trimmed := strings.TrimSpace(runWM)
	if trimmed == "" || trimmed == "{}" {
		return true, []string{"run predates input watermarking"}
	}
	var prev InputWatermark
	if err := json.Unmarshal([]byte(trimmed), &prev); err != nil {
		return true, []string{"run input watermark unreadable"}
	}
	if len(prev.Domains) == 0 {
		return true, []string{"run input watermark empty"}
	}
	var reasons []string
	for _, key := range []string{"monthly", "financial", "market", "shares", "reports"} {
		cur, ok := current.Domains[key]
		if !ok {
			continue
		}
		p, ok := prev.Domains[key]
		if !ok {
			reasons = append(reasons, key+": missing from run watermark")
			continue
		}
		if p.Rows != nil && cur.Rows != nil && *p.Rows != *cur.Rows {
			reasons = append(reasons, fmt.Sprintf("%s: rows %d -> %d", key, *p.Rows, *cur.Rows))
		}
		if timeAfter(cur.Arrival, p.Arrival) {
			reasons = append(reasons, key+": new arrival")
		}
		if timeAfter(cur.Date, p.Date) {
			reasons = append(reasons, key+": data date advanced")
		}
	}
	return len(reasons) > 0, reasons
}

// timeAfter reports whether a is strictly later than b, parsing PG-style timestamp or
// date text. Unparseable/empty values are "not after" (never fabricate staleness from
// a parse failure).
func timeAfter(a, b string) bool {
	ta, err := parsePGTime(a)
	if err != nil {
		return false
	}
	tb, err := parsePGTime(b)
	if err != nil {
		return false
	}
	return ta.After(tb)
}
