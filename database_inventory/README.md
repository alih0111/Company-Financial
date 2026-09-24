# Database Inventory — `codal` (SQL Server)

گزارش کامل و **read-only** از ساختار دیتابیس فعلی پروژه. هیچ object/datum تغییر، حذف یا migrate نشده است.

- **Server:** Microsoft SQL Server 2022 (16.0.1140.6)
- **Database:** `codal`
- **Schemaهای کاربری:** فقط `dbo`
- **ابزار استخراج:** `database_inventory/extract_inventory.py` (فقط SELECT روی system catalog)
- **اتصال:** از `go-app/.env` خوانده می‌شود؛ هیچ credential در خروجی‌ها ذخیره نمی‌شود.

## آمار کلی

| مورد | تعداد |
| --- | --- |
| Schema کاربری | 1 (`dbo`) |
| Table | **19** |
| View | **3** |
| Scalar Function | **1** (`fn_JalaliKey`) |
| Table-Valued Function | 0 |
| Stored Procedure | **0** |
| Trigger | **0** |
| Sequence | 0 |
| Synonym | 0 |
| Foreign Key | **0** |
| Index | 24 (شامل PK/UNIQUE) |
| Check Constraint | 0 |
| Computed Column | 0 |
| Identity Column | 16 |
| Default Constraint | 20 |

## فایل‌های این inventory

| فایل | محتوا |
| --- | --- |
| `01_schemas.md` | لیست schemaها |
| `02_tables.md` | جدول‌ها + row count + تاریخ create/modify |
| `03_columns.md` | تعریف ستون‌های همه‌ی جدول‌ها |
| `04_foreign_keys.md` | کلیدهای خارجی (خالی) |
| `05_indexes.md` | ایندکس‌ها، included/filtered |
| `06_views.md` | Viewها + وابستگی‌ها |
| `07_procedures.md` | Stored Procedureها (خالی) |
| `08_functions.md` | توابع |
| `09_triggers.md` | تریگرها (خالی) |
| `10_other_objects.md` | sequence/synonym/check/queue |
| `11_dependency_graph.md` | گراف وابستگی |
| `12_samples.md` + `12_samples/` | حداکثر ۵ رکورد نمونه هر جدول (ستون‌های حساس mask) |
| `13_legacy_analysis.md` | تحلیل legacy/duplicate/staging |
| `14_source_usage.md` | نقشه‌ی استفاده در سورس |
| `sql/views/*.sql` | definition کامل viewها |
| `sql/functions/*.sql` | definition کامل توابع |
| `_facts.json` | داده‌ی خام استخراج‌شده |

## مهم‌ترین Tableهای business

| دسته | جدول‌ها |
| --- | --- |
| گزارش‌های کدال (ingestion state) | `CodalReports`, `CodalSyncState`, `TrackedTickers` |
| فعالیت ماهانه (فروش) | `mahane` |
| صورت سود و زیان (میان‌دوره) | `miandore2` (فعال)، `miandore` (legacy) |
| وضعیت/صورت‌های مالی عمومی | `statements` (بدون مصرف واقعی) |
| قیمت بازار | `MarketPriceHistory` (فعال)، `StockData`، `StockPrices` (legacy) |
| نسبت P/E | `FullPE` |
| کاربران/احراز هویت | `Users` |
| پورتفوی و دارایی خانواده | `FamilyPeople`, `FamilyAssets`, `FamilyAccounts`, `FamilyHoldings`, `FamilyPrices`, `FamilyCashFlows`, `FamilyHistory` |

## مهم‌ترین Viewها

| View | نقش |
| --- | --- |
| **`dbo.vw_AIStockMetrics`** | View اصلی امتیازدهی کمّی (`QuantScore`، رتبه‌ها، TTM، جریمه‌ها) — **فعال** |
| `dbo.vw_AIStockMetrics2` | نسخه‌ی قدیمی — بدون مصرف (legacy) |
| `dbo.vw_AIStockMetrics3` | نسخه‌ی میانی — بدون مصرف (legacy) |

هر سه روی چهار منبع زیر ساخته شده‌اند:

```
fn_JalaliKey  +  mahane (فروش ماهانه)  +  miandore2 (سود و زیان)  +  MarketPriceHistory (قیمت)
```

`vw_AIStockMetrics` یک View بسیار پیچیده (حدود ۹۰KB) با ۹۱ پنجره‌ی `OVER()`، ۳۳ `TRY_CONVERT`، `LAG`/`ROW_NUMBER`/`RANK` و توابع تاریخ است.

## جداولی که ingestion روی آن‌ها می‌نویسد

