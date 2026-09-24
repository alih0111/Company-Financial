# 08 — تجزیه‌ی کامل `vw_AIStockMetrics`

> منابع: نسخه‌ی نصب‌شده در SQL Server (`database_inventory/sql/views/dbo.vw_AIStockMetrics.sql`, ~۳۳۳۰ خط) و فایل ریپو (`go-app/sql/vw_AIStockMetrics.sql`).
> **نکته‌ی مهم drift:** نسخه‌ی DB تا **v3.7** است (شامل بلوک «سود عملیاتی پایدار» و `OpAmt`)، اما فایل ریپو فقط تا **v3.6** است. پس فایل ریپو با DB هم‌گام نیست.
> هیچ چیزی تغییر داده نشده است.

## ساختار کلی (CTEها)

`CompanyList` → `MonthlySales` → `ProfitRaw`/`ProfitDedup` → `ProfitUnits` → `ProfitClean` → `ProfitLatest` → `Market` → `Metrics` → `Ranked` → خروجی.

### 1) Company universe
- `CompanyList`: `SELECT DISTINCT CompanyID, CompanyName FROM dbo.mahane WHERE CompanyID IS NOT NULL`.
- یعنی **universe از داده‌ی ماهانه ساخته می‌شود**، نه از یک جدول شرکت‌ها. هر شرکت بدون گزارش ماهانه در view غایب است.
- Input: `mahane.CompanyID, CompanyName`.

### 2) Monthly sales normalization (منبع `mahane`)
- `TRY_CONVERT(FLOAT, Value3) AS SalesAmount` از `dbo.mahane`.
- فیلترها: `CompanyID IS NOT NULL` و `Value3 IS NOT NULL`.
- `Value3` = مبلغ فروش/درآمد یک‌ماهه (به‌صورت ماهانه، نه تجمعی — طبق `MianSql2`).
- محاسبات: `SalesLast12M`, `SalesPrev12M`، رشد ۱۲ ماهه و ۳ ماهه از تجمیع ماه‌ها.
- Assumption: هر رکورد `mahane` یک ماه است؛ واحد آن (`U`) نامعلوم فرض می‌شود.
- Output: `SalesGrowth12M`, `SalesGrowth3M`, `SalesStability`, `SalesLast12M`.

### 3) Financial normalization (منبع `miandore2`)
- `ProfitRaw`/`ProfitDedup`: یک ردیف به‌ازای (شرکت، سال، ماه) با dedup روی جدیدترین گزارش.
- ستون‌های خوانده‌شده: `Num1_Value1 AS EPS`, `Product1 AS NetProfit`, `RevenueNew AS Revenue`, `NetProfitAmount/LY/FYPrev`, `OperatingProfitNew`, `FinanceCostsNew`, `OtherNonOpNew`, `OperatingCashFlow*`, `TotalAssets/CurrentAssets/TotalLiabilities/CurrentLiabilities/TotalEquity` (+ LY).
- `JYear = fn_JalaliKey(ReportDate)/10000`، `JMonth = (fn_JalaliKey(ReportDate)%10000)/100`.
- Assumption: `Product1` به‌عنوان «سود» در نظر گرفته می‌شود، ولی مقیاسش مخلوط است (به بخش unit fixes رجوع شود).

### 4) Unit fixes (v3.2/v3.3/v3.7) — پیچیده‌ترین بخش
- **`OpK` (ProfitUnits):** تشخیص per-share بودن `OpRaw`:
  - اگر `NetProfitAmount` موجود و `ABS(OpRaw) < 0.001*ABS(NetProfitAmount)` و (اختیاری) `< 0.001*ABS(Revenue)` → `OpK = NetProfitAmount / EPS`.
  - اگر `OpRaw` per-share است ولی `NetProfitAmount` نیست → `OpK = NULL` (NULL بهتر از عدد غلط).
  - وگرنه `OpK = 1.0`.
