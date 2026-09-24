# v1.2 → v1.2.1 Change Log (Pre-execution Patch)

> patch محدود؛ redesign نیست. هیچ DDL/migration اجرا نشده. هیچ production code تغییر نکرده.

| # | موضوع | v1.2 | v1.2.1 | فایل |
| --- | --- | --- | --- | --- |
| 1 | Duplicate index | `ix_price_observations_cutoff` در 050 و 090 | فقط در 050؛ حذف از 090 | `sql/050_market.sql`, `sql/090_indexes.sql` |
| 2 | Test count | README = 52 | README = 74 (auto) | `README.md`, `integrity_test_plan.md` |
| 3 | Report→Company consistency | فقط company_id در normalized | `UNIQUE(id, company_id)` روی reports + composite FK `(report_id, company_id)` | `sql/020_ingestion.sql`, `sql/040_fundamentals.sql` |
| 4 | parse_runs lifecycle | فقط identity frozen | state machine terminal + finished_at rule | `sql/020_ingestion.sql` |
| 5 | score_runs lifecycle | فقط identity frozen | state machine terminal + completed_at rule | `sql/080_analytics.sql` |
| 6 | Reversal cost-basis | فقط quantity/cash negate | + participant inherit + `cost_basis_rial` negate + view `effective_transactions` | `sql/070_portfolio.sql` |
| 7 | Quantity drift | ستون مستقل `quantity` | ستون generated `abs(quantity_delta)` | `sql/070_portfolio.sql` |
| 8 | observation_hash | UNIQUE global | scoped `(security_id, trade_date, source, price_series, observation_hash)` | `sql/050_market.sql` |
| 9 | daily_prices policy | ضمنی | مستند deterministic | `sql/050_market.sql` |
| 10 | preflight | — | `preflight_check.py` (read-only، بدون DB) | `preflight_check.py` |

## تست‌های اضافه‌شده (v1.2.1)
- P14–P17: parse_runs terminal transitions.
- C08–C09: report/company mismatch در monthly/financial.
- A08–A11: score_runs terminal transitions.
- M09: scoped observation hash.
- L21–L24: reversal cost-basis cancellation / quantity derived.

جمع: **74** تست (قبلاً 59).

## فایل‌های جدید
- `preflight_check.py`
- `v1_2_to_v1_2_1_changes.md`

## Gate
`preflight_check.py` = PASS → `READY_TO_CREATE_TEST_DATABASE`.
