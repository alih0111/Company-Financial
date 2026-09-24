# Validation Plan — SQL Server vs PostgreSQL v1

> Design artifact. هیچ مقایسه‌ای در این مرحله اجرا نشده است. این سند روش و toleranceها را تعریف می‌کند.

## اصول
- ابتدا **۲۰ شرکت نمونه** از صنایع مختلف، سپس **کل universe**.
- مقایسه‌ی systematic و تکرارپذیر (اسکریپت شماره‌گذاری‌شده، خروجی CSV/JSON).
- هر اختلاف با `severity` و علت ثبت شود (نه صرفاً عدد).
- معیار پذیرش: هیچ اختلاف **HIGH** حل‌نشده نماند.

## نمونه‌ی ۲۰ شرکت (شامل صنایع مختلف)
پیشنهاد: `فولاد, خودرو, شپنا, همراه, فملی, وبملت, تاپیکو, کگل, شبندر, اخابر, شیراز, خراسان, ارفع, آردینه, بترانس, بجهرم, کالا, اسیاتک, تپسی, کپرور` (برخی محصولی، برخی خدماتی، برخی هلدینگ).

## سنجه‌های مقایسه

| # | سنجه | SQL Server | PostgreSQL v1 | نوع مقایسه |
| --- | --- | --- | --- | --- |
| 1 | row counts هر جدول | count per table | count per mapped table | exact (با توضیح اختلاف legacy skip) |
| 2 | latest report | max(ReportDate) per company | max(period_end_date) per company | exact date |
| 3 | monthly sales | `mahane.Value3` last 12 | `sales_amount_rial` last 12 | relative tolerance |
| 4 | EPS | `Num1_Value1` | `eps` fact | relative tolerance |
| 5 | revenue | `RevenueNew` | `revenue` fact (rial) | relative tolerance |
| 6 | net profit | `NetProfitAmount` | `net_profit` fact | relative tolerance |
| 7 | operating profit | `OperatingProfitNew` | `operating_profit` fact | relative tolerance |
| 8 | assets | `TotalAssets` | `total_assets` | relative tolerance |
| 9 | equity | `TotalEquity` | `total_equity` | relative tolerance |
| 10 | cash flow | `OperatingCashFlow` | `operating_cash_flow` | relative tolerance |
| 11 | price history | MPH by Symbol/date | daily_prices by security/date | exact count + sample values |
| 12 | TTM | v3.7 value | analytics metric_snapshot | relative tolerance |
| 13 | P/E | v3.7 PEApprox | analytics | relative tolerance (علت اختلاف ثبت شود) |
| 14 | QuantScore | v3.7 | analytics.company_scores | tolerance (نه bit-for-bit) |

## Tolerance دقیق

- **Monetary facts** پس از تبدیل `million_rial → rial`:
  - مقدار مرجع ریالی = `legacy × 1,000,000`.
  - اختلاف مجاز: `abs(pg − ref) <= 1` ریال (error گردکردن numeric) **یا** `<= 1e-6 relative`، هرکدام بزرگ‌تر.
  - اگر legacy مقدار اعشاری داشته، `1e-4 relative` هم پذیرفته است.
- **EPS (`rial_per_share`)**: `abs diff <= 0.01` یا `1e-6 relative`.
- **روز/تاریخ**: تساوی کامل `date` (بدون اختلاف).
- **قیمت‌ها**: تساوی کامل (integer rial در legacy → numeric در pg).
- **TTM / margins**: `1e-4 relative`.
- **P/E**: `1e-3 relative`؛ اگر منبع P/E متفاوت باشد (vendor vs محاسبه‌شده) اختلاف با علت گزارش می‌شود، نه به‌عنوان failure.
- **QuantScore**: `abs diff <= 0.5` نمره (۰..۱۰۰)؛ **bit-for-bit انتظار نداریم** چون:
  - rounding/ORDER BY متفاوت،
  - نسخه‌ی داده (snapshot زمان) متفاوت،
  - حذف heuristicهای واحد ممکن است لبه‌ها را کمی جابه‌جا کند.
  هر اختلاف > 0.5 باید با breakdown فاکتورها (percentile/weight) توضیح داده شود.

## روش اجرا (مرحله‌ی آینده)
1. اسکریپت extract از SQL Server → `ref/*.csv` (فقط SELECT).
2. اسکریپت extract از PostgreSQL → `pg/*.csv`.
3. join روی `company`/`security`/`date`/`metric` و محاسبه‌ی diff + tolerance.
4. خروجی: `validation_report.csv` (per metric) + `validation_summary.json` (counts by severity).
5. اختلاف‌ها در `ingestion.data_quality_issues` به‌عنوان `issue_code='other'`/`'stale_data'`/`'identity_conflict'` ثبت شوند.

## معیارهای پذیرش (Definition of Done)
- همه‌ی row counts توجیه‌شده (اختلاف فقط برای legacy skip).
- هیچ اختلاف HIGH در monetary/date/price.
- TTM/P-E/QuantScore در tolerance یا با علت مستند.
- ۱۰۰٪ شرکت‌های نمونه و ≥۹۹٪ universe در محدوده‌ی tolerance.

### Units (اصلاح item 16)
- **monetary unit = `unknown`** → **failure (HIGH)**؛ باید resolve یا در DQ ثبت شود.
- **quantity_unit = `unknown`/NULL** → **accepted limitation**، نه failure؛ هیچ واحدی حدس زده نمی‌شود.
- هیچ رکوردی نباید با تبدیل واحد حدسی وارد شود.
