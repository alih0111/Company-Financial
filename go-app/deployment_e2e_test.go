package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"go-app/config"
	"golang.org/x/crypto/bcrypt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestDeploymentPostgres(t *testing.T) {
	dsn := os.Getenv("RFA_DEPLOY_TEST_DSN")
	if dsn == "" {
		t.Skip("requires an explicitly configured isolated PostgreSQL database")
	}
	u, err := url.Parse(dsn)
	if err != nil || !strings.HasPrefix(strings.TrimPrefix(u.Path, "/"), "company_financial_test_") || (u.Hostname() != "127.0.0.1" && u.Hostname() != "localhost") {
		t.Fatal("deployment test requires a local company_financial_test_ database")
	}
	for _, key := range []string{"CANONICAL_DATABASE_URL", "CDF_CANONICAL_URL", "CDF_CANONICAL_DB", "CDF_PILOT_DB", "CORS_ALLOWED_ORIGINS", "TRUSTED_PROXIES", "FRONTEND_DIR"} {
		t.Setenv(key, "")
	}
	t.Setenv("DATABASE_URL", dsn)
	t.Setenv("APP_ENV", "production")
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	t.Setenv("CDF_FAMILY_BACKEND", "disabled")
	t.Setenv("CDF_REGISTRATION_ENABLED", "0")
	t.Setenv("JWT_SECRET", "isolated-deployment-test-secret-32bytes-minimum")
	gin.SetMode(gin.TestMode)
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	suffix := fmt.Sprint(time.Now().UnixNano())
	users := []string{"test_owner_" + suffix, "test_other_" + suffix}
	password := "isolated-test-password-123"
	if err := createAdmin([]string{"--username", users[0], "--email", users[0] + "@example.com"}, strings.NewReader(password+"\n")); err != nil {
		t.Fatal(err)
	}
	hash, _ := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if _, err := db.Exec(`INSERT INTO auth.users (username,email,password_hash) VALUES ($1,$2,$3)`, users[1], users[1]+"@example.com", string(hash)); err != nil {
		t.Fatal(err)
	}
	var company, security string
	defer func() {
		_, _ = db.Exec(`DELETE FROM portfolio.positions WHERE portfolio_id IN (SELECT p.id FROM portfolio.portfolios p JOIN auth.users u ON u.id=p.user_id WHERE u.username=$1 OR u.username=$2)`, users[0], users[1])
		_, _ = db.Exec(`DELETE FROM portfolio.portfolios WHERE user_id IN (SELECT id FROM auth.users WHERE username=$1 OR username=$2)`, users[0], users[1])
		_, _ = db.Exec(`DELETE FROM auth.users WHERE username=$1 OR username=$2`, users[0], users[1])
		_, _ = db.Exec(`DELETE FROM portfolio.assets WHERE security_id=$1`, security)
		_, _ = db.Exec(`DELETE FROM core.securities WHERE id=$1`, security)
		_, _ = db.Exec(`DELETE FROM core.companies WHERE id=$1`, company)
	}()
	if err := db.QueryRow(`INSERT INTO core.companies (display_name,normalized_name) VALUES ($1,$1) RETURNING id::text`, "isolated_company_"+suffix).Scan(&company); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`INSERT INTO core.securities (company_id,codal_symbol,is_primary) VALUES ($1,$2,true) RETURNING id::text`, company, "TEST"+suffix).Scan(&security); err != nil {
		t.Fatal(err)
	}
	r, err := newRouter()
	if err != nil {
		t.Fatal(err)
	}
	request := func(method, path, token string, data any) *httptest.ResponseRecorder {
		body, _ := json.Marshal(data)
		req := httptest.NewRequest(method, path, bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.AddCookie(&http.Cookie{Name: config.SessionCookieName(), Value: token})
			req.Header.Set("Origin", "https://example.com")
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w
	}
	if got := request("GET", "/api/health/ready", "", nil); got.Code != 200 {
		t.Fatalf("readiness: %d", got.Code)
	}
	tokens := make([]string, 2)
	for i, user := range users {
		got := request("POST", "/api/login", "", map[string]string{"username": user, "password": password})
		if got.Code != 200 {
			t.Fatalf("login: %d %s", got.Code, got.Body)
		}
		var body map[string]any
		_ = json.Unmarshal(got.Body.Bytes(), &body)
		if _, leaked := body["token"]; leaked {
			t.Fatal("browser login exposed a readable token")
		}
		for _, cookie := range got.Result().Cookies() {
			if cookie.Name == config.SessionCookieName() {
				if !cookie.HttpOnly || !cookie.Secure || cookie.SameSite != http.SameSiteStrictMode || cookie.Domain != "" || cookie.Path != "/" {
					t.Fatal("insecure production session cookie")
				}
				tokens[i] = cookie.Value
			}
		}
		if len(tokens[i]) != 64 {
			t.Fatal("missing opaque browser session")
		}
		if got := request("GET", "/api/me", tokens[i], nil); got.Code != 200 {
			t.Fatalf("session: %d", got.Code)
		}
	}
	if got := request("GET", "/api/financial-statements?companyName=TEST"+suffix, tokens[0], nil); got.Code != 200 {
		t.Fatalf("canonical financial statements: %d %s", got.Code, got.Body)
	}
	if got := request("POST", "/api/login", "", map[string]string{"username": users[0], "password": "incorrect"}); got.Code != 401 {
		t.Fatalf("wrong password: %d", got.Code)
	}
	if got := request("POST", "/api/run-script", tokens[0], map[string]any{"baseUrl": "http://169.254.169.254/"}); got.Code != 410 {
		t.Fatalf("retired collector remained reachable: %d", got.Code)
	}
	for _, endpoint := range []string{"/api/sync-codal/jobs", "/api/brs/collect", "/api/market/collect", "/api/admin/analytics/refresh", "/api/family/assets"} {
		if got := request("POST", endpoint, tokens[1], map[string]any{}); got.Code != 403 {
			t.Fatalf("regular account reached %s: %d", endpoint, got.Code)
		}
	}
	forged, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{"username": users[0], "isAdmin": true, "exp": time.Now().Add(time.Hour).Unix()}).SignedString(config.JWTSecret())
	legacy := httptest.NewRequest("GET", "/api/me", nil)
	legacy.Header.Set("Authorization", "Bearer "+forged)
	rejected := httptest.NewRecorder()
	r.ServeHTTP(rejected, legacy)
	if rejected.Code != 401 {
		t.Fatal("legacy bearer token bypassed the production session store")
	}

	position := map[string]any{"company_id": security, "quantity": 10, "buy_price": 50000, "company_name": "untrusted name"}
	var writes sync.WaitGroup
	for i := 0; i < 6; i++ {
		writes.Add(1)
		go func() {
			defer writes.Done()
			if got := request("POST", "/api/portfolio", tokens[0], position); got.Code != 200 {
				t.Errorf("concurrent position write: %d %s", got.Code, got.Body)
			}
		}()
	}
	writes.Wait()
	var count int
	_ = db.QueryRow(`SELECT count(*) FROM portfolio.portfolios p JOIN auth.users u ON u.id=p.user_id WHERE u.username=$1 AND p.name='default'`, users[0]).Scan(&count)
	if count != 1 {
		t.Fatalf("concurrent writes created %d default portfolios", count)
	}
	for i, want := range []int{1, 0} {
		got := request("GET", "/api/portfolio", tokens[i], nil)
		if got.Code != 200 {
			t.Fatalf("read portfolio: %d %s", got.Code, got.Body)
		}
		var body struct {
			Holdings []any `json:"holdings"`
		}
		if err := json.Unmarshal(got.Body.Bytes(), &body); err != nil || len(body.Holdings) != want {
			t.Fatalf("user %d: expected %d holdings", i, want)
		}
	}
	if got := request("DELETE", "/api/portfolio/"+security, tokens[1], nil); got.Code != 404 {
		t.Fatalf("other user delete: %d", got.Code)
	}
	position["buy_price"] = -1
	if got := request("POST", "/api/portfolio", tokens[0], position); got.Code != 400 {
		t.Fatalf("negative cost accepted: %d", got.Code)
	}
	if _, err := db.Exec(`UPDATE auth.users SET is_admin=false WHERE username=$1`, users[0]); err != nil {
		t.Fatal(err)
	}
	if got := request("POST", "/api/run-script", tokens[0], map[string]any{}); got.Code != 403 {
		t.Fatalf("removed admin role still usable: %d", got.Code)
	}
	if _, err := db.Exec(`UPDATE auth.users SET is_active=false WHERE username=$1`, users[1]); err != nil {
		t.Fatal(err)
	}
	if got := request("GET", "/api/me", tokens[1], nil); got.Code != 401 {
		t.Fatalf("disabled account still usable: %d", got.Code)
	}
	if got := request("DELETE", "/api/portfolio/"+security, tokens[0], nil); got.Code != 200 {
		t.Fatalf("owner delete: %d %s", got.Code, got.Body)
	}
	// Cookie replay fails after logout; merely deleting a browser token is not sufficient.
	if got := request("POST", "/api/logout", tokens[0], nil); got.Code != 200 {
		t.Fatalf("logout: %d", got.Code)
	}
	if got := request("GET", "/api/me", tokens[0], nil); got.Code != 401 {
		t.Fatalf("revoked session can be replayed: %d", got.Code)
	}

	newLogin := request("POST", "/api/login", "", map[string]string{"username": users[0], "password": password})
	newSession := ""
	for _, cookie := range newLogin.Result().Cookies() {
		if cookie.Name == config.SessionCookieName() {
			newSession = cookie.Value
		}
	}
	if newLogin.Code != 200 || len(newSession) != 64 {
		t.Fatal("fresh session unavailable")
	}
	if _, err := db.Exec(`UPDATE auth.sessions SET last_seen_at=now()-interval '31 minutes' WHERE user_id=(SELECT id FROM auth.users WHERE username=$1)`, users[0]); err != nil {
		t.Fatal(err)
	}
	if got := request("GET", "/api/me", newSession, nil); got.Code != 401 {
		t.Fatal("idle session remained usable")
	}

	// Exercise real HTTPS transport and a cookie jar, not only forged headers.
	httpsServer := httptest.NewTLSServer(r)
	defer httpsServer.Close()
	client := httpsServer.Client()
	client.Jar, _ = cookiejar.New(nil)
	payload, _ := json.Marshal(map[string]string{"username": users[0], "password": password})
	loggedIn, err := client.Post(httpsServer.URL+"/api/login", "application/json", bytes.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, loggedIn.Body)
	loggedIn.Body.Close()
	if loggedIn.StatusCode != 200 {
		t.Fatalf("HTTPS login: %d", loggedIn.StatusCode)
	}
	me, err := client.Get(httpsServer.URL + "/api/me")
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, me.Body)
	me.Body.Close()
	if me.StatusCode != 200 {
		t.Fatal("Secure cookie was not accepted over HTTPS")
	}
	logoutRequest, _ := http.NewRequest("POST", httpsServer.URL+"/api/logout", nil)
	logoutRequest.Header.Set("Origin", httpsServer.URL)
	loggedOut, err := client.Do(logoutRequest)
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, loggedOut.Body)
	loggedOut.Body.Close()
	if loggedOut.StatusCode != 200 {
		t.Fatal("HTTPS logout failed")
	}
	me, err = client.Get(httpsServer.URL + "/api/me")
	if err != nil {
		t.Fatal(err)
	}
	io.Copy(io.Discard, me.Body)
	me.Body.Close()
	if me.StatusCode != 401 {
		t.Fatal("HTTPS cookie survived logout")
	}

}
