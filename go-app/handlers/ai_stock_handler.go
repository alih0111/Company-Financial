package handlers

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"go-app/config"
	"go-app/integration"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

func nfloat(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}

func nstring(n sql.NullString) string {
	if n.Valid {
		return n.String
	}
	return ""
}

func nbool(n sql.NullBool) bool {
	return n.Valid && n.Bool
}

func nullInt64(n sql.NullInt64) int64 {
	if n.Valid {
		return n.Int64
	}
	return 0
}

func parseIntQuery(c *gin.Context, key string, fallback int) int {
	raw := strings.TrimSpace(c.Query(key))
	if raw == "" {
		return fallback
	}

	v, err := strconv.Atoi(raw)
	if err != nil || v <= 0 {
		return fallback
	}

	return v
}

func parseFloatQuery(c *gin.Context, key string, fallback float64) float64 {
	raw := strings.TrimSpace(c.Query(key))
	if raw == "" {
		return fallback
	}

	v, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return fallback
	}

	return v
}

func scanAIStockMetric(rows *sql.Rows) (models.AIStockMetric, error) {
	var r models.AIStockMetric

	var symbol sql.NullString
	var companyName sql.NullString

	var latestSalesReportDate sql.NullString
	var latestProfitReportDate sql.NullString
	var latestMarketDate sql.NullString

	var quantScore sql.NullFloat64
	var dataQualityScore sql.NullFloat64

	var salesGrowth12M sql.NullFloat64
	var salesGrowth3M sql.NullFloat64
	var salesStability sql.NullFloat64

	var operatingProfitGrowthYoY sql.NullFloat64
	var operatingProfitGrowth4Reports sql.NullFloat64
	var netProfitGrowth4Reports sql.NullFloat64

	// معیارهای دقیق هم‌منبع از آخرین گزارش
	var operatingMarginLatest sql.NullFloat64
	var netMarginLatest sql.NullFloat64
	var revenueGrowthYoY sql.NullFloat64
	var interestCoverage sql.NullFloat64
	var nonOperatingPct sql.NullFloat64

	// معیارهای ۱۲ ماهه (fallback)
	var netProfitMargin12M sql.NullFloat64
	var operatingMargin12M sql.NullFloat64
	var operatingMarginTrend sql.NullFloat64
	var psRatio sql.NullFloat64

	var latestEPS sql.NullFloat64
	var latestOperatingEPS sql.NullFloat64
	var latestPrice sql.NullFloat64
	var peApprox sql.NullFloat64

	var priceReturn7D sql.NullFloat64
	var priceReturn30D sql.NullFloat64
	var priceReturn90D sql.NullFloat64

	var avgTradeValue30D sql.NullFloat64
	var avgVolume30D sql.NullFloat64
	var volatility30D sql.NullFloat64
	var pricePosition90D sql.NullFloat64

	var hasEnoughData sql.NullBool
	var badPEFlag sql.NullBool
	var weakSalesFlag sql.NullBool
	var weakOperatingProfitFlag sql.NullBool
	var weakLiquidityFlag sql.NullBool
	var lossMakerFlag sql.NullBool
	var weakCoverageFlag sql.NullBool
	var marginContractionFlag sql.NullBool

	var growthScore sql.NullFloat64
	var profitabilityScore sql.NullFloat64
	var valuationScore sql.NullFloat64
	var marketScore sql.NullFloat64

	// ستون‌های شفافیت v3
	var growthPenalty sql.NullFloat64
	var profitabilityPenalty sql.NullFloat64
	var valuationPenalty sql.NullFloat64
	var marketPenalty sql.NullFloat64
	var profitReportAgeMonths sql.NullInt64
	var marketDataAgeDays sql.NullInt64
	var staleDataFlag sql.NullBool
	var ttmNetProfit sql.NullFloat64
	var ttmEPS sql.NullFloat64
	var scoreVersion sql.NullString

	// رتبه‌ی درصدی فاکتورها (شفافیت v3)
	var salesGrowthRank sql.NullFloat64
	var salesGrowth3MRank sql.NullFloat64
	var revenueGrowthRank sql.NullFloat64
	var operatingProfitGrowthRank sql.NullFloat64
	var netProfitGrowthRank sql.NullFloat64
	var operatingMarginRank sql.NullFloat64
	var netMarginRank sql.NullFloat64
	var marginTrendRank sql.NullFloat64
	var interestCoverageRank sql.NullFloat64
	var earningsQualityRank sql.NullFloat64
	var peRank sql.NullFloat64
	var psRank sql.NullFloat64
	var liquidityRank sql.NullFloat64
	var stabilityRank sql.NullFloat64
	var lowVolatilityRank sql.NullFloat64
	var momentumRank sql.NullFloat64

	// فاکتورهای v3.2 (ترازنامه و جریان نقدی)
	var roe sql.NullFloat64
	var financialLeverage sql.NullFloat64
	var currentRatio sql.NullFloat64
	var cashConversion sql.NullFloat64
	var pbRatio sql.NullFloat64
	var roeRank sql.NullFloat64
	var leverageRank sql.NullFloat64
	var currentRatioRank sql.NullFloat64
	var cashConversionRank sql.NullFloat64
	var pbRank sql.NullFloat64

	err := rows.Scan(
		&r.CompanyID,
		&symbol,
		&companyName,

		&quantScore,
		&dataQualityScore,
		&hasEnoughData,

		&latestSalesReportDate,
		&latestProfitReportDate,
		&latestMarketDate,

		&salesGrowth12M,
		&salesGrowth3M,
		&salesStability,

		&operatingProfitGrowthYoY,
		&operatingProfitGrowth4Reports,
		&netProfitGrowth4Reports,

		&operatingMarginLatest,
		&netMarginLatest,
		&revenueGrowthYoY,
		&interestCoverage,
		&nonOperatingPct,

		&netProfitMargin12M,
		&operatingMargin12M,
		&operatingMarginTrend,
		&psRatio,

		&latestEPS,
		&latestOperatingEPS,
		&latestPrice,
		&peApprox,

		&priceReturn7D,
		&priceReturn30D,
		&priceReturn90D,

		&avgTradeValue30D,
		&avgVolume30D,
		&volatility30D,
		&pricePosition90D,

		&badPEFlag,
		&weakSalesFlag,
		&weakOperatingProfitFlag,
		&weakLiquidityFlag,
		&lossMakerFlag,
		&weakCoverageFlag,
		&marginContractionFlag,

		&growthScore,
		&profitabilityScore,
		&valuationScore,
		&marketScore,

		&growthPenalty,
		&profitabilityPenalty,
		&valuationPenalty,
		&marketPenalty,
		&profitReportAgeMonths,
		&marketDataAgeDays,
		&staleDataFlag,
		&ttmNetProfit,
		&ttmEPS,
		&scoreVersion,

		&salesGrowthRank,
		&salesGrowth3MRank,
		&revenueGrowthRank,
		&operatingProfitGrowthRank,
		&netProfitGrowthRank,
		&operatingMarginRank,
		&netMarginRank,
		&marginTrendRank,
		&interestCoverageRank,
		&earningsQualityRank,
		&peRank,
		&psRank,
		&liquidityRank,
		&stabilityRank,
		&lowVolatilityRank,
		&momentumRank,

		&roe,
		&financialLeverage,
		&currentRatio,
		&cashConversion,
		&pbRatio,
		&roeRank,
		&leverageRank,
		&currentRatioRank,
		&cashConversionRank,
		&pbRank,
	)

	if err != nil {
		return r, err
	}

	r.Symbol = nstring(symbol)
	r.CompanyName = nstring(companyName)

	r.QuantScore = nfloat(quantScore)
	r.DataQualityScore = nfloat(dataQualityScore)
	r.HasEnoughData = nbool(hasEnoughData)

	r.LatestSalesReportDate = nstring(latestSalesReportDate)
	r.LatestProfitReportDate = nstring(latestProfitReportDate)
	r.LatestMarketDate = nstring(latestMarketDate)

	r.SalesGrowth12M = nfloat(salesGrowth12M)
	r.SalesGrowth3M = nfloat(salesGrowth3M)
	r.SalesStability = nfloat(salesStability)

	r.OperatingProfitGrowthYoY = nfloat(operatingProfitGrowthYoY)
	r.OperatingProfitGrowth4Reports = nfloat(operatingProfitGrowth4Reports)
	r.NetProfitGrowth4Reports = nfloat(netProfitGrowth4Reports)

	r.OperatingMarginLatest = nfloat(operatingMarginLatest)
	r.NetMarginLatest = nfloat(netMarginLatest)
	r.RevenueGrowthYoY = nfloat(revenueGrowthYoY)
	r.InterestCoverage = nfloat(interestCoverage)
	r.NonOperatingPct = nfloat(nonOperatingPct)

	r.NetProfitMargin12M = nfloat(netProfitMargin12M)
	r.OperatingMargin12M = nfloat(operatingMargin12M)
	r.OperatingMarginTrend = nfloat(operatingMarginTrend)
	r.PSRatio = nfloat(psRatio)

	r.LatestEPS = nfloat(latestEPS)
	r.LatestOperatingEPS = nfloat(latestOperatingEPS)
	r.LatestPrice = nfloat(latestPrice)
	r.PEApprox = nfloat(peApprox)

	r.PriceReturn7D = nfloat(priceReturn7D)
	r.PriceReturn30D = nfloat(priceReturn30D)
	r.PriceReturn90D = nfloat(priceReturn90D)

	r.AvgTradeValue30D = nfloat(avgTradeValue30D)
	r.AvgVolume30D = nfloat(avgVolume30D)
	r.Volatility30D = nfloat(volatility30D)
	r.PricePosition90D = nfloat(pricePosition90D)

	r.BadPEFlag = nbool(badPEFlag)
	r.WeakSalesFlag = nbool(weakSalesFlag)
	r.WeakOperatingProfitFlag = nbool(weakOperatingProfitFlag)
	r.WeakLiquidityFlag = nbool(weakLiquidityFlag)
	r.LossMakerFlag = nbool(lossMakerFlag)
	r.WeakCoverageFlag = nbool(weakCoverageFlag)
	r.MarginContractionFlag = nbool(marginContractionFlag)

	r.GrowthScore = nfloat(growthScore)
	r.ProfitabilityScore = nfloat(profitabilityScore)
	r.ValuationScore = nfloat(valuationScore)
	r.MarketScore = nfloat(marketScore)

	r.GrowthPenalty = nfloat(growthPenalty)
	r.ProfitabilityPenalty = nfloat(profitabilityPenalty)
	r.ValuationPenalty = nfloat(valuationPenalty)
	r.MarketPenalty = nfloat(marketPenalty)
	r.ProfitReportAgeMonths = int(nullInt64(profitReportAgeMonths))
	r.MarketDataAgeDays = int(nullInt64(marketDataAgeDays))
	r.StaleDataFlag = nbool(staleDataFlag)
	r.TTMNetProfit = nfloat(ttmNetProfit)
	r.TTMEPS = nfloat(ttmEPS)
	r.ScoreVersion = nstring(scoreVersion)

	r.SalesGrowthRank = nfloat(salesGrowthRank)
	r.SalesGrowth3MRank = nfloat(salesGrowth3MRank)
	r.RevenueGrowthRank = nfloat(revenueGrowthRank)
	r.OperatingProfitGrowthRank = nfloat(operatingProfitGrowthRank)
	r.NetProfitGrowthRank = nfloat(netProfitGrowthRank)
	r.OperatingMarginRank = nfloat(operatingMarginRank)
	r.NetMarginRank = nfloat(netMarginRank)
	r.MarginTrendRank = nfloat(marginTrendRank)
	r.InterestCoverageRank = nfloat(interestCoverageRank)
	r.EarningsQualityRank = nfloat(earningsQualityRank)
	r.PERank = nfloat(peRank)
	r.PSRank = nfloat(psRank)
	r.LiquidityRank = nfloat(liquidityRank)
	r.StabilityRank = nfloat(stabilityRank)
	r.LowVolatilityRank = nfloat(lowVolatilityRank)
	r.MomentumRank = nfloat(momentumRank)

	r.ROE = nfloat(roe)
	r.FinancialLeverage = nfloat(financialLeverage)
	r.CurrentRatio = nfloat(currentRatio)
	r.CashConversion = nfloat(cashConversion)
	r.PBRatio = nfloat(pbRatio)
	r.ROERank = nfloat(roeRank)
	r.LeverageRank = nfloat(leverageRank)
	r.CurrentRatioRank = nfloat(currentRatioRank)
	r.CashConversionRank = nfloat(cashConversionRank)
	r.PBRank = nfloat(pbRank)

	return r, nil
}

