package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"strings"
	"time"

	"go-app/config"
	"go-app/integration"

	"github.com/gin-gonic/gin"
)

type rawMetric struct {
	SalesGrowth    float64
	SalesStability float64
	EPSLevel       float64
	EPSGrowth      float64
	FinalScore     float64
	CompanyID      string
	CompanyName    string
}

type FullPEData struct {
	PE    float64
	Price float64
}

func nullToFloat(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}

func stdDev(data []float64) float64 {
	if len(data) <= 1 {
		return 0
	}
	meanVal := mean(data)
	var variance float64
	for _, val := range data {
		diff := val - meanVal
		variance += diff * diff
	}
	return math.Sqrt(variance / float64(len(data)))
}

func roundFloat(val float64, places int) float64 {
	pow := math.Pow(10, float64(places))
	return math.Round(val*pow) / pow
}

// Optional: simple sigmoid-based normalization
func normalize(x float64) float64 {
	return 1 / (1 + math.Exp(-x/10))
}

func GetCompanyScores2(c *gin.Context) {
	start := time.Now()

	companyName := strings.TrimSpace(c.Query("companyName"))

	// CANONICAL-FIRST: serve the canonical per-company score without touching
	// SQL Server when routed canonically.
	sh := integration.Default()
	if companyName != "" && sh.CompanyScoresRoute(companyName) == integration.RouteCanary {
		b, err := sh.FetchCompanyScoreCanonical(c.Request.Context(), companyName)
		if err == nil {
			if b.HasScore {
				c.JSON(http.StatusOK, []gin.H{companyScoreCanonicalResponse(b)})
			} else {
				c.JSON(http.StatusOK, []gin.H{}) // explicit no-score state
			}
			return
		}
		if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical score unavailable", "reason": "sqlserver_offline_expected"})
			return
		}
	}

	db := config.GetDB()
	defer db.Close()

	param := companyName

	salesQuery := `SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))`
	epsQuery := `SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2 WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))`
	fullPEQuery := `SELECT CompanyName, PE, Price FROM codal.dbo.FullPE WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))`

	salesRows, err := db.Query(salesQuery, sql.Named("companyName", param))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "sales query error: " + err.Error()})
		return
	}
	defer salesRows.Close()

	epsRows, err := db.Query(epsQuery, sql.Named("companyName", param))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "eps query error: " + err.Error()})
		return
	}
	defer epsRows.Close()

	fullPERows, err := db.Query(fullPEQuery, sql.Named("companyName", param))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "fullPE query error: " + err.Error()})
		return
	}
	defer fullPERows.Close()

	// Maps
	salesMap := make(map[string][]float64)
	epsMap := make(map[string][]float64)
	nameMap := make(map[string]string)
	fullPEMap := make(map[string]FullPEData)

	// Load Sales
	for salesRows.Next() {
		var id, name, date string
		var value sql.NullFloat64
		if err := salesRows.Scan(&id, &name, &date, &value); err == nil {
			salesMap[id] = append(salesMap[id], nullToFloat(value))
			nameMap[id] = name
		}
	}

	// Load EPS
	for epsRows.Next() {
		var id, name, date string
		var value sql.NullFloat64
		if err := epsRows.Scan(&id, &name, &date, &value); err == nil {
			epsMap[id] = append(epsMap[id], nullToFloat(value))
			if _, exists := nameMap[id]; !exists {
				nameMap[id] = name
			}
		}
	}

	// Load PE
	for fullPERows.Next() {
		var name string
		var pe, price sql.NullFloat64
		if err := fullPERows.Scan(&name, &pe, &price); err == nil {
			fullPEMap[name] = FullPEData{PE: nullToFloat(pe), Price: nullToFloat(price)}
		}
	}

	if len(salesMap) == 0 && len(epsMap) == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "Company not found"})
		return
	}

	var results []gin.H
	var legacyRows []integration.CompanyScoreInputRow
	for id := range nameMap {
		sales := salesMap[id]
		eps := epsMap[id]
		name := nameMap[id]

		// Sales growth
		var salesGrowth float64
		if len(sales) >= 24 {
			recent := mean(sales[len(sales)-12:])
			previous := mean(sales[len(sales)-24 : len(sales)-12])
			if previous != 0 {
				salesGrowth = ((recent - previous) / math.Abs(previous)) * 100
			}
		}

		// EPS growth
		var epsGrowth float64
		// if len(eps) >= 8 {
		// 	recent := sum(eps[len(eps)-4:])
		// 	previous := sum(eps[len(eps)-8 : len(eps)-4])
		// 	if previous != 0 {
		// 		epsGrowth = ((recent - previous) / math.Abs(previous)) * 100
		// 	}
		// }
		// else if len(eps) >= 5 {
		// 	current := eps[len(eps)-1]  // e.g. 1404/09/30
		// 	lastYear := eps[len(eps)-5] // e.g. 1403/09/30

		// 	if lastYear != 0 {
		// 		epsGrowth = ((current - lastYear) / math.Abs(lastYear)) * 100
		// 	}
		// }
		if len(eps) >= 8 {
			recent := float64(mean(eps[len(eps)-4:]))
			previous := float64(mean(eps[len(eps)-8 : len(eps)-4]))
			if previous != 0 {
				epsGrowth = ((recent - previous) / math.Abs(previous)) * 100
			}
		} else if len(eps) >= 5 {
			current := float64(eps[len(eps)-1])
			lastYear := float64(eps[len(eps)-5])
			if lastYear != 0 {
				epsGrowth = ((current - lastYear) / math.Abs(lastYear)) * 100
			}
		}

		// Stability
		var stability float64
		if len(sales) > 1 {
			avg := mean(sales)
			if avg != 0 {
				stability = 1 - stdDev(sales)/avg
			}
		}

		// EPS Level
		epsLevel := mean(eps)

		// Final Score (after normalization, could improve this part later)
		score := 0.3*normalize(salesGrowth) + 0.2*normalize(stability) + 0.3*normalize(epsLevel) + 0.2*normalize(epsGrowth)

		// PE and Price
		peData := fullPEMap[name]

		results = append(results, gin.H{
			"companyID":      id,
			"companyName":    name,
			"salesGrowth":    roundFloat(salesGrowth, 2),
			"salesStability": roundFloat(stability, 2),
			"epsLevel":       roundFloat(epsLevel, 2),
			"epsGrowth":      roundFloat(epsGrowth, 2),
			"PE":             roundFloat(peData.PE, 2),
			"Price":          roundFloat(peData.Price, 2),
			"finalScore":     roundFloat(score, 4),
		})
		legacyRows = append(legacyRows, integration.CompanyScoreInputRow{
			LegacyCompanyID: id,
			CompanyName:     name,
			SalesGrowth:     roundFloat(salesGrowth, 2),
			EPSGrowth:       roundFloat(epsGrowth, 2),
			FinalScore:      roundFloat(score, 4),
			PE:              roundFloat(peData.PE, 2),
			Price:           roundFloat(peData.Price, 2),
		})
	}

	// SHADOW: compare canonical analytics against the legacy per-company score
	// read. The legacy response below is authoritative and unchanged.
	if sh.Enabled() {
		for _, row := range legacyRows {
			sh.CompareCompanyScores(c.Request.Context(), row, time.Since(start))
		}
	}

	c.JSON(http.StatusOK, results)
}

