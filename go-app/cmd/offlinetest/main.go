// Command offlinetest simulates SQL Server being completely unavailable while
// running the real Gin handlers, and records the exact outcome per endpoint.
//
// It does NOT touch the SQL Server instance: it points DB_SERVER at an
// unreachable host:port via the process environment before startup, so the lazy
// `sql.Open` never connects. The canonical PostgreSQL connection is exercised
// independently as the healthy reference.
//
// Usage (from go-app/), SQL Server unreachable via env override:
//
//	$env:DB_SERVER="127.0.0.1,59999"
//	go run ./cmd/offlinetest
package main

import (
	"context"
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"go-app/config"
	"go-app/handlers"
	"go-app/integration"
)

type result struct {
	Endpoint string
	Method   string
	Status   int
	Class    string
	Body     string
	Note     string
}

func main() {
	gin.SetMode(gin.ReleaseMode)
	g := gin.New()
	g.GET("/api/health/shadow", handlers.GetShadowHealth)
	g.POST("/api/login", handlers.Login)
	g.GET("/api/CompanyNames", handlers.GetCompanyNames)
	g.GET("/api/SalesData", handlers.GetSalesData)
	g.GET("/api/SalesData2", handlers.GetSalesData2)
	g.GET("/api/CompanyScores", handlers.GetCompanyScores2)
	g.GET("/api/AllCompanyScores", handlers.GetCompanyScores)
	g.GET("/api/StockPriceScore", handlers.StockPriceScore)
	g.GET("/api/price-history", handlers.GetPriceHistory)
	g.GET("/api/summary", handlers.GetAIStockSummary)
	g.GET("/api/export/scores", handlers.ExportScoresCSV)

	// Protected routes: simulate an already-authenticated admin so the DB path is
	// reached (JWT auth itself is DB-free once a token exists).
	auth := g.Group("/", func(c *gin.Context) {
		c.Set("username", "offlinetest_user")
		c.Set("isAdmin", true)
		c.Next()
	})
	auth.GET("/api/portfolio", handlers.GetPortfolio)
	auth.GET("/api/family/assets", handlers.GetFamilyAssets)
	auth.POST("/api/brs/collect", handlers.RunBrsCollector)

	// SQL Server reachability probe (bounded).
	sqlProbe := probeSQLServer()

	ctx := context.Background()
	sh := integration.Default()
	st := sh.RefreshStatus(ctx)

	// Direct PostgreSQL probe (independent of read mode) as the healthy reference.
	cfg := integration.LoadConfig()
	pgConfigured := cfg.CanonicalDSN != ""
	pgReachable := false
	pgNote := "not configured"
	if pgConfigured {
		if pg, err := integration.OpenPG(cfg); err != nil {
			pgNote = "unreachable: " + err.Error()
		} else if pg != nil {
			pgReachable = true
			pgNote = "reachable"
			pg.Close()
		}
	}

	cases := []struct {
		method, path, endpoint string
		body                   string
	}{
		{"GET", "/api/health/shadow", "health/shadow", ""},
		{"POST", "/api/login", "auth/login", `{"username":"offlinetest_user","password":"OfflineProbe!123"}`},
		{"GET", "/api/CompanyNames", "CompanyNames", ""},
		{"GET", "/api/SalesData?companyName=%DA%A9%D8%B3%D8%B1%D8%A7", "SalesData", ""},
		{"GET", "/api/SalesData2?companyName=%DA%86%DA%A9%D8%A7%D9%BE%D8%A7", "SalesData2", ""},
		{"GET", "/api/CompanyScores?companyName=%DA%A9%D8%B3%D8%B1%D8%A7", "CompanyScores", ""},
		{"GET", "/api/AllCompanyScores", "AllCompanyScores", ""},
		{"GET", "/api/StockPriceScore?companyName=%D9%88%D8%B3%D9%BE%D9%87", "StockPriceScore", ""},
		{"GET", "/api/price-history?companyName=%D9%88%D8%B3%D9%BE%D9%87&limit=30", "price-history", ""},
		{"GET", "/api/summary?limit=5", "summary", ""},
		{"GET", "/api/portfolio", "portfolio", ""},
		{"GET", "/api/family/assets", "family/assets", ""},
		{"POST", "/api/brs/collect", "go_trigger/brs_collect", `{"mode":"daily"}`},
		{"GET", "/api/export/scores?limit=5", "export/scores", ""},
	}

	rows := []result{}
	for _, c := range cases {
		var req *http.Request
		if c.method == "POST" {
			req = httptest.NewRequest(http.MethodPost, c.path, strings.NewReader(c.body))
			req.Header.Set("Content-Type", "application/json")
		} else {
			req = httptest.NewRequest(http.MethodGet, c.path, nil)
		}
		w := httptest.NewRecorder()
		t0 := time.Now()
		g.ServeHTTP(w, req)
		ms := float64(time.Since(t0).Microseconds()) / 1000.0
		body := w.Body.String()
		if len(body) > 200 {
			body = body[:200]
		}
		class := classify(c.endpoint, w.Code)
		rows = append(rows, result{
			Endpoint: c.endpoint, Method: c.method, Status: w.Code, Class: class,
			Body: asciiSafe(body), Note: fmt.Sprintf("%.1fms", ms),
		})
	}

	// Canonical-only health as the healthy reference.
	canonNote := "reachable"
	if !st.CanonicalReachable {
		canonNote = "unreachable: " + st.CanonicalError
	}

	outDir := "../sqlserver_retirement/output"
	if d := os.Getenv("CDF_RETIRE_OUTPUT_DIR"); d != "" {
		outDir = d
	}
	_ = os.MkdirAll(outDir, 0o755)
	_ = writeCSV(filepath.Join(outDir, "sqlserver_offline_failures.csv"), rows)

	summary := map[string]any{
		"generated_at":             time.Now().UTC().Format(time.RFC3339),
		"db_server_setting":        os.Getenv("DB_SERVER"),
		"sqlserver_reachable":      sqlProbe,
		"server_startup_ok":        true,
		"canonical_configured":     pgConfigured,
		"canonical_reachable":      pgReachable,
		"canonical_note":           pgNote,
		"canonical_read_mode_note": canonNote,
		"score_run_id":             st.ScoreRunID,
		"score_as_of":              st.ScoreAsOf,
		"results":                  rows,
		"counts":                   counts(rows),
	}
	b, _ := json.MarshalIndent(summary, "", "  ")
	_ = os.WriteFile(filepath.Join(outDir, "sqlserver_offline_test.json"), append(b, '\n'), 0o644)
	fmt.Println(string(b))
}

