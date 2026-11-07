package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestReportFlowReviewRequiresAdmin(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.POST("/review", ReviewReportFlow)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/review", nil))
	if w.Code != http.StatusForbidden {
		t.Fatalf("non-admin review: %d", w.Code)
	}
}

func TestReportFlowDisabledObserverDoesNotStartWorker(t *testing.T) {
	t.Setenv("REPORTFLOW_AUTOMATIC_ENABLED", "0")
	reportFlowBusy.Store(false)
	reportFlowTick()
	if reportFlowBusy.Load() {
		t.Fatal("disabled observer acquired the worker slot")
	}
}

func TestReportFlowArchivedAPIIsReadOnly(t *testing.T) {
	root, err := analyticsRepoRoot()
	if err != nil || !reportFlowArchived(root) {
		t.Skip("archived research marker is absent in this checkout")
	}
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.GET("/reportflow", GetReportFlow)
	router.POST("/review", func(c *gin.Context) {
		c.Set("isAdmin", true)
		ReviewReportFlow(c)
	})
	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/review", nil))
	if w.Code != http.StatusGone {
		t.Fatalf("archived review: %d %s", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/reportflow", nil))
	var body map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["archived"] != true || body["automatic_enabled"] != false {
		t.Fatalf("archived status: %s", w.Body.String())
	}
}
