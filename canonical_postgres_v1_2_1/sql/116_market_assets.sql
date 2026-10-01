-- 116_market_assets.sql — exchange index series (سری شاخص‌ها)
--
-- data source: Api.BrsApi.ir/Tsetmc/Index.php?type=3 (فقط اسنپ‌شات روز جاری:
-- شاخص کل، شاخص کل (هم‌وزن)، شاخص قیمت، آزاد شناور، بازار اول/دوم).
--
-- Why a separate table and not core.securities / market.price_observations:
--   * An index is neither a Company nor a tradable Security. It has no ISIN, no
--     shares, no issuer, and its "value" is a level, not an IRR price. Modeling
--     it as a security would require making core.securities.company_id nullable
--     and would falsify the "Company != Security" invariant.
--   * The series is consumed as a benchmark (beta / tracking error / real
--     benchmark instead of a synthetic equal-weight basket).
--
-- History note: BRS exposes only the *current* index snapshot. History is
-- therefore accumulated one row per trading day by the daily collector
-- (go-app/py/market_assets.py). Rows are append-only and idempotent per
-- (index_code, trade_date); re-running the collector the same day updates the
-- day's row in place.

CREATE TABLE IF NOT EXISTS market.index_observations (
    id                bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    index_code        text         NOT NULL,   -- stable machine code, e.g. TEDPIX
    index_name        text         NOT NULL,   -- Persian display name
    trade_date        date         NOT NULL,
    jalali_date_text  text,
    value             numeric(24,4) NOT NULL,
    change_value      numeric(24,4),
    change_percent    numeric(12,4),
    min_value         numeric(24,4),
    max_value         numeric(24,4),
    market_value_rial numeric(30,4),
    trade_count       bigint,
    trade_value_rial  numeric(30,4),
    trade_volume      numeric(30,0),
    source            text         NOT NULL DEFAULT 'brs_index',
    collected_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT index_observations_code_not_blank CHECK (length(btrim(index_code)) > 0),
    CONSTRAINT index_observations_high_low_chk
        CHECK (min_value IS NULL OR max_value IS NULL OR max_value >= min_value)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_index_observations_code_date
    ON market.index_observations (index_code, trade_date);
CREATE INDEX IF NOT EXISTS ix_index_observations_code_date
    ON market.index_observations (index_code, trade_date DESC);

COMMENT ON TABLE market.index_observations IS
    'Exchange index levels (TEDPIX etc.). Benchmark series; not a tradable security.';