// companyScoreCanonicalResponse maps a canonical score bundle to the legacy
// CompanyScores response shape. Category/factor values are canonical stored
// values; Go performs no scoring arithmetic.
func companyScoreCanonicalResponse(b integration.CompanyScoreBundle) gin.H {
	// Growth/operation donut values are canonical factor percentiles (0..100);
	// raw factor values are not materialized by canonical-v1, so this rank-based
	// score is the honest presentation (documented in SYMBOL_PAGE_UI_CONTRACT.md).
	pct := func(code string) float64 {
		for _, f := range b.Factors {
			if f.FactorCode == code {
				return roundFloat(f.Percentile*100, 2)
			}
		}
		return 0
	}
	return gin.H{
		"companyID":      b.LegacyCompanyID,
		"companyName":    b.CompanyName,
		"salesGrowth":    pct("SalesGrowth"),
		"salesStability": pct("Stability"),
		"epsLevel":       pct("NetMargin"),
		"epsGrowth":      pct("NetProfitGrowth"),
		"operation":      pct("OperatingMargin"),
		"PE":             0,
		"Price":          roundFloat(b.LatestPrice, 2),
		"finalScore":     roundFloat(b.QuantScore, 4),
		"quantScore":     roundFloat(b.QuantScore, 4),
		"growthScore":    roundFloat(b.GrowthScore, 2),
		"profitabilityScore": roundFloat(b.ProfitabilityScore, 2),
		"valuationScore": roundFloat(b.ValuationScore, 2),
		"marketScore":    roundFloat(b.MarketScore, 2),
		"dataQualityScore": roundFloat(b.DataQualityScore, 2),
		"scoreVersion":   b.ScoreVersion,
		"scoreAsOf":      b.Metadata.ScoreAsOf,
		"dataAsOf":       b.Metadata.FundamentalsAsOf,
		"scoreStale":     b.Metadata.Stale,
	}
}
