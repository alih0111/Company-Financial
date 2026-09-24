-- ============================================================================
-- 060_auth.sql  —  users and view events
-- DO NOT EXECUTE in this phase.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- auth.users
-- Replaces dbo.Users.
-- Removed vs legacy:
--   * no `Token` column (JWT/session lives outside DB; use a session store)
--   * no persistent `IsOnline` boolean (derive from sessions / last_seen)
--   * `ViewedItems` JSON removed -> normalized in auth.user_view_events
-- Case-insensitive uniqueness via citext.
-- ----------------------------------------------------------------------------
CREATE TABLE auth.users (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    username      citext      NOT NULL,
    email         citext,
    password_hash text        NOT NULL,               -- bcrypt/argon2 hash only
    is_admin      boolean     NOT NULL DEFAULT false,
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT users_username_not_blank CHECK (length(btrim(username)) > 0)
);

CREATE UNIQUE INDEX uq_users_username ON auth.users (username);
CREATE UNIQUE INDEX uq_users_email    ON auth.users (email) WHERE email IS NOT NULL;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON auth.users
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

COMMENT ON TABLE auth.users IS
    'User accounts. No tokens stored; case-insensitive username/email uniqueness.';

-- ----------------------------------------------------------------------------
-- auth.user_view_events
-- Normalizes legacy Users.ViewedItems JSON into events. Aggregates are computed
-- in queries/materialized views, not stored here.
-- ----------------------------------------------------------------------------
CREATE TABLE auth.user_view_events (
    id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    security_id uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    viewed_at   timestamptz NOT NULL DEFAULT now(),
    source      text,
    metadata    jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX ix_user_view_events_user_time ON auth.user_view_events (user_id, viewed_at DESC);
CREATE INDEX ix_user_view_events_security  ON auth.user_view_events (security_id) WHERE security_id IS NOT NULL;
