-- ============================================================================
-- 090_indexes.sql  —  cross-cutting / covering / partial / GIN indexes
-- DO NOT EXECUTE in this phase.
--
-- NOTE: table-local PK/FK/UQ and the primary access-path indexes are declared
-- inline in their respective files (010..080). This file adds only the indexes
-- required by the named query patterns that are NOT already covered, plus GIN
-- indexes for JSONB filtering. Every index below states its query pattern.
-- ============================================================================

-- (1) Latest report per company ---------------------------------------------
-- Covered inline by ix_reports_company_period. Add a partial variant restricted
-- to completed reports (the only ones used for analytics), which is smaller.
CREATE INDEX ix_reports_completed_company_period
    ON ingestion.reports (company_id, period_end_date DESC)
    WHERE processing_status = 'completed';

-- (2) Reports of a company in a time range ----------------------------------
-- Covered inline by ix_reports_company_type_ts (company_id, report_type,
-- published_at DESC). No extra index needed.

-- (3) All financial facts of a statement ------------------------------------
-- Covered inline by ix_financial_facts_statement (statement_id).

-- (4) Lookup by metric_code --------------------------------------------------
-- Covered inline by ix_financial_facts_metric_lookup (metric_code).
-- Add a composite to serve "metric across companies for a period" (analytics).
CREATE INDEX ix_financial_facts_metric_statement
    ON fundamentals.financial_facts (metric_code, statement_id);

-- (5) Latest price of a security --------------------------------------------
-- Covered inline by ix_daily_prices_security (security_id, trade_date DESC).
-- Add a covering index so "latest close/last price" needs no heap fetch.
CREATE INDEX ix_daily_prices_latest_covering
    ON market.daily_prices (security_id, trade_date DESC)
    INCLUDE (closing_price_rial, last_price_rial, is_adjusted);

-- (6) Price history by security/date ----------------------------------------
-- Covered inline by ix_daily_prices_security. No extra index needed.

-- (7) Latest score ------------------------------------------------------------
CREATE INDEX ix_score_runs_version_date_desc
    ON analytics.score_runs (score_version, as_of_date DESC)
    WHERE status = 'completed';
CREATE INDEX ix_company_scores_company_run
    ON analytics.company_scores (company_id, run_id DESC);

-- (8) Historical score / backtest -------------------------------------------
CREATE INDEX ix_metric_snapshots_company_metric_date
    ON analytics.metric_snapshots (company_id, metric_code, as_of_date DESC);

-- (9) Current portfolio position --------------------------------------------
-- Covered inline by positions_pk (portfolio_id, asset_id) after the v1.1
-- unified-asset change (item 7/10).

-- (10) Transaction ledger --------------------------------------------------
-- Covered inline by ix_transactions_portfolio_date. Add a partial index for the
-- common "ledger for one portfolio ordered by time" with reversal filtering.
CREATE INDEX ix_transactions_portfolio_date_asc
    ON portfolio.transactions (portfolio_id, trade_date, created_at);

-- Case-insensitive security symbol lookup -----------------------------------
-- Exact index exists; add functional for lower(codal_symbol) lookups.
CREATE INDEX ix_securities_codal_symbol_lower
    ON core.securities (lower(codal_symbol)) WHERE codal_symbol IS NOT NULL;

CREATE INDEX ix_companies_normalized_name_lower
    ON core.companies (lower(normalized_name));

-- JSONB GIN indexes (only where JSONB filtering is expected) -----------------
CREATE INDEX ix_runs_metadata_gin
    ON ingestion.runs USING gin (metadata jsonb_path_ops);
CREATE INDEX ix_dq_details_gin
    ON ingestion.data_quality_issues USING gin (details jsonb_path_ops);
CREATE INDEX ix_company_scores_details_gin
    ON analytics.company_scores USING gin (details jsonb_path_ops);

-- ----------------------------------------------------------------------------
-- Rationale summary (avoiding over-indexing):
--   * High-write append-only tables (raw.report_payloads, financial_facts,
--     transactions, daily_prices) keep only the indexes needed by read paths
--     above; no speculative indexes.
--   * JSONB GIN indexes are limited to three tables that are actually queried
--     by key; add more only when a concrete query requires it.
--   * All partial indexes encode a real predicate used in application queries.
-- ----------------------------------------------------------------------------
