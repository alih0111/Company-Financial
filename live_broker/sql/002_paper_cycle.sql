BEGIN;

CREATE TABLE IF NOT EXISTS broker_execution.paper_pools (
    pool_id text PRIMARY KEY,
    policy jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_execution.paper_accounts (
    broker_id text NOT NULL CHECK (broker_id = 'paper'),
    account_id text NOT NULL,
    pool_id text NOT NULL REFERENCES broker_execution.paper_pools,
    opening_cash_rial bigint NOT NULL CHECK (opening_cash_rial >= 0),
    reconciliation_blocked boolean NOT NULL DEFAULT false,
    PRIMARY KEY (broker_id, account_id),
    FOREIGN KEY (broker_id, account_id) REFERENCES broker_execution.accounts
);
ALTER TABLE broker_execution.positions ADD COLUMN IF NOT EXISTS managed_shares bigint NOT NULL DEFAULT 0;
ALTER TABLE broker_execution.accounts ADD COLUMN IF NOT EXISTS reconciliation_required boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS broker_execution.paper_assets (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    instrument_id text NOT NULL,
    symbol text NOT NULL,
    industry text NOT NULL,
    opening_shares bigint NOT NULL CHECK (opening_shares >= 0),
    opening_managed bigint NOT NULL CHECK (opening_managed BETWEEN 0 AND opening_shares),
    quote jsonb,
    rules jsonb,
    PRIMARY KEY (broker_id, account_id, instrument_id),
    UNIQUE (broker_id, account_id, symbol),
    FOREIGN KEY (broker_id, account_id) REFERENCES broker_execution.paper_accounts
);
CREATE TABLE IF NOT EXISTS broker_execution.paper_decisions (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    decision_id text NOT NULL,
    session date NOT NULL,
    decided_at timestamptz NOT NULL,
    valid_until timestamptz,
    ranking_digest text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (broker_id, account_id, decision_id),
    UNIQUE (broker_id, account_id, session),
    FOREIGN KEY (broker_id, account_id) REFERENCES broker_execution.paper_accounts
);
ALTER TABLE broker_execution.orders ADD COLUMN IF NOT EXISTS decision_id text;
ALTER TABLE broker_execution.orders ADD COLUMN IF NOT EXISTS admitted_at timestamptz;

CREATE TABLE IF NOT EXISTS broker_execution.paper_tickets (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    instrument_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('BUY','SELL')),
    shares bigint NOT NULL,
    limit_rial bigint NOT NULL,
    fee_reserve_rial bigint NOT NULL,
    expired boolean NOT NULL DEFAULT false,
    PRIMARY KEY (broker_id, account_id, intent_id),
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.orders
);
CREATE TABLE IF NOT EXISTS broker_execution.paper_attempts (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    session date NOT NULL,
    elapsed_sessions integer NOT NULL CHECK (elapsed_sessions > 0),
    event_digest text NOT NULL,
    reason text NOT NULL,
    fill_id text,
    executed_at timestamptz,
    shares bigint NOT NULL DEFAULT 0,
    price_rial bigint,
    fee_rial bigint,
    booked boolean NOT NULL DEFAULT false,
    PRIMARY KEY (broker_id, account_id, intent_id, session),
    UNIQUE (broker_id, account_id, intent_id, elapsed_sessions),
    UNIQUE (broker_id, account_id, fill_id),
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.paper_tickets
);
CREATE TABLE IF NOT EXISTS broker_execution.paper_reconciliations (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker_id text NOT NULL,
    account_id text NOT NULL,
    decision_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    state text NOT NULL,
    reasons jsonb NOT NULL,
    FOREIGN KEY (broker_id, account_id, decision_id) REFERENCES broker_execution.paper_decisions
);
COMMIT;
