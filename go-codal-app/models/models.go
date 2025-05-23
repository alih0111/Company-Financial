package models

type SalesRecord struct {
	CompanyName string
	CompanyID   int
	ReportDate  string
	Value1      float64
	Value2      float64
	Value3      float64
}

type ScoreResult struct {
	CompanyID      int     `json:"companyID"`
	CompanyName    string  `json:"companyName"`
	FinalScore     float64 `json:"finalScore"`
	SalesGrowth    float64 `json:"salesGrowth"`
	SalesStability float64 `json:"salesStability"`
	EPSLevel       float64 `json:"epsLevel"`
	EPSGrowth      float64 `json:"epsGrowth"`
}
