BEGIN;

CREATE TABLE IF NOT EXISTS broker_execution.submission_receipts (
    broker_id text NOT NULL,
    account_id text NOT NULL,
    intent_id text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('acknowledged', 'rejected', 'unknown')),
    provider_order_id text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (broker_id, account_id, intent_id),
    UNIQUE (broker_id, account_id, provider_order_id),
    FOREIGN KEY (broker_id, account_id, intent_id) REFERENCES broker_execution.orders,
    CHECK ((outcome = 'acknowledged') = (provider_order_id IS NOT NULL))
);

COMMIT;
