# Legacy SQL Server → Canonical PostgreSQL v1 Mapping

> Design artifact. هیچ داده‌ای مهاجرت نکرده است. تصمیم‌ها: `MIGRATE` | `TRANSFORM` | `MERGE` | `SKIP`/`LEGACY_DO_NOT_MIGRATE` | `ARCHIVE` | `REVIEW`.

## قواعد عمومی

- **Identity:** هر `CompanyID` (md5) و هر `InstrumentCode` به `core.legacy_entity_map` ثبت می‌شود و به `core.companies`/`core.securities` نگاشت می‌گردد. CompanyID ↔ شرکت با نام نرمال، و ابزار با `InstrumentCode` (در صورت وجود) یا `Symbol` resolve می‌شود.
- **Units:** مبالغ legacy «میلیون ریال» → `reported_value` (بدون تغییر) + `reported_unit='million_rial'` + `reported_unit_multiplier=1000000` + `canonical_value = reported_value × 1,000,000` (ریال). EPS بدون تبدیل (`rial_per_share`).
- **Dates:** `ReportDate`/`JalaliDate`/`DateKey` شمسی → `date` میلادی (مبدل معتبر؛ بدون roll-over) + `jalali_*` metadata. timestampهای naive → `timestamptz` (تبدیل local→UTC در صورت لزوم).
- **Dedup:** رکوردهای تکراری/اصلاحی → `ingestion.report_versions` (نسخه‌بندی) نه overwrite.

---

## جداول فعال

### `dbo.mahane` → `fundamentals.monthly_activities` — **TRANSFORM**
| legacy | new |
| --- | --- |
| `CompanyID` | resolve → `company_id`/`security_id` (+ legacy map) |
| `CompanyName` | `core.companies.display_name` (candidate) / alias |
| `ReportDate` | `period_end_date` (Greg→date) + `jalali_period_text` + fiscal_year/month |
| `Value1` | `production_quantity` (quantity_unit=NULL) |
| `Value2` | `sales_quantity` |
| `Value3` | `reported_sales_amount` (million_rial) → `sales_amount_rial = ×1e6` |
| `Url` | report source_url (مسیر sync) یا field جدا |
| `ID` | ignore (surrogate) |
| `LastModificationDate` | ignore (writer ندارد؛ در DQ ثبت شود) |
Report: از registry با (company, period_end) یا ساخته می‌شود.
**v1.2 (items 1,3):** داده‌ی legacy نسخه ندارد؛ migration برای هر report یک **synthetic `report_versions`** (version_no=1, content provenance موجود) و یک **synthetic `parse_run`** (`parser_name='legacy_sqlserver'`, `parser_version='legacy_import_v1'`, `status='completed'`) می‌سازد و `report_version_id`+`parse_run_id` (هر دو NOT NULL) را پر می‌کند.

### `dbo.miandore2` → `fundamentals.financial_statements` + `financial_facts` — **TRANSFORM**
جزئیات کامل ستون‌به‌متریک در `miandore2_fact_mapping.md`.
**v1.1:** هر statement/fact به `report_version_id` (synthetic در صورت نبود) وصل می‌شود.

### `dbo.MarketPriceHistory` → `market.price_observations` — **MIGRATE/TRANSFORM**
هر ردیف یک observation (append-only) با `observation_hash`, `price_series='adjusted'`, `adjustment_method='candle_daily_adjusted'`, `adjustment_version`, `provenance`. `market.daily_prices` یک **view** است و چیزی به آن migrate نمی‌شود.
| legacy | new |
| --- | --- |
| `InstrumentCode` | `security_id` (resolve by ins_code) |
| `Symbol`/`CompanyID`/`CompanyName` | fallback resolution + alias |
| `GregorianDate` | `trade_date` |
| `JalaliDate` | `jalali_date_text` |
| `HighPrice/LowPrice/ClosingPrice/LastPrice/FirstPrice/YesterdayPrice` | `*_rial` (numeric) |
| `ClosingChange/Percent`, `LastChange/Percent` | `closing_change_*`, `last_change_*` |
| `Volume`/`TradeValue`/`TradeCount` | same (TradeValue → `trade_value_rial`) |
| `Url` | `source_url` |
| `CollectedAt` | `collected_at` |
| `BrsName` | `core.securities.brs_name` / alias |
`open_price_rial` = NULL (legacy ندارد)؛ `is_adjusted=true`، `adjustment_method='candle_daily_adjusted'`.
**v1.2:** هر ردیف به `market.price_observations` می‌رود (نه view)؛ dedup با `observation_hash`.

### `dbo.CodalReports` → `ingestion.reports` — **MIGRATE**
| legacy | new |
| --- | --- |
| `CodalReportId` | `source_report_id` / `tracing_no` |
| `LetterType` | `letter_type` |
| `Ticker`/`CompanyName` | resolve → company_id/security_id |
| `ReportTitle`/`Title` | `title` |
| `ReportDate` | `period_end_date` + jalali |
| `PublishedAt` | `published_at` |
| `SourceUrl` | `source_url` |
| `Status`/`Attempts`/`ErrorMessage` | `processing_status`/`retry_count`/`error_message` |
| `DiscoveredAt`/`ProcessedAt` | same |

### `dbo.CodalSyncState` → `ingestion.sync_state` — **MIGRATE**
`LetterType` → `stream='letter_type:{n}'`؛ `LastSuccessfulSync` → `watermark`/`last_success_at`.

