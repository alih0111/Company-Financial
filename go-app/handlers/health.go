package handlers

import (
	"context"
	"database/sql"
	"net/http"
	"strings"
	"time"

	_ "github.com/denisenkom/go-mssqldb"
	"github.com/gin-gonic/gin"

	"go-app/config"
	"go-app/integration"
)

// probeSQLServer performs a bounded ping without affecting request behavior.
func probeSQLServer() (bool, string) {
	cs := config.ConnectionString
	if strings.TrimSpace(cs) == "" {
		return false, "not configured"
	}
	if !strings.Contains(strings.ToLower(cs), "timeout") {
		cs += ";Connection Timeout=2"
	}
	db, err := sql.Open("sqlserver", cs)
	if err != nil {
		return false, "open error"
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		return false, "offline"
	}
	return true, "reachable"
}

// GetShadowHealth exposes read mode, canonical analytics metadata and the SQL
// Server retirement state. It never exposes credentials.
//
// When CDF_SQLSERVER_MODE=offline_expected, an offline SQL Server is reported as
// RETIRED_EXPECTED and does not mark the application unhealthy.
func GetShadowHealth(c *gin.Context) {
	sh := integration.Default()
	st := sh.RefreshStatus(c.Request.Context())

	sqlReachable, sqlNote := probeSQLServer()
	sqlMode := config.SQLServerMode()
	sqlRequired := config.SQLServerRequired()

	sqlStatus := "OFFLINE"
	if sqlReachable {
		sqlStatus = "HEALTHY"
	} else if sqlMode == "offline_expected" {
		sqlStatus = "RETIRED_EXPECTED"
	}

	postgresStatus := "OFFLINE"
	if db, err := config.GetPG(); err == nil && db != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		if db.PingContext(ctx) == nil {
			postgresStatus = "HEALTHY"
		}
		cancel()
	} else if err != nil && strings.Contains(err.Error(), "not configured") {
		postgresStatus = "NOT_CONFIGURED"
	}

	overall := "HEALTHY"
	if postgresStatus != "HEALTHY" {
		overall = "DEGRADED"
	}
	if sqlRequired && !sqlReachable {
		overall = "UNHEALTHY"
	}

	c.JSON(http.StatusOK, gin.H{
		"read_mode":            st.ReadMode,
		"postgres_status":      postgresStatus,
		"canonical_configured": st.CanonicalConfigured,
		"canonical_reachable":  st.CanonicalReachable,
		"canonical_error":      st.CanonicalError,
		"analytics_status":     analyticsStatus(st.ScoreRunID, st.ScoreStale),
		"score_version":        st.ScoreVersion,
		"score_run_id":         st.ScoreRunID,
		"score_as_of":          st.ScoreAsOf,
		// score_computed_at lets a score whose data date did not advance still read as
		// freshly computed; score_stale_reasons names the domains that moved.
		"score_computed_at":   st.ScoreComputedAt,
		"score_run_seq":       st.ScoreRunSeq,
		"score_stale_reasons": st.ScoreStaleReasons,
		"data_as_of":          st.DataAsOf,
		"score_stale":         st.ScoreStale,
		"sqlserver_status":    sqlStatus,
		"sqlserver_note":      sqlNote,
		"sqlserver_required":  sqlRequired,
		"sqlserver_mode":      sqlMode,
		"overall":             overall,
		"comparison_rules":    st.ComparisonRules,
		"shadow_timeout_ms":   st.ShadowTimeoutMS,
	})
}

// analyticsStatus reports the served score's freshness. A run exists but its inputs
// have moved since -> STALE, which is a real health condition, not HEALTHY.
func analyticsStatus(runID string, stale bool) string {
	if runID == "" {
		return "NO_COMPLETED_RUN"
	}
	if stale {
		return "STALE"
	}
	return "HEALTHY"
}
