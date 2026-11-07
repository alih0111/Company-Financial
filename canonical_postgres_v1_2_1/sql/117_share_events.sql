-- 117_share_events.sql — Explicit capital / share-count event evidence + derived PIT intervals.
--
-- Problem this solves: `core.share_structure` is a *current* daily snapshot
-- (BRS AllSymbols: z/mv) and starts 2026-09-29. Historical valuation needs
-- shares_outstanding that were effective at the valuation date, and the audit
-- proved (a) no historical market cap or share series exists, (b) projecting
-- today's shares backwards is look-ahead, and (c) `capital / 1000` is not a
-- reliable share count (the implied nominal value deviates for 34 of 263
-- issuers).
--
-- Two layers, deliberately separated:
--   core.share_events    explicit evidence, one row per source statement about a
--                        capital change. Never inferred from a price move.
--   core.share_intervals derived, PIT-ordered [valid_from, valid_to) share counts
--                        reconstructed ONLY from a complete event chain anchored
--                        on a vendor snapshot. Gaps are materialized as
--                        HISTORICAL_SHARES_UNKNOWN rather than interpolated.
--
-- Return adjustment is a different question from valuation: an announcement or
-- registration date is not a market ex-date, so an event is usable for returns
-- only when both `market_ex_date` and `economics_explicit` are set.

CREATE TABLE IF NOT EXISTS core.share_events (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          uuid        NOT NULL REFERENCES core.companies(id) ON DELETE CASCADE,
    security_id         uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    event_type          text        NOT NULL,
    -- share-count evidence (explicit values only; never derived from prices)
    shares_before       numeric(24,0),
    shares_after        numeric(24,0),
    change_ratio        numeric(20,10),   -- e.g. 0.5 for a 50% increase
    capital_before_rial numeric(30,4),
    capital_after_rial  numeric(30,4),
    nominal_value_rial  numeric(20,4),
    -- dates, each with its own meaning (never conflated)
    announced_at        date,
    approved_at         date,
    registered_at       date,
    effective_date      date,             -- date from which the new count holds for VALUATION
    market_ex_date      date,             -- market price-adjustment date (RETURN adjustment)
    economics_explicit  boolean     NOT NULL DEFAULT false,
    -- lineage / PIT
    published_at        timestamptz,
    collected_at        timestamptz NOT NULL DEFAULT now(),
    source              text        NOT NULL,
    source_report_id    text,
    status              text        NOT NULL DEFAULT 'EVIDENCE',
    confidence          text        NOT NULL DEFAULT 'explicit',
    metadata            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT share_events_type_chk CHECK (event_type IN (
        'CAPITAL_INCREASE_PROPOSAL', 'BOARD_APPROVAL', 'EGM_APPROVAL',
        'AUDITOR_APPROVAL', 'REGISTRATION', 'CAPITAL_INCREASE_REGISTERED',
        'CAPITAL_REDUCTION', 'NOMINAL_VALUE_CHANGE', 'RIGHTS_ISSUE',
        'BONUS_SHARES', 'OTHER_CAPITAL_EVENT')),
    CONSTRAINT share_events_status_chk CHECK (status IN ('EVIDENCE', 'CONFIRMED', 'REJECTED')),
    CONSTRAINT share_events_confidence_chk CHECK (confidence IN ('explicit', 'derived')),
    -- a CONFIRMED event that claims return-adjustment usability must state both
    -- the market ex-date and the economics; nothing approximate is accepted
    CONSTRAINT share_events_return_usable_chk
        CHECK (status <> 'CONFIRMED' OR market_ex_date IS NULL
               OR economics_explicit OR market_ex_date IS NULL)
);

CREATE INDEX IF NOT EXISTS ix_share_events_company_date
    ON core.share_events (company_id, COALESCE(effective_date, registered_at, announced_at));
CREATE INDEX IF NOT EXISTS ix_share_events_security_date
    ON core.share_events (security_id, COALESCE(effective_date, registered_at, announced_at));

