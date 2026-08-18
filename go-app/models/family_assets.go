package models

// ─────────────────────────────────────────────────────────────────────
// دارایی خانواده — جایگزین اکسل «دارایی - 14050526.xlsx»
// ساختارها مطابق Sheet1 (پرتفوی اشخاص) و Sheet2 (تاریخچه جمع کل) هستند.
// ─────────────────────────────────────────────────────────────────────

// FamilyAssetRow یک دارایی (مثقال، کاسپین، ...) با آخرین قیمت و جمع کل بین اشخاص.
type FamilyAssetRow struct {
	AssetID        int     `json:"asset_id"`
	Name           string  `json:"name"`
	Symbol         string  `json:"symbol"` // نماد بازار برای سینک خودکار قیمت (خالی = دستی)
	Category       string  `json:"category"`       // stock | gold | dollar | other
	CommissionRate float64 `json:"commission_rate"` // نرخ کارمزد رفت‌وبرگشت
	SortOrder      int     `json:"sort_order"`
	LatestPrice    float64 `json:"latest_price"`
	PriceDate      string  `json:"price_date"`
	TotalQuantity  float64 `json:"total_quantity"`
	TotalCost      float64 `json:"total_cost"`
	TotalValue     float64 `json:"total_value"`
	TotalProfit    float64 `json:"total_profit"`
	ProfitPct      float64 `json:"profit_pct"`
	Weight         float64 `json:"weight"` // درصد از کل ارزش دارایی‌ها
}

// FamilyHoldingRow یک دارایی داخل سبد یک شخص (با محاسبات).
type FamilyHoldingRow struct {
	AssetID   int     `json:"asset_id"`
	AssetName string  `json:"asset_name"`
	Quantity  float64 `json:"quantity"`
	CostBasis float64 `json:"cost_basis"` // بهای تمام شده کل
	Value     float64 `json:"value"`      // تعداد × قیمت × (1 − کارمزد)
	Profit    float64 `json:"profit"`
	ProfitPct float64 `json:"profit_pct"`
	Weight    float64 `json:"weight"` // درصد از ارزش دارایی‌های شخص
}

// FamilyPersonRow سبد یک شخص + مانده حساب او.
type FamilyPersonRow struct {
	PersonID      int                 `json:"person_id"`
	Name          string              `json:"name"`
	SortOrder     int                 `json:"sort_order"`
	CashBalance   float64             `json:"cash_balance"` // مانده حساب
	Holdings      []FamilyHoldingRow  `json:"holdings"`
	HoldingsValue float64             `json:"holdings_value"`
	TotalValue    float64             `json:"total_value"` // دارایی‌ها + مانده
	TotalCost     float64             `json:"total_cost"`
	Profit        float64             `json:"profit"`
	ProfitPct     float64             `json:"profit_pct"`
	ShareOfTotal  float64             `json:"share_of_total"` // درصد از جمع کل
}

// FamilySummary جمع‌بندی کلی مطابق ردیف‌های انتهای Sheet1.
type FamilySummary struct {
	LatestDateKey string  `json:"latest_datekey"`
	HoldingsValue float64 `json:"holdings_value"` // مجموع ارزش همه دارایی‌ها
	TotalCash     float64 `json:"total_cash"`     // مجموع مانده حساب‌ها
	GrandTotal    float64 `json:"grand_total"`    // دارایی‌ها + مانده
	TotalCost     float64 `json:"total_cost"`
	TotalProfit   float64 `json:"total_profit"`
	TotalProfitPct float64 `json:"total_profit_pct"`
	BestTomorrow  float64 `json:"best_tomorrow"`  // جمع کل + ۳٪ ارزش دارایی‌ها
	WorstTomorrow float64 `json:"worst_tomorrow"` // جمع کل − ۳٪ ارزش دارایی‌ها
	StocksTotal   float64 `json:"stocks_total"`
	GoldTotal     float64 `json:"gold_total"`
	DollarTotal   float64 `json:"dollar_total"`
}

// FamilyState خروجی کلی endpoint وضعیت دارایی‌ها.
type FamilyState struct {
	TodayDateKey string            `json:"today_datekey"`
	Assets       []FamilyAssetRow  `json:"assets"`
	People       []FamilyPersonRow `json:"people"`
	Summary      FamilySummary     `json:"summary"`
}

// FamilyHistoryRow یک روز از تاریخچه: جمع کل واقعی (اکسل/سایت) +
// ارزش بازسازی‌شده هر شخص (دارایی امروز × قیمت تاریخی + مانده فعلی).
type FamilyHistoryRow struct {
	DateKey  string             `json:"date_key"`
	Total    float64            `json:"total"`
	HasTotal bool               `json:"has_total"` // از تاریخچه واقعی است نه بازسازی
	People   map[string]float64 `json:"people"`    // کلید = PersonID رشته‌ای
}

// FamilyCashFlow یک آورده/برداشت (ستون‌های E/F/G در Sheet2).
type FamilyCashFlow struct {
	ID        int     `json:"id"`
	DateKey   string  `json:"date_key"`
	Amount    float64 `json:"amount"`
	Direction string  `json:"direction"` // in | out
	Note      string  `json:"note"`
}
