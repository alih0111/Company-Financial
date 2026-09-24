# Canonical PostgreSQL Schema v1.1 — Schema Specification

> Design artifact (hardened). **هیچ DDL اجرا نشده است.** نسخه‌ی قبلی در `canonical_postgres_v1/` دست‌نخورده است.
> تغییرات v1→v1.1 در `v1_to_v1_1_changes.md`.

## اصول (بدون تغییر)
Company ≠ Security · UUID مستقل از نام/symbol · واحد IRR/`numeric` · سه لایه RAW→NORMALIZED→ANALYTICS · derived فقط در analytics.

## ۱) Report versioning (اصلاح‌شده)
- `fundamentals.monthly_activities.report_version_id` و `financial_statements.report_version_id` → **NOT NULL**.
- یکتایی version-aware:
  - `UNIQUE(report_version_id)` برای monthly_activities.
  - `UNIQUE(report_version_id, statement_type)` برای financial_statements.
- `report_id` برای ergonomics باقی می‌ماند؛ integrity با **composite FK**:
  `(report_version_id, report_id) → ingestion.report_versions(id, report_id)`.
  این تضمین می‌کند version واقعاً متعلق به همان report است.
- برای داده‌ی legacy بدون نسخه، migration یک **synthetic report_version** می‌سازد (version_no=1).

## ۲) `is_current` حذف شد
`ingestion.report_versions` دیگر ستون `is_current` ندارد (append-only). current = `MAX(version_no)` (tie: `collected_at`).
View: `ingestion.current_report_versions`.
تخصیص race-safe `version_no`: `MAX+1` زیر قفل `SELECT ... FROM reports WHERE id=:id FOR UPDATE` و UNIQUE نهایی.

## ۳) Correction relationship (رسمی کدال)
`ingestion.reports.supersedes_report_id uuid` self-FK با `ON DELETE RESTRICT` و CHECK عدم self-supersede.

تفاوت کلیدی:
- **report_version** = snapshot/fetch/parse از **همان** source report (TracingNo).
- **superseding report** = گزارش رسمی **جدید/اصلاحیه** با `source_report_id` مستقل.
برای point-in-time backtest، این دو نباید قاطی شوند.

## ۴) Immutability vs ON DELETE (یکسان‌سازی)
قاعده: **CASCADE فقط برای فرزندِ کاملاً متعلق که خودش mutable است**؛ برای chainهای audit/history → **RESTRICT**.
| رابطه | v1.1 |
| --- | --- |
| reports → report_versions | **RESTRICT** (بود CASCADE) |
| report_versions → raw.report_payloads | **RESTRICT** (بود CASCADE) |
| financial_statements → financial_facts | **RESTRICT** (بود CASCADE) |
| security_aliases → securities | CASCADE (صفت mutable) |
| participants/accounts/positions/valuation_snapshots → portfolios | CASCADE (متعلق) |
| company_scores → score_runs | CASCADE (متعلق) |
triggerهای immutability (`raw.report_payloads`, `financial_facts`, `transactions`) حالا با FK delete behavior تناقض ندارند.

## ۵) Company/Security consistency
- `core.securities` → `UNIQUE(id, company_id)`.
- در جداولی که هم `company_id` و هم `security_id` دارند:
  `(security_id, company_id) → core.securities(id, company_id)` (MATCH SIMPLE؛ اگر security NULL باشد چک نمی‌شود).
- اعمال‌شده در: `ingestion.reports`, `fundamentals.monthly_activities`, `analytics.company_scores`, `analytics.metric_snapshots`.

## ۶) Portfolio referential integrity
- `participants UNIQUE(id, portfolio_id)`؛ `accounts UNIQUE(id, portfolio_id)`؛ `transactions UNIQUE(id, portfolio_id)`.
- `accounts.(participant_id, portfolio_id) → participants(id, portfolio_id)`.
- `transactions.(account_id, portfolio_id) → accounts(id, portfolio_id)`.
- `transactions.(participant_id, portfolio_id) → participants(id, portfolio_id)`.
→ account/participant از portfolio دیگر **غیرممکن** است.

