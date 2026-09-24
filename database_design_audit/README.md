# Semantic Data Audit — خلاصه‌ی نهایی

> این پوشه حاصل یک audit **فقط خواندنی (read-only)** است. هیچ DDL/DML روی SQL Server یا PostgreSQL اجرا نشده، هیچ جدول/ستون rename نشده، و هیچ کد اپلیکیشن تغییر نکرده است.
> تکمیل‌کننده‌ی `database_inventory/` است؛ برای ساختار فیزیکی به آن مراجعه کنید.

## فایل‌های این audit

| فایل | موضوع |
| --- | --- |
| `01_py2_postgres_model.md` | مدل فعلی PostgreSQL/py2 |
| `02_mahane_semantics.md` | معنای واقعی `dbo.mahane` |
| `03_miandore2_semantics.md` | معنای واقعی `dbo.miandore2` |
| `04_company_identity.md` | شناسه‌های شرکت و نگاشت‌ها |
| `05_units.md` | واحدها و workaroundهای واحد |
| `06_dates.md` | تاریخ‌ها و `fn_JalaliKey` |
| `07_market_data.md` | جداول قیمت |
| `08_ai_metrics_decomposition.md` | تجزیه‌ی `vw_AIStockMetrics` |
| `09_data_quality.md` | مشکلات داده با severity |
| `10_old_to_domain_mapping.md` | نگاشت دامنه‌ای |
| `11_unknowns.md` | موارد نامعلوم |

---

## ۱) وضعیت فعلی data architecture

- **دو خط لوله‌ی موازی:**
  - **SQL Server (`codal`)** — خط لوله‌ی اصلی و فعال: ingestion (Playwright/pyodbc) + Go/Gin API + view امتیازدهی + React SPA.
  - **PostgreSQL (`py2`)** — خط لوله‌ی نیمه‌کاره/جدا: مدل نرمال‌شده برای فعالیت ماهانه و سود و زیان، بدون اتصال به Go.
- **جداول اصلی SQL Server:** `mahane` (ماهانه)، `miandore2` (صورت‌های مالی wide)، `MarketPriceHistory` (قیمت)، `FullPE` (P/E snapshot)، `Users` (auth)، `Family*` (دارایی خانوادگی)، و سه metadata (`CodalReports`, `CodalSyncState`, `TrackedTickers`).
- **استخراج:** کدال (feed + صفحه‌ی گزارش) و BRS/TSETMC (قیمت).
- **امتیازدهی:** کاملاً داخل `vw_AIStockMetrics` (v3.7 روی DB، ~۹۰KB) و یک handler AI خارجی.

## ۲) مهم‌ترین technical debtها

1. **ناسازگاری `CompanyID`** (`md5(name)` وابسته به رشته‌ی ورودی) و درهم‌آمیزی join روی `CompanyName` و `CompanyID`.
2. **نبود واحد و مقیاس** در ingestion → منطق جبرانی سنگین (`OpK`/`OpAmt`/`NPUnitRatio`/`TTM` دستی) داخل view.
3. **`Product1 = EPS × سرمایه`** با مقیاس مخلوط که منشأ بخش بزرگی از پیچیدگی view است.
4. **تاریخ‌های شمسی به‌صورت string** و نبود ستون تاریخ میلادی.
5. **صفر Foreign Key** و **`Users` بدون PK**.
6. **runtime DDL** در handlerها و parserها.
7. **جدول‌های بازار تکراری** و **viewهای نسخه‌دار موازی**.
8. **drift بین `go-app/sql/vw_AIStockMetrics.sql` (v3.6) و DB (v3.7)**.
9. **`FullPE` snapshot** با DELETE-همه در هر اجرا.

## ۳) مهم‌ترین data quality problems

- واحدهای متناقض (HIGH)، identity ناپایدار (HIGH)، تاریخ رشته‌ای (HIGH)، نبود FK/PK (HIGH)، float برای پول (HIGH).
- جدول‌های بدون writer (`StockData`, `StockPrices`, `statements`) و بدون writer/ستون (`LastModificationDate`) (MEDIUM).
- JSON داخل nvarchar، duplicate market tables، stale/legacy objects (MEDIUM).
- جزئیات کامل + severity: `09_data_quality.md`.

## ۴) وضعیت py2/PostgreSQL فعلی

- کد تمیز، نرمال‌شده و مبتنی بر SQLAlchemy 2 + Alembic.
- دامنه‌ی محدود: فقط **monthly_activities** و **financial_facts** (۵ متریک سود و زیان).
- **بدون** قیمت، P/E، کاربران، portfolio، scoring، registry کدال، و **بدون** ترازنامه/جریان نقدی.
- کاملاً **جدا از Go** (هیچ handler/endpoint آن را صدا نمی‌زند).
- `companies.symbol`/`instrument_code` تعریف شده‌اند ولی هرگز پر نمی‌شوند.

## ۵) چه قسمت‌هایی از py2 قابل استفاده‌ی مجدد است؟

