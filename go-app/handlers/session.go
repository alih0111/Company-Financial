package handlers

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"net/http"
	"time"
)

func issueBrowserSession(c *gin.Context, username string, isAdmin bool) {
	db, err := config.GetPG()
	if err != nil {
		c.JSON(503, gin.H{"error": "سرویس ورود موقتاً در دسترس نیست"})
		return
	}
	var random [32]byte
	if _, err := rand.Read(random[:]); err != nil {
		c.Status(503)
		return
	}
	secret := hex.EncodeToString(random[:])
	hash := sha256.Sum256([]byte(secret))
	ctx, cancel := pgTimeout()
	defer cancel()
	expires := time.Now().Add(config.SessionLifetime)
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		c.Status(503)
		return
	}
	defer tx.Rollback()
	var userID string
	err = tx.QueryRowContext(ctx, `SELECT id::text FROM auth.users WHERE username=$1 AND is_active=true FOR UPDATE`, username).Scan(&userID)
	if err != nil {
		c.Status(503)
		return
	}
	// Limit retained sessions per user. Never keep an unbounded login history.
	_, err = tx.ExecContext(ctx, `DELETE FROM auth.sessions WHERE user_id=$1 AND (expires_at<=now() OR last_seen_at<now()-interval '30 minutes' OR token_hash IN (SELECT token_hash FROM auth.sessions WHERE user_id=$1 ORDER BY created_at DESC OFFSET 9))`, userID)
	if err != nil {
		c.Status(503)
		return
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO auth.sessions(token_hash,user_id,expires_at) VALUES ($1,$2,$3)`, hash[:], userID, expires)
	if err != nil {
		c.Status(503)
		return
	}
	if err := tx.Commit(); err != nil {
		c.Status(503)
		return
	}
	http.SetCookie(c.Writer, config.SessionCookie(secret, expires))
	c.JSON(200, gin.H{"username": username, "isAdmin": isAdmin})
}

// Protected by authentication and OriginGuard. Clearing a cookie alone would
// leave a stolen credential usable, so revoke the database record first.
func Logout(c *gin.Context) {
	secret, err := c.Cookie(config.SessionCookieName())
	if err == nil && len(secret) == 64 {
		db, err := config.GetPG()
		if err != nil {
			c.Status(503)
			return
		}
		hash := sha256.Sum256([]byte(secret))
		ctx, cancel := pgTimeout()
		defer cancel()
		if _, err := db.ExecContext(ctx, `DELETE FROM auth.sessions WHERE token_hash=$1`, hash[:]); err != nil {
			c.Status(503)
			return
		}
	}
	http.SetCookie(c.Writer, config.SessionCookie("", time.Unix(1, 0)))
	c.JSON(200, gin.H{"message": "خروج انجام شد"})
}