### `dbo.TrackedTickers` → `ingestion.tracked_securities` (+ `core.securities`) — **TRANSFORM**
`Symbol` → resolve به `security_id`؛ اگر ابزار موجود نبود ساخته و در `security_aliases` ثبت شود. `Source` → `source`.
نمادهای حل‌نشده → `ingestion.data_quality_issues(issue_code='identity_conflict')`.

### `dbo.FullPE` → `market.vendor_snapshots` (اختیاری) — **SKIP canonical**
- canonical market/valuation نیست. در صورت نیاز: هر ردیف یک `vendor_snapshot` با `vendor='tsetmc_fullpe'`, `metric_code='pe'`/`'price'` و `captured_at=LastModified`.
- P/E در `analytics` از price + financial facts محاسبه می‌شود.

### `dbo.Users` → `auth.users` (+ `auth.user_view_events`) — **MIGRATE/TRANSFORM**
| legacy | new |
| --- | --- |
| `ID` | legacy map → `id` |
| `UserName`/`Email` | `username`/`email` (citext) |
| `Password` | `password_hash` |
| `IsAdmin`/`IsOnline`→ | `is_admin`؛ `IsOnline` حذف (session-based) |
| `Token` | **حذف** (JWT خارج از DB) |
| `ViewedItems` JSON | parse → `auth.user_view_events` (per item) |
| `Portfolio` JSON | parse → `portfolio.*` (اگر لازم) |

### `dbo.FamilyPeople` → `portfolio.participants` — **MIGRATE**
یک `portfolio` از نوع `family` ساخته می‌شود؛ هر PersonID → participant + legacy map.

### `dbo.FamilyAssets` → `portfolio.assets` — **MIGRATE/TRANSFORM**
`Category`→`asset_type`؛ `Symbol`→`core.securities` (در صورت تطبیق) یا فقط asset symbol.

### `dbo.FamilyAccounts` → `portfolio.accounts` + **opening_cash** — **TRANSFORM (v1.2 items 9,16)**
ابتدا یک **account synthetic** (`account_type='cash'`) برای portfolio ساخته می‌شود. `CashBalance` به‌عنوان تراکنش `opening_cash` (نه `deposit` جعلی) با `effective_date`=as-of migration و `trade_date=NULL` ثبت می‌شود؛ `metadata = {"source":"legacy_migration", ...}`.

### `dbo.FamilyHoldings` → `portfolio.transactions` (**opening_position**) — **TRANSFORM (v1.2 items 9,12,13)**
`Quantity`/`CostBasis` → یک تراکنش `opening_position` با:
- `effective_date` = as-of migration، `trade_date = NULL` (بدون تاریخ خرید ساختگی)،
- `quantity_delta = quantity`، `cash_delta_rial = 0`،
- `cost_basis_rial` = **structured** (نه صرفاً JSON)،
- `metadata = {"source":"legacy_migration","migration_ts":...}` (فقط provenance).
`portfolio.positions` سپس derived می‌شود.
دارایی بورسی → ابتدا یک `portfolio.assets` با `security_id` resolve‌شده ساخته می‌شود (مدل unified asset، item 7).

### `dbo.FamilyPrices` → `portfolio.asset_price_snapshots` — **MIGRATE (v1.1 item 11)**
`DateKey`→`price_date`؛ `AssetID`→`asset_id`؛ `Price`→`price_rial`. **بدون `portfolio_id`** (قیمت asset-level global است).

### `dbo.FamilyCashFlows` → `portfolio.transactions` — **MIGRATE**
`Direction` → `deposit`/`withdrawal`؛ `Amount`→`net_amount_rial`؛ `DateKey`→`trade_date`؛ `Note`→`notes`.

### `dbo.FamilyHistory` → `portfolio.valuation_snapshots` — **MIGRATE**
`TotalValue/ChangeValue/ChangePct` → `total_value_rial`/`pnl_rial`/`return_pct`؛ `DateKey`→`valuation_date`؛ `RecordedAt`→`calculated_at`.

---

## جداول legacy (مهاجرت نمی‌شوند)

| legacy | تصمیم | دلیل |
| --- | --- | --- |
| `dbo.miandore` | **LEGACY_DO_NOT_MIGRATE** | ۰ ارجاع؛ superseded by `miandore2` |
| `dbo.StockData` | **LEGACY_DO_NOT_MIGRATE** (investigation فقط) | ۱۱ نماد؛ stale تا 2025-05؛ writer ندارد |
| `dbo.StockPrices` | **LEGACY_DO_NOT_MIGRATE** | ۰ reader/writer |
| `dbo.statements` | **REVIEW** (خارج از دامنه‌ی v1) | فقط ۱ شرکت؛ UnitCode='unknown'؛ writer ناشناس |
| `dbo.vw_AIStockMetrics2` | **NOT MIGRATED** | view legacy |
| `dbo.vw_AIStockMetrics3` | **NOT MIGRATED** | view legacy |
| `dbo.fn_JalaliKey` | **NOT MIGRATED** | منطق به analytics/app منتقل می‌شود |
| `dbo.vw_AIStockMetrics` (v3.7) | **ARCHIVE reference** | برای parity؛ در `analytics` بازپیاده‌سازی می‌شود |

## آنچه آرشیو می‌شود (نه drop)
جداول legacy و snapshot v3.7 پس از cutover به‌صورت read-only آرشیو می‌شوند (`Phase 10`) تا در صورت نیاز قابل رجوع باشند.
