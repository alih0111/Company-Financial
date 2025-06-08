package handlers

import (
	"encoding/json"
	"io"
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

	// cmd := exec.Command("python", "py/scraper.py",
	// 	req.CompanyName,
	// 	// string(rune(req.RowMeta)), // convert int to string
	// 	strconv.Itoa(req.RowMeta),
	// 	req.BaseURL,
	// 	string(pageNumsJSON),
	// )

	// // Optional: redirect output (or capture if needed)
	// output, err := cmd.CombinedOutput()
	// if err != nil {
	// 	c.JSON(http.StatusInternalServerError, gin.H{
	// 		"error":   "Script execution failed",
	// 		"details": string(output),
	// 	})
	// 	return
	// }

	// c.JSON(http.StatusOK, gin.H{"message": "Script executed successfully!"})

	cmd := exec.Command("python", "py/scraper.py",
		req.CompanyName,
		strconv.Itoa(req.RowMeta),
		req.BaseURL,
		string(pageNumsJSON),
	)

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

}

func streamLogs(pipe io.ReadCloser) {
	buf := make([]byte, 1024)
	for {
		n, err := pipe.Read(buf)
		if n > 0 {
			logChunk := string(buf[:n])
			print(logChunk) // prints directly to the Go server console
		}
		if err != nil {
			if err == io.EOF {
				break
			}
			print("Error reading pipe:", err.Error())
			break
		}
	}
}
