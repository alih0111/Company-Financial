# Canonical PostgreSQL Schema v1.1 (Hardened)

> نسخه‌ی اصلاح‌شده‌ی `canonical_postgres_v1/` پس از Design Hardening.
> **هیچ DDL/migration اجرا نشده و هیچ production code تغییر نکرده است.** نسخه‌ی v1 دست‌نخورده باقی مانده است.

## خلاصه
v1.1 اشکالات integrity نسخه‌ی v1 را رفع می‌کند: version-aware normalization، حذف mutable `is_current`، رابطه‌ی correction رسمی، یکسان‌سازی immutability/CASCADE، composite FKهای company/security و portfolio، مدل unified asset، reversal integrity، opening transactions، و اصلاحات مستندسازی. جزئیات: `v1_to_v1_1_changes.md`.

## ساختار پوشه
```
canonical_postgres_v1_1/
  README.md                     schema.md
  erd.md                        v1_to_v1_1_changes.md
  integrity_test_plan.md        legacy_to_v1_mapping.md
  miandore2_fact_mapping.md     v37_compatibility.md
  sqlalchemy_model_plan.md      migration_plan.md
  validation_plan.md
  sql/ 001_extensions · 010_core · 020_ingestion · 030_raw · 040_fundamentals
       050_market · 060_auth · 070_portfolio · 080_analytics · 090_indexes
```

## Namespaceها
`core` · `ingestion` · `raw` · `fundamentals` · `market` · `analytics` · `portfolio` · `auth`

## نکات کلیدی v1.1
- **Version-aware normalization:** `report_version_id` NOT NULL + composite FK + UNIQUE version-aware؛ current از `MAX(version_no)` (view `ingestion.current_report_versions`).
- **Correction رسمی:** `reports.supersedes_report_id`.
- **CASCADE فقط برای فرزندِ متعلقِ mutable؛ RESTRICT برای audit/history.**
- **Consistency:** `(security_id, company_id)` composite FK؛ `securities UNIQUE(id, company_id)`.
- **Portfolio:** composite FKهای account/participant/portfolio؛ ledger = source of truth؛ positions = derived.
- **Unified asset:** ledger فقط `asset_id`؛ reversal با CHECK+partial unique+composite FK؛ `opening_position`/`opening_cash`.
- **Market:** provenance صریح (`price_series`, `adjustment_version`, `provenance`), بدون partition.
- **Score:** `score_version` فقط در `score_runs`.
- **Units:** monetary unknown = HIGH؛ quantity unknown = accepted.

## اجرا (مرحله‌ی آینده، نه الان)
`psql -f sql/001... ` به ترتیب شماره یا معادل Alembic. **اکنون اجرا نکنید.**

---

# PRE-IMPLEMENTATION REVIEW

## READY_FOR_TEST_DATABASE

طراحی v1.1 از نظر integrity و consistency self-consistent است و DDL کامل (بدون اجرا) آماده است. تمام ۱۸ آیتم Design Hardening اعمال و مستند شده‌اند، و ماتریس تست integrity تعریف شده است. گام بعدی، اجرای DDL در یک **test database** و اجرای `integrity_test_plan.md` است.

### خلاصه‌ی تغییرات v1 → v1.1
1. Report versioning version-aware + composite FK + synthetic version (item 1).
2. حذف `is_current` + view current (item 2).
3. `supersedes_report_id` (item 3).
4. یکسان‌سازی CASCADE→RESTRICT در chainهای audit (item 4).
5. Consistency شرکت/ابزار با composite FK (item 5).
6. Integrity پرتفوی با composite FK (item 6).
7. Unified asset target (item 7).
8. Reversal integrity با constraint (item 8).
9. `opening_position`/`opening_cash` (item 9).
10. `positions` PK مرکب ساده (item 10).
11. `asset_price_snapshots` asset-level (item 11).
12. Market provenance/version (item 12).
13. اصلاح ادعای partitioning (item 13).
14. مستندسازی parser/version integrity (item 14).
15. حذف `score_version` تکراری (item 15).
16. اصلاح acceptance واحدها (item 16).
17. `normalized_name` غیریکتا (item 17).
18. `integrity_test_plan.md` (item 18).

### شرایط همراه (blocker نیستند)
- `statements`/`StockData`/`StockPrices` خارج از دامنه.
- `quantity_unit` ممکن است unknown بماند.
- نگاشت نمادهای حل‌نشده → DQ + بازبینی دستی.
- DDL/tests فقط در محیط test و با تأیید صریح.
