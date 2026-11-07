package handlers

import (
	"github.com/gin-gonic/gin"
	"go-app/integration"
	"sort"
	"strings"
)

// Exact single-company reads retain the score-detail contract. Market lists
// expose only approved presentation fields, never every factor for every stock.
func writeLimitedSummary(c *gin.Context, rows []integration.AllScoreInputRow) {
	selected := make([]integration.AllScoreInputRow, 0, len(rows))
	exact := strings.TrimSpace(c.Query("companyName"))
	id := strings.TrimSpace(c.Query("companyID"))
	search := normalizeFaText(c.Query("q"))
	if len(search) > 120 {
		c.JSON(400, gin.H{"error": "عبارت جست‌وجو طولانی است."})
		return
	}
	for _, row := range rows {
		if exact != "" && normalizeFaText(row.CompanyName) != normalizeFaText(exact) && normalizeFaText(row.Symbol) != normalizeFaText(exact) {
			continue
		}
		if id != "" && row.LegacyCompanyID != id {
			continue
		}
		if search != "" && !strings.Contains(normalizeFaText(row.CompanyName+" "+row.Symbol), search) {
			continue
		}
		selected = append(selected, row)
	}
	metrics := buildCanonicalSummary(selected, 0)
	sortKey := c.DefaultQuery("sort", "quant_score")
	order := c.DefaultQuery("order", "desc")
	if order != "asc" && order != "desc" {
		c.JSON(400, gin.H{"error": "ترتیب معتبر نیست."})
		return
	}
	if sortKey != "quant_score" && sortKey != "company_name" && sortKey != "latest_price" {
		c.JSON(400, gin.H{"error": "ستون مرتب‌سازی مجاز نیست."})
		return
	}
	sort.SliceStable(metrics, func(i, j int) bool {
		a, b := metrics[i], metrics[j]
		comparison := 0
		switch sortKey {
		case "company_name":
			comparison = strings.Compare(a.CompanyName, b.CompanyName)
		case "latest_price":
			av, bv := 0.0, 0.0
			if a.LatestPrice != nil {
				av = *a.LatestPrice
			}
			if b.LatestPrice != nil {
				bv = *b.LatestPrice
			}
			if av < bv {
				comparison = -1
			} else if av > bv {
				comparison = 1
			}
		default:
			if a.QuantScore < b.QuantScore {
				comparison = -1
			} else if a.QuantScore > b.QuantScore {
				comparison = 1
			}
		}
		if comparison == 0 {
			return a.CompanyID < b.CompanyID
		}
		if order == "asc" {
			return comparison < 0
		}
		return comparison > 0
	})
	start, end, ok := dataPage(c, len(metrics))
	if !ok {
		return
	}
	if exact != "" || id != "" {
		c.JSON(200, metrics[start:end])
		return
	}
	result := make([]gin.H, 0, end-start)
	for _, row := range metrics[start:end] {
		result = append(result, gin.H{"company_id": row.CompanyID, "symbol": row.Symbol, "company_name": row.CompanyName, "quant_score": row.QuantScore, "data_quality_score": row.DataQualityScore, "has_enough_data": row.HasEnoughData, "latest_price": row.LatestPrice, "pe_approx": row.PEApprox, "sales_growth_12m": row.SalesGrowth12M, "net_profit_growth_4_reports": row.NetProfitGrowth4Reports, "latest_market_date": row.LatestMarketDate, "score_version": row.ScoreVersion})
	}
	c.JSON(200, result)
}
