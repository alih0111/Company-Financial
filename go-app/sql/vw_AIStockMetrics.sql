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
--  vw_AIStockMetrics
--  رتبه‌بندی کمّی شرکت‌های بورسی بر اساس داده‌های ماهانه (فروش) و گزارش‌های
--  فصلی صورت سود و زیان. خروجی اصلی: QuantScore بین 0..100.
--
--  تغییرات نسخه‌ی جدید:
--   1) افزودن 4 فاکتور جدید قابل محاسبه از داده‌ی موجود:
--        - NetProfitMargin12M  : حاشیه سود خالص سالانه
--        - OperatingMargin12M  : حاشیه سود عملیاتی سالانه
--        - OperatingMarginTrend: روند تغییر حاشیه عملیاتی YoY
--        - PSRatio             : نسبت قیمت به فروش سالانه (P/S)
--   2) تبدیل جریمه‌ها از حالت ضربی به جمعی (با کف 0.50)
--        نسخه‌ی قدیمی Україن: 0.55 * 0.70 * 0.70 = 0.27 (بیش از 70% کاهش)
--        نسخه‌ی جدید: 1.00 - (0.15+0.10+0.10+0.15) = 0.50 (حداکثر 50% کاهش)
--   3) افزودن جریمه‌ی «شرکت زیان‌ده» (سود خالص ۴ گزارشه منفی)
--   4) اصلاح وزن‌ها برای ترغیب رشد سود + کیفیت حاشیه
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

ProfitRaw AS (
    SELECT
        CompanyID,
        MAX(CompanyName) AS CompanyName,
        ReportDate,
        dbo.fn_JalaliKey(ReportDate) AS ReportKey,

        TRY_CONVERT(FLOAT, Num1_Value1) AS LatestEPS,
        TRY_CONVERT(FLOAT, Num2_Value1) AS Capital,        -- NEW: تعداد سهم (سرمایه)
        TRY_CONVERT(FLOAT, Num4_Value1) AS LatestOperatingEPS,
        TRY_CONVERT(FLOAT, Product1) AS NetProfit,
        TRY_CONVERT(FLOAT, OperatingProfitNew) AS OperatingProfitNew,
        TRY_CONVERT(FLOAT, OperatingProfitLastYear) AS OperatingProfitLastYear,
        TRY_CONVERT(FLOAT, RevenueNew) AS RevenueNew,
        TRY_CONVERT(FLOAT, RevenueLastYear) AS RevenueLastYear,
        TRY_CONVERT(FLOAT, FinanceCostsNew) AS FinanceCostsNew,
        TRY_CONVERT(FLOAT, OtherNonOpNew) AS OtherNonOpNew
    FROM dbo.miandore2
    WHERE CompanyID IS NOT NULL
      AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
    GROUP BY
        CompanyID,
        ReportDate,
        Num1_Value1,
        Num2_Value1,
        Num4_Value1,
        Product1,
        OperatingProfitNew,
        OperatingProfitLastYear,
        RevenueNew,
        RevenueLastYear,
        FinanceCostsNew,
        OtherNonOpNew
),

ProfitRanked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY CompanyID
            ORDER BY ReportKey DESC
        ) AS rn
    FROM ProfitRaw
),

