USE [codal]
GO

/****** Object:  View [dbo].[vw_AIStockMetrics]    Script Date: 7/24/2026 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO


IF OBJECT_ID(N'dbo.vw_AIStockMetrics', N'V') IS NOT NULL
    DROP VIEW dbo.vw_AIStockMetrics
GO


CREATE VIEW [dbo].[vw_AIStockMetrics]
AS
-- ============================================================================
--  vw_AIStockMetrics  (v3.0)
--  رتبه‌بندی کمّی شرکت‌های بورسی بر اساس داده‌های ماهانه (فروش) و گزارش‌های
--  میان‌دوره‌ی صورت سود و زیان. خروجی اصلی: QuantScore بین 0..100.
--
--  اصلاحات بنیادی نسخه‌ی v3 نسبت به v2:
--
--  ۱) سود و درآمد گزارش‌های میان‌دوره «تجمعی از ابتدای سال مالی» است، نه فصلی.
--     جمع ساده‌ی ۴ گزارش اخیر (روش v2) عملاً ~۲ سال سود را جمع می‌زد و
--     رشد سود و حاشیه‌های ۱۲ماهه را خراب می‌کرد. در v3 سود ۱۲ماهه‌ی واقعی
--     (TTM) به این شکل ساخته می‌شود:
--         TTM = سود تجمعی جدیدترین گزارش + س کل سال قبل - سود تجمعی دوره‌ی
--               مشابه سال قبل
--     و رشد TTM از نسبت TTM امسال به TTM سال قبل محاسبه می‌شود.
--
--  ۲) P/E با EPS تجمعیِ گزارش آخر ساخته می‌شد که برای گزارش ۳ماهه حدوداً
--     ۴ برابر P/E واقعی می‌داد. اکنون EPS دوازده‌ماهه (TTM EPS) محاسبه و
--     P/E = قیمت / EPS_TTM است (با جدول FullPE اعتبارسنجی شد؛ میانه‌ی
--     اختلاف ~۱.۱ برابر که عمدتاً از اختلاف تاریخ قیمت است).
--
--  ۳) P/S قبلاً با «تعداد سهم» ضربدر قیمت ساخته می‌شد که واحد سهم‌ها با
--     واحد فروش سازگار نبود و برای ۱۰۰٪ شرکت‌ها مقداری ≥ ۱۰۰ (بی‌معنی)
--     می‌داد. اکنون از هم‌ارزی بدون واحد استفاده می‌شود:
--         P/S = P/E × (سود خالص / فروش)
--
--  ۴) باگ رتبه‌ی «پوشش بهره» اصلاح شد: قبلاً پوشش بالای ۱۰۰ به‌عنوان
--     «بدترین» رتبه‌بندی می‌شد (وارونگی). اکنون پوشش بالا تا سقف ۲۰×
--     بهترین رتبه را می‌گیرد.
--
--  ۵) واحد ستون OperatingProfitNew در داده‌ها مخلوط است (اکثر ردیف‌ها
--     per-share، بعضی مطلق). با نسبت سطر-به-سطر (سود/تعداد سهم ضمنی)
--     یکسان‌سازی می‌شود.
--
--  ۶) مومنتوم قیمت: قبلاً بازده بالای ۳۵٪ «بدترین» رتبه را می‌گرفت.
--     اکنون بازده ۳۰روزه در بازه‌ی [-50, +40] کراپ می‌شود.
--
--  ۷) کهنگی داده (Staleness) وارد امتیاز شد: کیفیت داده بONUS تازگی گزارش
--     سود/قیمت دارد و داده‌ی کهنه جریمه‌ی امتیازی می‌گیرد.
--
--  ۸) جریمه‌ها از ضریب ضربی به «امتیاز کسرِی شفاف در هر دسته» تبدیل شدند و
--     مجموع زیر‌امتیازها × کیفیت داده دقیقاً برابر QuantScore است:
--         QuantScore = DataQualityScore × (Growth + Profitability + Valuation + Market)
--
--  ۹) فاکتورهای بدونِ داده‌ی ساختاری (مثل فروش ماهانه برای بانک‌ها) به جای
--     بدترین رتبه، رتبه‌ی خنثی (۰.۳) می‌گیرند؛ مقادیر «نامعتبرِ واقعی»
--     (مثل P/E منفی) همچنان بدترین رتبه + جریمه دارند.
--
--  اصلاح v3.3 — باگ ناسازگاری واحد در رشد سود خالص:
--     TTM گزارش آخر (ستون‌های مبلغی v3.2) با TTM سال قبل (ستون Product1)
--     مستقیماً مقایسه می‌شد؛ این دو ستون در برخی شرکت‌ها ۱۰۰۰ برابر اختلاف
--     واحد دارند و رشدهای کاذب ~−۱۰۰٪ تولید می‌کرد. اکنون:
--       ۱) ضریب واحد NPUnitRatio (توان صحیح ۱۰، از لنگرهای هم‌کمیت دو منبع)
--          محاسبه و TTM سال قبل هم‌واحد می‌شود؛
--       ۲) اگر لنگر معتبر نباشد، هر دو طرف از Product1 ساخته می‌شوند
--          (TTMNetProfitP1 در برابر TTMNetProfitPrev).
--     همچنین (v3.3): NetMarginLatest اولویتاً از NetProfitAmount (هم‌واحد با
--     RevenueNew) ساخته می‌شود و OperatingMarginLatest/Trend گارد ±۲۰۰٪ گرفتند،
--     چون Product1 (ریال) و RevenueNew/mahane (هزار ریال) هم‌خانواده‌ی واحد نیستند.
--
--  اصلاح v3.4 — بازتنظیم وزن‌ها بر اساس بک‌تست ۶۱ماهه (۱۳۹۹/۰۱-۱۴۰۴/۱۲،
--     point-in-time با تأخیر ۴۵ روزه انتشار، py/backtest.py + backtest_weights.py):
--       • IC فاکتورها: رشد فروش۱۲م 0.127(t=7.4) | رشد فروش۳م 0.117(t=8.1) |
--         رشد خالص 0.109(t=4.9) | P/Eوارونه −0.090(t=−5.4) | نوسان‌کم |
--         رشد عملیاتی ضعیف 0.045 | مومنتوم بی‌معنا t=1.8 | ثبات فروش IC≈0
--       • تغییرات: فروش۱۲م 9→10، فروش۳م 4→6، عملیاتی 8→5، P/E 10→11،
--         ثبات فروش 3→1، نوسان‌کم 3→5، مومنتوم 3→1
--       • جریمه‌ی کهنگی داده از دسته‌ی بازار حذف شد (دوگانه با ضریب DQ؛
--         پرچم StaleDataFlag برای شفافیت باقی است)
--       • اعتبارسنجی: درون‌نمونه ۹۹-۰۲ IC: 0.108→0.129 | برون‌نمونه ۰۳-۰۴
--         IC: 0.214→0.219 و پرتفوی بدون افت | کل دوره Top20-۶ماهه:
--         اضافه‌بازده 5.0→5.8٪/ماه، نرخ برد 74→85٪
--
--  اصلاح v3.5 — بازتنظیم وزن فاکتورهای v3.2 بر اساس بک‌تست فاز ۲
--     (py/backtest_phase2.py؛ ۱۰ نمادِ بک‌فیل‌شده کامل، ۶۱ ماه):
--       • IC فاکتورها: ROE +0.156(t=2.6) | حاشیه خالص۱۲م +0.138(t=2.3) قوی؛
--         کیفیت نقدی +0.051، اهرم +0.021، نسبت جاری −0.063، P/B +0.043 نوفه
--       • تغییرات: ROE 5→6، حاشیه خالص 3→4، کیفیت نقدی 4→2، اهرم 4→2،
--         نسبت جاری 3→2، P/B 3→2
--       • نتیجه‌ی پرتفوی (Top-5 در برابر میانگین ۱۰ نماد): مجموع ۳ماهه
--         510→765٪ (بنچمارک 446٪) | ۶ماهه 261→459٪ (بنچمارک 343٪)
--       • محدودیت: مقطع فقط ۱۰ نماد — وزن‌ها محافظه‌کارانه (نه صفر) تعدیل
--         شدند؛ بعد از بک‌فیل نمادهای بیشتر بازبینی مجدد شود
-- ============================================================================

WITH CompanyList AS (
    SELECT CompanyID, MAX(CompanyName) AS CompanyName
    FROM (
        SELECT CompanyID, CompanyName FROM dbo.mahane WHERE CompanyID IS NOT NULL
        UNION ALL
        SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyID IS NOT NULL
    ) x
    GROUP BY CompanyID
),

-- ---------------------------------------------------------------------------
--  فروش ماهانه (مقادیر هر ماه، غیرتجمعی — با نمونه‌ها صحت‌سنجی شد)
-- ---------------------------------------------------------------------------
MonthlyRaw AS (
    SELECT
        CompanyID,
        MAX(CompanyName) AS CompanyName,
        ReportDate,
        dbo.fn_JalaliKey(ReportDate) AS ReportKey,
        TRY_CONVERT(FLOAT, Value3) AS SalesAmount
    FROM dbo.mahane
    WHERE CompanyID IS NOT NULL
      AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
      AND TRY_CONVERT(FLOAT, Value3) IS NOT NULL
    GROUP BY
        CompanyID,
        ReportDate,
        Value3
),

MonthlyRanked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY CompanyID
            ORDER BY ReportKey DESC
        ) AS rn
    FROM MonthlyRaw
),

SalesAgg AS (
    SELECT
        CompanyID,

        MAX(CASE WHEN rn = 1 THEN CompanyName END) AS CompanyName,
        MAX(CASE WHEN rn = 1 THEN ReportDate END) AS LatestSalesReportDate,
        MAX(CASE WHEN rn = 1 THEN ReportKey END) AS LatestSalesReportKey,

        COUNT(*) AS SalesReportCount,

        SUM(CASE WHEN rn BETWEEN 1 AND 12 THEN SalesAmount ELSE 0 END) AS SalesLast12M,
        SUM(CASE WHEN rn BETWEEN 13 AND 24 THEN SalesAmount ELSE 0 END) AS SalesPrev12M,

        SUM(CASE WHEN rn BETWEEN 1 AND 3 THEN SalesAmount ELSE 0 END) AS SalesLast3M,
        SUM(CASE WHEN rn BETWEEN 4 AND 6 THEN SalesAmount ELSE 0 END) AS SalesPrev3M,

        AVG(CASE WHEN rn BETWEEN 1 AND 12 THEN SalesAmount END) AS SalesAvg12M,
        STDEV(CASE WHEN rn BETWEEN 1 AND 12 THEN SalesAmount END) AS SalesStd12M
    FROM MonthlyRanked
    GROUP BY CompanyID
),

-- ---------------------------------------------------------------------------
--  داده‌ی صورت سود و زیان:
--   - حذف ردیف‌های تکراریِ (شرکت، سال، ماه) با نگه‌داشتن آخرین گزارش
--   - یکسان‌سازی واحد سود عملیاتی (per-share → مطلق با نسبت سود/EPS سطر)
--   - ساخت TTM با اتصال گزارش‌های (سال-۱، ماه) و (سال-۱، ۱۲) و (سال-۲، ...)
-- ---------------------------------------------------------------------------
ProfitRaw AS (
    SELECT
        CompanyID,
        CompanyName,
        ReportDate,
        dbo.fn_JalaliKey(ReportDate) AS ReportKey,
        dbo.fn_JalaliKey(ReportDate) / 10000 AS JYear,
        (dbo.fn_JalaliKey(ReportDate) % 10000) / 100 AS JMonth,

        TRY_CONVERT(FLOAT, Num1_Value1) AS EPS,
        TRY_CONVERT(FLOAT, Product1) AS NetProfit,
        TRY_CONVERT(FLOAT, OperatingProfitNew) AS OpRaw,
        TRY_CONVERT(FLOAT, OperatingProfitLastYear) AS OpLYRaw,
        TRY_CONVERT(FLOAT, RevenueNew) AS Revenue,
        TRY_CONVERT(FLOAT, RevenueLastYear) AS RevenueLY,
        TRY_CONVERT(FLOAT, FinanceCostsNew) AS FinanceCosts,
        TRY_CONVERT(FLOAT, OtherNonOpNew) AS OtherNonOp,

        -- مقادیر واقعی جدول (هم‌واحد، معمولاً میلیون ریال) — v3.2
        TRY_CONVERT(FLOAT, NetProfitAmount) AS NetProfitAmount,
        TRY_CONVERT(FLOAT, NetProfitAmountLY) AS NetProfitAmountLY,
        TRY_CONVERT(FLOAT, NetProfitAmountFYPrev) AS NetProfitAmountFYPrev,
        TRY_CONVERT(FLOAT, OperatingProfitFYPrev) AS OperatingProfitFYPrev,
        TRY_CONVERT(FLOAT, RevenueFYPrev) AS RevenueFYPrev,
        TRY_CONVERT(FLOAT, OperatingCashFlow) AS OperatingCashFlow,
        TRY_CONVERT(FLOAT, OperatingCashFlowLY) AS OperatingCashFlowLY,
        TRY_CONVERT(FLOAT, OperatingCashFlowFYPrev) AS OperatingCashFlowFYPrev,

        TRY_CONVERT(FLOAT, TotalAssets) AS TotalAssets,
        TRY_CONVERT(FLOAT, CurrentAssets) AS CurrentAssets,
        TRY_CONVERT(FLOAT, TotalLiabilities) AS TotalLiabilities,
        TRY_CONVERT(FLOAT, CurrentLiabilities) AS CurrentLiabilities,
        TRY_CONVERT(FLOAT, TotalEquity) AS TotalEquity
    FROM dbo.miandore2
    WHERE CompanyID IS NOT NULL
      AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
),

ProfitDedup AS (
    SELECT
        p.*,
        ROW_NUMBER() OVER (PARTITION BY CompanyID, JYear, JMonth ORDER BY ReportKey DESC) AS drn,
        ROW_NUMBER() OVER (PARTITION BY CompanyID ORDER BY ReportKey DESC) AS rn
    FROM ProfitRaw p
),

-- یک ردیف به‌ازای (شرکت، سال، ماه) با واحد یکسان
-- تشخیص واحد سود عملیاتی (مطلق یا per-share) به این ترتیب:
--   ۱) اگر درآمدِ همان سطر موجود باشد: هرگاه سود عملیاتی به‌مراتب کوچک‌تر از
--      درآمد باشد per-share است (با سهم ضمنی = سود/EPS به مطلق برمی‌گردد)
--   ۲) در غیر این صورت معیار EPS: مقدار در مقیاس EPS (بین ۰.۰۵×EPS و ۱۰۰×EPS)
--      و به‌مراتب کوچک‌تر از سود خالصِ مطلق → per-share
--      (شرط حداقل ۰.۰۵×EPS مقادیر placeholder مثل 1.0 را دور می‌ریزد)
ProfitClean AS (
    SELECT
        CompanyID, CompanyName, ReportDate, ReportKey, JYear, JMonth, drn, rn,
        EPS, NetProfit, Revenue, RevenueLY, FinanceCosts, OtherNonOp,
        OpRaw, OpLYRaw,
        NetProfitAmount, NetProfitAmountLY, NetProfitAmountFYPrev,
        OperatingProfitFYPrev, RevenueFYPrev,
        OperatingCashFlow, OperatingCashFlowLY, OperatingCashFlowFYPrev,
        TotalAssets, CurrentAssets, TotalLiabilities, CurrentLiabilities, TotalEquity,

        CASE
            WHEN OpRaw IS NULL THEN NULL
            WHEN Revenue IS NOT NULL AND ABS(Revenue) > 0 THEN
                CASE
                    WHEN ABS(OpRaw) < 0.001 * ABS(Revenue) AND EPS > 0 AND NetProfit > 0
                        THEN OpRaw * NetProfit / EPS
                    ELSE OpRaw
                END
            WHEN EPS > 0 AND NetProfit > 0
                 AND ABS(OpRaw) < 0.05 * NetProfit
                 AND ABS(OpRaw) < 100.0 * EPS
                 AND ABS(OpRaw) >= 0.05 * EPS
                THEN OpRaw * NetProfit / EPS
            ELSE OpRaw
        END AS OpAbs,

        CASE
            WHEN OpLYRaw IS NULL THEN NULL
            WHEN RevenueLY IS NOT NULL AND ABS(RevenueLY) > 0 THEN
                CASE
                    WHEN ABS(OpLYRaw) < 0.001 * ABS(RevenueLY) AND EPS > 0 AND NetProfit > 0
                        THEN OpLYRaw * NetProfit / EPS
                    ELSE OpLYRaw
                END
            WHEN EPS > 0 AND NetProfit > 0
                 AND ABS(OpLYRaw) < 0.05 * NetProfit
                 AND ABS(OpLYRaw) < 100.0 * EPS
                 AND ABS(OpLYRaw) >= 0.05 * EPS
                THEN OpLYRaw * NetProfit / EPS
            ELSE OpLYRaw
        END AS OpLYAbs
    FROM ProfitDedup
    WHERE drn = 1
),

-- اتصال آخرین گزارش به گزارش‌های سال قبل برای ساخت TTM
ProfitWide AS (
    SELECT
        a.CompanyID,
        a.CompanyName AS CompanyName_p,
        a.ReportDate AS LatestProfitReportDate,
        a.ReportKey AS LatestProfitReportKey,
        a.JYear AS LatestJYear,
        a.JMonth AS LatestJMonth,

        a.EPS AS LatestEPSReport,           -- EPS تجمعی گزارش آخر
        a.NetProfit AS LatestNetProfitCum,  -- سود خالص تجمعی گزارش آخر
        a.OpAbs AS LatestOpAbs,
        a.OpLYAbs AS LatestOpLYAbs,
        a.Revenue AS LatestRevenueCum,
        a.RevenueLY AS LatestRevenueLYCum,
        a.FinanceCosts AS LatestFinanceCosts,
        a.OtherNonOp AS LatestOtherNonOp,

        -- مقادیر هم‌واحد گزارش آخر — v3.2
        a.NetProfitAmount AS LatestNetProfitAmount,
        a.NetProfitAmountLY AS LatestNetProfitAmountLY,
        a.NetProfitAmountFYPrev AS LatestNetProfitAmountFYPrev,
        a.OperatingProfitFYPrev AS LatestOperatingProfitFYPrev,
        a.RevenueFYPrev AS LatestRevenueFYPrev,
        a.OperatingCashFlow AS LatestOperatingCashFlow,
        a.OperatingCashFlowLY AS LatestOperatingCashFlowLY,
        a.OperatingCashFlowFYPrev AS LatestOperatingCashFlowFYPrev,
        a.TotalAssets AS LatestTotalAssets,
        a.CurrentAssets AS LatestCurrentAssets,
        a.TotalLiabilities AS LatestTotalLiabilities,
        a.CurrentLiabilities AS LatestCurrentLiabilities,
        a.TotalEquity AS LatestTotalEquity,
        a.OpRaw AS LatestOpRaw,
        a.OpLYRaw AS LatestOpLYRaw,

        b.NetProfit AS FYPrevNetProfit,     -- س کل سال قبل
        b.OpAbs AS FYPrevOpAbs,
        b.Revenue AS FYPrevRevenue,

        c.NetProfit AS LYPNetProfit,        -- دوره‌ی مشابه سال قبل (تجمعی)
        c.OpAbs AS LYPOpAbs,
        c.Revenue AS LYPRevenue,

        d.NetProfit AS FYPrev2NetProfit,    -- س کل دو سال قبل
        d.OpAbs AS FYPrev2OpAbs,
        d.Revenue AS FYPrev2Revenue,

        e.NetProfit AS LYP2NetProfit,       -- دوره‌ی مشابه دو سال قبل
        e.OpAbs AS LYP2OpAbs,
        e.Revenue AS LYP2Revenue
    FROM ProfitClean a
    LEFT JOIN ProfitClean b
        ON b.CompanyID = a.CompanyID AND b.JYear = a.JYear - 1 AND b.JMonth = 12
    LEFT JOIN ProfitClean c
        ON c.CompanyID = a.CompanyID AND c.JYear = a.JYear - 1 AND c.JMonth = a.JMonth
    LEFT JOIN ProfitClean d
        ON d.CompanyID = a.CompanyID AND d.JYear = a.JYear - 2 AND d.JMonth = 12
    LEFT JOIN ProfitClean e
        ON e.CompanyID = a.CompanyID AND e.JYear = a.JYear - 2 AND e.JMonth = a.JMonth
    WHERE a.rn = 1
),

ProfitAgg AS (
    SELECT
        CompanyID,
        COUNT(*) AS ProfitReportCount
    FROM ProfitClean
    GROUP BY CompanyID
),

-- ---------------------------------------------------------------------------
--  داده‌ی بازار
-- ---------------------------------------------------------------------------
MarketRaw AS (
    SELECT
        CompanyID,
        CompanyName,
        Symbol,
        TRY_CONVERT(DATE, GregorianDate) AS GDate,
        TRY_CONVERT(FLOAT, ClosingPrice) AS ClosingPrice,
        TRY_CONVERT(FLOAT, LastPrice) AS LastPrice,
        TRY_CONVERT(FLOAT, HighPrice) AS HighPrice,
        TRY_CONVERT(FLOAT, LowPrice) AS LowPrice,
        TRY_CONVERT(FLOAT, TradeValue) AS TradeValue,
        TRY_CONVERT(FLOAT, Volume) AS Volume,
        TRY_CONVERT(FLOAT, TradeCount) AS TradeCount,
        TRY_CONVERT(FLOAT, ClosingChangePercent) AS ClosingChangePercent,
        CollectedAt
    FROM dbo.MarketPriceHistory
    WHERE CompanyID IS NOT NULL
      AND TRY_CONVERT(DATE, GregorianDate) IS NOT NULL
),

MarketRanked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY CompanyID
            ORDER BY GDate DESC, CollectedAt DESC
        ) AS rn
    FROM MarketRaw
),

MarketAgg AS (
    SELECT
        CompanyID,

        MAX(CASE WHEN rn = 1 THEN CompanyName END) AS CompanyName,
        MAX(CASE WHEN rn = 1 THEN Symbol END) AS Symbol,
        MAX(CASE WHEN rn = 1 THEN GDate END) AS LatestMarketDate,

        COUNT(*) AS MarketDaysCount,

        MAX(CASE WHEN rn = 1 THEN COALESCE(LastPrice, ClosingPrice) END) AS LatestPrice,
        MAX(CASE WHEN rn = 1 THEN ClosingPrice END) AS LatestClosingPrice,

        MAX(CASE WHEN rn = 7 THEN ClosingPrice END) AS ClosingPrice7D,
        MAX(CASE WHEN rn = 30 THEN ClosingPrice END) AS ClosingPrice30D,
        MAX(CASE WHEN rn = 90 THEN ClosingPrice END) AS ClosingPrice90D,

        AVG(CASE WHEN rn BETWEEN 1 AND 30 THEN TradeValue END) AS AvgTradeValue30D,
        AVG(CASE WHEN rn BETWEEN 1 AND 30 THEN Volume END) AS AvgVolume30D,
        AVG(CASE WHEN rn BETWEEN 1 AND 30 THEN TradeCount END) AS AvgTradeCount30D,

        STDEV(CASE WHEN rn BETWEEN 1 AND 30 THEN ClosingChangePercent END) AS Volatility30D,

        MAX(CASE WHEN rn BETWEEN 1 AND 90 THEN HighPrice END) AS HighPrice90D,
        MIN(CASE WHEN rn BETWEEN 1 AND 90 THEN LowPrice END) AS LowPrice90D
    FROM MarketRanked
    GROUP BY CompanyID
),

-- ---------------------------------------------------------------------------
--  معیارهای پایه
-- ---------------------------------------------------------------------------
BaseMetrics AS (
    SELECT
        c.CompanyID,
        COALESCE(m.Symbol, N'') AS Symbol,
        COALESCE(c.CompanyName, s.CompanyName, p.CompanyName_p, m.CompanyName) AS CompanyName,

        s.LatestSalesReportDate,
        p.LatestProfitReportDate,
        m.LatestMarketDate,

        ISNULL(s.SalesReportCount, 0) AS SalesReportCount,
        ISNULL(pa.ProfitReportCount, 0) AS ProfitReportCount,
        ISNULL(m.MarketDaysCount, 0) AS MarketDaysCount,

        s.SalesLast12M,
        s.SalesPrev12M,
        s.SalesLast3M,
        s.SalesPrev3M,

        CASE
            WHEN s.SalesPrev12M IS NOT NULL AND ABS(s.SalesPrev12M) > 0
                THEN ((s.SalesLast12M - s.SalesPrev12M) / ABS(s.SalesPrev12M)) * 100.0
            ELSE NULL
        END AS SalesGrowth12M,

        CASE
            WHEN s.SalesPrev3M IS NOT NULL AND ABS(s.SalesPrev3M) > 0
                THEN ((s.SalesLast3M - s.SalesPrev3M) / ABS(s.SalesPrev3M)) * 100.0
            ELSE NULL
        END AS SalesGrowth3M,

        CASE
            WHEN s.SalesAvg12M IS NOT NULL AND ABS(s.SalesAvg12M) > 0
                THEN 1.0 - (ISNULL(s.SalesStd12M, 0) / ABS(s.SalesAvg12M))
            ELSE NULL
        END AS SalesStability,

        -- ============ موتور TTM (اصلاح‌شده در v3) ============
        -- ۱) TTM تک‌گزارشی (v3.2): از سه ستون دوره‌ی خود گزارش
        --    (دوره جاری + س کل سال قبل − دوره‌ی مشابه سال قبل) — هم‌واحد و دقیق
        -- ۲) fallback: TTM بین‌گزارشی از ترکیب گزارش‌های تاریخی
        COALESCE(
            CASE
                WHEN p.LatestJMonth = 12 AND p.LatestNetProfitAmount IS NOT NULL
                    THEN p.LatestNetProfitAmount
                WHEN p.LatestNetProfitAmount IS NOT NULL
                 AND p.LatestNetProfitAmountFYPrev IS NOT NULL
                 AND p.LatestNetProfitAmountLY IS NOT NULL
                    THEN p.LatestNetProfitAmount + p.LatestNetProfitAmountFYPrev - p.LatestNetProfitAmountLY
                ELSE NULL
            END,
            CASE
                WHEN p.LatestJMonth = 12 THEN p.LatestNetProfitCum
                WHEN p.FYPrevNetProfit IS NOT NULL AND p.LYPNetProfit IS NOT NULL
                    THEN p.LatestNetProfitCum + p.FYPrevNetProfit - p.LYPNetProfit
                ELSE NULL
            END
        ) AS TTMNetProfit,

        -- TTMهای تک‌گزارشی هم‌واحد (برای حاشیه‌ها، ROE و جریان نقدی)
        CASE
            WHEN p.LatestJMonth = 12 AND p.LatestNetProfitAmount IS NOT NULL
                THEN p.LatestNetProfitAmount
            WHEN p.LatestNetProfitAmount IS NOT NULL
             AND p.LatestNetProfitAmountFYPrev IS NOT NULL
             AND p.LatestNetProfitAmountLY IS NOT NULL
                THEN p.LatestNetProfitAmount + p.LatestNetProfitAmountFYPrev - p.LatestNetProfitAmountLY
            ELSE NULL
        END AS SR_TTMNetProfit,

        CASE
            WHEN p.LatestJMonth = 12 AND p.LatestOpRaw IS NOT NULL
                THEN p.LatestOpRaw
            WHEN p.LatestOpRaw IS NOT NULL
             AND p.LatestOperatingProfitFYPrev IS NOT NULL
             AND p.LatestOpLYRaw IS NOT NULL
                THEN p.LatestOpRaw + p.LatestOperatingProfitFYPrev - p.LatestOpLYRaw
            ELSE NULL
        END AS SR_TTMOperatingProfit,

        CASE
            WHEN p.LatestJMonth = 12 AND p.LatestRevenueCum IS NOT NULL
                THEN p.LatestRevenueCum
            WHEN p.LatestRevenueCum IS NOT NULL
             AND p.LatestRevenueFYPrev IS NOT NULL
             AND p.LatestRevenueLYCum IS NOT NULL
                THEN p.LatestRevenueCum + p.LatestRevenueFYPrev - p.LatestRevenueLYCum
            ELSE NULL
        END AS SR_TTMRevenue,

        CASE
            WHEN p.LatestJMonth = 12 AND p.LatestOperatingCashFlow IS NOT NULL
                THEN p.LatestOperatingCashFlow
            WHEN p.LatestOperatingCashFlow IS NOT NULL
             AND p.LatestOperatingCashFlowFYPrev IS NOT NULL
             AND p.LatestOperatingCashFlowLY IS NOT NULL
                THEN p.LatestOperatingCashFlow + p.LatestOperatingCashFlowFYPrev - p.LatestOperatingCashFlowLY
            ELSE NULL
        END AS SR_TTMOperatingCashFlow,

        -- سود خالص ۱۲ماهه‌ی سال قبل
        CASE
            WHEN p.LatestJMonth = 12 THEN p.LYPNetProfit
            WHEN p.FYPrev2NetProfit IS NOT NULL AND p.LYP2NetProfit IS NOT NULL
                THEN p.LYPNetProfit + p.FYPrev2NetProfit - p.LYP2NetProfit
            ELSE NULL
        END AS TTMNetProfitPrev,

        -- TTM بین‌گزارشی صرفاً از Product1 — هم‌واحد تضمینی با TTMNetProfitPrev (v3.3)
        CASE
            WHEN p.LatestJMonth = 12 THEN p.LatestNetProfitCum
            WHEN p.FYPrevNetProfit IS NOT NULL AND p.LYPNetProfit IS NOT NULL
                THEN p.LatestNetProfitCum + p.FYPrevNetProfit - p.LYPNetProfit
            ELSE NULL
        END AS TTMNetProfitP1,

        -- ضریب تبدیل واحد: Product1 → ستون‌های مبلغی v3.2 (v3.3)
        -- از لنگرهایی که «یک کمیت» را در هر دو منبع دارند (سود دوره‌ی مشابه،
        -- سپس سود تجمعی گزارش آخر). فقط توان‌های صحیح ۱۰ با تلورانس
        -- log₁₀ ≤ 0.1 پذیرفته می‌شوند؛ هر نسبت دیگر یعنی خطای داده/تجدیدعرضه
        -- و باید به مسیر Product1-only برگردیم.
        COALESCE(
            CASE
                WHEN p.LatestNetProfitAmountLY IS NOT NULL
                 AND ABS(p.LYPNetProfit) > 0
                 AND p.LatestNetProfitAmountLY * p.LYPNetProfit > 0
                 AND ABS(LOG10(ABS(p.LatestNetProfitAmountLY) / ABS(p.LYPNetProfit))
                        - ROUND(LOG10(ABS(p.LatestNetProfitAmountLY) / ABS(p.LYPNetProfit)), 0)) <= 0.1
                    THEN POWER(10.0E0, ROUND(LOG10(ABS(p.LatestNetProfitAmountLY) / ABS(p.LYPNetProfit)), 0))
                ELSE NULL
            END,
            CASE
                WHEN p.LatestNetProfitAmount IS NOT NULL
                 AND ABS(p.LatestNetProfitCum) > 0
                 AND p.LatestNetProfitAmount * p.LatestNetProfitCum > 0
                 AND ABS(LOG10(ABS(p.LatestNetProfitAmount) / ABS(p.LatestNetProfitCum))
                        - ROUND(LOG10(ABS(p.LatestNetProfitAmount) / ABS(p.LatestNetProfitCum)), 0)) <= 0.1
                    THEN POWER(10.0E0, ROUND(LOG10(ABS(p.LatestNetProfitAmount) / ABS(p.LatestNetProfitCum)), 0))
                ELSE NULL
            END
        ) AS NPUnitRatio,

        -- سود عملیاتی ۱۲ماهه
        -- گارد سازگاری مقیاس: اگر اجزاء (گزارش آخر، س سال قبل، دوره‌ی مشابه)
        -- بیش از ۱۰۰ برابر اختلاف magnitude داشته باشند یعنی واحدها در گزارش‌های
        -- شرکت مخلوط است → محاسبه کنار گذاشته می‌شود (NULL)
        CASE
            WHEN p.LatestJMonth = 12 THEN p.LatestOpAbs
            WHEN p.FYPrevOpAbs IS NOT NULL AND p.LYPOpAbs IS NOT NULL
             AND (p.FYPrevOpAbs = 0 OR p.LatestOpAbs = 0
                  OR (ABS(p.FYPrevOpAbs) <= ABS(p.LatestOpAbs) * 100.0
                      AND ABS(p.LatestOpAbs) <= ABS(p.FYPrevOpAbs) * 100.0))
             AND (p.LYPOpAbs = 0 OR p.LatestOpAbs = 0
                  OR (ABS(p.LYPOpAbs) <= ABS(p.LatestOpAbs) * 100.0
                      AND ABS(p.LatestOpAbs) <= ABS(p.LYPOpAbs) * 100.0))
                THEN p.LatestOpAbs + p.FYPrevOpAbs - p.LYPOpAbs
            ELSE NULL
        END AS TTMOperatingProfit,

        -- سود عملیاتی ۱۲ماهه‌ی سال قبل (با همان گارد سازگاری مقیاس)
        CASE
            WHEN p.LatestJMonth = 12 THEN p.LYPOpAbs
            WHEN p.FYPrev2OpAbs IS NOT NULL AND p.LYP2OpAbs IS NOT NULL
             AND (p.FYPrev2OpAbs = 0 OR p.LYPOpAbs = 0
                  OR (ABS(p.FYPrev2OpAbs) <= ABS(p.LYPOpAbs) * 100.0
                      AND ABS(p.LYPOpAbs) <= ABS(p.FYPrev2OpAbs) * 100.0))
             AND (p.LYP2OpAbs = 0 OR p.LYPOpAbs = 0
                  OR (ABS(p.LYP2OpAbs) <= ABS(p.LYPOpAbs) * 100.0
                      AND ABS(p.LYPOpAbs) <= ABS(p.LYP2OpAbs) * 100.0))
                THEN p.LYPOpAbs + p.FYPrev2OpAbs - p.LYP2OpAbs
            ELSE NULL
        END AS TTMOperatingProfitPrev,

        -- درآمد ۱۲ماهه (هم‌منبع؛ فقط برای شرکت‌های دارای ستون درآمد)
        CASE
            WHEN p.LatestJMonth = 12 THEN p.LatestRevenueCum
            WHEN p.FYPrevRevenue IS NOT NULL AND p.LYPRevenue IS NOT NULL
                THEN p.LatestRevenueCum + p.FYPrevRevenue - p.LYPRevenue
            ELSE NULL
        END AS TTMRevenue,

        -- تعداد سهم ضمنی = سود تجمعی / EPS همان گزارش (سازگار با واحد سود)
        CASE
            WHEN p.LatestEPSReport > 0 AND p.LatestNetProfitCum > 0
                THEN p.LatestNetProfitCum / p.LatestEPSReport
            ELSE NULL
        END AS ImpliedShares,

        p.LatestEPSReport,
        p.LatestNetProfitCum,
        p.LatestOpAbs,
        p.LatestOpLYAbs,
        p.LatestRevenueCum,
        p.LatestRevenueLYCum,
        p.LatestFinanceCosts,
        p.LatestOtherNonOp,
        p.LatestNetProfitAmount,
        p.LatestTotalAssets,
        p.LatestCurrentAssets,
        p.LatestTotalLiabilities,
        p.LatestCurrentLiabilities,
        p.LatestTotalEquity,

        p.LYPNetProfit,
        p.LYPOpAbs,

        -- ============ معیارهای بازار ============
        m.LatestPrice,
        m.LatestClosingPrice,

        CASE
            WHEN m.ClosingPrice7D IS NOT NULL AND ABS(m.ClosingPrice7D) > 0
                THEN ((m.LatestClosingPrice - m.ClosingPrice7D) / ABS(m.ClosingPrice7D)) * 100.0
            ELSE NULL
        END AS PriceReturn7D,

        CASE
            WHEN m.ClosingPrice30D IS NOT NULL AND ABS(m.ClosingPrice30D) > 0
                THEN ((m.LatestClosingPrice - m.ClosingPrice30D) / ABS(m.ClosingPrice30D)) * 100.0
            ELSE NULL
        END AS PriceReturn30D,

        CASE
            WHEN m.ClosingPrice90D IS NOT NULL AND ABS(m.ClosingPrice90D) > 0
                THEN ((m.LatestClosingPrice - m.ClosingPrice90D) / ABS(m.ClosingPrice90D)) * 100.0
            ELSE NULL
        END AS PriceReturn90D,

        m.AvgTradeValue30D,
        m.AvgVolume30D,
        m.AvgTradeCount30D,
        m.Volatility30D,

        CASE
            WHEN m.HighPrice90D IS NOT NULL
             AND m.LowPrice90D IS NOT NULL
             AND ABS(m.HighPrice90D - m.LowPrice90D) > 0
                THEN ((m.LatestPrice - m.LowPrice90D) / ABS(m.HighPrice90D - m.LowPrice90D)) * 100.0
            ELSE NULL
        END AS PricePosition90D,

        -- ============ کهنگی داده ============
        -- تاریخ امروز شمسی (تقریبی؛ برای سنجش کهنگی به افقی چند ماهه کافی است)
        (YEAR(GETDATE()) -
            CASE
                WHEN (MONTH(GETDATE()) < 3) OR (MONTH(GETDATE()) = 3 AND DAY(GETDATE()) < 21) THEN 622
                ELSE 621
            END) * 12
        + CASE MONTH(GETDATE())
            WHEN 1 THEN 11 WHEN 2 THEN 12 WHEN 3 THEN 1 WHEN 4 THEN 2
            WHEN 5 THEN 3 WHEN 6 THEN 4 WHEN 7 THEN 5 WHEN 8 THEN 6
            WHEN 9 THEN 7 WHEN 10 THEN 8 WHEN 11 THEN 9 WHEN 12 THEN 10
          END
        - (p.LatestJYear * 12 + p.LatestJMonth) AS ProfitReportAgeMonths,

        DATEDIFF(DAY, m.LatestMarketDate, GETDATE()) AS MarketDataAgeDays,

        -- ============ کیفیت داده (با مؤلفه‌ی تازگی — v3) ============
        (
            CASE
                WHEN ISNULL(s.SalesReportCount, 0) >= 24 THEN 0.28
                WHEN ISNULL(s.SalesReportCount, 0) >= 12 THEN 0.16
                WHEN ISNULL(s.SalesReportCount, 0) >= 6 THEN 0.09
                ELSE 0
            END
            +
            CASE
                WHEN ISNULL(pa.ProfitReportCount, 0) >= 16 THEN 0.28
                WHEN ISNULL(pa.ProfitReportCount, 0) >= 8 THEN 0.16
                WHEN ISNULL(pa.ProfitReportCount, 0) >= 4 THEN 0.09
                ELSE 0
            END
            +
            CASE
                WHEN ISNULL(m.MarketDaysCount, 0) >= 90 THEN 0.21
                WHEN ISNULL(m.MarketDaysCount, 0) >= 30 THEN 0.13
                WHEN ISNULL(m.MarketDaysCount, 0) >= 10 THEN 0.06
                ELSE 0
            END
            +
            CASE
                WHEN m.LatestPrice IS NOT NULL AND m.LatestPrice > 0 THEN 0.09
                ELSE 0
            END
            +
            -- تازگی گزارش سود
            CASE
                WHEN p.LatestProfitReportDate IS NULL THEN 0
                WHEN (YEAR(GETDATE()) -
                        CASE
                            WHEN (MONTH(GETDATE()) < 3) OR (MONTH(GETDATE()) = 3 AND DAY(GETDATE()) < 21) THEN 622
                            ELSE 621
                        END) * 12
                     + CASE MONTH(GETDATE())
                        WHEN 1 THEN 11 WHEN 2 THEN 12 WHEN 3 THEN 1 WHEN 4 THEN 2
                        WHEN 5 THEN 3 WHEN 6 THEN 4 WHEN 7 THEN 5 WHEN 8 THEN 6
                        WHEN 9 THEN 7 WHEN 10 THEN 8 WHEN 11 THEN 9 WHEN 12 THEN 10
                       END
                     - (p.LatestJYear * 12 + p.LatestJMonth) <= 5 THEN 0.08
                WHEN (YEAR(GETDATE()) -
                        CASE
                            WHEN (MONTH(GETDATE()) < 3) OR (MONTH(GETDATE()) = 3 AND DAY(GETDATE()) < 21) THEN 622
                            ELSE 621
                        END) * 12
                     + CASE MONTH(GETDATE())
                        WHEN 1 THEN 11 WHEN 2 THEN 12 WHEN 3 THEN 1 WHEN 4 THEN 2
                        WHEN 5 THEN 3 WHEN 6 THEN 4 WHEN 7 THEN 5 WHEN 8 THEN 6
                        WHEN 9 THEN 7 WHEN 10 THEN 8 WHEN 11 THEN 9 WHEN 12 THEN 10
                       END
                     - (p.LatestJYear * 12 + p.LatestJMonth) <= 8 THEN 0.045
                ELSE 0
            END
            +
            -- تازگی داده‌ی قیمت
            CASE
                WHEN m.LatestMarketDate IS NULL THEN 0
                WHEN DATEDIFF(DAY, m.LatestMarketDate, GETDATE()) <= 7 THEN 0.06
                WHEN DATEDIFF(DAY, m.LatestMarketDate, GETDATE()) <= 14 THEN 0.035
                ELSE 0
            END
        ) AS DataQualityScore
    FROM CompanyList c
    LEFT JOIN SalesAgg s ON s.CompanyID = c.CompanyID
    LEFT JOIN ProfitWide p ON p.CompanyID = c.CompanyID
    LEFT JOIN ProfitAgg pa ON pa.CompanyID = c.CompanyID
    LEFT JOIN MarketAgg m ON m.CompanyID = c.CompanyID
),

Derived AS (
    SELECT
        b.*,

        -- رشد سود خالص (v3.3): فقط جفت‌های هم‌واحد مقایسه می‌شوند
        -- ۱) TTM تک‌گزارشی (ستون‌های مبلغی v3.2) در برابر TTM سال قبل × ضریب واحد
        -- ۲) TTM بین‌گزارشی Product1 در برابر TTM سال قبل Product1
        -- ۳) fallback: رشد دوره‌ی مشابه سال قبل (هر دو Product1)
        COALESCE(
            CASE
                WHEN b.SR_TTMNetProfit IS NOT NULL
                 AND b.NPUnitRatio IS NOT NULL
                 AND b.TTMNetProfitPrev IS NOT NULL AND ABS(b.TTMNetProfitPrev) > 0
                    THEN ((b.SR_TTMNetProfit - b.TTMNetProfitPrev * b.NPUnitRatio)
                          / ABS(b.TTMNetProfitPrev * b.NPUnitRatio)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN b.TTMNetProfitP1 IS NOT NULL
                 AND b.TTMNetProfitPrev IS NOT NULL AND ABS(b.TTMNetProfitPrev) > 0
                    THEN ((b.TTMNetProfitP1 - b.TTMNetProfitPrev) / ABS(b.TTMNetProfitPrev)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN b.LYPNetProfit IS NOT NULL AND ABS(b.LYPNetProfit) > 0
                    THEN ((b.LatestNetProfitCum - b.LYPNetProfit) / ABS(b.LYPNetProfit)) * 100.0
                ELSE NULL
            END
        ) AS NetProfitGrowthTTM,

        -- رشد سود عملیاتی: TTM در اولویت، بعد دوره‌ی مشابه، بعد ستون داخل گزارش
        -- (هر مقایسه فقط با گارد سازگاری مقیاس ±۱۰۰ برابر انجام می‌شود)
        COALESCE(
            CASE
                WHEN b.TTMOperatingProfitPrev IS NOT NULL AND ABS(b.TTMOperatingProfitPrev) > 0
                    THEN ((b.TTMOperatingProfit - b.TTMOperatingProfitPrev) / ABS(b.TTMOperatingProfitPrev)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN b.LYPOpAbs IS NOT NULL AND ABS(b.LYPOpAbs) > 0
                 AND b.LatestOpAbs IS NOT NULL
                 AND ABS(b.LYPOpAbs) <= ABS(b.LatestOpAbs) * 100.0
                 AND ABS(b.LatestOpAbs) <= ABS(b.LYPOpAbs) * 100.0
                    THEN ((b.LatestOpAbs - b.LYPOpAbs) / ABS(b.LYPOpAbs)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN b.LatestOpLYAbs IS NOT NULL AND ABS(b.LatestOpLYAbs) > 0
                 AND b.LatestOpAbs IS NOT NULL
                 AND ABS(b.LatestOpLYAbs) <= ABS(b.LatestOpAbs) * 100.0
                 AND ABS(b.LatestOpAbs) <= ABS(b.LatestOpLYAbs) * 100.0
                    THEN ((b.LatestOpAbs - b.LatestOpLYAbs) / ABS(b.LatestOpLYAbs)) * 100.0
                ELSE NULL
            END
        ) AS OperatingProfitGrowthTTM,

        -- درآمد ۱۲ماهه‌ی مؤثر: هم‌منبع در اولویت، وگرنه فروش ماهانه
        COALESCE(b.TTMRevenue, b.SalesLast12M) AS EffectiveRevenue12M,

        -- حاشیه‌های ۱۲ماهه؛ اولویت با TTM تک‌گزارشی هم‌واحد (v3.2)
        -- سقف معقولیت |حاشیه| ≤ ۲۰۰٪: خارج از آن تقریباً همیشه خطای واحد داده است
        CASE
            WHEN b.SR_TTMOperatingProfit IS NOT NULL AND b.SR_TTMRevenue IS NOT NULL
             AND ABS(b.SR_TTMRevenue) > 0
             AND ABS(b.SR_TTMOperatingProfit / ABS(b.SR_TTMRevenue) * 100.0) <= 200.0
                THEN (b.SR_TTMOperatingProfit / ABS(b.SR_TTMRevenue)) * 100.0
            WHEN b.TTMOperatingProfit IS NOT NULL AND ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) > 0
             AND ABS(b.TTMOperatingProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) * 100.0) <= 200.0
                THEN (b.TTMOperatingProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M))) * 100.0
            ELSE NULL
        END AS OperatingMargin12M,

        CASE
            WHEN b.SR_TTMNetProfit IS NOT NULL AND b.SR_TTMRevenue IS NOT NULL
             AND ABS(b.SR_TTMRevenue) > 0
             AND ABS(b.SR_TTMNetProfit / ABS(b.SR_TTMRevenue) * 100.0) <= 200.0
                THEN (b.SR_TTMNetProfit / ABS(b.SR_TTMRevenue)) * 100.0
            WHEN b.TTMNetProfit IS NOT NULL AND ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) > 0
             AND ABS(b.TTMNetProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) * 100.0) <= 200.0
                THEN (b.TTMNetProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M))) * 100.0
            ELSE NULL
        END AS NetProfitMargin12M,

        -- حاشیه‌های گزارش آخر (هم‌منبع؛ نسبت است پس طول دوره خنثی می‌شود)
        -- v3.3: گارد ±۲۰۰٪ — Product1 (ریال) و RevenueNew (هزار ریال) هم‌خانواده نیستند؛
        -- حاشیه‌ی بیرون از ±۲۰۰٪ تقریباً همیشه خطای واحد است → NULL
        CASE
            WHEN b.LatestOpAbs IS NOT NULL AND b.LatestRevenueCum IS NOT NULL AND ABS(b.LatestRevenueCum) > 0
             AND ABS(b.LatestOpAbs / ABS(b.LatestRevenueCum) * 100.0) <= 200.0
                THEN (b.LatestOpAbs / ABS(b.LatestRevenueCum)) * 100.0
            ELSE NULL
        END AS OperatingMarginLatest,

        -- v3.3: اولویت با NetProfitAmount (هم‌واحد با RevenueNew)؛
        -- fallback فقط با گارد ±۲۰۰٪ (Product1 ریالی ÷ درآمد هزارریالی = ۱۰۰۰ برابر خطا)
        CASE
            WHEN b.LatestNetProfitAmount IS NOT NULL
             AND b.LatestRevenueCum IS NOT NULL AND ABS(b.LatestRevenueCum) > 0
                THEN (b.LatestNetProfitAmount / ABS(b.LatestRevenueCum)) * 100.0
            WHEN b.LatestNetProfitCum IS NOT NULL
             AND b.LatestRevenueCum IS NOT NULL AND ABS(b.LatestRevenueCum) > 0
             AND ABS(b.LatestNetProfitCum / ABS(b.LatestRevenueCum) * 100.0) <= 200.0
                THEN (b.LatestNetProfitCum / ABS(b.LatestRevenueCum)) * 100.0
            ELSE NULL
        END AS NetMarginLatest,

        -- روند حاشیه عملیاتی: هم‌منبع در اولویت
        -- v3.3: هر دو سمت باید |حاشیه| ≤ ۲۰۰٪ داشته باشند؛ در غیر این صورت
        -- اختلاف واحدها (OpAbs ریالی/هزارریالی در دو دوره) مقدار را خراب می‌کند
        COALESCE(
            CASE
                WHEN b.LatestOpAbs IS NOT NULL AND b.LatestOpLYAbs IS NOT NULL
                 AND b.LatestRevenueCum IS NOT NULL AND b.LatestRevenueLYCum IS NOT NULL
                 AND ABS(b.LatestRevenueCum) > 0 AND ABS(b.LatestRevenueLYCum) > 0
                 AND ABS(b.LatestOpAbs / ABS(b.LatestRevenueCum) * 100.0) <= 200.0
                 AND ABS(b.LatestOpLYAbs / ABS(b.LatestRevenueLYCum) * 100.0) <= 200.0
                    THEN (b.LatestOpAbs / ABS(b.LatestRevenueCum)) * 100.0
                       - (b.LatestOpLYAbs / ABS(b.LatestRevenueLYCum)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN b.TTMOperatingProfitPrev IS NOT NULL
                 AND b.SalesPrev12M IS NOT NULL AND ABS(b.SalesPrev12M) > 0
                 AND ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) > 0
                 AND ABS(b.TTMOperatingProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M)) * 100.0) <= 200.0
                 AND ABS(b.TTMOperatingProfitPrev / ABS(b.SalesPrev12M) * 100.0) <= 200.0
                    THEN (b.TTMOperatingProfit / ABS(COALESCE(b.TTMRevenue, b.SalesLast12M))) * 100.0
                       - (b.TTMOperatingProfitPrev / ABS(b.SalesPrev12M)) * 100.0
                ELSE NULL
            END
        ) AS OperatingMarginTrend,

        -- رشد درآمد هم‌منبع (دوره‌ی مشابه سال قبل)
        CASE
            WHEN b.LatestRevenueCum IS NOT NULL AND b.LatestRevenueLYCum IS NOT NULL
             AND ABS(b.LatestRevenueLYCum) > 0
                THEN ((b.LatestRevenueCum - b.LatestRevenueLYCum) / ABS(b.LatestRevenueLYCum)) * 100.0
            ELSE NULL
        END AS RevenueGrowthYoY,

        -- پوشش هزینه‌ی مالی (هم‌منبع)؛ خارج از بازه‌ی معقول (۰, ۱۰۰۰۰] → NULL
        CASE
            WHEN b.LatestOpAbs IS NOT NULL AND b.LatestFinanceCosts IS NOT NULL
             AND ABS(b.LatestFinanceCosts) > 0
             AND b.LatestOpAbs / ABS(b.LatestFinanceCosts) > 0
             AND b.LatestOpAbs / ABS(b.LatestFinanceCosts) <= 10000.0
                THEN b.LatestOpAbs / ABS(b.LatestFinanceCosts)
            ELSE NULL
        END AS InterestCoverage,

        -- سهم غیرعملیاتی از سود عملیاتی (هم‌منبع؛ قدرمطلق چون وابستگی ملاک است)
        CASE
            WHEN b.LatestOtherNonOp IS NOT NULL AND b.LatestOpAbs IS NOT NULL
             AND ABS(b.LatestOpAbs) > 0
                THEN (ABS(b.LatestOtherNonOp) / ABS(b.LatestOpAbs)) * 100.0
            ELSE NULL
        END AS NonOperatingPct,

        -- ============ فاکتورهای v3.2 از ترازنامه و جریان نقدی ============
        -- ROE = سود خالص ۱۲ماهه‌ی هم‌واحد / حقوق مالکانه (سقف معقولیت ±۳۰۰٪)
        CASE
            WHEN b.SR_TTMNetProfit IS NOT NULL
             AND b.LatestTotalEquity IS NOT NULL AND b.LatestTotalEquity > 0
             AND ABS(b.SR_TTMNetProfit / b.LatestTotalEquity * 100.0) <= 300.0
                THEN (b.SR_TTMNetProfit / b.LatestTotalEquity) * 100.0
            ELSE NULL
        END AS ROE,

        -- اهرم مالی = بدهی‌ها / حقوق مالکانه (کمتر = ایمن‌تر؛ سقف ۵۰)
        CASE
            WHEN b.LatestTotalLiabilities IS NOT NULL AND b.LatestTotalLiabilities >= 0
             AND b.LatestTotalEquity IS NOT NULL AND b.LatestTotalEquity > 0
             AND b.LatestTotalLiabilities / b.LatestTotalEquity <= 50.0
                THEN b.LatestTotalLiabilities / b.LatestTotalEquity
            ELSE NULL
        END AS FinancialLeverage,

        -- نسبت جاری = دارایی جاری / بدهی جاری (سقف ۱۵)
        CASE
            WHEN b.LatestCurrentAssets IS NOT NULL AND b.LatestCurrentAssets >= 0
             AND b.LatestCurrentLiabilities IS NOT NULL AND b.LatestCurrentLiabilities > 0
             AND b.LatestCurrentAssets / b.LatestCurrentLiabilities <= 15.0
                THEN b.LatestCurrentAssets / b.LatestCurrentLiabilities
            ELSE NULL
        END AS CurrentRatio,

        -- کیفیت نقدی سود = جریان نقد عملیاتی ۱۲ماهه / سود خالص ۱۲ماهه
        -- هرچه به ۱ نزدیک‌تر یا بالاتر = سود پشتوانه‌ی نقدی دارد (بازه‌ی معقول −۲..۵)
        CASE
            WHEN b.SR_TTMOperatingCashFlow IS NOT NULL
             AND b.SR_TTMNetProfit IS NOT NULL AND b.SR_TTMNetProfit > 0
             AND b.SR_TTMOperatingCashFlow / b.SR_TTMNetProfit BETWEEN -2.0 AND 5.0
                THEN b.SR_TTMOperatingCashFlow / b.SR_TTMNetProfit
            ELSE NULL
        END AS CashConversion,

        -- EPS دوازده‌ماهه — نسبت‌ها باید هم‌مقیاس باشند:
        -- اولویت ۱: SR_TTM ÷ NetProfitAmount (هر دو واحد جدول) × EPS گزارش
        -- اولویت ۲: TTM بین‌گزارشی ÷ سود تجمعی Product1 (هر دو مقیاس Product1) × EPS
        COALESCE(
            CASE
                WHEN b.SR_TTMNetProfit IS NOT NULL
                 AND b.LatestNetProfitAmount IS NOT NULL AND b.LatestNetProfitAmount > 0
                 AND b.LatestEPSReport > 0
                    THEN b.SR_TTMNetProfit * b.LatestEPSReport / b.LatestNetProfitAmount
                ELSE NULL
            END,
            CASE
                WHEN b.TTMNetProfit IS NOT NULL AND b.LatestEPSReport > 0 AND b.LatestNetProfitCum > 0
                    THEN b.TTMNetProfit * b.LatestEPSReport / b.LatestNetProfitCum
                ELSE NULL
            END
        ) AS TTMEPS,

        -- P/E بر مبنای EPS دوازدهماهه (اصلاح v3)
        CASE
            WHEN b.LatestPrice IS NOT NULL AND b.LatestPrice > 0
             AND b.SR_TTMNetProfit IS NOT NULL
             AND b.LatestNetProfitAmount IS NOT NULL AND b.LatestNetProfitAmount > 0
             AND b.LatestEPSReport > 0
                THEN b.LatestPrice / (b.SR_TTMNetProfit * b.LatestEPSReport / b.LatestNetProfitAmount)
            WHEN b.LatestPrice IS NOT NULL AND b.LatestPrice > 0
             AND b.TTMNetProfit IS NOT NULL AND b.LatestEPSReport > 0 AND b.LatestNetProfitCum > 0
             AND b.TTMNetProfit * b.LatestEPSReport / b.LatestNetProfitCum > 0
                THEN b.LatestPrice / (b.TTMNetProfit * b.LatestEPSReport / b.LatestNetProfitCum)
            ELSE NULL
        END AS PEApprox,

        -- EPS عملیاتی دوازده‌ماهه (نمایشی)
        CASE
            WHEN b.TTMOperatingProfit IS NOT NULL AND b.LatestEPSReport > 0 AND b.LatestNetProfitCum > 0
                THEN b.TTMOperatingProfit * b.LatestEPSReport / b.LatestNetProfitCum
            ELSE NULL
        END AS TTMOperatingEPS
    FROM BaseMetrics b
),

-- ---------------------------------------------------------------------------
--  رتبه‌بندی مقطعی (صدکی) با کراپ مقادیر افراطی — v3.1
--
--  اصل مهم: صدکِ هر فاکتور فقط بین شرکت‌هایی محاسبه می‌شود که برای آن فاکتور
--  «داده دارند»؛ شرکت‌های بدون داده از مخرج توزیع حذف می‌شوند و رتبه‌ی خنثی
--  می‌گیرند (قبلاً ردیف‌های NULL در توزیع می‌نشستند و رتبه‌ی شرکت‌های واقعی
--  را منحرف می‌کردند — مثلاً بهترین کیفیت سود رتبه‌ی ۲۴٪ می‌گرفت!).
--
--  فرمول صدک (مدل strictly-below با مدیریت tie):
--      pct = تعداد داده‌های کوچک‌تر / (تعداد داده − ۱)
--      مقدار مساوی (tie) هم‌رتبه‌اند؛ گروهِ بهترین مقدار → صدک ۰ → رتبه ۱۰۰٪
--  فاکتورهایی که «کمتر بهتر» است (P/E، P/S، غیرعملیاتی، نوسان) معکوس می‌شوند.
--
--  NULL ساختاری → رتبه‌ی خنثی 0.30 (پوشش بهره/کیفیت سود نامعلوم: 0.50)
--  مقدار نامعتبر (P/E نامعتبر و…) → بدترین رتبه + جریمه
-- ---------------------------------------------------------------------------
RankKeys AS (
    SELECT
        d.*,
        COUNT(*) OVER () AS NRows,

        CASE WHEN d.SalesGrowth12M IS NULL THEN NULL
             WHEN d.SalesGrowth12M > 150 THEN 150.0
             WHEN d.SalesGrowth12M < -150 THEN -150.0
             ELSE d.SalesGrowth12M END AS SGKey,

        CASE WHEN d.SalesGrowth3M IS NULL THEN NULL
             WHEN d.SalesGrowth3M > 150 THEN 150.0
             WHEN d.SalesGrowth3M < -150 THEN -150.0
             ELSE d.SalesGrowth3M END AS SG3Key,

        CASE WHEN d.NetProfitGrowthTTM IS NULL THEN NULL
             WHEN d.NetProfitGrowthTTM > 300 THEN 300.0
             WHEN d.NetProfitGrowthTTM < -300 THEN -300.0
             ELSE d.NetProfitGrowthTTM END AS NPGKey,

        CASE WHEN d.OperatingProfitGrowthTTM IS NULL THEN NULL
             WHEN d.OperatingProfitGrowthTTM > 250 THEN 250.0
             WHEN d.OperatingProfitGrowthTTM < -250 THEN -250.0
             ELSE d.OperatingProfitGrowthTTM END AS OPGKey,

        CASE WHEN d.RevenueGrowthYoY IS NULL THEN NULL
             WHEN d.RevenueGrowthYoY > 200 THEN 200.0
             WHEN d.RevenueGrowthYoY < -200 THEN -200.0
             ELSE d.RevenueGrowthYoY END AS RGKey,

        CASE WHEN d.OperatingMargin12M IS NULL THEN NULL
             WHEN d.OperatingMargin12M > 80 THEN 80.0
             WHEN d.OperatingMargin12M < -80 THEN -80.0
             ELSE d.OperatingMargin12M END AS OMKey,

        CASE WHEN d.NetProfitMargin12M IS NULL THEN NULL
             WHEN d.NetProfitMargin12M > 60 THEN 60.0
             WHEN d.NetProfitMargin12M < -60 THEN -60.0
             ELSE d.NetProfitMargin12M END AS NMKey,

        CASE WHEN d.OperatingMarginTrend IS NULL THEN NULL
             WHEN d.OperatingMarginTrend > 25 THEN 25.0
             WHEN d.OperatingMarginTrend < -25 THEN -25.0
             ELSE d.OperatingMarginTrend END AS MTKey,

        -- پوشش بهره: نامعلوم → NULL | زیر صفر → بدترین | بالای ۲۰× سقف
        CASE WHEN d.InterestCoverage IS NULL THEN NULL
             WHEN d.InterestCoverage <= 0 THEN -999999.0
             WHEN d.InterestCoverage > 20 THEN 20.0
             ELSE d.InterestCoverage END AS ICKey,

        -- سهم غیرعملیاتی (قدرمطلق؛ کمتر = سود باکیفیت‌تر)
        CASE WHEN d.NonOperatingPct IS NULL THEN NULL
             WHEN ABS(d.NonOperatingPct) > 150 THEN 150.0
             ELSE ABS(d.NonOperatingPct) END AS EQKey,

        -- P/E فقط در بازه‌ی (۰، ۶۰] معتبر؛ خارج از آن بدترین کلید
        CASE WHEN d.PEApprox IS NOT NULL AND d.PEApprox > 0 AND d.PEApprox <= 60
             THEN d.PEApprox ELSE 999999.0 END AS PEKey,

        -- P/S = P/E × حاشیه خالص؛ فقط وقتی هر دو معتبرند
        CASE WHEN d.PEApprox IS NOT NULL AND d.PEApprox > 0 AND d.PEApprox <= 60
              AND d.NetProfitMargin12M IS NOT NULL AND d.NetProfitMargin12M > 0
             THEN d.PEApprox * (d.NetProfitMargin12M / 100.0)
             ELSE 999999.0 END AS PSKey,

        d.AvgTradeValue30D AS LQKey,
        d.SalesStability AS STKey,
        d.Volatility30D AS LVKey,

        -- مومنتوم کراپ‌شده
        CASE WHEN d.PriceReturn30D IS NULL THEN NULL
             WHEN d.PriceReturn30D > 40 THEN 40.0
             WHEN d.PriceReturn30D < -50 THEN -50.0
             ELSE d.PriceReturn30D END AS MOKey,

        -- ===== فاکتورهای v3.2 =====
        -- ROE (کراپ ±۱۵۰٪)
        CASE WHEN d.ROE IS NULL THEN NULL
             WHEN d.ROE > 150 THEN 150.0
             WHEN d.ROE < -150 THEN -150.0
             ELSE d.ROE END AS ROEKey,

        -- اهرم مالی: کمتر بهتر → معکوس (کراپ ۵۰)
        CASE WHEN d.FinancialLeverage IS NULL THEN NULL
             WHEN d.FinancialLeverage > 50 THEN 50.0
             ELSE d.FinancialLeverage END AS LEVKey,

        -- نسبت جاری (کراپ ۱۵)
        CASE WHEN d.CurrentRatio IS NULL THEN NULL
             WHEN d.CurrentRatio > 15 THEN 15.0
             ELSE d.CurrentRatio END AS CRKey,

        -- کیفیت نقدی سود (کراپ −۲..۵) — بالاتر بهتر
        CASE WHEN d.CashConversion IS NULL THEN NULL
             WHEN d.CashConversion > 5 THEN 5.0
             WHEN d.CashConversion < -2 THEN -2.0
             ELSE d.CashConversion END AS CCKey,

        -- P/B = P/E × ROE فقط وقتی هر دو معتبرند (سقف معتبر ۳۰)
        CASE WHEN d.PEApprox IS NOT NULL AND d.PEApprox > 0 AND d.PEApprox <= 60
              AND d.ROE IS NOT NULL AND d.ROE > 0
              AND d.PEApprox * d.ROE / 100.0 <= 30.0
             THEN d.PEApprox * d.ROE / 100.0
             ELSE 999999.0 END AS PBKey
    FROM Derived d
),

RankDists AS (
    SELECT
        k.*,
        RANK() OVER (ORDER BY k.SGKey)  AS SGRnk,  COUNT(k.SGKey)  OVER () AS SGCnt,
        RANK() OVER (ORDER BY k.SG3Key) AS SG3Rnk, COUNT(k.SG3Key) OVER () AS SG3Cnt,
        RANK() OVER (ORDER BY k.NPGKey) AS NPGRnk, COUNT(k.NPGKey) OVER () AS NPGCnt,
        RANK() OVER (ORDER BY k.OPGKey) AS OPGRnk, COUNT(k.OPGKey) OVER () AS OPGCnt,
        RANK() OVER (ORDER BY k.RGKey)  AS RGRnk,  COUNT(k.RGKey)  OVER () AS RGCnt,
        RANK() OVER (ORDER BY k.OMKey)  AS OMRnk,  COUNT(k.OMKey)  OVER () AS OMCnt,
        RANK() OVER (ORDER BY k.NMKey)  AS NMRnk,  COUNT(k.NMKey)  OVER () AS NMCnt,
        RANK() OVER (ORDER BY k.MTKey)  AS MTRnk,  COUNT(k.MTKey)  OVER () AS MTCnt,
        RANK() OVER (ORDER BY k.ICKey)  AS ICRnk,  COUNT(k.ICKey)  OVER () AS ICCnt,
        RANK() OVER (ORDER BY k.EQKey)  AS EQRnk,  COUNT(k.EQKey)  OVER () AS EQCnt,
        RANK() OVER (ORDER BY k.PEKey)  AS PERnk,  COUNT(k.PEKey)  OVER () AS PECnt,
        RANK() OVER (ORDER BY k.PSKey)  AS PSRnk,  COUNT(k.PSKey)  OVER () AS PSCnt,
        RANK() OVER (ORDER BY k.LQKey)  AS LQRnk,  COUNT(k.LQKey)  OVER () AS LQCnt,
        RANK() OVER (ORDER BY k.STKey)  AS STRnk,  COUNT(k.STKey)  OVER () AS STCnt,
        RANK() OVER (ORDER BY k.LVKey)  AS LVRnk,  COUNT(k.LVKey)  OVER () AS LVCnt,
        RANK() OVER (ORDER BY k.MOKey)  AS MORnk,  COUNT(k.MOKey)  OVER () AS MOCnt,
        RANK() OVER (ORDER BY k.ROEKey) AS ROERnk, COUNT(k.ROEKey) OVER () AS ROECnt,
        RANK() OVER (ORDER BY k.LEVKey) AS LEVRnk, COUNT(k.LEVKey) OVER () AS LEVCnt,
        RANK() OVER (ORDER BY k.CRKey)  AS CRRnk,  COUNT(k.CRKey)  OVER () AS CRCnt,
        RANK() OVER (ORDER BY k.CCKey)  AS CCRnk,  COUNT(k.CCKey)  OVER () AS CCCnt,
        RANK() OVER (ORDER BY k.PBKey)  AS PBRnk,  COUNT(k.PBKey)  OVER () AS PBCnt,

        -- اندازه‌ی گروه هم‌ارزش (tie) برای صدکِ میانی
        COUNT(*) OVER (PARTITION BY k.SGKey)  AS SGTie,
        COUNT(*) OVER (PARTITION BY k.SG3Key) AS SG3Tie,
        COUNT(*) OVER (PARTITION BY k.NPGKey) AS NPGTie,
        COUNT(*) OVER (PARTITION BY k.OPGKey) AS OPGTie,
        COUNT(*) OVER (PARTITION BY k.RGKey)  AS RGTie,
        COUNT(*) OVER (PARTITION BY k.OMKey)  AS OMTie,
        COUNT(*) OVER (PARTITION BY k.NMKey)  AS NMTie,
        COUNT(*) OVER (PARTITION BY k.MTKey)  AS MTTie,
        COUNT(*) OVER (PARTITION BY k.ICKey)  AS ICTie,
        COUNT(*) OVER (PARTITION BY k.EQKey)  AS EQTie,
        COUNT(*) OVER (PARTITION BY k.PEKey)  AS PETie,
        COUNT(*) OVER (PARTITION BY k.PSKey)  AS PSTie,
        COUNT(*) OVER (PARTITION BY k.LQKey)  AS LQTie,
        COUNT(*) OVER (PARTITION BY k.STKey)  AS STTie,
        COUNT(*) OVER (PARTITION BY k.LVKey)  AS LVTie,
        COUNT(*) OVER (PARTITION BY k.MOKey)  AS MOTie,
        COUNT(*) OVER (PARTITION BY k.ROEKey) AS ROETie,
        COUNT(*) OVER (PARTITION BY k.LEVKey) AS LEVTie,
        COUNT(*) OVER (PARTITION BY k.CRKey)  AS CRTie,
        COUNT(*) OVER (PARTITION BY k.CCKey)  AS CCTie,
        COUNT(*) OVER (PARTITION BY k.PBKey)  AS PBTie
    FROM RankKeys k
),

-- صدک میانی (midrank): مقدار هم‌رتبه به جای «کل زیر گروه»، میانگین جایگاه گروه را می‌گیرد
--   pct = (2×تعداد_کوچک‌تر_اکید + تعداد_هم‌ارزش − 1) / (2×(تعداد داده − 1))
Ranked AS (
    SELECT
        r.*,

        CASE WHEN r.SGKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.SGRnk - 1 - (r.NRows - r.SGCnt)) + (r.SGTie - 1)) * 1.0 / NULLIF(2*(r.SGCnt - 1), 0), 0.5) END AS SalesGrowthRank,

        CASE WHEN r.SG3Key IS NULL THEN 0.30
             ELSE COALESCE((2*(r.SG3Rnk - 1 - (r.NRows - r.SG3Cnt)) + (r.SG3Tie - 1)) * 1.0 / NULLIF(2*(r.SG3Cnt - 1), 0), 0.5) END AS SalesGrowth3MRank,

        CASE WHEN r.NPGKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.NPGRnk - 1 - (r.NRows - r.NPGCnt)) + (r.NPGTie - 1)) * 1.0 / NULLIF(2*(r.NPGCnt - 1), 0), 0.5) END AS NetProfitGrowthRank,

        CASE WHEN r.OPGKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.OPGRnk - 1 - (r.NRows - r.OPGCnt)) + (r.OPGTie - 1)) * 1.0 / NULLIF(2*(r.OPGCnt - 1), 0), 0.5) END AS OperatingProfitGrowthRank,

        CASE WHEN r.RGKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.RGRnk - 1 - (r.NRows - r.RGCnt)) + (r.RGTie - 1)) * 1.0 / NULLIF(2*(r.RGCnt - 1), 0), 0.5) END AS RevenueGrowthRank,

        CASE WHEN r.OMKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.OMRnk - 1 - (r.NRows - r.OMCnt)) + (r.OMTie - 1)) * 1.0 / NULLIF(2*(r.OMCnt - 1), 0), 0.5) END AS OperatingMarginRank,

        CASE WHEN r.NMKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.NMRnk - 1 - (r.NRows - r.NMCnt)) + (r.NMTie - 1)) * 1.0 / NULLIF(2*(r.NMCnt - 1), 0), 0.5) END AS NetMarginRank,

        CASE WHEN r.MTKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.MTRnk - 1 - (r.NRows - r.MTCnt)) + (r.MTTie - 1)) * 1.0 / NULLIF(2*(r.MTCnt - 1), 0), 0.5) END AS MarginTrendRank,

        CASE WHEN r.ICKey IS NULL THEN 0.50
             ELSE COALESCE((2*(r.ICRnk - 1 - (r.NRows - r.ICCnt)) + (r.ICTie - 1)) * 1.0 / NULLIF(2*(r.ICCnt - 1), 0), 0.5) END AS InterestCoverageRank,

        -- کیفیت سود: کمتر بهتر → معکوس
        CASE WHEN r.EQKey IS NULL THEN 0.50
             ELSE COALESCE(1.0 - (2*(r.EQRnk - 1 - (r.NRows - r.EQCnt)) + (r.EQTie - 1)) * 1.0 / NULLIF(2*(r.EQCnt - 1), 0), 0.5) END AS EarningsQualityRank,

        -- P/E: کمتر بهتر → معکوس؛ نامعتبر (کلید 999999) → صفر
        CASE WHEN r.PEKey >= 999999.0 THEN 0.0
             ELSE COALESCE(1.0 - (2*(r.PERnk - 1 - (r.NRows - r.PECnt)) + (r.PETie - 1)) * 1.0 / NULLIF(2*(r.PECnt - 1), 0), 0.5) END AS PERank,

        CASE WHEN r.PSKey >= 999999.0 THEN 0.0
             ELSE COALESCE(1.0 - (2*(r.PSRnk - 1 - (r.NRows - r.PSCnt)) + (r.PSTie - 1)) * 1.0 / NULLIF(2*(r.PSCnt - 1), 0), 0.5) END AS PSRank,

        -- نقدشوندگی: بدون داده = بدترین (قابل معامله نیست)؛ خنثی ندارد
        CASE WHEN r.LQKey IS NULL THEN 0.0
             ELSE COALESCE((2*(r.LQRnk - 1 - (r.NRows - r.LQCnt)) + (r.LQTie - 1)) * 1.0 / NULLIF(2*(r.LQCnt - 1), 0), 0.5) END AS LiquidityRank,

        CASE WHEN r.STKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.STRnk - 1 - (r.NRows - r.STCnt)) + (r.STTie - 1)) * 1.0 / NULLIF(2*(r.STCnt - 1), 0), 0.5) END AS StabilityRank,

        -- نوسان کم بهتر → معکوس
        CASE WHEN r.LVKey IS NULL THEN 0.30
             ELSE COALESCE(1.0 - (2*(r.LVRnk - 1 - (r.NRows - r.LVCnt)) + (r.LVTie - 1)) * 1.0 / NULLIF(2*(r.LVCnt - 1), 0), 0.5) END AS LowVolatilityRank,

        CASE WHEN r.MOKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.MORnk - 1 - (r.NRows - r.MOCnt)) + (r.MOTie - 1)) * 1.0 / NULLIF(2*(r.MOCnt - 1), 0), 0.5) END AS MomentumRank,

        -- ===== رتبه‌های v3.2 =====
        CASE WHEN r.ROEKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.ROERnk - 1 - (r.NRows - r.ROECnt)) + (r.ROETie - 1)) * 1.0 / NULLIF(2*(r.ROECnt - 1), 0), 0.5) END AS ROERank,

        -- اهرم کمتر بهتر → معکوس
        CASE WHEN r.LEVKey IS NULL THEN 0.30
             ELSE COALESCE(1.0 - (2*(r.LEVRnk - 1 - (r.NRows - r.LEVCnt)) + (r.LEVTie - 1)) * 1.0 / NULLIF(2*(r.LEVCnt - 1), 0), 0.5) END AS LeverageRank,

        CASE WHEN r.CRKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.CRRnk - 1 - (r.NRows - r.CRCnt)) + (r.CRTie - 1)) * 1.0 / NULLIF(2*(r.CRCnt - 1), 0), 0.5) END AS CurrentRatioRank,

        CASE WHEN r.CCKey IS NULL THEN 0.30
             ELSE COALESCE((2*(r.CCRnk - 1 - (r.NRows - r.CCCnt)) + (r.CCTie - 1)) * 1.0 / NULLIF(2*(r.CCCnt - 1), 0), 0.5) END AS CashConversionRank,

        -- P/B کمتر بهتر؛ نامعتبر (کلید 999999) → صفر
        CASE WHEN r.PBKey >= 999999.0 THEN 0.0
             ELSE COALESCE(1.0 - (2*(r.PBRnk - 1 - (r.NRows - r.PBCnt)) + (r.PBTie - 1)) * 1.0 / NULLIF(2*(r.PBCnt - 1), 0), 0.5) END AS PBRank
    FROM RankDists r
),

Penalized AS (
    SELECT
        r.*,

        -- جریمه‌های رشد (از ۴۰ امتیاز دسته)
        ( 6.0 * CASE WHEN r.SalesGrowth12M IS NOT NULL AND r.SalesGrowth12M < -20 THEN 1 ELSE 0 END
        + 5.0 * CASE WHEN r.OperatingProfitGrowthTTM IS NOT NULL AND r.OperatingProfitGrowthTTM < -25 THEN 1 ELSE 0 END
        ) AS GrowthPenalty,

        -- جریمه‌های سودآوری (از ۲۴ امتیاز دسته)
        ( 10.0 * CASE WHEN r.TTMNetProfit IS NOT NULL AND r.TTMNetProfit < 0 THEN 1 ELSE 0 END
        + 4.0 * CASE WHEN r.InterestCoverage IS NOT NULL AND r.InterestCoverage < 1.5 THEN 1 ELSE 0 END
        + 3.0 * CASE WHEN r.OperatingMarginTrend IS NOT NULL AND r.OperatingMarginTrend < -2 THEN 1 ELSE 0 END
        + CASE
            WHEN r.NonOperatingPct IS NULL THEN 0.0
            WHEN r.NonOperatingPct <= 20 THEN 0.0
            WHEN r.NonOperatingPct >= 100 THEN 8.0
            ELSE (r.NonOperatingPct - 20.0) / 80.0 * 8.0
          END
        ) AS ProfitabilityPenalty,

        -- جریمه‌ی ارزش‌گذاری (از ۱۶ امتیاز دسته)
        ( 8.0 * CASE WHEN r.PEApprox IS NULL OR r.PEApprox <= 0 OR r.PEApprox > 60 THEN 1 ELSE 0 END
        ) AS ValuationPenalty,

        -- v3.4: جریمه‌ی کهنگی از دسته‌ی بازار حذف شد — همین ریسک در ضریب
        -- DataQualityScore (تازگی گزارش/قیمت) اعمال می‌شود و دوبار جریمه نوفه می‌ساخت
        0.0 AS MarketPenalty
    FROM Ranked r
)

SELECT
    CompanyID,
    Symbol,
    CompanyName,

    LatestSalesReportDate,
    LatestProfitReportDate,
    LatestMarketDate,

    SalesReportCount,
    ProfitReportCount,
    MarketDaysCount,

    ROUND(SalesLast12M, 2) AS SalesLast12M,
    ROUND(SalesPrev12M, 2) AS SalesPrev12M,
    ROUND(SalesGrowth12M, 2) AS SalesGrowth12M,
    ROUND(SalesGrowth3M, 2) AS SalesGrowth3M,
    ROUND(SalesStability, 4) AS SalesStability,

    ROUND(TTMEPS, 2) AS LatestEPS,
    ROUND(TTMOperatingEPS, 2) AS LatestOperatingEPS,
    ROUND(LatestOpAbs, 2) AS LatestOperatingProfit,
    ROUND(LatestOpLYAbs, 2) AS LatestOperatingProfitLastYear,
    -- نمایش رشدها با کراپ (رتبه‌بندی جداگانه کراپ شده؛ این فقط برای نمایش تمیز است)
    ROUND(CASE WHEN NetProfitGrowthTTM > 1000 THEN 1000.0
               WHEN NetProfitGrowthTTM < -100 THEN -100.0
               ELSE NetProfitGrowthTTM END, 2) AS NetProfitGrowth4Reports,
    ROUND(CASE WHEN OperatingProfitGrowthTTM > 1000 THEN 1000.0
               WHEN OperatingProfitGrowthTTM < -100 THEN -100.0
               ELSE OperatingProfitGrowthTTM END, 2) AS OperatingProfitGrowthYoY,
    ROUND(CASE WHEN OperatingProfitGrowthTTM > 1000 THEN 1000.0
               WHEN OperatingProfitGrowthTTM < -100 THEN -100.0
               ELSE OperatingProfitGrowthTTM END, 2) AS OperatingProfitGrowth4Reports,

    ROUND(LatestPrice, 2) AS LatestPrice,
    ROUND(LatestClosingPrice, 2) AS LatestClosingPrice,
    ROUND(PEApprox, 2) AS PEApprox,

    ROUND(PriceReturn7D, 2) AS PriceReturn7D,
    ROUND(PriceReturn30D, 2) AS PriceReturn30D,
    ROUND(PriceReturn90D, 2) AS PriceReturn90D,

    ROUND(AvgTradeValue30D, 2) AS AvgTradeValue30D,
    ROUND(AvgVolume30D, 2) AS AvgVolume30D,
    ROUND(AvgTradeCount30D, 2) AS AvgTradeCount30D,
    ROUND(Volatility30D, 4) AS Volatility30D,
    ROUND(PricePosition90D, 2) AS PricePosition90D,

    ROUND(DataQualityScore, 4) AS DataQualityScore,

    CAST(
        CASE
            WHEN ISNULL(SalesReportCount, 0) >= 12
             AND ISNULL(ProfitReportCount, 0) >= 1
             AND ISNULL(MarketDaysCount, 0) >= 30
             AND LatestPrice IS NOT NULL
                THEN 1
            ELSE 0
        END
    AS BIT) AS HasEnoughData,

    CAST(
        CASE
            WHEN PEApprox IS NULL OR PEApprox <= 0 OR PEApprox > 60 THEN 1
            ELSE 0
        END
    AS BIT) AS BadPEFlag,

    CAST(
        CASE
            WHEN SalesGrowth12M IS NOT NULL AND SalesGrowth12M < -20 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakSalesFlag,

    CAST(
        CASE
            WHEN OperatingProfitGrowthTTM IS NOT NULL AND OperatingProfitGrowthTTM < -25 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakOperatingProfitFlag,

    CAST(
        CASE
            WHEN AvgTradeValue30D IS NULL OR AvgTradeValue30D <= 0 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakLiquidityFlag,

    CAST(
        CASE
            WHEN TTMNetProfit IS NOT NULL AND TTMNetProfit < 0 THEN 1
            ELSE 0
        END
    AS BIT) AS LossMakerFlag,

    CAST(
        CASE
            WHEN InterestCoverage IS NOT NULL AND InterestCoverage < 1.5 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakCoverageFlag,

    CAST(
        CASE
            WHEN OperatingMarginTrend IS NOT NULL AND OperatingMarginTrend < -2 THEN 1
            ELSE 0
        END
    AS BIT) AS MarginContractionFlag,

    ROUND(NetProfitMargin12M, 2) AS NetProfitMargin12M,
    ROUND(OperatingMargin12M, 2) AS OperatingMargin12M,
    ROUND(OperatingMarginTrend, 2) AS OperatingMarginTrend,

    -- P/S = P/E × حاشیه خالص (هم‌ارزی بدون واحد؛ فقط با داده‌ی معتبر و سقف ۱۰۰)
    ROUND(
        CASE WHEN PEApprox IS NOT NULL AND PEApprox > 0 AND PEApprox <= 60
              AND NetProfitMargin12M IS NOT NULL AND NetProfitMargin12M > 0
              AND PEApprox * (NetProfitMargin12M / 100.0) <= 100.0
            THEN PEApprox * (NetProfitMargin12M / 100.0)
            ELSE NULL END
    , 2) AS PSRatio,

    ROUND(OperatingMarginLatest, 2) AS OperatingMarginLatest,
    ROUND(NetMarginLatest, 2) AS NetMarginLatest,
    ROUND(CASE WHEN RevenueGrowthYoY > 1000 THEN 1000.0
               WHEN RevenueGrowthYoY < -100 THEN -100.0
               ELSE RevenueGrowthYoY END, 2) AS RevenueGrowthYoY,
    ROUND(InterestCoverage, 2) AS InterestCoverage,
    ROUND(NonOperatingPct, 2) AS NonOperatingPct,

    -- فاکتورهای v3.2 (ترازنامه و جریان نقدی)
    ROUND(ROE, 2) AS ROE,
    ROUND(FinancialLeverage, 2) AS FinancialLeverage,
    ROUND(CurrentRatio, 2) AS CurrentRatio,
    ROUND(CashConversion, 3) AS CashConversion,
    ROUND(CASE WHEN PEApprox IS NOT NULL AND PEApprox > 0 AND PEApprox <= 60
              AND ROE IS NOT NULL AND ROE > 0
              AND PEApprox * ROE / 100.0 <= 30.0
            THEN PEApprox * ROE / 100.0 ELSE NULL END, 2) AS PBRatio,

    -- ----------------------------------------------------------------------
    --  زیرامتیاز دسته‌ها (وزن × رتبه − جریمه، با کف صفر) — وزن‌های v3.5
    --  (رشد/ارزش/بازار از بک‌تست فاز ۱؛ فاکتورهای v3.2 از فاز ۲)
    --
    --  رشد ۳۶:    فروش سالانه 10 | فروش ۳ماهه 6 | درآمد 5 | عملیاتی 5 | خالص 10
    --  سودآوری ۲۶: حاشیه عملیاتی 4 | حاشیه خالص 4 | ROE 6 | روند حاشیه 3 | پوشش بهره 3 | کیفیت نقدی 2 | کیفیت سود 4
    --  ارزش‌گذاری ۱۶: P/E 11 | P/S 3 | P/B 2
    --  بازار ۱۷:  نقدشوندگی 6 | اهرم 2 | نسبت جاری 2 | ثبات فروش 1 | نوسان کم 5 | مومنتوم 1
    --
    --  QuantScore = DataQualityScore × مجموع چهار دسته (سازگار با تجزیه‌وتحلیل فرانت)
    -- ----------------------------------------------------------------------
    -- امتیاز خام هر دسته = مجموع (وزن × رتبه)؛ وزن‌ها بر حسب امتیازند
    -- رشد: 10+6+5+5+10=36 | سودآوری: 4+4+6+3+3+2+4=26 | ارزش: 11+3+2=16 | بازار: 6+2+2+1+5+1=17
    ROUND(
        CASE WHEN (10.0*SalesGrowthRank + 6.0*SalesGrowth3MRank + 5.0*RevenueGrowthRank
                   + 5.0*OperatingProfitGrowthRank + 10.0*NetProfitGrowthRank) - GrowthPenalty < 0
             THEN 0
             ELSE (10.0*SalesGrowthRank + 6.0*SalesGrowth3MRank + 5.0*RevenueGrowthRank
                   + 5.0*OperatingProfitGrowthRank + 10.0*NetProfitGrowthRank) - GrowthPenalty
        END, 1) AS GrowthScore,

    ROUND(
        CASE WHEN (4.0*OperatingMarginRank + 4.0*NetMarginRank + 6.0*ROERank + 3.0*MarginTrendRank
                   + 3.0*InterestCoverageRank + 2.0*CashConversionRank + 4.0*EarningsQualityRank) - ProfitabilityPenalty < 0
             THEN 0
             ELSE (4.0*OperatingMarginRank + 4.0*NetMarginRank + 6.0*ROERank + 3.0*MarginTrendRank
                   + 3.0*InterestCoverageRank + 2.0*CashConversionRank + 4.0*EarningsQualityRank) - ProfitabilityPenalty
        END, 1) AS ProfitabilityScore,

    ROUND(
        CASE WHEN (11.0*PERank + 3.0*PSRank + 2.0*PBRank) - ValuationPenalty < 0
             THEN 0
             ELSE (11.0*PERank + 3.0*PSRank + 2.0*PBRank) - ValuationPenalty
        END, 1) AS ValuationScore,

    ROUND(
        CASE WHEN (6.0*LiquidityRank + 2.0*LeverageRank + 2.0*CurrentRatioRank + 1.0*StabilityRank
                   + 5.0*LowVolatilityRank + 1.0*MomentumRank) - MarketPenalty < 0
             THEN 0
             ELSE (6.0*LiquidityRank + 2.0*LeverageRank + 2.0*CurrentRatioRank + 1.0*StabilityRank
                   + 5.0*LowVolatilityRank + 1.0*MomentumRank) - MarketPenalty
        END, 1) AS MarketScore,

    ROUND(
        DataQualityScore * (
            CASE WHEN (10.0*SalesGrowthRank + 6.0*SalesGrowth3MRank + 5.0*RevenueGrowthRank
                       + 5.0*OperatingProfitGrowthRank + 10.0*NetProfitGrowthRank) - GrowthPenalty < 0
                 THEN 0
                 ELSE (10.0*SalesGrowthRank + 6.0*SalesGrowth3MRank + 5.0*RevenueGrowthRank
                       + 5.0*OperatingProfitGrowthRank + 10.0*NetProfitGrowthRank) - GrowthPenalty
            END
            + CASE WHEN (4.0*OperatingMarginRank + 4.0*NetMarginRank + 6.0*ROERank + 3.0*MarginTrendRank
                         + 3.0*InterestCoverageRank + 2.0*CashConversionRank + 4.0*EarningsQualityRank) - ProfitabilityPenalty < 0
                 THEN 0
                 ELSE (4.0*OperatingMarginRank + 4.0*NetMarginRank + 6.0*ROERank + 3.0*MarginTrendRank
                       + 3.0*InterestCoverageRank + 2.0*CashConversionRank + 4.0*EarningsQualityRank) - ProfitabilityPenalty
              END
            + CASE WHEN (11.0*PERank + 3.0*PSRank + 2.0*PBRank) - ValuationPenalty < 0
                 THEN 0
                 ELSE (11.0*PERank + 3.0*PSRank + 2.0*PBRank) - ValuationPenalty
              END
            + CASE WHEN (6.0*LiquidityRank + 2.0*LeverageRank + 2.0*CurrentRatioRank + 1.0*StabilityRank
                         + 5.0*LowVolatilityRank + 1.0*MomentumRank) - MarketPenalty < 0
                 THEN 0
                 ELSE (6.0*LiquidityRank + 2.0*LeverageRank + 2.0*CurrentRatioRank + 1.0*StabilityRank
                       + 5.0*LowVolatilityRank + 1.0*MomentumRank) - MarketPenalty
              END
        ), 2) AS QuantScore,

    -- ----------------------------------------------------------------------
    --  ستون‌های جدید v3 (شفافیت و عیب‌یابی)
    -- ----------------------------------------------------------------------
    ProfitReportAgeMonths,
    MarketDataAgeDays,

    CAST(
        CASE
            WHEN (ProfitReportAgeMonths IS NOT NULL AND ProfitReportAgeMonths > 8)
              OR (MarketDataAgeDays IS NOT NULL AND MarketDataAgeDays > 14)
                THEN 1
            ELSE 0
        END
    AS BIT) AS StaleDataFlag,

    ROUND(GrowthPenalty, 1) AS GrowthPenalty,
    ROUND(ProfitabilityPenalty, 1) AS ProfitabilityPenalty,
    ROUND(ValuationPenalty, 1) AS ValuationPenalty,
    ROUND(MarketPenalty, 1) AS MarketPenalty,

    ROUND(TTMNetProfit, 2) AS TTMNetProfit,
    ROUND(TTMNetProfitP1, 2) AS TTMNetProfitP1,
    ROUND(NPUnitRatio, 8) AS NPUnitRatio,
    ROUND(TTMEPS, 2) AS TTMEPS,

    ROUND(ImpliedShares, 0) AS ImpliedShares,

    N'v3.5' AS ScoreVersion,

    -- ----------------------------------------------------------------------
    --  رتبه‌ی درصدی هر فاکتور بین کل بازار (CUME_DIST؛ برای شفافیت کامل در UI)
    --  عددی بین ۰ و ۱؛ مثلاً ۰.۸۵ یعنی بهتر از ۸۵٪ شرکت‌ها در آن فاکتور.
    --  فاکتور بدونِ داده = ۰.۳۰ (خنثی) | نامعتبر = ~۰ (بدترین)
    -- ----------------------------------------------------------------------
    ROUND(SalesGrowthRank, 4) AS SalesGrowthRank,
    ROUND(SalesGrowth3MRank, 4) AS SalesGrowth3MRank,
    ROUND(RevenueGrowthRank, 4) AS RevenueGrowthRank,
    ROUND(OperatingProfitGrowthRank, 4) AS OperatingProfitGrowthRank,
    ROUND(NetProfitGrowthRank, 4) AS NetProfitGrowthRank,

    ROUND(OperatingMarginRank, 4) AS OperatingMarginRank,
    ROUND(NetMarginRank, 4) AS NetMarginRank,
    ROUND(MarginTrendRank, 4) AS MarginTrendRank,
    ROUND(InterestCoverageRank, 4) AS InterestCoverageRank,
    ROUND(EarningsQualityRank, 4) AS EarningsQualityRank,

    ROUND(PERank, 4) AS PERank,
    ROUND(PSRank, 4) AS PSRank,

    ROUND(LiquidityRank, 4) AS LiquidityRank,
    ROUND(StabilityRank, 4) AS StabilityRank,
    ROUND(LowVolatilityRank, 4) AS LowVolatilityRank,
    ROUND(MomentumRank, 4) AS MomentumRank,

    -- رتبه‌های فاکتورهای v3.2
    ROUND(ROERank, 4) AS ROERank,
    ROUND(LeverageRank, 4) AS LeverageRank,
    ROUND(CurrentRatioRank, 4) AS CurrentRatioRank,
    ROUND(CashConversionRank, 4) AS CashConversionRank,
    ROUND(PBRank, 4) AS PBRank
FROM Penalized;
GO
