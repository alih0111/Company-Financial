package middleware

import (
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestAuthenticationRejectsMissingExpiryAndOtherAlgorithms(t *testing.T) {
	secret := "test-only-secret-32-bytes-long-for-auth"
	t.Setenv("JWT_SECRET", secret)
	t.Setenv("APP_ENV", "test")
	for _, tc := range []struct {
		name      string
		algorithm jwt.SigningMethod
		claims    jwt.MapClaims
		status    int
	}{
		{"valid", jwt.SigningMethodHS256, jwt.MapClaims{"username": "user", "exp": time.Now().Add(time.Hour).Unix()}, 200},
		{"no expiry", jwt.SigningMethodHS256, jwt.MapClaims{"username": "user"}, 401},
		{"expired", jwt.SigningMethodHS256, jwt.MapClaims{"username": "user", "exp": time.Now().Add(-time.Hour).Unix()}, 401},
		{"wrong algorithm", jwt.SigningMethodHS384, jwt.MapClaims{"username": "user", "exp": time.Now().Add(time.Hour).Unix()}, 401},
		{"missing user", jwt.SigningMethodHS256, jwt.MapClaims{"exp": time.Now().Add(time.Hour).Unix()}, 401},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := gin.New()
			r.GET("/", AuthMiddleware(), func(c *gin.Context) { c.Status(200) })
			token, _ := jwt.NewWithClaims(tc.algorithm, tc.claims).SignedString([]byte(secret))
			req := httptest.NewRequest("GET", "/", nil)
			req.Header.Set("Authorization", "Bearer "+token)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != tc.status {
				t.Fatalf("status %d; want %d", w.Code, tc.status)
			}
		})
	}
}

func TestRateLimitDoesNotTrustForwardedIP(t *testing.T) {
	r := gin.New()
	_ = r.SetTrustedProxies(nil)
	r.GET("/", RateLimit(1, time.Minute), func(c *gin.Context) { c.Status(200) })
	for i, want := range []int{200, http.StatusTooManyRequests} {
		req := httptest.NewRequest("GET", "/", nil)
		req.Header.Set("X-Forwarded-For", []string{"1.1.1.1", "2.2.2.2"}[i])
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != want {
			t.Fatalf("status %d, want %d", w.Code, want)
		}
	}
}
