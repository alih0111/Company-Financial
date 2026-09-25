# v3.7 Golden Regression Oracle — Manifest

**COMPATIBILITY_ONLY_NOT_CANONICAL — NOT PRODUCTION, NOT CANONICAL, FROZEN.**

This oracle is a regression/reference artifact. It reproduces production
`dbo.vw_AIStockMetrics` (ScoreVersion `v3.7`) exactly over the exact 276-subject
legacy scoring population. It is **not** the future analytics architecture and must
**not** be the source of production analytics.

## Why it is not canonical

* It depends on **legacy-derived fields** that were intentionally never migrated to
  canonical facts: `Product1`, `Num1_Value*`, `Num2_Value*`, and the
  `NPUnitRatio` / `OpK` / `OpAmt` unit heuristics.
* It consumes a **frozen legacy CSV snapshot** taken read-only from SQL Server
  (`analytics_parity_debug/reference/legacy_v37_*.csv`).
* Its population (`mahane ∪ miandore2`, 276) is a legacy eligibility rule, not a
  canonical identity policy.

## Frozen output

| item | value |
| --- | --- |
| golden hash | `849a4efd49711101eb5e29c719d8c233efa0d7e6c928d47b21882540cbbac264` |
| subjects | 276 (ordered by legacy `CompanyID`) |
| golden output | `golden_output.json` |
| golden hash file | `golden_hash.txt` |
| artifact hashes | `_artifact_hashes.json` |
| oracle test | `test_oracle_golden.py` (3 passed) |

Parity achieved: base metrics 0 mismatch · 21 factor ranks exact · QuantScore
276/276 exact · reproducibility PASS · SQL Server SELECT-only · canonical untouched.

## Golden output surface

Per subject: ordered `legacy_company_id`; base metrics (sales, TTM net profit,
margins, ROE, price, PEApprox, EPS, growths); 21 factor ranks; penalties
(`GrowthPenalty`, `ProfitabilityPenalty`, `ValuationPenalty`, `MarketPenalty`);
category scores (`GrowthScore`, `ProfitabilityScore`, `ValuationScore`,
`MarketScore`, `DataQualityScore`); `QuantScore`.

## Change policy (frozen)

From now on, without an explicit version bump and a `freeze_oracle.py` re-run, the
following must not change:

* factor weights
* population
* NULL / rank / tie behavior
* `Product1` emulation

Any intentional semantic change requires a new version and a new golden hash.

## Code / inputs

| artifact | location |
| --- | --- |
| oracle driver | `analytics_v37_compat/compute_v37_legacy_full.py` |
| pipeline | `analytics_v37_compat/compute_v37_faithful.py` |
| population builder | `analytics_v37_compat/build_v37_compat_population.py` |
| 276 subjects | `analytics_parity_debug/v37_scoring_subjects.csv` |
| reference snapshot (94 cols) | `analytics_parity/reference/v37_full_snapshot.csv` |
| frozen legacy inputs | `analytics_parity_debug/reference/legacy_v37_{financial,monthly,market}_inputs.csv` |
| shadow compat table | `compat_v37.scoring_subjects` (COMPATIBILITY_ONLY_NOT_CANONICAL) |

## Re-freeze (intentional only)

```powershell
$py = "C:\Users\aliheyd\AppData\Local\Temp\opencode\pgtest_venv\Scripts\python.exe"
& $py canonical_postgres_v1_2_1\analytics_v37_oracle\freeze_oracle.py
& $py -m pytest canonical_postgres_v1_2_1\analytics_v37_oracle -q
```
