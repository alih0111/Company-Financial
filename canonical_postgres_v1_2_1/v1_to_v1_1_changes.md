# v1 → v1.1 Change Log (Design Hardening)

> `canonical_postgres_v1/` دست‌نخورده است. این سند هر تغییر و دلیل آن را ثبت می‌کند.
> هیچ DDL/migration اجرا نشده و هیچ production code تغییر نکرده است.

| # | موضوع | v1 | v1.1 | دلیل |
| --- | --- | --- | --- | --- |
| 1 | Report versioning | `report_version_id` nullable؛ UNIQUE روی `report_id`/(`report_id,type`) | `report_version_id` **NOT NULL**؛ UNIQUE version-aware (`report_version_id` / `report_version_id,statement_type`)؛ composite FK `(report_version_id, report_id) → report_versions(id, report_id)`؛ synthetic version برای legacy | output هر version باید مستقل بماند؛ integrity واقعی report↔version |
| 2 | `is_current` | ستون mutable در `report_versions` | حذف شد؛ current = `MAX(version_no)` + view `current_report_versions`؛ تخصیص race-safe مستند شد | append-only نباید UPDATE لازم داشته باشد |
| 3 | Codal correction | — | `reports.supersedes_report_id` self-FK (RESTRICT) + CHECK no-self | تفکیک correction رسمی از fetch/parse version؛ مهم برای backtest |
| 4 | Immutability vs CASCADE | reports→versions و versions→payloads و statements→facts با CASCADE | همه به **RESTRICT** | تاریخچه‌ی RAW/مالی نباید با حذف parent پاک شود |
| 5 | company/security consistency | ستون‌های مستقل | `securities UNIQUE(id, company_id)` + composite FK در reports/monthly_activities/company_scores/metric_snapshots | DB تضمین کند security متعلق به company است |
| 6 | portfolio integrity | FK ساده | `participants/accounts/transactions UNIQUE(id, portfolio_id)` + composite FK برای account/participant | account/participant از portfolio دیگر غیرممکن |
| 7 | transaction target | هم `asset_id` و هم `security_id` | **Option A: فقط `asset_id`** (unified asset)؛ `assets.security_id` برای بورسی؛ CHECK نوع‌محور | حذف ambiguity؛ position ساده |
| 8 | reversal integrity | self-FK ساده | CHECK self، partial UNIQUE یک‌بار reverse، composite FK همان portfolio | audit/reproducible، بدون trigger غیرقطعی |
| 9 | opening balance/position | buy/deposit جعلی برای Family | `opening_position`/`opening_cash` + `metadata.source=legacy_migration` | نباید معامله/تاریخ جعلی ساخت |
| 10 | positions | `COALESCE(asset_id, security_id)` unique | PK `(portfolio_id, asset_id)` | مدل unified؛ سادگی |
| 11 | asset price snapshots | `portfolio_id` nullable + UNIQUE(asset_id,date) | `portfolio_id` حذف؛ UNIQUE(asset_id, date) | قیمت asset-level global است؛ override مخصوص portfolio concept جداست |
| 12 | market reproducibility | فقط `is_adjusted/adjustment_method` | + `price_series`, `adjustment_version`, `provenance jsonb` | backtest بداند از کدام series/version استفاده کرد |
| 13 | partitioning claim | ادعای «surrogate PK برای partition» | ادعا اصلاح شد؛ v1.1 بدون partition | ادعای PostgreSQL نادرست بود |
| 14 | financial version integrity | ضمنی | مستند: parser_version در report_versions؛ re-parse = نسخه‌ی جدید (بدون denormalize) | audit «کدام parser» از طریق join |
| 15 | score version dup | `score_version` در run و company_scores | حذف از `company_scores` | جلوگیری از drift؛ فقط `run_id` |
| 16 | validation unit criterion | «صفر DQ برای unit ناشناخته» | monetary unknown = HIGH؛ quantity unknown = accepted | تناقض با audit (quantity می‌تواند unknown بماند) |
| 17 | normalized_name | UNIQUE | index غیریکتا؛ identity از external ids/legacy map | نام نباید identity باشد؛ escape hatch مستند |
| 18 | integrity tests | — | `integrity_test_plan.md` (۲۷ test case) | اثبات محدودیت‌ها |

## فایل‌های تغییر‌یافته/جدید
- SQL: `010_core.sql`, `020_ingestion.sql`, `030_raw.sql`, `040_fundamentals.sql`, `050_market.sql`, `080_analytics.sql`, `070_portfolio.sql` (rewrite), `090_indexes.sql`.
- Docs: `schema.md`, `erd.md`, `legacy_to_v1_mapping.md`, `migration_plan.md`, `validation_plan.md`, `sqlalchemy_model_plan.md`, `README.md`.
- جدید: `integrity_test_plan.md`, `v1_to_v1_1_changes.md`.
- بدون تغییر: `miandore2_fact_mapping.md`, `v37_compatibility.md`, و `sql/001_extensions.sql`, `060_auth.sql`.
