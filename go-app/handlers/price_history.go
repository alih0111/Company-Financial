package handlers

import (
	"database/sql"
	"net/http"
	"strings"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

type PriceHistoryRow struct {
	Date           string  `json:"date"`
	JalaliDate     string  `json:"jalali_date"`
	ClosingPrice   float64 `json:"closing_price"`
	LastPrice      float64 `json:"last_price"`
	HighPrice      float64 `json:"high_price"`
	LowPrice       float64 `json:"low_price"`
	Volume         float64 `json:"volume"`
	TradeValue     float64 `json:"trade_value"`
	ChangePercent  float64 `json:"change_percent"`
}

// GetPriceHistory تاریخچه‌ی قیمت یک نماد را از MarketPriceHistory برمی‌گرداند.
// پارامتر companyName (نماد یا نام شرکت) و اختیاریاً limit (پیش‌فرض ۳۶۵ روز).
func GetPriceHistory(c *gin.Context) {
	companyName := strings.TrimSpace(c.Query("companyName"))
	if companyName == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "companyName is required"})
		return
	}

	limit := parseIntQuery(c, "limit", 365)
	if limit > 5000 {
		limit = 5000
	}

	companyName = normalizePersian(companyName)

	db := config.GetDB()
	defer db.Close()

	query := `
		SELECT TOP (@limit)
			CONVERT(NVARCHAR(20), GregorianDate, 23) AS gdate,
			ISNULL(JalaliDate, '') AS jdate,
			ISNULL(ClosingPrice, 0) AS [close],
			ISNULL(LastPrice, 0) AS [last],
			ISNULL(HighPrice, 0) AS [high],
			ISNULL(LowPrice, 0) AS [low],
			ISNULL(Volume, 0) AS [vol],
			ISNULL(TradeValue, 0) AS [tval],
			ISNULL(ClosingChangePercent, 0) AS [chg]
		FROM dbo.MarketPriceHistory
		WHERE CompanyName = @name OR Symbol = @name
		ORDER BY GregorianDate DESC
	`

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("name", companyName),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	result := make([]PriceHistoryRow, 0)
	for rows.Next() {
		var r PriceHistoryRow
		if err := rows.Scan(
			&r.Date, &r.JalaliDate, &r.ClosingPrice, &r.LastPrice,
			&r.HighPrice, &r.LowPrice, &r.Volume, &r.TradeValue,
			&r.ChangePercent,
		); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		result = append(result, r)
	}

	c.JSON(http.StatusOK, result)
}
