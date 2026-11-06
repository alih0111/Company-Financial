package handlers

import (
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