func GetAIStockSummary(c *gin.Context) {
	start := time.Now()

	limitQuery := parseIntQuery(c, "limit", 20)

	// CANONICAL-FIRST: serve canonical analytics summary without SQL Server.
	sh := integration.Default()
	if sh.SummaryRoute() == integration.RouteCanary {
		if rows, err := sh.FetchSummaryCanonical(c.Request.Context()); err == nil && len(rows) > 0 {
			c.JSON(http.StatusOK, buildCanonicalSummary(rows, limitQuery))
			return
		} else if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical summary unavailable; SQL Server is offline_expected"})
			return
		}
	}

	db := config.GetDB()
	defer db.Close()

	limit := limitQuery
	minAvgTradeValue30D := parseFloatQuery(c, "min_avg_trade_value_30d", 0)

	if limit > 1000 {
		limit = 1000
	}

	query := `
        SELECT TOP (@limit)
            CompanyID,
            Symbol,
            CompanyName,

            QuantScore,
            DataQualityScore,
            HasEnoughData,

            LatestSalesReportDate,
            LatestProfitReportDate,
            CONVERT(NVARCHAR(20), LatestMarketDate, 23) AS LatestMarketDate,

            SalesGrowth12M,
            SalesGrowth3M,
            SalesStability,

            OperatingProfitGrowthYoY,
            OperatingProfitGrowth4Reports,
            NetProfitGrowth4Reports,

            OperatingMarginLatest,
            NetMarginLatest,
            RevenueGrowthYoY,
            InterestCoverage,
            NonOperatingPct,

            NetProfitMargin12M,
            OperatingMargin12M,
            OperatingMarginTrend,
            PSRatio,

            LatestEPS,
            LatestOperatingEPS,
            LatestPrice,
            PEApprox,

            PriceReturn7D,
            PriceReturn30D,
            PriceReturn90D,

            AvgTradeValue30D,
            AvgVolume30D,
            Volatility30D,
            PricePosition90D,

            BadPEFlag,
            WeakSalesFlag,
            WeakOperatingProfitFlag,
            WeakLiquidityFlag,
            LossMakerFlag,
            WeakCoverageFlag,
            MarginContractionFlag,

            GrowthScore,
            ProfitabilityScore,
            ValuationScore,
            MarketScore,

            GrowthPenalty,
            ProfitabilityPenalty,
            ValuationPenalty,
            MarketPenalty,
            ProfitReportAgeMonths,
            MarketDataAgeDays,
            StaleDataFlag,
            TTMNetProfit,
            TTMEPS,
            ScoreVersion,

            SalesGrowthRank,
            SalesGrowth3MRank,
            RevenueGrowthRank,
            OperatingProfitGrowthRank,
            NetProfitGrowthRank,
            OperatingMarginRank,
            NetMarginRank,
            MarginTrendRank,
            InterestCoverageRank,
            EarningsQualityRank,
            PERank,
            PSRank,
            LiquidityRank,
            StabilityRank,
            LowVolatilityRank,
            MomentumRank,

            ROE,
            FinancialLeverage,
            CurrentRatio,
            CashConversion,
            PBRatio,
            ROERank,
            LeverageRank,
            CurrentRatioRank,
            CashConversionRank,
            PBRank
        FROM dbo.vw_AIStockMetrics
		WHERE ISNULL(AvgTradeValue30D, 0) >= @minAvgTradeValue30D
        ORDER BY QuantScore DESC
		`
	// WHERE HasEnoughData = 1

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("minAvgTradeValue30D", minAvgTradeValue30D),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "summary query error: " + err.Error()})
		return
	}
	defer rows.Close()

	result := make([]models.AIStockMetric, 0)

	for rows.Next() {
		item, err := scanAIStockMetric(rows)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan summary error: " + err.Error()})
			return
		}
		result = append(result, item)
	}

	if err := rows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "rows error: " + err.Error()})
		return
	}

	// SHADOW: compare canonical-v1 analytics scores against the legacy v3.7
	// metrics. The legacy response below is authoritative and unchanged.
	if sh.Enabled() {
		sh.CompareScores(c.Request.Context(), toScoreInputs(result), time.Since(start))
	}

	c.JSON(http.StatusOK, result)
}

