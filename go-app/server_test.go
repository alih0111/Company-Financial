package main

import (
	"github.com/golang-jwt/jwt/v4"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestProductionServingAndRouteProtection(t *testing.T) {
	root := t.TempDir()
	_ = os.WriteFile(filepath.Join(root, "index.html"), []byte("<html>RFA</html>"), 0600)
	_ = os.Mkdir(filepath.Join(root, "assets"), 0700)
	_ = os.WriteFile(filepath.Join(root, "assets", "app-123.js"), []byte("// build"), 0600)
	_ = os.WriteFile(filepath.Join(root, ".env"), []byte("secret"), 0600)
	public := t.TempDir()
	_ = os.Mkdir(filepath.Join(public, "strategies"), 0700)
	artifact := filepath.Join(public, "strategies", "live.json")
	_ = os.WriteFile(artifact, []byte(`{"version":1}`), 0600)
	t.Setenv("PUBLIC_ARTIFACTS_DIR", public)
	t.Setenv("FRONTEND_DIR", root)
	t.Setenv("APP_ENV", "test")
	t.Setenv("TRUSTED_PROXIES", "")
	t.Setenv("CORS_ALLOWED_ORIGINS", "https://example.com")
	secret := "test-only-secret-at-least-32-characters"
	t.Setenv("JWT_SECRET", secret)
	r, err := newRouter()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		method, path string
		status       int
	}{
		{"GET", "/", 200}, {"GET", "/dashboard", 200}, {"HEAD", "/portfolio", 200},
		{"GET", "/assets/app-123.js", 200}, {"GET", "/assets/missing.js", 404},
		{"GET", "/api/missing", 404}, {"GET", "/.env", 404}, {"GET", "/a/../.env", 404},
		{"GET", "/api/health/live", 200}, {"GET", "/api/health/shadow", 401},
		{"GET", "/api/portfolio", 401}, {"GET", "/api/family/assets", 401},
	} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, nil))
		if w.Code != tc.status {
			t.Errorf("%s %s = %d, want %d", tc.method, tc.path, w.Code, tc.status)
		}
		if w.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Error("missing security header")
		}
	}
	token, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{"username": "user", "isAdmin": false, "exp": time.Now().Add(time.Hour).Unix()}).SignedString([]byte(secret))
	for _, endpoint := range []string{"/api/run-script", "/api/run-script2", "/api/fetchAllData", "/api/admin/analytics/refresh", "/api/family/assets"} {
		req := httptest.NewRequest("POST", endpoint, strings.NewReader("{}"))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != 403 {
			t.Errorf("non-admin can reach %s: %d", endpoint, w.Code)
		}
	}
	for _, origin := range []string{"https://example.com", "https://evil.example"} {
		req := httptest.NewRequest("OPTIONS", "/api/login", nil)
		req.Host = "api.example.com"
		req.Header.Set("Origin", origin)
		req.Header.Set("Access-Control-Request-Method", "POST")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if origin == "https://example.com" && w.Header().Get("Access-Control-Allow-Origin") != origin {
			t.Error("allowed origin rejected")
		}
		if origin != "https://example.com" && w.Header().Get("Access-Control-Allow-Origin") != "" {
			t.Error("foreign origin allowed")
		}
	}
	adminToken, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{"username": "owner", "isAdmin": true, "exp": time.Now().Add(time.Hour).Unix()}).SignedString([]byte(secret))
	for _, version := range []string{`{"version":1}`, `{"version":2}`} {
		_ = os.WriteFile(artifact, []byte(version), 0600)
		w := httptest.NewRecorder()
		req := httptest.NewRequest("GET", "/strategies/live.json", nil)
		req.Header.Set("Authorization", "Bearer "+adminToken)
		r.ServeHTTP(w, req)
		if w.Code != 200 || w.Body.String() != version || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatal("published strategy artifact is stale or unavailable")
		}
	}
}

func TestFrontendDoesNotFollowSymlinkOutsideItsRoot(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	_ = os.WriteFile(filepath.Join(root, "index.html"), []byte("<html>public</html>"), 0600)
	_ = os.WriteFile(filepath.Join(outside, "private.json"), []byte(`{"password":"PRIVATE_TEST_VALUE"}`), 0600)
	if err := os.Symlink(filepath.Join(outside, "private.json"), filepath.Join(root, "public.json")); err != nil {
		t.Skip("host does not permit symlink creation")
	}
	t.Setenv("FRONTEND_DIR", root)
	t.Setenv("PUBLIC_ARTIFACTS_DIR", "")
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	t.Setenv("TRUSTED_PROXIES", "")
	r, err := newRouter()
	if err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	t.Setenv("APP_ENV", "test")
	t.Setenv("JWT_SECRET", "isolated-symlink-test-secret-32bytes")
	token, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{"username": "owner", "isAdmin": true, "exp": time.Now().Add(time.Hour).Unix()}).SignedString([]byte("isolated-symlink-test-secret-32bytes"))
	req := httptest.NewRequest("GET", "/public.json", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)
	if w.Code != 404 || strings.Contains(w.Body.String(), "PRIVATE_TEST_VALUE") {
		t.Fatal("symlink leaked a file outside the public root")
	}
}

func TestPublicSummaryUsesActualMonthlyReportWithoutExposingInputs(t *testing.T) {
	t.Setenv("APP_ENV", "test")
	t.Setenv("FRONTEND_DIR", "")
	t.Setenv("PUBLIC_ARTIFACTS_DIR", "../client/public")
	t.Setenv("TRUSTED_PROXIES", "")
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	r, err := newRouter()
	if err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("GET", "/api/strategy/summary", nil))
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"id":"from-1401"`) {
		t.Fatalf("public monthly summary unavailable: %d", w.Code)
	}
	for _, key := range []string{`"positions"`, `"downloads"`, `"path"`, `"policy_sha256"`, `"FactorRaw"`} {
		if strings.Contains(w.Body.String(), key) {
			t.Fatal("public summary exposed detailed research data")
		}
	}
	// A quarterly-only case must not be presented as a monthly strategy result.
	if strings.Contains(w.Body.String(), `"id":"from-1402"`) {
		t.Fatal("quarterly case mislabeled as the monthly strategy")
	}
}