## ۷) Transaction target = Option A (Unified Asset)
- ledger فقط `asset_id` دارد (نه `security_id`).
- دارایی بورسی = ردیف `portfolio.assets` با `security_id`.
- CHECK: نوع‌های نقدی نیازی به asset ندارند؛ نوع‌های asset-محور الزامی.
- مزیت: position calculation بدون ambiguity؛ یک target type.

## ۸) Reversal integrity
- CHECK `reverses_tx_id <> id`.
- `UNIQUE(reverses_tx_id) WHERE NOT NULL` → هر تراکنش حداکثر یک‌بار reverse.
- composite FK `(reverses_tx_id, portfolio_id) → transactions(id, portfolio_id)` → reverse در همان portfolio.
- همه با constraint قطعی (بدون trigger غیرقطعی).

## ۹) Opening balance/position
transaction_typeهای `opening_position` و `opening_cash` اضافه شدند. migration Family داده‌ی legacy را به‌عنوان opening ثبت می‌کند (نه buy جعلی) و provenance در `metadata` (`source=legacy_migration`, cost basis/quantity/timestamp).

## ۱۰) Positions (derived)
مدل unified → `PRIMARY KEY(portfolio_id, asset_id)`. source of truth = ledger؛ position فقط cache/rebuildable.

## ۱۱) Asset price semantics (قطعی)
`portfolio.asset_price_snapshots` → **global per asset**: `portfolio_id` حذف شد؛ `UNIQUE(asset_id, price_date)`. (override مخصوص portfolio در آینده یک concept جداست.)

## ۱۲) Market price reproducibility
مدل **A**: یک series canonical (adjusted) با provenance صریح: `source`, `adjustment_method`, `price_series`, `adjustment_version`, `adjusted_at`, `provenance jsonb`, `collected_at`. `market.price_observations` (raw unadjusted) عمداً ساخته نشد (ضد over-engineering)؛ archive فعلی MarketPriceHistory نقش raw backup را دارد.

## ۱۳) daily_prices partitioning
v1.1: **بدون partition**، `bigint IDENTITY PK`، `UNIQUE(security_id, trade_date)`. ادعای نادرست v1 درباره‌ی «surrogate PK برای partition» اصلاح شد: جداول partitioned در PostgreSQL محدودیت PK/UNIQUE دارند. partition به آینده موکول شد.

## ۱۴) Financial version integrity
هر ردیف normalized به `report_version_id` وصل است؛ `parser_version` در `report_versions` می‌ماند (بدون denormalize). re-parse با parser جدید = **نسخه‌ی جدید** report_version، نه تغییر facts. (`ingestion.parse_runs` اختیاری/موکول.)

## ۱۵) Score version
`analytics.company_scores.score_version` **حذف شد** (از `run_id` → `score_runs.score_version`). `metric_snapshots.calculation_version` می‌ماند چون لینک run ندارد.

## ۱۶) Units (اصلاح acceptance)
- `unknown` برای **mmonetary** → مشکل (HIGH).
- `unknown`/NULL برای **quantity_unit** → limitation پذیرفته‌شده.
هیچ واحدی حدس زده نمی‌شود.

## ۱۷) `normalized_name`
دیگر **UNIQUE نیست**؛ فقط index غیریکتا. identity از external identifiers + `legacy_entity_map`. (escape hatch: partial unique با dedup صریح، در schema مستند شده.)

## Companies / Securities / uniqueness (خلاصه)
- `companies`: `id` PK؛ `normalized_name` NOT NULL + index غیریکتا؛ `display_name` NOT NULL.
- `securities`: `tsetmc_ins_code` UNIQUE جزئی، `isin` UNIQUE جزئی، `is_primary` partial unique per company، `UNIQUE(id, company_id)`.

## IMMUTABILITY / AUDIT
| Table | رفتار | مکانیزم |
| --- | --- | --- |
| `raw.report_payloads` | append-only | trigger |
| `fundamentals.financial_facts` | append-only | trigger |
| `portfolio.transactions` | immutable ledger | trigger |
| `ingestion.report_versions` | append-only | only insert؛ current derived |
| `analytics.*` | append-only | only insert |
| `market.daily_prices` | upsertable | provenance stamped |

## Query-pattern → index
(بدون تغییر عمده؛ `positions_pk` جای `uq_positions_target` را گرفت؛ `ix_report_versions_report_time` اضافه شد.)
