# Canonical PostgreSQL Schema v1 — Schema Specification

> Design artifact. **هیچ DDL اجرا نشده است.** DDL در `sql/` قرار دارد و فقط برای بازبینی/اجرای آینده است.

## اصول طراحی (قطعی)

1. **Company ≠ Security.** `core.companies` (ناشر) و `core.securities` (ابزار قابل معامله) دو entity جدا هستند.
2. **UUID مستقل از نام/symbol** برای همه‌ی هویت‌ها. `tsetmc_ins_code` روی `securities` است.
3. **واحد پول canonical = IRR (ریال)** و نوع **`numeric`** (نه float). مقدار legacy میلیون‌ریالی هنگام migration ×1,000,000 و `reported_*` نیز برای audit حفظ می‌شود.
4. **Dates:** business date = `date` میلادی؛ در کنارش `jalali_text`/`fiscal_year`/`fiscal_month`. Event = `timestamptz` UTC.
5. **سه لایه:** `raw` → `fundamentals`/`market` → `analytics`.
6. **Derived metrics فقط در `analytics`** (TTM/growth/margin/ROE/ratios/P-E/P-S/momentum/volatility/QuantScore/DataQualityScore).

## Namespaceها

| Schema | نقش |
| --- | --- |
| `core` | هویت: companies, securities, aliases, legacy map |
| `ingestion` | registry گزارش‌ها، نسخه‌ها، watermark، tracked، runs، DQ |
| `raw` | payload خام گزارش (immutable) |
| `fundamentals` | فعالیت ماهانه، صورت‌های مالی، facts، metric dictionary |
| `market` | قیمت روزانه، رویداد شرکتی، snapshot فروشنده |
| `analytics` | score runs/scores/factors/metric snapshots |
| `portfolio` | portfolios/participants/accounts/ledger/valuation |
| `auth` | users/view events |

## UUID generation
`gen_random_uuid()` به‌عنوان `DEFAULT` ستون‌های UUID. `pgcrypto` برای سازگاری با سرورهای قدیمی‌تر فعال می‌شود (روی PG13+ تابع built-in است). هیچ trigger-based UUID generation استفاده نمی‌شود.

## Companies uniqueness (تصمیم و دلیل)
`core.companies.normalized_name` **UNIQUE** است. دلیل: مسیر ingestion فعلی name-first است (`CompanyID = md5(name)`) و migration/ingestion به upsert idempotent بر اساس نام نیاز دارد؛ audit نشان داد هیچ دو entity متمایزی نام نرمال‌شده‌ی یکسان ندارند.
**ریسک/escape hatch:** اگر در آینده دو نهاد قانونی متمایز نام نرمال‌شده‌ی یکسان پیدا کردند، constraint حذف و به index غیریکتا تغییر می‌کند (مستند در `migration_plan.md`).

## Securities uniqueness
- `tsetmc_ins_code` → **UNIQUE جزئی** WHERE NOT NULL.
- `isin` → **UNIQUE جزئی** WHERE NOT NULL.
- `is_primary` → partial unique `(company_id) WHERE is_primary` (حداکثر یک ابزار اصلی هر شرکت).
- `codal_symbol` → ایندکس معمولی + ایندکس functional `lower()` (نه UNIQUE؛ نماد می‌تواند در طول زمان/شرکت‌ها جابه‌جا شود و در alias history ثبت می‌گردد).

## PK choice: market.daily_prices
**انتخاب: UUID/IDENTITY surrogate PK + UNIQUE (security_id, trade_date).** (در DDL از `bigint GENERATED ALWAYS AS IDENTITY` استفاده شده — surrogate سبک‌تر از UUID برای جدول پرحجم.)
دلیل:
- FKهای آینده و partition توسط `trade_date` آسان می‌شود (کلید طبیعی مرکب، partition key را به همه‌ی FKها تحمیل می‌کند).
- یکتایی business key با UNIQUE index تضمین می‌شود.
- اگر روزی چند vendor هم‌زمان آمد، `source` به کلید یکتا اضافه می‌شود.

## DELETE behavior (صریح)

