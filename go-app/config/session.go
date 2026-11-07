package config

import (
	"net/http"
	"time"
)

const SessionLifetime = 12 * time.Hour
const SessionIdleTimeout = 30 * time.Minute

func SessionCookieName() string {
	if Production() {
		return "__Host-rfa_session"
	}
	return "rfa_session"
}

func SessionCookie(value string, expires time.Time) *http.Cookie {
	age := int(time.Until(expires).Seconds())
	if value == "" {
		age = -1
	}
	return &http.Cookie{Name: SessionCookieName(), Value: value, Path: "/", HttpOnly: true, Secure: Production(), SameSite: http.SameSiteStrictMode, MaxAge: age, Expires: expires}
}
