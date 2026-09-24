# 04 — Date & Time Policy

> investigation فقط. مبنا: schema فعلی + نمونه‌ی داده + `fn_JalaliKey` + `jdatetime`.

## دسته‌بندی Business Date vs Event Timestamp

| ستون | جدول | دسته | معنی | نوع فعلی | نمونه واقعی |
| --- | --- | --- | --- | --- | --- |
| `ReportDate` | `mahane`, `miandore2`, `statements` | **Business date (fiscal period end)** | پایان دوره‌ی گزارش (شمسی) | `nvarchar` | `1405/05/31` |
| `JalaliDate` | `MarketPriceHistory` | **Business date (trading date)** | تاریخ معاملات شمسی | `char(10)` | `1405/07/02` |
| `GregorianDate` | `MarketPriceHistory` | **Business date (trading date)** | تاریخ معاملات میلادی | `date` | `2026-09-24` |
| `DateKey` | `Family*` | **Business date** | تاریخ snapshot/قیمت/جریان | `nvarchar(10)` | `1405/07/02` |
| `CodalReports.ReportDate` | `CodalReports` | Business date | تاریخ گزارش | `nvarchar(20)` | — |
| `PublishedAt` | `CodalReports` | **Event timestamp** | زمان انتشار در کدال | `datetime2` | `2026-09-24 17:03:32` |
| `DiscoveredAt` | `CodalReports` | Event timestamp | زمان کشف | `datetime2` (SYSUTCDATETIME) | `2026-09-24 14:32:32` |
| `ProcessedAt` | `CodalReports` | Event timestamp | زمان پردازش | `datetime2` (SYSUTCDATETIME) | — |
| `CollectedAt` | `MarketPriceHistory`, `statements` | Event timestamp | زمان جمع‌آوری | `datetime2` (SYSUTCDATETIME / sysdatetime) | `2026-09-24 17:01:10.652` |
| `LastModificationDate` | `mahane` | Event timestamp؟ | **UNKNOWN** (writer ندارد) | `datetime2` | — |
| `RecordedAt` | `FamilyHistory` | Event timestamp | زمان ثبت snapshot | `datetime` (**getdate → local**) | — |

## Timezone: داده naive است
- همه‌ی ستون‌ها `datetime2`/`datetime` بدون offset هستند → **naive**.
- بیشتر ingestionها از `SYSUTCDATETIME()` استفاده می‌کنند (UTC)، ولی `FamilyHistory.RecordedAt` از `getdate()` (محلی تهران) و `FullPE.LastModified` از `datetime.now()` (محلی).
- `CodalReports.PublishedAt` از `parse_persian_datetime(...).togregorian()` ساخته می‌شود که یک `datetime` naive (زمان کدال، تهران) است → **به‌عنوان UTC ذخیره نشده**.
- نتیجه: در یک ستون/جدول، UTC و local مخلوط است → **ناسازگاری منطقه‌ی زمانی**.

## `fn_JalaliKey` و 1405/06/31
- `fn_JalaliKey('1405/06/31')` → `14050631` (فقط کلید عددی مرتب‌سازی؛ تاریخ واقعی نیست).
- اعتبارسنجی با `jdatetime`:
  - `1405/06/31` → **معتبر** → `2026-09-22` (سه‌شنبه). (ماه‌های ۱..۶ در تقویم جلالی ۳۱ روزه‌اند.)
  - `1405/07/01` → معتبر → `2026-09-23`.
  - `1405/12/29` → معتبر → `2027-03-20`.
  - `1405/12/30` و `1404/12/30` → **نامعتبر** (سال‌های غیرکبیسه اسفند ۲۹ روزه دارند).
- **قاعده‌ی تبدیل/اعتبارسنجی:** از یک مبدل تقویم واقعی (jdatetime / کتابخانه‌ی Postgres) استفاده شود و **هیچ roll-over انجام نشود**؛ تاریخ نامعتبر باید رد شود، نه اینکه به ماه بعد بچرخد.
- بررسی داده‌ی فعلی: `SELECT COUNT(*) FROM miandore2 WHERE fn_JalaliKey(ReportDate) IS NULL` → **۰**؛ بازه `1398/01/31` تا `1405/05/31`. یعنی همه‌ی `ReportDate`های فعلی معتبرند.

## Policy پیشنهادی (بررسی‌شده، نه کورکورانه)

اصول پیشنهادی و ارزیابی آن‌ها برای بازار ایران:

1. **تاریخ اصلی محاسباتی = Gregorian `date`.** ✅ مناسبی؛ اما توجه: مرز روز معاملاتی در ایران = نیمه‌شب تهران (نه UTC). اگر فقط `date` ذخیره شود، ambigu­ity مرز روز جهانی مشکل‌ساز می‌شود. راه‌حل: `date` برای business date + ذخیره‌ی صریح `jalali` به‌عنوان ستون قابل‌نمایش/کلید فصلی.
2. **تاریخ جلالی = metadata/display.** ✅ نگه‌داشتن `fiscal_year_jalali`, `fiscal_month_jalali` (int) برای rank/فصلی، در کنار `date`.
3. **Event timestamps به UTC.** ✅ `timestamptz` با UTC ذخیره شود. توجه: چون `PublishedAt` فعلی در واقع زمان تهران است، مهاجرت باید آن را به UTC تبدیل کند (تهران = UTC+3:30).
4. **Timezone در display تبدیل شود.** ✅ لایه‌ی نمایش (frontend) به `Asia/Tehran` تبدیل کند. ایران از ۲۰۲۲ DST ندارد → offset ثابت +3:30.
5. **fiscal year/month جداگانه.** ✅ همان بند ۲.

### نگاشت نوع Postgres پیشنهادی

| فیلد فعلی | نوع پیشنهادی | یادداشت |
| --- | --- | --- |
| `ReportDate` (mahane/miandore2) | `date` (Gregorian) + `jalali_text` + `fiscal_year/month int` | تبدیل با مبدل معتبر |
| `JalaliDate` (MPH) | `date` (Gregorian، از قبل `GregorianDate` داریم) + `jalali_text` اختیاری | `GregorianDate` canonical |
| `GregorianDate` (MPH) | `date` | ✅ canonical trading date |
| `DateKey` (Family*) | `date` (Gregorian) + jalali metadata | — |
| `PublishedAt` | `timestamptz` (UTC، تبدیل از تهران) | — |
| `DiscoveredAt/ProcessedAt/CollectedAt` | `timestamptz` (UTC) | ✅ فعلی تقریباً UTC است |
| `RecordedAt`/`LastModified` | `timestamptz` (UTC) | فعلی local → باید تبدیل شود |
| `fn_JalaliKey` | منطق اپلیکیشن/تابع `immutable` + ستون‌های پیش‌محاسبه | کلید مرتب‌سازی |

## UNKNOWNها
- منطقه‌ی زمانی واقعی `statements.CollectedAt` (sysdatetime = local یا UTC؟).
- معنای `LastModificationDate` (writer ندارد).
