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
	paperTrialRunsPath    = ".runtime/paper-trial-refresh-runs"
	paperTrialStatusFile  = ".runtime/paper-trial-refresh-status.json"
	paperTrialStaleAfter  = 15 * time.Minute
)

var paperTrialStartBusy atomic.Bool

type paperTrialRefreshStatus struct {
	State            string                              `json:"state"` // Idle | Running | Finished | Failed
	RunID            string                              `json:"run_id,omitempty"`
	Stage            string                              `json:"stage,omitempty"`
	StartedAt        string                              `json:"started_at,omitempty"`
	FinishedAt       string                              `json:"finished_at,omitempty"`
	ExpExitCode      *int                                `json:"exp_exit_code,omitempty"`
	TrialExitCode    *int                                `json:"trial_exit_code,omitempty"`
	Message          string                              `json:"message,omitempty"`
	Error            string                              `json:"error,omitempty"`
	ExpError         string                              `json:"exp_error,omitempty"`
	TrialError       string                              `json:"trial_error,omitempty"`
	Accounts         map[string]json.RawMessage          `json:"accounts,omitempty"`
	LastSuccess      map[string]paperTrialAccountSuccess `json:"last_success,omitempty"`
	LastSuccessScope string                              `json:"last_success_scope,omitempty"`
	RecoveryRequired bool                                `json:"recovery_required,omitempty"`
}

type paperTrialAccountSuccess struct {
	RunID      string `json:"run_id"`
	FinishedAt string `json:"finished_at"`
	Outcome    string `json:"outcome"`
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
	raw = append(raw, '\n')
	if status.RunID != "" {
		if filepath.Base(status.RunID) != status.RunID || !strings.HasPrefix(status.RunID, "run-") {
			return fmt.Errorf("invalid paper run ID")
		}
		runDir := filepath.Join(root, filepath.FromSlash(paperTrialRunsPath), status.RunID)
		if err := os.MkdirAll(runDir, 0o700); err != nil {
			return err
		}
		if err := writePaperTrialStatusAtomic(filepath.Join(runDir, "status.json"), raw); err != nil {
			return err
		}
	}
	return writePaperTrialStatusAtomic(path, raw)
}

func writePaperTrialStatusAtomic(path string, data []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".paper-status-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), path)
}

// paperTrialStatusIsMine keeps a stale goroutine (server killed mid-run, or a
// hung run taken over after the staleness window) from clobbering a newer run's status.
func paperTrialStatusIsMine(root, runID string) bool {
	return loadPaperTrialStatus(root).RunID == runID
}

// A status age cannot establish that a child process stopped. An old or
// malformed Running record needs inspection, not an automatic takeover.
func paperTrialRunningState(status paperTrialRefreshStatus, now time.Time) (running, needsInspection bool) {
	if status.State != "Running" {
		return false, false
	}
	started, err := time.Parse(time.RFC3339, status.StartedAt)
	return true, err != nil || started.After(now) || now.Sub(started) >= paperTrialStaleAfter
}

// paperTrialLogTail keeps the admin-facing error short; the full output is on disk.
func paperTrialLogTail(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if line != "" {
			runes := []rune(line)
			if len(runes) > 1000 {
				line = string(runes[len(runes)-1000:])
			}
			return line
		}
	}
	return ""
}

// The cycle prints one JSON summary with each account's independent outcome.
func paperTrialAccounts(path string) map[string]json.RawMessage {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		var result struct {
			Accounts map[string]json.RawMessage `json:"accounts"`
		}
		if json.Unmarshal([]byte(lines[i]), &result) == nil && result.Accounts != nil {
			return result.Accounts
		}
	}
	return nil
}

