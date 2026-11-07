package handlers

import (
	"crypto/tls"
	"fmt"
	"go-app/config"
	"gopkg.in/gomail.v2"
	"net"
	"net/smtp"
	"os"
	"strconv"
	"time"
)

// Explicit deadlines and mandatory TLS in production. Never disable certificate
// verification or fall back to cleartext after STARTTLS failure.
func sendSignupMail(message *gomail.Message, from, to string) error {
	host, port := config.SMTPHost(), config.SMTPPort()
	address := net.JoinHostPort(host, strconv.Itoa(port))
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	tlsConfig := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}
	var connection net.Conn
	var err error
	if port == 465 {
		connection, err = tls.DialWithDialer(dialer, "tcp", address, tlsConfig)
	} else {
		connection, err = dialer.Dial("tcp", address)
	}
	if err != nil {
		return err
	}
	defer connection.Close()
	if err := connection.SetDeadline(time.Now().Add(20 * time.Second)); err != nil {
		return err
	}
	client, err := smtp.NewClient(connection, host)
	if err != nil {
		return err
	}
	defer client.Close()
	if port != 465 {
		if ok, _ := client.Extension("STARTTLS"); ok {
			if err := client.StartTLS(tlsConfig); err != nil {
				return err
			}
		} else if config.Production() {
			return fmt.Errorf("SMTP server does not support required STARTTLS")
		}
	}
	if err := client.Auth(smtp.PlainAuth("", os.Getenv("SMTP_EMAIL"), os.Getenv("SMTP_PASSWORD"), host)); err != nil {
		return err
	}
	if err := client.Mail(from); err != nil {
		return err
	}
	if err := client.Rcpt(to); err != nil {
		return err
	}
	writer, err := client.Data()
	if err != nil {
		return err
	}
	if _, err := message.WriteTo(writer); err != nil {
		_ = writer.Close()
		return err
	}
	if err := writer.Close(); err != nil {
		return err
	}
	return client.Quit()
}
