package handlers

import (
	"sort"

	"go-app/integration"
)

// canonicalStockMetric is the canonical /api/summary response shape. It mirrors
// the client's AIStockMetric JSON contract:
//   - category/quant/data-quality scores come from analytics.company_scores;
//   - factor rank fields come from analytics.factor_scores.percentile (0..1) and
//     drive the score-detail progress fills;
//   - base metric value fields are pointers so genuinely unavailable values are
//     emitted as JSON null ("--" in the UI) instead of a misleading 0.
type canonicalStockMetric struct {
	CompanyID   string `json:"company_id"`
	Symbol      string `json:"symbol"`
	CompanyName string `json:"company_name"`

	QuantScore       float64 `json:"quant_score"`
	DataQualityScore float64 `json:"data_quality_score"`
	HasEnoughData    bool    `json:"has_enough_data"`

	LatestSalesReportDate  *string `json:"latest_sales_report_date"`
	LatestProfitReportDate *string `json:"latest_profit_report_date"`
	LatestMarketDate       *string `json:"latest_market_date"`

	SalesGrowth12M *float64 `json:"sales_growth_12m"`
	SalesGrowth3M  *float64 `json:"sales_growth_3m"`
	SalesStability *float64 `json:"sales_stability"`

	OperatingProfitGrowthYoY      *float64 `json:"operating_profit_growth_yoy"`
	OperatingProfitGrowth4Reports *float64 `json:"operating_profit_growth_4_reports"`
	NetProfitGrowth4Reports       *float64 `json:"net_profit_growth_4_reports"`

	OperatingMarginLatest *float64 `json:"operating_margin_latest"`
	NetMarginLatest       *float64 `json:"net_margin_latest"`
	RevenueGrowthYoY      *float64 `json:"revenue_growth_yoy"`
	InterestCoverage      *float64 `json:"interest_coverage"`
	NonOperatingPct       *float64 `json:"non_operating_pct"`

	NetProfitMargin12M    *float64 `json:"net_profit_margin_12m"`
	OperatingMargin12M    *float64 `json:"operating_margin_12m"`
	OperatingMarginTrend  *float64 `json:"operating_margin_trend"`
	PSRatio               *float64 `json:"ps_ratio"`

	LatestEPS          *float64 `json:"latest_eps"`
	LatestOperatingEPS *float64 `json:"latest_operating_eps"`
	LatestPrice        *float64 `json:"latest_price"`
	PEApprox           *float64 `json:"pe_approx"`

	PriceReturn7D  *float64 `json:"price_return_7d"`
	PriceReturn30D *float64 `json:"price_return_30d"`
	PriceReturn90D *float64 `json:"price_return_90d"`

	AvgTradeValue30D *float64 `json:"avg_trade_value_30d"`
	AvgVolume30D     *float64 `json:"avg_volume_30d"`
	Volatility30D    *float64 `json:"volatility_30d"`
	PricePosition90D *float64 `json:"price_position_90d"`

	BadPEFlag               bool `json:"bad_pe_flag"`
	WeakSalesFlag           bool `json:"weak_sales_flag"`
	WeakOperatingProfitFlag bool `json:"weak_operating_profit_flag"`
	WeakLiquidityFlag       bool `json:"weak_liquidity_flag"`
	LossMakerFlag           bool `json:"loss_maker_flag"`
	WeakCoverageFlag        bool `json:"weak_coverage_flag"`
	MarginContractionFlag   bool `json:"margin_contraction_flag"`

	GrowthScore        float64 `json:"growth_score"`
	ProfitabilityScore float64 `json:"profitability_score"`
	ValuationScore     float64 `json:"valuation_score"`
	MarketScore        float64 `json:"market_score"`

	GrowthPenalty        float64 `json:"growth_penalty"`
	ProfitabilityPenalty float64 `json:"profitability_penalty"`
	ValuationPenalty     float64 `json:"valuation_penalty"`
	MarketPenalty        float64 `json:"market_penalty"`
	ProfitReportAgeMonths int    `json:"profit_report_age_months"`
	MarketDataAgeDays    int    `json:"market_data_age_days"`
	StaleDataFlag        bool   `json:"stale_data_flag"`
	TTMNetProfit         *float64 `json:"ttm_net_profit"`
	TTMEPS               *float64 `json:"ttm_eps"`
	ScoreVersion         string `json:"score_version"`

	// Factor percentile ranks (0..1) — progress-bar fills.
	SalesGrowthRank           float64 `json:"sales_growth_rank"`
	SalesGrowth3MRank         float64 `json:"sales_growth_3m_rank"`
	RevenueGrowthRank         float64 `json:"revenue_growth_rank"`
	OperatingProfitGrowthRank float64 `json:"operating_profit_growth_rank"`
	NetProfitGrowthRank       float64 `json:"net_profit_growth_rank"`
	OperatingMarginRank       float64 `json:"operating_margin_rank"`
	NetMarginRank             float64 `json:"net_margin_rank"`
	MarginTrendRank           float64 `json:"margin_trend_rank"`
	InterestCoverageRank      float64 `json:"interest_coverage_rank"`
	EarningsQualityRank       float64 `json:"earnings_quality_rank"`
	PERank                    float64 `json:"pe_rank"`
	PSRank                    float64 `json:"ps_rank"`
	LiquidityRank             float64 `json:"liquidity_rank"`
	StabilityRank             float64 `json:"stability_rank"`
	LowVolatilityRank         float64 `json:"low_volatility_rank"`
	MomentumRank              float64 `json:"momentum_rank"`

	ROE                *float64 `json:"roe"`
	FinancialLeverage  *float64 `json:"financial_leverage"`
	CurrentRatio       *float64 `json:"current_ratio"`
	CashConversion     *float64 `json:"cash_conversion"`
	PBRatio            *float64 `json:"pb_ratio"`
	ROERank            float64  `json:"roe_rank"`
	LeverageRank       float64  `json:"leverage_rank"`
	CurrentRatioRank   float64  `json:"current_ratio_rank"`
	CashConversionRank float64  `json:"cash_conversion_rank"`
	PBRank             float64  `json:"pb_rank"`
}

