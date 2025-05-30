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

	query := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"
	rows, err := db.Query(query)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var data []models.EPSRecord
	for rows.Next() {
		var record models.EPSRecord
		// var product1 sql.NullFloat64

		// if err := rows.Scan(&record.CompanyID, &record.CompanyName, &record.ReportDate, &product1); err != nil {
		// 	c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		// 	return
		// }
		var product1 sql.NullFloat64
		if err := rows.Scan(&record.CompanyID, &record.CompanyName, &record.ReportDate, &product1); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		if product1.Valid {
			record.EPS = product1.Float64
		} else {
			record.EPS = 0
		}
		data = append(data, record)
	}

	// Group EPS by company
	epsMap := make(map[string][]float64)
	nameMap := make(map[string]string)

	for _, rec := range data {
		epsMap[rec.CompanyID] = append(epsMap[rec.CompanyID], rec.EPS)
		nameMap[rec.CompanyID] = rec.CompanyName
	}

	// Calculate EPS growth
	var scores []models.CompanyScore
	for companyID, epsSeries := range epsMap {
		var growth float64
		if len(epsSeries) >= 8 {
			recent := mean(epsSeries[len(epsSeries)-4:])
			previous := mean(epsSeries[len(epsSeries)-8 : len(epsSeries)-4])
			if previous != 0 {
				growth = ((recent - previous) / math.Abs(previous)) * 100
			}
		}
		scores = append(scores, models.CompanyScore{
			CompanyID:   companyID,
			CompanyName: nameMap[companyID],
			EPSGrowth:   roundFloat(growth, 2),
		})
	}

	// Sort scores descending
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].EPSGrowth > scores[j].EPSGrowth
	})

	c.JSON(http.StatusOK, scores)
}

func mean(values []float64) float64 {
	sum := 0.0
	for _, v := range values {
		sum += v
	}
	return sum / float64(len(values))
}

// func roundFloat(val float64, places int) float64 {
// 	pow := math.Pow(10, float64(places))
// 	return math.Round(val*pow) / pow
// }
