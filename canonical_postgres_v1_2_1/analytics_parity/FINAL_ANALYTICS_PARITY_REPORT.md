# Final Analytics Parity Report — v3.7 vs Canonical PostgreSQL v1.2.1

> Shadow migration + analytics v3.7 comparison. SQL Server فقط READ؛ هیچ production DB/code تغییر نکرد.

## 1. Freeze
- `analysis_cutoff_at` = `2026-09-24T20:41:02Z` · `analysis_as_of_date` = `2026-09-24`
- `reference_context.json`: SQL Server `codal`, view `dbo.vw_AIStockMetrics`, **ScoreVersion=v3.7**, reference rows **276**, columns **94**, TrackedTickers **282**.

## 2. Reference snapshot
`reference/v37_full_snapshot.csv` — تمام ۹۴ ستون، ۲۷۶ ردیف. الگوریتم مرجع: نسخه‌ی production (نه repo v3.6).

## 3. Universe manifest
`universe_manifest.csv`: ۲۸۲ symbol؛ include=۲۸۲؛ clusters=۲۷۷. (`build_universe_manifest.py`)

## 4. Full-universe canonical migration
Shadow DB `company_financial_analytics_shadow_v121`:
- identity: 273 companies / 273 securities، 0 duplicate ins، 0 name-only
- monthly_activities: 12,004 (subset=12,075 ✓)
- financial_facts: 71,361 (expected non-null mapped=71,361 ✓)
- price_observations: 705,812 (= MPH ✓)
- orphan=0، duplicate=0، unit ok

## 5. Canonical Input Gate
**FULL_UNIVERSE_INPUTS_PASS** (`full_universe_migration_validation.md`).

## 6. Analytics v3.7-compat
پیاده‌سازی جدا در `analytics_v37_compat/` (فقط read از canonical، بدون تغییر canonical data). لایه‌ها:
- L1 source selection، L2 monthly sales، L3 financial normalization، L4 TTM، L6 valuation، L7 market price، L9 ranks (reduced)، L10 weights، L11 QuantScore.

## 7. Metric parity (comparison_data + metric_comparison.md)
| reference column | compared | exact | within tol | mismatch |
| --- | --- | --- | --- | --- |
| SalesLast12M | 273 | 83 | 0 | 190 |
| SalesPrev12M | 273 | 83 | 0 | 190 |
| SalesGrowth12M | 273 | 89 | 181 | 3 |
| TTMNetProfit | 273 | 16 | 0 | 257 |
| PEApprox | 273 | 28 | 4 | 241 |
| OperatingMargin12M | 273 | 131 | 6 | 136 |
| NetProfitMargin12M | 273 | 171 | 84 | 18 |
| ROE | 273 | 171 | 86 | 16 |
| **QuantScore** | 273 | **0** | 0 | **273** |

## 8. Population parity — FAIL
v3.7=276 vs canonical=273 vs intersection=273. یکسان نبودن population ⇒ rank/percentile parity ممکن نیست.

## 9. Reproducibility — PASS
دو بار اجرا، hash یکسان (`reproducibility.md`).

## 10. Point-in-Time — PASS
observation با `collected_at > cutoff` = 0؛ فقط `<= cutoff` مصرف شد (`point_in_time_safety.md`).

## 11. Stored test analytics (shadow only)
`analytics.score_runs` با `score_version='v3.7-compat'` + ۲۷۳ ردیف `company_scores` ثبت شد (`_stored_score_run.txt`).

## 12. Issues
`issues.md`: هیچ `UNKNOWN` mismatch نیست؛ اما `LOGIC_DIFFERENCE` و `POPULATION_DIFFERENCE` باقی است. هیچ mismatch مخفی نشد و canonical data برای match کردن legacy خراب نشد.

---

# Analytics Parity Gate

## ANALYTICS_PARITY_FAIL

معیارهای PASS برآورده نشد:
- ❌ full v3.7 factor/rank reproduction incomplete (۱۹ فاکتور؛ فقط زیرمجموعه).
- ❌ population parity (276 vs 273).
- ❌ QuantScore parity = 0%.
- ✅ canonical input parity PASS.
- ✅ reproducibility PASS.
- ✅ point-in-time PASS.
- ✅ هیچ UNKNOWN mismatch.

**blocker اصلی:** بازتولید دقیق کل خط لوله‌ی rank/percentile/NULL/tie و فاکتورهای v3.7 (و هم‌ترازی population با view اصلی) هنوز پیاده نشده است. canonical data جای خود محفوظ است و هیچ workaround legacy به آن تزریق نشد.


## Secret Safety
- ??? connection string/password/token ??????? ???? ?? ????????/CSV?? ????? ???? credential ??? ?? ???? ???? ?? `.env` ?????? ??.
- ????? substring ?? **false positive** ???: `DB_PASSWORD` ?? ??? ????? ??? ?? ?????? ?????? ???? ????? ???? CSV?? (snapshot/reference) ???? ??????. ??? ?? ????? ?????? ??? ?????? ???? ???? ?? ??????? credential.
