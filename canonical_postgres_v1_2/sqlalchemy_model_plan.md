# SQLAlchemy / Alembic Model Plan (v1.2)

> مبنا: `go-app/py2/src/codal_ingestor/models.py`. **production code تغییر نمی‌کند.**
> این سند با DDL v1.2 sync است (بدون اشاره‌ی stale به `is_current`، `parser_version` در report_versions، مدل قدیمی daily_prices، initial capital، commission).

## نگاشت modelهای فعلی

| model فعلی | وضعیت | مقصد v1.2 |
| --- | --- | --- |
| `Base` | KEEP | پایه |
| `Company` | SPLIT | `core.companies` + `core.securities` (model جدید) |
| `Report` | EXTEND | `ingestion.reports` (+ source_report_id, tracing_no, retry_count, processing_status, fiscal/jalali, published_at, source, supersedes_report_id) |
| `ReportVersion` | REFACTOR | `ingestion.report_versions` فقط محتوا (`version_no, content_hash, source_url, collected_at`)؛ **بدون `parser_version`، بدون `is_current`** |
| `MonthlyActivity` | EXTEND | `fundamentals.monthly_activities` (+ report_version_id NOT NULL, parse_run_id NOT NULL, sales_amount_rial, reported_*, quantity_unit, fiscal/jalali) |
| `FinancialFact` | EXTEND | `fundamentals.financial_statements` + `fundamentals.financial_facts` (split header/fact) |

## modelهای جدید (NEW)

| model | جدول |
| --- | --- |
| `Security`, `SecurityAlias`, `LegacyEntityMap` | `core.*` |
| `ParseRun` | `ingestion.parse_runs` |
| `ReportPayload`, `SyncState`, `TrackedSecurity`, `IngestionRun`, `DataQualityIssue` | `ingestion.*` / `raw.*` |
| `FinancialStatement`, `MetricDefinition` | `fundamentals.*` |
| `PriceObservation` (+ `DailyPrice` view model / `Table` reflection) | `market.price_observations` / `market.daily_prices` (view) |
| `CorporateAction`, `VendorSnapshot` | `market.*` |
| `User`, `UserViewEvent` | `auth.*` |
| `Portfolio`, `Participant`, `Account`, `Asset`, `Transaction`, `Position`, `ValuationSnapshot`, `AssetPriceSnapshot` | `portfolio.*` |
| `ScoreRun`, `CompanyScore`, `FactorScore`, `MetricSnapshot` | `analytics.*` |

## نکات مدل‌سازی v1.2
- **report_versions:** هیچ `parser_version`/`is_current`. current از view `ingestion.current_report_versions` (read-only `Table`/`select`).
- **parse_runs:** lifecycle-mutable فقط (status/finished_at/error_message). identity frozen.
- **monthly_activities / financial_statements:** `parse_run_id` NOT NULL + composite FK:
  `ForeignKeyConstraint(["parse_run_id","report_version_id"], ["ingestion.parse_runs.id","ingestion.parse_runs.report_version_id"])`
  و `ForeignKeyConstraint(["report_version_id","report_id"], ["ingestion.report_versions.id","ingestion.report_versions.report_id"])`.
- **company/security:** `Security` با `UniqueConstraint("id","company_id")`؛ childها composite FK `(security_id, company_id)`.
- **market:** `PriceObservation` (append-only؛ PK identity؛ `UniqueConstraint("observation_hash")`). `daily_prices` یک view است (نه `__tablename__` قابل نوشتن)؛ برای خواندن از `select()`/`reflect`.
- **analytics:** `CompanyScore` بدون `score_version`؛ `ScoreRun` دارای `source_cutoff_at`. outputها immutable (فقط insert).
- **portfolio:** `Portfolio` بدون `initial_capital_rial`؛ `Asset` بدون `commission_rate`؛ `Asset.name/symbol` nullable + CHECK. `Transaction`: `effective_date` NOT NULL، `trade_date` nullable، `quantity_delta`, `cash_delta_rial`, `cost_basis_rial`, `asset_id` (بدون security_id)، `account_id` NOT NULL.
- **reversal:** در ORM فقط `insert` با `transaction_type='reversal'` و `reverses_tx_id`؛ trigger مقادیر inverse را پر می‌کند (در ORM نباید quantity/cash را دستی ست کرد).
- **immutable:** repository فقط `insert` برای report_versions/payloads/monthly_activities/financial_statements/financial_facts/transactions/analytics outputs.
- **UUID:** `server_default=text("gen_random_uuid()")` + `default=uuid.uuid4`.
- **CITEXT:** `from sqlalchemy.dialects.postgresql import CITEXT`.
- **Enums:** `String` + `CheckConstraint`.

## ترتیب Alembic migrations
```
0001_initial (py2 legacy target, untouched)
0002_v1_extensions_and_schemas
0003_core
0004_ingestion_reports_versions_parseruns   -- includes views + immutability/cycle triggers
0005_raw
0006_fundamentals                            -- metric_definitions seed in data migration
0007_market                                  -- price_observations + daily_prices view
0008_auth
0009_portfolio
0010_analytics
0011_indexes_and_triggers
```
هر migration `upgrade()`/`downgrade()` کامل.

## وضعیت production
هیچ تغییری در `go-app/py2/**` اعمال نمی‌شود؛ این modelها در مرحله‌ی implementation پس از تأیید ساخته می‌شوند.
