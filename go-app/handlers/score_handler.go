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

	// Query FullPE data
	fullPEQuery := "SELECT TOP (1000) ID, CompanyName, PE, Price, LastModified FROM codal.dbo.FullPE"
	fullPERows, err := db.Query(fullPEQuery)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer fullPERows.Close()

	// Parse FullPE data into a map
	type FullPEData struct {
		PE    float64
		Price float64
	}
	fullPEMap := make(map[string]FullPEData)

	for fullPERows.Next() {
		var id int
		var companyName string
		var pe, price sql.NullFloat64
		var lastModified sql.NullTime

		if err := fullPERows.Scan(&id, &companyName, &pe, &price, &lastModified); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		fullPEMap[companyName] = FullPEData{
			PE:    nullToFloat(pe),
			Price: nullToFloat(price),
		}
	}

	// Parse sales data
	salesMap := make(map[string][]float64)
	nameMap := make(map[string]string)

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

	// Parse EPS data
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

	// Merge results
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
		name := nameMap[companyID]

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

		// Get PE and Price from FullPEMap
		peData := fullPEMap[name]

		scores = append(scores, models.CompanyScore{
			CompanyID:   companyID,
			CompanyName: name,
			SalesGrowth: roundFloat(salesGrowth, 2),
			EPSGrowth:   roundFloat(epsGrowth, 2),
			PE:          roundFloat(peData.PE, 2),
			Price:       roundFloat(peData.Price, 2),
		})
	}

	// Sort by EPS growth descending
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].EPSGrowth > scores[j].EPSGrowth
	})

	c.JSON(http.StatusOK, scores)
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