- **`OpAbs`:** `OpRaw` که اگر per-share بود با `NetProfit/EPS` مقیاس‌دهی می‌شود (فقط برای نسبت‌های بی‌مقیاس مثل رشد).
- **`OpAmt` (v3.7):** `OpRaw * OpK` → **هم‌واحد با Revenue/FinanceCosts/OtherNonOp/NetProfitAmount**؛ با گارد «حداکثر ۳ برابر درآمد» وگرنه NULL. فقط `OpAmt` مجاز است در نسبت با ستون‌های مبلغی ترکیب شود.
- **`NPUnitRatio`:** توان-۱۰ بین `NetProfitAmount` و `Product1`/`NetProfitCum` با `LOG10` و `ROUND` (اگر اختلاف < 0.1 مرتبه).

### 5) TTM calculations
- `TTMNetProfit`: اگر ماه گزارش = ۱۲ → `LatestNetProfitAmount`؛ وگرنه `LatestNetProfitAmount + LatestNetProfitAmountFYPrev - LatestNetProfitAmountLY` (تجمعی از ابتدای سال).
- `TTMNetProfitPrev`, `TTMNetProfitP1` (fallback از `Product1`).
- `TTMOperatingProfit`, `TTMRevenue`, `TTMOperatingCashFlow` با همان منطق.
- نسخه‌های `SR_TTM*` (v3.7: «سود عملیاتی پایدار/گزارش‌شده») برای تفکیک منبع per-share از مبلغی.

### 6) Growth metrics
- `NetProfitGrowthTTM` / `OperatingProfitGrowthTTM` با `NPUnitRatio` و fallbackها.
- محدودسازی (clamp): `NetProfitGrowthTTM` در `[-300, 300]`، `OperatingProfitGrowthTTM` در `[-250, 250]`، و خروجی نهایی در `[-100, 1000]`.
- `RevenueGrowth` از TTMRevenue/`SalesLast12M`.

### 7) Profitability metrics
- `OperatingMargin`, `NetMargin` با گارد `ABS(ratio) <= 200%`.
- `InterestCoverage`, `NonOperatingPct` (v3.7 از `OpAmt` هم‌واحد).
- `ROE = TTMNetProfit / LatestTotalEquity` با گارد `<= 300%`.
- `CashConversion = SR_TTMOperatingCashFlow / SR_TTMNetProfit` در بازه `[-2, 5]`.
- `OperatingMargin12M`, `NetProfitMargin12M` (fallback تجمعی).

### 8) Valuation metrics
- `TTMEPS = SR_TTMNetProfit × LatestEPSReport / LatestNetProfitAmount` (یا fallback با `NetProfitCum`).
- `PEApprox = LatestPrice / TTMEPS`.
- `PSRatio = PEApprox × (NetProfitMargin12M/100)` (یا از ROE) — «چون P/S = P/E × حاشیه سود خالص».
- `PBRatio = PEApprox × ROE/100` با گارد `<= 30`.

### 9) Market metrics (منبع `MarketPriceHistory`)
- `LatestPrice = MAX(CASE WHEN rn=1 THEN COALESCE(LastPrice, ClosingPrice))`.
- `PriceReturn7D/30D/90D`, `AvgTradeValue30D`, `AvgVolume30D`, `Volatility30D`, `PricePosition90D`.
- `LatestMarketDate`, و تازگی قیمت برای DataQuality.

### 10) Data quality (`DataQualityScore`)
- ترکیب امتیاز تازگی گزارش سود (بر اساس فاصله‌ی ماه گزارش تا «الان»: `<=5` ماه → 0.08، `<=8` ماه → 0.045) و تازگی قیمت (`<=7` روز → 0.06، `<=14` روز → 0.035).
- محاسبه‌ی «الان» با `GETDATE()` و تبدیل تقریبی میلادی→شمسی با `MONTH(GETDATE()) < 3` و offset 621/622 (heuristic).

### 11) Penalties (v3.2)
- `GrowthPenalty`: جریمه برای رشد فروش/سود منفی/کم (مثلاً `OperatingProfitGrowthTTM < -25` → ۵ امتیاز).
- `ProfitabilityPenalty`: `TTMNetProfit < 0` → ۱۰ امتیاز، و شرط‌های دیگر.
- `ValuationPenalty`, `MarketPenalty` (MarketPenalty فعلاً 0.0 و به DataQualityScore منتقل شده).

