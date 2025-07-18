package handlers

import (
	"database/sql"
	"fmt"
	"go-app/config"
	"log"
	"math/rand"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v4"
	"github.com/joho/godotenv"
	"golang.org/x/crypto/bcrypt"
	"gopkg.in/gomail.v2"
)

var (
	smtpEmail    string
	smtpPassword string
	jwtSecret    []byte
)

func init() {
	err := godotenv.Load()
	if err != nil {
		log.Fatal("Error loading .env file")
	}

	smtpEmail = os.Getenv("SMTP_EMAIL")
	smtpPassword = os.Getenv("SMTP_PASSWORD")
	jwtSecret = []byte(os.Getenv("JWT_SECRET"))

	if smtpEmail == "" || smtpPassword == "" {
		log.Fatal("SMTP_EMAIL or SMTP_PASSWORD is not set in .env")
	}
}

// var jwtSecret = []byte("your_secret_key")       // Replace with an env var in production
var verificationCodes = make(map[string]string) // email -> code

func Login(c *gin.Context) {
	var creds struct {
		Username string `json:"username"` // Can be either username or email
		Password string `json:"password"`
	}
	if err := c.BindJSON(&creds); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request"})
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
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	} else if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	if bcrypt.CompareHashAndPassword([]byte(hashedPassword), []byte(creds.Password)) != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid credentials"})
		return
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"username": actualUsername,
		"isAdmin":  isAdmin,
		"exp":      time.Now().Add(time.Hour * 72).Unix(),
	})

	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to sign token"})
		return
	}

	// Mark user as online
	_, _ = db.Exec(`UPDATE [codal].[dbo].[Users] SET [IsOnline] = 1, [Token] = @p2 WHERE [UserName] = @p1`,
		actualUsername, tokenString)

	c.JSON(http.StatusOK, gin.H{"token": tokenString})
}

func Register(c *gin.Context) {
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

	expectedCode, ok := verificationCodes[input.Email]
	if !ok || expectedCode != input.Code {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid or expired verification code"})
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
		VALUES (@p1, @p2, @p3, 0, '')
		`, input.Username, input.Email, string(hashedPassword))
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to register user"})
		return
	}

	delete(verificationCodes, input.Email)
	c.JSON(http.StatusOK, gin.H{"message": "Registration successful"})
}

func SendVerificationCode(c *gin.Context) {
	var input struct {
		Email string `json:"email"`
	}

	if err := c.BindJSON(&input); err != nil || input.Email == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Valid email is required"})
		return
	}

	code := fmt.Sprintf("%06d", rand.Intn(1000000))
	verificationCodes[input.Email] = code

	// Send email
	m := gomail.NewMessage()
	m.SetHeader("From", smtpEmail)
	m.SetHeader("To", input.Email)
	m.SetHeader("Subject", "Your Verification Code")
	m.SetBody("text/plain", fmt.Sprintf("Your code is: %s", code))

	d := gomail.NewDialer("smtp.gmail.com", 587, smtpEmail, smtpPassword)

	if err := d.DialAndSend(m); err != nil {
		fmt.Printf("Error sending email: %v\n", err) // Add this
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to send email"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "Verification code sent"})
}
