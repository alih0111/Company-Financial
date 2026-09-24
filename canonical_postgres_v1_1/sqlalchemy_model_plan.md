# SQLAlchemy / Alembic Model Plan

> مبنا: `go-app/py2/src/codal_ingestor/models.py` و `alembic/versions/0001_initial.py`.
> **فایل‌های production تغییر نمی‌کنند** در این مرحله؛ این سند نقشه‌ی آینده است.
> وضعیت‌ها: `KEEP` | `EXTEND` | `SPLIT` | `NEW` | `DEPRECATE`.

## نگاشت modelهای فعلی

| model فعلی | وضعیت | مقصد در v1 |
| --- | --- | --- |
| `Base` | KEEP | پایه‌ی مشترک |
| `Company` | **SPLIT** | `core.companies` (حتماً) + `core.securities` (خارج می‌شود به model جدید) |
| `Report` | **EXTEND** | `ingestion.reports` (add source_report_id, tracing_no, retry_count, processing_status, fiscal/jalali, published_at, source) |
| `ReportVersion` | **EXTEND** | `ingestion.report_versions` (add version_no, parser_version, is_current) |
| `MonthlyActivity` | **EXTEND** | `fundamentals.monthly_activities` (add sales_amount_rial, reported_*, quantity_unit, fiscal/jalali, report_version_id, security_id) |
| `FinancialFact` | **EXTEND** | `fundamentals.financial_facts` + `financial_statements` (split header/fact) |

## modelهای جدید (NEW)

| model | جدول |
| --- | --- |
| `Security` | `core.securities` |
| `SecurityAlias` | `core.security_aliases` |
| `LegacyEntityMap` | `core.legacy_entity_map` |
| `ReportPayload` | `raw.report_payloads` |
| `SyncState` | `ingestion.sync_state` |
| `TrackedSecurity` | `ingestion.tracked_securities` |
| `IngestionRun` | `ingestion.runs` |
| `DataQualityIssue` | `ingestion.data_quality_issues` |
| `FinancialStatement` | `fundamentals.financial_statements` |
| `MetricDefinition` | `fundamentals.metric_definitions` |
| `DailyPrice` | `market.daily_prices` |
| `CorporateAction` | `market.corporate_actions` |
| `VendorSnapshot` | `market.vendor_snapshots` |
| `User` | `auth.users` |
| `UserViewEvent` | `auth.user_view_events` |
| `Portfolio` / `Participant` / `Account` / `Asset` / `Transaction` / `Position` / `ValuationSnapshot` / `AssetPriceSnapshot` | `portfolio.*` |
| `ScoreRun` / `CompanyScore` / `FactorScore` / `MetricSnapshot` | `analytics.*` |

## تصمیم‌های مدل‌سازی

- **UUID PK:** `mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))`؛ در پایتون هم `default=uuid.uuid4` برای استفاده‌ی ORM.
- **Schema binding:** `__table_args__ = {"schema": "core"}` و `Base.metadata = MetaData(schema=...)` یا هر schema جدا. توصیه: یک `MetaData` مشترک بدون schema پیش‌فرض و schema در هر model.
- **citext:** `from sqlalchemy.dialects.postgresql import CITEXT`؛ `username`/`email` با `CITEXT` و `unique=True`.
- **Numeric:** همه‌ی مقادیر پولی/کمّی `Numeric(precision, scale)` (هیچ `Float`).
- **JSONB:** `postgresql.JSONB`.
- **timestamptz:** `DateTime(timezone=True)`.
- **Identity columns (`financial_facts.id`, `daily_prices.id`, ...):** `BigInteger, primary_key=True, autoincrement=True` با `Identity()`.
- **Immutable tables:** در ORM فقط `insert`؛ هیچ `update`/`delete` در repository (triggerها هم محافظت می‌کنند).
- **Enums:** به‌جای PostgreSQL ENUM از `String` + CHECK استفاده می‌کنیم (کم‌دردسرتر برای migration و تغییر مقدار). ORM با `CheckConstraint`.

## ترتیب Alembic migrations

```
0001_initial (existing, py2 legacy target)   -- دست‌نخورده می‌ماند
0002_v1_extensions_and_schemas               -- CREATE EXTENSION/SCHEMA
0003_core                                    -- companies, securities, aliases, legacy_map
0004_ingestion                               -- reports, report_versions, sync_state, tracked, runs, dq
0005_raw                                     -- report_payloads (+ immutability trigger)
0006_fundamentals                            -- metric_definitions, monthly_activities, financial_statements, financial_facts
0007_market                                  -- daily_prices, corporate_actions, vendor_snapshots
0008_auth                                    -- users, user_view_events
0009_portfolio                               -- portfolios..asset_price_snapshots
0010_analytics                               -- score_runs, company_scores, factor_scores, metric_snapshots
0011_indexes_and_immutability                -- cross-cutting indexes + triggers
```

> `0001` موجود (py2) و v1 در یک database می‌توانند هم‌زیستی کنند، چون v1 در schemaهای نام‌دار و py2 در `public` است. اگر تصمیم به یکپارچه‌سازی باشد، `0001` در قالب refactor به schemaها منتقل می‌شود (خارج از دامنه‌ی این طراحی).

## نکات migration framework
- هر فایل migration باید `upgrade()` و `downgrade()` کامل داشته باشد (حتی اگر downgrade فقط drop باشد).
- immutable triggerها در `upgrade` ساخته و در `downgrade` حذف شوند.
- داده seed ثابت (`metric_definitions`) در migration جدا (data migration) با upsert idempotent.

## وضعیت فعلی production code
هیچ تغییری در `go-app/py2/**` اعمال نمی‌شود. این modelهای جدید در مرحله‌ی implementation و پس از تأیید طراحی ساخته می‌شوند.

## تفاوت‌های ORM در v1.1 (نسبت به نقشه‌ی v1)
- `ReportVersion` → ستون `is_current` **ندارد**؛ current از `MAX(version_no)` یا view `ingestion.current_report_versions`.
- `Report` → ستون جدید `supersedes_report_id` (self-FK) و relationship خودارجاع.
- `MonthlyActivity` / `FinancialStatement` → `report_version_id` **NOT NULL** + composite FK؛ `__table_args__` شامل `ForeignKeyConstraint(["report_version_id","report_id"], ["ingestion.report_versions.id","ingestion.report_versions.report_id"])`.
- `Company` → `normalized_name` بدون `unique=True` (فقط `index=True`).
- `Security` → `UniqueConstraint("id","company_id")` (برای composite FKهای فرزند).
- همه‌ی modelهایی که `(security_id, company_id)` دارند → `ForeignKeyConstraint(..., ondelete="RESTRICT")`.
- `CompanyScore` → بدون `score_version`؛ `score_version` فقط از `ScoreRun`.
- `Transaction` → فقط `asset_id` (بدون `security_id`) + `metadata JSONB` + constraintهای reversal؛ `opening_position`/`opening_cash` در CHECK.
- `Position` → PK مرکب `(portfolio_id, asset_id)`.
- `AssetPriceSnapshot` → بدون `portfolio_id`.
- `DailyPrice` → ستون‌های `price_series`, `adjustment_version`, `provenance`.
- `Account`/`Participant`/`Transaction` → composite FKها برای integrity همان portfolio.

