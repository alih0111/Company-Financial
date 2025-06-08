package handlers

import (
	"net/http"
	"os/exec"

	"github.com/gin-gonic/gin"
)

func RunScriptPE(c *gin.Context) {

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
