package handlers

import (
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func TestSignupPostgres(t *testing.T) {
	dsn := os.Getenv("RFA_DEPLOY_TEST_DSN")
	if dsn == "" {
		t.Skip("requires explicit isolated PostgreSQL")
	}
	u, err := url.Parse(dsn)
	if err != nil || !strings.HasPrefix(strings.TrimPrefix(u.Path, "/"), "company_financial_test_") || (u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1") {
		t.Fatal("test database guard")
	}
	for _, key := range []string{"CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "CDF_CANONICAL_DB", "CDF_PILOT_DB"} {
		t.Setenv(key, "")
	}
	t.Setenv("DATABASE_URL", dsn)
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	t.Setenv("CDF_REGISTRATION_ENABLED", "1")
	db, err := config.GetPG()
	if err != nil {
		t.Fatal(err)
	}
	username := fmt.Sprintf("signup_test_%d", time.Now().UnixNano())
	email := username + "@example.com"
	defer db.Exec(`DELETE FROM auth.users WHERE username=$1`, username)
	code, err := signupCodes.issue(email, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	r := gin.New()
	r.POST("/register", Register)
	data, _ := json.Marshal(map[string]any{"email": strings.ToUpper(email), "username": username, "password": "test-password-123", "code": code, "isAdmin": true})
	for _, status := range []int{200, 400} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("POST", "/register", strings.NewReader(string(data))))
		if w.Code != status {
			t.Fatalf("registration response %d, want %d: %s", w.Code, status, w.Body)
		}
	}
	var admin bool
	if err := db.QueryRow(`SELECT is_admin FROM auth.users WHERE username=$1`, username).Scan(&admin); err != nil || admin {
		t.Fatal("registration granted admin or did not persist")
	}
}
