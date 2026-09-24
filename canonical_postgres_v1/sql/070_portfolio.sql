-- ============================================================================
-- 070_portfolio.sql  —  portfolios, participants, accounts, ledger, valuation
-- DO NOT EXECUTE in this phase.
--
-- Architectural stance:
--   * transactions = immutable ledger = source of truth.
--   * positions and cash balances = derived/materialized/cache (see positions).
--   * valuation snapshots are derived caches, rebuildable from ledger + prices.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- portfolio.portfolios
-- Designed to also support paper/live trading later, not only family migration.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.portfolios (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid        REFERENCES auth.users(id) ON DELETE SET NULL,
    name                text        NOT NULL,
    portfolio_type      text        NOT NULL,
    base_currency       text        NOT NULL DEFAULT 'IRR',
    initial_capital_rial numeric(30,4),
    is_active           boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT portfolios_type_chk CHECK (portfolio_type IN ('personal','family','paper','live')),
    CONSTRAINT portfolios_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE INDEX ix_portfolios_user ON portfolio.portfolios (user_id) WHERE user_id IS NOT NULL;

CREATE TRIGGER trg_portfolios_updated_at
    BEFORE UPDATE ON portfolio.portfolios
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.participants   (replaces FamilyPeople; supports multi-owner)
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.participants (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    name         text        NOT NULL,
    user_id      uuid        REFERENCES auth.users(id) ON DELETE SET NULL,
    sort_order   integer     NOT NULL DEFAULT 0,
    is_active    boolean     NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT participants_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE INDEX ix_participants_portfolio ON portfolio.participants (portfolio_id);

CREATE TRIGGER trg_participants_updated_at
    BEFORE UPDATE ON portfolio.participants
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.accounts   (cash/broker accounts)
-- Cash balance is NOT stored here; it is derived from the ledger.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.accounts (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    participant_id      uuid        REFERENCES portfolio.participants(id) ON DELETE SET NULL,
    account_type        text        NOT NULL,
    broker              text,
    external_account_ref text,
    is_active           boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT accounts_type_chk CHECK (account_type IN ('cash','broker','margin','other'))
);

CREATE INDEX ix_accounts_portfolio ON portfolio.accounts (portfolio_id);

CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON portfolio.accounts
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.assets   (replaces FamilyAssets; non-listed assets like gold)
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.assets (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id     uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    asset_type      text        NOT NULL,
    name            text        NOT NULL,
    symbol          text,
    pricing_source  text,
    commission_rate numeric(12,6) NOT NULL DEFAULT 0,
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT assets_type_chk CHECK (asset_type IN ('stock','gold','currency','real_estate','fund','other')),
    CONSTRAINT assets_commission_chk CHECK (commission_rate >= 0 AND commission_rate <= 1)
);

CREATE INDEX ix_assets_security ON portfolio.assets (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX ix_assets_type     ON portfolio.assets (asset_type);

CREATE TRIGGER trg_assets_updated_at
    BEFORE UPDATE ON portfolio.assets
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.transactions   (immutable ledger)
-- Corrections via reversing/corrective transactions, never UPDATE/DELETE.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.transactions (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id      uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE RESTRICT,
    account_id        uuid        REFERENCES portfolio.accounts(id) ON DELETE RESTRICT,
    participant_id    uuid        REFERENCES portfolio.participants(id) ON DELETE SET NULL,
    asset_id          uuid        REFERENCES portfolio.assets(id) ON DELETE RESTRICT,
    security_id       uuid        REFERENCES core.securities(id) ON DELETE RESTRICT,
    transaction_type  text        NOT NULL,
    trade_date        date        NOT NULL,
    quantity          numeric(30,6),
    price_rial        numeric(30,6),
    gross_amount_rial numeric(30,4),
    fee_rial          numeric(30,4),
    tax_rial          numeric(30,4),
    net_amount_rial   numeric(30,4),
    external_ref      text,
    notes             text,
    reverses_tx_id    uuid        REFERENCES portfolio.transactions(id) ON DELETE RESTRICT,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT transactions_type_chk CHECK (transaction_type IN
        ('buy','sell','deposit','withdrawal','dividend','fee','tax','adjustment','transfer_in','transfer_out')),
    CONSTRAINT transactions_qty_chk CHECK (quantity IS NULL OR quantity > 0),
    CONSTRAINT transactions_target_chk CHECK (asset_id IS NOT NULL OR security_id IS NOT NULL
        OR transaction_type IN ('deposit','withdrawal','fee','tax','adjustment'))
);

CREATE INDEX ix_transactions_portfolio_date ON portfolio.transactions (portfolio_id, trade_date);
CREATE INDEX ix_transactions_security       ON portfolio.transactions (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX ix_transactions_asset          ON portfolio.transactions (asset_id) WHERE asset_id IS NOT NULL;
CREATE INDEX ix_transactions_account        ON portfolio.transactions (account_id) WHERE account_id IS NOT NULL;

CREATE OR REPLACE FUNCTION portfolio.prevent_transaction_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'portfolio.transactions is an immutable ledger (attempted %)', TG_OP;
END;
$$;

CREATE TRIGGER trg_transactions_immutable
    BEFORE UPDATE OR DELETE ON portfolio.transactions
    FOR EACH ROW EXECUTE FUNCTION portfolio.prevent_transaction_mutation();

COMMENT ON TABLE portfolio.transactions IS
    'Immutable ledger; source of truth. Correct via reversing transactions.';

-- ----------------------------------------------------------------------------
-- portfolio.positions
-- DECISION: derived/materialized cache, NOT source of truth.
-- Rationale: positions are a deterministic function of the ledger. Storing them
-- as plain mutable rows invites drift. We provide a position table only as a
-- refreshable cache (or implement as a MATERIALIZED VIEW later). `as_of_at`
-- makes the snapshot explicit.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.positions (
    portfolio_id uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    asset_id     uuid        REFERENCES portfolio.assets(id) ON DELETE CASCADE,
    security_id  uuid        REFERENCES core.securities(id) ON DELETE CASCADE,
    quantity     numeric(30,6) NOT NULL,
    avg_cost_rial numeric(30,6),
    cost_basis_rial numeric(30,4),
    as_of_at     timestamptz NOT NULL DEFAULT now(),
    computed_from_tx_count integer NOT NULL DEFAULT 0,
    CONSTRAINT positions_target_chk CHECK (num_nonnulls(asset_id, security_id) = 1)
);

CREATE UNIQUE INDEX uq_positions_target
    ON portfolio.positions (portfolio_id, COALESCE(asset_id, security_id));

COMMENT ON TABLE portfolio.positions IS
    'Derived cache (rebuildable from ledger). Not authoritative; refresh on demand.';

-- ----------------------------------------------------------------------------
-- portfolio.valuation_snapshots   (replaces FamilyHistory)
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.valuation_snapshots (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id      uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    valuation_date    date        NOT NULL,
    total_value_rial  numeric(30,4),
    cash_value_rial   numeric(30,4),
    invested_value_rial numeric(30,4),
    pnl_rial          numeric(30,4),
    return_pct        numeric(12,4),
    calculated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT valuation_snapshots_unique UNIQUE (portfolio_id, valuation_date)
);

-- ----------------------------------------------------------------------------
-- portfolio.asset_price_snapshots   (replaces FamilyPrices)
-- For non-market assets / valuation overrides. Separate from market.daily_prices.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.asset_price_snapshots (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id uuid       REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    asset_id    uuid        NOT NULL REFERENCES portfolio.assets(id) ON DELETE CASCADE,
    price_date  date        NOT NULL,
    price_rial  numeric(30,4) NOT NULL,
    source      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT asset_price_unique UNIQUE (asset_id, price_date)
);

CREATE INDEX ix_asset_price_asset_date ON portfolio.asset_price_snapshots (asset_id, price_date DESC);
