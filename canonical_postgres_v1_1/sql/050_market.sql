-- ============================================================================
-- 050_market.sql  —  daily prices, corporate actions, vendor snapshots
-- DO NOT EXECUTE in this phase.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- market.daily_prices
-- Canonical replacement for dbo.MarketPriceHistory. Prices in IRR (rial), numeric.
--
-- PK decision: bigint IDENTITY surrogate PK + UNIQUE (security_id, trade_date).
-- Reason:
--   * A stable surrogate key keeps FKs simple and decouples them from the
--     business key.
--   * The business key (security_id, trade_date) is enforced by a UNIQUE index,
--     giving the same integrity guarantee.
--   * This table currently has ~700k rows; partitioning is NOT done in v1.1.
--     (v1.1 CHANGE item 13: the previous "future partitioning" justification was
--     inaccurate -- partitioned tables in PostgreSQL restrict PK/UNIQUE to
--     include the partition key, so a surrogate PK alone would not make
--     partitioning automatic. Partitioning is simply deferred; if adopted later,
--     trade_date is a natural partition key and the PK/UNIQUE must be revisited
--     to include it.)
--
-- v1.1 CHANGE (item 12): chosen model = A (single canonical series) WITH
-- explicit provenance/version. The canonical series here is the ADJUSTED one
-- (BRS candle_daily_adjusted + local/or vendor adjustment), and every row records
-- source, adjustment_method, adjustment_version and collected_at so a backtest
-- can state exactly which price series/version it consumed. A separate
-- market.price_observations (raw unadjusted) is intentionally NOT created now
-- (avoids over-engineering at 700k rows); the archived legacy MarketPriceHistory
-- remains the raw backup, and a price_observations layer can be added later.
-- ----------------------------------------------------------------------------
CREATE TABLE market.daily_prices (
    id                    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    security_id           uuid        NOT NULL REFERENCES core.securities(id) ON DELETE RESTRICT,
    trade_date            date        NOT NULL,
    first_price_rial      numeric(24,4),
    open_price_rial       numeric(24,4),             -- may be NULL (legacy MPH lacks true open)
    high_price_rial       numeric(24,4),
    low_price_rial        numeric(24,4),
    closing_price_rial    numeric(24,4),
    last_price_rial       numeric(24,4),
    yesterday_price_rial  numeric(24,4),
    closing_change_rial   numeric(24,4),
    closing_change_percent numeric(12,4),
    last_change_rial      numeric(24,4),
    last_change_percent   numeric(12,4),
    volume                bigint,
    trade_value_rial      numeric(30,4),
    trade_count           bigint,
    is_adjusted           boolean     NOT NULL DEFAULT false,
    adjustment_method     text,
    -- v1.1 (item 12): explicit series + provenance for reproducibility.
    price_series          text        NOT NULL DEFAULT 'adjusted',
    adjustment_version    text,                        -- e.g. 'brs-candle-v1', 'local-heuristic-2026'
    adjusted_at           timestamptz,
    provenance            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    source                text        NOT NULL DEFAULT 'brs',
    source_url            text,
    collected_at          timestamptz NOT NULL DEFAULT now(),
    jalali_date_text      text,
    CONSTRAINT daily_prices_volume_chk           CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT daily_prices_trade_count_chk      CHECK (trade_count IS NULL OR trade_count >= 0),
    CONSTRAINT daily_prices_trade_value_chk      CHECK (trade_value_rial IS NULL OR trade_value_rial >= 0),
    CONSTRAINT daily_prices_high_low_chk         CHECK (high_price_rial IS NULL OR low_price_rial IS NULL OR high_price_rial >= low_price_rial),
    CONSTRAINT daily_prices_adjust_method_chk    CHECK (adjustment_method IS NULL OR adjustment_method IN
        ('candle_daily_adjusted','vendor_adjusted','local_heuristic','none','unknown')),
    CONSTRAINT daily_prices_price_series_chk     CHECK (price_series IN ('adjusted','unadjusted'))
);

CREATE UNIQUE INDEX uq_daily_prices_security_date ON market.daily_prices (security_id, trade_date);
CREATE INDEX ix_daily_prices_date       ON market.daily_prices (trade_date DESC);
CREATE INDEX ix_daily_prices_security   ON market.daily_prices (security_id, trade_date DESC);

COMMENT ON TABLE market.daily_prices IS
    'Canonical daily prices (IRR). Business key = (security_id, trade_date); surrogate PK for FKs.';

-- ----------------------------------------------------------------------------
-- market.corporate_actions
-- Makes price adjustment explicit instead of hidden heuristic.
-- ----------------------------------------------------------------------------
CREATE TABLE market.corporate_actions (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id            uuid        NOT NULL REFERENCES core.securities(id) ON DELETE RESTRICT,
    action_date            date        NOT NULL,
    action_type            text        NOT NULL,
    adjustment_factor      numeric(24,8),
    source                 text,
    source_reference       text,
    is_confirmed           boolean     NOT NULL DEFAULT false,
    detected_heuristically boolean     NOT NULL DEFAULT false,
    metadata               jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT corporate_actions_type_chk CHECK (action_type IN
        ('capital_increase','cash_dividend','stock_dividend','split','reverse_split','rights_issue','merger','other')),
    CONSTRAINT corporate_actions_factor_chk CHECK (adjustment_factor IS NULL OR adjustment_factor > 0)
);

CREATE INDEX ix_corporate_actions_security_date ON market.corporate_actions (security_id, action_date DESC);
CREATE INDEX ix_corporate_actions_type          ON market.corporate_actions (action_type);

-- ----------------------------------------------------------------------------
-- market.vendor_snapshots   (optional)
-- For vendor-provided valuation snapshots (e.g. legacy FullPE) so they never
-- pollute canonical market tables.
-- ----------------------------------------------------------------------------
CREATE TABLE market.vendor_snapshots (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id  uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    company_id   uuid        REFERENCES core.companies(id) ON DELETE SET NULL,
    captured_at  timestamptz NOT NULL,
    vendor       text        NOT NULL,
    metric_code  text        NOT NULL,                -- e.g. 'pe','price','pb'
    value        numeric(30,6),
    unit         text,
    raw_payload  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vendor_snapshots_target_chk CHECK (security_id IS NOT NULL OR company_id IS NOT NULL)
);

CREATE INDEX ix_vendor_snapshots_company  ON market.vendor_snapshots (company_id, metric_code, captured_at DESC);
CREATE INDEX ix_vendor_snapshots_security ON market.vendor_snapshots (security_id, metric_code, captured_at DESC);
