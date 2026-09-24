-- ============================================================================
-- 080_analytics.sql  —  score runs, company/factor scores, metric snapshots
-- DO NOT EXECUTE in this phase.
--
-- All derived metrics (TTM, growth, margins, ROE, ratios, P/E, P/S, momentum,
-- volatility, QuantScore, DataQualityScore) live HERE, never in raw/fundamentals.
-- Everything is versioned (score_version / calculation_version) and reproducible.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- analytics.score_runs
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.score_runs (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    score_version text       NOT NULL,                -- e.g. 'v3.7'
    as_of_date   date        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    code_version text,                                -- git commit / release tag
    parameters   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status       text        NOT NULL DEFAULT 'running',
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT score_runs_status_chk CHECK (status IN ('running','completed','failed','partial'))
);

CREATE INDEX ix_score_runs_version_date ON analytics.score_runs (score_version, as_of_date DESC);

-- ----------------------------------------------------------------------------
-- analytics.company_scores
-- Business key: (run_id, company_id) unique.
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.company_scores (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              uuid        NOT NULL REFERENCES analytics.score_runs(id) ON DELETE CASCADE,
    company_id          uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    primary_security_id uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    quant_score         numeric(12,4),
    data_quality_score  numeric(12,4),
    growth_score        numeric(12,4),
    profitability_score numeric(12,4),
    valuation_score     numeric(12,4),
    market_score        numeric(12,4),
    -- v1.1 CHANGE (item 15): score_version removed here. It is owned by
    -- analytics.score_runs and obtained via run_id (no denormalized copy that
    -- could drift). Company_scores always belongs to exactly one run.
    input_hash          text,
    details             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- v1.1 (item 5): the primary security, if present, must belong to company_id.
    CONSTRAINT company_scores_security_company_fk FOREIGN KEY (primary_security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_company_scores_run_company ON analytics.company_scores (run_id, company_id);
CREATE INDEX ix_company_scores_company ON analytics.company_scores (company_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- analytics.factor_scores
-- Per-factor transparency so v3.7 factors can be reproduced and audited.
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.factor_scores (
    id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         uuid        NOT NULL REFERENCES analytics.score_runs(id) ON DELETE CASCADE,
    company_id     uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    factor_code    text        NOT NULL,              -- 'SalesGrowth12MRank', 'PERank', 'ROE', ...
    raw_value      numeric(24,6),
    percentile     numeric(9,6),
    weighted_score numeric(24,6),
    weight         numeric(12,4),
    metadata       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_factor_scores_run_company_factor
    ON analytics.factor_scores (run_id, company_id, factor_code);
CREATE INDEX ix_factor_scores_factor ON analytics.factor_scores (factor_code);

-- ----------------------------------------------------------------------------
-- analytics.metric_snapshots
-- Point-in-time derived metrics for backtesting. Look-ahead safety:
--   as_of_date      = the date the value is considered "known"
--   source_cutoff_at = the ingestion timestamp cutoff used (no data collected
--                      after this instant may influence the value)
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.metric_snapshots (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    as_of_date          date        NOT NULL,
    company_id          uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    primary_security_id uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    metric_code         text        NOT NULL,
    value               numeric(30,6),
    unit                text,
    calculation_version text        NOT NULL,         -- e.g. 'v3.7' (owned here: no run link)
    source_cutoff_at    timestamptz NOT NULL,
    details             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- v1.1 (item 5): primary security, if present, must belong to company_id.
    CONSTRAINT metric_snapshots_security_company_fk FOREIGN KEY (primary_security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_metric_snapshots_key
    ON analytics.metric_snapshots (as_of_date, company_id, metric_code, calculation_version);
CREATE INDEX ix_metric_snapshots_metric ON analytics.metric_snapshots (metric_code, as_of_date DESC);
