package handlers

import (
	"net/http"
	"os/exec"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

func RunScriptPE(c *gin.Context) {
	if config.SQLServerMode() == "offline_expected" {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "FullPE refresh retired (SQL Server only)", "reason": "sqlserver_offline_expected"})
		return
	}

	cmd := exec.Command("python", "py/scraperFullPE.py")

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
