package handlers

import (
	"net/http"

	"go-app/integration"

	"github.com/gin-gonic/gin"
)

// GetShadowHealth exposes the integration read mode and backend availability.
// It never exposes credentials or connection strings. Canonical shadow
// availability does not affect the legacy production health semantics.
func GetShadowHealth(c *gin.Context) {
	sh := integration.Default()
	st := sh.RefreshStatus(c.Request.Context())
	c.JSON(http.StatusOK, gin.H{
		"read_mode":            st.ReadMode,
		"canonical_configured": st.CanonicalConfigured,
		"canonical_reachable":  st.CanonicalReachable,
		"canonical_error":      st.CanonicalError,
		"score_version":        st.ScoreVersion,
		"score_run_id":         st.ScoreRunID,
		"score_as_of":          st.ScoreAsOf,
		"comparison_rules":     st.ComparisonRules,
		"shadow_timeout_ms":    st.ShadowTimeoutMS,

		"price_history_canary_enabled":      st.CanaryEnabled,
		"price_history_canary_symbol_count": st.CanarySymbolCount,
		"price_history_canary_percent":      st.CanaryPercent,
		"price_history_canary_verify":       st.CanaryVerify,
		"price_history_canary_timeout_ms":   st.CanaryTimeoutMS,
	})
}
