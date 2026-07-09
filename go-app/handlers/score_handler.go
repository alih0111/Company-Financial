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

type EPSMetrics struct {
	Product1s               []float64
	OperatingProfitNews     []float64
	OperatingProfitLastYear []float64
}

func GetCompanyScores(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	// Query sales data
	salesQuery := "SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane "
	salesRows, err := db.Query(salesQuery)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer salesRows.Close()

	// Query EPS data
	// epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2"
	epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1, OperatingProfitNew, OperatingProfitLastYear FROM miandore2"
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
	// epsMap := make(map[string][]float64)

	epsMap := make(map[string]*EPSMetrics)
	for epsRows.Next() {
		var companyID, companyName, reportDate string
		var product1, operatingProfitNew, OperatingProfitLastYear sql.NullFloat64

		if err := epsRows.Scan(&companyID, &companyName, &reportDate, &product1, &operatingProfitNew, &OperatingProfitLastYear); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		if _, exists := epsMap[companyID]; !exists {
			epsMap[companyID] = &EPSMetrics{}
		}

		epsMap[companyID].Product1s = append(epsMap[companyID].Product1s, nullToFloat(product1))
		epsMap[companyID].OperatingProfitNews = append(epsMap[companyID].OperatingProfitNews, nullToFloat(operatingProfitNew))
		epsMap[companyID].OperatingProfitLastYear = append(epsMap[companyID].OperatingProfitLastYear, nullToFloat(OperatingProfitLastYear))

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
		name := nameMap[companyID]

		var eps []float64
		var operation float64
		var epsGrowth float64
		var epsPositiveAndGrowing bool

		epsData, hasEPS := epsMap[companyID]
		if hasEPS && epsData != nil {
			eps = epsData.Product1s

			if len(epsData.OperatingProfitNews) > 0 && len(epsData.OperatingProfitLastYear) > 0 {
				opNew := epsData.OperatingProfitNews[len(epsData.OperatingProfitNews)-1]
				op := epsData.OperatingProfitLastYear[len(epsData.OperatingProfitLastYear)-1]

				if !math.IsNaN(opNew) && !math.IsNaN(op) && op != 0 {
					// operation = ((opNew-op)/math.Abs(op))*100
					operation = op / opNew * 100
					// operation = ((opNew - op) / math.Abs(op)) * 100
					// operation = opNew
				}
			}

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

			// EPS Positive and Growing
			// if len(eps) >= 16 {
			// 	epsPositiveAndGrowing = true
			// 	prevYearEPS := 0.0

			// 	for i := 4; i > 0; i-- {
			// 		start := len(eps) - i*4
			// 		end := start + 4
			// 		yearEPS := mean(eps[start:end])

			// 		if yearEPS <= 0 || (i < 4 && yearEPS <= prevYearEPS) {
			// 			epsPositiveAndGrowing = false
			// 			break
			// 		}
			// 		prevYearEPS = yearEPS
			// 	}
			// }
			// if len(eps) >= 8 && len(eps) < 16 {
			// 	epsPositiveAndGrowing = true
			// 	prevYearEPS := 0.0

			// 	for i := 2; i > 0; i-- {
			// 		start := len(eps) - i*4
			// 		end := start + 4
			// 		yearEPS := mean(eps[start:end])

			// 		if yearEPS <= 0 || (i < 2 && yearEPS <= prevYearEPS) {
			// 			epsPositiveAndGrowing = false
			// 			break
			// 		}
			// 		prevYearEPS = yearEPS
			// 	}
			// }

			const (
				quartersPerYear = 4
				maxYears        = 4
				minYears        = 2
				maxDropPercent  = 0.10
			)

			availableYears := len(eps) / quartersPerYear

			if availableYears >= minYears {
				yearsToCheck := availableYears
				if yearsToCheck > maxYears {
					yearsToCheck = maxYears
				}

				firstQuarter := len(eps) - yearsToCheck*quartersPerYear
				previousYearEPS := 0.0

				epsPositiveAndGrowing = true

				for year := 0; year < yearsToCheck; year++ {
					start := firstQuarter + year*quartersPerYear
					end := start + quartersPerYear

					// Quarterly EPS values should normally be summed.
					yearEPS := sum(eps[start:end])

					if yearEPS <= 0 {
						epsPositiveAndGrowing = false
						break
					}

					// Compare each year with the previous year.
					if year > 0 && yearEPS <= previousYearEPS*(1-maxDropPercent) {
						epsPositiveAndGrowing = false
						break
					}

					previousYearEPS = yearEPS
				}
			}

			// 40,000,000,000
			if (eps[len(eps)-1] / 100000000000) > 1 {
				epsPositiveAndGrowing = true
			}

			// epsGrowth := true

			for _, v := range eps[max(0, len(eps)-8):] {
				if v < 0 {
					epsPositiveAndGrowing = false
					break
				}
			}
			if len(eps) < 16 {
				epsPositiveAndGrowing = false
			}

		}

		// Sales growth always calculated
		var salesGrowth float64
		if len(sales) >= 24 {
			recent := mean(sales[len(sales)-12:])
			previous := mean(sales[len(sales)-24 : len(sales)-12])
			if previous != 0 {
				salesGrowth = ((recent - previous) / math.Abs(previous)) * 100
			}
		}

		// PE and price
		peData := fullPEMap[name]

		scores = append(scores, models.CompanyScore{
			CompanyID:   companyID,
			CompanyName: name,
			SalesGrowth: roundFloat(salesGrowth, 2),
			EPSGrowth:   roundFloat(epsGrowth, 2),
			PE:          roundFloat(peData.PE, 2),
			Price:       roundFloat(peData.Price, 2),
			Stable:      epsPositiveAndGrowing,
			Operation:   roundFloat(operation, 2),
		})
	}

	// Sort by EPS growth descending
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].EPSGrowth > scores[j].EPSGrowth
	})

	c.JSON(http.StatusOK, scores)
}

func sum(values []float64) float64 {
	total := 0.0

	for _, value := range values {
		total += value
	}

	return total
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
