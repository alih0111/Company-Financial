package config

import (
	"database/sql"
	"log"
	"os"

	"github.com/joho/godotenv"
	_ "github.com/microsoft/go-mssqldb"
)

var ConnectionString string

func init() {
	if err := godotenv.Load(); err != nil {
		// .env is optional: in production the process environment is authoritative.
		log.Println("note: no .env file loaded:", err)
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
