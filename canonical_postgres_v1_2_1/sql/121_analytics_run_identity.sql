-- 121: analytics run identity + exact input watermark + run-scoped snapshots.
--
-- WHY THIS EXISTS
-- The served score used to be selected by `ORDER BY as_of_date DESC, started_at DESC`.
-- `as_of_date` is a *data* date (the PIT visibility date), not a *run* property. Two
-- consequences broke the refresh pipeline:
--
--   1. A run computed from newer data could carry an earlier as_of than an existing
--      run, so it was never selected ("as_of regression"), and
--   2. Two runs sharing an as_of could not both store `metric_snapshots`, because the
--      unique key was (as_of_date, company_id, metric_code, calculation_version) and
--      the store path had no ON CONFLICT — the recompute aborted on a unique violation.
--
-- The fix separates three concepts:
--   * as_of_date       -> data visibility date (PIT filter + display). Unchanged.
--   * input_watermark  -> exact fingerprint of the inputs a run consumed (staleness).
--   * run_seq          -> monotonic run recency; the key the read path selects on.
--
-- metric_snapshots becomes run-scoped, so re-scoring the same as_of over corrected
-- inputs is a NEW row under a NEW run instead of an aborted transaction. The PIT series
-- stays queryable by (metric_code, as_of_date); the append-only triggers stay in force
-- (corrections are new runs, never mutations).
--
-- Contract: integration_shadow_v1/ANALYTICS_REFRESH_CONTRACT.md

-- ---------------------------------------------------------------------------
-- analytics.score_runs: run_seq (monotonic recency)
-- ---------------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS analytics.score_runs_run_seq_seq;

ALTER TABLE analytics.score_runs ADD COLUMN IF NOT EXISTS run_seq bigint;

-- Backfill in true chronological order. `protect_score_run_identity` only guards the
-- identity columns (score_version/as_of_date/source_cutoff_at/started_at/code_version/
-- parameters), so touching run_seq is allowed by the trigger.
UPDATE analytics.score_runs sr
   SET run_seq = s.rn
  FROM (SELECT id, row_number() OVER (ORDER BY started_at, id) AS rn
          FROM analytics.score_runs) s
 WHERE sr.id = s.id AND sr.run_seq IS NULL;

ALTER TABLE analytics.score_runs
    ALTER COLUMN run_seq SET DEFAULT nextval('analytics.score_runs_run_seq_seq');

SELECT setval('analytics.score_runs_run_seq_seq',
              GREATEST((SELECT COALESCE(max(run_seq), 1) FROM analytics.score_runs), 1));

ALTER TABLE analytics.score_runs ALTER COLUMN run_seq SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_score_runs_run_seq
    ON analytics.score_runs (run_seq);

-- ---------------------------------------------------------------------------
-- analytics.score_runs: input_watermark + run_kind
-- ---------------------------------------------------------------------------
ALTER TABLE analytics.score_runs
    ADD COLUMN IF NOT EXISTS input_watermark jsonb NOT NULL DEFAULT '{}'::jsonb;

-- run_kind gates *serving*: only orchestrate_refresh.py may write 'serving'. Ad-hoc or
-- historical/PIT invocations write 'pit_backfill' and can never be served as current.
ALTER TABLE analytics.score_runs
    ADD COLUMN IF NOT EXISTS run_kind text NOT NULL DEFAULT 'serving';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'score_runs_run_kind_chk') THEN
        ALTER TABLE analytics.score_runs
            ADD CONSTRAINT score_runs_run_kind_chk
            CHECK (run_kind IN ('serving', 'pit_backfill'));
    END IF;
END $$;

-- The read path's selector: newest completed serving run for a version.
CREATE INDEX IF NOT EXISTS ix_score_runs_serving
    ON analytics.score_runs (score_version, run_seq DESC)
    WHERE status = 'completed' AND run_kind = 'serving';

-- ---------------------------------------------------------------------------
-- analytics.metric_snapshots: run-scoped identity
-- ---------------------------------------------------------------------------
ALTER TABLE analytics.metric_snapshots
    ADD COLUMN IF NOT EXISTS run_id uuid REFERENCES analytics.score_runs(id);

-- store_run writes the run row and its snapshots in ONE transaction, so `now()` (the
-- transaction timestamp) is identical for `score_runs.started_at` and
-- `metric_snapshots.created_at`. That is the exact, verified backfill key (60,399/60,399
-- rows mapped, zero collisions under the new key).
--
-- The append-only trigger is disabled only for this one-time structural backfill; it is
-- re-enabled immediately and the whole migration runs in one transaction, so a failure
-- rolls the trigger state back with everything else.
ALTER TABLE analytics.metric_snapshots DISABLE TRIGGER USER;

UPDATE analytics.metric_snapshots ms
   SET run_id = sr.id
  FROM analytics.score_runs sr
 WHERE sr.started_at = ms.created_at AND ms.run_id IS NULL;

ALTER TABLE analytics.metric_snapshots ENABLE TRIGGER USER;

-- Fail loudly rather than silently leaving history unattributable.
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n FROM analytics.metric_snapshots WHERE run_id IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION
            'metric_snapshots.run_id backfill incomplete: % rows have no producing run', n;
    END IF;
END $$;

ALTER TABLE analytics.metric_snapshots ALTER COLUMN run_id SET NOT NULL;

-- Replace the as_of-scoped key (which made a same-as_of recompute unstorable) with a
-- run-scoped key (which makes it storable and auditable).
DROP INDEX IF EXISTS analytics.uq_metric_snapshots_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_snapshots_run_key
    ON analytics.metric_snapshots (run_id, company_id, metric_code);

COMMENT ON COLUMN analytics.score_runs.run_seq IS
    'Monotonic run recency. The read path selects the newest completed serving run by this, not by as_of_date (see ANALYTICS_REFRESH_CONTRACT.md).';
COMMENT ON COLUMN analytics.score_runs.input_watermark IS
    'Per-domain fingerprint (max data date, arrival, row count, content digest) of the inputs this run consumed. Staleness = current watermark != this value.';
COMMENT ON COLUMN analytics.score_runs.run_kind IS
    'serving = written by orchestrate_refresh (selectable as current); pit_backfill = ad-hoc/historical (never served as current).';
COMMENT ON COLUMN analytics.metric_snapshots.run_id IS
    'Producing score run. Snapshots are run-scoped; the PIT series is read by (metric_code, as_of_date).';
