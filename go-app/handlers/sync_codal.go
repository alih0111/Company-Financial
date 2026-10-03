package handlers

import (
	"encoding/json"
	"io"
	"net/http"
	"os/exec"
	"strconv"

	"github.com/gin-gonic/gin"
)

// SyncCodalRequest بدنه‌ی درخواست اجرای sync مبتنی بر discovery کدال.
type SyncCodalRequest struct {
	Mode     string `json:"mode"`      // "all" | "financial" | "monthly"
	DryRun   bool   `json:"dry_run"`   // فقط کشف، بدون تغییر داده
	MaxPages int    `json:"max_pages"` // حداکثر صفحه از هر feed
	Limit    int    `json:"limit"`     // حداکثر گزارش جدید
	Symbol   string `json:"symbol"`    // جمع‌آوری فقط برای این نماد (خالی = feed سراسری)
}

// RunSyncCodal دستور py/sync_codal.py را اجرا می‌کند.
// این endpoint additive است و flow قدیمی run-script را تغییر نمی‌دهد.
// stdout اسکریپت (JSON) به‌صورت پاسخ برگردانده می‌شود و لاگ‌ها به کنسول سرور می‌روند.
func RunSyncCodal(c *gin.Context) {
	if !c.GetBool("isAdmin") {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin only"})
		return
	}

	var req SyncCodalRequest
	_ = c.ShouldBindJSON(&req)

	mode := req.Mode
	if mode != "all" && mode != "financial" && mode != "monthly" {
		mode = "all"
	}

	args := []string{"py/sync_codal.py", "--type", mode}
	if req.DryRun {
		args = append(args, "--dry-run")
	}
	if req.MaxPages > 0 {
		args = append(args, "--max-pages", strconv.Itoa(req.MaxPages))
	}
	if req.Limit > 0 {
		args = append(args, "--limit", strconv.Itoa(req.Limit))
	}
	if req.Symbol != "" {
		args = append(args, "--symbol", req.Symbol)
	}

	cmd := exec.Command("python", args...)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stdout pipe: " + err.Error()})
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stderr pipe: " + err.Error()})
		return
	}

	if err := cmd.Start(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "start failed: " + err.Error()})
		return
	}

	// لاگ‌ها (stderr) به‌صورت زنده به کنسول سرور
	go streamLogs(stderr)

	out, readErr := io.ReadAll(stdout)
	waitErr := cmd.Wait()

	if readErr != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "read stdout: " + readErr.Error()})
		return
	}

	// اگر stdout JSON معتبر باشد همان را برمی‌گردانیم (حتی وقتی بعضی گزارش‌ها
	// fail شده‌اند و exit code غیرصفر است). در غیر این صورت خطا می‌دهیم.
	var parsed map[string]interface{}
	if json.Unmarshal(out, &parsed) == nil {
		c.Data(http.StatusOK, "application/json; charset=utf-8", out)
		return
	}

	msg := "no valid JSON output"
	if waitErr != nil {
		msg = waitErr.Error()
	}
	c.JSON(http.StatusInternalServerError, gin.H{"error": msg, "output": string(out)})
}
