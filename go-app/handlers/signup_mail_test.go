package handlers

import (
	"bufio"
	"fmt"
	"gopkg.in/gomail.v2"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestSignupMailRefusesTLSStripping(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv("APP_ENV", "production")
	t.Setenv("SMTP_HOST", "127.0.0.1")
	t.Setenv("SMTP_PORT", strconv.Itoa(listener.Addr().(*net.TCPAddr).Port))
	t.Setenv("SMTP_EMAIL", "test@example.com")
	t.Setenv("SMTP_PASSWORD", "isolated-test-password")
	done := make(chan string, 1)
	go func() {
		connection, err := listener.Accept()
		if err != nil {
			done <- "accept failed"
			return
		}
		defer connection.Close()
		_ = connection.SetDeadline(time.Now().Add(3 * time.Second))
		fmt.Fprint(connection, "220 test SMTP\r\n")
		reader := bufio.NewReader(connection)
		_, _ = reader.ReadString('\n')
		fmt.Fprint(connection, "250 test SMTP without STARTTLS\r\n")
		line, _ := reader.ReadString('\n')
		done <- line
	}()
	err = sendSignupMail(gomail.NewMessage(), "test@example.com", "recipient@example.com")
	if err == nil || !strings.Contains(err.Error(), "STARTTLS") {
		t.Fatal("unencrypted SMTP accepted")
	}
	if next := <-done; strings.HasPrefix(next, "AUTH") || strings.HasPrefix(next, "MAIL") {
		t.Fatal("credentials or email sent without TLS")
	}
}