func paperTrialOutcomeError(accounts map[string]json.RawMessage) string {
	if accounts == nil {
		return "ACCOUNT_OUTCOMES_NOT_RECORDED"
	}
	for _, method := range []string{"P1", "P3"} {
		var outcome struct {
			Status string `json:"status"`
		}
		if json.Unmarshal(accounts[method], &outcome) != nil || strings.TrimSpace(outcome.Status) == "" {
			return "ACCOUNT_OUTCOME_MISSING:" + method
		}
		if outcome.Status == "ERROR" {
			return "ACCOUNT_ERROR:" + method
		}
	}
	return ""
}

// Only explicit applied results from completed manual runs qualify. Scheduler
// history and prior runs without per-account outcomes remain unknown.
func paperTrialLastSuccess(root string) map[string]paperTrialAccountSuccess {
	result := make(map[string]paperTrialAccountSuccess)
	runs, err := os.ReadDir(filepath.Join(root, filepath.FromSlash(paperTrialRunsPath)))
	if err != nil {
		return result
	}
	for _, entry := range runs {
		if !entry.IsDir() || !strings.HasPrefix(entry.Name(), "run-") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(paperTrialRunsPath), entry.Name(), "status.json"))
		if err != nil {
			continue
		}
		var status paperTrialRefreshStatus
		if json.Unmarshal(raw, &status) != nil || status.RunID != entry.Name() || (status.State != "Finished" && status.State != "Failed") {
			continue
		}
		finished, err := time.Parse(time.RFC3339, status.FinishedAt)
		if err != nil {
			continue
		}
		for _, method := range []string{"P1", "P3"} {
			var outcome struct {
				Status string `json:"status"`
			}
			if json.Unmarshal(status.Accounts[method], &outcome) != nil || (outcome.Status != "MARK_APPLIED" && outcome.Status != "FILL_APPLIED") {
				continue
			}
			prior, exists := result[method]
			priorTime, _ := time.Parse(time.RFC3339, prior.FinishedAt)
			if !exists || finished.After(priorTime) || (finished.Equal(priorTime) && status.RunID > prior.RunID) {
				result[method] = paperTrialAccountSuccess{RunID: status.RunID, FinishedAt: status.FinishedAt, Outcome: outcome.Status}
			}
		}
	}
	return result
}

func paperTrialStatusWithHistory(root string, now time.Time) paperTrialRefreshStatus {
	status := loadPaperTrialStatus(root)
	_, status.RecoveryRequired = paperTrialRunningState(status, now)
	status.LastSuccess = paperTrialLastSuccess(root)
	status.LastSuccessScope = "completed_manual_runs_with_explicit_applied_outcomes_only"
	return status
}

