-- Durable, per-account data budgets. No response bodies, raw IPs or portfolios
-- are recorded here. Apply as the schema owner before deploying the new API.
CREATE TABLE IF NOT EXISTS auth.data_policies (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT true,
    requests_limit integer NOT NULL CHECK (requests_limit BETWEEN 10 AND 10000),
    records_limit integer NOT NULL CHECK (records_limit BETWEEN 100 AND 200000),
    bytes_limit bigint NOT NULL CHECK (bytes_limit BETWEEN 65536 AND 268435456),
    symbols_limit integer NOT NULL CHECK (symbols_limit BETWEEN 1 AND 1000),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS auth.data_usage (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    day date NOT NULL,
    requests bigint NOT NULL DEFAULT 0 CHECK (requests >= 0),
    records bigint NOT NULL DEFAULT 0 CHECK (records >= 0),
    bytes bigint NOT NULL DEFAULT 0 CHECK (bytes >= 0),
    symbols integer NOT NULL DEFAULT 0 CHECK (symbols >= 0),
    denied bigint NOT NULL DEFAULT 0,
    last_denial text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS auth.data_targets (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    day date NOT NULL,
    target_hash bytea NOT NULL CHECK (octet_length(target_hash) = 32),
    PRIMARY KEY (user_id, day, target_hash)
);
CREATE TABLE IF NOT EXISTS auth.data_ip_usage (
    day date NOT NULL,
    ip_hash bytea NOT NULL CHECK (octet_length(ip_hash) = 32),
    requests bigint NOT NULL DEFAULT 0,
    records bigint NOT NULL DEFAULT 0,
    bytes bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (day, ip_hash)
);
CREATE INDEX IF NOT EXISTS ix_data_usage_day ON auth.data_usage(day);
CREATE INDEX IF NOT EXISTS ix_data_targets_day ON auth.data_targets(day);