### 12) Percentile / Ranking
- رتبه‌ی درصدی هر فاکتور بین کل بازار با شبیه‌سازی `midrank` (شامل handle کردن tie و NULL). رتبه‌ها در بازه‌ی ۰..۱.
- مقدار NULL/ناموجود → رتبه‌ی خنثای حدود `0.3` (یا 0.5 در برخی فاکتورها) طبق کامنت‌ها.

### 13) Factor weights (از بلوک QuantScore نصب‌شده)

| دسته | فاکتورها | وزن‌ها |
| --- | --- | --- |
| **Growth** (مجموع ۳۶) | SalesGrowth, SalesGrowth3M, RevenueGrowth, OperatingProfitGrowth, NetProfitGrowth | 10 + 6 + 5 + 5 + 10 |
| **Profitability** (مجموع ۲۶) | OperatingMargin, NetMargin, ROE, MarginTrend, InterestCoverage, CashConversion, EarningsQuality | 4 + 4 + 6 + 3 + 3 + 2 + 4 |
| **Valuation** (مجموع ۱۶) | PE, PS, PB | 11 + 3 + 2 |
| **Market** (مجموع ۱۱) | Liquidity, Leverage, CurrentRatio, Stability, LowVolatility, Momentum | 3 + 2 + 2 + 1 + 2 + 1 |

### 14) QuantScore
```
QuantScore = DataQualityScore × (GrowthScore + ProfitabilityScore + ValuationScore + MarketScore)
```
- هر دسته پس از کسر penalty، حداقل ۰ می‌شود.
- خروجی `ROUND(..., 2)`.
- `DataQualityScore` ضریب کلی است (کمترین تازگی → کمترین امتیاز).

## Schema-related workarounds

| بخش پیچیده‌ی view | چرا ساخته شده | در مدل جدید قابل حذف؟ |
| --- | --- | --- |
| `OpK` / `OpAbs` / `OpAmt` / `SR_TTM*` | «سود عملیاتی» گاهی per-share و گاهی مبلغی است؛ هیچ ستون واحدی وجود ندارد | **بله** اگر ingestion واحد و ماهیت per-share را کد کند |
| `NPUnitRatio` | `Product1 = EPS × سرمایه` مقیاس مخلوط دارد | **بله** اگر سود خالص مبلغی و EPS جدا و واحددار ذخیره شوند |
| `TTMEPS` (ضرب/تقسیم دستی) | نبود EPS با مقیاس مبلغی و اختلاف واحد | **بله** با نگه‌داشتن EPS TTM و NetProfit جدا با واحد |
| `DataQualityScore` با `GETDATE()` و offset تقویمی دستی | `ReportDate` رشته‌ی شمسی است و ستون تاریخ میلادی وجود ندارد | **بله** با ستون `date`/`period_end_date` و محاسبه‌ی فاصله‌ی واقعی |
| `JYear/JMonth` با `fn_JalaliKey` روی هر ردیف | تاریخ شمسی به‌صورت string ذخیره شده | **بله** با ستون‌های `__year/__month` یا `date` |
| رتبه‌بندی midrank دستی | SQL Server آن زمان تابع رتبه‌بندی دلخواه با tie/null نداشت | تا حدی (Postgres `percent_rank`/`cume_dist`) |
| نگه‌داری سه نسخه‌ی view | تکامل نسخه‌ها روی DB (v1/v2/v3) | **بله** با یک مدل واحد و versioned |
| `DataQualityScore` جایگزین MarketPenalty | فیلدهای تازگی در سطح داده نبود | **بله** با metadata تازگی در ingestion |

## `UNKNOWN`ها
- مقادیر دقیق آستانه‌های برخی penaltyها بدون خواندن کامل توابع درون view.
- کدام fallback در داده‌ی واقعی فعال است (`SR_*` یا عادی) به ترکیب داده بستگی دارد.