// toScoreInputs adapts legacy AIStockMetric rows to the integration comparison
// shape. Only fields with a defined canonical counterpart are carried.
func toScoreInputs(rows []models.AIStockMetric) []integration.ScoreInputRow {
	out := make([]integration.ScoreInputRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, integration.ScoreInputRow{
			LegacyCompanyID:    r.CompanyID,
			Symbol:             r.Symbol,
			CompanyName:        r.CompanyName,
			QuantScore:         r.QuantScore,
			DataQualityScore:   r.DataQualityScore,
			GrowthScore:        r.GrowthScore,
			ProfitabilityScore: r.ProfitabilityScore,
			ValuationScore:     r.ValuationScore,
			MarketScore:        r.MarketScore,
			ScoreVersion:       r.ScoreVersion,
		})
	}
	return out
}

func getOneSummaryByCompanyID(db *sql.DB, companyID string) (models.AIStockMetric, error) {
	query := `
        SELECT TOP (@limit)
            CompanyID,
            Symbol,
            CompanyName,

            QuantScore,
            DataQualityScore,
            HasEnoughData,

            LatestSalesReportDate,
            LatestProfitReportDate,
            CONVERT(NVARCHAR(20), LatestMarketDate, 23) AS LatestMarketDate,

            SalesGrowth12M,
            SalesGrowth3M,
            SalesStability,

            OperatingProfitGrowthYoY,
            OperatingProfitGrowth4Reports,
            NetProfitGrowth4Reports,

            OperatingMarginLatest,
            NetMarginLatest,
            RevenueGrowthYoY,
            InterestCoverage,
            NonOperatingPct,

            NetProfitMargin12M,
            OperatingMargin12M,
            OperatingMarginTrend,
            PSRatio,

            LatestEPS,
            LatestOperatingEPS,
            LatestPrice,
            PEApprox,

            PriceReturn7D,
            PriceReturn30D,
            PriceReturn90D,

            AvgTradeValue30D,
            AvgVolume30D,
            Volatility30D,
            PricePosition90D,

            BadPEFlag,
            WeakSalesFlag,
            WeakOperatingProfitFlag,
            WeakLiquidityFlag,
            LossMakerFlag,
            WeakCoverageFlag,
            MarginContractionFlag,

            GrowthScore,
            ProfitabilityScore,
            ValuationScore,
            MarketScore,

            GrowthPenalty,
            ProfitabilityPenalty,
            ValuationPenalty,
            MarketPenalty,
            ProfitReportAgeMonths,
            MarketDataAgeDays,
            StaleDataFlag,
            TTMNetProfit,
            TTMEPS,
            ScoreVersion,

            SalesGrowthRank,
            SalesGrowth3MRank,
            RevenueGrowthRank,
            OperatingProfitGrowthRank,
            NetProfitGrowthRank,
            OperatingMarginRank,
            NetMarginRank,
            MarginTrendRank,
            InterestCoverageRank,
            EarningsQualityRank,
            PERank,
            PSRank,
            LiquidityRank,
            StabilityRank,
            LowVolatilityRank,
            MomentumRank,

            ROE,
            FinancialLeverage,
            CurrentRatio,
            CashConversion,
            PBRatio,
            ROERank,
            LeverageRank,
            CurrentRatioRank,
            CashConversionRank,
            PBRank
        FROM dbo.vw_AIStockMetrics
        WHERE CompanyID = @companyID
    `

	rows, err := db.Query(query, sql.Named("companyID", companyID))
	if err != nil {
		return models.AIStockMetric{}, err
	}
	defer rows.Close()

	if !rows.Next() {
		return models.AIStockMetric{}, sql.ErrNoRows
	}

	return scanAIStockMetric(rows)
}

