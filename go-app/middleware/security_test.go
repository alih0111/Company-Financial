package middleware

import (
	"bytes"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCookieWritesRequireTrustedOrigin(t *testing.T) {
	t.Setenv("APP_ENV", "production")
	t.Setenv("CORS_ALLOWED_ORIGINS", "")
	for _, tc := range []struct {
		name, origin, site string
		cookie             bool
		status             int
	}{
		{"same origin", "https://example.com", "same-origin", true, 200},
		{"foreign origin", "https://attacker.example", "cross-site", true, 403},
		{"missing origin", "", "", true, 403},
		{"insecure origin", "http://example.com", "same-origin", true, 403},
		{"subdomain", "https://other.example.com", "same-site", true, 403},
		{"null origin", "null", "cross-site", true, 403},
		{"curl without a browser session", "", "", false, 200},
		{"cross site login", "https://attacker.example", "cross-site", false, 403},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := gin.New()
			r.POST("/", OriginGuard(), func(c *gin.Context) { c.Status(200) })
			req := httptest.NewRequest("POST", "/", nil)
			req.Header.Set("Origin", tc.origin)
			req.Header.Set("Sec-Fetch-Site", tc.site)
			if tc.cookie {
				req.AddCookie(&http.Cookie{Name: config.SessionCookieName(), Value: "fake-session"})
			}
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != tc.status {
				t.Fatalf("status %d, want %d", w.Code, tc.status)
			}
		})
	}
}

func TestChunkedAndFormBodiesCannotBypassLimits(t *testing.T) {
	for _, tc := range []struct {
		body, kind string
		status     int
	}{
		{strings.Repeat("x", (2<<20)+1), "application/json", 413},
		{"username=user&password=secret", "application/x-www-form-urlencoded", 415},
		{`{"value":1}`, "application/json", 200},
	} {
		r := gin.New()
		r.POST("/", RequestBodyLimit(), func(c *gin.Context) { c.Status(200) })
		req := httptest.NewRequest("POST", "/", strings.NewReader(tc.body))
		req.ContentLength = -1
		req.Header.Set("Content-Type", tc.kind)
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != tc.status {
			t.Fatalf("status %d, want %d", w.Code, tc.status)
		}
	}
}

func TestFailuresAndLogsDoNotExposeSecrets(t *testing.T) {
	t.Setenv("APP_ENV", "production")
	var logs bytes.Buffer
	previous := log.Writer()
	log.SetOutput(&logs)
	defer log.SetOutput(previous)
	r := gin.New()
	r.Use(RequestSafety())
	r.GET("/error", func(c *gin.Context) { c.JSON(500, gin.H{"error": "TEST_PRIVATE_SECRET"}) })
	r.GET("/panic", func(c *gin.Context) { panic("TEST_PRIVATE_SECRET") })
	for _, path := range []string{"/error", "/panic"} {
		req := httptest.NewRequest("GET", path+"?key=TEST_PRIVATE_SECRET", nil)
		req.Header.Set("Cookie", "session=TEST_PRIVATE_SECRET")
		req.Header.Set("Authorization", "Bearer TEST_PRIVATE_SECRET")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != 500 || len(w.Header().Get("X-Request-ID")) != 32 {
			t.Fatal("unexpected failure response")
		}
		if strings.Contains(w.Body.String(), "TEST_PRIVATE_SECRET") || strings.Contains(logs.String(), "TEST_PRIVATE_SECRET") {
			t.Fatal("sensitive response, query, header or panic was exposed")
		}
	}
}

func TestAIEndpointsSharePerUserQuota(t *testing.T) {
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("username", "user"); c.Next() })
	quota := UserRateLimit(1, time.Minute)
	r.POST("/chat", quota, func(c *gin.Context) { c.Status(200) })
	r.POST("/stream", quota, func(c *gin.Context) { c.Status(200) })
	for index, path := range []string{"/chat", "/stream"} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("POST", path, nil))
		want := 200
		if index == 1 {
			want = 429
		}
		if w.Code != want {
			t.Fatalf("shared quota bypass: %d", w.Code)
		}
	}
}

func TestExpensiveAuthWorkHasABoundedConcurrency(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	done := make(chan struct{})
	r := gin.New()
	r.POST("/", ConcurrencyLimit(1), func(c *gin.Context) { close(entered); <-release; c.Status(200) })
	go func() { defer close(done); r.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("POST", "/", nil)) }()
	<-entered
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest("POST", "/", nil))
	close(release)
	<-done
	if w.Code != 503 || w.Header().Get("Retry-After") == "" {
		t.Fatal("unbounded parallel authentication work")
	}
}
