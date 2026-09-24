-- ============================================================================
-- 020_ingestion.sql  —  Codal registry, versions, sync state, tracked, runs, DQ
-- DO NOT EXECUTE in this phase.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ingestion.reports
-- Canonical registry of Codal reports (replaces dbo.CodalReports).
-- Idempotent status/retry design.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.reports (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    security_id       uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    source            text        NOT NULL DEFAULT 'codal',
    source_report_id  text        NOT NULL,            -- Codal TracingNo (as text)
    tracing_no        bigint,                          -- numeric form
    letter_type       integer,
    report_type       text,                            -- 'financial' | 'monthly' | ...
    title             text,
    period_end_date   date,
    jalali_period_text text,
    fiscal_year       integer,
    fiscal_month      integer,
    published_at      timestamptz,
    source_url        text,
    discovered_at     timestamptz NOT NULL DEFAULT now(),
    processed_at      timestamptz,
    processing_status text        NOT NULL DEFAULT 'discovered',
    retry_count       integer     NOT NULL DEFAULT 0,
    error_message     text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reports_status_chk CHECK (processing_status IN
        ('discovered','processing','completed','failed','unsupported')),
    CONSTRAINT reports_retry_nonneg CHECK (retry_count >= 0),
    CONSTRAINT reports_fiscal_month_chk CHECK (fiscal_month IS NULL OR (fiscal_month BETWEEN 1 AND 12))
);

-- Uniqueness of a source report per source (TracingNo is unique for Codal).
CREATE UNIQUE INDEX uq_reports_source_report_id
    ON ingestion.reports (source, source_report_id);
CREATE INDEX ix_reports_company_period   ON ingestion.reports (company_id, period_end_date DESC);
CREATE INDEX ix_reports_company_type_ts  ON ingestion.reports (company_id, report_type, published_at DESC);
CREATE INDEX ix_reports_status           ON ingestion.reports (processing_status);
CREATE INDEX ix_reports_security         ON ingestion.reports (security_id) WHERE security_id IS NOT NULL;

CREATE TRIGGER trg_reports_updated_at
    BEFORE UPDATE ON ingestion.reports
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE ingestion.reports IS
    'Codal report registry. Idempotent by (source, source_report_id); retry via status/retry_count.';

-- ----------------------------------------------------------------------------
-- ingestion.report_versions
-- Append-only. A corrective/new report never overwrites the prior version.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.report_versions (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id      uuid        NOT NULL REFERENCES ingestion.reports(id) ON DELETE CASCADE,
    version_no     integer     NOT NULL,
    content_hash   text        NOT NULL,
    source_url     text,
    collected_at   timestamptz NOT NULL DEFAULT now(),
    parser_version text,
    is_current     boolean     NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_versions_no_chk CHECK (version_no >= 1)
);

CREATE UNIQUE INDEX uq_report_versions_no      ON ingestion.report_versions (report_id, version_no);
CREATE UNIQUE INDEX uq_report_versions_hash    ON ingestion.report_versions (report_id, content_hash);
CREATE UNIQUE INDEX uq_report_versions_current ON ingestion.report_versions (report_id) WHERE is_current;

COMMENT ON TABLE ingestion.report_versions IS
    'Append-only report versions. Exactly one is_current row per report (partial unique).';

-- ----------------------------------------------------------------------------
-- ingestion.sync_state
-- Generic watermark store (replaces dbo.CodalSyncState, not hardcoded to LetterType).
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.sync_state (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source          text        NOT NULL,
    stream          text        NOT NULL,             -- e.g. 'letter_type:6', 'letter_type:58', 'prices:daily'
    watermark       timestamptz,
    last_success_at timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_sync_state_source_stream ON ingestion.sync_state (source, stream);

CREATE TRIGGER trg_sync_state_updated_at
    BEFORE UPDATE ON ingestion.sync_state
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE ingestion.sync_state IS
    'Generic incremental watermark per (source, stream).';

-- ----------------------------------------------------------------------------
-- ingestion.tracked_securities
-- Replaces dbo.TrackedTickers. Keyed by security_id, never by raw symbol string.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.tracked_securities (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id uuid        NOT NULL REFERENCES core.securities(id) ON DELETE CASCADE,
    source      text,
    reason      text,
    is_active   boolean     NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_tracked_securities ON ingestion.tracked_securities (security_id);
CREATE INDEX ix_tracked_active ON ingestion.tracked_securities (is_active) WHERE is_active;

CREATE TRIGGER trg_tracked_securities_updated_at
    BEFORE UPDATE ON ingestion.tracked_securities
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- ingestion.runs
-- Observability registry for ingestion/analytics jobs.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.runs (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source         text        NOT NULL,
    job_type       text        NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text        NOT NULL DEFAULT 'running',
    items_seen     integer     NOT NULL DEFAULT 0,
    items_inserted integer     NOT NULL DEFAULT 0,
    items_updated  integer     NOT NULL DEFAULT 0,
    items_failed   integer     NOT NULL DEFAULT 0,
    metadata       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT runs_status_chk CHECK (status IN ('running','completed','failed','partial','cancelled')),
    CONSTRAINT runs_counts_nonneg CHECK (
        items_seen >= 0 AND items_inserted >= 0 AND items_updated >= 0 AND items_failed >= 0)
);

CREATE INDEX ix_runs_source_job_started ON ingestion.runs (source, job_type, started_at DESC);

-- ----------------------------------------------------------------------------
-- ingestion.data_quality_issues
-- First-class DQ registry (replaces ad-hoc flags).
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.data_quality_issues (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type text        NOT NULL,
    entity_id   uuid,
    issue_code  text        NOT NULL,
    severity    text        NOT NULL,
    detected_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    details     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT dq_severity_chk CHECK (severity IN ('low','medium','high','critical')),
    CONSTRAINT dq_issue_code_chk CHECK (issue_code IN (
        'unknown_unit','identity_conflict','invalid_date','stale_data',
        'duplicate_report','parser_failure','missing_relation','orphan_record','other'))
);

CREATE INDEX ix_dq_entity   ON ingestion.data_quality_issues (entity_type, entity_id);
CREATE INDEX ix_dq_severity ON ingestion.data_quality_issues (severity, detected_at DESC);
CREATE INDEX ix_dq_open     ON ingestion.data_quality_issues (issue_code) WHERE resolved_at IS NULL;
