package handlers

import (
	"context"
	"database/sql"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"go-app/dataaccess"
	"strconv"
	"time"
)

// Identities are needed by the portfolio selector. This directory deliberately
// has no scores, prices, factors, report history or research payloads.
func GetCompanyDirectory(c *gin.Context) {
	db, err := config.GetPG()
	if err != nil {
		c.Status(503)
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `SELECT s.id::text,co.display_name,COALESCE(s.codal_symbol,'') FROM core.securities s JOIN core.companies co ON co.id=s.company_id WHERE s.is_active AND co.is_active AND s.is_primary ORDER BY co.display_name,s.id LIMIT 5000`)
	if err != nil {
		c.Status(503)
		return
	}
	defer rows.Close()
	result := []gin.H{}
	for rows.Next() {
		var id, name, symbol string
		if rows.Scan(&id, &name, &symbol) != nil {
			c.Status(503)
			return
		}
		result = append(result, gin.H{"company_id": id, "company_name": name, "symbol": symbol})
	}
	if rows.Err() != nil {
		c.Status(503)
		return
	}
	c.JSON(200, result)
}

func GetDataAccess(c *gin.Context) {
	username := c.GetString("username")
	if target := c.Param("username"); target != "" {
		username = target
	}
	db, err := config.GetPG()
	if err != nil {
		c.Status(503)
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	status, err := dataaccess.ReadStatus(ctx, db, username)
	if err == sql.ErrNoRows {
		c.Status(404)
		return
	}
	if err != nil {
		c.Status(503)
		return
	}
	c.JSON(200, status)
}

func SetDataAccess(c *gin.Context) {
	var body struct {
		Enabled *bool             `json:"enabled"`
		Limits  config.DataLimits `json:"limits"`
	}
	if c.ShouldBindJSON(&body) != nil || body.Enabled == nil || !body.Limits.Valid() {
		c.JSON(400, gin.H{"error": "وضعیت و محدودیت‌های معتبر حساب لازم است."})
		return
	}
	db, err := config.GetPG()
	if err != nil {
		c.Status(503)
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	result, err := db.ExecContext(ctx, `INSERT INTO auth.data_policies(user_id,enabled,requests_limit,records_limit,bytes_limit,symbols_limit)
 SELECT id,$2,$3,$4,$5,$6 FROM auth.users WHERE username=$1 AND is_admin=false
 ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,requests_limit=excluded.requests_limit,records_limit=excluded.records_limit,bytes_limit=excluded.bytes_limit,symbols_limit=excluded.symbols_limit,updated_at=now()`, c.Param("username"), *body.Enabled, body.Limits.Requests, body.Limits.Records, body.Limits.Bytes, body.Limits.Symbols)
	if err != nil {
		c.Status(503)
		return
	}
	n, _ := result.RowsAffected()
	if n == 0 {
		c.JSON(404, gin.H{"error": "حساب عادی پیدا نشد."})
		return
	}
	GetDataAccess(c)
}

func ListDataAccess(c *gin.Context) {
	db, err := config.GetPG()
	if err != nil {
		c.Status(503)
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `SELECT u.username::text,d.requests,d.records,d.bytes,d.symbols,d.denied,d.last_denial,COALESCE(p.enabled,true)
 FROM auth.data_usage d JOIN auth.users u ON u.id=d.user_id LEFT JOIN auth.data_policies p ON p.user_id=u.id
 WHERE d.day=(now() AT TIME ZONE 'Asia/Tehran')::date AND NOT u.is_admin
 ORDER BY d.denied DESC,d.requests DESC,u.username LIMIT 20`)
	if err != nil {
		c.Status(503)
		return
	}
	defer rows.Close()
	items := []gin.H{}
	for rows.Next() {
		var username, last string
		var requests, records, bytes, symbols, denied int64
		var enabled bool
		if rows.Scan(&username, &requests, &records, &bytes, &symbols, &denied, &last, &enabled) != nil {
			c.Status(503)
			return
		}
		items = append(items, gin.H{"username": username, "requests": requests, "records": records, "bytes": bytes, "symbols": symbols, "denied": denied, "last_denial": last, "enabled": enabled})
	}
	if rows.Err() != nil {
		c.Status(503)
		return
	}
	c.JSON(200, items)
}

func dataPage(c *gin.Context, total int) (int, int, bool) {
	page, size := 1, 20
	for key, out := range map[string]*int{"page": &page, "page_size": &size} {
		values := c.Request.URL.Query()[key]
		if len(values) > 1 {
			c.JSON(400, gin.H{"error": "پارامتر صفحه تکراری است."})
			return 0, 0, false
		}
		if len(values) == 1 {
			n, err := strconv.Atoi(values[0])
			if err != nil || n < 1 || n > 100000 {
				c.JSON(400, gin.H{"error": "شماره یا اندازهٔ صفحه معتبر نیست."})
				return 0, 0, false
			}
			*out = n
		}
	}
	if size > 20 {
		c.JSON(400, gin.H{"error": "حداکثر اندازهٔ صفحه ۲۰ ردیف است."})
		return 0, 0, false
	}
	c.Header("X-Page", strconv.Itoa(page))
	c.Header("X-Page-Size", strconv.Itoa(size))
	c.Header("X-Total-Count", strconv.Itoa(total))
	start := min(total, (page-1)*size)
	return start, min(total, start+size), true
}
