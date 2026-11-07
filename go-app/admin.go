package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"go-app/config"
	"io"
	"net/mail"
	"os"
	"strings"
	"time"
	"unicode"
)

// Administrative accounts are created only from the server CLI. A public
// registration can never choose its own role. Passwords come from stdin.
func createAdmin(args []string, input io.Reader) error {
	flags := flag.NewFlagSet("admin", flag.ContinueOnError)
	username := flags.String("username", "", "new administrator username")
	email := flags.String("email", "", "administrator email")
	if err := flags.Parse(args); err != nil {
		return err
	}
	*username = strings.TrimSpace(*username)
	*email = strings.ToLower(strings.TrimSpace(*email))
	a, err := mail.ParseAddress(*email)
	if err != nil || a.Address != *email || len(*email) > 254 {
		return fmt.Errorf("valid --email is required")
	}
	if len([]rune(*username)) < 3 || len([]rune(*username)) > 64 {
		return fmt.Errorf("--username must contain 3 to 64 characters")
	}
	for _, char := range *username {
		if !unicode.IsLetter(char) && !unicode.IsDigit(char) && char != '.' && char != '_' && char != '-' {
			return fmt.Errorf("username may contain letters, digits, ., _ and -")
		}
	}
	reader := bufio.NewReader(io.LimitReader(input, 128))
	password, err := reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return fmt.Errorf("could not read password from stdin")
	}
	password = strings.TrimSuffix(strings.TrimSuffix(password, "\n"), "\r")
	if !config.ValidNewPassword(password) {
		return fmt.Errorf("admin password must be uncommon, with at least 15 characters and at most 72 bytes")
	}
	hash, err := config.HashPassword(password)
	if err != nil {
		return err
	}
	db, err := config.GetPG()
	if err != nil {
		return fmt.Errorf("administrator database unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err = db.ExecContext(ctx, `INSERT INTO auth.users (username,email,password_hash,is_admin,is_active) VALUES ($1,$2,$3,true,true)`, *username, *email, hash)
	if err != nil {
		return fmt.Errorf("could not create administrator; username/email may already exist (no existing account was changed)")
	}
	fmt.Fprintln(os.Stdout, "Administrator created. No existing account was changed.")
	return nil
}
