package config

import (
	"database/sql"
	"fmt"

	_ "github.com/denisenkom/go-mssqldb"
)

var (
	server   = "wsn-mis-068"
	port     = 1433
	user     = "sa"
	password = "dbco@2023hamkaran"
	database = "codal"
)

func GetDBConnection() (*sql.DB, error) {
	connString := fmt.Sprintf("server=%s;user id=%s;password=%s;port=%d;database=%s",
		server, user, password, port, database)
	return sql.Open("sqlserver", connString)
}
