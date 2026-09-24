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
    security_id       uuid,
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
    -- v1.1 CHANGE (item 3): an official Codal corrective report is a DISTINCT
    -- report (its own TracingNo/source_report_id). Report B supersedes Report A.
    -- Different from report_versions (which are fetch/parse snapshots of the SAME
    -- source report). Self-referencing, history-preserving.
    supersedes_report_id uuid      REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reports_status_chk CHECK (processing_status IN
        ('discovered','processing','completed','failed','unsupported')),
    CONSTRAINT reports_retry_nonneg CHECK (retry_count >= 0),
    CONSTRAINT reports_fiscal_month_chk CHECK (fiscal_month IS NULL OR (fiscal_month BETWEEN 1 AND 12)),
    CONSTRAINT reports_no_self_supersede CHECK (supersedes_report_id IS NULL OR supersedes_report_id <> id),
    -- v1.1 (item 5): if security_id is present it must belong to company_id.
    CONSTRAINT reports_security_company_fk FOREIGN KEY (security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

-- Uniqueness of a source report per source (TracingNo is unique for Codal).
CREATE UNIQUE INDEX uq_reports_source_report_id
    ON ingestion.reports (source, source_report_id);
CREATE INDEX ix_reports_company_period   ON ingestion.reports (company_id, period_end_date DESC);
CREATE INDEX ix_reports_company_type_ts  ON ingestion.reports (company_id, report_type, published_at DESC);
CREATE INDEX ix_reports_status           ON ingestion.reports (processing_status);
CREATE INDEX ix_reports_security         ON ingestion.reports (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX ix_reports_supersedes       ON ingestion.reports (supersedes_report_id) WHERE supersedes_report_id IS NOT NULL;

CREATE TRIGGER trg_reports_updated_at
    BEFORE UPDATE ON ingestion.reports
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE ingestion.reports IS
    'Codal report registry. Idempotent by (source, source_report_id); retry via status/retry_count.';

-- ----------------------------------------------------------------------------
-- ingestion.report_versions
-- Append-only. A corrective/new fetch/parse of the SAME source report never
-- overwrites the prior version.
--
-- v1.1 CHANGE (item 2): `is_current` was removed. A mutable current-pointer
-- column contradicts append-only (it requires UPDATE of the previous row).
-- "Current" is derived: the row with the greatest version_no (ties broken by
-- collected_at). See view ingestion.current_report_versions below.
--
-- Race-safe version_no allocation:
--   * version_no is assigned inside a transaction as
--        COALESCE(MAX(version_no), 0) + 1  for the target report_id
--     under a row lock on the parent report:
--        SELECT ... FROM ingestion.reports WHERE id = :report_id FOR UPDATE;
--   * The UNIQUE(report_id, version_no) is the final guard against races.
--   * Alternatively use a per-report sequence keyed by report_id if hot spots.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.report_versions (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id      uuid        NOT NULL REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    version_no     integer     NOT NULL,
    content_hash   text        NOT NULL,
    source_url     text,
    collected_at   timestamptz NOT NULL DEFAULT now(),
    parser_version text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_versions_no_chk CHECK (version_no >= 1)
);

CREATE UNIQUE INDEX uq_report_versions_no   ON ingestion.report_versions (report_id, version_no);
CREATE UNIQUE INDEX uq_report_versions_hash ON ingestion.report_versions (report_id, content_hash);
CREATE INDEX ix_report_versions_report_time ON ingestion.report_versions (report_id, version_no DESC, collected_at DESC);

-- v1.1 CHANGE (item 1): composite key so normalized outputs can enforce that
-- their report_version truly belongs to the stated report_id (composite FK).
ALTER TABLE ingestion.report_versions
    ADD CONSTRAINT report_versions_id_report_key UNIQUE (id, report_id);

COMMENT ON TABLE ingestion.report_versions IS
    'Append-only fetch/parse versions of the same source report. Current = max(version_no).';

-- Derived "current" view (no mutable state on the table).
CREATE OR REPLACE VIEW ingestion.current_report_versions AS
SELECT DISTINCT ON (report_id)
       report_id, id AS report_version_id, version_no, content_hash,
       source_url, collected_at, parser_version
FROM ingestion.report_versions
ORDER BY report_id, version_no DESC, collected_at DESC;

COMMENT ON VIEW ingestion.current_report_versions IS
    'Derived current version per report = greatest version_no (tie: latest collected_at).';

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
