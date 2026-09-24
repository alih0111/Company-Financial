# 13 — Legacy / Duplicate / Staging / Unused Analysis

> این فایل فقط **علامت‌گذاری** است. هیچ object حذف، rename یا تغییر داده نشده است.
> مبنا: تعداد ردیف، تاریخ create/modify، و میزان ارجاع واقعی در سورس (`14_source_usage.md`).

## خلاصه تصمیم‌ها

| Object | وضعیت | دلیل |
| --- | --- | --- |
| `dbo.miandore` | **LEGACY / STALE** | ۰ ارجاع در سورس؛ superseded توسط `miandore2`؛ آخرین modify در 2025-07-03 |
| `dbo.StockPrices` | **LEGACY** | ۰ ارجاع در سورس؛ آخرین modify در 2025-07-03؛ فقط ۲۷۷ ردیف |
| `dbo.vw_AIStockMetrics2` | **LEGACY** | ۰ ارجاع در سورس؛ نسخه‌ی قدیمی view اصلی |
| `dbo.vw_AIStockMetrics3` | **LEGACY** | ۰ ارجاع در سورس؛ نسخه‌ی میانی view اصلی |
| `dbo.statements` | **UNUSED / STAGING** | هیچ ارجاع واقعی در سورس (تنها hit یک متغیر Go به نام `statements` بود) |
| `dbo.StockData` | **SUSPECT (نیمه‌متروک)** | فقط یک endpoint (`StockPriceScore`) از آن می‌خواند؛ هم‌پوشان با `MarketPriceHistory` |
| `dbo.FullPE` | **ACTIVE (با ریسک افزونگی)** | توسط Go و py استفاده می‌شود، اما P/E در view هم محاسبه می‌شود |
| `dbo.Users` | **ACTIVE (ریسک داده)** | بدون Primary Key؛ ستون `Token` بدون ایندکس |

## جزئیات

### 1) `dbo.miandore` — legacy
- create/modify: `2025-07-03`، ۶۷۹ ردیف، بدون هیچ ارجاع در `go-app/**`.
- ساختار قدیمی سود و زیان (`Value1..Value3`, `Sarmaye`) که با `dbo.miandore2` جایگزین شده است.
- `miandore2` فعال است (۷۴ ارجاع در ۱۹ فایل، شامل `scraper.py`، `codal_processor.py`، `sync_codal.py` و handlerها).

### 2) `dbo.StockPrices` — legacy
- create/modify: `2025-07-03`، ۲۷۷ ردیف، ۰ ارجاع.
- ساختار `date nvarchar`, `CompanyName`, `mean_price nvarchar` … که با `MarketPriceHistory` (۷۰۵٬۸۱۲ ردیف، فعال) جایگزین شده است.

### 3) `vw_AIStockMetrics2` و `vw_AIStockMetrics3` — legacy views
- هر دو همان چهار منبع `vw_AIStockMetrics` را می‌خوانند (`mahane`, `miandore2`, `MarketPriceHistory`, `fn_JalaliKey`).
- فقط `vw_AIStockMetrics` در سورس استفاده می‌شود (۶ فایل). نسخه‌های ۲ و ۳ هیچ ارجاعی ندارند و در DB باقی مانده‌اند.
- توجه: `vw_AIStockMetrics3` اندازه‌ی نزدیک به view اصلی دارد (۸۱KB در برابر ۹۰KB) و margin بهبودها را نگه می‌دارد.

### 4) `dbo.statements` — staging / unused
- create: `2026-07-24`، ۵٬۹۲۰ ردیف، UNIQUE روی `(CompanyID, ReportDate, StatementType, MetricCode, PeriodOrder)`.
- ساختار آن شبیه `financial_facts` در خط لوله‌ی PostgreSQL (`py2`) است (metric-code based، generic).
- هیچ writer/reader واقعی در `go-app/**` پیدا نشد → احتمالاً یک staging table مربوط به طراحی جدید یا نسخه‌ی نیمه‌کاره.

### 5) `dbo.StockData` — نیمه‌متروک / هم‌پوشان
- فقط در `go-app/handlers/stock_analysis.go` (endpoint `StockPriceScore`) استفاده می‌شود.
- داده‌ی OHLC روزانه دارد و کارکردش با `MarketPriceHistory` هم‌پوشانی دارد.

## هم‌پوشانی‌ها (Duplicate-like groups)

| گروه | Objectها | توضیح |
| --- | --- | --- |
| ذخیره‌ی قیمت | `StockData`, `StockPrices`, `MarketPriceHistory` | سه جدول با کارکرد مشابه؛ فقط `MarketPriceHistory` فعال و کامل است |
| سود و زیان میان‌دوره | `miandore`, `miandore2` | `miandore` متروک |
| نسبت P/E | `FullPE` و محاسبه‌ی `PEApprox` در `vw_AIStockMetrics` | دو منبع موازی P/E |
| View امتیازدهی | `vw_AIStockMetrics`, `_2`, `_3` | فقط نسخه‌ی بدون پسوند فعال است |
| داده‌ی ماهانه | `mahane` و (به‌طور موازی) `py2.monthly_activities` در Postgres | دو خط لوله‌ی موازی |

## نکات غیر-legacy اما مهم

- **DDL در زمان اجرا (runtime DDL):** `go-app/handlers/family_assets.go` و `go-app/py/family_import.py` جدول‌های `Family*` را با `CREATE TABLE`/`ALTER TABLE`/`MERGE` می‌سازند و تغییر می‌دهند. این یعنی schema بخشی از کد اپلیکیشن است، نه migration مستقل.
- **مسیر hardcoded:** در `py/FullPE.py`, `py/MianSql.py`, `py/MianSql2.py`, `py/price.py` مسیر `C:\Users\aliheyd\...` ثابت نوشته شده؛ برای portability باید env-driven شود.
- **`py2` کاملاً جدا از `codal` است:** خط لوله‌ی `codal_ingestor` روی PostgreSQL کار می‌کند و هیچ ارجاعی به جدول‌های `codal` ندارد.

## ریسک‌های داده (flag، بدون تغییر)

1. `dbo.Users` هیچ PK/UNIQUE روی `ID` یا `UserName` ندارد → احتمال رکورد تکراری در مهاجرت.
2. `dbo.Users.Password` روی `nvarchar(950)` است (هش bcrypt) — هنگام مهاجرت باید `text`/`varchar` شود.
3. `dbo.Users.Token` روی `nvarchar(max)` بدون ایندکس.
4. `dbo.FullPE` ستون Identity دارد (`ID`) اما PK روی `CompanyName` است.
5. تاریخ‌های جلالی به‌صورت `nvarchar` ذخیره شده‌اند (`ReportDate`, `DateKey`, `JalaliDate`) → نیاز به normalize در Postgres.
6. مقادیر مالی با `float(53)` ذخیره شده‌اند (نه `decimal`/`money`) → ریسک دقت.
