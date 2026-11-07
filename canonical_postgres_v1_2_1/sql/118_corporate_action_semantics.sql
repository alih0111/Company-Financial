-- 118: corporate-action semantics/evidence status (RETURN_SERIES_CORPORATE_ACTION_INTEGRITY
-- hardening, 2026-10-02). TASK 3 schema boundary, option B: one table holds both the
-- mechanical adjustment fact and the (separately graded) semantic label.
--
--   event_semantics_status   grades the SEMANTIC claim (action_type):
--     CONFIRMED    independent source evidence (e.g. TSETMC share-change record) supports it
--     INFERRED     refinement derived from announcement text (e.g. funding source in LT28)
--     UNCLASSIFIED no semantic evidence; the row is a mechanical price adjustment only
--   adjustment_evidence_status grades the MECHANICAL fact (discontinuity + factor):
--     CONFIRMED    exchange-declared reference re-base (official gap rule), factor reproducible
--     INVALID      reserved for rejections (ordinary moves must never enter this table)
--
-- The return builder consumes adjustment_factor + action_date with
-- adjustment_evidence_status = 'CONFIRMED'; it never requires a semantic label.
-- Idempotent: safe to re-run.

ALTER TABLE market.corporate_actions
    ADD COLUMN IF NOT EXISTS event_semantics_status text;
ALTER TABLE market.corporate_actions
    ADD COLUMN IF NOT EXISTS adjustment_evidence_status text;

ALTER TABLE market.corporate_actions DROP CONSTRAINT IF EXISTS corporate_actions_semantics_status_check;
ALTER TABLE market.corporate_actions
    ADD CONSTRAINT corporate_actions_semantics_status_check
    CHECK (event_semantics_status IS NULL OR
           event_semantics_status IN ('CONFIRMED', 'INFERRED', 'UNCLASSIFIED'));

ALTER TABLE market.corporate_actions DROP CONSTRAINT IF EXISTS corporate_actions_evidence_status_check;
ALTER TABLE market.corporate_actions
    ADD CONSTRAINT corporate_actions_evidence_status_check
    CHECK (adjustment_evidence_status IS NULL OR
           adjustment_evidence_status IN ('CONFIRMED', 'INVALID'));

COMMENT ON COLUMN market.corporate_actions.event_semantics_status IS
    'Grade of the semantic action_type claim: CONFIRMED (independent evidence, e.g. TSETMC share-change record) / INFERRED (announcement-text refinement) / UNCLASSIFIED (price adjustment only, no semantic evidence)';
COMMENT ON COLUMN market.corporate_actions.adjustment_evidence_status IS
    'Grade of the mechanical adjustment fact: CONFIRMED (exchange-declared reference re-base per official gap rule) / INVALID (reserved for rejections)';
