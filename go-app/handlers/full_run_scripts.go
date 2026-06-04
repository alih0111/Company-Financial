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
	"time"

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

	var url, reportDate string
	query := fmt.Sprintf(`
		SELECT TOP 1 Url, ReportDate
		FROM %s
		WHERE CompanyName LIKE @p1
		ORDER BY ReportDate DESC`, table)

	err := db.QueryRow(query, companyName).Scan(&url, &reportDate)
	if err != nil {
		if err == sql.ErrNoRows {
			return "", nil
		}
		return "", err
	}

	// Convert Persian date to time.Time
	t, err := persianDateToTime(reportDate)
	if err != nil {
		return "", err
	}

	if script == "script1" {
		if time.Since(t) < 100*24*time.Hour {
			return "", nil
		}
	}
	if script == "script2" {
		if time.Since(t) < 30*24*time.Hour {
			return "", nil
		}
	}

	return url, nil
}

// persianDateToTime converts "yyyy/mm/dd" in Persian calendar to time.Time
func persianDateToTime(dateStr string) (time.Time, error) {
	parts := strings.Split(dateStr, "/")
	if len(parts) != 3 {
		return time.Time{}, fmt.Errorf("invalid date format: %s", dateStr)
	}
	year, err1 := strconv.Atoi(parts[0])
	month, err2 := strconv.Atoi(parts[1])
	day, err3 := strconv.Atoi(parts[2])
	if err1 != nil || err2 != nil || err3 != nil {
		return time.Time{}, fmt.Errorf("invalid date parts: %s", dateStr)
	}

	// Convert Persian date to Gregorian
	gy, gm, gd := jalaliToGregorian(year, month, day)

	return time.Date(gy, time.Month(gm), gd, 0, 0, 0, 0, time.Local), nil
}

// Simple Jalali (Persian) to Gregorian conversion
func jalaliToGregorian(jy, jm, jd int) (int, int, int) {
	jy += 1595
	days := -355668 + 365*jy + jy/33*8 + (jy%33+3)/4 + jd
	if jm < 7 {
		days += (jm - 1) * 31
	} else {
		days += (jm-7)*30 + 186
	}
	gy := 400 * (days / 146097)
	days %= 146097
	leap := true
	if days > 36524 {
		gy += 100 * ((days - 1) / 36524)
		days = (days - 1) % 36524
		if days >= 365 {
			days++
		} else {
			leap = false
		}
	}
	gy += 4 * (days / 1461)
	days %= 1461
	if days > 365 {
		gy += (days - 1) / 365
		days = (days - 1) % 365
		leap = false
	}
	var gm int
	var gd int
	salA := [...]int{0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365}
	if leap {
		salA = [...]int{0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366}
	}

	for gm = 0; gm < 12; gm++ {
		if days < salA[gm+1] {
			gd = days - salA[gm] + 1
			gm++
			break
		}
	}
	return gy, gm, gd
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

// handlers/bulkfetch.go  (فقط بخش BulkFetch تغییر کرده + یک type جدید)

// type BulkJob struct {
// 	Company string `json:"company"`
// 	Url     string `json:"url"`
// }

// func BulkFetch(c *gin.Context) {
// 	var req BulkFetchRequest

// 	if err := c.ShouldBindJSON(&req); err != nil {
// 		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON: " + err.Error()})
// 		return
// 	}

// 	if req.Script != "script1" && req.Script != "script2" {
// 		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid script type"})
// 		return
// 	}
// 	if len(req.Companies) == 0 {
// 		c.JSON(http.StatusBadRequest, gin.H{"error": "No companies provided"})
// 		return
// 	}
// 	if req.RowMeta == 0 {
// 		req.RowMeta = 20
// 	}
// 	if req.PageNumbers == nil {
// 		req.PageNumbers = []int{1, 2, 3, 4}
// 	}

// 	errors := []string{}
// 	jobs := []BulkJob{}

// 	for _, company := range req.Companies {
// 		url, err := getURLFromDB(company, req.Script)
// 		if err != nil || url == "" {
// 			errors = append(errors, fmt.Sprintf("No URL found for %s", company))
// 			continue
// 		}
// 		jobs = append(jobs, BulkJob{Company: company, Url: url})
// 	}

// 	if len(jobs) == 0 {
// 		c.JSON(http.StatusMultiStatus, gin.H{
// 			"message": "No jobs to run",
// 			"errors":  errors,
// 		})
// 		return
// 	}

// 	pageJSON, _ := json.Marshal(req.PageNumbers)
// 	jobsJSON, _ := json.Marshal(jobs)

// 	// یک بار پایتون اجرا میشه و همه شرکت‌ها رو با یک Driver میره
// 	cmd := exec.Command("python", "py/bulk_runner.py",
// 		req.Script,
// 		strconv.Itoa(req.RowMeta),
// 		string(pageJSON),
// 		string(jobsJSON),
// 	)

// 	output, err := cmd.CombinedOutput()
// 	outStr := string(output)

// 	// parse نتایج
// 	successMap := map[string]bool{}
// 	failMap := map[string]string{}

// 	for _, line := range strings.Split(outStr, "\n") {
// 		line = strings.TrimSpace(line)
// 		if line == "" {
// 			continue
// 		}
// 		// RESULT|Company|OK
// 		// RESULT|Company|FAIL|message...
// 		if strings.HasPrefix(line, "RESULT|") {
// 			parts := strings.Split(line, "|")
// 			if len(parts) >= 3 {
// 				company := parts[1]
// 				status := parts[2]
// 				if status == "OK" {
// 					successMap[company] = true
// 				} else if status == "FAIL" {
// 					msg := ""
// 					if len(parts) >= 4 {
// 						msg = strings.Join(parts[3:], "|")
// 					}
// 					failMap[company] = msg
// 				}
// 			}
// 		}
// 	}

// 	if err != nil {
// 		errors = append(errors, "bulk runner failed: "+err.Error())
// 	}

// 	for _, job := range jobs {
// 		if successMap[job.Company] {
// 			continue
// 		}
// 		if msg, ok := failMap[job.Company]; ok {
// 			errors = append(errors, fmt.Sprintf("%s failed: %s", job.Company, msg))
// 		} else {
// 			errors = append(errors, fmt.Sprintf("%s failed or had no data: %s", job.Company, outStr))
// 		}
// 	}

// 	if len(errors) > 0 {
// 		c.JSON(http.StatusMultiStatus, gin.H{
// 			"message": "Partial success",
// 			"errors":  errors,
// 		})
// 		return
// 	}

// 	c.JSON(http.StatusOK, gin.H{"message": "All scripts executed successfully"})
// }
