package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"sort"

	"go-app/config"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

func GetCompanyScores(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	// Query sales data
	salesQuery := "SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane"
	salesRows, err := db.Query(salesQuery)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer salesRows.Close()

	// Query EPS data
	epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"
	epsRows, err := db.Query(epsQuery)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer epsRows.Close()

	// Parse sales data into map[CompanyID][]float64
	salesMap := make(map[string][]float64)
	nameMap := make(map[string]string) // CompanyID -> CompanyName

	for salesRows.Next() {
		var companyID, companyName, reportDate string
		var value3 sql.NullFloat64
		if err := salesRows.Scan(&companyID, &companyName, &reportDate, &value3); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		salesMap[companyID] = append(salesMap[companyID], nullToFloat(value3))
		nameMap[companyID] = companyName
	}

	// Parse EPS data into map[CompanyID][]float64
	epsMap := make(map[string][]float64)
	for epsRows.Next() {
		var companyID, companyName, reportDate string
		var product1 sql.NullFloat64
		if err := epsRows.Scan(&companyID, &companyName, &reportDate, &product1); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		epsMap[companyID] = append(epsMap[companyID], nullToFloat(product1))
		if _, ok := nameMap[companyID]; !ok {
			nameMap[companyID] = companyName
		}
	}

	// Calculate scores for companies appearing in either sales or EPS data
	companies := make(map[string]bool)
	for id := range salesMap {
		companies[id] = true
	}
	for id := range epsMap {
		companies[id] = true
	}

	var scores []models.CompanyScore
	for companyID := range companies {
		sales := salesMap[companyID]
		eps := epsMap[companyID]

		// Calculate sales growth
		var salesGrowth float64
		if len(sales) >= 24 {
			recent := mean(sales[len(sales)-12:])
			previous := mean(sales[len(sales)-24 : len(sales)-12])
			if previous != 0 {
				salesGrowth = ((recent - previous) / math.Abs(previous)) * 100
			}
		}

		// Calculate EPS growth
		var epsGrowth float64
		if len(eps) >= 8 {
			recent := mean(eps[len(eps)-4:])
			previous := mean(eps[len(eps)-8 : len(eps)-4])
			if previous != 0 {
				epsGrowth = ((recent - previous) / math.Abs(previous)) * 100
			}
		}

		scores = append(scores, models.CompanyScore{
			CompanyID:   companyID,
			CompanyName: nameMap[companyID],
			SalesGrowth: roundFloat(salesGrowth, 2),
			EPSGrowth:   roundFloat(epsGrowth, 2),
		})
	}

	// Sort by combined score or by EPS growth if you want; here sorted by EPSGrowth descending
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].EPSGrowth > scores[j].EPSGrowth
	})

	c.JSON(http.StatusOK, scores)
}

// func nullToFloat(n sql.NullFloat64) float64 {
// 	if n.Valid {
// 		return n.Float64
// 	}
// 	return 0
// }

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

// func roundFloat(val float64, places int) float64 {
// 	pow := math.Pow(10, float64(places))
// 	return math.Round(val*pow) / pow
// }

// func GetCompanyScores(c *gin.Context) {
// 	db := config.GetDB()
// 	defer db.Close()

// 	query := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"
// 	rows, err := db.Query(query)
// 	if err != nil {
// 		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
// 		return
// 	}
// 	defer rows.Close()

// 	var data []models.EPSRecord
// 	for rows.Next() {
// 		var record models.EPSRecord
// 		// var product1 sql.NullFloat64

// 		// if err := rows.Scan(&record.CompanyID, &record.CompanyName, &record.ReportDate, &product1); err != nil {
// 		// 	c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
// 		// 	return
// 		// }
// 		var product1 sql.NullFloat64
// 		if err := rows.Scan(&record.CompanyID, &record.CompanyName, &record.ReportDate, &product1); err != nil {
// 			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
// 			return
// 		}

// 		if product1.Valid {
// 			record.EPS = product1.Float64
// 		} else {
// 			record.EPS = 0
// 		}
// 		data = append(data, record)
// 	}

// 	// Group EPS by company
// 	epsMap := make(map[string][]float64)
// 	nameMap := make(map[string]string)

// 	for _, rec := range data {
// 		epsMap[rec.CompanyID] = append(epsMap[rec.CompanyID], rec.EPS)
// 		nameMap[rec.CompanyID] = rec.CompanyName
// 	}

// 	// Calculate EPS growth
// 	var scores []models.CompanyScore
// 	for companyID, epsSeries := range epsMap {
// 		var growth float64
// 		if len(epsSeries) >= 8 {
// 			recent := mean(epsSeries[len(epsSeries)-4:])
// 			previous := mean(epsSeries[len(epsSeries)-8 : len(epsSeries)-4])
// 			if previous != 0 {
// 				growth = ((recent - previous) / math.Abs(previous)) * 100
// 			}
// 		}
// 		scores = append(scores, models.CompanyScore{
// 			CompanyID:   companyID,
// 			CompanyName: nameMap[companyID],
// 			EPSGrowth:   roundFloat(growth, 2),
// 		})
// 	}

// 	// Sort scores descending
// 	sort.Slice(scores, func(i, j int) bool {
// 		return scores[i].EPSGrowth > scores[j].EPSGrowth
// 	})

// 	c.JSON(http.StatusOK, scores)
// }

// func mean(values []float64) float64 {
// 	sum := 0.0
// 	for _, v := range values {
// 		sum += v
// 	}
// 	return sum / float64(len(values))
// }

// func roundFloat(val float64, places int) float64 {
// 	pow := math.Pow(10, float64(places))
// 	return math.Round(val*pow) / pow
// }
