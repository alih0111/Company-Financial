# Exact v3.7 Compatibility Debugging — Final Report

Status: **v3.7 parity reproduced for the exact 276-subject scoring population**
using an isolated compatibility model. No canonical company/security/fact and no
production code/DB was modified. SQL Server was SELECT-only.

## 1. Gate summary

| item | result |
| --- | --- |
| Population parity (276 = 276, diff 0) | **POPULATION_PARITY_PASS** |
| Base metrics (sales, TTMNetProfit, margins, ROE, PEApprox) | **0 mismatch** |
| 21 factor populations / ranks | **0 mismatch** (max residual = 4-decimal rounding) |
| QuantScore | **276/276 exact** |
| Reproducibility (2 runs, identical hash) | **PASS** (`eefcebfb…ca5c7c`) |
| canonical inputs (`FULL_UNIVERSE_INPUTS_PASS`) | unchanged |

## 2. Discrepancy found in the repository

`canonical_postgres_v1_2_1/analytics_parity/_comparison_summary.json` is
**stale/corrupt**: every metric repeats one identical stats tuple
(`exact=171, within=86, mismatch=16, max_abs=2813.5779`) that contradicts
`comparison_metrics.csv` (e.g. SalesLast12M = 83 exact / 190 mismatch).

Resolution: raw CSV is authoritative; `_comparison_summary.json` is ignored.
The compatibility driver now regenerates a per-metric summary
(`comparison_data/_comparison_summary_legacy_full.json`) and contains a
regression guard that aborts if all metric summaries share identical statistics.

## 3. Root causes identified

1. **Unit scaling** — canonical monetary facts are in `rial`; v3.7 monetary
   columns are in `million rial`. Values differed by exactly `1e6`.
2. **TTM semantics** — the reduced compat returned `d[1]` when p2/p3 were missing
   instead of following v3.7's amount-path → Product1-path → NULL.
3. **Latest-report selection** — facts were read across all statements with a
   nondeterministic overwrite instead of the latest report (`ProfitDedup rn=1`).
4. **Share count** — used `capital/1000`; correct is `capital/1e6`
   (= legacy `Num2_Value1`, = `ImpliedShares = Product1/EPS`).
5. **Latest price** — used closing only; correct is `COALESCE(last, close)`.
6. **OperatingProfit per-share** — missing `OpK/OpAbs/OpAmt` normalization.
7. **Volatility** — `LAG` over `ORDER BY trade_date DESC` uses the **more recent**
   row; window is rn 2..30 (29 returns), not rn 1..30.
8. **Operating growth fallbacks** — required strict 100× scale guard (no
   zero-escape); and `OpAbs` must use the **real legacy `Product1`**, not
   `EPS×Num2_Value1` (Num2_Value1 has mixed scale across some reports).
9. **Population** — v3.7 = `mahane ∪ miandore2` (276); canonical = `TrackedTickers ∩
   MarketPriceHistory` (273), plus many-to-one market merges (کسرا).

## 4. Compatibility model (COMPATIBILITY_ONLY_NOT_CANONICAL)

Separate from canonical identity, in `compat_v37` schema on the shadow DB and in
`analytics_parity_debug/`:

| artifact | purpose |
| --- | --- |
| `v37_scoring_subjects.csv` | exact 276 legacy scoring subjects + nullable canonical mapping |
| `population_exact_diff.csv` | exact subject-set diff (0/0) |
| `reference/legacy_v37_financial_inputs.csv` | frozen legacy financial columns (read-only) incl. `Product1` |
| `reference/legacy_v37_monthly_inputs.csv` | frozen legacy monthly `Value3` |
| `reference/legacy_v37_market_inputs.csv` | frozen per-CompanyID market rows (fixes کسرا merge) |
| `compat_v37.scoring_subjects` | disposable shadow table, documented `COMPATIBILITY_ONLY_NOT_CANONICAL` |

`Product1`, `NPUnitRatio`, `OpK`, `OpAmt` and legacy scale decisions are emulated
**inside the compatibility layer only** from the frozen snapshot; they are never
written into `fundamentals.financial_facts`.

## 5. Reproduction

```powershell
$py = "C:\Users\aliheyd\AppData\Local\Temp\opencode\pgtest_venv\Scripts\python.exe"
$env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
& $py canonical_postgres_v1_2_1\analytics_v37_compat\build_v37_compat_population.py
& $py canonical_postgres_v1_2_1\analytics_v37_compat\compute_v37_legacy_full.py
```

Outputs: `metric_comparison_legacy_full.md`, `comparison_data/computed_legacy_full.csv`,
`_comparison_summary_legacy_full.json`, `_compute_hash_legacy_full.txt`.

## 6. Interpretation / limits

* This proves the **v3.7 compatibility oracle** can be reproduced exactly over the
  correct population from frozen legacy inputs.
* The **canonical-driven** derivation (`compute_v37_faithful.py`, no frozen
  snapshot) remains 8 TTMNetProfit / 7 PEApprox mismatches for subjects whose
  amount path is NULL and which rely on the non-migratable legacy `Product1`, and
  excludes the 5 no-price subjects. Those are documented
  `LEGACY_DERIVED_NOT_MIGRATED`, not arithmetic bugs.
* `compat_v37.*` is disposable test/compat state, not Canonical PostgreSQL v1.2.1.
