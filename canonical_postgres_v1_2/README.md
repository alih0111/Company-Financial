# Canonical PostgreSQL Schema v1.2 (Final Hardening)

> نسخه‌ی نهایی پیش از اجرا روی Test Database. **هیچ DDL/migration اجرا نشده و هیچ production code تغییر نکرده است.**
> نسخه‌های `canonical_postgres_v1/` و `canonical_postgres_v1_1/` دست‌نخورده‌اند.

## خلاصه‌ی v1.2
تفکیک **fetch version از parse run**، زنجیره‌ی provenance کامل، immutability واقعی DB-level، cycle detection برای supersede، **market price revisioning append-only** با cutoff point-in-time، ledger با اثرهای علامت‌دار و reversal اجباری، و sync کامل مستندات. جزئیات: `v1_1_to_v1_2_changes.md`.

## ساختار پوشه
```
canonical_postgres_v1_2/
  README.md                    schema.md
  erd.md                       v1_1_to_v1_2_changes.md
  integrity_test_plan.md       legacy_to_v1_mapping.md
  miandore2_fact_mapping.md    v37_compatibility.md
  sqlalchemy_model_plan.md     migration_plan.md
  validation_plan.md
  sql/ 001_extensions · 010_core · 020_ingestion · 030_raw · 040_fundamentals
       050_market · 060_auth · 070_portfolio · 080_analytics · 090_indexes
```

## Namespaceها
`core · ingestion · raw · fundamentals · market · analytics · portfolio · auth`

## ترتیب اجرای SQL (تأییدشده)
```
001_extensions.sql → 010_core.sql → 020_ingestion.sql → 030_raw.sql →
040_fundamentals.sql → 050_market.sql → 060_auth.sql → 070_portfolio.sql →
080_analytics.sql → 090_indexes.sql
```
وابستگی: `010` قبل از `020` (securities برای composite FK)؛ `020` (parse_runs/report_versions) قبل از `040`؛ `070` (accounts/participants/assets) قبل از `080` لازم نیست اما `070` بعد از `060` (auth.users) بیاید. ترتیب بالا رعایت‌کننده است.

## نکات کلیدی
- **Provenance:** `report → report_version(fetch) → parse_run(parser) → normalized(parse_run_id)`.
- **Immutability:** trigger روی report_versions، payloads، monthly_activities، financial_statements، financial_facts، transactions، analytics outputs.
- **Market:** `price_observations` append-only + `daily_prices` view + `source_cutoff_at`.
- **Ledger:** `effective_date`/`trade_date`، `quantity_delta`/`cash_delta_rial`، `cost_basis_rial`، `account_id NOT NULL`، reversal اجباریِ معکوس.
- **Units:** monetary unknown=HIGH، quantity unknown=accepted.

## اجرا (مرحله‌ی آینده، نه الان)
فقط در test database و با تأیید. سپس `integrity_test_plan.md`.

---

# FINAL PRE-TEST REVIEW

## READY_FOR_EXECUTABLE_TEST

### خلاصه‌ی تغییرات v1.1 → v1.2
1. تفکیک `report_versions` (fetch) از `parse_runs` (parser)؛ حذف `parser_version` از report_versions (item 1).
2. `parse_run_id` NOT NULL + composite FK در normalized؛ uniqueness parse-aware (item 2).
3. synthetic `report_version` + synthetic `parse_run` برای legacy (item 3).
4. immutability واقعی DB-level برای report_versions/normalized/raw (item 4).
5. cycle detection supersede (۲فره/NFره) + قفل identity منبع (item 5).
6. `market.price_observations` append-only + `daily_prices` view (item 6).
7. `score_runs.source_cutoff_at` + قرارداد point-in-time (item 7).
8. حذف FK متناقض SET NULL؛ فقط composite RESTRICT (item 8).
9. consistency شرکت/ابزار در vendor_snapshots (item 9).
10. حذف `initial_capital_rial` (item 10).
11. حذف `assets.commission_rate` (item 11).
12. `effective_date`/`trade_date` جدا (item 12).
13. `cost_basis_rial` ساختاریافته برای opening_position (item 13).
14. اثرهای علامت‌دار `quantity_delta`/`cash_delta_rial` + queryهای قطعی cash/position (item 14).
15. `reversal` + trigger معکوس‌کننده (item 15).
16. `account_id NOT NULL` + account synthetic (item 16).
17. derive name/symbol برای security-linked assets + view (item 17).
18. immutability آنالیتیکس + lifecycle score_runs (item 18).
19. sync کامل SQLAlchemy/documentation (item 19).
20. بسط integrity tests (item 20).
21. مثال point-in-time بازار (item 21).
22. مثال عددی ledger (item 22).
23. static consistency review (item 23).

### تعداد نهایی integrity testها
**۵۲ تست DB-level** (P01–P13، C01–C07، S01–S04، M01–M08، A01–A07، L01–L20) — جزئیات در `integrity_test_plan.md`.

### ترتیب اجرای SQL
`001 → 010 → 020 → 030 → 040 → 050 → 060 → 070 → 080 → 090` (فقط در test database، با تأیید).
