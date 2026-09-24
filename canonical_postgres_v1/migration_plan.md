# Migration Plan — SQL Server (`codal`) → Canonical PostgreSQL v1

> Design artifact. **هیچ migration اجرا نمی‌شود.** مهاجرت big-bang نیست؛ ۱۱ فاز با validation و rollback.
> فرض: SQL Server منبع فقط-خواندنی باقی می‌ماند تا پایان cutover.

## اصول
- هر فاز idempotent و قابل بازاجرا.
- هیچ داده‌ای در SQL Server تغییر نمی‌کند.
- هر تغییر قابل rollback (drop schema/مرحله) یا برگشت‌پذیر است.
- `core.legacy_entity_map` در همه‌ی فازها پر می‌شود تا traceability حفظ شود.

---

## Phase 0 — Schema creation
- **Prerequisites:** دسترسی به یک PostgreSQL خالی/جدید؛ تأیید DDL.
- **Actions:** اجرای `sql/001`..`sql/090` (فقط extension/schema/table/constraint/index).
- **Validation:** وجود همه‌ی schemaها/جدول‌ها؛ `\dt` per schema؛ صحت triggerها؛ اجرای dry-run یک INSERT/... در محیط تست.
- **Rollback:** `DROP SCHEMA ... CASCADE` برای همه‌ی schemaهای v1.

## Phase 1 — Company / Security identity seed
- **Prerequisites:** Phase 0؛ snapshot جداول مرجع (mahane/miandore2/MPH/TrackedTickers/FullPE/CodalReports).
- **Actions:**
  1. استخراج union شرکت‌ها از منابع (mahane/miandore2/MPH) → `core.companies`.
  2. resolve `InstrumentCode`/`Symbol` → `core.securities` (+ `is_primary`).
  3. پرکردن `core.security_aliases` (symbol/company_name/brs_name/legacy_name).
  4. پرکردن `core.legacy_entity_map` برای هر `CompanyID` و `InstrumentCode`.
  5. نمادهای حل‌نشده → `ingestion.data_quality_issues`.
- **Validation:** تعداد company/security با audit (278 شرکت تقریبی)؛ یکتایی `tsetmc_ins_code`؛ تکرار نمادها در DQ.
- **Rollback:** truncate `core.*` (جداول تازه).

## Phase 2 — Codal registry / raw
- **Prerequisites:** Phase 1.
- **Actions:** migrate `CodalReports` → `ingestion.reports`؛ migrate `CodalSyncState` → `ingestion.sync_state`؛ migrate `TrackedTickers` → `tracked_securities`؛ (اختیاری) آرشیو RAW payloadها اگر موجود باشد.
- **Validation:** `count(reports)` = count(CodalReports) با tolerance؛ وجود legacy map؛ watermark درست.
- **Rollback:** truncate `ingestion.*` و `raw.*`.

## Phase 3 — Fundamentals
- **Prerequisites:** Phase 2؛ seed `metric_definitions`.
- **Actions:** `miandore2` → `financial_statements`+`financial_facts` (per `miandore2_fact_mapping.md`)؛ `mahane` → `monthly_activities` با تبدیل واحد ×1e6.
- **Validation:** row counts؛ مقایسه EPS/Revenue/NetProfit/Assets/Equity/CF برای ۲۰ شرکت و سپس universe (نگاه `validation_plan.md`)؛ صفر DQ برای unit ناشناخته.
- **Rollback:** truncate `fundamentals.*` (به‌جز `metric_definitions`).

## Phase 4 — Market prices
- **Prerequisites:** Phase 1؛ `securities` با `tsetmc_ins_code`.
- **Actions:** `MarketPriceHistory` → `market.daily_prices` (resolve by ins_code)؛ استخراج/ثبت `corporate_actions` از heuristic فعلی (با `detected_heuristically=true`).
- **Validation:** row count؛ latest date per security؛ نمونه‌ی OHLC با legacy برای ۲۰ نماد.
- **Rollback:** truncate `market.*`.

