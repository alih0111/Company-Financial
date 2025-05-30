package handlers

import (
	"database/sql"
	"net/http"
	"strings"

	"go-codal-app/config"
	"go-codal-app/models"

	"github.com/gin-gonic/gin"
)

func GetSalesData(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	companyName := c.Query("companyName")
	query := "SELECT CompanyName, CompanyID, ReportDate, Product1, Product2, Product3 FROM miandore2"

	var rows *sql.Rows
	var err error

	if companyName != "" {
		query += " WHERE CompanyName = @companyName"
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
	for rows.Next() {
		var s models.SalesData
		var p1, p2, p3 sql.NullFloat64

		if err := rows.Scan(&s.CompanyName, &s.CompanyID, &s.ReportDate, &p1, &p2, &p3); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		s.Product1 = nullToFloat(p1)
		s.Product2 = nullToFloat(p2)
		s.Product3 = nullToFloat(p3)

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

	c.JSON(http.StatusOK, data)
}

func GetCompanyNames(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	query := "SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName"
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

	c.JSON(http.StatusOK, names)
}

func GetURL(c *gin.Context) {
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

// func nullToFloat(n sql.NullFloat64) float64 {
// 	if n.Valid {
// 		return n.Float64
// 	}
// 	return 0
// }

// func roundFloat(val float64, places int) float64 {
// 	pow := 1.0
// 	for i := 0; i < places; i++ {
// 		pow *= 10
// 	}
// 	return float64(int(val*pow+0.5)) / pow
// }