// GetAIStockDetail serves GET /api/detail?companyID=<legacy 32-hex> or
// ?companyName=<symbol|name>. Canonical-only read of one company: identity,
// canonical scores, monthly activities, income-statement periods, market
// history and materialized base-metric snapshots (with units).
//
// The route previously read the retired SQL Server view and was unreachable
// (the handler read a path param that the route never registered), so nothing
// depended on its old payload; the top-level keys are kept anyway.
func GetAIStockDetail(c *gin.Context) {
	legacyID := strings.TrimSpace(c.Query("companyID"))
	name := strings.TrimSpace(c.Query("companyName"))

	sh := integration.Default()
	if sh == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical read unavailable"})
		return
	}
	if legacyID == "" {
		if name == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "companyID or companyName is required"})
			return
		}
		bundle, err := sh.FetchCompanyScoreCanonical(c.Request.Context(), name)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "canonical resolve error: " + err.Error()})
			return
		}
		legacyID = bundle.LegacyCompanyID
	}
	if legacyID == "" {
		c.JSON(http.StatusNotFound, gin.H{"error": "company not found"})
		return
	}

	page, err := sh.FetchSymbolPageCanonical(c.Request.Context(), legacyID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "canonical detail error: " + err.Error()})
		return
	}
	if !page.IdentityFound {
		c.JSON(http.StatusNotFound, gin.H{"error": "company not found"})
		return
	}

	capAt := func(v, max int) int {
		if v > max {
			return max
		}
		return v
	}
	months := capAt(parseIntQuery(c, "months", 24), 60)
	marketDays := capAt(parseIntQuery(c, "market_days", 90), 250)
	profitReports := capAt(parseIntQuery(c, "profit_reports", 8), 20)

	monthly := make([]gin.H, 0, months)
	for i, m := range page.Monthly {
		if i >= months {
			break
		}
		monthly = append(monthly, gin.H{
			"report_date": m.ReportDate, "production_qty": m.ProductionQuantity,
			"sales_qty": m.SalesQuantity, "sales_amount_rial": m.SalesAmountRial,
		})
	}

	profit := make([]gin.H, 0, profitReports)
	for i, f := range page.Financial {
		if i >= profitReports {
			break
		}
		profit = append(profit, gin.H{
			"report_date": f.ReportDate, "eps_rial": f.EPS,
			"revenue_million_rial": f.Revenue, "operating_profit_million_rial": f.OperatingProfit,
			"net_profit_million_rial": f.NetProfit, "capital_million_rial": f.Capital,
		})
	}

	market := make([]gin.H, 0, marketDays)
	for i, d := range page.Market {
		if i >= marketDays {
			break
		}
		market = append(market, gin.H{
			"gregorian_date": d.Date, "jalali_date": d.JalaliDate,
			"closing_price": d.ClosingPrice, "last_price": d.LastPrice,
			"high_price": d.HighPrice, "low_price": d.LowPrice,
			"volume": d.Volume, "trade_value": d.TradeValue, "change_percent": d.ChangePercent,
		})
	}

	metrics := make([]gin.H, 0, len(page.MetricSnapshots))
	for _, s := range page.MetricSnapshots {
		metrics = append(metrics, gin.H{
			"metric_code": s.MetricCode, "value": s.Value, "unit": s.Unit, "as_of_date": s.AsOfDate,
		})
	}

	summary := gin.H{}
	if len(page.Scores) > 0 {
		s := page.Scores[0]
		summary = gin.H{
			"company_id": s.LegacyCompanyID, "symbol": s.Symbol, "company_name": s.CompanyName,
			"quant_score": s.QuantScore, "data_quality_score": s.DataQualityScore,
			"growth_score": s.GrowthScore, "profitability_score": s.ProfitabilityScore,
			"valuation_score": s.ValuationScore, "market_score": s.MarketScore,
			"score_version": s.ScoreVersion,
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"summary": summary,
		"monthly": monthly,
		"profit":  profit,
		"market":  market,
		"metrics": metrics,
		"identity": gin.H{
			"symbol": page.Identity.Symbol, "display_name": page.Identity.DisplayName,
			"legal_name": page.Identity.LegalName, "tsetmc_ins_code": page.Identity.TsetmcInsCode,
		},
		"meta": gin.H{
			"score_as_of": page.Metadata.ScoreAsOf, "score_run_id": page.Metadata.ScoreRunID,
			"market_as_of": page.Metadata.MarketAsOf, "fundamentals_as_of": page.Metadata.FundamentalsAsOf,
			"stale": page.Metadata.Stale,
		},
	})
}

