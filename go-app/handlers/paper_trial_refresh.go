package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

// Manual paper-portfolio retry, the web equivalent of Update-Paper-Portfolio.cmd:
// the locked engine's own scripts, run sequentially. This only re-runs the same
// update the scheduled tasks run, so a transient TSETMC error no longer has to
// wait for the next 13:30/22:30 slot; fills stay bound to official close
// evidence and nothing here can backdate a decision.
const (
	paperTrialExpScript   = "ranking_research/future_eval_v12_30/experimental_paper.py"
	paperTrialCycleScript = "ranking_research/future_eval_v12_30/paper_month_trial.py"
	paperTrialLogPath     = ".runtime/paper-trial-refresh.log"
	paperTrialStatusFile  = ".runtime/paper-trial-refresh-status.json"
	paperTrialStaleAfter  = 15 * time.Minute
)

var paperTrialStartBusy atomic.Bool

type paperTrialRefreshStatus struct {
	State         string `json:"state"` // Idle | Running | Finished | Failed
	Stage         string `json:"stage,omitempty"`
	StartedAt     string `json:"started_at,omitempty"`
	FinishedAt    string `json:"finished_at,omitempty"`
	ExpExitCode   *int   `json:"exp_exit_code,omitempty"`
	TrialExitCode *int   `json:"trial_exit_code,omitempty"`
	Message       string `json:"message,omitempty"`
	Error         string `json:"error,omitempty"`
}

func paperTrialStatusPath(root string) string {
	return filepath.Join(root, filepath.FromSlash(paperTrialStatusFile))
}

func loadPaperTrialStatus(root string) paperTrialRefreshStatus {
	var status paperTrialRefreshStatus
	if raw, err := os.ReadFile(paperTrialStatusPath(root)); err == nil {
		if json.Unmarshal(raw, &status) == nil && status.State != "" {
			return status
		}
	}
	return paperTrialRefreshStatus{State: "Idle",
		Message: "اجرای دستی سبد کاغذی در جریان نیست."}
}

func writePaperTrialStatus(root string, status paperTrialRefreshStatus) error {
	path := paperTrialStatusPath(root)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(raw, '\n'), 0o644)
}

// paperTrialStatusIsMine keeps a stale goroutine (server killed mid-run, or a
// hung run taken over after the staleness window) from clobbering a newer run's status.
func paperTrialStatusIsMine(root, startedAt string) bool {
	return loadPaperTrialStatus(root).StartedAt == startedAt
}

// paperTrialLogTail keeps the admin-facing error short; the full output is on disk.
func paperTrialLogTail(root string) string {
	raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(paperTrialLogPath)))
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if line != "" {
			if len(line) > 300 {
				line = line[len(line)-300:]
			}
			return line
		}
	}
	return ""
}

// paperTrialRunScript runs one engine script to completion with the same flags
// as Update-Paper-Portfolio.cmd, appending output to the shared retry log.
func paperTrialRunScript(root, python, script string, args ...string) int {
	cmd := exec.Command(python, append([]string{"-B", "-X", "utf8",
		filepath.Join(root, filepath.FromSlash(script))}, args...)...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	logFile, logErr := os.OpenFile(filepath.Join(root, filepath.FromSlash(paperTrialLogPath)),
		os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if logErr == nil {
		defer logFile.Close()
		cmd.Stdout, cmd.Stderr = logFile, logFile
	}
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return exitErr.ExitCode()
		}
		return -1
	}
	return 0
}

func GetPaperTrialRefreshStatus(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, loadPaperTrialStatus(root))
}

