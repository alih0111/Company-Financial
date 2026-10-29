package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

// جمع‌آوری خودکار کدال — همان «جمع‌آوری سریع» صفحه، بدون نیاز به کلیک.
//
// یک ورکر پس‌زمینه هر CODAL_AUTO_SYNC_INTERVAL_MINUTES دقیقه (پیش‌فرض ۳۰)
// py/sync_codal.py را اجرا می‌کند. خود اسکریپت incremental است (watermark +
// dedup با TracingNo در پستگرس)، پس فقط گزارش‌های جدیدِ نمادهای شناسایی‌شده
// دریافت می‌شوند و اجرای مکرر بار اضافی روی کدال نمی‌گذارد.
//
// قفل single-flight بین اجرای خودکار و دکمه‌ی دستی مشترک است؛ هر دو هرگز
// همزمان اجرا نمی‌شوند (context مرورگر و نوشتن canonical نباید موازی شوند).

const (
	codalAutoStatePath = ".runtime/codal-auto-sync.json"
	codalAutoLockPath  = ".runtime/codal-auto-sync.lock"
	codalAutoLogPath   = ".runtime/codal-auto-sync.log"
	codalAutoTimeout   = 15 * time.Minute
	codalAutoLockStale = 20 * time.Minute
)

// codalSyncBusy بین مسیر خودکار (این فایل) و مسیر دستی (sync_codal.go) مشترک است.
var codalSyncBusy atomic.Bool

func codalAutoSyncEnabled() bool {
	return os.Getenv("CODAL_AUTO_SYNC_ENABLED") != "0"
}

func codalAutoSyncInterval() time.Duration {
	raw := os.Getenv("CODAL_AUTO_SYNC_INTERVAL_MINUTES")
	minutes, err := strconv.Atoi(raw)
	if err != nil || minutes <= 0 {
		return 30 * time.Minute
	}
	if minutes < 5 {
		// کف ایمنی: کدال در فشار مکرر پاسخ throttle می‌دهد.
		minutes = 5
	}
	return time.Duration(minutes) * time.Minute
}

// codalSyncPython پایتون venv پروژه را ترجیح می‌دهد (playwright + psycopg آنجاست).
func codalSyncPython() string {
	if cwd, err := os.Getwd(); err == nil {
		venv := filepath.Join(cwd, "..", ".venv", "scripts", "python.exe")
		if _, err := os.Stat(venv); err == nil {
			return venv
		}
	}
	return "python"
}

// StartCodalAutoSync ورکر چرخشی را در گوروتین بالا می‌آورد. با
// CODAL_AUTO_SYNC_ENABLED=0 غیرفعال می‌شود.
func StartCodalAutoSync() {
	if !codalAutoSyncEnabled() {
		log.Println("⏸️ codal auto sync disabled (CODAL_AUTO_SYNC_ENABLED=0)")
		return
	}
	interval := codalAutoSyncInterval()
	log.Printf("🔁 codal auto sync enabled: every %s (first pass in 2m)", interval)
	go func() {
		time.Sleep(2 * time.Minute) // بگذار بالا آمدن سرور کامل شود
		for {
			codalAutoSyncTick()
			time.Sleep(codalAutoSyncInterval())
		}
	}()
}

