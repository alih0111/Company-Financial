-- ============================================================================
-- 070_portfolio.sql  —  portfolios, participants, accounts, ledger, valuation
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- Ledger is the ONLY accounting source of truth. Everything else is derived.
-- Accounting model (item 14): every ledger row carries explicit signed effects
--   quantity_delta   (asset units; + = acquire, - = dispose)
--   cash_delta_rial  (cash; + = inflow, - = outflow)
-- current cash    = SUM(cash_delta_rial)
-- current qty     = SUM(quantity_delta)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- portfolio.portfolios   (v1.2 item 10: initial_capital_rial removed)
-- Initial capital, when needed (paper), is an opening_cash ledger transaction.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.portfolios (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid        REFERENCES auth.users(id) ON DELETE SET NULL,
    name          text        NOT NULL,
    portfolio_type text       NOT NULL,
    base_currency text        NOT NULL DEFAULT 'IRR',
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT portfolios_type_chk CHECK (portfolio_type IN ('personal','family','paper','live')),
    CONSTRAINT portfolios_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE INDEX ix_portfolios_user ON portfolio.portfolios (user_id) WHERE user_id IS NOT NULL;

CREATE TRIGGER trg_portfolios_updated_at
    BEFORE UPDATE ON portfolio.portfolios
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- portfolio.participants
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
-- v1.2 (item 16): transactions.account_id is NOT NULL; a synthetic account is
-- created for legacy migration. Cash balance derived from ledger.
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
-- portfolio.assets
-- v1.2 (item 11): commission_rate removed (fees live in transactions.fee_rial).
-- v1.2 (item 17): for security-linked assets, name/symbol are derived (nullable
-- here); non-security assets require name. See view portfolio.assets_resolved.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.assets (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id     uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    asset_type      text        NOT NULL,
    name            text,
    symbol          text,
    pricing_source  text,
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT assets_type_chk CHECK (asset_type IN ('stock','gold','currency','real_estate','fund','other')),
    CONSTRAINT assets_name_chk CHECK (security_id IS NOT NULL OR (name IS NOT NULL AND length(btrim(name)) > 0)),
    CONSTRAINT assets_security_key UNIQUE (security_id)
);

CREATE INDEX ix_assets_security ON portfolio.assets (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX ix_assets_type     ON portfolio.assets (asset_type);

CREATE TRIGGER trg_assets_updated_at
    BEFORE UPDATE ON portfolio.assets
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- Resolved display for assets: listed assets derive name/symbol from company/security.
CREATE VIEW portfolio.assets_resolved AS
SELECT a.id, a.security_id, a.asset_type,
       COALESCE(a.name, c.display_name) AS resolved_name,
       COALESCE(a.symbol, s.codal_symbol) AS resolved_symbol,
       a.pricing_source, a.is_active
FROM portfolio.assets a
LEFT JOIN core.securities s ON s.id = a.security_id
LEFT JOIN core.companies  c ON c.id = s.company_id;

-- ----------------------------------------------------------------------------
-- portfolio.transactions   (immutable ledger)
-- v1.2: unified asset target; signed effects; effective_date/trade_date split;
-- structured opening cost basis; explicit reversal type with enforcing trigger.
-- ----------------------------------------------------------------------------
CREATE TABLE portfolio.transactions (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id      uuid        NOT NULL REFERENCES portfolio.portfolios(id) ON DELETE RESTRICT,
    account_id        uuid        NOT NULL,
    participant_id    uuid,
    asset_id          uuid        REFERENCES portfolio.assets(id) ON DELETE RESTRICT,
    transaction_type  text        NOT NULL,
    effective_date    date        NOT NULL,
    trade_date        date,
    quantity          numeric(30,6),
    price_rial        numeric(30,6),
    gross_amount_rial numeric(30,4),
    fee_rial          numeric(30,4),
    tax_rial          numeric(30,4),
    net_amount_rial   numeric(30,4),
    quantity_delta    numeric(30,6) NOT NULL DEFAULT 0,
    cash_delta_rial   numeric(30,4) NOT NULL DEFAULT 0,
    cost_basis_rial   numeric(30,4),
    external_ref      text,
    notes             text,
    reverses_tx_id    uuid,
    metadata          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT transactions_type_chk CHECK (transaction_type IN
        ('buy','sell','deposit','withdrawal','dividend','fee','tax','adjustment',
         'transfer_in','transfer_out','opening_position','opening_cash','reversal')),
    CONSTRAINT transactions_qty_chk CHECK (quantity IS NULL OR quantity > 0),
    -- market events need a trade date; administrative events do not.
    CONSTRAINT transactions_trade_date_chk CHECK (
        (transaction_type IN ('buy','sell') AND trade_date IS NOT NULL)
        OR transaction_type NOT IN ('buy','sell')),
    -- asset required except for pure cash/administrative types.
    CONSTRAINT transactions_target_chk CHECK (
        transaction_type IN ('deposit','withdrawal','fee','tax','opening_cash','transfer_in','transfer_out','adjustment','reversal')
        OR asset_id IS NOT NULL),
    -- opening_position must carry a structured cost basis (item 13).
    CONSTRAINT transactions_opening_cost_chk CHECK (
        transaction_type <> 'opening_position'
        OR (cost_basis_rial IS NOT NULL AND cost_basis_rial >= 0)),
    -- signed effect convention (item 14). reversal sign is enforced by trigger.
    CONSTRAINT transactions_sign_chk CHECK (
        (transaction_type = 'buy'              AND quantity_delta > 0 AND cash_delta_rial < 0)
        OR (transaction_type = 'sell'          AND quantity_delta < 0 AND cash_delta_rial > 0)
        OR (transaction_type = 'deposit'       AND quantity_delta = 0 AND cash_delta_rial > 0)
        OR (transaction_type = 'opening_cash'  AND quantity_delta = 0 AND cash_delta_rial > 0)
        OR (transaction_type = 'withdrawal'    AND quantity_delta = 0 AND cash_delta_rial < 0)
        OR (transaction_type = 'fee'           AND quantity_delta = 0 AND cash_delta_rial < 0)
        OR (transaction_type = 'tax'           AND quantity_delta = 0 AND cash_delta_rial < 0)
        OR (transaction_type = 'dividend'      AND quantity_delta = 0 AND cash_delta_rial > 0)
        OR (transaction_type = 'opening_position' AND quantity_delta > 0 AND cash_delta_rial = 0)
        OR (transaction_type IN ('transfer_in','transfer_out','adjustment','reversal'))),
    CONSTRAINT transactions_no_self_reverse CHECK (reverses_tx_id IS NULL OR reverses_tx_id <> id),
    CONSTRAINT transactions_id_portfolio_key UNIQUE (id, portfolio_id),
    CONSTRAINT transactions_account_portfolio_fk FOREIGN KEY (account_id, portfolio_id)
        REFERENCES portfolio.accounts(id, portfolio_id) ON DELETE RESTRICT,
    CONSTRAINT transactions_participant_portfolio_fk FOREIGN KEY (participant_id, portfolio_id)
        REFERENCES portfolio.participants(id, portfolio_id) ON DELETE RESTRICT,
    CONSTRAINT transactions_reverses_portfolio_fk FOREIGN KEY (reverses_tx_id, portfolio_id)
        REFERENCES portfolio.transactions(id, portfolio_id) ON DELETE RESTRICT
);

CREATE INDEX ix_transactions_portfolio_date ON portfolio.transactions (portfolio_id, effective_date);
CREATE INDEX ix_transactions_asset          ON portfolio.transactions (asset_id) WHERE asset_id IS NOT NULL;
CREATE INDEX ix_transactions_account        ON portfolio.transactions (account_id);

-- A given transaction may be reversed at most once.
CREATE UNIQUE INDEX uq_transactions_reverses
    ON portfolio.transactions (reverses_tx_id) WHERE reverses_tx_id IS NOT NULL;

-- v1.2 (item 15): reversal enforcement. A reversal auto-inherits the original's
-- portfolio/account/asset and negates its signed effects.
CREATE OR REPLACE FUNCTION portfolio.apply_reversal()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    orig portfolio.transactions%ROWTYPE;
BEGIN
    IF NEW.reverses_tx_id IS NULL THEN
        IF NEW.transaction_type = 'reversal' THEN
            RAISE EXCEPTION 'reversal requires reverses_tx_id';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.transaction_type <> 'reversal' THEN
        RAISE EXCEPTION 'only transaction_type=reversal may set reverses_tx_id';
    END IF;

    SELECT * INTO orig FROM portfolio.transactions WHERE id = NEW.reverses_tx_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reversed transaction % does not exist', NEW.reverses_tx_id;
    END IF;
    IF orig.reverses_tx_id IS NOT NULL THEN
        RAISE EXCEPTION 'cannot reverse a reversal (%)', orig.id;
    END IF;
    IF NEW.portfolio_id <> orig.portfolio_id THEN
        RAISE EXCEPTION 'reversal portfolio mismatch';
    END IF;

    -- Force exact inverse effects and identity inheritance.
    NEW.account_id      := orig.account_id;
    NEW.asset_id        := orig.asset_id;
    NEW.quantity_delta  := -orig.quantity_delta;
    NEW.cash_delta_rial := -orig.cash_delta_rial;
    IF NEW.effective_date IS NULL THEN
        NEW.effective_date := CURRENT_DATE;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_transactions_apply_reversal
    BEFORE INSERT ON portfolio.transactions
    FOR EACH ROW EXECUTE FUNCTION portfolio.apply_reversal();

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
    'Immutable ledger; only accounting source of truth. Signed effects + explicit reversal.';

-- ----------------------------------------------------------------------------
-- portfolio.positions   (derived/materialized cache)
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
-- v1.1: asset-level global price (no portfolio_id).
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
