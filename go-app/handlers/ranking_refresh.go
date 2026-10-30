package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

const manualRankingRefreshScript = "ranking_research/future_eval_v12_30/manual_ranking_refresh.py"

var paperCycleStartBusy atomic.Bool

type paperCycleTaskStatus struct {
	State              string         `json:"state"`
	Stage              string         `json:"stage,omitempty"`
	LastRunTime        string         `json:"last_run_time"`
	LastResult         int            `json:"last_task_result"`
	LatestRunID        string         `json:"latest_run_id"`
	CycleStatus        string         `json:"cycle_status"`
	RankingStageStatus string         `json:"ranking_stage_status"`
	FreshFinancial     bool           `json:"fresh_financial_reports"`
	FreshMonthlySales  bool           `json:"fresh_monthly_sales"`
	EvaluationDate     string         `json:"evaluation_date,omitempty"`
	ScoredCount        map[string]int `json:"scored_count,omitempty"`
	Message            string         `json:"message,omitempty"`
	Error              string         `json:"error,omitempty"`
}

func rankingRefreshStatusPath(root string) string {
	return filepath.Join(root, ".runtime", "ranking-refresh-status.json")
}

func loadPaperCycleStatus(root string) (paperCycleTaskStatus, error) {
	var status paperCycleTaskStatus
	if raw, err := os.ReadFile(rankingRefreshStatusPath(root)); err == nil {
		if err := json.Unmarshal(raw, &status); err != nil {
			return status, err
		}
		if status.State != "" {
			return status, nil
		}
	}

	path := filepath.Join(root, "client", "public", "research", "v12-37", "latest-ranking.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return status, err
	}
	var artifact struct {
		ArtifactID     string         `json:"artifact_id"`
		EvaluationDate string         `json:"evaluation_date"`
		ComputedAtUTC  string         `json:"computed_at_utc"`
		ScoredCount    map[string]int `json:"scored_count"`
	}
	if err := json.Unmarshal(raw, &artifact); err != nil {
		return status, err
	}
	status = paperCycleTaskStatus{State: "Ready", LatestRunID: artifact.ArtifactID,
		LastRunTime: artifact.ComputedAtUTC, LastResult: 0, CycleStatus: "READY",
		RankingStageStatus: "ready", EvaluationDate: artifact.EvaluationDate,
		ScoredCount: artifact.ScoredCount, Message: "رتبه‌بندی آماده است."}
	return status, nil
}

func writeRankingRefreshStatus(root string, status paperCycleTaskStatus) error {
	path := rankingRefreshStatusPath(root)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(raw, '\n'), 0o644)
}

func GetRankingRefreshStatus(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	status, err := loadPaperCycleStatus(root)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "وضعیت به‌روزرسانی رتبه‌بندی خوانده نشد: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, status)
}

func StartRankingRefresh(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	if !paperCycleStartBusy.CompareAndSwap(false, true) {
		c.JSON(http.StatusConflict, gin.H{"error": "درخواست شروع در حال ثبت است؛ کمی صبر کنید.", "busy": true})
		return
	}
	defer paperCycleStartBusy.Store(false)

	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	status, err := loadPaperCycleStatus(root)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "وضعیت فعلی رتبه‌بندی در دسترس نیست."})
		return
	}
	if status.State == "Running" {
		c.JSON(http.StatusAccepted, gin.H{"started": false, "already_running": true,
			"baseline_run_id": status.LatestRunID, "baseline_last_run_time": status.LastRunTime,
			"message": status.Message})
		return
	}

	baselineRunID, baselineLastRunTime := status.LatestRunID, status.LastRunTime
	runID := fmt.Sprintf("v12_37_manual_%s", time.Now().UTC().Format("20060102T150405.000000000Z"))
	running := paperCycleTaskStatus{State: "Running", Stage: "starting", LatestRunID: runID,
		LastRunTime: baselineLastRunTime, LastResult: 0, CycleStatus: "LOCAL_CANONICAL_REFRESH_RUNNING",
		RankingStageStatus: "starting", Message: "در حال شروع بازسازی محلی؛ کدال دوباره پیمایش نمی‌شود."}
	if err := writeRankingRefreshStatus(root, running); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	python := analyticsRefreshPython(root)
	cmd := exec.Command(python, filepath.Join(root, filepath.FromSlash(manualRankingRefreshScript)), "--run-id", runID)
	cmd.Dir = root
	logPath := filepath.Join(root, ".runtime", "ranking-refresh.log")
	logFile, logErr := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if logErr == nil {
		cmd.Stdout, cmd.Stderr = logFile, logFile
	}
	if err := cmd.Start(); err != nil {
		if logFile != nil {
			_ = logFile.Close()
		}
		running.State, running.Stage, running.RankingStageStatus = "Failed", "failed", "failed"
		running.Error, running.Message, running.LastResult = err.Error(), "شروع پردازش رتبه‌بندی ناموفق بود.", 1
		_ = writeRankingRefreshStatus(root, running)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "شروع بازسازی رتبه‌بندی ناموفق بود: " + err.Error()})
		return
	}
	go func() {
		_ = cmd.Wait()
		if logFile != nil {
			_ = logFile.Close()
		}
	}()

	c.JSON(http.StatusAccepted, gin.H{"started": true, "baseline_run_id": baselineRunID,
		"baseline_last_run_time": baselineLastRunTime,
		"message":                "بازسازی محلی شروع شد؛ از داده‌های جمع‌آوری‌شده استفاده می‌شود و کل کدال دوباره بررسی نمی‌شود."})
}
