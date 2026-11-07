package handlers

import (
	"context"
	"encoding/json"
	"go-app/config"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

var factorMixRankingBusy atomic.Bool

// GetFactorMixRanking serves the separately calculated current scores.
func GetFactorMixRanking(c *gin.Context) {
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	path := filepath.Join(root, ".runtime", "factormix-ranking", "latest.json")
	var status struct {
		Error string `json:"error"`
	}
	if body, err := os.ReadFile(filepath.Join(root, ".runtime", "factormix-ranking", "status.json")); err == nil {
		_ = json.Unmarshal(body, &status)
	}
	if config.Production() && status.Error != "" {
		status.Error = "بازسازی ناموفق بود؛ مدیر باید گزارش سرور را بررسی کند."
	}
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		c.JSON(http.StatusOK, gin.H{"ranking": nil, "running": factorMixRankingBusy.Load(), "refresh_error": status.Error})
		return
	}
	if err != nil || !json.Valid(raw) {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "خواندن رتبه‌بندی FactorMix ناموفق بود."})
		return
	}
	c.Header("Cache-Control", "no-store")
	var ranking any = json.RawMessage(raw)
	if !c.GetBool("isAdmin") {
		value, ok := limitedFactorMixRanking(c, raw)
		if !ok {
			return
		}
		ranking = value
	}
	c.JSON(http.StatusOK, gin.H{"ranking": ranking, "running": factorMixRankingBusy.Load(), "refresh_error": status.Error})
}

// RefreshFactorMixRanking invokes only the score publisher, with no account API.
func RefreshFactorMixRanking(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	if !factorMixRankingBusy.CompareAndSwap(false, true) {
		c.JSON(http.StatusConflict, gin.H{"error": "محاسبهٔ FactorMix در حال انجام است."})
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		factorMixRankingBusy.Store(false)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	// Use a bounded server-owned context so navigating away does not interrupt
	// publication. The Python OS lock also covers manual command invocations.
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	cmd := exec.CommandContext(ctx, analyticsRefreshPython(root), "-B", "-m", "factormix.refresh_ranking")
	cmd.Dir = root
	logDir := filepath.Join(root, ".runtime", "factormix-ranking")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		cancel()
		factorMixRankingBusy.Store(false)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	log, err := os.OpenFile(filepath.Join(logDir, "refresh.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		cancel()
		factorMixRankingBusy.Store(false)
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	cmd.Stdout, cmd.Stderr = log, log
	go func() {
		defer factorMixRankingBusy.Store(false)
		defer cancel()
		defer log.Close()
		if err := cmd.Run(); err != nil {
			// Keep an existing detailed Python error, including a failure before
			// the worker started or a timeout imposed by this process.
			message := "محاسبهٔ FactorMix ناموفق بود: " + err.Error()
			if raw, readErr := os.ReadFile(filepath.Join(logDir, "status.json")); readErr == nil {
				var status struct {
					Error string `json:"error"`
				}
				if json.Unmarshal(raw, &status) == nil && status.Error != "" {
					message = status.Error
				}
			}
			body, _ := json.Marshal(gin.H{"state": "failed", "error": message})
			_ = os.WriteFile(filepath.Join(logDir, "status.json"), body, 0o644)
		}
	}()
	c.JSON(http.StatusAccepted, gin.H{"running": true})
}
