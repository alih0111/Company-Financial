package middleware

import (
	"bytes"
	"context"
	"errors"
	"go-app/config"
	"go-app/dataaccess"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

const maximumDataResponse = 2 << 20

// Keep a response private until its entire delivery budget has been committed.
// In particular, concurrent requests cannot all pass a preflight balance check
// and then deliver their data without paying for it.
type dataWriter struct {
	gin.ResponseWriter
	body     bytes.Buffer
	status   int
	overflow bool
}

func (w *dataWriter) WriteHeader(status int) {
	if !w.Written() {
		w.status = status
	}
}
func (w *dataWriter) WriteHeaderNow() {
	if w.status == 0 {
		w.status = 200
	}
}
func (w *dataWriter) Status() int {
	if w.status == 0 {
		return 200
	}
	return w.status
}
func (w *dataWriter) Size() int {
	if !w.Written() {
		return -1
	}
	return w.body.Len()
}
func (w *dataWriter) Written() bool { return w.body.Len() > 0 || w.overflow }
func (w *dataWriter) Flush()        { w.WriteHeaderNow() }
func (w *dataWriter) Write(body []byte) (int, error) {
	w.WriteHeaderNow()
	if w.body.Len()+len(body) > maximumDataResponse {
		w.overflow = true
		return len(body), nil
	}
	return w.body.Write(body)
}
func (w *dataWriter) WriteString(body string) (int, error) { return w.Write([]byte(body)) }

func budgetHeaders(c *gin.Context, status dataaccess.Status) {
	c.Header("Cache-Control", "no-store")
	c.Header("X-Data-Requests-Remaining", strconv.FormatInt(max(0, status.Limits.Requests-status.Used.Requests), 10))
	c.Header("X-Data-Symbols-Remaining", strconv.FormatInt(max(0, status.Limits.Symbols-status.Used.Symbols), 10))
	c.Header("X-Data-Reset", status.ResetsAt.Format(time.RFC3339))
}
func budgetFailure(c *gin.Context, status dataaccess.Status, err error) {
	c.Header("Content-Length", "")
	c.Writer.Header().Del("Content-Length")
	var denied *dataaccess.Denied
	if errors.As(err, &denied) {
		budgetHeaders(c, status)
		if denied.Reason == "disabled" {
			c.AbortWithStatusJSON(403, gin.H{"error": "دسترسی دادهٔ این حساب غیرفعال است؛ با مدیر تماس بگیرید.", "code": "data_access_disabled"})
			return
		}
		c.Header("Retry-After", strconv.Itoa(max(1, int(time.Until(denied.Reset).Seconds()))))
		c.AbortWithStatusJSON(429, gin.H{"error": "سهمیهٔ دریافت دادهٔ امروز به پایان رسیده است؛ پس از زمان اعلام‌شده دوباره تلاش کنید.", "code": "data_quota_exceeded", "reason": denied.Reason, "resets_at": denied.Reset})
	} else {
		c.AbortWithStatusJSON(503, gin.H{"error": "بررسی مجوز دریافت داده موقتاً ممکن نیست.", "code": "data_access_unavailable"})
	}
}

// JSONCost counts delivered array elements and identities, including nested
// results. Raw bytes are also charged so a large object cannot evade row limits.
func JSONCost(body []byte) (dataaccess.Cost, error) { return dataaccess.JSONCost(body) }

func DataAccess() gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.GetBool("isAdmin") {
			c.Next()
			return
		}
		// Query selectors are single values; reject duplicate/wildcard/batch
		// selectors before fetching data. Free-text search has its own limit.

		required := map[string]bool{"/api/SalesData": true, "/api/SalesData2": true, "/api/CompanyScores": true, "/api/StockPriceScore": true, "/api/price-history": true, "/api/financial-statements": true}
		if required[c.FullPath()] && strings.TrimSpace(c.Query("companyName")) == "" || c.FullPath() == "/api/detail" && strings.TrimSpace(c.Query("companyName")) == "" && strings.TrimSpace(c.Query("companyID")) == "" {
			c.AbortWithStatusJSON(400, gin.H{"error": "انتخاب دقیق یک شرکت لازم است.", "code": "data_selector_required"})
			return
		}
		targets := []string{}
		for _, key := range []string{"companyName", "companyID", "company_id", "symbol", "ticker"} {
			values := c.Request.URL.Query()[key]
			if len(values) > 1 {
				c.AbortWithStatusJSON(400, gin.H{"error": "هر درخواست فقط یک نماد را می‌پذیرد."})
				return
			}
			if len(values) == 1 {
				value := strings.TrimSpace(values[0])
				if value == "" || len(value) > 200 || strings.ContainsAny(value, "%*\x00\r\n") {
					c.AbortWithStatusJSON(400, gin.H{"error": "شناسهٔ نماد معتبر نیست."})
					return
				}
				targets = append(targets, value)
			}
		}
		db, err := config.GetPG()
		if err != nil {
			budgetFailure(c, dataaccess.Status{}, err)
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
		status, err := dataaccess.Reserve(ctx, db, c.GetString("username"), c.ClientIP(), dataaccess.Cost{Requests: 1, Targets: targets})
		cancel()
		if err != nil {
			budgetFailure(c, status, err)
			return
		}
		budgetHeaders(c, status)
		// Streaming output is budgeted conservatively in advance; tool results
		// are separately charged before entering the model context.
		if c.FullPath() == "/api/chat/stream" {
			ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
			status, err = dataaccess.Reserve(ctx, db, c.GetString("username"), c.ClientIP(), dataaccess.Cost{Records: 50, Bytes: 64 << 10})
			cancel()
			if err != nil {
				budgetFailure(c, status, err)
				return
			}
			budgetHeaders(c, status)
			c.Next()
			return
		}
		original := c.Writer
		buffer := &dataWriter{ResponseWriter: original}
		c.Writer = buffer
		defer func() { c.Writer = original }()
		c.Next()
		c.Writer = original
		original.Header().Del("Content-Length")
		if buffer.overflow {
			c.AbortWithStatusJSON(413, gin.H{"error": "این خروجی برای دریافت عادی بیش از حد بزرگ است؛ بازه یا تعداد نتایج را کاهش دهید.", "code": "data_response_too_large"})
			return
		}
		if buffer.Status() >= 200 && buffer.Status() < 300 && buffer.body.Len() > 0 {
			cost, parseErr := JSONCost(buffer.body.Bytes())
			if c.FullPath() == "/api/CompanyNames" || c.FullPath() == "/api/companies" {
				cost.Targets = nil
				cost.Records = 0
			}
			if parseErr != nil {
				c.AbortWithStatusJSON(503, gin.H{"error": "خروجی داده قابل ارائه نیست."})
				return
			}
			ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
			status, err = dataaccess.Reserve(ctx, db, c.GetString("username"), c.ClientIP(), cost)
			cancel()
			if err != nil {
				budgetFailure(c, status, err)
				return
			}
			budgetHeaders(c, status)
		}
		original.WriteHeader(buffer.Status())
		_, _ = original.Write(buffer.body.Bytes())
	}
}

// Per-account concurrency guard; active entries are removed on completion.
// This bounds parallel harvesting without an ever-growing identity map.
func DataConcurrency() gin.HandlerFunc {
	return keyedConcurrency(2, 32)
}
