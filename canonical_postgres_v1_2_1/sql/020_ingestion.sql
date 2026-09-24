-- ============================================================================
-- 020_ingestion.sql  —  Codal registry, FETCH versions, PARSE runs, sync, tracked, DQ
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- v1.2 key change (item 1): fetch/content version and parser execution are
-- separated:
--   ingestion.report_versions = content/fetch versions only (no parser_version)
--   ingestion.parse_runs      = parser executions (N per report_version)
--   normalized outputs attach to parse_run_id.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ingestion.reports  (canonical registry; replaces dbo.CodalReports)
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.reports (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    security_id       uuid,
    source            text        NOT NULL DEFAULT 'codal',
    source_report_id  text        NOT NULL,            -- Codal TracingNo (as text)
    tracing_no        bigint,
    letter_type       integer,
    report_type       text,
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
    -- v1.1: official Codal corrective report (distinct TracingNo) supersedes A.
    supersedes_report_id uuid      REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reports_status_chk CHECK (processing_status IN
        ('discovered','processing','completed','failed','unsupported')),
    CONSTRAINT reports_retry_nonneg CHECK (retry_count >= 0),
    CONSTRAINT reports_fiscal_month_chk CHECK (fiscal_month IS NULL OR (fiscal_month BETWEEN 1 AND 12)),
    CONSTRAINT reports_no_self_supersede CHECK (supersedes_report_id IS NULL OR supersedes_report_id <> id),
    CONSTRAINT reports_security_company_fk FOREIGN KEY (security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT,
    -- v1.2.1 (item 3): referencable key so normalized rows can prove their
    -- company_id matches the parent report's company_id.
    CONSTRAINT reports_id_company_key UNIQUE (id, company_id)
);

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

-- v1.2 (item 5): forbid changing source identity after creation.
CREATE OR REPLACE FUNCTION ingestion.prevent_report_identity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.source IS DISTINCT FROM OLD.source
       OR NEW.source_report_id IS DISTINCT FROM OLD.source_report_id THEN
        RAISE EXCEPTION 'ingestion.reports source identity is immutable (source/source_report_id)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reports_identity_immutable
    BEFORE UPDATE ON ingestion.reports
    FOR EACH ROW EXECUTE FUNCTION ingestion.prevent_report_identity_change();

-- v1.2 (item 5): supersede cycle detection (self, 2-node, N-node).
CREATE OR REPLACE FUNCTION ingestion.check_supersede_cycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.supersedes_report_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.supersedes_report_id = NEW.id THEN
        RAISE EXCEPTION 'supersede cycle: report % cannot supersede itself', NEW.id;
    END IF;
    IF EXISTS (
        WITH RECURSIVE ancestors(id) AS (
            SELECT NEW.supersedes_report_id
            UNION ALL
            SELECT r.supersedes_report_id
            FROM ingestion.reports r
            JOIN ancestors a ON r.id = a.id
            WHERE r.supersedes_report_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'supersede cycle detected for report %', NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reports_supersede_cycle
    BEFORE INSERT OR UPDATE OF supersedes_report_id ON ingestion.reports
    FOR EACH ROW EXECUTE FUNCTION ingestion.check_supersede_cycle();

COMMENT ON TABLE ingestion.reports IS
    'Codal report registry. source identity immutable; supersede cycles blocked.';

-- ----------------------------------------------------------------------------
-- ingestion.report_versions  (FETCH/content versions ONLY; append-only)
-- v1.2 (item 1): parser_version removed. Current = max(version_no).
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.report_versions (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id      uuid        NOT NULL REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    version_no     integer     NOT NULL,
    content_hash   text        NOT NULL,
    source_url     text,
    collected_at   timestamptz NOT NULL DEFAULT now(),
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_versions_no_chk CHECK (version_no >= 1)
);

CREATE UNIQUE INDEX uq_report_versions_no   ON ingestion.report_versions (report_id, version_no);
-- Dedup policy: identical fetched content for a report is not stored twice.
CREATE UNIQUE INDEX uq_report_versions_hash ON ingestion.report_versions (report_id, content_hash);
CREATE INDEX ix_report_versions_report_time ON ingestion.report_versions (report_id, version_no DESC, collected_at DESC);

ALTER TABLE ingestion.report_versions
    ADD CONSTRAINT report_versions_id_report_key UNIQUE (id, report_id);

CREATE OR REPLACE VIEW ingestion.current_report_versions AS
SELECT DISTINCT ON (report_id)
       report_id, id AS report_version_id, version_no, content_hash,
       source_url, collected_at
FROM ingestion.report_versions
ORDER BY report_id, version_no DESC, collected_at DESC;

-- v1.2 (item 4): real immutability for fetch versions.
CREATE OR REPLACE FUNCTION ingestion.prevent_row_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'ingestion.% is append-only (attempted %)', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TRIGGER trg_report_versions_immutable
    BEFORE UPDATE OR DELETE ON ingestion.report_versions
    FOR EACH ROW EXECUTE FUNCTION ingestion.prevent_row_mutation();

COMMENT ON TABLE ingestion.report_versions IS
    'Append-only FETCH/content versions. No parser info; see ingestion.parse_runs.';

-- ----------------------------------------------------------------------------
-- ingestion.parse_runs  (parser executions over a report_version)
-- v1.2 (item 1): 1 report_version -> N parse_runs. Lifecycle-mutable only.
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.parse_runs (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_version_id uuid        NOT NULL REFERENCES ingestion.report_versions(id) ON DELETE RESTRICT,
    parser_name       text        NOT NULL,
    parser_version    text        NOT NULL,
    code_version      text,                            -- git commit/release
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'running',
    parameters        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    error_message     text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT parse_runs_status_chk CHECK (status IN ('running','completed','failed','unsupported')),
    CONSTRAINT parse_runs_finished_chk CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status <> 'running' AND finished_at IS NOT NULL))
);

-- At most one COMPLETED run per (content version, parser identity).
CREATE UNIQUE INDEX uq_parse_runs_completed
    ON ingestion.parse_runs (report_version_id, parser_name, parser_version)
    WHERE status = 'completed';
CREATE INDEX ix_parse_runs_version   ON ingestion.parse_runs (report_version_id, started_at DESC);
CREATE INDEX ix_parse_runs_status    ON ingestion.parse_runs (status);

-- Referencable pair for composite FKs from normalized outputs.
ALTER TABLE ingestion.parse_runs
    ADD CONSTRAINT parse_runs_id_report_version_key UNIQUE (id, report_version_id);

-- v1.2 (item 4): parse_runs may update lifecycle columns only; identity frozen.
CREATE OR REPLACE FUNCTION ingestion.protect_parse_run_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.report_version_id IS DISTINCT FROM OLD.report_version_id
       OR NEW.parser_name IS DISTINCT FROM OLD.parser_name
       OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
       OR NEW.code_version IS DISTINCT FROM OLD.code_version
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.parameters IS DISTINCT FROM OLD.parameters THEN
        RAISE EXCEPTION 'ingestion.parse_runs identity is immutable; only lifecycle columns may change';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_parse_runs_identity
    BEFORE UPDATE ON ingestion.parse_runs
    FOR EACH ROW EXECUTE FUNCTION ingestion.protect_parse_run_identity();

-- v1.2.1 (item 4): terminal state machine.
--   running -> completed | failed | unsupported
--   terminal states cannot transition again.
CREATE OR REPLACE FUNCTION ingestion.enforce_parse_run_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status <> 'running' THEN
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'parse_run % is in terminal state %; status cannot change', OLD.id, OLD.status;
        END IF;
    END IF;
    IF NEW.status = 'running' AND NEW.finished_at IS NOT NULL THEN
        RAISE EXCEPTION 'running parse_run must have finished_at NULL';
    END IF;
    IF NEW.status <> 'running' AND NEW.finished_at IS NULL THEN
        RAISE EXCEPTION 'terminal parse_run (%) must have finished_at set', NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_parse_runs_lifecycle
    BEFORE UPDATE ON ingestion.parse_runs
    FOR EACH ROW EXECUTE FUNCTION ingestion.enforce_parse_run_lifecycle();

COMMENT ON TABLE ingestion.parse_runs IS
    'Parser executions (N per report_version). Identity frozen; terminal status immutable.';

-- ----------------------------------------------------------------------------
-- ingestion.sync_state
-- ----------------------------------------------------------------------------
CREATE TABLE ingestion.sync_state (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source          text        NOT NULL,
    stream          text        NOT NULL,
    watermark       timestamptz,
    last_success_at timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_sync_state_source_stream ON ingestion.sync_state (source, stream);

CREATE TRIGGER trg_sync_state_updated_at
    BEFORE UPDATE ON ingestion.sync_state
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- ingestion.tracked_securities
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
