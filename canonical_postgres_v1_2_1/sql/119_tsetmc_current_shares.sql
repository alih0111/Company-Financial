-- 119: TSETMC current share snapshots (current-share-source contract, 2026-10-02).
-- PRIMARY current shares for the production UI score. Rows are written ONLY by the
-- collector with the REAL acquisition timestamp (collected_at = now at fetch time);
-- collected_at is never backdated or rewritten. The Engine selects the latest row per
-- security with collected_at <= run cutoff; if none is eligible it falls back to
-- core.share_structure (BRS), and if both are missing the existing valuation penalty
-- applies. Historical (market_pit='trade_date') runs never read this table.

CREATE TABLE IF NOT EXISTS market.tsetmc_current_shares (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id uuid NOT NULL REFERENCES core.securities(id) ON DELETE RESTRICT,
    shares_count bigint NOT NULL CHECK (shares_count > 0),
    source text NOT NULL DEFAULT 'TSETMC_ZTITAD_CURRENT',
    collected_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tsetmc_current_shares_sec_time
    ON market.tsetmc_current_shares (security_id, collected_at DESC);

COMMENT ON TABLE market.tsetmc_current_shares IS
    'TSETMC zTitad current share snapshots; PRIMARY current-share source for the UI score (contract: UI_SCORE_CURRENT_SOURCE_CONTRACT.md). collected_at is the real acquisition time and is immutable.';
