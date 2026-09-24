# Migration Plan (v1.2) — SQL Server (`codal`) → Canonical PostgreSQL

> Design artifact. **هیچ migration اجرا نمی‌شود.** ۱۱ فاز با validation/rollback.

## اصول
- هر فاز idempotent و بازاجراپذیر؛ SQL Server فقط‌خواندنی تا پایان cutover.
- `core.legacy_entity_map` در همه‌ی فازها پر می‌شود.
- زنجیره‌ی provenance: `report → report_version → parse_run → normalized`.

## Phase 0 — Schema creation
- **Prereq:** PostgreSQL تست؛ تأیید DDL.
- **Actions:** اجرای `sql/001`..`sql/090` (extension/schema/table/view/constraint/index/trigger).
- **Validation:** وجود schemaها/جداول/viewها؛ صحت triggerها؛ SMOKE insert در تست.
- **Rollback:** `DROP SCHEMA ... CASCADE`.

## Phase 1 — Company/Security identity seed
- **Prereq:** Phase 0.
- **Actions:** union شرکت‌ها → `core.companies`؛ resolve `InstrumentCode`/`Symbol` → `core.securities`؛ aliases؛ `legacy_entity_map`؛ موارد حل‌نشده → DQ.
- **Validation:** تعدادها؛ یکتایی `tsetmc_ins_code`؛ نبود دو `is_primary`.
- **Rollback:** truncate `core.*`.

## Phase 2 — Codal registry / fetch versions / parse runs
- **Prereq:** Phase 1.
- **Actions:** `CodalReports` → `ingestion.reports`؛ `CodalSyncState` → `sync_state`؛ `TrackedTickers` → `tracked_securities`.
  برای هر report یک **synthetic `report_version`** (provenance موجود) و یک **synthetic `parse_run`** (`parser_name='legacy_sqlserver'`, `parser_version='legacy_import_v1'`, `status='completed'`, `finished_at=now()`) بساز. (طبق CHECK، status غیر-running باید `finished_at` داشته باشد.)
- **Validation:** counts؛ legacy map؛ watermark؛ یک parse_run completed per version.
- **Rollback:** truncate `ingestion.*`/`raw.*`.

## Phase 3 — Fundamentals (attach to parse_run)
- **Prereq:** Phase 2؛ seed `metric_definitions`.
- **Actions:** `miandore2` → statements+facts؛ `mahane` → `monthly_activities` (×1e6). همه با `parse_run_id` synthetic، `report_version_id` synthetic.
- **Validation:** counts؛ مقایسه‌ی ۲۰ شرکت سپس universe.
  - monetary unit `unknown` = **failure (HIGH)**؛ quantity_unit `unknown`/NULL = **accepted**؛ هیچ واحدی حدس زده نمی‌شود.
- **Rollback:** truncate `fundamentals.*` (به‌جز metric_definitions).

## Phase 4 — Market prices
- **Prereq:** Phase 1.
- **Actions:** `MarketPriceHistory` → `market.price_observations` (append-only؛ `observation_hash`؛ provenance: source/adjustment_method/version). corporate actions از heuristic فعلی با `detected_heuristically=true`.
- **Validation:** counts؛ `daily_prices` view = latest؛ نمونه‌ی OHLC برای ۲۰ نماد.
- **Rollback:** truncate `market.*`.

## Phase 5 — Users / portfolio
- **Prereq:** Phase 1, Phase 4.
- **Actions:** `Users` → `auth.users` + `user_view_events`.
  `Family*`:
  - ساخت یک portfolio (type=family) و یک **account synthetic** (`account_type='cash'`).
  - holdings → `opening_position` (`effective_date`=as-of migration، `trade_date=NULL`، `cost_basis_rial` structured، `metadata.source='legacy_migration'`).
  - cash balance → `opening_cash`.
  - cashflows → deposit/withdrawal؛ FamilyHistory → valuation_snapshots؛ FamilyPrices → asset_price_snapshots (asset-level).
  - دارایی بورسی → `portfolio.assets` با `security_id`.
- **Validation:** بازسازی cash/position از ledger با allocation مثال‌ها؛ تطبیق با Holdings.
- **Rollback:** truncate `auth.*`/`portfolio.*`.

## Phase 6 — Analytics parity with v3.7
- **Prereq:** Phase 3 + 4.
- **Actions:** بازپیاده‌سازی v3.7 در analytics؛ `score_runs.source_cutoff_at` = cutoff داده؛ outputs immutable؛ برای run تمام‌شده `status='completed'` و `completed_at` الزامی است (طبق state machine).
- **Validation:** مقایسه با view v3.7 (tolerance؛ `v37_compatibility.md`).
- **Rollback:** truncate `analytics.*`.

## Phase 7 — Dual-read validation
- **Actions:** خواندن موازی SQL Server/PostgreSQL؛ مقایسه‌ی مسیرها؛ ثبت اختلاف در DQ.
- **Validation:** نبود اختلاف HIGH.

## Phase 8 — Go API cutover
- feature-flag؛ dual-run؛ مقایسه‌ی پاسخ‌ها؛ rollback = برگشت flag.

## Phase 9 — Python ingestion cutover
- ingestion جدید در schemaهای v1.2 بنویسد؛ fee/tax/opening/reversal طبق semantics؛ rollback = فعال‌سازی ingestion قدیمی.

## Phase 10 — SQL Server read-only / archive
- SQL Server read-only؛ legacy آرشیو؛ backup کامل.

## Dependency
```
0 -> 1 -> 2 -> 3 -> 4 -> 6 -> 7 -> 8 -> 9 -> 10
                     \-> 5 --/
```

## ریسک‌ها
- نگاشت identity نماد/نام → DQ + بازبینی.
- یکسان‌سازی واحد تاریخی → validation per-record.
- تعدیل heuristic legacy → corporate_actions.detected_heuristically بازبینی.
- reversal/opening semantics باید در ingestion جدید دقیق پیاده شود (وگرنه trigger رد می‌کند).