func codalAutoSyncTick() {
	// اگر اجرای دستی در جریان است، این دور بی‌سروصدا رد می‌شود.
	if !codalSyncBusy.CompareAndSwap(false, true) {
		return
	}
	defer codalSyncBusy.Store(false)

	_ = os.MkdirAll(".runtime", 0o700)
	// قفل بین-پروسه‌ای: اگر پروسه‌ای کشته شود قفل را رها نمی‌کند؛ بعد از
	// بیشینه‌ی زمان اجرا (۱۵د) + حاشیه، قفل کهنه شمرده می‌شود.
	if st, err := os.Stat(codalAutoLockPath); err == nil && time.Since(st.ModTime()) > codalAutoLockStale {
		_ = os.Remove(codalAutoLockPath)
	}
	lock, err := os.OpenFile(codalAutoLockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return // پروسه‌ی دیگری از همین اپ در حال اجراست
	}
	_ = lock.Close()
	defer os.Remove(codalAutoLockPath)

	now := time.Now()
	state := map[string]any{
		"running":          true,
		"last_attempt_at":  now.Format(time.RFC3339),
		"interval_minutes": int(codalAutoSyncInterval().Minutes()),
	}
	writeCodalAutoState(state)

	workDir, err := os.Getwd()
	script := filepath.Join(workDir, "py", "sync_codal.py")
	if err != nil {
		state["status"], state["message"] = "failed", "cannot resolve working dir"
		state["running"] = false
		writeCodalAutoState(state)
		return
	}
	if _, err := os.Stat(script); err != nil {
		state["status"], state["message"] = "failed", "py/sync_codal.py not found"
		state["running"] = false
		writeCodalAutoState(state)
		log.Println("❌ codal auto sync:", state["message"])
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), codalAutoTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, codalSyncPython(), script, "--type", "all")
	cmd.Dir = workDir
	cmd.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8")

	// قرارداد sync_codal.py: stdout فقط JSON نهایی؛ stderr لاگ‌ها.
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	runErr := cmd.Run()
	_ = os.WriteFile(codalAutoLogPath, append(stderr.Bytes(), stdout.Bytes()...), 0o600)

	state["running"] = false
	state["finished_at"] = time.Now().Format(time.RFC3339)
	if ctx.Err() == context.DeadlineExceeded {
		state["status"], state["message"] = "timeout", "اجرا از ۱۵ دقیقه بیشتر طول کشید؛ دور بعد ادامه می‌دهد"
		log.Println("⏱️ codal auto sync timeout after", codalAutoTimeout)
		writeCodalAutoState(state)
		return
	}

	var summary struct {
		Success bool   `json:"success"`
		Error   string `json:"error"`
		Total   struct {
			Scanned     int `json:"scanned"`
			Already     int `json:"already"`
			New         int `json:"new"`
			Completed   int `json:"completed"`
			Failed      int `json:"failed"`
			Quarantined int `json:"quarantined"`
			Errors      int `json:"errors"`
		} `json:"total"`
	}
	if json.Unmarshal(stdout.Bytes(), &summary) != nil {
		state["status"], state["message"] = "failed", "خروجی JSON معتبر برگردانده نشد"
		if runErr != nil {
			state["error"] = runErr.Error()
		}
		log.Println("❌ codal auto sync: no valid JSON; see", codalAutoLogPath)
		writeCodalAutoState(state)
		return
	}
	if summary.Error != "" {
		// مثلا کدال در دسترس نیست؛ دور بعد دوباره امتحان می‌شود.
		state["error"] = summary.Error
	}

	state["last_summary"] = map[string]any{
		"scanned":     summary.Total.Scanned,
		"already":     summary.Total.Already,
		"new":         summary.Total.New,
		"completed":   summary.Total.Completed,
		"failed":      summary.Total.Failed,
		"quarantined": summary.Total.Quarantined,
		"errors":      summary.Total.Errors,
	}
	switch {
	case summary.Success:
		state["status"] = "completed"
		state["last_success_at"] = state["finished_at"]
		state["message"] = "آخرین جمع‌آوری خودکار انجام شد"
		log.Printf("✅ codal auto sync: scanned=%d new=%d completed=%d failed=%d quarantined=%d",
			summary.Total.Scanned, summary.Total.New, summary.Total.Completed,
			summary.Total.Failed, summary.Total.Quarantined)
	case summary.Error != "" && summary.Total.Scanned == 0:
		// مثلا کدال در دسترس نیست؛ watermark جلو نرفته و دور بعد دوباره
		// همان بازه را اسکن می‌کند، پس چیزی از دست نمی‌رود.
		state["status"] = "failed"
		state["message"] = "کدال در دسترس نبود؛ دور بعد دوباره تلاش می‌شود"
		log.Printf("⚠️ codal auto sync failed: %s", summary.Error)
	default:
		state["status"] = "completed_with_errors"
		state["message"] = "جمع‌آوری انجام شد اما بخشی ناموفق بود"
		log.Printf("⚠️ codal auto sync finished with errors: new=%d failed=%d errors=%d",
			summary.Total.New, summary.Total.Failed, summary.Total.Errors)
	}
	state["next_run_at"] = time.Now().Add(codalAutoSyncInterval()).Format(time.RFC3339)
	writeCodalAutoState(state)
}

func writeCodalAutoState(state map[string]any) {
	state["enabled"] = codalAutoSyncEnabled()
	raw, err := json.Marshal(state)
	if err != nil {
		return
	}
	_ = os.MkdirAll(".runtime", 0o700)
	_ = os.WriteFile(codalAutoStatePath+".tmp", raw, 0o600)
	_ = os.Rename(codalAutoStatePath+".tmp", codalAutoStatePath)
}

// GetCodalSyncStatus وضعیت جمع‌آوری خودکار را برمی‌گرداند (GET /api/sync-codal/status).
func GetCodalSyncStatus(c *gin.Context) {
	if !c.GetBool("isAdmin") {
		c.JSON(403, gin.H{"error": "admin only"})
		return
	}
	state := map[string]any{
		"enabled":          codalAutoSyncEnabled(),
		"interval_minutes": int(codalAutoSyncInterval().Minutes()),
		"running":          codalSyncBusy.Load(),
		"schedule_label":   "جمع‌آوری خودکار جدیدترین گزارش‌های کدال برای نمادهای شما",
	}
	if raw, err := os.ReadFile(codalAutoStatePath); err == nil {
		persisted := map[string]any{}
		if json.Unmarshal(raw, &persisted) == nil {
			for k, v := range persisted {
				if _, live := state[k]; !live {
					state[k] = v
				}
			}
		}
	}
	state["running"] = codalSyncBusy.Load()
	if _, has := state["next_run_at"]; !has {
		if last, ok := state["last_attempt_at"].(string); ok && !state["running"].(bool) {
			if t, err := time.Parse(time.RFC3339, last); err == nil {
				state["next_run_at"] = t.Add(codalAutoSyncInterval()).Format(time.RFC3339)
			}
		}
	}
	c.JSON(200, state)
}
