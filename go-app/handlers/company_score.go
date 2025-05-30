package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"sort"

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

func GetCompanyScores2(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	companyName := c.Query("companyName")

	salesQuery := "SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane"
	epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"

	var salesRows, epsRows *sql.Rows
	var err error

	if companyName != "" {
		param := "%" + companyName + "%"
		salesQuery += " WHERE CompanyName LIKE @companyName"
		epsQuery += " WHERE CompanyName LIKE @companyName"
		salesRows, err = db.Query(salesQuery, sql.Named("companyName", param))
		if err == nil {
			epsRows, err = db.Query(epsQuery, sql.Named("companyName", param))
		}
	} else {
		salesRows, err = db.Query(salesQuery)
		if err == nil {
			epsRows, err = db.Query(epsQuery)
		}
	}

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer salesRows.Close()
	defer epsRows.Close()

	// Sales and EPS time series
	salesMap := make(map[string][]float64)
	epsMap := make(map[string][]float64)
	nameMap := make(map[string]string)

	// Parse sales data
	for salesRows.Next() {
		var companyID, name, date string
		var value3 sql.NullFloat64
		if err := salesRows.Scan(&companyID, &name, &date, &value3); err == nil {
			salesMap[companyID] = append(salesMap[companyID], nullToFloat(value3))
			nameMap[companyID] = name
		}
	}

	// Parse EPS data
	for epsRows.Next() {
		var companyID, name, date string
		var product1 sql.NullFloat64
		if err := epsRows.Scan(&companyID, &name, &date, &product1); err == nil {
			epsMap[companyID] = append(epsMap[companyID], nullToFloat(product1))
			if _, ok := nameMap[companyID]; !ok {
				nameMap[companyID] = name
			}
		}
	}

	if len(salesMap) == 0 && len(epsMap) == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "No data found"})
		return
	}

	// Scoring
	allCompanies := make(map[string]bool)
	for k := range salesMap {
		allCompanies[k] = true
	}
	for k := range epsMap {
		allCompanies[k] = true
	}

	scoreList := []rawMetric{}
	for companyID := range allCompanies {
		sales := salesMap[companyID]
		eps := epsMap[companyID]

		// Sales Growth
		var salesGrowth float64
		if len(sales) >= 24 {
			recent := mean(sales[len(sales)-12:])
			previous := mean(sales[len(sales)-24 : len(sales)-12])
			if previous != 0 {
				salesGrowth = roundFloat((recent-previous)/math.Abs(previous)*100, 2)
			}
		}

		// Sales Stability
		var stability float64
		if len(sales) > 1 {
			avg := mean(sales)
			if avg != 0 {
				stability = 1 - stdDev(sales)/avg
			}
		}

		// EPS Level and Growth
		epsLevel := mean(eps)
		var epsGrowth float64
		if len(eps) >= 8 {
			recent := mean(eps[len(eps)-4:])
			previous := mean(eps[len(eps)-8 : len(eps)-4])
			if previous != 0 {
				epsGrowth = roundFloat((recent-previous)/math.Abs(previous)*100, 2)
			}
		}

		scoreList = append(scoreList, rawMetric{
			CompanyID:      companyID,
			CompanyName:    nameMap[companyID],
			SalesGrowth:    salesGrowth,
			SalesStability: stability,
			EPSLevel:       epsLevel,
			EPSGrowth:      epsGrowth,
		})
	}

	// MinMax normalize across all companies
	normalizeFields(&scoreList)

	// Final scoring formula
	for i := range scoreList {
		s := &scoreList[i]
		s.FinalScore = 0.3*s.SalesGrowth + 0.2*s.SalesStability + 0.3*s.EPSLevel + 0.2*s.EPSGrowth
	}

	// Format output
	sort.Slice(scoreList, func(i, j int) bool {
		return scoreList[i].FinalScore > scoreList[j].FinalScore
	})

	var result []gin.H
	for _, s := range scoreList {
		result = append(result, gin.H{
			"companyID":      s.CompanyID,
			"companyName":    s.CompanyName,
			"finalScore":     roundFloat(s.FinalScore, 4),
			"salesGrowth":    roundFloat(s.SalesGrowth, 4),
			"salesStability": roundFloat(s.SalesStability, 4),
			"epsLevel":       roundFloat(s.EPSLevel, 4),
			"epsGrowth":      roundFloat(s.EPSGrowth, 4),
		})
	}

	c.JSON(http.StatusOK, result)
}

// --- Helpers ---

// func mean(arr []float64) float64 {
// 	if len(arr) == 0 {
// 		return 0
// 	}
// 	sum := 0.0
// 	for _, v := range arr {
// 		sum += v
// 	}
// 	return sum / float64(len(arr))
// }

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

func nullToFloat(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}

func normalizeFields(scores *[]rawMetric) {
	minMax := func(get func(r rawMetric) float64) (min, max float64) {
		min, max = math.MaxFloat64, -math.MaxFloat64
		for _, r := range *scores {
			v := get(r)
			if v < min {
				min = v
			}
			if v > max {
				max = v
			}
		}
		if min == max {
			return 0, 1
		}
		return
	}

	fields := []struct {
		get  func(r rawMetric) float64
		set  func(r *rawMetric, v float64)
		name string
	}{
		{func(r rawMetric) float64 { return r.SalesGrowth }, func(r *rawMetric, v float64) { r.SalesGrowth = v }, "SalesGrowth"},
		{func(r rawMetric) float64 { return r.SalesStability }, func(r *rawMetric, v float64) { r.SalesStability = v }, "SalesStability"},
		{func(r rawMetric) float64 { return r.EPSLevel }, func(r *rawMetric, v float64) { r.EPSLevel = v }, "EPSLevel"},
		{func(r rawMetric) float64 { return r.EPSGrowth }, func(r *rawMetric, v float64) { r.EPSGrowth = v }, "EPSGrowth"},
	}

	for _, f := range fields {
		min, max := minMax(f.get)
		rangeVal := max - min
		if rangeVal == 0 {
			rangeVal = 1
		}
		for i := range *scores {
			orig := f.get((*scores)[i])
			norm := (orig - min) / rangeVal
			f.set(&(*scores)[i], norm)
		}
	}
}
