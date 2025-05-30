package handlers

import (
	"database/sql"
	"net/http"
	"time"

	"go-codal-app/config"

	_ "github.com/denisenkom/go-mssqldb"
	"github.com/gin-gonic/gin"
)

type StockRow struct {
	TradeDate time.Time
	Close     float64
	Volume    float64
}

func StockPriceScore(c *gin.Context) {
	ticker := c.Query("companyName")
	if ticker == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Missing required parameter: companyName"})
		return
	}

	ticker = normalizePersian(ticker)

	db := config.GetDB()
	defer db.Close()

	query := `SELECT TradeDate, [Close], Volume FROM dbo.StockData WHERE Ticker = @ticker ORDER BY TradeDate`

	rows, err := db.Query(query, sql.Named("ticker", ticker))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var data []StockRow
	for rows.Next() {
		var row StockRow
		if err := rows.Scan(&row.TradeDate, &row.Close, &row.Volume); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		data = append(data, row)
	}
	if len(data) == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "No data found"})
		return
	}

	// Process indicators
	closePrices := extract(data, func(r StockRow) float64 { return r.Close })
	volumes := extract(data, func(r StockRow) float64 { return r.Volume })

	ma20 := rollingMean(closePrices, 20)
	ma50 := rollingMean(closePrices, 50)
	prevClose := append([]float64{0}, closePrices[:len(closePrices)-1]...)
	avgVolume := rollingMean(volumes, 20)
	rsi := computeRSI(closePrices, 14)
	exp1 := ema(closePrices, 12)
	exp2 := ema(closePrices, 26)
	macd := subtractSeries(exp1, exp2)
	signal := ema(macd, 9)

	returns := percentChange(closePrices)
	volatility := rollingStdDev(returns, 20)
	momentum := subtractSeries(closePrices, shift(closePrices, 10))
	trend := rollingSlope(closePrices, 20)

	// Score (last row only)
	n := len(closePrices) - 1
	score := 0.0
	if ma20[n] > ma50[n] {
		score += 0.2
	}
	if closePrices[n] > prevClose[n] {
		score += 0.2
	}
	if volumes[n] > avgVolume[n] {
		score += 0.2
	}
	if rsi[n] > 30 && rsi[n] < 70 {
		score += 0.2
	}
	if macd[n] > signal[n] {
		score += 0.2
	}

	result := gin.H{
		"TradeDate":   data[n].TradeDate.Format("2006-01-02"),
		"Close":       round(closePrices[n], 2),
		"RSI":         round(rsi[n], 2),
		"MACD":        round(macd[n], 2),
		"Signal_Line": round(signal[n], 2),
		"Volatility":  round(volatility[n], 4),
		"Momentum":    round(momentum[n], 2),
		"Trend_Slope": round(trend[n], 5),
		"Score":       round(score*100, 2),
	}

	c.JSON(http.StatusOK, result)
}
