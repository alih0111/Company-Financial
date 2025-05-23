package handlers

import (
	"database/sql"
	"go-codal-app/config"
	"net/http"

	"github.com/gin-gonic/gin"
)

func GetSalesData(c *gin.Context) {
	companyName := c.Query("companyName")

	query := "SELECT CompanyName, CompanyID, ReportDate, Product1, Product2, Product3 FROM miandore2"
	var params []interface{}
	if companyName != "" {
		query += " WHERE CompanyName = ?"
		params = append(params, companyName)
	}

	db, err := config.GetDBConnection()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer db.Close()

	rows, err := db.Query(query, params...)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var results []map[string]interface{}
	for rows.Next() {
		var name string
		var id int
		var reportDate string
		var v1, v2, v3 float64
		rows.Scan(&name, &id, &reportDate, &v1, &v2, &v3)

		// Perform calculations
		pct := v1 / 1000000
		wow := 0
		if v1 > 0 && (v2 < 0 || v3 < 0) {
			wow = 1
		} else if v1 < 0 && (v2 > 0 || v3 > 0) {
			wow = -1
		}

		results = append(results, map[string]interface{}{
			"companyName": name,
			"companyID":   id,
			"reportDate":  reportDate,
			"Product1":    v1,
			"Product2":    v2,
			"Product3":    v3,
			"percentage":  pct,
			"wow":         wow,
		})
	}

	c.JSON(http.StatusOK, results)
}

func GetCompanyNames(c *gin.Context) {
	db, err := config.GetDBConnection()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer db.Close()

	rows, err := db.Query("SELECT DISTINCT CompanyName FROM miandore2")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var names []string
	for rows.Next() {
		var name string
		rows.Scan(&name)
		names = append(names, name)
	}

	c.JSON(http.StatusOK, names)
}

func GetURL(c *gin.Context) {
	var req struct {
		CompanyName string `json:"companyName"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}

	db, err := config.GetDBConnection()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer db.Close()

	query := "SELECT TOP 1 Url FROM miandore2 WHERE CompanyName like ?"
	row := db.QueryRow(query, req.CompanyName)

	var url string
	err = row.Scan(&url)
	if err == sql.ErrNoRows {
		c.JSON(http.StatusOK, gin.H{"url": ""})
		return
	} else if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"url": url})
}
