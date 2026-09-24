# 05 — DB View Drift (`vw_AIStockMetrics`)

> فقط snapshot و diff. هیچ view/DB تغییر نکرد. Snapshot تولید از DB در:
> `canonical_design_inputs/sql/vw_AIStockMetrics_production.sql`
> diff کامل normalized: `canonical_design_inputs/_view.diff`

## منابع مقایسه
- **Production (SQL Server فعلی):** export از `sys.sql_modules` → `sql/vw_AIStockMetrics_production.sql` (همان فایل `database_inventory/sql/views/dbo.vw_AIStockMetrics.sql`).
- **Repo (Git):** `go-app/sql/vw_AIStockMetrics.sql`.
- هر دو با `CREATE VIEW [dbo].[vw_AIStockMetrics]` شروع می‌شوند و header نسخه `v3.0` دارند.

## آمار diff (پس از حذف خطوط خالی)

| سنجه | مقدار |
| --- | --- |
| خطوط غیرخالی repo | 1,385 |
| خطوط غیرخالی production | 1,485 |
| شباهت (SequenceMatcher ratio) | **0.9373** |
| خطوط افزوده‌شده در production | **+140** |
| خطوط حذف/تغییرکرده از repo | **-40** |
| خطوط نشان‌دار `v3.7` در production | 12 (شامل `ScoreVersion = N'v3.7'`) |

→ **repo = v3.6، production = v3.7**. production کامل‌تر و جدیدتر است و باید منبع حقیقت باشد.

## تغییرات معنایی v3.7 (که در repo نیست)

1. **تفکیک «سود عملیاتی بی‌مقیاس» از «سود عملیاتی هم‌واحد»** (بخش هدر خطوط ~۲۰۱–۲۴۰ production):
   مشکل: `OpAbs` برای گزارش‌های per-share با ضریب `Product1` (= EPS × سرمایه، مقیاس ریال) نرمال می‌شد، نه با واحد مبلغی گزارش. نتیجه:
   - `InterestCoverage` ~۱۰۰۰ برابر بزرگ → از گارد ۱۰۰۰۰ رد می‌شد ولی در فاکتور با وزن ۳ رتبه‌ی نادرست می‌داد.
   - `NonOperatingPct` با مخرج ~۱۰۰۰ برابر → ~۰٪ → بهترین رتبه‌ی کیفیت سود با وزن ۴.
   - `SR_TTMOperatingProfit` از `OpRaw` خام ساخته می‌شد → حاشیه‌ی ~۰٪.

2. **ستون‌های جدید `OpAmt` / `OpLYAmt` / `OpFYPrevAmt`** (CTE `ProfitUnits` + `ProfitClean`، خطوط ~۴۷۳–۶۸۲):
   ضریب `OpK = NetProfitAmount / EPS` (تعداد سهم ÷ ضریب واحد) برای گزارش‌های per-share؛ و `OpAmt = OpRaw × OpK` (هم‌واحد با `RevenueNew`/`FinanceCostsNew`/`OtherNonOpNew`/`NetProfitAmount`) با گارد «حداکثر ۳× درآمد» وگرنه NULL.
   `OpAbs` دست‌نخورده و فقط برای نسبت‌های بی‌مقیاس (رشد) باقی ماند.

3. **`SR_TTM*` (“sustainable” / هم‌واحد)** برای حاشیه‌ها/ROE/CashConversion از `OpRaw×OpK` به‌جای `OpRaw` خام.

4. **لایه‌ی دوم هم‌واحد برای `OperatingMargin12M`/`NetProfitMargin12M`** (خطوط ~۱۸۳۹–۱۸۹۰) بر پایه‌ی دوره‌ی تجمعی گزارش آخر، برای شرکت‌های بدون ستون سال مالی قبل (جای رتبه‌ی خنثای ۰.۳).

5. **نمایش `LatestEPS`/`LatestOperatingEPS` بر پایه‌ی مقدار هم‌واحد مبلغی** و `LatestOpAmt` (خطوط ~۱۴۳۱، ۱۹۲۰–۲۰۴۳، ۲۸۲۷).

6. **`ScoreVersion = N'v3.7'`** در خروجی (خط ~۳۲۶۳).

## نتیجه/ریسک
- **ریسک drift:** هر تغییر در DB از repo جدا می‌شود؛ نسخه‌بندی view در DB است نه Git.
- **اقدام پیشنهادی (خارج از این مرحله):** repo را به v3.7 به‌روزرسانی و از این پس view را versioned + migration-managed نگه دارید. تا آن زمان، snapshot فعلی در `sql/` منبع طراحی است.
