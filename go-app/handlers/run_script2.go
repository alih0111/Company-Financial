package handlers

import (
	"encoding/json"
	"log"
	"net/http"
	"os/exec"
	"strconv"

	"github.com/gin-gonic/gin"
)

type RunScript2Request struct {
	CompanyName string `json:"companyName"`
	RowMeta     int    `json:"rowMeta"`
	BaseURL     string `json:"baseUrl"`
	PageNumbers []int  `json:"pageNumbers"`
}

func RunScript2(c *gin.Context) {
	var req RunScript2Request

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid JSON: " + err.Error()})
		return
	}

	pageNumsJSON, err := json.Marshal(req.PageNumbers)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to encode page numbers"})
		return
	}

	// cmd := exec.Command("python", "py/scraper2.py",
	// 	req.CompanyName,
	// 	strconv.Itoa(req.RowMeta),
	// 	req.BaseURL,
	// 	string(pageNumsJSON),
	// )
	log.Println("RunScript2 called py")
	cmd := exec.Command("python", "py/scraper2.py",
		req.CompanyName,
		strconv.Itoa(req.RowMeta),
		req.BaseURL,
		string(pageNumsJSON),
	)
	log.Println("RunScript2 called py2")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to get stdout: " + err.Error()})
		return
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to get stderr: " + err.Error()})
		return
	}

	// Start command execution
	if err := cmd.Start(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to start command: " + err.Error()})
		return
	}

	// Stream logs to the server console in real time
	go streamLogs(stdout)
	go streamLogs(stderr)

	// Wait for the script to finish
	if err := cmd.Wait(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Script execution failed: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Script executed successfully!"})

	// output, err := cmd.CombinedOutput()
	// if err != nil {
	// 	c.JSON(http.StatusInternalServerError, gin.H{
	// 		"error":   "Script execution failed",
	// 		"details": string(output),
	// 	})
	// 	return
	// }

	// c.JSON(http.StatusOK, gin.H{"message": "Script executed successfully!"})
}
