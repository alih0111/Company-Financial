package handlers

import (
	"database/sql"
	"net/http"
	"strings"

	"go-codal-app/config"
	"go-codal-app/models"

	"github.com/gin-gonic/gin"
)

func GetSalesData2(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	companyName := c.Query("companyName")
	query := "SELECT CompanyName, CompanyID, ReportDate, Value1, Value2, Value3 FROM mahane"

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

	var data []models.SalesData2
	for rows.Next() {
		var s models.SalesData2
		var v1, v2, v3 sql.NullFloat64

		if err := rows.Scan(&s.CompanyName, &s.CompanyID, &s.ReportDate, &v1, &v2, &v3); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		s.Value1 = nullToFloat(v1)
		s.Value2 = nullToFloat(v2)
		s.Value3 = nullToFloat(v3)

		if s.Value1 == 0 {
			continue
		}

		s.Value1 /= 1_000_000
		s.Value2 /= 1_000_000
		s.Value3 /= 1_000_000
		s.Percentage = s.Value3 * 1000 // equivalent of: value3 / 1000

		if s.Value1 > 0 && (s.Value2 < 0 || s.Value3 < 0) {
			s.WoW = 1
		} else if s.Value1 < 0 && (s.Value2 > 0 || s.Value3 > 0) {
			s.WoW = -1
		} else {
			s.WoW = 0
		}

		data = append(data, s)
	}

	c.JSON(http.StatusOK, data)
}

func GetURL2(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	var req models.GetURLRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	query := "SELECT TOP 1 Url FROM mahane WHERE CompanyName LIKE @companyName"
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