ProfitAgg AS (
    SELECT
        CompanyID,

        MAX(CASE WHEN rn = 1 THEN CompanyName END) AS CompanyName,
        MAX(CASE WHEN rn = 1 THEN ReportDate END) AS LatestProfitReportDate,
        MAX(CASE WHEN rn = 1 THEN ReportKey END) AS LatestProfitReportKey,

        COUNT(*) AS ProfitReportCount,

        MAX(CASE WHEN rn = 1 THEN LatestEPS END) AS LatestEPS,
        MAX(CASE WHEN rn = 1 THEN LatestOperatingEPS END) AS LatestOperatingEPS,
        MAX(CASE WHEN rn = 1 THEN Capital END) AS LatestCapital,    -- NEW

        MAX(CASE WHEN rn = 1 THEN OperatingProfitNew END) AS LatestOperatingProfit,
        MAX(CASE WHEN rn = 1 THEN OperatingProfitLastYear END) AS LatestOperatingProfitLastYear,

        MAX(CASE WHEN rn = 1 THEN NetProfit END) AS LatestNetProfit,

        MAX(CASE WHEN rn = 1 THEN RevenueNew END) AS LatestRevenue,
        MAX(CASE WHEN rn = 1 THEN RevenueLastYear END) AS LatestRevenueLastYear,
        MAX(CASE WHEN rn = 1 THEN FinanceCostsNew END) AS LatestFinanceCosts,
        MAX(CASE WHEN rn = 1 THEN OtherNonOpNew END) AS LatestOtherNonOp,

        SUM(CASE WHEN rn BETWEEN 1 AND 4 THEN NetProfit ELSE 0 END) AS NetProfitLast4Reports,
        SUM(CASE WHEN rn BETWEEN 5 AND 8 THEN NetProfit ELSE 0 END) AS NetProfitPrev4Reports,

        SUM(CASE WHEN rn BETWEEN 1 AND 4 THEN OperatingProfitNew ELSE 0 END) AS OperatingProfitLast4Reports,
        SUM(CASE WHEN rn BETWEEN 5 AND 8 THEN OperatingProfitNew ELSE 0 END) AS OperatingProfitPrev4Reports
    FROM ProfitRanked
    GROUP BY CompanyID
),

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