| جدول | نویسنده |
| --- | --- |
| `mahane` | `py/MianSql2.py`, `py/scraper2.py`, `py/codal_processor.py`, `py/sync_codal.py` |
| `miandore2` | `py/MianSql.py`, `py/scraper.py`, `py/codal_processor.py`, `py/sync_codal.py` |
| `MarketPriceHistory` | `py/price.py`, `py/brs_prices.py` |
| `FullPE` | `py/scraperFullPE.py` (DELETE + insert) |
| `CodalReports` / `CodalSyncState` | `py/codal_registry.py`, `py/codal_sync_state.py` |
| `TrackedTickers` | `py/codal_universe.py`, `py/codal_prefilter.py` |
| `Family*` | `py/family_import.py` و runtime DDL در `go-app/handlers/family_assets.go` (`CREATE/ALTER/MERGE`) |

## جداولی که Go API از آن‌ها می‌خواند

| جدول | محل مصرف |
| --- | --- |
| `mahane`, `miandore2`, `FullPE` | `company_score.go`, `score_handler.go`, `sales_data.go`, `sales_data2.go` |
| `MarketPriceHistory` | `price_history.go`, `family_assets.go`, و `vw_AIStockMetrics` |
| `vw_AIStockMetrics` | `ai_stock_handler.go` (`/summary`, `/detail`, `/analyze`) |
| `Users` | `auth.go`, `portfolio.go`, `userViewed.go` |
| `StockData` | `stock_analysis.go` (`/StockPriceScore`) |
| `Family*` | `family_assets.go` |

## دسته‌بندی دامنه‌ای

- **قیمت:** `MarketPriceHistory` (اصلی)، `StockData`، `StockPrices` (legacy)، `FullPE` (P/E)، `FamilyPrices` (قیمت دارایی خانواده).
- **گزارش کدال:** `CodalReports`, `CodalSyncState`, `TrackedTickers`.
- **صورت‌های مالی:** `miandore2` (فعال)، `miandore` (legacy)، `statements` (بدون مصرف).
- **فعالیت ماهانه:** `mahane`.
- **کاربران/احراز هویت:** `Users` (بدون PK؛ ستون‌های `Password`, `Token`, `Email`, `IsAdmin`, `Portfolio`).
- **پورتفوی/دارایی:** `FamilyPeople`, `FamilyAssets`, `FamilyAccounts`, `FamilyHoldings`, `FamilyPrices`, `FamilyCashFlows`, `FamilyHistory` + JSON `Users.Portfolio`.

## Objectهای مشکوک به legacy

`miandore`, `StockPrices`, `vw_AIStockMetrics2`, `vw_AIStockMetrics3`, `statements` (بدون مصرف واقعی)، و `StockData` (هم‌پوشان/نیمه‌متروک).
جزئیات در `13_legacy_analysis.md`.

---

# Potential Migration Issues (SQL Server → PostgreSQL)

> این بخش فهرست مواردی است که در مهاجرت به PostgreSQL نیاز به توجه/بازنویسی دارند. (فقط گزارش؛ هیچ تغییری اعمال نشده.)

## 1) انواع داده

| SQL Server | محل استفاده | معادل/راه‌حل PostgreSQL |
| --- | --- | --- |
| `NVARCHAR(n/max)` | تقریباً همه‌ی جدول‌ها (نام‌ها، تاریخ جلالی، URL) | `text` یا `varchar(n)`؛ دیگر نیازی به `N` نیست |
| `VARCHAR(n)` | `statements.Url`, `MarketPriceHistory.InstrumentCode/Url` | `varchar(n)`/`text` |
| `DATETIME` | `FamilyHistory.RecordedAt` | `timestamp` |
| `DATETIME2(7)` | `PublishedAt`, `CollectedAt`, `DiscoveredAt`, ... | `timestamptz`/`timestamp` |
| `DATE` | `MarketPriceHistory.GregorianDate`, `StockData.TradeDate` | `date` |
| `MONEY` | (استفاده نشده) | `numeric` |
| `FLOAT(53)` | تمام مقادیر مالی و امتیازها | `double precision`؛ برای مقادیر مالی بهتر است `numeric` |
| `DECIMAL(12,4)` | `ClosingChangePercent`, `LastChangePercent` | `numeric(12,4)` |
| `DECIMAL(24,0)` | `MarketPriceHistory.TradeValue` | `numeric(24,0)` |
| `BIGINT` | حجم/تعداد معاملات | `bigint` |
| `BIT` | `IsActive`, `IsOnline`, `IsAdmin` | `boolean` |
| `CHAR(10)` | `MarketPriceHistory.JalaliDate` | `char(10)`/`text` |

## 2) IDENTITY و کلیدها

- **IDENTITY** در ۱۶ ستون (مثلاً `Users.ID`, `mahane.ID`, `miandore2.ID`, `Family*.ID`). → در Postgres باید `GENERATED ... AS IDENTITY` یا `serial` شود.
- `FullPE.ID` identity است اما **PK روی `CompanyName`** تعریف شده → وقتی PK اصلی به `ID` منتقل شود، ترتیب باید حفظ شود.
- **`Users` هیچ PK/UNIQUE ندارد** → باید PK جدید تعریف و قبل از مهاجرت رکوردهای تکراری پاک‌سازی شوند.
- **صفر کلید خارجی** در DB → یکپارچگی referential در کد است؛ در Postgres می‌توان FK واقعی اضافه کرد ولی داده‌ی یتیم می‌تواند مهاجرت را بشکند.

