package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"sort"
	"time"

	"go-app/config"
	"go-app/integration"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

type EPSMetrics struct {
	Product1s               []float64
	OperatingProfitNews     []float64
	OperatingProfitLastYear []float64
	RevenueNews             []float64
}

func GetCompanyScores(c *gin.Context) {
	start := time.Now()

	// CANONICAL-FIRST: serve the canonical all-company score list without
	// touching SQL Server when routed canonically.
	sh := integration.Default()
	if sh.AllCompanyScoresRoute() == integration.RouteCanary {
		if rows, err := sh.FetchAllScoresCanonical(c.Request.Context()); err == nil && len(rows) > 0 {
			c.JSON(http.StatusOK, allScoresCanonicalResponse(rows))
			return
		} else if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical scores unavailable; SQL Server is offline_expected"})
			return
		}
	}

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
	epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1, OperatingProfitNew, OperatingProfitLastYear, RevenueNew FROM miandore2"
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
		var product1, operatingProfitNew, OperatingProfitLastYear, revenueNew sql.NullFloat64

		if err := epsRows.Scan(&companyID, &companyName, &reportDate, &product1, &operatingProfitNew, &OperatingProfitLastYear, &revenueNew); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		if _, exists := epsMap[companyID]; !exists {
			epsMap[companyID] = &EPSMetrics{}
		}

		epsMap[companyID].Product1s = append(epsMap[companyID].Product1s, nullToFloat(product1))
		epsMap[companyID].OperatingProfitNews = append(epsMap[companyID].OperatingProfitNews, nullToFloat(operatingProfitNew))
		epsMap[companyID].OperatingProfitLastYear = append(epsMap[companyID].OperatingProfitLastYear, nullToFloat(OperatingProfitLastYear))
		epsMap[companyID].RevenueNews = append(epsMap[companyID].RevenueNews, nullToFloat(revenueNew))

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

			if len(epsData.OperatingProfitNews) > 0 && len(epsData.RevenueNews) > 0 {
				opNew := epsData.OperatingProfitNews[len(epsData.OperatingProfitNews)-1]
				revenue := epsData.RevenueNews[len(epsData.RevenueNews)-1]

				if !math.IsNaN(opNew) && !math.IsNaN(revenue) && revenue != 0 {
					operation = opNew / revenue * 100
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

	// SHADOW: compare canonical analytics against the legacy all-company score
	// list. The legacy response below is authoritative and unchanged.
	if sh.Enabled() {
		legacyRows := make([]integration.AllScoreInputRow, 0, len(scores))
		for _, s := range scores {
			legacyRows = append(legacyRows, integration.AllScoreInputRow{
				LegacyCompanyID: s.CompanyID,
				CompanyName:     s.CompanyName,
				SalesGrowth:     s.SalesGrowth,
				EPSGrowth:       s.EPSGrowth,
				PE:              s.PE,
				Price:           s.Price,
				Operation:       s.Operation,
				Stable:          s.Stable,
			})
		}
		sh.CompareAllCompanyScores(c.Request.Context(), legacyRows, time.Since(start))
	}

	c.JSON(http.StatusOK, scores)
}

// allScoresCanonicalResponse maps canonical all-company scores to the legacy
// CompanyScore shape. Compatibility fields are populated from canonical factors
// where a canonical meaning exists; the legacy `Stable` heuristic has no
// canonical equivalent and is emitted as false (documented).
func allScoresCanonicalResponse(rows []integration.AllScoreInputRow) []models.CompanyScore {
	out := make([]models.CompanyScore, 0, len(rows))
	for _, r := range rows {
		out = append(out, models.CompanyScore{
			CompanyID:   r.LegacyCompanyID,
			CompanyName: r.CompanyName,
			SalesGrowth: roundFloat(r.SalesGrowth, 2),
			EPSGrowth:   roundFloat(r.EPSGrowth, 2),
			PE:          roundFloat(r.PE, 2),
			Price:       roundFloat(r.Price, 2),
			Stable:      false,
			Operation:   roundFloat(r.Operation, 2),
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EPSGrowth > out[j].EPSGrowth })
	return out
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
