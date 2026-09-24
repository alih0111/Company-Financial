-- ============================================================================
-- 070_portfolio.sql  —  portfolios, participants, accounts, ledger, valuation
-- v1.1 (hardened). DO NOT EXECUTE in this phase.
--
-- v1.1 architectural decisions:
--   * transactions = immutable ledger = source of truth.
--   * positions and cash balances = derived/materialized/cache.
--   * item 6: composite FKs guarantee account/participant belong to the same
--     portfolio as the transaction/account that references them.
--   * item 7: Option A -- unified asset abstraction. Every transaction targets
--     portfolio.assets via asset_id only; listed securities are represented by
--     an asset row whose security_id points to core.securities. No asset_id XOR
--     security_id ambiguity in the ledger.
--   * item 8: reversal integrity enforced by CHECK + partial UNIQUE + composite FK.
--   * item 9: opening_position / opening_cash transaction types for legacy migration
--     (no fabricated historical trades).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- portfolio.portfolios
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
-- portfolio.participants   (replaces FamilyPeople)
-- v1.1 (item 6): UNIQUE(id, portfolio_id) makes the pair referenceable by
-- composite FKs from accounts/transactions.
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
    CONSTRAINT participants_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT participants_id_portfolio_key UNIQUE (id, portfolio_id)
);

CREATE INDEX ix_participants_portfolio ON portfolio.participants (portfolio_id);

CREATE TRIGGER trg_participants_updated_at
    BEFORE UPDATE ON portfolio.participants
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.accounts   (cash/broker accounts)
-- Cash balance NOT stored here; derived from ledger.
-- v1.1 (item 6): participant (if any) must belong to the same portfolio.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.accounts (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id        uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    participant_id      uuid,
    account_type        text        NOT NULL,
    broker              text,
    external_account_ref text,
    is_active           boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT accounts_type_chk CHECK (account_type IN ('cash','broker','margin','other')),
    CONSTRAINT accounts_id_portfolio_key UNIQUE (id, portfolio_id),
    CONSTRAINT accounts_participant_portfolio_fk FOREIGN KEY (participant_id, portfolio_id)
        REFERENCES portfolio.participants(id, portfolio_id) ON DELETE RESTRICT
);

CREATE INDEX ix_accounts_portfolio ON portfolio.accounts (portfolio_id);

CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON portfolio.accounts
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.assets   (replaces FamilyAssets; non-listed assets like gold)
-- A listed security is represented by an asset row with security_id set.
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
    CONSTRAINT assets_commission_chk CHECK (commission_rate >= 0 AND commission_rate <= 1),
    -- At most one asset row per security (prevents ambiguous ledger targets).
    CONSTRAINT assets_security_key UNIQUE (security_id)
);

CREATE INDEX ix_assets_security ON portfolio.assets (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX ix_assets_type     ON portfolio.assets (asset_type);

CREATE TRIGGER trg_assets_updated_at
    BEFORE UPDATE ON portfolio.assets
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.transactions   (immutable ledger)
-- Option A: single target type = asset_id (nullable for pure cash movements).
-- Corrections via reversing transactions, never UPDATE/DELETE.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.transactions (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id      uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE RESTRICT,
    account_id        uuid,
    participant_id    uuid,
    asset_id          uuid        REFERENCES portfolio.assets(id) ON DELETE RESTRICT,
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
    reverses_tx_id    uuid,
    -- v1.1 (item 9): migration provenance (e.g. {"source":"legacy_migration",
    -- "legacy_cost_basis":..., "legacy_quantity":..., "migration_ts":...}).
    metadata          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT transactions_type_chk CHECK (transaction_type IN
        ('buy','sell','deposit','withdrawal','dividend','fee','tax','adjustment',
         'transfer_in','transfer_out','opening_position','opening_cash')),
    CONSTRAINT transactions_qty_chk CHECK (quantity IS NULL OR quantity > 0),
    -- cash-only types need no asset; position/dividend types require one.
    CONSTRAINT transactions_target_chk CHECK (
        transaction_type IN ('deposit','withdrawal','fee','tax','opening_cash','transfer_in','transfer_out','adjustment')
        OR asset_id IS NOT NULL),
    -- item 8: a transaction cannot reverse itself.
    CONSTRAINT transactions_no_self_reverse CHECK (reverses_tx_id IS NULL OR reverses_tx_id <> id),
    -- item 6: account and participant, if present, must belong to this portfolio.
    CONSTRAINT transactions_id_portfolio_key UNIQUE (id, portfolio_id),
    CONSTRAINT transactions_account_portfolio_fk FOREIGN KEY (account_id, portfolio_id)
        REFERENCES portfolio.accounts(id, portfolio_id) ON DELETE RESTRICT,
    CONSTRAINT transactions_participant_portfolio_fk FOREIGN KEY (participant_id, portfolio_id)
        REFERENCES portfolio.participants(id, portfolio_id) ON DELETE RESTRICT,
    -- item 8: reversal must be in the same portfolio.
    CONSTRAINT transactions_reverses_portfolio_fk FOREIGN KEY (reverses_tx_id, portfolio_id)
        REFERENCES portfolio.transactions(id, portfolio_id) ON DELETE RESTRICT
);

CREATE INDEX ix_transactions_portfolio_date ON portfolio.transactions (portfolio_id, trade_date);
CREATE INDEX ix_transactions_asset          ON portfolio.transactions (asset_id) WHERE asset_id IS NOT NULL;
CREATE INDEX ix_transactions_account        ON portfolio.transactions (account_id) WHERE account_id IS NOT NULL;

-- item 8: a given transaction may be reversed at most once.
CREATE UNIQUE INDEX uq_transactions_reverses
    ON portfolio.transactions (reverses_tx_id) WHERE reverses_tx_id IS NOT NULL;

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
    'Immutable ledger; source of truth. Unified target = asset_id. Correct via reversing transactions.';

-- ----------------------------------------------------------------------------
-- portfolio.positions   (derived/materialized cache, NOT source of truth)
-- v1.1 (item 10): unified asset model -> simple UNIQUE(portfolio_id, asset_id).
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.positions (
    portfolio_id uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE CASCADE,
    asset_id     uuid        NOT NULL REFERENCES portfolio.assets(id) ON DELETE CASCADE,
    quantity     numeric(30,6) NOT NULL,
    avg_cost_rial numeric(30,6),
    cost_basis_rial numeric(30,4),
    as_of_at     timestamptz NOT NULL DEFAULT now(),
    computed_from_tx_count integer NOT NULL DEFAULT 0,
    CONSTRAINT positions_pk PRIMARY KEY (portfolio_id, asset_id)
);

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
-- v1.1 (item 11): DECISION -- prices are a property of the ASSET (global), not
-- of a portfolio. portfolio_id is removed and uniqueness is (asset_id, price_date).
-- Rationale: legacy FamilyPrices has no portfolio dimension; non-market assets
-- (gold, currency) have a single observed price. A future portfolio-specific
-- valuation OVERRIDE would be a separate concept/table, not this one.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.asset_price_snapshots (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id    uuid        NOT NULL REFERENCES portfolio.assets(id) ON DELETE CASCADE,
    price_date  date        NOT NULL,
    price_rial  numeric(30,4) NOT NULL,
    source      text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT asset_price_unique UNIQUE (asset_id, price_date)
);

CREATE INDEX ix_asset_price_asset_date ON portfolio.asset_price_snapshots (asset_id, price_date DESC);
