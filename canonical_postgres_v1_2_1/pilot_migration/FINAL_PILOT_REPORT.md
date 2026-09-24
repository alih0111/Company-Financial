# Final Pilot Report — SQL Server → PostgreSQL v1.2.1

> Pilot data migration واقعی و محدود. SQL Server فقط SELECT شد؛ هیچ production PG و هیچ production code تغییر نکرد.

## Environment
- Source: SQL Server `codal` (read-only).
- Target: PostgreSQL pilot `company_financial_migration_pilot_v121` (ساخته‌شده از صفر).
- Schema: `canonical_postgres_v1_2_1/sql/*` (v1.2.1).
- Isolated pilot DBs: `..._pilot_v121`, `..._pilot_rb`; test DB قبلی دست‌نخورده.

## Sample
۸ شرکت heterogeneous: khodro, dekpesol, chekapa, erafo, shekarbn, betrans, ofoq, kastra (+ identity conflict). (`sample_selection.md`)

## Schema / Smoke
- 10/10 DDL files: PASS (`create_pilot_db.py`)
- smoke_pilot.py: **PASS** (round-trip identity→report→monthly→fact→price→reversal، rollback)

## Identity — PASS
- duplicate `tsetmc_ins_code` = **0**
- securities created by name only = **0**
- **kastra convergence:** دو legacy CompanyID (`4ccc96…`, `7e41b7…`) با InstrumentCode `4614779520007780` → **۱** canonical company/security.
- 8 canonical companies، 8 securities، 52 legacy map rows، 17 aliases (`identity_validation.md`).

## Row Counts — PASS
| entity | source | target | diff |
| --- | --- | --- | --- |
| monthly (mahane) | 594 | 594 | 0 |
| financial facts | expected 2110 (non-null mapped) | 2110 | 0 |
| prices (MPH) | 26595 | 26595 | 0 |

هیچ price dedup collision رخ نداد. (`row_count_validation.md`)

## Value Parity
- **Monthly:** 594/594، `sales_amount_rial = Value3 × 1,000,000` دقیق. (`monthly_validation.md`)
- **Financial:** 2110/2110؛ EPS دقیق (rial_per_share)، monetary دقیق به‌جز **۱ ردیف** با اختلاف `~3e-7` (گردکردن `numeric(30,6)` در برابر FLOAT). (`financial_validation.md`)
- **Market:** 160/160 نمونه (earliest 5 + latest 5 + 10 میانی deterministic) برای OHLC/close/last/first/yesterday/volume/trade_value/trade_count دقیق. (`market_validation.md`)

## Date — PASS
27189 جفت تاریخ (jalali↔greg) بررسی شد؛ mismatch/invalid = **0**؛ بدون silent rollover. `1405/06/31`→`2026-09-22` معتبر. (`date_validation.md`)

## Unit — PASS
monetary canonical != `rial`/`rial_per_share` = **0**؛ `reported_unit` مبالغ = `million_rial`؛ quantity_unit NULL مجاز. (`unit_validation.md`)

## Orphan / Duplicate — PASS
همه‌ی checks = **0** (facts/statements/monthly/security/price/legacy-map orphans، duplicate ins/observation/report/fact). (`orphan_duplicate_validation.md`)

## Idempotency — PASS
اجرای دوم و سوم هیچ ردیف جدیدی نساخت؛ counts تمام جداول بدون تغییر. (`idempotency_test.md`)

## Rollback / Failure — PASS
با `--inject-failure` روی khodro در DB مجزا: khodro کاملاً rollback (security=0) و ۷ شرکت دیگر commit شدند (companies=7). هیچ half-migrated state. استراتژی: **transaction per company**. (`rollback_test.md`)

## Issues Found
جزئیات: `issues.md`. خلاصه:
- **LOW:** ۱ ردیف گردکردن `numeric(30,6)` vs `FLOAT` (tolerance 1e-6). پیشنهاد: گسترش مقیاس در نسخه‌ی بعد یا پذیرش tolerance.
- **LOW/by-design:** `--all` پیاده نشد؛ `raw.report_payloads` خالی (RAW موجود نیست)؛ cross-link CodalReports↔legacy reports انجام نشد؛ FullPE/analytics خارج از دامنه.
- هیچ issue با severity HIGH.

## Changes Made
- فقط ابزار migration (`migration_tools/*`)، گزارش‌ها (`pilot_migration/*`)، و دو DB pilot.
- **هیچ تغییر در `sql/` (schema)، هیچ تغییر در production SQL Server/PG/code.**

## Secret Safety
- هیچ connection string/password/token در گزارش‌ها/کد commit نشد. credential در زمان اجرا از `.env` خوانده شد.

---

# Pilot Gate

## PILOT_MIGRATION_PASS_WITH_KNOWN_LIMITATIONS

معیارهای PASS برآورده شد: identity صحیح، row-count expectations صحیح، واحد پولی صحیح، financial parity (در tolerance مستند)، market parity دقیق، date conversion صحیح، orphan=0، unexpected duplicate=0، اجرای دوم idempotent، rollback test pass.

محدودیت‌های شناخته‌شده‌ی ثبت‌شده:
1. گردکردن `numeric(30,6)` برای ۱ ردیف monetary (tolerance 1e-6).
2. `raw.report_payloads` خالی (payload خام legacy موجود نیست؛ provenance در report_version/parse_run).
3. cross-link بین CodalReports و گزارش‌های سنتزی legacy انجام نشد.
4. `--all`/full migration پیاده نشده (خارج از دامنه‌ی این مرحله).
5. FullPE و analytics عمداً migrate محاسبه نشدند.
