-- ============================================================================
-- 090_indexes.sql  —  cross-cutting / covering / partial / GIN indexes
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- Table-local PK/FK/UQ and primary access-path indexes are declared inline in
-- 010..080. This file adds only cross-cutting indexes for named query patterns
-- and JSONB GIN indexes. market.daily_prices is a VIEW in v1.2, so its access
-- paths are indexed on market.price_observations.
-- ============================================================================

-- (1) Latest report per company (completed only)
CREATE INDEX ix_reports_completed_company_period
    ON ingestion.reports (company_id, period_end_date DESC)
    WHERE processing_status = 'completed';

-- (3)(4) facts by statement / metric
CREATE INDEX ix_financial_facts_metric_statement
    ON fundamentals.financial_facts (metric_code, statement_id);

-- Parse-run lookup by parser identity (reproducibility/audit)
CREATE INDEX ix_parse_runs_parser
    ON ingestion.parse_runs (parser_name, parser_version, started_at DESC);

-- (5)(6) Latest price covering index.
-- v1.2.1: point-in-time cutoff index (ix_price_observations_cutoff) is declared
-- table-local in 050_market.sql ONLY. Do not redefine it here (duplicate-object
-- blocker fixed).
CREATE INDEX ix_price_observations_latest_covering
    ON market.price_observations (security_id, trade_date DESC, collected_at DESC)
    INCLUDE (closing_price_rial, last_price_rial, adjustment_version);

-- (7) Latest score
CREATE INDEX ix_score_runs_version_date_desc
    ON analytics.score_runs (score_version, as_of_date DESC)
    WHERE status = 'completed';
CREATE INDEX ix_company_scores_company_run
    ON analytics.company_scores (company_id, run_id DESC);

-- (8) Historical score / backtest
CREATE INDEX ix_metric_snapshots_company_metric_date
    ON analytics.metric_snapshots (company_id, metric_code, as_of_date DESC);

-- (10) Transaction ledger (ascending by effective date)
CREATE INDEX ix_transactions_portfolio_effective_asc
    ON portfolio.transactions (portfolio_id, effective_date, created_at);

-- Case-insensitive security/company lookups
CREATE INDEX ix_securities_codal_symbol_lower
    ON core.securities (lower(codal_symbol)) WHERE codal_symbol IS NOT NULL;
CREATE INDEX ix_companies_normalized_name_lower
    ON core.companies (lower(normalized_name));

-- JSONB GIN indexes (only where key filtering is expected)
CREATE INDEX ix_runs_metadata_gin
    ON ingestion.runs USING gin (metadata jsonb_path_ops);
CREATE INDEX ix_dq_details_gin
    ON ingestion.data_quality_issues USING gin (details jsonb_path_ops);
CREATE INDEX ix_company_scores_details_gin
    ON analytics.company_scores USING gin (details jsonb_path_ops);
