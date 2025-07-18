package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"strings"

	"go-app/config"

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
	db := config.GetDB()
	defer db.Close()

	// companyName := c.Query("companyName")
	// if companyName == "" {
	// 	c.JSON(http.StatusBadRequest, gin.H{"error": "companyName query parameter is required"})
	// 	return
	// }

	// param := "%" + companyName + "%"

	// // Queries with filters
	// salesQuery := `SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane WHERE CompanyName LIKE @companyName`
	// epsQuery := `SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2 WHERE CompanyName LIKE @companyName`
	// fullPEQuery := `SELECT CompanyName, PE, Price FROM codal.dbo.FullPE WHERE CompanyName LIKE @companyName`

	companyName := strings.TrimSpace(c.Query("companyName"))
	param := companyName + "%"

	salesQuery := `SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName)) + '%'`
	epsQuery := `SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2 WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName)) + '%'`
	fullPEQuery := `SELECT CompanyName, PE, Price FROM codal.dbo.FullPE WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName)) + '%'`

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
		if len(eps) >= 8 {
			recent := mean(eps[len(eps)-4:])
			previous := mean(eps[len(eps)-8 : len(eps)-4])
			if previous != 0 {
				epsGrowth = ((recent - previous) / math.Abs(previous)) * 100
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
	}

	c.JSON(http.StatusOK, results)
}
