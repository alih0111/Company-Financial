-- ============================================================================
-- 010_core.sql  —  core domain: companies, securities, aliases, legacy map
-- DO NOT EXECUTE in this phase.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- core.companies
-- The legal entity / issuer. Identity is an internal UUID, independent of name
-- and independent of any tradable symbol.
-- ----------------------------------------------------------------------------
CREATE TABLE core.companies (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name      text,                          -- full registered legal name (may be absent)
    display_name    text        NOT NULL,          -- human-facing name used in UI
    normalized_name text        NOT NULL,          -- normalized/trimmed comparison key
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT companies_display_name_not_blank CHECK (length(btrim(display_name)) > 0),
    CONSTRAINT companies_normalized_name_not_blank CHECK (length(btrim(normalized_name)) > 0)
);

-- Rationale for UNIQUE(normalized_name): the legacy ingestion path is name-first
-- (CompanyID = md5(name)) and we need idempotent company upserts during migration.
-- There is currently no evidence of two distinct legal entities sharing a
-- normalized name. See schema.md "Companies uniqueness" for the trade-off and
-- the escape hatch (drop the constraint and use a non-unique index if it ever
-- blocks legitimate data).
ALTER TABLE core.companies
    ADD CONSTRAINT companies_normalized_name_key UNIQUE (normalized_name);

CREATE INDEX ix_companies_display_name ON core.companies (display_name);
CREATE INDEX ix_companies_is_active    ON core.companies (is_active) WHERE is_active;

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON core.companies
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE core.companies IS
    'Issuer/legal entity. Never keyed by name or symbol.';

-- ----------------------------------------------------------------------------
-- core.securities
-- A tradable instrument. A company may have many securities: base symbol,
-- rights issues, secondary symbols (e.g. سیمرغ / سیمرغ3, جم پیلن / جم پیلن2/3).
-- ----------------------------------------------------------------------------
CREATE TABLE core.securities (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id       uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    tsetmc_ins_code  bigint,                       -- TSETMC "insCode" (external market identifier)
    codal_symbol     text,                         -- Codal ticker / Symbol
    isin             text,                         -- optional, when available
    brs_name         text,                         -- vendor (BRS) display name
    security_type    text        NOT NULL DEFAULT 'stock',
    is_primary       boolean     NOT NULL DEFAULT false,
    is_active        boolean     NOT NULL DEFAULT true,
    valid_from       date,
    valid_to         date,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT securities_type_chk CHECK (security_type IN
        ('stock','right','preferred','bond','sukuk','etf','fund','option','gold','commodity','other')),
    CONSTRAINT securities_validity_chk CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

-- tsetmc_ins_code is UNIQUE when present.
CREATE UNIQUE INDEX uq_securities_tsetmc_ins_code
    ON core.securities (tsetmc_ins_code) WHERE tsetmc_ins_code IS NOT NULL;

-- isin is UNIQUE when present.
CREATE UNIQUE INDEX uq_securities_isin
    ON core.securities (isin) WHERE isin IS NOT NULL;

-- At most one primary security per company (partial unique).
CREATE UNIQUE INDEX uq_securities_one_primary_per_company
    ON core.securities (company_id) WHERE is_primary;

CREATE INDEX ix_securities_company      ON core.securities (company_id);
CREATE INDEX ix_securities_codal_symbol  ON core.securities (codal_symbol);
CREATE INDEX ix_securities_active        ON core.securities (is_active) WHERE is_active;

CREATE TRIGGER trg_securities_updated_at
    BEFORE UPDATE ON core.securities
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE core.securities IS
    'Tradable instrument. Carries external identifiers (tsetmc_ins_code, codal_symbol, isin).';

-- ----------------------------------------------------------------------------
-- core.security_aliases
-- History/mapping of names and symbols over time (old symbols, legacy names).
-- ----------------------------------------------------------------------------
CREATE TABLE core.security_aliases (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id  uuid        NOT NULL REFERENCES core.securities(id) ON DELETE CASCADE,
    alias_type   text        NOT NULL,
    alias_value  text        NOT NULL,
    source       text,                             -- 'codal','tsetmc','brs','legacy_sqlserver', ...
    valid_from   date,
    valid_to     date,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT security_aliases_type_chk CHECK (alias_type IN
        ('symbol','company_name','brs_name','legacy_name','isin')),
    CONSTRAINT security_aliases_validity_chk CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX uq_security_alias
    ON core.security_aliases (security_id, alias_type, alias_value, COALESCE(source, ''));
CREATE INDEX ix_security_aliases_value ON core.security_aliases (alias_type, alias_value);

COMMENT ON TABLE core.security_aliases IS
    'Append-mostly mapping of historical symbol/name aliases to a security.';

-- ----------------------------------------------------------------------------
-- core.legacy_entity_map
-- Critical for migration: maps every legacy SQL Server entity key to the new
-- canonical UUID, so we can trace e.g. md5 "002c39..." -> new company/security.
-- ----------------------------------------------------------------------------
CREATE TABLE core.legacy_entity_map (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system  text        NOT NULL DEFAULT 'sqlserver_codal',
    source_table   text        NOT NULL,
    legacy_key     text        NOT NULL,
    entity_type    text        NOT NULL,
    target_uuid    uuid        NOT NULL,
    mapping_method text,
    confidence     numeric(3,2),
    notes          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT legacy_entity_map_confidence_chk CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT legacy_entity_map_entity_type_chk CHECK (entity_type IN
        ('company','security','report','portfolio','participant','account','asset','user','other'))
);

CREATE UNIQUE INDEX uq_legacy_entity_map
    ON core.legacy_entity_map (source_system, source_table, legacy_key, entity_type);
CREATE INDEX ix_legacy_entity_map_target ON core.legacy_entity_map (entity_type, target_uuid);

COMMENT ON TABLE core.legacy_entity_map IS
    'Migration traceability: legacy SQL Server keys -> canonical UUID entities.';