## Phase 5 — Users / portfolio
- **Prerequisites:** Phase 1 (securities/assets) و Phase 4 (برای valuation).
- **Actions:** `Users` → `auth.users` + `user_view_events`؛ `Family*` → `portfolio.*` (accounts/holdings/cashflows به ledger؛ FamilyHistory → valuation_snapshots؛ FamilyPrices → asset_price_snapshots).
- **Validation:** تعداد transactions ساخته‌شده از holdings/cashflows/cash balance؛ بازسازی `positions` و تطبیق با Holdings؛ بازسازی valuation با valuation_snapshots.
- **Rollback:** truncate `auth.*` (به‌جز seeded users اگر لازم) و `portfolio.*`.

## Phase 6 — Analytics parity with v3.7
- **Prerequisites:** Phase 3 + Phase 4.
- **Actions:** بازپیاده‌سازی منطق v3.7 (TTM/growth/margins/valuation/market/penalties/ranking/weights) در analytics؛ ساخت `score_runs`، `company_scores`، `factor_scores`، `metric_snapshots`.
- **Validation:** مقایسه با خروجی view v3.7 (تolerance) برای universe (نگاه `v37_compatibility.md` و `validation_plan.md`).
- **Rollback:** truncate `analytics.*`.

## Phase 7 — Dual-read validation
- **Prerequisites:** Phases 3–6.
- **Actions:** اجرای هم‌زمان خواندن SQL Server و PostgreSQL در محیط staging؛ مقایسه‌ی systematic؛ ثبت اختلاف‌ها در DQ.
- **Validation:** مسیرها: آخرین گزارش، گزارش‌های بازه، facts، آخرین قیمت، price history، latest score، backtest sample. هیچ اختلاف HIGH حل‌نشده نماند.
- **Rollback:** خروج از staging؛ هیچ تغییری در production.

## Phase 8 — Go API cutover
- **Prerequisites:** Phase 7 سبز؛ feature-flag آماده.
- **Actions:** افزودن لایه‌ی دسترسی Postgres در Go (کد جدید؛ فعلاً تولید نمی‌کنیم)؛ سوییچ تدریجی endpointها با feature flag؛ dual-run و مقایسه‌ی پاسخ‌ها.
- **Validation:** پاسخ endpointها در برابر نسخه‌ی SQL Server؛ p95 latency؛ نرخ خطا.
- **Rollback:** برگرداندن flock به SQL Server (flag).

## Phase 9 — Python ingestion cutover
- **Prerequisites:** Phase 8 پایدار.
- **Actions:** ingestion جدید (py2-style) در schemaهای v1 بنویسد؛ ingestion قدیمی SQL Server متوقف/آرشیو؛ RAW ذخیره شود.
- **Validation:** یک چرخه‌ی کامل sync (financial+monthly) و صحت رکوردهای جدید؛ idempotency روی اجرای تکراری.
- **Rollback:** دوباره فعال‌کردن ingestion قدیمی.

## Phase 10 — SQL Server read-only / archive
- **Prerequisites:** Phase 9 پایدار و اطمینان از parity.
- **Actions:** SQL Server را read-only/آرشیو کنید؛ جداول legacy و view v3.7 را برای مرجع نگه دارید؛ پاک‌سازی runtime DDL/فایل‌ها.
- **Validation:** هیچ writer فعالی به SQL Server نباشد؛ backup کامل گرفته شده.
- **Rollback:** در صورت اضطرار، دسترسی write موقت و بازگشت.

---

## Dependency graph فازها
```
0 -> 1 -> 2 -> 3 -> 4 -> 6 -> 7 -> 8 -> 9 -> 10
                     \-> 5 --/
```
(5 بعد از 1 و 4؛ 6 بعد از 3 و 4.)

## ریسک‌های کلیدی
- نگاشت identity (نماد/نام) برای برخی شرکت‌ها نامطمئن است → DQ + بازبینی دستی.
- واحد تاریخی مخلوط (احتمال وجود رکوردهای thousand_rial) → validation per-record.
- تعدیل قیمت heuristic legacy → `corporate_actions.detected_heuristically` باید بازبینی شود.