func getMonthlyPoints(db *sql.DB, companyID string, limit int) ([]models.AIMonthlyPoint, error) {
	query := `
        SELECT TOP (@limit)
            ReportDate,
            Value1,
            Value2,
            Value3
        FROM dbo.mahane
        WHERE CompanyID = @companyID
          AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
        ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
    `

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("companyID", companyID),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]models.AIMonthlyPoint, 0)

	for rows.Next() {
		var r models.AIMonthlyPoint
		var v1, v2, v3 sql.NullFloat64

		if err := rows.Scan(&r.ReportDate, &v1, &v2, &v3); err != nil {
			return nil, err
		}

		r.Value1 = nfloat(v1)
		r.Value2 = nfloat(v2)
		r.Value3 = nfloat(v3)

		result = append(result, r)
	}

	return result, rows.Err()
}

func getProfitPoints(db *sql.DB, companyID string, limit int) ([]models.AIProfitPoint, error) {
	query := `
        SELECT TOP (@limit)
            ReportDate,
            Num1_Value1,
            Num2_Value1,
            Num4_Value1,
            Product1,
            OperatingProfitNew,
            OperatingProfitLastYear,
            FinanceCostsNew,
            FinanceCostsLastYear,
            OtherNonOpNew,
            OtherNonOpLastYear
        FROM dbo.miandore2
        WHERE CompanyID = @companyID
          AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
        ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
    `

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("companyID", companyID),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]models.AIProfitPoint, 0)

	for rows.Next() {
		var r models.AIProfitPoint
		var netEPS, capital, operatingEPS, netProfit, opNew, opLast sql.NullFloat64
		var fcNew, fcLast, nonNew, nonLast sql.NullFloat64

		if err := rows.Scan(
			&r.ReportDate,
			&netEPS,
			&capital,
			&operatingEPS,
			&netProfit,
			&opNew,
			&opLast,
			&fcNew,
			&fcLast,
			&nonNew,
			&nonLast,
		); err != nil {
			return nil, err
		}

		r.NetEPS = nfloat(netEPS)
		r.Capital = nfloat(capital)
		r.OperatingEPS = nfloat(operatingEPS)
		r.NetProfitApprox = nfloat(netProfit)
		r.OperatingProfitNew = nfloat(opNew)
		r.OperatingProfitLastYear = nfloat(opLast)
		r.FinanceCostsNew = nfloat(fcNew)
		r.FinanceCostsLastYear = nfloat(fcLast)
		r.OtherNonOpNew = nfloat(nonNew)
		r.OtherNonOpLastYear = nfloat(nonLast)

		result = append(result, r)
	}

	return result, rows.Err()
}

