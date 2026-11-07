-- Browser session secrets are random 256-bit values. Only SHA-256 hashes are
-- stored. This additive migration is safe to apply to an existing database.
CREATE TABLE IF NOT EXISTS auth.sessions (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CONSTRAINT session_expiry_check CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS ix_sessions_expiry ON auth.sessions (expires_at);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON auth.sessions (user_id);
