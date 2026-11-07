package middleware

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"go-app/config"
	"net/http"
	"strings"
	"time"
)

func AuthMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		username, isAdmin := "", false
		cookie, cookieErr := c.Cookie(config.SessionCookieName())
		// Production accepts opaque server-side sessions only. Development can
		// still use legacy Bearer JWTs for the offline fixtures and old tools.
		if cookieErr == nil && len(cookie) == 64 {
			if _, err := hex.DecodeString(cookie); err != nil {
				c.AbortWithStatus(401)
				return
			}
			db, err := config.GetPG()
			if err != nil || db == nil {
				c.AbortWithStatusJSON(503, gin.H{"error": "سرویس حساب‌ها موقتاً در دسترس نیست"})
				return
			}
			ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
			defer cancel()
			hash := sha256.Sum256([]byte(cookie))
			var touch bool
			err = db.QueryRowContext(ctx, `SELECT u.username::text,u.is_admin,s.last_seen_at<now()-interval '5 minutes'
                FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id
                WHERE s.token_hash=$1 AND u.is_active=true AND s.expires_at>now() AND s.last_seen_at>now()-interval '30 minutes'`, hash[:]).Scan(&username, &isAdmin, &touch)
			if err == sql.ErrNoRows {
				c.AbortWithStatusJSON(401, gin.H{"error": "نشست منقضی یا باطل شده است؛ دوباره وارد شوید"})
				return
			}
			if err != nil {
				c.AbortWithStatus(503)
				return
			}
			if touch {
				result, err := db.ExecContext(ctx, `UPDATE auth.sessions SET last_seen_at=now() WHERE token_hash=$1`, hash[:])
				if err != nil {
					c.AbortWithStatus(503)
					return
				}
				if count, _ := result.RowsAffected(); count != 1 {
					c.AbortWithStatus(401)
					return
				}
			}
		} else {
			header := c.GetHeader("Authorization")
			if !config.Production() && cookieErr == nil && strings.Count(cookie, ".") == 2 {
				header = "Bearer " + cookie
			}
			if config.Production() || !strings.HasPrefix(header, "Bearer ") || len(config.JWTSecret()) == 0 {
				c.AbortWithStatusJSON(401, gin.H{"error": "ورود به حساب لازم است"})
				return
			}
			claims := jwt.MapClaims{}
			token, err := jwt.ParseWithClaims(strings.TrimPrefix(header, "Bearer "), claims, func(token *jwt.Token) (interface{}, error) { return config.JWTSecret(), nil }, jwt.WithValidMethods([]string{"HS256"}))
			username, _ = claims["username"].(string)
			if err != nil || !token.Valid || !claims.VerifyExpiresAt(time.Now().Unix(), true) || strings.TrimSpace(username) == "" {
				c.AbortWithStatusJSON(401, gin.H{"error": "نشست نامعتبر است؛ دوباره وارد شوید"})
				return
			}
			isAdmin, _ = claims["isAdmin"].(bool)
		}

		c.Set("username", username)
		c.Set("isAdmin", isAdmin)
		c.Next()
	}
}

func AdminOnly() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !c.GetBool("isAdmin") {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "این عملیات فقط برای مدیر مجاز است"})
			return
		}
		c.Next()
	}
}
