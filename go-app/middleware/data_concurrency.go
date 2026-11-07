package middleware

import (
	"github.com/gin-gonic/gin"
	"sync"
	"time"
)

func keyedConcurrency(perUser, global int) gin.HandlerFunc {
	var mu sync.Mutex
	active := map[string]int{}
	total := 0
	return func(c *gin.Context) {
		if c.GetBool("isAdmin") {
			c.Next()
			return
		}
		key := c.GetString("username")
		mu.Lock()
		if total >= global || active[key] >= perUser {
			mu.Unlock()
			c.Header("Retry-After", "3")
			c.AbortWithStatusJSON(429, gin.H{"error": "چند درخواست هم‌زمان در حال انجام است؛ کمی بعد تلاش کنید.", "code": "data_concurrency_exceeded"})
			return
		}
		total++
		active[key]++
		mu.Unlock()
		defer func() {
			mu.Lock()
			total--
			active[key]--
			if active[key] == 0 {
				delete(active, key)
			}
			mu.Unlock()
		}()
		c.Next()
	}
}

func DataRateLimit() gin.HandlerFunc {
	limited := UserRateLimit(30, time.Minute)
	return func(c *gin.Context) {
		if c.GetBool("isAdmin") {
			c.Next()
			return
		}
		limited(c)
	}
}