func StartPaperTrialRefresh(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	if !paperTrialStartBusy.CompareAndSwap(false, true) {
		c.JSON(http.StatusConflict, gin.H{"error": "درخواست شروع در حال ثبت است؛ کمی صبر کنید.", "busy": true})
		return
	}
	defer paperTrialStartBusy.Store(false)

	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	status := loadPaperTrialStatus(root)
	if status.State == "Running" {
		if started, parseErr := time.Parse(time.RFC3339, status.StartedAt); parseErr == nil && time.Since(started) < paperTrialStaleAfter {
			c.JSON(http.StatusAccepted, gin.H{"started": false, "already_running": true, "message": status.Message})
			return
		}
		// A Running status older than the window means the previous run died
		// mid-way (server restart, hung python); take over with a fresh run.
	}

	startedAt := time.Now().UTC().Format(time.RFC3339)
	running := paperTrialRefreshStatus{State: "Running", Stage: "exp_update", StartedAt: startedAt,
		Message: "در حال اجرای دستی سبد کاغذی؛ ابتدا به‌روزرسانی حساب آزمایشی قبلی، سپس آزمون ۳۰روزهٔ P1/P3."}
	if err := writePaperTrialStatus(root, running); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	python := analyticsRefreshPython(root)
	cmd := exec.Command(python, "-B", "-X", "utf8",
		filepath.Join(root, filepath.FromSlash(paperTrialExpScript)), "update", "--publish")
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	logFile, logErr := os.OpenFile(filepath.Join(root, filepath.FromSlash(paperTrialLogPath)),
		os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if logErr == nil {
		cmd.Stdout, cmd.Stderr = logFile, logFile
	}
	if err := cmd.Start(); err != nil {
		if logFile != nil {
			_ = logFile.Close()
		}
		failed := paperTrialRefreshStatus{State: "Failed", Stage: "start", StartedAt: startedAt,
			FinishedAt: time.Now().UTC().Format(time.RFC3339),
			Error:      err.Error(), Message: "شروع اجرای دستی سبد کاغذی ناموفق بود."}
		_ = writePaperTrialStatus(root, failed)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "شروع اجرای دستی سبد کاغذی ناموفق بود: " + err.Error()})
		return
	}

	go func() {
		expExit := 0
		if err := cmd.Wait(); err != nil {
			var exitErr *exec.ExitError
			if errors.As(err, &exitErr) {
				expExit = exitErr.ExitCode()
			} else {
				expExit = -1
			}
		}
		if logFile != nil {
			_ = logFile.Close()
		}
		if !paperTrialStatusIsMine(root, startedAt) {
			return
		}
		trialRunning := paperTrialRefreshStatus{State: "Running", Stage: "trial_cycle",
			StartedAt: startedAt, ExpExitCode: &expExit,
			Message: fmt.Sprintf("به‌روزرسانی حساب آزمایشی قبلی با کد خروجی %d تمام شد؛ در حال اجرای آزمون ۳۰روزهٔ P1/P3.", expExit)}
		_ = writePaperTrialStatus(root, trialRunning)

		trialExit := paperTrialRunScript(root, python, paperTrialCycleScript)
		if !paperTrialStatusIsMine(root, startedAt) {
			return
		}
		finishedAt := time.Now().UTC().Format(time.RFC3339)
		if expExit == 0 && trialExit == 0 {
			_ = writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Finished", Stage: "done",
				StartedAt: startedAt, FinishedAt: finishedAt, ExpExitCode: &expExit, TrialExitCode: &trialExit,
				Message: "اجرای دستی سبد کاغذی کامل شد؛ داده‌های صفحه تازه شد."})
			return
		}
		_ = writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Failed", Stage: "done",
			StartedAt: startedAt, FinishedAt: finishedAt, ExpExitCode: &expExit, TrialExitCode: &trialExit,
			Message: "اجرای دستی سبد کاغذی با خطا تمام شد؛ اگر اجرای زمان‌بندی‌شده در جریان بوده، کمی بعد دوباره تلاش کنید.",
			Error:   paperTrialLogTail(root)})
	}()

	c.JSON(http.StatusAccepted, gin.H{"started": true, "started_at": startedAt,
		"message": "تلاش دوبارهٔ اجرای سبد کاغذی شروع شد؛ وضعیت روی همین صفحه به‌روز می‌شود."})
}
