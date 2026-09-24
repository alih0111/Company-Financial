-- ============================================================================
-- 080_analytics.sql  —  score runs, company/factor scores, metric snapshots
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- All derived metrics live here. Everything versioned and reproducible.
-- v1.2: score_runs carries source_cutoff_at; outputs are immutable;
-- security FKs use a single policy (composite RESTRICT).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- analytics.score_runs
-- Lifecycle-mutable (running -> completed/failed/partial); identity frozen.
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.score_runs (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    score_version   text        NOT NULL,
    as_of_date      date        NOT NULL,
    -- v1.2 (item 7): no input collected after this instant may influence the run.
    source_cutoff_at timestamptz NOT NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    code_version    text,
    parameters      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'running',
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT score_runs_status_chk CHECK (status IN ('running','completed','failed','partial'))
);

CREATE INDEX ix_score_runs_version_date ON analytics.score_runs (score_version, as_of_date DESC);
CREATE INDEX ix_score_runs_cutoff       ON analytics.score_runs (source_cutoff_at);

CREATE OR REPLACE FUNCTION analytics.protect_score_run_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.score_version    IS DISTINCT FROM OLD.score_version
       OR NEW.as_of_date     IS DISTINCT FROM OLD.as_of_date
       OR NEW.source_cutoff_at IS DISTINCT FROM OLD.source_cutoff_at
       OR NEW.started_at     IS DISTINCT FROM OLD.started_at
       OR NEW.code_version   IS DISTINCT FROM OLD.code_version
       OR NEW.parameters     IS DISTINCT FROM OLD.parameters THEN
        RAISE EXCEPTION 'analytics.score_runs identity is immutable; only lifecycle columns may change';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_score_runs_identity
    BEFORE UPDATE ON analytics.score_runs
    FOR EACH ROW EXECUTE FUNCTION analytics.protect_score_run_identity();

-- v1.2.1 (item 5): terminal state machine (running -> completed|failed|partial).
CREATE OR REPLACE FUNCTION analytics.enforce_score_run_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status <> 'running' THEN
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'score_run % is terminal (%); status cannot change', OLD.id, OLD.status;
        END IF;
    END IF;
    IF NEW.status = 'running' AND NEW.completed_at IS NOT NULL THEN
        RAISE EXCEPTION 'running score_run must have completed_at NULL';
    END IF;
    IF NEW.status <> 'running' AND NEW.completed_at IS NULL THEN
        RAISE EXCEPTION 'terminal score_run (%) must have completed_at set', NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_score_runs_lifecycle
    BEFORE UPDATE ON analytics.score_runs
    FOR EACH ROW EXECUTE FUNCTION analytics.enforce_score_run_lifecycle();

-- ----------------------------------------------------------------------------
-- analytics.company_scores   (immutable output)
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.company_scores (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              uuid        NOT NULL REFERENCES analytics.score_runs(id) ON DELETE CASCADE,
    company_id          uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    primary_security_id uuid,
    quant_score         numeric(12,4),
    data_quality_score  numeric(12,4),
    growth_score        numeric(12,4),
    profitability_score numeric(12,4),
    valuation_score     numeric(12,4),
    market_score        numeric(12,4),
    input_hash          text,
    details             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- v1.2 (item 8): single policy -- composite RESTRICT (no conflicting SET NULL).
    CONSTRAINT company_scores_security_company_fk FOREIGN KEY (primary_security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_company_scores_run_company ON analytics.company_scores (run_id, company_id);
CREATE INDEX ix_company_scores_company ON analytics.company_scores (company_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- analytics.factor_scores   (immutable output)
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.factor_scores (
    id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         uuid        NOT NULL REFERENCES analytics.score_runs(id) ON DELETE CASCADE,
    company_id     uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    factor_code    text        NOT NULL,
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
-- analytics.metric_snapshots   (immutable output; point-in-time)
-- ----------------------------------------------------------------------------
CREATE TABLE analytics.metric_snapshots (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    as_of_date          date        NOT NULL,
    company_id          uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    primary_security_id uuid,
    metric_code         text        NOT NULL,
    value               numeric(30,6),
    unit                text,
    calculation_version text        NOT NULL,
    source_cutoff_at    timestamptz NOT NULL,
    details             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- v1.2 (item 8): single policy -- composite RESTRICT.
    CONSTRAINT metric_snapshots_security_company_fk FOREIGN KEY (primary_security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_metric_snapshots_key
    ON analytics.metric_snapshots (as_of_date, company_id, metric_code, calculation_version);
CREATE INDEX ix_metric_snapshots_metric ON analytics.metric_snapshots (metric_code, as_of_date DESC);

-- ----------------------------------------------------------------------------
-- v1.2 (item 18): analytics outputs are immutable.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.prevent_output_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'analytics.% is append-only (attempted %)', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TRIGGER trg_company_scores_immutable
    BEFORE UPDATE OR DELETE ON analytics.company_scores
    FOR EACH ROW EXECUTE FUNCTION analytics.prevent_output_mutation();

CREATE TRIGGER trg_factor_scores_immutable
    BEFORE UPDATE OR DELETE ON analytics.factor_scores
    FOR EACH ROW EXECUTE FUNCTION analytics.prevent_output_mutation();

CREATE TRIGGER trg_metric_snapshots_immutable
    BEFORE UPDATE OR DELETE ON analytics.metric_snapshots
    FOR EACH ROW EXECUTE FUNCTION analytics.prevent_output_mutation();
