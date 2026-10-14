package qvt

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestPaperOnlySummary(t *testing.T) {
	gin.SetMode(gin.TestMode)
	path := filepath.Join(t.TempDir(), "latest.json")
	t.Setenv("QVT_PAPER_SUMMARY_FILE", path)
	r := gin.New()
	r.GET("/paper", GetQvtV2Paper)
	check := func(want int) {
		t.Helper()
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("GET", "/paper", nil))
		if w.Code != want {
			t.Fatalf("HTTP %d, wanted %d: %s", w.Code, want, w.Body.String())
		}
	}
	check(200)
	for _, test := range []struct {
		body string
		code int
	}{
		{`{"version":"qvt-paper-forward-v1","mode":"reference_only","real_orders":0,"positions":[]}`, 200},
		{`{"version":"qvt-paper-forward-v1","mode":"live","real_orders":1}`, 503},
		{`broken`, 503},
	} {
		if err := os.WriteFile(path, []byte(test.body), 0600); err != nil {
			t.Fatal(err)
		}
		check(test.code)
	}
}

func TestPaperObservationSchedule(t *testing.T) {
	for _, test := range []struct {
		timestamp string
		due       bool
	}{
		{"2026-10-13T09:14:00Z", false}, // 12:44 Tehran
		{"2026-10-13T09:15:00Z", true},
		{"2026-10-15T10:00:00Z", false}, // Thursday
		{"2026-10-16T10:00:00Z", false}, // Friday
	} {
		stamp, _ := time.Parse(time.RFC3339, test.timestamp)
		if paperObservationDue(stamp) != test.due {
			t.Fatalf("unexpected schedule at %s", test.timestamp)
		}
	}
}
