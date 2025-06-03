package models

import "gorm.io/gorm"

type SalesRecord struct {
	CompanyName string
	CompanyID   string
	ReportDate  string
	Value1      float64
	Value2      float64
	Value3      float64
}

type ScoreResult struct {
	CompanyID      string  `json:"companyID"`
	CompanyName    string  `json:"companyName"`
	FinalScore     float64 `json:"finalScore"`
	SalesGrowth    float64 `json:"salesGrowth"`
	SalesStability float64 `json:"salesStability"`
	EPSLevel       float64 `json:"epsLevel"`
	EPSGrowth      float64 `json:"epsGrowth"`
}

type CompanyScore struct {
	CompanyID   string  `json:"companyID"`
	CompanyName string  `json:"companyName"`
	EPSGrowth   float64 `json:"epsGrowth"`
	SalesGrowth float64 `json:"salesGrowth"`
}

type EPSRecord struct {
	CompanyID   string
	CompanyName string
	ReportDate  string
	EPS         float64
}

type SalesData struct {
	CompanyName string  `json:"companyName"`
	CompanyID   string  `json:"companyID"`
	ReportDate  string  `json:"reportDate"`
	Product1    float64 `json:"Product1"`
	Product2    float64 `json:"Product2"`
	Product3    float64 `json:"Product3"`
	Percentage  float64 `json:"percentage"`
	WoW         int     `json:"wow"`
}

type CompanyName struct {
	CompanyName string `json:"companyName"`
}

type GetURLRequest struct {
	CompanyName string `json:"companyName"`
}

type GetURLResponse struct {
	URL string `json:"url"`
}

type SalesData2 struct {
	CompanyName string  `json:"companyName"`
	CompanyID   string  `json:"companyID"`
	ReportDate  string  `json:"reportDate"`
	Value1      float64 `json:"value1"`
	Value2      float64 `json:"value2"`
	Value3      float64 `json:"value3"`
	Percentage  float64 `json:"percentage"`
	WoW         int     `json:"wow"`
}

type User struct {
	gorm.Model
	Username string `gorm:"uniqueIndex" json:"username"`
	Password string `json:"password"` // store hashed password only
}
