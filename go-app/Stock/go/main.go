package main

import (
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"

	_ "github.com/denisenkom/go-mssqldb"
	"github.com/gin-gonic/gin"
)

var db *sql.DB

func initDB() {
	var err error
	connString := fmt.Sprintf("server=%s;user id=%s;password=%s;database=%s",
		os.Getenv("DB_SERVER"),
		os.Getenv("DB_USER"),
		os.Getenv("DB_PASSWORD"),
		os.Getenv("DB_NAME"),
	)

	db, err = sql.Open("sqlserver", connString)
	if err != nil {
		log.Fatal("Error creating connection pool: ", err.Error())
	}
}

func getCompanyFacts(c *gin.Context) {
	ticker := c.Param("ticker")

	// اول چک می‌کنیم داده وجود داره یا نه
	var count int
	err := db.QueryRow(`
		SELECT COUNT(*)
		FROM FinancialFacts f
		JOIN FinancialReports r ON f.ReportID = r.ReportID
		JOIN Companies c ON r.CompanyID = c.CompanyID
		WHERE c.Ticker = @p1
	`, ticker).Scan(&count)

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// اگه داده نبود → اجرای Python
	if count == 0 {
		cmd := exec.Command("python", "./python-scripts/import_facts.py")
		cmd.Env = os.Environ() // .env هم باید لود شده باشه
		output, err := cmd.CombinedOutput()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{
				"error":  "Python script failed",
				"detail": string(output),
			})
			return
		}
	}

	// حالا داده رو برگردونیم
	rows, err := db.Query(`
		SELECT f.FactName, f.Value, f.StartDate, f.EndDate
		FROM FinancialFacts f
		JOIN FinancialReports r ON f.ReportID = r.ReportID
		JOIN Companies c ON r.CompanyID = c.CompanyID
		WHERE c.Ticker = @p1
		ORDER BY f.EndDate DESC
	`, ticker)

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	var results []map[string]interface{}
	for rows.Next() {
		var factName string
		var value float64
		var startDate, endDate string
		rows.Scan(&factName, &value, &startDate, &endDate)

		results = append(results, gin.H{
			"fact":      factName,
			"value":     value,
			"startDate": startDate,
			"endDate":   endDate,
		})
	}

	c.JSON(http.StatusOK, results)
}

func main() {
	initDB()
	defer db.Close()

	r := gin.Default()
	r.GET("/api/company/:ticker/facts", getCompanyFacts)

	r.Run(":8080")
}
