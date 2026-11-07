package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"go-app/middleware"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDataAccessPostgres(t *testing.T) {
	dsn := os.Getenv("RFA_DEPLOY_TEST_DSN")
	if dsn == "" {
		t.Skip("requires isolated PostgreSQL")
	}
	u, err := url.Parse(dsn)
	if err != nil || !strings.HasPrefix(u.Path, "/company_financial_test_") || (u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1") {
		t.Fatal("unsafe test database")
	}
	for _, key := range []string{"CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "CDF_CANONICAL_DB", "CDF_PILOT_DB", "CORS_ALLOWED_ORIGINS", "TRUSTED_PROXIES"} {
		t.Setenv(key, "")
	}
	t.Setenv("DATABASE_URL", dsn)
	t.Setenv("APP_ENV", "production")
	t.Setenv("JWT_SECRET", "isolated-data-budget-secret-at-least-32bytes")
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	names := []string{fmt.Sprintf("data_reader_%d", time.Now().UnixNano()), fmt.Sprintf("data_owner_%d", time.Now().UnixNano())}
	tokens := []string{}
	for i, name := range names {
		var id string
		if err = db.QueryRow(`INSERT INTO auth.users(username,email,password_hash,is_admin) VALUES($1,$2,'not-a-login-hash',$3) RETURNING id::text`, name, name+"@example.com", i == 1).Scan(&id); err != nil {
			t.Fatal(err)
		}
		defer db.Exec(`DELETE FROM auth.users WHERE username=$1`, name)
		random := make([]byte, 32)
		if _, err = rand.Read(random); err != nil {
			t.Fatal(err)
		}
		secret := hex.EncodeToString(random)
		hash := sha256.Sum256([]byte(secret))
		if _, err = db.Exec(`INSERT INTO auth.sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '12 hours')`, hash[:], id); err != nil {
			t.Fatal(err)
		}
		tokens = append(tokens, secret)
	}
	root := t.TempDir()
	public := t.TempDir()
	os.WriteFile(filepath.Join(root, "index.html"), []byte("<html>RFA</html>"), 0600)
	os.Mkdir(filepath.Join(public, "strategies"), 0700)
	os.WriteFile(filepath.Join(public, "strategies", "private.csv"), []byte("PRIVATE_TEST_ROWS"), 0600)
	t.Setenv("FRONTEND_DIR", root)
	t.Setenv("PUBLIC_ARTIFACTS_DIR", public)
	router, err := newRouter()
	if err != nil {
		t.Fatal(err)
	}
	request := func(method, path, token string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, nil)
		if token != "" {
			req.AddCookie(&http.Cookie{Name: config.SessionCookieName(), Value: token})
		}
		req.Header.Set("Range", "bytes=0-4")
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		return w
	}
	// Production's proxy waits for readiness before forwarding users. Do the same
	// here: a cold Windows test executable may need a database connection retry.
	readyDeadline := time.Now().Add(20 * time.Second)
	for {
		if w := request("GET", "/api/health/ready", ""); w.Code == 200 {
			break
		}
		if time.Now().After(readyDeadline) {
			t.Fatal("isolated database did not become ready")
		}
		time.Sleep(100 * time.Millisecond)
	}
	for _, path := range []string{"/strategies/private.csv", "/strategies//private.csv", "/assets/../strategies/private.csv", "/strategies%2fprivate.csv", "/STRATEGIES/private.csv"} {
		for _, method := range []string{"GET", "HEAD"} {
			for index, token := range []string{"", tokens[0]} {
				w := request(method, path, token)
				want := 401
				if index == 1 {
					want = 403
				}
				if (w.Code != want && w.Code != 404) || strings.Contains(w.Body.String(), "PRIVATE_TEST_ROWS") {
					t.Fatalf("archive bypass %s %s: %d", method, path, w.Code)
				}
			}
		}
	}
	if w := request("GET", "/strategies/private.csv", tokens[1]); w.Code != 206 {
		t.Fatalf("administrator archive unavailable: %d", w.Code)
	}
	for _, path := range []string{"/api/AllCompanyScores", "/api/export/scores", "/api/qvt-v2/ranking", "/api/reportflow"} {
		if w := request("GET", path, tokens[0]); w.Code != 403 {
			t.Fatalf("bulk route available to reader: %s %d", path, w.Code)
		}
	}
	if _, err = db.Exec(`INSERT INTO auth.data_policies(user_id,requests_limit,records_limit,bytes_limit,symbols_limit) SELECT id,10,100,65536,10 FROM auth.users WHERE username=$1`, names[0]); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 10; i++ {
		if w := request("GET", "/api/companies", tokens[0]); w.Code != 200 {
			t.Fatalf("normal data read %d: %d %s", i, w.Code, w.Body.String())
		}
	}
	denied := request("GET", "/api/companies", tokens[0])
	if denied.Code != 429 || !strings.Contains(denied.Body.String(), "data_quota_exceeded") || denied.Header().Get("Retry-After") == "" {
		t.Fatalf("quota denial invalid: %d %s", denied.Code, denied.Body)
	}
	// A new router has fresh in-memory rate limits, but must not reset the budget.
	router, err = newRouter()
	if err != nil {
		t.Fatal(err)
	}
	if w := request("GET", "/api/companies", tokens[0]); w.Code != 429 {
		t.Fatal("router restart reset the budget")
	}
	for _, path := range []string{"/api/me", "/api/data-access"} {
		if w := request("GET", path, tokens[0]); w.Code != 200 {
			t.Fatal("quota blocked account management")
		}
	}
	if w := request("GET", "/api/data-access", tokens[1]); w.Code != 200 || !strings.Contains(w.Body.String(), `"unlimited":true`) {
		t.Fatal("administrator budget incorrect")
	}
	if _, err = db.Exec(`UPDATE auth.data_usage SET requests=0 WHERE user_id=(SELECT id FROM auth.users WHERE username=$1)`, names[0]); err != nil {
		t.Fatal(err)
	}
	router.GET("/api/fixture-budget", middleware.AuthMiddleware(), middleware.DataAccess(), func(c *gin.Context) {
		rows := make([]string, 101)
		for i := range rows {
			rows[i] = "PRIVATE_RESPONSE_MARKER"
		}
		c.JSON(200, rows)
	})
	if w := request("GET", "/api/fixture-budget", tokens[0]); w.Code != 429 || strings.Contains(w.Body.String(), "PRIVATE_RESPONSE_MARKER") {
		t.Fatalf("unpaid rows leaked: %d", w.Code)
	}
	router.GET("/api/fixture-overflow", middleware.AuthMiddleware(), middleware.DataAccess(), func(c *gin.Context) { c.JSON(200, gin.H{"secret": strings.Repeat("PRIVATE_RESPONSE_MARKER", 120000)}) })
	if w := request("GET", "/api/fixture-overflow", tokens[0]); w.Code != 413 || strings.Contains(w.Body.String(), "PRIVATE_RESPONSE_MARKER") {
		t.Fatalf("oversized output leaked: %d", w.Code)
	}

	policy := []byte(`{"enabled":false,"limits":{"requests":10,"records":100,"bytes":65536,"symbols":10}}`)
	for index, token := range []string{tokens[0], tokens[1]} {
		req := httptest.NewRequest("PUT", "/api/admin/data-access/"+names[0], bytes.NewReader(policy))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Origin", "https://example.com")
		req.AddCookie(&http.Cookie{Name: config.SessionCookieName(), Value: token})
		w := httptest.NewRecorder()
		router.ServeHTTP(w, req)
		want := 403
		if index == 1 {
			want = 200
		}
		if w.Code != want {
			t.Fatalf("data policy authorization/write: %d, want %d", w.Code, want)
		}
	}
	if w := request("GET", "/api/companies", tokens[0]); w.Code != 403 || !strings.Contains(w.Body.String(), "data_access_disabled") {
		t.Fatal("administrator could not disable data delivery")
	}
	if w := request("GET", "/api/admin/data-access", tokens[1]); w.Code != 200 || !strings.Contains(w.Body.String(), names[0]) {
		t.Fatal("data abuse overview unavailable to administrator")
	}

}