BaseMetrics AS (
    SELECT
        c.CompanyID,
        COALESCE(m.Symbol, N'') AS Symbol,
        COALESCE(c.CompanyName, s.CompanyName, p.CompanyName, m.CompanyName) AS CompanyName,

        s.LatestSalesReportDate,
        p.LatestProfitReportDate,
        m.LatestMarketDate,

        ISNULL(s.SalesReportCount, 0) AS SalesReportCount,
        ISNULL(p.ProfitReportCount, 0) AS ProfitReportCount,
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

        p.LatestEPS,
        p.LatestOperatingEPS,
        p.LatestCapital,                       -- NEW
        p.LatestOperatingProfit,
        p.LatestOperatingProfitLastYear,

        p.LatestNetProfit,
        p.LatestRevenue,
        p.LatestRevenueLastYear,
        p.LatestFinanceCosts,
        p.LatestOtherNonOp,

        p.NetProfitLast4Reports,
        p.NetProfitPrev4Reports,

        CASE
            WHEN p.NetProfitPrev4Reports IS NOT NULL AND ABS(p.NetProfitPrev4Reports) > 0
                THEN ((p.NetProfitLast4Reports - p.NetProfitPrev4Reports) / ABS(p.NetProfitPrev4Reports)) * 100.0
            ELSE NULL
        END AS NetProfitGrowth4Reports,

        CASE
            WHEN p.LatestOperatingProfitLastYear IS NOT NULL AND ABS(p.LatestOperatingProfitLastYear) > 0
                THEN ((p.LatestOperatingProfit - p.LatestOperatingProfitLastYear) / ABS(p.LatestOperatingProfitLastYear)) * 100.0
            ELSE NULL
        END AS OperatingProfitGrowthYoY,

        CASE
            WHEN p.OperatingProfitPrev4Reports IS NOT NULL AND ABS(p.OperatingProfitPrev4Reports) > 0
                THEN ((p.OperatingProfitLast4Reports - p.OperatingProfitPrev4Reports) / ABS(p.OperatingProfitPrev4Reports)) * 100.0
            ELSE NULL
        END AS OperatingProfitGrowth4Reports,

        -- NEW: حاشیه‌ی سود خالص سالانه
        --     سود خالص 4 گزارش فصلی (معادل 12 ماه) تقسیم بر فروش 12 ماه
        CASE
            WHEN p.NetProfitLast4Reports IS NOT NULL
             AND s.SalesLast12M IS NOT NULL
             AND ABS(s.SalesLast12M) > 0
                THEN (p.NetProfitLast4Reports / ABS(s.SalesLast12M)) * 100.0
            ELSE NULL
        END AS NetProfitMargin12M,

        -- NEW: حاشیه‌ی سود عملیاتی سالانه
        CASE
            WHEN p.OperatingProfitLast4Reports IS NOT NULL
             AND s.SalesLast12M IS NOT NULL
             AND ABS(s.SalesLast12M) > 0
                THEN (p.OperatingProfitLast4Reports / ABS(s.SalesLast12M)) * 100.0
            ELSE NULL
        END AS OperatingMargin12M,

        -- NEW: حاشیه‌ی سود عملیاتی سال قبل (برای روند)
        CASE
            WHEN p.OperatingProfitPrev4Reports IS NOT NULL
             AND s.SalesPrev12M IS NOT NULL
             AND ABS(s.SalesPrev12M) > 0
                THEN (p.OperatingProfitPrev4Reports / ABS(s.SalesPrev12M)) * 100.0
            ELSE NULL
        END AS OperatingMarginPrev12M,

        -- روند تغییر حاشیه‌ی عملیاتی YoY (دقیق، از داده‌ی هم‌منبع)
        -- اولویت ۱: هم صورت و هم مخرج از یک گزارش (OperatingProfit + Revenue)
        -- اولویت ۲: fallback به روش قدیمی (12M aggregation)
        COALESCE(
            CASE
                WHEN p.LatestOperatingProfit IS NOT NULL
                 AND p.LatestOperatingProfitLastYear IS NOT NULL
                 AND p.LatestRevenue IS NOT NULL
                 AND p.LatestRevenueLastYear IS NOT NULL
                 AND ABS(p.LatestRevenue) > 0
                 AND ABS(p.LatestRevenueLastYear) > 0
                    THEN (p.LatestOperatingProfit / ABS(p.LatestRevenue)) * 100.0
                         - (p.LatestOperatingProfitLastYear / ABS(p.LatestRevenueLastYear)) * 100.0
                ELSE NULL
            END,
            CASE
                WHEN p.OperatingProfitLast4Reports IS NOT NULL
                 AND p.OperatingProfitPrev4Reports IS NOT NULL
                 AND s.SalesLast12M IS NOT NULL
                 AND s.SalesPrev12M IS NOT NULL
                 AND ABS(s.SalesLast12M) > 0
                 AND ABS(s.SalesPrev12M) > 0
                    THEN
                        (p.OperatingProfitLast4Reports / ABS(s.SalesLast12M)) * 100.0
                        -
                        (p.OperatingProfitPrev4Reports / ABS(s.SalesPrev12M)) * 100.0
                ELSE NULL
            END
        ) AS OperatingMarginTrend,

        -- حاشیه‌ی سود عملیاتی (دقیق، از آخرین گزارش — هم‌منبع)
        CASE
            WHEN p.LatestOperatingProfit IS NOT NULL
             AND p.LatestRevenue IS NOT NULL
             AND ABS(p.LatestRevenue) > 0
                THEN (p.LatestOperatingProfit / ABS(p.LatestRevenue)) * 100.0
            ELSE NULL
        END AS OperatingMarginLatest,

        -- حاشیه‌ی سود خالص (دقیق، از آخرین گزارش — هم‌منبع)
        CASE
            WHEN p.LatestNetProfit IS NOT NULL
             AND p.LatestRevenue IS NOT NULL
             AND ABS(p.LatestRevenue) > 0
                THEN (p.LatestNetProfit / ABS(p.LatestRevenue)) * 100.0
            ELSE NULL
        END AS NetMarginLatest,

        -- رشد درآمد YoY (دقیق، از صورت سود و زیان)
        CASE
            WHEN p.LatestRevenue IS NOT NULL
             AND p.LatestRevenueLastYear IS NOT NULL
             AND ABS(p.LatestRevenueLastYear) > 0
                THEN ((p.LatestRevenue - p.LatestRevenueLastYear) / ABS(p.LatestRevenueLastYear)) * 100.0
            ELSE NULL
        END AS RevenueGrowthYoY,

        -- نسبت پوشش هزینه مالی (Interest Coverage)
        -- OperatingProfit / |FinanceCosts| — توان پرداخت بهره از سود عملیاتی
        -- زیر ۱.۵ = هشدار، زیر ۱ = بحرانی
        CASE
            WHEN p.LatestOperatingProfit IS NOT NULL
             AND p.LatestFinanceCosts IS NOT NULL
             AND ABS(p.LatestFinanceCosts) > 0
                THEN p.LatestOperatingProfit / ABS(p.LatestFinanceCosts)
            ELSE NULL
        END AS InterestCoverage,

        -- سهم درآمد غیرعملیاتی از سود عملیاتی (درصد)
        -- (سایر درآمدها و هزینه‌های غیرعملیاتی) / سود عملیاتی × ۱۰۰
        -- مثلاً اگه شرکت زمین فروخته باشه، این عدد بالا می‌شه
        -- عدد پایین/نزدیک صفر = سود باکیفیت (از فعالیت اصلی)
        -- عدد بالا = سود وابسته به منابع یکبار/غیرعملیاتی
        CASE
            WHEN p.LatestOtherNonOp IS NOT NULL
             AND p.LatestOperatingProfit IS NOT NULL
             AND ABS(p.LatestOperatingProfit) > 0
                THEN (p.LatestOtherNonOp / ABS(p.LatestOperatingProfit)) * 100.0
            ELSE NULL
        END AS NonOperatingPct,

        -- NEW: نسبت قیمت به فروش سالانه (P/S)
        --     MarketCap / SalesLast12M = (LatestPrice * LatestCapital) / SalesLast12M
        --     یک شرکت سودآور ولی کم‌ارزش می‌تونه P/S پایین داشته باشه.
        CASE
            WHEN m.LatestPrice IS NOT NULL
             AND p.LatestCapital IS NOT NULL
             AND p.LatestCapital > 0
             AND s.SalesLast12M IS NOT NULL
             AND ABS(s.SalesLast12M) > 0
                THEN (m.LatestPrice * p.LatestCapital) / ABS(s.SalesLast12M)
            ELSE NULL
        END AS PSRatio,

        m.LatestPrice,
        m.LatestClosingPrice,

        CASE
            WHEN p.LatestEPS IS NOT NULL AND p.LatestEPS > 0 AND m.LatestPrice IS NOT NULL
                THEN m.LatestPrice / p.LatestEPS
            ELSE NULL
        END AS PEApprox,

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

        (
            CASE
                WHEN ISNULL(s.SalesReportCount, 0) >= 24 THEN 0.35
                WHEN ISNULL(s.SalesReportCount, 0) >= 12 THEN 0.25
                WHEN ISNULL(s.SalesReportCount, 0) >= 6 THEN 0.12
                ELSE 0
            END
            +
            CASE
                WHEN ISNULL(p.ProfitReportCount, 0) >= 8 THEN 0.30
                WHEN ISNULL(p.ProfitReportCount, 0) >= 4 THEN 0.20
                WHEN ISNULL(p.ProfitReportCount, 0) >= 1 THEN 0.10
                ELSE 0
            END
            +
            CASE
                WHEN ISNULL(m.MarketDaysCount, 0) >= 90 THEN 0.25
                WHEN ISNULL(m.MarketDaysCount, 0) >= 30 THEN 0.18
                WHEN ISNULL(m.MarketDaysCount, 0) >= 10 THEN 0.08
                ELSE 0
            END
            +
            CASE
                WHEN m.LatestPrice IS NOT NULL AND m.LatestPrice > 0 THEN 0.10
                ELSE 0
            END
        ) AS DataQualityScore
    FROM CompanyList c
    LEFT JOIN SalesAgg s ON s.CompanyID = c.CompanyID
    LEFT JOIN ProfitAgg p ON p.CompanyID = c.CompanyID
    LEFT JOIN MarketAgg m ON m.CompanyID = c.CompanyID
),