| رابطه | ON DELETE | دلیل |
| --- | --- | --- |
| `securities.company_id → companies` | **RESTRICT** | حذف شرکت نباید ابزارهایش را بی‌سرپرست کند |
| `security_aliases.security_id → securities` | **CASCADE** | alias صفت ابزار است |
| `reports.company_id → companies` | **RESTRICT** | تاریخ گزارش نباید پاک شود |
| `reports.security_id → securities` | **SET NULL** | گزارش می‌تواند بدون ابزار بماند |
| `report_versions.report_id → reports` | **CASCADE** | version متعلق به report است |
| `raw.report_payloads.report_version_id → report_versions` | **CASCADE** | payload متعلق به version است |
| `monthly_activities.report_id → reports` | **RESTRICT** | داده‌ی مالی نباید cascade پاک شود |
| `financial_statements.report_id → reports` | **RESTRICT** | همان |
| `financial_facts.statement_id → financial_statements` | **CASCADE** | fact متعلق به statement است |
| `financial_facts.metric_code → metric_definitions` | **RESTRICT** | حذف متریک نباید facts را پاک کند |
| `daily_prices.security_id → securities` | **RESTRICT** | تاریخ قیمت محافظت شود |
| `corporate_actions.security_id → securities` | **RESTRICT** | — |
| `transactions.portfolio_id → portfolios` | **RESTRICT** | ledger محافظت شود |
| `transactions.*_id → ...` | **RESTRICT/SET NULL** | بسته به اختیاری بودن |
| `company_scores.run_id → score_runs` | **CASCADE** | score متعلق به run است |

قاعده‌ی کلی: **CASCADE فقط برای فرزندهای واقعاً «متعلق» (versions/payloads/facts/scores)**؛ برای داده‌ی مالی/تاریخی مستقل، **RESTRICT**.

## IMMUTABILITY / AUDIT

| Table | رفتار | مکانیزم |
| --- | --- | --- |
| `raw.report_payloads` | **append-only** | trigger `raw.prevent_mutation` |
| `fundamentals.financial_facts` | **append-only** | trigger `fundamentals.prevent_fact_mutation` |
| `portfolio.transactions` | **immutable ledger** | trigger `portfolio.prevent_transaction_mutation` |
| `ingestion.report_versions` | append-only (عملی) | بدون trigger؛ only insert، `is_current` جایگزین می‌شود |
| `analytics.score_runs` / `company_scores` / `factor_scores` | append-only | بدون trigger؛ فقط insert |
| `market.daily_prices` | upsertable | اصلاح مجاز؛ `adjusted_at` stamped |

`updated_at` فقط روی جدول‌های mutable با trigger `core.set_updated_at()` نگه داشته می‌شود.

## RAW storage sizing (توضیح object storage)
- Codal HTML معمولاً ده‌ها تا چند صد KB است → `content_text` در DB مناسب است.
- `content_json` فقط برای metadata/JSON کوچک (مثل snapshot پارسر).
- اگر یک payload به‌طور معمول از **~1–2MB** بگذرد، یا حجم کل RAW به **ده‌ها GB** برسد، بایت‌ها به object storage منتقل و فقط `storage_uri` + `content_hash` + `byte_size` + `mime_type` در DB نگه داشته شود.
- CHECK تضمین می‌کند حداقل یکی از `content_text`/`content_json`/`storage_uri` موجود باشد.

## Metric dictionary
`fundamentals.metric_definitions` منبع نام‌گذاری پایدار است؛ `financial_facts.metric_code` به آن FK می‌دهد. کدها مستقل از `RowTitle` فارسی‌اند (نمونه‌ها: `revenue`, `net_profit`, `operating_profit`, `finance_cost`, `total_assets`, `current_assets`, `total_liabilities`, `current_liabilities`, `total_equity`, `operating_cash_flow`, `eps`, `operating_eps`, `capital`).

## Query-pattern → index coverage (خلاصه)
| Query pattern | Index |
| --- | --- |
| آخرین گزارش شرکت | `ix_reports_company_period` (+ partial completed) |
| گزارش‌های یک بازه | `ix_reports_company_type_ts` |
| همه‌ی factهای یک statement | `ix_financial_facts_statement` |
| lookup بر اساس metric_code | `ix_financial_facts_metric_lookup` / `_metric_statement` |
| آخرین قیمت یک security | `ix_daily_prices_latest_covering` |
| price history security/date | `ix_daily_prices_security` |
| latest score | `ix_score_runs_version_date_desc` + `ix_company_scores_company_run` |
| historical score/backtest | `ix_metric_snapshots_company_metric_date` |
| current position | `uq_positions_target` |
| transaction ledger | `ix_transactions_portfolio_date` (+ asc) |
