# SHADOW V1 — LIVE OPERATIONAL FAILURE LOG (append-only; SHADOW_V1_SPEC §16)

Append-only log of data gaps, identity issues, late data, collector failures,
suspensions, unexpected corporate actions, execution ambiguity, and accounting
exceptions observed during the forward shadow period. Past shadow decisions are never
patched retrospectively.

- [2026-10-03T19:05:00Z] LOG CREATED at spec freeze (no shadow month ingested yet; the
  state file decision list is empty).
- [2026-10-03T19:05:00Z] DATA-CONTRACT FINDING (pre-start observation, documented in
  spec §5a/§5b): `market.price_observations` (source `brs`, series `adjusted`,
  `adjustment_method='vendor_adjusted'`/`legacy_brs_adjusted`) contains (a) phantom
  carry-over sessions — e.g. 2026-10-02 (Friday) rows are byte-identical re-stamps of the
  2026-09-30 session for 276/282 securities, and a 2026-09-26 row for فولاد re-stamps the
  2026-09-24 snapshot while the real Saturday close (3260, per raw cache) is missing from
  the DB; (b) multiple intraday snapshots per (security, trade_date) (1,420 duplicate
  pairs); (c) token holiday sessions (2026-09-27: 5 securities). Mitigation frozen in
  spec: path-A prices come only from raw closing caches; calendar excludes Thu/Fri and
  requires breadth >= 30; path-B is diagnostic-only.
- [2026-10-03T19:05:00Z] COLLECTION-LAG OBSERVATION: raw closing caches (238 files) were
  last refreshed 2026-10-01 22:57–23:03 local, covering sessions through 2026-09-30; the
  2026-10-02/10-03 sessions are not yet in the caches. Shadow observations finalize only
  when caches cover E (or the §15b 7-day deadline fires with DATA_MISSING).
- [2026-10-03T19:05:00Z] COVERAGE OBSERVATION: last pre-freeze production run scored 271
  companies; 238 have raw price caches; 235 are in the certified identity map (36 are
  DB-resolved only, newer than the map). If an unpriceable name is selected, its target
  stays cash per the frozen failed-target rule and is reported monthly.
- [2026-10-03T19:05:00Z] IDENTITY QUARANTINE (from live pipeline log): Codal canonical
  sync reports an identity-quarantine backlog of 18 retriable documents
  (`QUARANTINED_IDENTITY`); does not affect scored companies but is monitored here.

- [2026-10-03T19:44:50Z] LAUNCH CERTIFICATION (user directive 2026-10-03, post-acceptance): V1 harness accepted technically;
  live-start certification performed per Parts 1-11. Verdicts recorded in SHADOW_V1_LAUNCH_CERTIFICATION.md/.json.
- [2026-10-03T19:44:50Z] Part 2 verdict: V1 monthly rule ("earliest qualifying run whose as_of falls in a strictly later
  calendar month") = FAIL as written (fires mid-month on real production stamps; historical rule is
  as_of = last canonical trading date of the month, cutoff EOD UTC, recovered from all 63 certified dates).
  NOT launched under V1. Superseding pre-first-decision spec SHADOW_V1_1_SPEC.md frozen
  (sha256 f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e); V1 spec preserved unchanged.
- [2026-10-03T19:44:50Z] Part 3: mid-session guard classified OPERATIONAL_ONLY; V1.1 freezes it as a two-sided window
  (12:45 Tehran post-close operational lower bound; EOD-UTC-as_of historical upper bound). Guard can only
  disqualify, never shift, a decision.
- [2026-10-03T19:44:50Z] HARNESS DEFECT (found by Part 6/7 diagnostics, fixed pre-first-use): raw_caches_max_date() parsed
  cache filenames with Path.stem, leaking ".json" into ins_code; the function would always have returned
  None and every observation would have finalized by the 7-day deadline as DATA_MISSING. Fixed to strip
  the full ".json.gz" suffix. Never exercised on any observation.
- [2026-10-03T19:44:50Z] One aborted partial refresh cycle (pre-fix filename parse) was killed within 25 fetches; its
  writes were merge-append only and idempotent; the certified cycle evidence is the completed corrected run.
- [2026-10-03T19:44:50Z] Part 6: one genuine post-freeze refresh cycle completed (all fetches after the freeze instant;
  session 2026-10-03 acquired; raw pClosing retained; 0 failures; coverage 271/271 scored companies;
  172 same-day late arrivals skipped; 2207 vendor revisions ignored - field audit shows 0 pClosing changes).
- [2026-10-03T19:44:50Z] Part 7: identity onboarding executed - 235 HISTORICAL_MAP_VERIFIED + 36 FORWARD_MAP_VERIFIED,
  0 UNRESOLVED / 0 AMBIGUOUS, append-only ledger identity_onboarding_ledger.jsonl batch
  ONBOARD-20261003T193414Z. Fill gate: only verified identities receive paper fills.
- [2026-10-03T19:44:50Z] Parts 9-10: no genuinely qualifying production run exists yet (predicate audit of all 12
  canonical-v1-dev runs: 0 pass the V1.1 rule); Decision #1 not created; forward 12-cycle clock NOT started.