Ranked AS (
    SELECT
        b.*,

        CUME_DIST() OVER (ORDER BY ISNULL(b.SalesGrowth12M, -999999.0)) AS SalesGrowthRank,
        CUME_DIST() OVER (ORDER BY ISNULL(b.SalesGrowth3M, -999999.0)) AS SalesGrowth3MRank,
        CUME_DIST() OVER (ORDER BY ISNULL(b.OperatingProfitGrowthYoY, -999999.0)) AS OperatingProfitRank,
        CUME_DIST() OVER (ORDER BY ISNULL(b.NetProfitGrowth4Reports, -999999.0)) AS NetProfitRank,
        CUME_DIST() OVER (ORDER BY ISNULL(b.SalesStability, -999999.0)) AS StabilityRank,
        CUME_DIST() OVER (ORDER BY ISNULL(b.AvgTradeValue30D, 0.0)) AS LiquidityRank,

        1.0 - CUME_DIST() OVER (
            ORDER BY
                CASE
                    WHEN b.PEApprox IS NOT NULL AND b.PEApprox > 0 AND b.PEApprox < 80
                        THEN b.PEApprox
                    ELSE 999999.0
                END
        ) AS PERank,

        1.0 - CUME_DIST() OVER (
            ORDER BY ISNULL(b.Volatility30D, 999999.0)
        ) AS LowVolatilityRank,

        CUME_DIST() OVER (
            ORDER BY
                CASE
                    WHEN b.PriceReturn30D BETWEEN -15 AND 35 THEN b.PriceReturn30D
                    ELSE -999999.0
                END
        ) AS HealthyMomentumRank,

        -- NEW: رتبه‌بندی بر اساس حاشیه سود خالص (بالا = بهتر)
        CUME_DIST() OVER (ORDER BY ISNULL(b.NetProfitMargin12M, -999999.0)) AS NetMarginRank,

        -- NEW: رتبه‌بندی بر اساس روند تغییر حاشیه (مثبت/روبه‌بالا = بهتر)
        CUME_DIST() OVER (ORDER BY ISNULL(b.OperatingMarginTrend, -999999.0)) AS MarginTrendRank,

        -- NEW: رتبه‌بندی P/S (پایین = ارزان = بهتر)
        1.0 - CUME_DIST() OVER (
            ORDER BY
                CASE
                    WHEN b.PSRatio IS NOT NULL AND b.PSRatio > 0 AND b.PSRatio < 100
                        THEN b.PSRatio
                    ELSE 999999.0
                END
        ) AS PSRank,

        -- NEW v2: رتبه‌بندی بر اساس حاشیه عملیاتی دقیق (هم‌منبع از آخرین گزارش)
        CUME_DIST() OVER (ORDER BY ISNULL(b.OperatingMarginLatest, -999999.0)) AS OperatingMarginLatestRank,

        -- NEW v2: رتبه‌بندی بر اساس رشد درآمد دقیق YoY
        CUME_DIST() OVER (ORDER BY ISNULL(b.RevenueGrowthYoY, -999999.0)) AS RevenueGrowthRank,

        -- NEW v2: رتبه‌بندی بر اساس پوشش بهره (بالا = ایمن = بهتر)
        CUME_DIST() OVER (
            ORDER BY
                CASE
                    WHEN b.InterestCoverage IS NOT NULL AND b.InterestCoverage > 0 AND b.InterestCoverage < 100
                        THEN b.InterestCoverage
                    ELSE -999999.0
                END
        ) AS InterestCoverageRank,

        -- NEW v2: کیفیت سود — هرچه سهم غیرعملیاتی کمتر = سود پایدارتر = بهتر
        -- رتبه‌بندی معکوس: NonOperatingPct پایین = بهتر = رتبه بالا
        1.0 - CUME_DIST() OVER (ORDER BY ISNULL(b.NonOperatingPct, 999999.0)) AS EarningsQualityRank
    FROM BaseMetrics b
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

    ROUND(LatestEPS, 2) AS LatestEPS,
    ROUND(LatestOperatingEPS, 2) AS LatestOperatingEPS,
    ROUND(LatestOperatingProfit, 2) AS LatestOperatingProfit,
    ROUND(LatestOperatingProfitLastYear, 2) AS LatestOperatingProfitLastYear,
    ROUND(NetProfitGrowth4Reports, 2) AS NetProfitGrowth4Reports,
    ROUND(OperatingProfitGrowthYoY, 2) AS OperatingProfitGrowthYoY,
    ROUND(OperatingProfitGrowth4Reports, 2) AS OperatingProfitGrowth4Reports,

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
            WHEN PEApprox IS NULL OR PEApprox <= 0 OR PEApprox > 80 THEN 1
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
            WHEN OperatingProfitGrowthYoY IS NOT NULL AND OperatingProfitGrowthYoY < -20 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakOperatingProfitFlag,

    CAST(
        CASE
            WHEN AvgTradeValue30D IS NULL OR AvgTradeValue30D <= 0 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakLiquidityFlag,

    -- NEW: ستون‌های جدید - در انتهای SELECT برای حفظ سازگاری با کد Go
    ROUND(NetProfitMargin12M, 2) AS NetProfitMargin12M,
    ROUND(OperatingMargin12M, 2) AS OperatingMargin12M,
    ROUND(OperatingMarginTrend, 2) AS OperatingMarginTrend,
    ROUND(PSRatio, 2) AS PSRatio,

    -- NEW v2: معیارهای دقیق از داده‌ی هم‌منبع (RevenueNew از همان گزارش)
    ROUND(OperatingMarginLatest, 2) AS OperatingMarginLatest,
    ROUND(NetMarginLatest, 2) AS NetMarginLatest,
    ROUND(RevenueGrowthYoY, 2) AS RevenueGrowthYoY,
    ROUND(InterestCoverage, 2) AS InterestCoverage,
    ROUND(NonOperatingPct, 2) AS NonOperatingPct,

    CAST(
        CASE
            WHEN NetProfitLast4Reports IS NULL OR NetProfitLast4Reports < 0 THEN 1
            ELSE 0
        END
    AS BIT) AS LossMakerFlag,

    -- NEW v2: پرچم پوشش بهره ضعیف (Interest Coverage < 1.5)
    -- یعنی سود عملیاتی به‌سختی هزینه مالی رو پوشش می‌ده
    CAST(
        CASE
            WHEN InterestCoverage IS NOT NULL AND InterestCoverage < 1.5 THEN 1
            ELSE 0
        END
    AS BIT) AS WeakCoverageFlag,

    -- NEW v2: پرچم انقباض حاشیه عملیاتی (حاشیه امسال < سال قبل)
    -- نشانه‌ی کاهش بهره‌وری
    CAST(
        CASE
            WHEN OperatingMarginTrend IS NOT NULL AND OperatingMarginTrend < -2 THEN 1
            ELSE 0
        END
    AS BIT) AS MarginContractionFlag,

    -- ----------------------------------------------------------------------
    --  QuantScore نهایی (نسخه‌ی v2 با استفاده از دیتای هم‌منبع)
    --
    --  محاسبه‌ی وزن رتبه‌ها (مجموع وزن‌ها = 1.00):
    --
    --   0.11  SalesGrowthRank         رشد فروش سالانه
    --   0.05  SalesGrowth3MRank        رشد فروش 3 ماهه
    --   0.09  RevenueGrowthRank        رشد درآمد دقیق YoY
    --   0.11  OperatingProfitRank      رشد سود عملیاتی YoY
    --   0.07  NetProfitRank            رشد سود خالص 4 گزارش
    --   0.07  OperatingMarginLatestRank حاشیه عملیاتی دقیق
    --   0.05  NetMarginRank            حاشیه سود خالص 12M
    --   0.05  MarginTrendRank          روند تغییر حاشیه
    --   0.05  InterestCoverageRank     پوشش بهره
    --   0.06  EarningsQualityRank      کیفیت سود (سهم غیرعملیاتی)  (NEW v2)
    --   0.09  PERank                   ارزانی P/E
    --   0.04  PSRank                   ارزانی P/S
    --   0.06  StabilityRank            ثبات فروش
    --   0.06  LiquidityRank            نقدشوندگی
    --   0.02  LowVolatilityRank        نوسان پایین
    --   0.02  HealthyMomentumRank      مومنتوم قیمت
    --   -----  + ----------
    --   1.00
    --
    --  جریمه‌ها (جمعی، با کف 0.50):
    --   -15%  اگر P/E نامعتبر (NULL، <=0 یا >80)
    --   -10%  اگر رشد فروش سالانه < -20%
    --   -10%  اگر رشد سود عملیاتی YoY < -20%
    --   -15%  اگر شرکت زیان‌ده (سود خالص 4 گزارشه منفی)
    --   -08%  اگر پوشش بهره ضعیف (< 1.5)
    --   -05%  اگر انقباض حاشیه عملیاتی (> -2%)
    --   -08%  اگر سهم غیرعملیاتی بالا (> 30%)                 (NEW v2)
    -- ----------------------------------------------------------------------
    ROUND(
        100.0 *
        (
            0.11 * SalesGrowthRank
            + 0.05 * SalesGrowth3MRank
            + 0.09 * RevenueGrowthRank
            + 0.11 * OperatingProfitRank
            + 0.07 * NetProfitRank
            + 0.07 * OperatingMarginLatestRank
            + 0.05 * NetMarginRank
            + 0.05 * MarginTrendRank
            + 0.05 * InterestCoverageRank
            + 0.06 * EarningsQualityRank
            + 0.09 * PERank
            + 0.04 * PSRank
            + 0.06 * StabilityRank
            + 0.06 * LiquidityRank
            + 0.02 * LowVolatilityRank
            + 0.02 * HealthyMomentumRank
        )
        * DataQualityScore
        * (
            1.0
            - 0.15 * CASE WHEN PEApprox IS NULL OR PEApprox <= 0 OR PEApprox > 80 THEN 1 ELSE 0 END
            - 0.10 * CASE WHEN SalesGrowth12M IS NOT NULL AND SalesGrowth12M < -20 THEN 1 ELSE 0 END
            - 0.10 * CASE WHEN OperatingProfitGrowthYoY IS NOT NULL AND OperatingProfitGrowthYoY < -20 THEN 1 ELSE 0 END
            - 0.15 * CASE WHEN NetProfitLast4Reports IS NULL OR NetProfitLast4Reports < 0 THEN 1 ELSE 0 END
            - 0.08 * CASE WHEN InterestCoverage IS NOT NULL AND InterestCoverage < 1.5 THEN 1 ELSE 0 END
            - 0.05 * CASE WHEN OperatingMarginTrend IS NOT NULL AND OperatingMarginTrend < -2 THEN 1 ELSE 0 END
            - 0.08 * CASE WHEN NonOperatingPct IS NOT NULL AND NonOperatingPct > 30 THEN 1 ELSE 0 END
        )
    , 2) AS QuantScore
FROM Ranked;
GO