CREATE TABLE IF NOT EXISTS core.share_intervals (
    id                 bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    security_id        uuid        NOT NULL REFERENCES core.securities(id) ON DELETE CASCADE,
    company_id         uuid,
    valid_from         date,                  -- NULL = unknown lower bound (open past)
    valid_to           date,                  -- NULL = still effective
    shares_outstanding numeric(24,0),
    -- KNOWLEDGE TIME: when the evidence establishing this count became public.
    -- For an observed vendor snapshot it is that snapshot's collected_at (an
    -- observation cannot be known before it was observed, which keeps today's
    -- count out of history). For a reconstructed interval it is
    -- MAX(published_at) over the REQUIRED evidence only. Derivable from
    -- evidence.required_evidence[].published_at; materialized so the PIT
    -- predicate is indexable. NULL = knowledge time not established, so the
    -- interval is never PIT-eligible.
    knowledge_from     timestamptz,
    basis              text        NOT NULL,
    status             text        NOT NULL,
    source             text        NOT NULL,
    evidence           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    collected_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT share_intervals_basis_chk CHECK (basis IN (
        'VENDOR_SNAPSHOT', 'RECONSTRUCTED_EVENT_CHAIN', 'UNKNOWN')),
    CONSTRAINT share_intervals_status_chk CHECK (status IN (
        'KNOWN', 'HISTORICAL_SHARES_UNKNOWN')),
    -- a KNOWN interval must carry a count and a known start; an UNKNOWN one must
    -- not carry a count (the gap is materialized, never interpolated)
    CONSTRAINT share_intervals_known_has_count_chk
        CHECK ((status = 'KNOWN') = (shares_outstanding IS NOT NULL)),
    CONSTRAINT share_intervals_known_has_start_chk
        CHECK (status <> 'KNOWN' OR valid_from IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_share_intervals_from
    ON core.share_intervals (security_id, valid_from);
CREATE INDEX IF NOT EXISTS ix_share_intervals_pit
    ON core.share_intervals (security_id, valid_from DESC);
-- Idempotent migration for databases created before the knowledge-time column.
-- The index is created inside the block so it works on a fresh database (column
-- already present) and on an existing one (column added here).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='core' AND table_name='share_intervals'
                     AND column_name='knowledge_from') THEN
        ALTER TABLE core.share_intervals ADD COLUMN knowledge_from timestamptz;
    END IF;
    CREATE INDEX IF NOT EXISTS ix_share_intervals_knowledge
        ON core.share_intervals (security_id, knowledge_from);
END $$;

-- Interval integrity: a security can never have two overlapping share intervals,
-- so two contradictory counts cannot coexist. `valid_from IS NULL` is the real
-- unbounded past (no sentinel date is stored); COALESCE only shapes the range for
-- the comparison, and `valid_to IS NULL` is the open present.
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE core.share_intervals
    DROP CONSTRAINT IF EXISTS share_intervals_no_overlap;
ALTER TABLE core.share_intervals
    ADD CONSTRAINT share_intervals_no_overlap
    EXCLUDE USING gist (
        security_id WITH =,
        daterange(COALESCE(valid_from, '-infinity'::date),
                  COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
    );

-- Migration for a database created before the unbounded-past representation:
-- `valid_from` must be nullable, and a KNOWN interval must still carry a start.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='core' AND table_name='share_intervals'
                 AND column_name='valid_from' AND is_nullable='NO') THEN
        ALTER TABLE core.share_intervals ALTER COLUMN valid_from DROP NOT NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid='core.share_intervals'::regclass
                     AND conname='share_intervals_known_has_start_chk') THEN
        ALTER TABLE core.share_intervals
            ADD CONSTRAINT share_intervals_known_has_start_chk
            CHECK (status <> 'KNOWN' OR valid_from IS NOT NULL);
    END IF;
END $$;