func getMarketPoints(db *sql.DB, companyID string, limit int) ([]models.AIMarketPoint, error) {
	query := `
        SELECT TOP (@limit)
            CONVERT(NVARCHAR(20), GregorianDate, 23) AS GregorianDate,
            JalaliDate,
            ClosingPrice,
            LastPrice,
            HighPrice,
            LowPrice,
            ClosingChangePercent,
            TradeValue,
            Volume,
            TradeCount
        FROM dbo.MarketPriceHistory
        WHERE CompanyID = @companyID
          AND TRY_CONVERT(DATE, GregorianDate) IS NOT NULL
        ORDER BY TRY_CONVERT(DATE, GregorianDate) DESC, CollectedAt DESC
    `

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("companyID", companyID),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]models.AIMarketPoint, 0)

	for rows.Next() {
		var r models.AIMarketPoint

		var jalaliDate sql.NullString
		var closingPrice, lastPrice, highPrice, lowPrice sql.NullFloat64
		var closingChangePercent, tradeValue, volume, tradeCount sql.NullFloat64

		if err := rows.Scan(
			&r.GregorianDate,
			&jalaliDate,
			&closingPrice,
			&lastPrice,
			&highPrice,
			&lowPrice,
			&closingChangePercent,
			&tradeValue,
			&volume,
			&tradeCount,
		); err != nil {
			return nil, err
		}

		r.JalaliDate = nstring(jalaliDate)
		r.ClosingPrice = nfloat(closingPrice)
		r.LastPrice = nfloat(lastPrice)
		r.HighPrice = nfloat(highPrice)
		r.LowPrice = nfloat(lowPrice)
		r.ClosingChangePercent = nfloat(closingChangePercent)
		r.TradeValue = nfloat(tradeValue)
		r.Volume = nfloat(volume)
		r.TradeCount = nfloat(tradeCount)

		result = append(result, r)
	}

	return result, rows.Err()
}
func buildStockAnalysisPrompt(candidates []models.AIStockMetric) (string, error) {
	payload, err := json.MarshalIndent(candidates, "", "  ")
	if err != nil {
		return "", err
	}

	prompt := fmt.Sprintf(`
تو تحلیلگر داده بازار سرمایه هستی، اما حق نداری توصیه قطعی خرید یا فروش بدهی.

من یک لیست از نمادها می‌فرستم که قبلاً با محاسبات عددی رتبه‌بندی شده‌اند.
وظیفه تو تحلیل ثانویه است، نه محاسبه خام.

قواعد سخت:
1. فقط از داده‌های JSON استفاده کن.
2. هیچ عددی را حدس نزن.
3. اگر داده ناقص است، صریح بنویس "داده ناکافی".
4. رتبه‌بندی نهایی را بر اساس ترکیب رشد فروش، رشد سود عملیاتی، رشد سود خالص، P/E، نقدشوندگی، کیفیت داده و ریسک قیمت انجام بده.
5. رشد قیمت بدون رشد سود را امتیاز مثبت حساب نکن.
6. P/E منفی، صفر یا غیرعادی را ریسک حساب کن.
7. خروجی فقط JSON معتبر باشد. متن اضافه ننویس.

ساختار خروجی:
{
  "top_candidates": [
    {
      "rank": 1,
      "company_id": "...",
      "symbol": "...",
      "company_name": "...",
      "decision": "بررسی بیشتر",
      "confidence": 0.0,
      "strengths": ["..."],
      "risks": ["..."],
      "reason": "..."
    }
  ],
  "rejected_or_risky": [
    {
      "company_id": "...",
      "symbol": "...",
      "company_name": "...",
      "reason": "..."
    }
  ],
  "general_notes": ["..."]
}

داده:
%s
`, string(payload))

	return strings.TrimSpace(prompt), nil
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequest struct {
	Model       string        `json:"model"`
	Messages    []chatMessage `json:"messages"`
	Temperature float64       `json:"temperature"`
}

type chatResponse struct {
	Choices []struct {
		Message chatMessage `json:"message"`
	} `json:"choices"`
}

func callAI(prompt string) (string, error) {
	chatURL := strings.TrimSpace(os.Getenv("AI_CHAT_URL"))
	apiKey := strings.TrimSpace(os.Getenv("AI_API_KEY"))
	model := strings.TrimSpace(os.Getenv("AI_MODEL"))

	if chatURL == "" {
		return "", fmt.Errorf("AI_CHAT_URL is empty")
	}
	if apiKey == "" {
		return "", fmt.Errorf("AI_API_KEY is empty")
	}
	if model == "" {
		model = "default"
	}

	reqBody := chatRequest{
		Model:       model,
		Temperature: 0.1,
		Messages: []chatMessage{
			{
				Role:    "system",
				Content: "You are a precise financial data analyst. Return only valid JSON. Do not provide buy/sell advice.",
			},
			{
				Role:    "user",
				Content: prompt,
			},
		},
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return "", err
	}

	httpReq, err := http.NewRequest(http.MethodPost, chatURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return "", err
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+apiKey)

	client := &http.Client{
		Timeout: 90 * time.Second,
	}

	resp, err := client.Do(httpReq)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	respBytes, _ := io.ReadAll(resp.Body)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("AI error status=%d body=%s", resp.StatusCode, string(respBytes))
	}

	var parsed chatResponse
	if err := json.Unmarshal(respBytes, &parsed); err != nil {
		return "", fmt.Errorf("invalid AI response JSON: %w; raw=%s", err, string(respBytes))
	}

	if len(parsed.Choices) == 0 {
		return "", fmt.Errorf("AI response has no choices")
	}

	return strings.TrimSpace(parsed.Choices[0].Message.Content), nil
}