// buildCanonicalStockMetric maps a canonical score row to the response shape.
func buildCanonicalStockMetric(r integration.AllScoreInputRow) canonicalStockMetric {
	rank := func(code string) float64 { return integration.FactorRank(r.FactorRanks, code) }
	raw := func(code string) *float64 { return integration.FactorRaw(r.FactorRaw, code) }
	return canonicalStockMetric{
		CompanyID: r.LegacyCompanyID, Symbol: r.Symbol, CompanyName: r.CompanyName,
		QuantScore: r.QuantScore, DataQualityScore: r.DataQualityScore, HasEnoughData: true,

		SalesGrowth12M: raw("SalesGrowth"), SalesGrowth3M: raw("SalesGrowth3M"),
		SalesStability: raw("Stability"),
		OperatingProfitGrowthYoY: raw("OperatingProfitGrowth"),
		NetProfitGrowth4Reports:  raw("NetProfitGrowth"),
		OperatingMargin12M:       raw("OperatingMargin"),
		NetProfitMargin12M:       raw("NetMargin"),
		OperatingMarginTrend:     raw("MarginTrend"),
		InterestCoverage:         raw("InterestCoverage"),
		NonOperatingPct:          raw("EarningsQuality"),
		RevenueGrowthYoY:         raw("RevenueGrowth"),
		PSRatio:                  raw("PS"),
		PEApprox:                 raw("PE"),
		PBRatio:                  raw("PB"),
		AvgTradeValue30D:         raw("Liquidity"),
		FinancialLeverage:        raw("Leverage"),
		CurrentRatio:             raw("CurrentRatio"),
		Volatility30D:            raw("LowVolatility"),
		PriceReturn30D:           raw("Momentum"),
		ROE:                      raw("ROERank"),
		CashConversion:           raw("CashConversion"),

		GrowthScore: r.GrowthScore, ProfitabilityScore: r.ProfitabilityScore,
		ValuationScore: r.ValuationScore, MarketScore: r.MarketScore,
		ScoreVersion: r.ScoreVersion,

		SalesGrowthRank: rank("SalesGrowth"), SalesGrowth3MRank: rank("SalesGrowth3M"),
		RevenueGrowthRank: rank("RevenueGrowth"),
		OperatingProfitGrowthRank: rank("OperatingProfitGrowth"),
		NetProfitGrowthRank: rank("NetProfitGrowth"),
		OperatingMarginRank: rank("OperatingMargin"), NetMarginRank: rank("NetMargin"),
		MarginTrendRank: rank("MarginTrend"), InterestCoverageRank: rank("InterestCoverage"),
		EarningsQualityRank: rank("EarningsQuality"), PERank: rank("PE"),
		PSRank: rank("PS"), LiquidityRank: rank("Liquidity"), StabilityRank: rank("Stability"),
		LowVolatilityRank: rank("LowVolatility"), MomentumRank: rank("Momentum"),
		ROERank: rank("ROERank"), LeverageRank: rank("Leverage"),
		CurrentRatioRank: rank("CurrentRatio"), CashConversionRank: rank("CashConversion"),
		PBRank: rank("PB"),
	}
}

func buildCanonicalSummary(rows []integration.AllScoreInputRow, limit int) []canonicalStockMetric {
	sorted := append([]integration.AllScoreInputRow(nil), rows...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].QuantScore > sorted[j].QuantScore })
	if limit > 0 && len(sorted) > limit {
		sorted = sorted[:limit]
	}
	out := make([]canonicalStockMetric, 0, len(sorted))
	for _, r := range sorted {
		out = append(out, buildCanonicalStockMetric(r))
	}
	return out
}
