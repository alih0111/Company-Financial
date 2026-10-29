package handlers

import (
	"testing"
	"time"
)

func TestCodalAutoSyncEnabled(t *testing.T) {
	t.Setenv("CODAL_AUTO_SYNC_ENABLED", "")
	if !codalAutoSyncEnabled() {
		t.Fatal("default (unset) must be enabled")
	}
	t.Setenv("CODAL_AUTO_SYNC_ENABLED", "0")
	if codalAutoSyncEnabled() {
		t.Fatal("CODAL_AUTO_SYNC_ENABLED=0 must disable")
	}
	t.Setenv("CODAL_AUTO_SYNC_ENABLED", "1")
	if !codalAutoSyncEnabled() {
		t.Fatal("CODAL_AUTO_SYNC_ENABLED=1 must enable")
	}
}

func TestCodalAutoSyncInterval(t *testing.T) {
	cases := []struct {
		raw  string
		want time.Duration
	}{
		{"", 30 * time.Minute},    // پیش‌فرض
		{"abc", 30 * time.Minute}, // مقدار نامعتبر → پیش‌فرض
		{"0", 30 * time.Minute},   // نامعتبر → پیش‌فرض
		{"2", 5 * time.Minute},    // کف ایمنی
		{"10", 10 * time.Minute},
		{"120", 120 * time.Minute},
	}
	for _, c := range cases {
		t.Setenv("CODAL_AUTO_SYNC_INTERVAL_MINUTES", c.raw)
		if got := codalAutoSyncInterval(); got != c.want {
			t.Errorf("interval(%q) = %s, want %s", c.raw, got, c.want)
		}
	}
}
