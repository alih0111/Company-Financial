package models

type AIStockMetric struct {
	CompanyID   string `json:"company_id"`
	Symbol      string `json:"symbol"`
	CompanyName string `json:"company_name"`

	QuantScore       float64 `json:"quant_score"`
	DataQualityScore float64 `json:"data_quality_score"`
	HasEnoughData    bool    `json:"has_enough_data"`

	LatestSalesReportDate  string `json:"latest_sales_report_date"`
	LatestProfitReportDate string `json:"latest_profit_report_date"`
	LatestMarketDate       string `json:"latest_market_date"`

	SalesGrowth12M float64 `json:"sales_growth_12m"`
	SalesGrowth3M  float64 `json:"sales_growth_3m"`
	SalesStability float64 `json:"sales_stability"`

	OperatingProfitGrowthYoY      float64 `json:"operating_profit_growth_yoy"`
	OperatingProfitGrowth4Reports float64 `json:"operating_profit_growth_4_reports"`
	NetProfitGrowth4Reports       float64 `json:"net_profit_growth_4_reports"`

	LatestEPS          float64 `json:"latest_eps"`
	LatestOperatingEPS float64 `json:"latest_operating_eps"`
	LatestPrice        float64 `json:"latest_price"`
	PEApprox           float64 `json:"pe_approx"`

	PriceReturn7D  float64 `json:"price_return_7d"`
	PriceReturn30D float64 `json:"price_return_30d"`
	PriceReturn90D float64 `json:"price_return_90d"`

	AvgTradeValue30D float64 `json:"avg_trade_value_30d"`
	AvgVolume30D     float64 `json:"avg_volume_30d"`
	Volatility30D    float64 `json:"volatility_30d"`
	PricePosition90D float64 `json:"price_position_90d"`

	BadPEFlag               bool `json:"bad_pe_flag"`
	WeakSalesFlag           bool `json:"weak_sales_flag"`
	WeakOperatingProfitFlag bool `json:"weak_operating_profit_flag"`
	WeakLiquidityFlag       bool `json:"weak_liquidity_flag"`
}

type AIMonthlyPoint struct {
	ReportDate string  `json:"report_date"`
	Value1     float64 `json:"production_qty"`
	Value2     float64 `json:"sales_qty"`
	Value3     float64 `json:"sales_amount"`
}

type AIProfitPoint struct {
	ReportDate              string  `json:"report_date"`
	NetEPS                  float64 `json:"net_eps"`
	Capital                 float64 `json:"capital"`
	OperatingEPS            float64 `json:"operating_eps"`
	NetProfitApprox         float64 `json:"net_profit_approx"`
	OperatingProfitNew      float64 `json:"operating_profit_new"`
	OperatingProfitLastYear float64 `json:"operating_profit_last_year"`
}

type AIMarketPoint struct {
	GregorianDate        string  `json:"gregorian_date"`
	JalaliDate           string  `json:"jalali_date"`
	ClosingPrice         float64 `json:"closing_price"`
	LastPrice            float64 `json:"last_price"`
	HighPrice            float64 `json:"high_price"`
	LowPrice             float64 `json:"low_price"`
	ClosingChangePercent float64 `json:"closing_change_percent"`
	TradeValue           float64 `json:"trade_value"`
	Volume               float64 `json:"volume"`
	TradeCount           float64 `json:"trade_count"`
}

type AIStockDetail struct {
	Summary modelsCompatAIStockMetric `json:"summary"`
	Monthly []AIMonthlyPoint          `json:"monthly"`
	Profit  []AIProfitPoint           `json:"profit"`
	Market  []AIMarketPoint           `json:"market"`
}

type modelsCompatAIStockMetric = AIStockMetric

type AIAnalyzeRequest struct {
	Limit               int     `json:"limit"`
	MinAvgTradeValue30D float64 `json:"min_avg_trade_value_30d"`
}

type AIAnalyzeResponse struct {
	Candidates []AIStockMetric `json:"candidates"`
	Prompt     string          `json:"prompt"`
	AIResult   string          `json:"ai_result"`
}