func AnalyzeTopStocksWithAI(c *gin.Context) {
	if config.SQLServerMode() == "offline_expected" {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "AI analyze unavailable (legacy view retired)", "reason": "sqlserver_offline_expected"})
		return
	}
	db := config.GetDB()
	defer db.Close()

	var req models.AIAnalyzeRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		req = models.AIAnalyzeRequest{}
	}

	limit := req.Limit
	if limit <= 0 {
		limit = 20
	}
	if limit > 50 {
		limit = 50
	}

	minAvgTradeValue30D := req.MinAvgTradeValue30D

	query := `
        SELECT TOP (@limit)
            CompanyID,
            Symbol,
            CompanyName,

            QuantScore,
            DataQualityScore,
            HasEnoughData,

            LatestSalesReportDate,
            LatestProfitReportDate,
            CONVERT(NVARCHAR(20), LatestMarketDate, 23) AS LatestMarketDate,

            SalesGrowth12M,
            SalesGrowth3M,
            SalesStability,

            OperatingProfitGrowthYoY,
            OperatingProfitGrowth4Reports,
            NetProfitGrowth4Reports,

            OperatingMarginLatest,
            NetMarginLatest,
            RevenueGrowthYoY,
            InterestCoverage,
            NonOperatingPct,

            NetProfitMargin12M,
            OperatingMargin12M,
            OperatingMarginTrend,
            PSRatio,

            LatestEPS,
            LatestOperatingEPS,
            LatestPrice,
            PEApprox,

            PriceReturn7D,
            PriceReturn30D,
            PriceReturn90D,

            AvgTradeValue30D,
            AvgVolume30D,
            Volatility30D,
            PricePosition90D,

            BadPEFlag,
            WeakSalesFlag,
            WeakOperatingProfitFlag,
            WeakLiquidityFlag,
            LossMakerFlag,
            WeakCoverageFlag,
            MarginContractionFlag,

            GrowthScore,
            ProfitabilityScore,
            ValuationScore,
            MarketScore,

            GrowthPenalty,
            ProfitabilityPenalty,
            ValuationPenalty,
            MarketPenalty,
            ProfitReportAgeMonths,
            MarketDataAgeDays,
            StaleDataFlag,
            TTMNetProfit,
            TTMEPS,
            ScoreVersion,

            SalesGrowthRank,
            SalesGrowth3MRank,
            RevenueGrowthRank,
            OperatingProfitGrowthRank,
            NetProfitGrowthRank,
            OperatingMarginRank,
            NetMarginRank,
            MarginTrendRank,
            InterestCoverageRank,
            EarningsQualityRank,
            PERank,
            PSRank,
            LiquidityRank,
            StabilityRank,
            LowVolatilityRank,
            MomentumRank,

            ROE,
            FinancialLeverage,
            CurrentRatio,
            CashConversion,
            PBRatio,
            ROERank,
            LeverageRank,
            CurrentRatioRank,
            CashConversionRank,
            PBRank
        FROM dbo.vw_AIStockMetrics
		WHERE ISNULL(AvgTradeValue30D, 0) >= @minAvgTradeValue30D
        ORDER BY QuantScore DESC
		`
	// WHERE HasEnoughData = 1

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("minAvgTradeValue30D", minAvgTradeValue30D),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "candidate query error: " + err.Error()})
		return
	}
	defer rows.Close()

	candidates := make([]models.AIStockMetric, 0)

	for rows.Next() {
		item, err := scanAIStockMetric(rows)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan candidate error: " + err.Error()})
			return
		}
		candidates = append(candidates, item)
	}

	if len(candidates) == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "no valid candidates found"})
		return
	}

	prompt, err := buildStockAnalysisPrompt(candidates)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "prompt build error: " + err.Error()})
		return
	}

	aiResult, err := callAI(prompt)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":      "AI call error: " + err.Error(),
			"candidates": candidates,
			"prompt":     prompt,
		})
		return
	}

	c.JSON(http.StatusOK, models.AIAnalyzeResponse{
		Candidates: candidates,
		Prompt:     prompt,
		AIResult:   aiResult,
	})
}
