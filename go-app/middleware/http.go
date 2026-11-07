package middleware

import (
	"github.com/gin-gonic/gin"
	"net/http"
	"strconv"
	"sync"
	"time"
)

func SecurityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("X-Content-Type-Options", "nosniff")
		c.Header("X-Frame-Options", "DENY")
		c.Header("Referrer-Policy", "strict-origin-when-cross-origin")
		c.Header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
		c.Header("Cache-Control", "no-store")
		c.Header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
		c.Header("Cross-Origin-Opener-Policy", "same-origin")
		c.Header("Cross-Origin-Resource-Policy", "same-origin")
		c.Header("X-Permitted-Cross-Domain-Policies", "none")
		c.Header("Pragma", "no-cache")
		c.Next()
	}
}

// Bounded per-client fixed window; main explicitly sets trusted proxy addresses.
func RateLimit(limit int, window time.Duration) gin.HandlerFunc {
	return keyedRateLimit(limit, window, func(c *gin.Context) string { return c.ClientIP() })
}

func UserRateLimit(limit int, window time.Duration) gin.HandlerFunc {
	return keyedRateLimit(limit, window, func(c *gin.Context) string { return c.GetString("username") })
}

func keyedRateLimit(limit int, window time.Duration, keyFor func(*gin.Context) string) gin.HandlerFunc {
	type entry struct {
		count int
		reset time.Time
	}
	var mu sync.Mutex
	clients := map[string]entry{}
	return func(c *gin.Context) {
		now := time.Now()
		key := keyFor(c)
		mu.Lock()
		if len(clients) >= 10000 {
			for ip, v := range clients {
				if !now.Before(v.reset) {
					delete(clients, ip)
				}
			}
		}
		v, found := clients[key]
		if !found && len(clients) >= 10000 {
			mu.Unlock()
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "سرویس شلوغ است؛ کمی بعد تلاش کنید"})
			return
		}
		if !now.Before(v.reset) {
			v = entry{reset: now.Add(window)}
		}
		v.count++
		clients[key] = v
		mu.Unlock()
		if v.count > limit {
			c.Header("Retry-After", strconv.Itoa(int(time.Until(v.reset).Seconds())+1))
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "درخواست بیش از حد؛ کمی بعد دوباره تلاش کنید"})
			return
		}
		c.Next()
	}
}
