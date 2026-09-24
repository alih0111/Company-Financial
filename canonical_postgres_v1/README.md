# Canonical PostgreSQL Schema v1

> مرحله‌ی طراحی. **هیچ DDL/migration اجرا نشده و هیچ production code تغییر نکرده است.**
> این پوشه شامل DDL کامل (اجرانشده)، سند طراحی، نقشه‌ی مهاجرت، و planها است.

## خلاصه تصمیم‌های پایه
- **Company ≠ Security**؛ identity داخلی UUID، مستقل از نام/symbol؛ `tsetmc_ins_code` روی `securities`.
- **واحد پول canonical = IRR (ریال)**، نوع `numeric`؛ legacy میلیون‌ریال ×1,000,000 با حفظ `reported_*`.
- **قیمت canonical از `MarketPriceHistory`**؛ `StockData`/`StockPrices` legacy؛ `FullPE` غیر-canonical.
- **تاریخ:** business date = `date` میلادی + jalali metadata؛ event = `timestamptz` UTC.
- **سه لایه:** RAW → NORMALIZED (`fundamentals`/`market`) → ANALYTICS.
- **Derived metrics فقط در `analytics`** با نسخه‌بندی و point-in-time.

## ساختار پوشه
```
canonical_postgres_v1/
  README.md
  schema.md
  erd.md
  legacy_to_v1_mapping.md
  miandore2_fact_mapping.md
  v37_compatibility.md
  sqlalchemy_model_plan.md
  migration_plan.md
  validation_plan.md
  sql/
    001_extensions.sql
    010_core.sql
    020_ingestion.sql
    030_raw.sql
    040_fundamentals.sql
    050_market.sql
    060_auth.sql
    070_portfolio.sql
    080_analytics.sql
    090_indexes.sql
```

## Namespaceها
`core` · `ingestion` · `raw` · `fundamentals` · `market` · `analytics` · `portfolio` · `auth`

## جداول (خلاصه)
- **core:** companies, securities, security_aliases, legacy_entity_map
- **ingestion:** reports, report_versions, sync_state, tracked_securities, runs, data_quality_issues
- **raw:** report_payloads
- **fundamentals:** metric_definitions, monthly_activities, financial_statements, financial_facts
- **market:** daily_prices, corporate_actions, vendor_snapshots
- **analytics:** score_runs, company_scores, factor_scores, metric_snapshots
- **auth:** users, user_view_events
- **portfolio:** portfolios, participants, accounts, assets, transactions, positions, valuation_snapshots, asset_price_snapshots

## Immutability / Delete behavior
- **Append-only:** `raw.report_payloads`, `fundamentals.financial_facts`, `portfolio.transactions` (trigger-guarded)؛ همچنین عملاً `ingestion.report_versions` و `analytics.score_runs/*`.
- **FK CASCADE فقط برای فرزندهای متعلق**؛ برای داده‌ی مالی/تاریخی مستقل **RESTRICT**. (جدول کامل در `schema.md`.)

## RAW storage
`raw.report_payloads` با CHECK «حداقل یکی از content_text/content_json/storage_uri». برای payload بزرگ‌تر از ~1–2MB یا حجم کل ده‌ها GB، bytes به object storage منتقل و فقط `storage_uri`+`content_hash` نگه داشته شود.

## چطور DDL اجرا می‌شود (در مرحله‌ی آینده، نه الان)
```
psql -f sql/001_extensions.sql
psql -f sql/010_core.sql
...  (به ترتیب شماره)
psql -f sql/090_indexes.sql
```
یا معادل Alembic از `sqlalchemy_model_plan.md`. **اکنون اجرا نکنید.**

---

# IMPLEMENTATION READINESS

## READY_TO_IMPLEMENT

طراحی v1 کامل و self-consistent است و بر یافته‌های auditها (`database_inventory`, `database_design_audit`, `canonical_design_inputs`) بنا شده است. DDL کامل، نقشه‌ی مهاجرت ستون‌به‌ستون، compatibility با v3.7، و planهای migration/validation آماده‌اند.

### دامنه‌ی implementation (گام بعدی، پس از تأیید)
1. اجرای Phase 0 (DDL) در یک PostgreSQL جدید/تست.
2. seed `metric_definitions`.
3. migration فازبه‌فاز مطابق `migration_plan.md` با validation مطابق `validation_plan.md`.
4. بازپیاده‌سازی analytics v3.7 و مقایسه‌ی parity.

### شرایط/فرض‌های همراه (blocker نیستند)
- `statements`, `StockData`, `StockPrices` خارج از دامنه‌ی v1 (legacy/REVIEW).
- `quantity_unit` ممکن است `NULL`/`unknown` بماند؛ هیچ واحد ساختگی تولید نمی‌شود.
- نگاشت برخی نمادهای حل‌نشده نیازمند بازبینی دستی و ثبت در `ingestion.data_quality_issues` است.
- `open_price_rial` برای داده‌ی legacy MPH خالی است (ستون طراحی شده ولی منبع ندارد).
- migration/apply فقط پس از تأیید صریح و در محیط غیر-production انجام شود.
