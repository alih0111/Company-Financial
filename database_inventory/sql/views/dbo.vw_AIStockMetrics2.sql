

CREATE   VIEW [dbo].[vw_AIStockMetrics2]
AS
WITH CompanyList AS (
    SELECT CompanyID, MAX(CompanyName) AS CompanyName
    FROM (
        SELECT CompanyID, CompanyName FROM dbo.mahane WHERE CompanyID IS NOT NULL
        UNION ALL
        SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyID IS NOT NULL
        UNION ALL
        SELECT CompanyID, CompanyName FROM dbo.MarketPriceHistory WHERE CompanyID IS NOT NULL
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
        TRY_CONVERT(FLOAT, Num4_Value1) AS LatestOperatingEPS,
        TRY_CONVERT(FLOAT, Product1) AS NetProfit,
        TRY_CONVERT(FLOAT, OperatingProfitNew) AS OperatingProfitNew,
        TRY_CONVERT(FLOAT, OperatingProfitLastYear) AS OperatingProfitLastYear
    FROM dbo.miandore2
    WHERE CompanyID IS NOT NULL
      AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
    GROUP BY
        CompanyID,
        ReportDate,
        Num1_Value1,
        Num4_Value1,
        Product1,
        OperatingProfitNew,
        OperatingProfitLastYear
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

        MAX(CASE WHEN rn = 1 THEN OperatingProfitNew END) AS LatestOperatingProfit,
        MAX(CASE WHEN rn = 1 THEN OperatingProfitLastYear END) AS LatestOperatingProfitLastYear,

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
        p.LatestOperatingProfit,
        p.LatestOperatingProfitLastYear,

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
        ) AS HealthyMomentumRank
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

    ROUND(
        100.0 *
        (
            0.22 * SalesGrowthRank +
            0.10 * SalesGrowth3MRank +
            0.20 * OperatingProfitRank +
            0.12 * NetProfitRank +
            0.13 * PERank +
            0.10 * StabilityRank +
            0.08 * LiquidityRank +
            0.03 * LowVolatilityRank +
            0.02 * HealthyMomentumRank
        )
        *
        DataQualityScore
        *
        CASE
            WHEN PEApprox IS NULL OR PEApprox <= 0 OR PEApprox > 80 THEN 0.55
            ELSE 1.0
        END
        *
        CASE
            WHEN SalesGrowth12M IS NOT NULL AND SalesGrowth12M < -20 THEN 0.70
            ELSE 1.0
        END
        *
        CASE
            WHEN OperatingProfitGrowthYoY IS NOT NULL AND OperatingProfitGrowthYoY < -20 THEN 0.70
            ELSE 1.0
        END
    , 2) AS QuantScore
FROM Ranked;
