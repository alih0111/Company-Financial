-- ============================================================================
-- 030_raw.sql  —  raw report payloads (immutable)
-- DO NOT EXECUTE in this phase.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- raw.report_payloads
-- Preserves the original Codal report content so a future parser can reprocess
-- WITHOUT re-downloading. Append-only / immutable.
--
-- Storage guidance (see schema.md "RAW storage sizing"):
--   * In-database is appropriate for typical Codal HTML pages (tens to a few
--     hundred KB) and JSON payloads.
--   * When a single payload routinely exceeds ~1-2 MB or total RAW volume grows
--     into the tens of GB, externalize the bytes to object storage and keep only
--     storage_uri + content_hash + metadata in PostgreSQL.
--   * content_json is for structured metadata/snapshots (small). Large HTML/XBRL
--     should prefer content_text (medium) or storage_uri (large).
-- ----------------------------------------------------------------------------
CREATE TABLE raw.report_payloads (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_version_id uuid        NOT NULL REFERENCES ingestion.report_versions(id) ON DELETE CASCADE,
    payload_type      text        NOT NULL,
    content_hash      text        NOT NULL,
    content_text      text,
    content_json      jsonb,
    storage_uri       text,
    mime_type         text,
    byte_size         bigint,
    collected_at      timestamptz NOT NULL DEFAULT now(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT report_payloads_type_chk CHECK (payload_type IN
        ('html','json','xbrl','excel_meta','parser_snapshot')),
    CONSTRAINT report_payloads_at_least_one_source CHECK (
        num_nonnulls(content_text, content_json, storage_uri) >= 1),
    CONSTRAINT report_payloads_byte_size_chk CHECK (byte_size IS NULL OR byte_size >= 0)
);

CREATE INDEX ix_report_payloads_version ON raw.report_payloads (report_version_id, payload_type);
CREATE UNIQUE INDEX uq_report_payloads_hash
    ON raw.report_payloads (report_version_id, payload_type, content_hash);

COMMENT ON TABLE raw.report_payloads IS
    'Immutable raw report content. At least one of content_text/content_json/storage_uri required.';

-- Immutability guard: block UPDATE/DELETE of raw payload bytes.
-- (Migration/repair can be done by a superuser by disabling the trigger.)
CREATE OR REPLACE FUNCTION raw.prevent_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'raw.report_payloads is append-only (attempted %)', TG_OP;
END;
$$;

CREATE TRIGGER trg_report_payloads_immutable
    BEFORE UPDATE OR DELETE ON raw.report_payloads
    FOR EACH ROW EXECUTE FUNCTION raw.prevent_mutation();
