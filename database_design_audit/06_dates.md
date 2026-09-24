# 06 — Date Audit

> مبنا: trace کد. هیچ حدسی زده نشده؛ موارد نامعلوم `UNKNOWN`.

## فهرست ستون‌های تاریخ/زمان

| ستون | جدول | نوع SQL Server | معنی business | نحوه‌ی تولید |
| --- | --- | --- | --- | --- |
| `ReportDate` | `mahane`, `miandore2`, `CodalReports` | `nvarchar(50)` / `nvarchar(20)` | **پایان دوره‌ی گزارش** به شمسی (`YYYY/MM/DD`) | از `#ctl00_lblPeriodEndToDate` (MianSql/MianSql2) یا header جدول |
| `JalaliDate` | `MarketPriceHistory` | `char(10)` | تاریخ معاملات شمسی | از `parse_brs_timestamp`/`parse_brs_date` (تبدیل میلادی→شمسی) |
| `GregorianDate` | `MarketPriceHistory` | `date` | تاریخ معاملات میلادی | از timestamp/فیلد تاریخ BRS یا `today_jalali` |
| `DateKey` | `Family*` (`FamilyHistory`, `FamilyPrices`, `FamilyCashFlows`) | `nvarchar(10)` | تاریخ شمسی snapshot/قیمت/جریان نقدی | `family_import.py` / Go handlerها |
| `PublishedAt` | `CodalReports` | `datetime2` | زمان انتشار گزارش در کدال (میلادی) | `codal_feed.parse_persian_datetime` از `PublishDateTime` |
| `CollectedAt` | `MarketPriceHistory`, `statements` | `datetime2` | زمان جمع‌آوری رکورد | default `SYSUTCDATETIME()` / `sysdatetime()` |
| `LastModificationDate` | `mahane` | `datetime2` | **UNKNOWN** — در سورس نوشته نمی‌شود | — |
| `ProcessedAt` | `CodalReports` | `datetime2` | زمان پردازش نهایی گزارش | `codal_registry._set_status` با `SYSUTCDATETIME()` |
| `DiscoveredAt` | `CodalReports` | `datetime2` | زمان کشف گزارش | default `SYSUTCDATETIME()` |
| `updated_at` / `created_at` | `py2` tables | `timestamptz` | زمان‌های سیستم (Postgres) | `now()` |
| `period_end_date` | `py2.reports` | `date` | پایان دوره‌ی گزارش (میلادی) | `jalali_to_gregorian` |
| `RecordedAt` | `FamilyHistory` | `datetime` | زمان ثبت snapshot | default `getdate()` (**محلی/بدون TZ**) |

## نکته‌ی UTC vs محلی

- `SYSUTCDATETIME()` (UTC): `CodalReports.DiscoveredAt/ProcessedAt`, `MarketPriceHistory.CollectedAt`, `CodalSyncState.UpdatedAt`, `TrackedTickers.CreatedAt`, `statements.CollectedAt` (sysdatetime → **محلی**).
- `getdate()` (محلی): `FamilyHistory.RecordedAt`.
- `datetime.now()` (محلی): `FullPE.LastModified`.
- **ناسازگاری منطقه‌ی زمانی** بین ستون‌ها وجود دارد (بعضی UTC، بعضی local) → ریسک در مهاجرت.

## `fn_JalaliKey` — دقیقاً چه می‌کند؟

- ورودی `@date NVARCHAR(30)`.
- `-` و فاصله را با `/` یکسان و حذف می‌کند، سپس `Y/M/D` را با `CHARINDEX` جدا می‌کند.
- با `TRY_CONVERT(INT, ...)` اجزاء را عددی می‌کند؛ اگر نامعتبر یا خارج از بازه (۱..۱۲ ماه، ۱..۳۱ روز) → `NULL`.
- خروجی: عدد صحیح `YYYYMMDD` (مثلاً `1404/09/30` → `14040930`).
- **برنمی‌گرداند:** تاریخ واقعی؛ فقط یک کلید مرتب‌سازی/مقایسه‌ی عددی است.

### کاربردها
- در `vw_AIStockMetrics`: `JYear = fn_JalaliKey(ReportDate)/10000`، `JMonth = (fn_JalaliKey(ReportDate)%10000)/100`، و `ORDER BY fn_JalaliKey(ReportDate)` برای مرتب‌سازی زمانی. **نکته:** تابع روی هر ردیف صدا زده می‌شود → می‌تواند پرهزینه و مانع استفاده از index باشد.
- در `ai_stock_handler.go` (`getMonthlyPoints`, `getProfitPoints`): فیلتر `WHERE dbo.fn_JalaliKey(ReportDate) IS NOT NULL`.

## تاریخ‌های string که در Postgres بهتر است `date`/`timestamptz` شوند

| ستون فعلی | پیشنهاد |
| --- | --- |
| `mahane.ReportDate` | `date` (شمسی) یا `date` میلادی + یک ستون جدا برای شمسی، یا کلید عددی |
| `miandore2.ReportDate` | همان |
| `CodalReports.ReportDate` | `date` |
| `MarketPriceHistory.JalaliDate` | `date` (یا نگه‌داشتن به‌عنوان ستون مشتق) |
| `Family*.DateKey` | `date` |
| `users.Portfolio` (JSON با `buy_date`) | `date` داخل `jsonb` |
| `LastModificationDate` | `timestamptz` (پس از روشن شدن معنایش) |

## `UNKNOWN`ها

- معنای `LastModificationDate` و اینکه «آخرین تغییر گزارش» است یا «آخرین تغییر رکورد».
- اینکه `statements.CollectedAt` با `sysdatetime()` (محلی) یا UTC پر شده در داده‌ی فعلی.
