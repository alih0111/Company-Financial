package handlers

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"go-app/config"
	"net/http"
	"os/exec"
	"strconv"
	"strings"

	_ "github.com/denisenkom/go-mssqldb"
	"github.com/gin-gonic/gin"
)

type BulkFetchRequest struct {
	Script      string   `json:"script"`      // script1 or script2
	Companies   []string `json:"companies"`   // list of company names
	RowMeta     int      `json:"rowMeta"`     // optional: default = 20
	PageNumbers []int    `json:"pageNumbers"` // optional: default = [1,2,3,4]
}

func getURLFromDB(companyName string, script string) (string, error) {
	table := "mahane"
	if script == "script1" {
		table = "miandore2"
	}

	db := config.GetDB()
	defer db.Close()
	var err error

	var url string
	query := fmt.Sprintf("SELECT TOP 1 Url FROM %s WHERE CompanyName LIKE @p1", table)
	err = db.QueryRow(query, companyName).Scan(&url)
	if err != nil {
		if err == sql.ErrNoRows {
			return "", nil
		}
		return "", err
	}

	return url, nil
}

func BulkFetch(c *gin.Context) {
	var req BulkFetchRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON: " + err.Error()})
		return
	}

	if req.Script != "script1" && req.Script != "script2" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid script type"})
		return
	}
	if len(req.Companies) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "No companies provided"})
		return
	}
	if req.RowMeta == 0 {
		req.RowMeta = 20
	}
	if req.PageNumbers == nil {
		req.PageNumbers = []int{1, 2, 3, 4}
	}

	errors := []string{}

	for _, company := range req.Companies {
		url, err := getURLFromDB(company, req.Script)
		if err != nil || url == "" {
			errors = append(errors, fmt.Sprintf("No URL found for %s", company))
			continue
		}

		pageJSON, _ := json.Marshal(req.PageNumbers)
		scriptName := "py/scraper.py"
		if req.Script == "script2" {
			scriptName = "py/scraper2.py"
		}

		cmd := exec.Command("python", scriptName,
			company,
			strconv.Itoa(req.RowMeta),
			url,
			string(pageJSON),
		)

		output, err := cmd.CombinedOutput()
		outStr := string(output)

		if err != nil || !strings.Contains(outStr, "scraping and saving successful") {
			errors = append(errors, fmt.Sprintf("%s failed or had no data: %s", company, outStr))
			continue
		}

	}

	if len(errors) > 0 {
		c.JSON(http.StatusMultiStatus, gin.H{
			"message": "Partial success",
			"errors":  errors,
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "All scripts executed successfully"})
}