// paperTrialRunScript runs one engine script to completion with the same flags
// as Update-Paper-Portfolio.cmd, writing to the stage's own run log.
func paperTrialRunScript(root, python, script, logPath string, args ...string) int {
	cmd := exec.Command(python, append([]string{"-B", "-X", "utf8",
		filepath.Join(root, filepath.FromSlash(script))}, args...)...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	logFile, logErr := os.OpenFile(logPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if logErr != nil {
		return -1
	}
	defer logFile.Close()
	cmd.Stdout, cmd.Stderr = logFile, logFile
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return exitErr.ExitCode()
		}
		_, _ = fmt.Fprintln(logFile, err)
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
	c.JSON(http.StatusOK, paperTrialStatusWithHistory(root, time.Now()))
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
	if running, needsInspection := paperTrialRunningState(status, time.Now()); running {
		if needsInspection {
			c.JSON(http.StatusConflict, gin.H{"started": false, "already_running": true, "recovery_required": true,
				"error": "وضعیت اجرای قبلی قدیمی یا نامعتبر است؛ پیش از اجرای دوباره، پایان فرایند و گزارش آن باید بررسی شود."})
		} else {
			c.JSON(http.StatusAccepted, gin.H{"started": false, "already_running": true, "message": status.Message})
		}
		return
	}

	runsDir := filepath.Join(root, filepath.FromSlash(paperTrialRunsPath))
	if err := os.MkdirAll(runsDir, 0o700); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "امکان ساخت مسیر گزارش اجرا نیست."})
		return
	}
	runDir, err := os.MkdirTemp(runsDir, "run-")
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "امکان ساخت گزارش مستقل اجرا نیست."})
		return
	}
	runID := filepath.Base(runDir)
	expLog := filepath.Join(runDir, "experimental.log")
	trialLog := filepath.Join(runDir, "trial.log")
	startedAt := time.Now().UTC().Format(time.RFC3339)
	running := paperTrialRefreshStatus{State: "Running", Stage: "exp_update", StartedAt: startedAt, RunID: runID,
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
	logFile, logErr := os.OpenFile(expLog, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if logErr != nil {
		_ = writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Failed", Stage: "start", RunID: runID,
			StartedAt: startedAt, FinishedAt: time.Now().UTC().Format(time.RFC3339), Error: logErr.Error()})
		c.JSON(http.StatusInternalServerError, gin.H{"error": "امکان ساخت گزارش مرحله نیست."})
		return
	}
	cmd.Stdout, cmd.Stderr = logFile, logFile
	if err := cmd.Start(); err != nil {
		if logFile != nil {
			_ = logFile.Close()
		}
		failed := paperTrialRefreshStatus{State: "Failed", Stage: "start", StartedAt: startedAt, RunID: runID,
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
		expError := ""
		if expExit != 0 {
			expError = paperTrialLogTail(expLog)
			if expError == "" {
				expError = fmt.Sprintf("experimental stage failed with exit code %d and no diagnostic output", expExit)
			}
		}
		if !paperTrialStatusIsMine(root, runID) {
			return
		}
		trialRunning := paperTrialRefreshStatus{State: "Running", Stage: "trial_cycle",
			StartedAt: startedAt, RunID: runID, ExpExitCode: &expExit, ExpError: expError,
			Message: fmt.Sprintf("به‌روزرسانی حساب آزمایشی قبلی با کد خروجی %d تمام شد؛ در حال اجرای آزمون ۳۰روزهٔ P1/P3.", expExit)}
		_ = writePaperTrialStatus(root, trialRunning)

		trialExit := paperTrialRunScript(root, python, paperTrialCycleScript, trialLog)
		accounts := paperTrialAccounts(trialLog)
		trialError := ""
		if trialExit != 0 {
			trialError = paperTrialLogTail(trialLog)
			if trialError == "" {
				trialError = fmt.Sprintf("trial stage failed with exit code %d and no diagnostic output or log unavailable", trialExit)
			}
		} else {
			trialError = paperTrialOutcomeError(accounts)
		}
		if !paperTrialStatusIsMine(root, runID) {
			return
		}
		finishedAt := time.Now().UTC().Format(time.RFC3339)
		if expExit == 0 && trialExit == 0 && trialError == "" {
			_ = writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Finished", Stage: "done",
				StartedAt: startedAt, RunID: runID, FinishedAt: finishedAt, ExpExitCode: &expExit, TrialExitCode: &trialExit, Accounts: accounts,
				Message: "اجرای دستی پایان یافت؛ نتیجه و تاریخ دادهٔ هر حساب را بررسی کنید."})
			return
		}
		_ = writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Failed", Stage: "done",
			StartedAt: startedAt, RunID: runID, FinishedAt: finishedAt, ExpExitCode: &expExit, TrialExitCode: &trialExit, Accounts: accounts,
			ExpError: expError, TrialError: trialError,
			Message: "اجرای دستی سبد کاغذی با خطا تمام شد؛ اگر اجرای زمان‌بندی‌شده در جریان بوده، کمی بعد دوباره تلاش کنید.",
			Error:   strings.TrimSpace(strings.Join([]string{expError, trialError}, "\n"))})
	}()

	c.JSON(http.StatusAccepted, gin.H{"started": true, "started_at": startedAt, "run_id": runID,
		"message": "تلاش دوبارهٔ اجرای سبد کاغذی شروع شد؛ وضعیت روی همین صفحه به‌روز می‌شود."})
}
