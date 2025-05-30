package handlers

import (
	"encoding/json"
	"net/http"
	"os/exec"

	"strconv"

	"github.com/gin-gonic/gin"
)

type RunScriptRequest struct {
	CompanyName string `json:"companyName"`
	RowMeta     int    `json:"rowMeta"`
	BaseURL     string `json:"baseUrl"`
	PageNumbers []int  `json:"pageNumbers"`
}

func RunScript(c *gin.Context) {
	var req RunScriptRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON: " + err.Error()})
		return
	}

	pageNumsJSON, err := json.Marshal(req.PageNumbers)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encode page numbers"})
		return
	}

	cmd := exec.Command("python", "py/scraper.py",
		req.CompanyName,
		// string(rune(req.RowMeta)), // convert int to string
		strconv.Itoa(req.RowMeta),
		req.BaseURL,
		string(pageNumsJSON),
	)

	// Optional: redirect output (or capture if needed)
	output, err := cmd.CombinedOutput()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":   "Script execution failed",
			"details": string(output),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Script executed successfully!"})
}
