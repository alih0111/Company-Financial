package config

import (
	"database/sql"
	"log"

	_ "github.com/denisenkom/go-mssqldb"
)

var ConnectionString = "server=wsn-mis-068;user id=sa;password=dbco@2023hamkaran;database=codal"

func GetDB() *sql.DB {
	db, err := sql.Open("sqlserver", ConnectionString)
	if err != nil {
		log.Fatal("Failed to connect to DB:", err)
	}
	return db
}
