package handlers

import (
	"context"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"net/http"
	"time"
)

// Readiness means the required schema is accessible. It does not assert that
// scores are fresh or that market data has been imported.
func GetReadiness(c *gin.Context) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "unavailable"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()
	var schemaReady bool
	err = db.QueryRowContext(ctx, `SELECT to_regclass('auth.users') IS NOT NULL AND to_regclass('auth.sessions') IS NOT NULL AND to_regclass('auth.data_usage') IS NOT NULL AND to_regclass('auth.data_policies') IS NOT NULL AND to_regclass('auth.data_targets') IS NOT NULL AND to_regclass('auth.data_ip_usage') IS NOT NULL AND to_regclass('core.companies') IS NOT NULL AND to_regclass('analytics.score_runs') IS NOT NULL AND to_regclass('portfolio.portfolios') IS NOT NULL`).Scan(&schemaReady)
	if err != nil || !schemaReady {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "unavailable"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ready"})
}
