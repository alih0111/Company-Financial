package handlers

import (
	"go-codal-app/config"
	"go-codal-app/models"
	"math"
	"net/http"
	"sort"

	"github.com/gin-gonic/gin"
)

type DataRecord struct {
	CompanyID   int
	CompanyName string
	ReportDate  string
	Value       float64
}

func GetCompanyScores(c *gin.Context) {
	companyName := c.Query("companyName")

	salesQuery := "SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane"
	epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"
	var params []interface{}
	if companyName != "" {
		salesQuery += " WHERE CompanyName LIKE ?"
		epsQuery += " WHERE CompanyName LIKE ?"
		params = append(params, "%"+companyName+"%")
	}

	db, err := config.GetDBConnection()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer db.Close()

	salesRows, err := db.Query(salesQuery, params...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer salesRows.Close()

	epsRows, err := db.Query(epsQuery, params...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer epsRows.Close()

	type record struct {
		CompanyID   int
		CompanyName string
		ReportDate  string
		Value       float64
	}

	salesData := make(map[int][]DataRecord)
	epsData := make(map[int][]DataRecord)

	for salesRows.Next() {
		var id int
		var name, date string
		var v float64
		salesRows.Scan(&id, &name, &date, &v)
		salesData[id] = append(salesData[id], DataRecord{id, name, date, v})
	}

	for epsRows.Next() {
		var id int
		var name, date string
		var v float64
		epsRows.Scan(&id, &name, &date, &v)
		epsData[id] = append(epsData[id], DataRecord{id, name, date, v})
	}

	results := []models.ScoreResult{}

	for companyID, sales := range salesData {
		eps, ok := epsData[companyID]
		if !ok {
			continue
		}

		sort.Slice(sales, func(i, j int) bool {
			return sales[i].ReportDate < sales[j].ReportDate
		})
		sort.Slice(eps, func(i, j int) bool {
			return eps[i].ReportDate < eps[j].ReportDate
		})

		salesVals := extractValues(sales)
		epsVals := extractValues(eps)

		if len(salesVals) < 2 || len(epsVals) < 2 {
			continue
		}

		salesGrowth := computeGrowth(salesVals)
		salesStability := computeStability(salesVals)
		epsLevel := mean(epsVals)
		epsGrowth := computeYearlyGrowth(epsVals)

		scores := models.ScoreResult{
			CompanyID:      companyID,
			CompanyName:    sales[0].CompanyName,
			SalesGrowth:    salesGrowth,
			SalesStability: salesStability,
			EPSLevel:       epsLevel,
			EPSGrowth:      epsGrowth,
		}
		results = append(results, scores)
	}

	// Normalize
	norm := normalizeScores(results)

	// Sort by FinalScore descending
	sort.Slice(norm, func(i, j int) bool {
		return norm[i].FinalScore > norm[j].FinalScore
	})

	c.JSON(http.StatusOK, norm)
}

func extractValues(records []DataRecord) []float64 {
	vals := []float64{}
	for _, r := range records {
		vals = append(vals, r.Value)
	}
	return vals
}

func mean(vals []float64) float64 {
	if len(vals) == 0 {
		return 0
	}
	sum := 0.0
	for _, v := range vals {
		sum += v
	}
	return sum / float64(len(vals))
}

func computeStability(vals []float64) float64 {
	avg := mean(vals)
	if avg == 0 {
		return 0
	}
	variance := 0.0
	for _, v := range vals {
		variance += math.Pow(v-avg, 2)
	}
	variance /= float64(len(vals))
	std := math.Sqrt(variance)
	return 1 - (std / avg)
}

func computeGrowth(vals []float64) float64 {
	if len(vals) < 24 {
		return 0
	}
	currYear := mean(vals[len(vals)-12:])
	prevYear := mean(vals[len(vals)-24 : len(vals)-12])
	if prevYear == 0 {
		return 0
	}
	return round(((currYear - prevYear) / math.Abs(prevYear)) * 100)
}

func computeYearlyGrowth(vals []float64) float64 {
	if len(vals) < 8 {
		return 0
	}
	curr := mean(vals[len(vals)-4:])
	prev := mean(vals[len(vals)-8 : len(vals)-4])
	if prev == 0 {
		return 0
	}
	return round(((curr - prev) / math.Abs(prev)) * 100)
}

func round(val float64) float64 {
	return math.Round(val*100) / 100
}

func normalizeScores(scores []models.ScoreResult) []models.ScoreResult {
	mins := models.ScoreResult{SalesGrowth: math.MaxFloat64, SalesStability: math.MaxFloat64, EPSLevel: math.MaxFloat64, EPSGrowth: math.MaxFloat64}
	maxs := models.ScoreResult{}

	for _, s := range scores {
		if s.SalesGrowth < mins.SalesGrowth {
			mins.SalesGrowth = s.SalesGrowth
		}
		if s.SalesStability < mins.SalesStability {
			mins.SalesStability = s.SalesStability
		}
		if s.EPSLevel < mins.EPSLevel {
			mins.EPSLevel = s.EPSLevel
		}
		if s.EPSGrowth < mins.EPSGrowth {
			mins.EPSGrowth = s.EPSGrowth
		}
		if s.SalesGrowth > maxs.SalesGrowth {
			maxs.SalesGrowth = s.SalesGrowth
		}
		if s.SalesStability > maxs.SalesStability {
			maxs.SalesStability = s.SalesStability
		}
		if s.EPSLevel > maxs.EPSLevel {
			maxs.EPSLevel = s.EPSLevel
		}
		if s.EPSGrowth > maxs.EPSGrowth {
			maxs.EPSGrowth = s.EPSGrowth
		}
	}

	for i := range scores {
		n := &scores[i]
		norm := func(val, min, max float64) float64 {
			if max == min {
				return 0
			}
			return (val - min) / (max - min)
		}
		n.FinalScore = 0.3*norm(n.SalesGrowth, mins.SalesGrowth, maxs.SalesGrowth) +
			0.2*norm(n.SalesStability, mins.SalesStability, maxs.SalesStability) +
			0.3*norm(n.EPSLevel, mins.EPSLevel, maxs.EPSLevel) +
			0.2*norm(n.EPSGrowth, mins.EPSGrowth, maxs.EPSGrowth)
	}

	return scores
}