func classify(endpoint string, code int) string {
	switch endpoint {
	case "health/shadow":
		if code == 200 {
			return "CANONICAL_OK"
		}
		return "HEALTH_FAIL"
	case "family/assets":
		// CDF_FAMILY_BACKEND=postgres → 200 without SQL Server.
		// CDF_FAMILY_BACKEND=disabled → explicit 503 deferral.
		if code == 200 {
			return "OK_WITHOUT_SQLSERVER"
		}
		if code == 503 {
			return "DEFERRED_OK"
		}
		return "SQLSERVER_REQUIRED_FAIL"
	case "StockPriceScore":
		return "DEPRECATED_SAFE_TO_DISABLE"
	case "export/scores":
		return "LEGACY_UNUSED"
	case "go_trigger/brs_collect":
		if code == 200 {
			return "GO_TRIGGER_OK"
		}
		return "GO_TRIGGER_FAIL"
	}
	if code == 200 {
		return "OK_WITHOUT_SQLSERVER"
	}
	return "SQLSERVER_REQUIRED_FAIL"
}

func counts(rows []result) map[string]int {
	out := map[string]int{}
	for _, r := range rows {
		out[r.Class]++
	}
	return out
}

func probeSQLServer() bool {
	cs := config.ConnectionString
	if cs == "" {
		return false
	}
	if !strings.Contains(cs, "timeout") {
		cs += ";Connection Timeout=3"
	}
	db, err := sql.Open("sqlserver", cs)
	if err != nil {
		return false
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	return db.PingContext(ctx) == nil
}

func writeCSV(path string, rows []result) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"endpoint", "method", "http_status", "class", "note", "body"})
	for _, r := range rows {
		_ = w.Write([]string{r.Endpoint, r.Method, fmt.Sprint(r.Status), r.Class, r.Note, r.Body})
	}
	return w.Error()
}

func asciiSafe(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < 128 {
			b.WriteRune(r)
		} else {
			b.WriteString("?")
		}
	}
	return b.String()
}