- ✅ **الگوی مدل‌سازی:** `companies`/`reports`/`report_versions`/`monthly_activities`/`financial_facts` (UUID, FK, UNIQUE, JSONB, Numeric, تاریخ میلادی).
- ✅ **لایه‌ی domain:** نرمال‌سازی متن/برچسب/نام، `jalali_to_gregorian`, `to_decimal`, `content_hash`.
- ✅ **الگوی versioning گزارش‌ها** (`report_versions` + content hash) — دقیقاً چیزی که در SQL Server نیست.
- ✅ **parsers:** تشخیص ستون‌های یک‌ماهه، ردیف جمع، و `detect_currency_unit`.
- ✅ **repository/upsert** با `on_conflict_do_update`.

## ۶) چه قسمت‌هایی باید بازطراحی شوند؟

- **مدل financial_facts:** باید ترازنامه و جریان نقدی هم پوشش دهد (نه فقط ۵ متریک).
- **monthly_activities:** باید «کل فروش داخلی/صادراتی» و متریک‌های بیشتر را پوشش دهد (فعلاً دارد، اما نگاشت به `mahane` ناقص است).
- **company identity:** باید `symbol`/`instrument_code` پر شود و از `md5(name)` به شناسه‌ی واقعی (ISIN/TracingNo) مهاجرت کند.
- **collectors/browser:** وابسته به Chromium محلی و selectboxهای شکننده؛ نیاز به retry/observability بهتر.
- **اضافه‌کردن دامنه‌های غایب:** قیمت، valuation، users/portfolio، registry، scoring.
- **حذف منطق جبرانی از view** با کد کردن واحد/مقیاس در زمان ingestion.

## ۷) جدول‌های legacy

`miandore`, `StockPrices`, `vw_AIStockMetrics2`, `vw_AIStockMetrics3`, `statements` (بدون مصرف واقعی)، و `StockData` (نیمه‌متروک). جزئیات: `10_old_to_domain_mapping.md`.

## ۸) جدول‌های منبع اصلی داده (source of truth)

| دامنه | منبع اصلی |
| --- | --- |
| فروش ماهانه | `mahane` |
| صورت‌های مالی | `miandore2` |
| قیمت | `MarketPriceHistory` |
| P/E | `FullPE` (یا محاسبه‌ی view) |
| کاربران | `Users` |
| دارایی خانواده | `Family*` |
| registry کدال | `CodalReports` + `CodalSyncState` |
| universe | `TrackedTickers` |

## ۹) مهم‌ترین unknownها

- نویسنده/منبع `StockData`, `StockPrices`, `statements`.
- واحد واقعی همه‌ی مبالغ و قیمت‌ها.
- تفکیک دقیق per-share از مبلغی در داده‌ی خام.
- وابستگی‌های خارج از ریپو و اینکه آیا py2 در production است.
- وجود data drift بین نسخه‌ی ریپو و DB view.
- فهرست کامل در `11_unknowns.md`.

---

## Ready for Canonical PostgreSQL Design?

**نه کاملاً — هنوز چند تصمیم/داده لازم است.** اطلاعات برای طراحی *ساختار* کافی است، اما برای طراحی *درستِ* واحد، identity و valuation، سه شکاف باقی است:

### آنچه آماده است
- فهرست کامل جداول/ستون‌ها/روابط فیزیکی (`database_inventory/`).
- معنای ستون‌های `mahane` و `miandore2` و نگاشت دوره‌ها.
- شناخت کامل موتور امتیازدهی و کارهای جبرانی واحد.
- یک مدل هدف نرمال‌شده‌ی موجود (`py2`) به‌عنوان نقطه‌ی شروع.

### آنچه باید قبل از طراحی نهایی روشن شود
1. **واحد و مقیاس:** آیا منبع (کدال/BRS) واحد را می‌دهد؟ تصمیم بگیریم واحد را در ingestion استخراج و به یک واحد پایه (مثلاً ریال) نرمال کنیم یا نگه داریم. (blocker برای حذف workaroundها)
2. **Company identity:** انتخاب شناسه‌ی canonical (پیشنهاد: ISIN/TracingNo/Symbol) و ساخت جدول `companies` با `symbol`/`instrument_code` پر. (blocker برای حذف `md5(name)`)
3. **دامنه‌های قیمت و valuation:** تصمیم بگیریم `MarketPriceHistory` canonical است و `StockData` merge می‌شود؛ و `FullPE` به time-series تبدیل می‌شود یا نه.
4. **تاریخ‌ها:** انتخاب `date`/`timestamptz` و منطقه‌ی زمانی مرجع.
5. **داده‌ی واقعی:** اجرای چند query تجمیعی (بدون تغییر) برای پاسخ به unknownهای ۱–۷ (`11_unknowns.md`) — مثلاً پراکندگی واحد، پوشش timeline، و ناسازگاری CompanyID.
6. **دامنه‌ی py2:** آیا py2 خط لوله‌ی آینده است یا باید به‌عنوان مرجع مدل استفاده و در خط لوله‌ی Go ادغام شود.

با روشن شدن موارد ۱–۴، طراحی schema تمیز PostgreSQL (با FK واقعی، `numeric` برای پول، `date`/`timestamptz`، `jsonb`، و بدون workaroundهای واحد) قابل انجام است.
