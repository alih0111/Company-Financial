-- ============================================================================
-- 130_score_v4.sql — v4 score columns on analytics.company_scores
--
-- Design:
--   * additive-only: every column is nullable, no existing column changes, no
--     row is touched. The append-only/mutation triggers are unaffected (they
--     block UPDATE/DELETE, not INSERT).
--   * idempotent: ADD COLUMN IF NOT EXISTS — safe to re-run.
--   * v3 runs keep NULL in the v4 columns; v4 runs fill both the v4 columns
--     and the legacy columns (quant_score = v4 score, data_quality_score =
--     confidence/100, growth/quality/valuation/market mapped to the legacy
--     category columns; financial_strength lives only in score_breakdown).
-- Rollback: DROP COLUMN list at the bottom (kept commented).
-- ============================================================================

ALTER TABLE analytics.company_scores
    ADD COLUMN IF NOT EXISTS score               numeric(12,4),
    ADD COLUMN IF NOT EXISTS confidence          numeric(12,4),
    ADD COLUMN IF NOT EXISTS adjusted_score      numeric(12,4),
    ADD COLUMN IF NOT EXISTS score_model         text,
    ADD COLUMN IF NOT EXISTS market_percentile   numeric(9,6),
    ADD COLUMN IF NOT EXISTS sector_percentile   numeric(9,6),
    ADD COLUMN IF NOT EXISTS penalties_total     numeric(12,4),
    ADD COLUMN IF NOT EXISTS score_breakdown     jsonb,
    ADD COLUMN IF NOT EXISTS confidence_breakdown jsonb,
    ADD COLUMN IF NOT EXISTS penalties_breakdown jsonb;

-- Latest v4 run per company (read helper for API/ops).
CREATE OR REPLACE VIEW analytics.v_company_scores_v4 AS
SELECT DISTINCT ON (cs.company_id)
       cs.company_id,
       cs.primary_security_id,
       cs.score, cs.confidence, cs.adjusted_score, cs.score_model,
       cs.market_percentile, cs.sector_percentile, cs.penalties_total,
       cs.score_breakdown, cs.confidence_breakdown, cs.penalties_breakdown,
       cs.quant_score,
       sr.as_of_date, sr.source_cutoff_at, sr.completed_at
FROM analytics.company_scores cs
JOIN analytics.score_runs sr ON sr.id = cs.run_id
WHERE sr.score_version = 'v4' AND sr.status = 'completed'
ORDER BY cs.company_id, sr.as_of_date DESC, sr.started_at DESC;

-- Rollback (only if ever needed; v4 rows become unreadable, v3 rows untouched):
-- DROP VIEW IF EXISTS analytics.v_company_scores_v4;
-- ALTER TABLE analytics.company_scores
--     DROP COLUMN IF EXISTS score, DROP COLUMN IF EXISTS confidence,
--     DROP COLUMN IF EXISTS adjusted_score, DROP COLUMN IF EXISTS score_model,
--     DROP COLUMN IF EXISTS market_percentile, DROP COLUMN IF EXISTS sector_percentile,
--     DROP COLUMN IF EXISTS penalties_total, DROP COLUMN IF EXISTS score_breakdown,
--     DROP COLUMN IF EXISTS confidence_breakdown, DROP COLUMN IF EXISTS penalties_breakdown;
