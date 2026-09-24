-- ============================================================================
-- 050_market.sql  —  price observations (append-only), canonical view, corp actions, vendor
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- v1.2 (item 6): price revisioning is real.
--   * market.price_observations = APPEND-ONLY source of truth (all versions kept).
--   * market.daily_prices       = VIEW returning the latest canonical (adjusted)
--                                 observation per (security_id, trade_date).
-- Old versions are never overwritten; backtests select by collected_at cutoff.
-- Prices in IRR (rial), numeric.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- market.price_observations   (append-only; replaces the v1.1 daily_prices table)
-- ----------------------------------------------------------------------------
CREATE TABLE market.price_observations (
    id                     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    security_id            uuid        NOT NULL REFERENCES core.securities(id) ON DELETE RESTRICT,
    trade_date             date        NOT NULL,
    price_series           text        NOT NULL DEFAULT 'adjusted',   -- 'adjusted' | 'unadjusted'
    first_price_rial       numeric(24,4),
    open_price_rial        numeric(24,4),
    high_price_rial        numeric(24,4),
    low_price_rial         numeric(24,4),
    closing_price_rial     numeric(24,4),
    last_price_rial        numeric(24,4),
    yesterday_price_rial   numeric(24,4),
    closing_change_rial    numeric(24,4),
    closing_change_percent numeric(12,4),
    last_change_rial       numeric(24,4),
    last_change_percent    numeric(12,4),
    volume                 bigint,
    trade_value_rial       numeric(30,4),
    trade_count            bigint,
    is_adjusted            boolean     NOT NULL DEFAULT true,
    adjustment_method      text,
    adjustment_version     text,
    provenance             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    source                 text        NOT NULL DEFAULT 'brs',
    source_url             text,
    collected_at           timestamptz NOT NULL DEFAULT now(),
    jalali_date_text       text,
    observation_hash       text        NOT NULL,        -- content hash for dedup
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT price_obs_volume_chk      CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT price_obs_trade_count_chk CHECK (trade_count IS NULL OR trade_count >= 0),
    CONSTRAINT price_obs_trade_value_chk CHECK (trade_value_rial IS NULL OR trade_value_rial >= 0),
    CONSTRAINT price_obs_high_low_chk    CHECK (high_price_rial IS NULL OR low_price_rial IS NULL OR high_price_rial >= low_price_rial),
    CONSTRAINT price_obs_series_chk      CHECK (price_series IN ('adjusted','unadjusted')),
    CONSTRAINT price_obs_method_chk      CHECK (adjustment_method IS NULL OR adjustment_method IN
        ('candle_daily_adjusted','vendor_adjusted','local_heuristic','none','unknown'))
);

-- Dedup: an identical observation (same content hash) is never stored twice.
CREATE UNIQUE INDEX uq_price_observations_hash ON market.price_observations (observation_hash);
CREATE INDEX ix_price_observations_security_date ON market.price_observations (security_id, trade_date, collected_at DESC);
CREATE INDEX ix_price_observations_cutoff        ON market.price_observations (security_id, trade_date, collected_at);

CREATE OR REPLACE FUNCTION market.prevent_observation_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'market.price_observations is append-only (attempted %)', TG_OP;
END;
$$;

CREATE TRIGGER trg_price_observations_immutable
    BEFORE UPDATE OR DELETE ON market.price_observations
    FOR EACH ROW EXECUTE FUNCTION market.prevent_observation_mutation();

COMMENT ON TABLE market.price_observations IS
    'Append-only price source of truth; multiple versions per (security,date) allowed.';

-- ----------------------------------------------------------------------------
-- market.daily_prices  (VIEW: latest canonical adjusted observation per key)
-- Simple API read path. Old versions remain in price_observations for backtests.
-- ----------------------------------------------------------------------------
CREATE VIEW market.daily_prices AS
SELECT DISTINCT ON (security_id, trade_date)
       security_id, trade_date,
       first_price_rial, open_price_rial, high_price_rial, low_price_rial,
       closing_price_rial, last_price_rial, yesterday_price_rial,
       closing_change_rial, closing_change_percent,
       last_change_rial, last_change_percent,
       volume, trade_value_rial, trade_count,
       is_adjusted, adjustment_method, adjustment_version, provenance,
       source, source_url, collected_at, jalali_date_text,
       id AS observation_id
FROM market.price_observations
WHERE price_series = 'adjusted'
ORDER BY security_id, trade_date, collected_at DESC, id DESC;

COMMENT ON VIEW market.daily_prices IS
    'Canonical latest adjusted price per (security_id, trade_date). Read-only view.';

-- ----------------------------------------------------------------------------
-- market.corporate_actions
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
-- market.vendor_snapshots   (vendor-provided valuation, never canonical market)
-- v1.2 (item 9): if security is present, company must be present AND match.
-- ----------------------------------------------------------------------------
CREATE TABLE market.vendor_snapshots (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id  uuid,
    company_id   uuid,
    captured_at  timestamptz NOT NULL,
    vendor       text        NOT NULL,
    metric_code  text        NOT NULL,
    value        numeric(30,6),
    unit         text,
    raw_payload  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vendor_snapshots_target_chk CHECK (security_id IS NOT NULL OR company_id IS NOT NULL),
    -- v1.2: security implies company, so the composite FK is always evaluable.
    CONSTRAINT vendor_snapshots_security_implies_company CHECK (security_id IS NULL OR company_id IS NOT NULL),
    CONSTRAINT vendor_snapshots_company_fk FOREIGN KEY (company_id)
        REFERENCES core.companies(id) ON DELETE RESTRICT,
    CONSTRAINT vendor_snapshots_security_company_fk FOREIGN KEY (security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT
);

CREATE INDEX ix_vendor_snapshots_company  ON market.vendor_snapshots (company_id, metric_code, captured_at DESC);
CREATE INDEX ix_vendor_snapshots_security ON market.vendor_snapshots (security_id, metric_code, captured_at DESC);
