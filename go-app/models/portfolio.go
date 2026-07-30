package models

// PortfolioHolding یک دارایی (سهم) داخل پورتفولیوی کاربر.
// این ساختار به‌صورت JSON داخل ستون [Portfolio] جدول Users ذخیره می‌شود
// (همان الگوی [ViewedItems]).
type PortfolioHolding struct {
	CompanyID   string  `json:"company_id"`
	Symbol      string  `json:"symbol,omitempty"`
	CompanyName string  `json:"company_name"`
	Quantity    float64 `json:"quantity"`
	BuyPrice    float64 `json:"buy_price"`
	BuyDate     string  `json:"buy_date,omitempty"`
	Note        string  `json:"note,omitempty"`
}

// PortfolioHoldingEnriched نسخه‌ی غنی‌شده‌ی دارایی با قیمت زنده و محاسبات.
type PortfolioHoldingEnriched struct {
	PortfolioHolding

	LatestPrice  float64 `json:"latest_price"`
	HasLivePrice bool    `json:"has_live_price"`
	MarketValue  float64 `json:"market_value"`
	CostBasis    float64 `json:"cost_basis"`
	Gain         float64 `json:"gain"`
	GainPct      float64 `json:"gain_pct"`
	Weight       float64 `json:"weight"`
}

// PortfolioSummary خروجی کلی endpoint پورتفولیو (دارایی‌ها + خلاصه‌ی کل).
type PortfolioSummary struct {
	TotalCost       float64                    `json:"total_cost"`
	TotalCostRaw    float64                    `json:"total_cost_raw"`
	TotalMarketValue float64                   `json:"total_market_value"`
	TotalGain       float64                    `json:"total_gain"`
	TotalGainPct    float64                    `json:"total_gain_pct"`
	HoldingsCount   int                        `json:"holdings_count"`
	Holdings        []PortfolioHoldingEnriched `json:"holdings"`
}