package handlers

import (
	"database/sql"
	"fmt"
	"go-app/config"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"golang.org/x/crypto/bcrypt"
	"gopkg.in/gomail.v2"
)

func Login(c *gin.Context) {
	var creds struct {
		Username string `json:"username"` // Can be either username or email
		Password string `json:"password"`
	}
	if err := c.BindJSON(&creds); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
		return
	}
	creds.Username = strings.TrimSpace(creds.Username)
	if creds.Username == "" || len(creds.Username) > 254 || creds.Password == "" || len(creds.Password) > 72 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "نام کاربری و گذرواژه معتبر وارد کنید"})
		return
	}
	if len(config.JWTSecret()) < 32 {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "سرویس ورود پیکربندی نشده است"})
		return
	}
	if !allowLoginAttempt(creds.Username, time.Now()) {
		c.Header("Retry-After", "900")
		c.JSON(429, gin.H{"error": "تلاش‌های ورود زیاد بوده است؛ کمی بعد دوباره تلاش کنید"})
		return
	}

	if config.AuthBackend() == "postgres" {
		loginPostgres(c, creds.Username, creds.Password)
		return
	}

	db := config.GetDB()
	defer db.Close()

	var (
		hashedPassword string
		isAdmin        bool
		actualUsername string
	)

	err := db.QueryRow(`
		SELECT [UserName], [Password], [IsAdmin]
		FROM [codal].[dbo].[Users]
		WHERE [UserName] = @p1 OR [Email] = @p1
	`, creds.Username).Scan(&actualUsername, &hashedPassword, &isAdmin)

	if err == sql.ErrNoRows {
		_ = config.VerifyPassword(dummyLoginHash, creds.Password)
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	} else if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "سرویس حساب‌ها موقتاً در دسترس نیست"})
		return
	}

	if bcrypt.CompareHashAndPassword([]byte(hashedPassword), []byte(creds.Password)) != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	}
	clearLoginAttempts(creds.Username)

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"username": actualUsername,
		"isAdmin":  isAdmin,
		"exp":      time.Now().Add(config.SessionLifetime).Unix(),
	})

	tokenString, err := token.SignedString(config.JWTSecret())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to sign token"})
		return
	}

	// Mark user as online
	_, _ = db.Exec(`UPDATE [codal].[dbo].[Users] SET [IsOnline] = 1, [Token] = @p2 WHERE [UserName] = @p1`,
		actualUsername, tokenString)

	http.SetCookie(c.Writer, config.SessionCookie(tokenString, time.Now().Add(config.SessionLifetime)))
	c.JSON(http.StatusOK, gin.H{"username": actualUsername, "isAdmin": isAdmin})
}

func Register(c *gin.Context) {
	if !config.RegistrationEnabled() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "ثبت‌نام فعلاً بسته است"})
		return
	}
	var input struct {
		Email    string `json:"email"`
		Username string `json:"username"`
		Password string `json:"password"`
		Code     string `json:"code"`
	}

	if err := c.BindJSON(&input); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid input"})
		return
	}

	input.Email = normalizeEmail(input.Email)
	input.Username = strings.TrimSpace(input.Username)
	if !validRegistration(input.Email, input.Username, input.Password) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "ایمیل معتبر، نام کاربری ۳ تا ۶۴ حرفی بدون فاصله و گذرواژه غیررایج با حداقل ۱۵ نویسه و حداکثر ۷۲ بایت لازم است"})
		return
	}
	if !signupCodes.consume(input.Email, input.Code, time.Now()) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "کد تأیید نادرست یا منقضی است؛ کد تازه درخواست کنید"})
		return
	}

	if config.AuthBackend() == "postgres" {
		registerPostgres(c, input.Username, input.Email, input.Password)
		return
	}

	db := config.GetDB()
	defer db.Close()

	// 🔍 Check if the username already exists
	var count int
	err := db.QueryRow("SELECT COUNT(*) FROM [codal].[dbo].[Users] WHERE [UserName] = @p1", input.Username).Scan(&count)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Database error while checking username"})
		return
	}
	if count > 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Username already taken"})
		return
	}

	var count2 int
	err2 := db.QueryRow("SELECT COUNT(*) FROM [codal].[dbo].[Users] WHERE [Email] = @p1", input.Email).Scan(&count2)
	if err2 != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Database error while checking Email"})
		return
	}
	if count2 > 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Email already taken"})
		return
	}

	// 🔐 Hash the password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(input.Password), bcrypt.DefaultCost)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to hash password"})
		return
	}

	// ✅ Insert new user
	_, err = db.Exec(`
		INSERT INTO [codal].[dbo].[Users] ([UserName], [Email], [Password], [IsOnline], [ViewedItems])
		VALUES (@p1, @p2, @p3, 0, '[]')
		`, input.Username, input.Email, string(hashedPassword))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to register user"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Registration successful"})
}

func SendVerificationCode(c *gin.Context) {
	if !config.RegistrationEnabled() || !config.SMTPConfigured() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "ارسال ایمیل ثبت‌نام فعلاً در دسترس نیست"})
		return
	}
	var input struct {
		Email string `json:"email"`
	}

	if err := c.BindJSON(&input); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Valid email is required"})
		return
	}
	input.Email = normalizeEmail(input.Email)
	if input.Email == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "ایمیل معتبر وارد کنید"})
		return
	}
	code, err := signupCodes.issue(input.Email, time.Now())
	if err != nil {
		c.Header("Retry-After", "60")
		c.JSON(http.StatusTooManyRequests, gin.H{"error": "برای ارسال دوبارهٔ کد یک دقیقه صبر کنید"})
		return
	}

	// Send email
	m := gomail.NewMessage()
	sender := os.Getenv("SMTP_FROM")
	if sender == "" {
		sender = os.Getenv("SMTP_EMAIL")
	}
	m.SetHeader("From", sender)
	m.SetHeader("To", input.Email)
	m.SetHeader("Subject", "Your Verification Code")
	m.SetBody("text/plain", fmt.Sprintf("کد تأیید حساب RFA: %s\nاین کد تا ۱۰ دقیقه معتبر است. اگر این درخواست را ثبت نکرده‌اید، پیام را نادیده بگیرید.", code))

	if err := sendSignupMail(m, sender, input.Email); err != nil {
		signupCodes.discard(input.Email)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "ارسال ایمیل ناموفق بود؛ کمی بعد دوباره تلاش کنید"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Verification code sent"})
}
