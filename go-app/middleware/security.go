package middleware

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Neither query strings nor headers, body, cookies, panic values or passwords
// belong in HTTP access logs. Keep a server-generated correlation ID instead.
func RequestSafety() gin.HandlerFunc {
	return func(c *gin.Context) {
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			c.AbortWithStatus(503)
			return
		}
		id := hex.EncodeToString(random[:])
		c.Set("requestID", id)
		c.Header("X-Request-ID", id)
		start := time.Now()
		writer := &safeErrorWriter{ResponseWriter: c.Writer, id: id}
		c.Writer = writer
		defer func() {
			if recover() != nil {
				log.Printf("request panic id=%s", id)
				if !c.Writer.Written() {
					c.AbortWithStatusJSON(500, gin.H{"error": "خطای داخلی سرویس", "request_id": id})
				} else {
					c.Abort()
				}
			}
			path := c.FullPath()
			if path == "" {
				path = "/unmatched"
			}
			log.Printf("request id=%s method=%s route=%s status=%d duration=%s", id, c.Request.Method, path, c.Writer.Status(), time.Since(start))
		}()
		c.Next()
	}
}

type safeErrorWriter struct {
	gin.ResponseWriter
	id        string
	sanitized bool
}

func (w *safeErrorWriter) Write(body []byte) (int, error) {
	if config.Production() && w.Status() >= 500 {
		if !w.sanitized {
			w.sanitized = true
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Del("Content-Length")
			data, _ := json.Marshal(gin.H{"error": "سرویس موقتاً در دسترس نیست؛ دوباره تلاش کنید", "request_id": w.id})
			_, err := w.ResponseWriter.Write(data)
			return len(body), err
		}
		return len(body), nil
	}
	return w.ResponseWriter.Write(body)
}
func (w *safeErrorWriter) WriteString(body string) (int, error) { return w.Write([]byte(body)) }

func OriginGuard() gin.HandlerFunc {
	return func(c *gin.Context) {
		method := c.Request.Method
		if method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions {
			c.Next()
			return
		}
		origin := c.GetHeader("Origin")
		_, cookieErr := c.Cookie(config.SessionCookieName())
		valid := false
		if origin != "" {
			u, err := url.Parse(origin)
			valid = err == nil && u.User == nil && u.Path == "" && u.RawQuery == "" && u.Fragment == "" && u.Host == c.Request.Host && (u.Scheme == "https" || !config.Production() && u.Scheme == "http")
			if err == nil && !config.Production() && (u.Hostname() == "localhost" || u.Hostname() == "127.0.0.1") && u.Port() == "3000" && (u.Scheme == "http" || u.Scheme == "https") {
				if remote := net.ParseIP(c.RemoteIP()); remote != nil && remote.IsLoopback() {
					valid = true
				}
			}
			if !valid {
				for _, allowed := range config.CSVEnv("CORS_ALLOWED_ORIGINS") {
					if origin == allowed {
						valid = true
						break
					}
				}
			}
		}
		if origin != "" && !valid || origin == "" && cookieErr == nil || strings.EqualFold(c.GetHeader("Sec-Fetch-Site"), "cross-site") && !valid {
			c.AbortWithStatusJSON(403, gin.H{"error": "مبدأ درخواست معتبر نیست"})
			return
		}
		c.Next()
	}
}

// Read the bounded JSON body before binding so oversized chunked input returns
// 413 too, and never makes it into password hashing, SQL or a child process.
func RequestBodyLimit() gin.HandlerFunc {
	return func(c *gin.Context) {
		const maximum = 2 << 20
		if c.Request.ContentLength > maximum {
			c.AbortWithStatusJSON(413, gin.H{"error": "حجم درخواست بیش از حد مجاز است"})
			return
		}
		if c.Request.Body != nil {
			body, err := io.ReadAll(io.LimitReader(c.Request.Body, maximum+1))
			_ = c.Request.Body.Close()
			if err != nil {
				c.AbortWithStatus(400)
				return
			}
			if len(body) > maximum {
				c.AbortWithStatusJSON(413, gin.H{"error": "حجم درخواست بیش از حد مجاز است"})
				return
			}
			if len(body) > 0 {
				kind, _, err := mime.ParseMediaType(c.GetHeader("Content-Type"))
				if err != nil || kind != "application/json" {
					c.AbortWithStatusJSON(415, gin.H{"error": "بدنه باید JSON باشد"})
					return
				}
			}
			c.Request.Body = io.NopCloser(bytes.NewReader(body))
		}
		c.Next()
	}
}

func RetiredCollector() gin.HandlerFunc {
	return func(c *gin.Context) {
		if config.Production() || config.SQLServerMode() == "offline_expected" {
			c.AbortWithStatusJSON(410, gin.H{"error": "این پردازش قدیمی غیرفعال است؛ از دریافت canonical استفاده کنید"})
			return
		}
		c.Next()
	}
}

// Bound expensive password hashing and mail requests across all client IPs.
// Per-IP limits alone do not contain a distributed flood of distinct accounts.
func ConcurrencyLimit(maximum int) gin.HandlerFunc {
	slots := make(chan struct{}, maximum)
	return func(c *gin.Context) {
		select {
		case slots <- struct{}{}:
			defer func() { <-slots }()
			c.Next()
		default:
			c.Header("Retry-After", "2")
			c.AbortWithStatusJSON(503, gin.H{"error": "سرویس شلوغ است؛ کمی بعد تلاش کنید"})
		}
	}
}
