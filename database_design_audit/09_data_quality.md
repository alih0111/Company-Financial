# 09 — Data Quality Audit

> این سند فقط فهرست مشکلات است؛ **هیچ چیزی اصلاح نشده**. severity = HIGH/MEDIUM/LOW.

## Identity

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 1 | `CompanyID = md5(company_name)` غیرپایدار و وابسته به رشته؛ مسیرهای مختلف رشته‌های متفاوت (نام کامل vs نماد) می‌فرستند | **HIGH** | `MianSql.py:60`, `sync_codal.py:265`, `codal_processor.py:26` |
| 2 | join بر اساس `CompanyName` در بخشی از کد و `CompanyID` در بخش دیگر | **HIGH** | `score_handler.go:72`, `company_score.go:124`, `price_history.go:56`, `scraperFullPE.py:47` در برابر `ai_stock_handler.go` |
| 3 | fuzzy/containment matching برای BRS↔Codal | **MEDIUM** | `brs_prices.py:518-597` |
| 4 | `TrackedTickers` نماد-محور ولی داده‌ی مرکزی `CompanyID`-محور | **MEDIUM** | `codal_universe.py` |
| 5 | ستون‌های `symbol` و `instrument_code` در Postgres `companies` هرگز پر نمی‌شوند | **MEDIUM** | `repository.py:110` |

## Units

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 6 | واحد `mahane.Value1/2/3` و همه‌ی مبالغ `miandore2` استخراج نمی‌شود | **HIGH** | `MianSql.py`, `MianSql2.py` (بدون `detect_currency_unit`) |
| 7 | `Product1 = EPS × سرمایه` مقیاس مخلوط | **HIGH** | `MianSql.py:625`, توضیح v3.7 در view |
| 8 | `OperatingProfitNew` گاهی per-share و گاهی مبلغی | **HIGH** | `vw_AIStockMetrics` `OpK`/`OpAmt` |
| 9 | heuristic حدس `million_rial` در py2 وقتی واحد نامعلوم است | **MEDIUM** | `py2/parsers/monthly.py:164`, `profit_loss.py:203` |

## Dates

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 10 | تاریخ‌های شمسی به‌صورت string (`nvarchar`/`char`) | **HIGH** | `mahane.ReportDate`, `miandore2.ReportDate`, `MarketPriceHistory.JalaliDate`, `Family*.DateKey` |
| 11 | نبود اعتبارسنجی/نرمال‌سازی مرکزی تاریخ جلالی (هر parser جدا) | **MEDIUM** | `fn_JalaliKey` + regexهای جداگانه |
| 12 | ناسازگاری UTC/local (`SYSUTCDATETIME` vs `getdate()` vs `datetime.now()`) | **MEDIUM** | `FamilyHistory.RecordedAt`, `FullPE.LastModified` |
| 13 | محاسبه‌ی «امروز شمسی» با offset دستی در view | **MEDIUM** | `vw_AIStockMetrics` (`MONTH(GETDATE())` + 621/622) |

## Schema / Integrity

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 14 | **صفر Foreign Key** در کل DB؛ یکپارچگی در کد | **HIGH** | inventory `04_foreign_keys.md` |
| 15 | `Users` هیچ PK/UNIQUE ندارد | **HIGH** | inventory `03_columns.md` / `05_indexes.md` |
| 16 | `float` برای مقادیر مالی | **HIGH** | همه‌ی جدول‌های مالی |
| 17 | JSON داخل `nvarchar` (`Users.Portfolio`, `Users.ViewedItems`) | **MEDIUM** | inventory |
| 18 | runtime DDL در handlerها و py (`family_assets.go`, `family_import.py`, `MianSql*`, `brs_prices`) | **MEDIUM** | `14_source_usage.md` |
| 19 | جدول‌های بازار تکراری (`StockData`/`StockPrices`/`MarketPriceHistory`) | **MEDIUM** | `07_market_data.md` |
| 20 | `FullPE` snapshot است و هر run کل جدول را پاک/بازنویسی می‌کند (از دست رفتن تاریخ) | **MEDIUM** | `scraperFullPE.py:64` |
| 21 | مقیاس `DECIMAL(24,0)` برای `TradeValue` و `BIGINT` برای قیمت (بدون واحد) | **LOW/MEDIUM** | inventory |

## Data / Pipeline

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 22 | رکوردهای تکراری/اصلاحی: هیچ مدل versioning در SQL Server نیست (در py2 هست) | **HIGH** | `miandore2`/`mahane` upsert بر اساس `(CompanyID, ReportDate)` |
| 23 | `miandore2` ستون‌های قدیمی (`Num*`) را هرگز به‌روزرسانی نمی‌کند (COALESCE-only) | **MEDIUM** | `MianSql.py:1385-1446` |
| 24 | `Url` در `mahane` بین مسیر legacy (فید) و sync (خود گزارش) ناسازگار | **LOW** | `MianSql2.py`, `codal_processor.py` |
| 25 | NULL-heavy: نسبت بالایی از ستون‌های جدید `miandore2` (ترازنامه/جریان) ممکن است NULL باشند | **MEDIUM** | `ALTER TABLE ADD` تدریجی |
| 26 | `StockData`/`StockPrices`/`statements` بدون writer در سورس → orphan-like/stale | **MEDIUM** | inventory + `14_source_usage.md` |
| 27 | `LastModificationDate` بدون writer | **LOW** | grep بدون نتیجه |
| 28 | مقادیر صفر در `Value1/Value2` برای گزارش‌های خدماتی → ambiguity با مقدار واقعی صفر | **MEDIUM** | `MianSql2.extract_one_month_values` |
| 29 | آستانه‌های corporate action heuristic (`-12%`/`-20%`) | **MEDIUM** | `brs_prices.py:1327` |
| 30 | مدیریت خطای parser با return `False`/`None` (بدون ثبت دلیل) | **LOW** | parserها |
| 31 | مسیرهای hardcoded ویندوزی در py | **LOW** | `FullPE.py:32`, `MianSql*.py` |
| 32 | `scraperFullPE` با `localhost`/`Trusted_Connection` (نه `.env`) | **MEDIUM** | `scraperFullPE.py:54-59` |

## View / Scoring

| # | مشکل | severity | شواهد |
| --- | --- | --- | --- |
| 33 | نسخه‌ی ریپو (`go-app/sql`) با DB نصب‌شده هم‌گام نیست (repo v3.6 vs DB v3.7) | **HIGH** | مقایسه‌ی فایل‌ها |
| 34 | سه نسخه‌ی view روی DB (`vw_AIStockMetrics`, `_2`, `_3`) | **MEDIUM** | inventory `06_views.md` |
| 35 | منطق سنگین کسب‌وکار داخل SQL (حدود ۹۰KB) → تست‌پذیری پایین | **MEDIUM** | `08_ai_metrics_decomposition.md` |
| 36 | `DataQualityScore` محدود به تازگی گزارش/قیمت (نه کیفیت واقعی داده) | **LOW** | view |
| 37 | رتبه‌ی خنثای پیش‌فرض (0.3/0.5) می‌تواند ارزیابی را مخدوش کند | **MEDIUM** | کامنت‌های view |

## Elder / Legacy

| # | مشکل | severity |
| --- | --- | --- |
| 38 | `miandore`, `StockPrices`, `vw_AIStockMetrics2/3`, `statements` (بدون مصرف) | **MEDIUM** |
| 39 | `StockData` نیمه‌متروک (فقط یک endpoint) | **MEDIUM** |
