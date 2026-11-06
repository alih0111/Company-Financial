package handlers

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestFactorMixRefreshRequiresAdminAndRejectsOverlap(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, test := range []struct {
		name  string
		admin bool
		busy  bool
		want  int
	}{
		{"non_admin", false, false, http.StatusForbidden},
		{"already_running", true, true, http.StatusConflict},
	} {
		t.Run(test.name, func(t *testing.T) {
			factorMixRankingBusy.Store(test.busy)
			defer factorMixRankingBusy.Store(false)
			router := gin.New()
			router.POST("/refresh", func(c *gin.Context) {
				c.Set("isAdmin", test.admin)
				RefreshFactorMixRanking(c)
			})
			response := httptest.NewRecorder()
			router.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/refresh", nil))
			if response.Code != test.want {
				t.Fatalf("status %d, want %d", response.Code, test.want)
			}
		})
	}
}

func TestFactorMixPublishedRankingAPI(t *testing.T) {
	// The first calculation may not exist in a clean checkout.
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/ranking", GetFactorMixRanking)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/ranking", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("status %d: %s", response.Code, response.Body.String())
	}
}
