package handlers

import (
	"context"
	"database/sql"
	"net/http"
	"strings"
	"time"

	"go-app/config"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"golang.org/x/crypto/bcrypt"
)

func pgTimeout() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 5*time.Second)
}

// PostgreSQL-backed auth (canonical auth.users). Password hashes are bcrypt and
// are copied verbatim from the legacy store, so existing credentials keep
// working. Hashes are never logged.

func issueJWT(c *gin.Context, username string, isAdmin bool) {
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"username": username,
		"isAdmin":  isAdmin,
		"exp":      time.Now().Add(time.Hour * 72).Unix(),
	})
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to sign token"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"token": tokenString})
}

func loginPostgres(c *gin.Context, username, password string) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres auth unavailable"})
		return
	}
	ctx, cancel := pgTimeout()
	defer cancel()

	var (
		actualUsername string
		hashedPassword string
		isAdmin        bool
	)
	err = db.QueryRowContext(ctx, `
		SELECT username::text, password_hash, is_admin
		FROM auth.users
		WHERE (username = $1 OR email = $1) AND is_active = true
	`, username).Scan(&actualUsername, &hashedPassword, &isAdmin)
	if err == sql.ErrNoRows {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "auth query error"})
		return
	}
	if bcrypt.CompareHashAndPassword([]byte(hashedPassword), []byte(password)) != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	}
	_, _ = db.ExecContext(ctx, `UPDATE auth.users SET last_login_at = now(), updated_at = now() WHERE username = $1`, actualUsername)
	issueJWT(c, actualUsername, isAdmin)
}

func registerPostgres(c *gin.Context, username, email, password string) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres auth unavailable"})
		return
	}
	ctx, cancel := pgTimeout()
	defer cancel()

	hashed, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to hash password"})
		return
	}
	_, err = db.ExecContext(ctx, `
		INSERT INTO auth.users (id, username, email, password_hash, is_admin, is_active)
		VALUES (gen_random_uuid(), $1, $2, $3, false, true)
	`, strings.TrimSpace(username), strings.TrimSpace(email), string(hashed))
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			c.JSON(http.StatusBadRequest, gin.H{"error": "Username or email already taken"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to register user"})
		return
	}
	delete(verificationCodes, email)
	c.JSON(http.StatusOK, gin.H{"message": "Registration successful"})
}
