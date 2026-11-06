package handlers

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

var reportFlowBusy atomic.Bool

// ReportFlow has its own account and files. It never invokes a broker or the
// FactorMix publisher. The Python process also takes an OS-level lock.
func StartReportFlowObserver() {
	go func() {
		for {
			reportFlowTick()
			time.Sleep(time.Minute)
		}
	}()
}

func queueReportFlowReview(source string) {
	root, err := analyticsRepoRoot()
	if err != nil {
		return
	}
	dir := filepath.Join(root, ".runtime", "reportflow")
	if _, err := os.Stat(filepath.Join(dir, "account.json")); err != nil {
		return
	}
	raw, _ := json.Marshal(map[string]string{"source": source, "queued_at_utc": time.Now().UTC().Format(time.RFC3339Nano)})
	_ = writeAtomicFile(filepath.Join(dir, "request.json"), raw, 0o600)
	go reportFlowTick()
}

func reportFlowTick() {
	if os.Getenv("REPORTFLOW_AUTOMATIC_ENABLED") == "0" || !reportFlowBusy.CompareAndSwap(false, true) {
		return
	}
	defer reportFlowBusy.Store(false)
	root, err := analyticsRepoRoot()
	if err != nil {
		return
	}
	dir := filepath.Join(root, ".runtime", "reportflow")
	if _, err := os.Stat(filepath.Join(dir, "account.json")); err != nil {
		return
	}
	log, err := os.OpenFile(filepath.Join(dir, "service.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer log.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, analyticsRefreshPython(root), "-B", "-m", "reportflow.service")
	cmd.Dir = root
	cmd.Stdout, cmd.Stderr = log, log
	if err := cmd.Run(); err != nil {
		raw, _ := json.Marshal(map[string]string{"state": "FAILED", "message": "بررسی خودکار ناموفق بود؛ آخرین حساب ثبت‌شده حفظ شده است.", "error": err.Error()})
		_ = writeAtomicFile(filepath.Join(dir, "worker-error.json"), raw, 0o600)
	} else {
		_ = os.Remove(filepath.Join(dir, "worker-error.json"))
	}
}

func GetReportFlow(c *gin.Context) {
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(500, gin.H{"error": "مسیر حساب مستقل در دسترس نیست."})
		return
	}
	result := gin.H{"running": reportFlowBusy.Load(), "automatic_enabled": os.Getenv("REPORTFLOW_AUTOMATIC_ENABLED") != "0"}
	for _, name := range []string{"status", "portfolio", "account", "worker-error"} {
		raw, err := os.ReadFile(filepath.Join(root, ".runtime", "reportflow", name+".json"))
		if err == nil && json.Valid(raw) {
			result[name] = json.RawMessage(raw)
		}
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(200, result)
}

func ReviewReportFlow(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(500, gin.H{"error": "مسیر حساب مستقل در دسترس نیست."})
		return
	}
	if _, err := os.Stat(filepath.Join(root, ".runtime", "reportflow", "account.json")); err != nil {
		c.JSON(409, gin.H{"error": "حساب مستقل ReportFlow هنوز ایجاد نشده است."})
		return
	}
	queueReportFlowReview("manual")
	c.JSON(202, gin.H{"queued": true})
}
