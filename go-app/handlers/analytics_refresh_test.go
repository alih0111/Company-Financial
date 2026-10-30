package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
)

// The manual refresh is admin-only: a non-admin must never be able to append a
// serving score run.
func TestRefreshAnalyticsScoresRequiresAdmin(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/refresh", func(c *gin.Context) {
		c.Set("isAdmin", false)
		RefreshAnalyticsScores(c)
	})
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/refresh", nil))
	if w.Code != http.StatusForbidden {
		t.Fatalf("non-admin status = %d, want 403", w.Code)
	}
}

// A second click while a recompute is running must not start a parallel engine run.
func TestRefreshAnalyticsScoresRejectsConcurrentRun(t *testing.T) {
	gin.SetMode(gin.TestMode)
	analyticsRefreshBusy.Store(true)
	defer analyticsRefreshBusy.Store(false)

	r := gin.New()
	r.POST("/refresh", func(c *gin.Context) {
		c.Set("isAdmin", true)
		RefreshAnalyticsScores(c)
	})
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/refresh", nil))
	if w.Code != http.StatusConflict {
		t.Fatalf("busy status = %d, want 409", w.Code)
	}
}

// The endpoint shells out to a script in the repository, so the path resolution is
// part of the contract: it must find the orchestrator from the app working directory.
func TestAnalyticsRepoRootFindsOrchestrator(t *testing.T) {
	root, err := analyticsRepoRoot()
	if err != nil {
		t.Fatalf("repo root: %v", err)
	}
	script := filepath.Join(root, filepath.FromSlash(analyticsRefreshScript))
	if _, err := os.Stat(script); err != nil {
		t.Fatalf("orchestrator missing at %s: %v", script, err)
	}
	if _, err := os.Stat(analyticsRefreshPython(root)); err != nil {
		t.Fatalf("python interpreter not found: %v", err)
	}
}

// Optional live check: really run the engine through the handler and assert the
// response contract. Opt-in because it invokes Python (seconds) and would append a
// serving run when the inputs moved.
func TestRefreshAnalyticsScoresLive(t *testing.T) {
	if os.Getenv("RFA_TEST_LIVE_REFRESH") != "1" {
		t.Skip("set RFA_TEST_LIVE_REFRESH=1 to run the engine through the handler")
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/refresh", func(c *gin.Context) {
		c.Set("isAdmin", true)
		RefreshAnalyticsScores(c)
	})
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/refresh", nil))

	var body analyticsRefreshResponse
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("response is not JSON: %v (%s)", err, w.Body.String())
	}
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", w.Code, w.Body.String())
	}
	switch body.Action {
	case "RECOMPUTED":
		if !body.Recomputed || body.RunSeq == 0 || body.ComputedAt == "" {
			t.Fatalf("recomputed response incomplete: %+v", body)
		}
	case "NOT_STALE":
		if body.Recomputed {
			t.Fatalf("NOT_STALE must not claim a recompute: %+v", body)
		}
	default:
		t.Fatalf("unexpected action %q: %+v", body.Action, body)
	}
	if body.Message == "" || body.DurationMS <= 0 {
		t.Fatalf("message/duration missing: %+v", body)
	}
}
