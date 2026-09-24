-- ============================================================================
-- Canonical PostgreSQL Schema v1
-- 001_extensions.sql
-- ----------------------------------------------------------------------------
-- DO NOT EXECUTE in this phase. Design artifact only.
--
-- UUID strategy:
--   * PostgreSQL 13+ has gen_random_uuid() built in. We still enable pgcrypto so
--     the schema also works on older servers (pgcrypto provides gen_random_uuid).
--   * All surrogate PKs use gen_random_uuid() as column DEFAULT.
--   * citext is used for case-insensitive username/email uniqueness in auth.
--   * No trigger-based UUID generation; DEFAULT is preferred (simpler, faster).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid() (also built-in on PG13+)
CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive text (auth.users)

-- Schemas (namespaces). Ordered by domain separation.
CREATE SCHEMA IF NOT EXISTS core;         -- companies / securities / aliases / legacy map
CREATE SCHEMA IF NOT EXISTS ingestion;    -- codal registry, versions, sync state, runs, DQ
CREATE SCHEMA IF NOT EXISTS raw;          -- raw report payloads (immutable)
CREATE SCHEMA IF NOT EXISTS fundamentals; -- monthly activities, financial statements/facts
CREATE SCHEMA IF NOT EXISTS market;       -- daily prices, corporate actions, vendor snapshots
CREATE SCHEMA IF NOT EXISTS analytics;    -- score runs, company/factor scores, metric snapshots
CREATE SCHEMA IF NOT EXISTS portfolio;    -- portfolios, participants, accounts, ledger, valuation
CREATE SCHEMA IF NOT EXISTS auth;         -- users, view events

-- ----------------------------------------------------------------------------
-- Shared utility: updated_at maintenance.
-- Applied only to mutable tables. Append-only tables do NOT get this trigger.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION core.set_updated_at() IS
    'Generic BEFORE UPDATE trigger to stamp updated_at = now() on mutable rows.';
