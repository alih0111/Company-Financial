package handlers

import (
	"database/sql"
	"net/http"
	"strings"
	"time"

	"go-app/config"
	"go-app/integration"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

func GetSalesData(c *gin.Context) {
	start := time.Now()

	companyName := c.Query("companyName")

	// CANONICAL-FIRST: serve canonical income-statement presentation without
	// touching SQL Server when routed canonically. Product1/2/3 are deprecated
	// compatibility fields and are never derived.
	sh := integration.Default()
	if companyName != "" && sh.SalesDataRoute(companyName) == integration.RouteCanary {
		rows, err := sh.FetchCumulativeProfitCanonical(c.Request.Context(), companyName)
		if err == nil {
			// Empty history (no reported net_profit) is a valid explicit state (200 []).
			c.JSON(http.StatusOK, salesDataCanonicalResponse(rows, companyName))
			return
		}
		if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical income statement unavailable", "reason": "sqlserver_offline_expected"})
			return
		}
	}

	db := config.GetDB()
	defer db.Close()

	// In LEGACY mode the exact original query runs. The mapped metric columns are
	// only added when a fundamentals shadow comparison is actually enabled, so
	// default production behavior (rows, columns, order, response) is unchanged.
	shadowOn := sh.Enabled() && sh.Mode(integration.EndpointSalesData) != integration.ModeLegacy

	columns := "CompanyName, CompanyID, ReportDate, Product1, Product2, Product3"
	if shadowOn {
		columns += ", RevenueNew, OperatingProfitNew, NetProfitAmount, Num1_Value1, Num2_Value1"
	}
	query := "SELECT " + columns + " FROM miandore2"

	var rows *sql.Rows
	var err error

	if companyName != "" {
		query += " WHERE CompanyName = @companyName order by reportdate "
		rows, err = db.Query(query, sql.Named("companyName", companyName))

	} else {
		rows, err = db.Query(query)
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var data []models.SalesData
	var shadowRows []integration.FinancialInputRow
	for rows.Next() {
		var s models.SalesData
		var p1, p2, p3 sql.NullFloat64
		var revenue, opProfit, netProfit, eps, capital sql.NullFloat64

		targets := []any{&s.CompanyName, &s.CompanyID, &s.ReportDate, &p1, &p2, &p3}
		if shadowOn {
			targets = append(targets, &revenue, &opProfit, &netProfit, &eps, &capital)
		}
		if err := rows.Scan(targets...); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		s.Product1 = nullToFloat(p1)
		s.Product2 = nullToFloat(p2)
		s.Product3 = nullToFloat(p3)

		if shadowOn {
			// Shadow comparison row from mapped legacy metrics only. Product1/2/3
			// are legacy derived heuristics and are never mapped to canonical.
			shadowRows = append(shadowRows, integration.FinancialInputRow{
				LegacyCompanyID: s.CompanyID,
				ReportDate:      s.ReportDate,
				EPS:             nullToFloat(eps),
				Revenue:         nullToFloat(revenue),
				OperatingProfit: nullToFloat(opProfit),
				NetProfit:       nullToFloat(netProfit),
				Capital:         nullToFloat(capital),
			})
		}

		if s.Product1 == 0 {
			continue
		}

		s.Percentage = roundFloat(s.Product1/1_000_000, 2)

		// WoW calculation
		if s.Product1 > 0 && (s.Product2 < 0 || s.Product3 < 0) {
			s.WoW = 1
		} else if s.Product1 < 0 && (s.Product2 > 0 || s.Product3 > 0) {
			s.WoW = -1
		} else {
			s.WoW = 0
		}

		data = append(data, s)
	}

	// SHADOW: compare mapped income-statement metrics against canonical facts.
	// The legacy response data above is authoritative and unchanged.
	if shadowOn {
		sh.CompareSalesData(c.Request.Context(), shadowRows, time.Since(start))
	}

	c.JSON(http.StatusOK, data)
}

// salesDataCanonicalResponse maps canonical income-statement rows to the legacy
// SalesData response shape using the explicit canonical presentation contract.
//
// Presentation metric: canonical EPS (rial_per_share), which is complete across
// the report history (unlike net_profit, which the migration materialized only
// for the latest report for most companies). Rows are returned oldest -> newest
// so the chart renders left=older, right=newer. Product1/2/3 are deprecated and
// emitted as 0; the client consumes percentage/wow/reportDate/companyName.
// The upper chart shows the reported CUMULATIVE (YTD) net profit for each
// financial period, one point per period, oldest -> newest, resetting naturally
// at each fiscal year (no standalone-quarter subtraction, no EPS substitution).
// Periods where net_profit was not reported are simply absent.
//
// Compatibility: legacy `percentage` = cumulative net profit in million_rial
// (presentation value for the bar height; the chart auto-scales). Explicit
// fields `fiscalYear`, `periodOrder` (3/6/9/12), `periodEndDate`,
// `cumulativeNetProfitRial/Million` are provided additively.
func salesDataCanonicalResponse(rows []integration.NetProfitPeriodRow, companyName string) []models.SalesData {
	out := make([]models.SalesData, 0, len(rows))
	var prev float64
	for i, r := range rows {
		wow := 0
		if i > 0 {
			if r.CanonicalRial > 0 && prev < 0 {
				wow = 1
			} else if r.CanonicalRial < 0 && prev > 0 {
				wow = -1
			}
		}
		prev = r.CanonicalRial
		out = append(out, models.SalesData{
			CompanyName:                companyName,
			CompanyID:                  r.LegacyCompanyID,
			ReportDate:                 r.JalaliPeriod,
			Percentage:                 roundFloat(r.ReportedMillion, 2),
			WoW:                        wow,
			PeriodEndDate:              r.PeriodEndDate,
			FiscalYear:                 r.FiscalYear,
			PeriodOrder:                r.PeriodOrder,
			CumulativeNetProfitRial:    r.CanonicalRial,
			CumulativeNetProfitMillion: r.ReportedMillion,
		})
	}
	return out
}

func GetCompanyNames(c *gin.Context) {
	start := time.Now()

	// CANONICAL-FIRST: serve canonical company/symbol names without SQL Server.
	sh := integration.Default()
	if sh.CompanyNamesRoute() == integration.RouteCanary {
		if names, err := sh.FetchCompanyNamesCanonical(c.Request.Context()); err == nil && len(names) > 0 {
			c.JSON(http.StatusOK, names)
			return
		} else if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical company names unavailable; SQL Server is offline_expected"})
			return
		}
	}

	db := config.GetDB()
	defer db.Close()

	query := "SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName "
	rows, err := db.Query(query)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		names = append(names, name)
	}

	// SHADOW: compare against canonical core.companies names. The legacy
	// response below is authoritative and is never replaced.
	if sh.Enabled() {
		sh.CompareCompanyNames(c.Request.Context(), names, time.Since(start))
	}

	c.JSON(http.StatusOK, names)
}

func GetURL(c *gin.Context) {
	if config.SQLServerMode() == "offline_expected" {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "report URL lookup unavailable", "reason": "sqlserver_offline_expected"})
		return
	}
	db := config.GetDB()
	defer db.Close()

	var req models.GetURLRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	query := "SELECT TOP 1 Url FROM miandore2 WHERE CompanyName LIKE @companyName"
	likePattern := "%" + strings.TrimSpace(req.CompanyName) + "%"
	row := db.QueryRow(query, sql.Named("companyName", likePattern))

	var url sql.NullString
	if err := row.Scan(&url); err != nil {
		if err == sql.ErrNoRows {
			c.JSON(http.StatusOK, models.GetURLResponse{URL: ""})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	if url.Valid {
		c.JSON(http.StatusOK, models.GetURLResponse{URL: url.String})
	} else {
		c.JSON(http.StatusOK, models.GetURLResponse{URL: ""})
	}
}