## 3) سینتکس و توابع T-SQL

| T-SQL | محل | معادل PostgreSQL |
| --- | --- | --- |
| `TOP (n)` | `vw_AIStockMetrics` و کوئری‌های Go | `LIMIT n` |
| `ISNULL(a, b)` | viewها (۱۶ بار) و کوئری‌های Go | `COALESCE(a, b)` |
| `GETDATE()` / `SYSDATETIME()` / `SYSUTCDATETIME()` | defaultها و viewها (۱۸ بار) | `now()` / `clock_timestamp()` / `now() AT TIME ZONE 'UTC'` |
| `TRY_CONVERT` / `TRY_CAST` | viewها (۳۳ بار) | `CAST` در `BEGIN…EXCEPTION` یا تابع کمکی `try_cast` سفارشی |
| `CAST(... AS ...)` | viewها | `CAST` (سازگار) |
| `DATEDIFF` | viewها | `EXTRACT`/تفریق interval |
| `CHARINDEX` | `fn_JalaliKey`, viewها | `strpos`/`position` |
| `LEN` | viewها | `length` |
| `SUBSTRING` | `fn_JalaliKey` | `substring` (سازگار) |
| `LTRIM/RTRIM` | `fn_JalaliKey`, viewها | `trim` |
| `NULLIF`, `COALESCE` | viewها | سازگار |
| `ROW_NUMBER()`, `RANK()`, `LAG()`, `OVER()` | viewها (۹۱ پنجره) | سازگار (Postgres از ۸.۴ به بعد) |
| `N'...'` unicode literals | همه‌جا | حذف پیشوند `N` |
| `[bracket]` identifiers | کوئری‌ها | `"double quotes"` یا snake_case |
| `@p1`, `sql.Named` | Go (`go-mssqldb`) | `$1, $2` و placeholders پستگرس |

## 4) توابع، View و منطق سرور

- **`dbo.fn_JalaliKey` (Scalar UDF):** تبدیل کلید تاریخ جلالی. در Postgres باید به یک PL/pgSQL function یا تابع اپلیکیشن تبدیل شود. اگر به‌صورت computed/functional index لازم باشد، تابع باید `IMMUTABLE` باشد.
- **Viewهای بسیار پیچیده:** `vw_AIStockMetrics` منطق سنگین امتیازدهی (TTM، رتبه‌بندی درصدی، جریمه‌ها) را داخل SQL دارد. در Postgres این را می‌توان view/materialized view یا منطق اپلیکیشن کرد، اما خط‌به‌خط باید ترجمه شود.
- **Indexed View:** هیچ view ای indexed نیست (بررسی شد) → ریسک سمت view کمتر است، اما پرفورمنس view اصلی باید با indexهای معادل حفظ شود.
- **Computed Column:** هیچ ستون computed وجود ندارد → مشکلی از این بابت نیست.

## 5) Collation و Unicode

- همه‌ی ستون‌های متنی `SQL_Latin1_General_CP1_CI_AS` هستند ولی داده‌ی فارسی در آن‌ها ذخیره شده (به لطف `nvarchar`).
- در Postgres باید `UTF8` و collation مناسب (مثلاً `fa-IR`/`C`) انتخاب شود و یکتایی حساب‌ها/نام‌ها تست شود.

## 6) اشیای غیرقابل مهاجرت مستقیم

- ۰ Stored Procedure، ۰ Trigger، ۰ Sequence، ۰ Synonym → سطح مهاجرت DDL ساده‌تر است.
- runtime DDL در `family_assets.go` و `family_import.py` → باید به migration رسمی Postgres تبدیل شود.

## 7) داده‌ی تاریخ و ذخیره‌ی JSON

- تاریخ‌های جلالی به‌صورت **رشته‌ی nvarchar** ذخیره شده‌اند (`ReportDate`, `DateKey`, `JalaliDate`) → پیشنهاد: در Postgres به `date`/کلید عددی (`fn_JalaliKey`) تبدیل شوند.
- `Users.ViewedItems` و `Users.Portfolio` شامل **JSON فشرده در nvarchar** هستند → کاندید `jsonb`.
- اعداد پولی با `float` ذخیره شده‌اند → احتمال خطای گردکردن؛ در Postgres از `numeric` استفاده شود.

## 8) سایر موارد

- **`TOP` + `ORDER BY` در کوئری‌های Go:** به `LIMIT` ترجمه شود.
- **`sql.Named` و `@` placeholders** باید به placeholderهای positional پستگرس تبدیل شوند.
- مسیرهای hardcoded ویندوزی (`C:\Users\aliheyd\...`) در اسکریپت‌های py قبل از اجرای روی محیط جدید اصلاح شوند.

---

## بازتولید گزارش

```powershell
python database_inventory/extract_inventory.py
```

اسکریپت کاملاً read-only است و فقط SELECT روی catalog می‌زند.
