# 06 — py2 Reuse Decision

> مقایسه‌ی `go-app/py2/` با یافته‌های جدید. هیچ schema/کدی ساخته یا تغییر نشده.
> وضعیت‌ها: **KEEP** | **EXTEND** | **REFACTOR** | **REPLACE**

## تصمیم به‌ازای component

| Component | تصمیم | دلیل |
| --- | --- | --- |
| `companies` | **EXTEND** | UUID PK مناسب است؛ اما باید `symbol`/`instrument_code` پر شود و ابعاد company/security جدا شود |
| `reports` | **KEEP** | نرمال، UNIQUE روی (company,type,period)، content-hash؛ الگوی درست |
| `report_versions` | **KEEP** | versioning گزارش‌های اصلاحی؛ دقیقاً چیزی که SQL Server ندارد |
| `monthly_activities` | **KEEP** (با اصلاح جزئی → **EXTEND**) | totals یک‌ماهه درست است؛ باید در صورت نیاز متریک/واحد بیشتر پوشش دهد |
| `financial_facts` | **EXTEND** | مدل generic metric درست است ولی فعلاً فقط ۵ متریک سود و زیان؛ باید `statement_type` و ترازنامه/جریان نقدی و خطوط کامل را پوشش دهد |
| | | |
| `collectors` | **REFACTOR** | وابسته به selectbox/Chromium محلی؛ نیاز به robustness، retry، observability |
| `parsers` | **KEEP** | منطق تشخیص ستون/ردیف/واحد (`detect_currency_unit`) خوب و قابل استفاده |
| `repository` | **KEEP** | upsertهای `on_conflict_do_update` + versioning |
| `Alembic setup` | **KEEP** | `0001_initial` هم‌خوان با models؛ نقطه‌ی شروع migration |
| `SQLAlchemy setup` | **KEEP** | Declarative 2.x، `JSONB`, `Numeric`, `DateTime(tz)` |
| `domain` | **KEEP** | normalize/`jalali_to_gregorian`/`to_decimal`/`content_hash` |

## پاسخ به سؤالات طراحی

### آیا UUID internal PK خوب است؟
**بله.** از وابستگی به نام/شناسه‌ی خارجی جلوگیری می‌کند و برای upsertهای idempotent مناسب است. باید در `companies` بماند.

### `companies.symbol` داخل companies باشد یا security جدا؟
- ساختار فعلی `symbol`+`instrument_code` را روی `companies` گذاشته ولی هرگز پر نمی‌کند.
- یافته‌ها نشان می‌دهد یک شرکت می‌تواند چند نماد/ابزار داشته باشد (`سیمرغ`/`سیمرغ3`, `جم پیلن`/`2`/`3`) و یک نماد می‌تواند به‌اشتباه دو شرکت داشته باشد (کسرا).
- → **جدا کردن `securities`/`instruments` توصیه می‌شود:** `company_id` (FK) + `symbol` + `instrument_code`(unic) + `security_type` + `is_active`. `companies.symbol` حذف/منتقل شود.

### `instrument_code` روی company یا security؟
روی **security/instrument**. چون یکتای بازار است (insCode) و می‌تواند در سطح ابزار (نماد پایه/حق تقدم) فرق کند.

### آیا `financial_facts` generic کافی است؟
**بله، ولی ناقص است.** الگوی `(report_id, period_order, metric_code, value, unit_code)` برای facts عمومی (سود و زیان، ترازنامه، جریان نقدی، تغییرات حقوق) کافی است. باید:
- `statement_type` اضافه شود (balance_sheet / cash_flow / income / comprehensive_income / equity_changes)،
- `row_title` (عنوان خط) و `metric_code` پایدار برای cross-report،
- `unit_code` واقعی (نه صرفاً rial_per_share)،
- نگاشت رسمی metric_code ↔ عنوان کدال.

### `monthly_activities` wide یا fact-based؟
**wide (فعلی) بماند.** گزارش فعالیت ماهانه مجموعه‌ی ثابتی از ستون‌هاست (تولید/فروش/مبلغ/داخلی/صادراتی) و wide خوانا و ساده است. تنها گسترش: متریک‌های اختیاری و ستون `quantity_unit`.

## شکاف‌های دامنه‌ای py2 (که باید اضافه شوند)
- قیمت بازار (MarketPriceHistory) — دامنه‌ی جدید.
- valuation/P-E (یا محاسبه‌ی derived).
- کاربران/auth/portfolio و Family*.
- registry کدال (`CodalReports`/`CodalSyncState`) و universe (`TrackedTickers`).
- metadata کیفیت داده برای جایگزینی `DataQualityScore` دستی.

## جمع‌بندی
py2 یک **پایه‌ی قابل استفاده‌ی مجدد** است (KEEP در اکثر لایه‌ها) که نیازمند **EXTEND** در مدل (company→security، financial_facts کامل) و **REFACTOR** در collectorهاست. هیچ بخشی نیازمند REPLACE کامل نیست جز افزودن دامنه‌های غایب.
