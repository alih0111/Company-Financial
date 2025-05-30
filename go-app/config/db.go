package config

import (
	"database/sql"
	"log"
	"os"

	_ "github.com/denisenkom/go-mssqldb"
	"github.com/joho/godotenv"
)

var ConnectionString string

func init() {
	err := godotenv.Load()
	if err != nil {
		log.Fatal("Error loading .env file")
	}

	server := os.Getenv("DB_SERVER")
	user := os.Getenv("DB_USER")
	password := os.Getenv("DB_PASSWORD")
	database := os.Getenv("DB_NAME")

	ConnectionString = "server=" + server + ";user id=" + user + ";password=" + password + ";database=" + database
}

func GetDB() *sql.DB {
	db, err := sql.Open("sqlserver", ConnectionString)
	if err != nil {
		log.Fatal("Failed to connect to DB:", err)
	}
	return db
}
