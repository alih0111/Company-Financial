# 10 — Old → New Domain Mapping

> برای هر object فعلی SQL Server: دامنه‌ی معنایی + وضعیت پیشنهادی.
> وضعیت‌ها: `MIGRATE` | `TRANSFORM` | `MERGE` | `LEGACY_DO_NOT_MIGRATE` | `REVIEW`.
> **هیچ schema جدیدی طراحی یا ساخته نشده است.**

## جداول

| Object | دامنه | وضعیت پیشنهادی | دلیل |
| --- | --- | --- | --- |
| `dbo.mahane` | monthly activities (فروش/تولید یک‌ماهه) | **TRANSFORM** | ستون‌های `Value1/2/3` معنای صریح ندارند؛ باید به فیلدهای نام‌دار (`production_quantity`, `sales_quantity`, `sales_amount`) تبدیل شوند (مدل py2) |
| `dbo.miandore2` | financial facts (سود و زیان + ترازنامه + جریان نقدی) | **TRANSFORM** | چند صورت مالی در یک جدول wide؛ باید به مدل long/fact (py2) تبدیل شود |
| `dbo.miandore` | صورت سود و زیان قدیمی | **LEGACY_DO_NOT_MIGRATE** | ۰ ارجاع، ۶۷۹ ردیف، جایگزین‌شده با `miandore2` |
| `dbo.statements` | financial statements (metric-based، شبیه `financial_facts`) | **REVIEW** | بدون writer/reader در سورس؛ اگر منبع خارجی فعال دارد باید بررسی شود |
| `dbo.MarketPriceHistory` | daily market prices | **MIGRATE** | canonical market table؛ نیاز به واحد/واحد پول و ستون‌های تاریخ واقعی |
| `dbo.StockData` | daily OHLC (نماد معاملاتی) | **REVIEW** | فقط یک reader؛ ستون `Open` دارد. اگر منبعش فعال است `MERGE` در market، وگرنه legacy |
| `dbo.StockPrices` | daily price قدیمی | **LEGACY_DO_NOT_MIGRATE** | ۰ ارجاع |
| `dbo.FullPE` | valuation snapshot (P/E, Price) | **TRANSFORM** | snapshot؛ در مدل جدید باید به‌صورت اندازه‌گیری زمان‌دار (time-series valuation) ذخیره شود |
| `dbo.CodalReports` | report registry (dedup/status) | **MIGRATE** | منبع حقیقت پردازش گزارش‌ها؛ مدل خوبی دارد |
| `dbo.CodalSyncState` | ingestion state (watermark) | **MIGRATE** | کوچک و سالم |
| `dbo.TrackedTickers` | company/ticker universe | **REVIEW** | نماد-محور؛ در دنیای `CompanyID`-محور باید به جدول company/ticker نگاشت شود |
| `dbo.Users` | authentication/user profile | **TRANSFORM** | بدون PK؛ `Portfolio`/`ViewedItems` به‌صورت JSON در nvarchar → جدا/`jsonb` |
| `dbo.Family*` (People/Assets/Accounts/Holdings/Prices/CashFlows/History) | portfolio/asset management | **TRANSFORM/MERGE** | دامنه‌ی جدا؛ ساختار قابل نگه‌داری اما نیاز به FK و تاریخ واقعی |
| `dbo.fn_JalaliKey` | date key function | **TRANSFORM (app/DB function)** | در Postgres به تابع `IMMUTABLE` یا منطق اپلیکیشن تبدیل شود |

## Views

| Object | دامنه | وضعیت |
| --- | --- | --- |
| `vw_AIStockMetrics` | scoring engine | **TRANSFORM** → مدل‌شده به pipeline/app یا materialized view |
| `vw_AIStockMetrics2` | scoring (قدیمی) | **LEGACY_DO_NOT_MIGRATE** |
| `vw_AIStockMetrics3` | scoring (میانی) | **LEGACY_DO_NOT_MIGRATE** |

## نگاشت دامنه‌ای (خلاصه)

```
dbo.mahane            -> monthly_activities
dbo.miandore2         -> financial_facts (+ balance sheet / cash flow facts)
dbo.miandore          -> (legacy, حذف از دامنه)
dbo.MarketPriceHistory-> daily_market_prices
dbo.StockData         -> daily_market_prices (merge، اگر منبع فعال باشد)
dbo.FullPE            -> valuation_snapshots
dbo.CodalReports      -> report_registry
dbo.CodalSyncState    -> ingestion_state
dbo.TrackedTickers    -> company_universe / identifiers
dbo.Users             -> users / auth / user_profile
dbo.Family*           -> portfolio / family_assets
```

## مدل موجود py2 به‌عنوان هدف نگاشت

| دامنه | معادل py2 | پوشش فعلی |
| --- | --- | --- |
| `mahane` | `companies` + `reports` + `monthly_activities` | ✅ |
| `miandore2` (سود و زیان) | `financial_facts` | ✅ (فقط ۵ متریک، بدون ترازنامه/جریان) |
| `MarketPriceHistory` | — | ❌ |
| `FullPE` | — | ❌ |
| `CodalReports`/`CodalSyncState` | — | ❌ |
| `Users`/`Family*` | — | ❌ |
| scoring view | — | ❌ |
