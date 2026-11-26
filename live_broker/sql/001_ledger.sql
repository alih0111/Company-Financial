BEGIN;
CREATE SCHEMA IF NOT EXISTS broker_execution;

CREATE TABLE IF NOT EXISTS broker_execution.accounts (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    cash_rial bigint NOT NULL,
    stopped boolean NOT NULL DEFAULT true,
    lease_owner text,
    lease_until timestamptz,
    fence bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (broker_id, account_id)
);

CREATE TABLE IF NOT EXISTS broker_execution.controls (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    stopped boolean NOT NULL DEFAULT true
);
INSERT INTO broker_execution.controls DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS broker_execution.positions (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    instrument_id text NOT NULL,
    shares bigint NOT NULL,
    PRIMARY KEY (broker_id, account_id, instrument_id),
    FOREIGN KEY (broker_id, account_id) REFERENCES broker_execution.accounts
);

CREATE TABLE IF NOT EXISTS broker_execution.orders (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    instrument_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('BUY','SELL')),
    shares bigint NOT NULL CHECK (shares > 0),
    limit_rial bigint NOT NULL CHECK (limit_rial > 0),
    fee_reserve_rial bigint NOT NULL CHECK (fee_reserve_rial >= 0),
    policy_version text NOT NULL,
    risk_reason text NOT NULL,
    state text NOT NULL CHECK (state IN ('CREATED','RISK_REJECTED','APPROVED','SUBMITTING','UNKNOWN',
        'ACKNOWLEDGED','PARTIALLY_FILLED','FILLED','CANCEL_REQUESTED','CANCELED','REJECTED','EXPIRED')),
    filled_shares bigint NOT NULL DEFAULT 0 CHECK (filled_shares BETWEEN 0 AND shares),
    reserved_rial bigint NOT NULL DEFAULT 0 CHECK (reserved_rial >= 0),
    reserved_shares bigint NOT NULL DEFAULT 0 CHECK (reserved_shares >= 0),
    submit_fence bigint,
    PRIMARY KEY (broker_id, account_id, intent_id),
    FOREIGN KEY (broker_id, account_id) REFERENCES broker_execution.accounts
);

CREATE TABLE IF NOT EXISTS broker_execution.outbox (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    PRIMARY KEY (broker_id, account_id, intent_id),
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.orders
);

CREATE TABLE IF NOT EXISTS broker_execution.events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    event text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    detail jsonb NOT NULL DEFAULT '{}',
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.orders
);

CREATE TABLE IF NOT EXISTS broker_execution.fills (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    fill_id text NOT NULL,
    intent_id text NOT NULL,
    executed_at timestamptz NOT NULL,
    shares bigint NOT NULL CHECK (shares > 0),
    price_rial bigint NOT NULL CHECK (price_rial > 0),
    fee_rial bigint NOT NULL CHECK (fee_rial >= 0),
    PRIMARY KEY (broker_id, account_id, fill_id),
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.orders
);
COMMIT;
