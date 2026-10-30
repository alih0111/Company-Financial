package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// Manual analytics refresh.
//
// The score table reads a materialised run (analytics.company_scores), never a live
// computation, so new Codal reports and new monthly activities only reach the screen
// after a recompute. The hourly Windows task that used to do this was removed on
// purpose: recomputation is now an explicit admin action from the screen page, and
// nothing recomputes (or even checks) on a timer.
//
// POST /api/admin/analytics/refresh  -> orchestrate_refresh.py --mode RUN_IF_STALE
//
// RUN_IF_STALE (not FORCE_RUN): if no input moved since the served run the answer is
// NOT_STALE and no duplicate run is appended. Every successful call that does recompute
// appends a NEW serving run; prior runs stay untouched.

const (
	analyticsRefreshScript  = "canonical_postgres_v1_2_1/analytics_canonical_v1/orchestrate_refresh.py"
	analyticsRefreshTimeout = 8 * time.Minute
	analyticsRefreshLogPath = ".runtime/analytics-refresh.log"
	analyticsRefreshOutPath = ".runtime/analytics-refresh-summary.json"
)

var analyticsRefreshBusy atomic.Bool

// orchestrateResult mirrors the subset of orchestrate_refresh.py's JSON summary that
// the endpoint reports. Unknown fields are ignored on purpose.
type orchestrateResult struct {
	Action     string `json:"action"`
	Recomputed bool   `json:"recomputed"`
	Staleness  struct {
		Stale   bool     `json:"stale"`
		Reasons []string `json:"reasons"`
	} `json:"staleness"`
	LatestServingRun struct {
		ID        string `json:"id"`
		RunSeq    int64  `json:"run_seq"`
		AsOfDate  string `json:"as_of_date"`
		Completed string `json:"completed_at"`
	} `json:"latest_serving_run"`
	NewRun *struct {
		StoredRunID string `json:"stored_run_id"`
		Completed   bool   `json:"completed"`
		Population  int    `json:"population"`
		RunSeq      int64  `json:"run_seq"`
		CompletedAt string `json:"completed_at"`
	} `json:"new_run"`
	BlockedReason string `json:"blocked_reason"`
	RecomputeAsOf string `json:"recompute_as_of"`
}

type analyticsRefreshResponse struct {
	Action       string   `json:"action"`
	Recomputed   bool     `json:"recomputed"`
	RunID        string   `json:"run_id,omitempty"`
	RunSeq       int64    `json:"run_seq,omitempty"`
	AsOf         string   `json:"as_of,omitempty"`
	ComputedAt   string   `json:"computed_at,omitempty"`
	Population   int      `json:"population,omitempty"`
	Stale        bool     `json:"stale"`
	StaleReasons []string `json:"stale_reasons,omitempty"`
	BlockedReason string  `json:"blocked_reason,omitempty"`
	DurationMS   int64    `json:"duration_ms"`
	Message      string   `json:"message"`
}

func analyticsRepoRoot() (string, error) {
	roots := make([]string, 0, 6)
	if cwd, err := os.Getwd(); err == nil {
		roots = append(roots, cwd, filepath.Join(cwd, ".."), filepath.Join(cwd, "..", ".."), filepath.Join(cwd, "..", "..", ".."))
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		roots = append(roots, dir, filepath.Join(dir, ".."), filepath.Join(dir, "..", ".."), filepath.Join(dir, "..", "..", ".."))
	}
	for _, root := range roots {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(analyticsRefreshScript))); err == nil {
			abs, err := filepath.Abs(root)
			if err != nil {
				return root, nil
			}
			return abs, nil
		}
	}
	return "", fmt.Errorf("اسکریپت به‌روزرسانی امتیازها (orchestrate_refresh.py) پیدا نشد")
}

func analyticsRefreshPython(root string) string {
	for _, candidate := range []string{
		filepath.Join(root, ".venv", "Scripts", "python.exe"),
		filepath.Join(root, ".venv", "scripts", "python.exe"),
		filepath.Join(root, ".venv", "bin", "python"),
	} {
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}
	if exe := strings.TrimSpace(os.Getenv("CDF_PYTHON")); exe != "" {
		return exe
	}
	return "python"
}

// analyticsRunInfo reads the appended run's recency/date straight from canonical PG so
// the button can report "اجرای #۵۰ · ۱۵:۰۸" instead of a bare success.
func analyticsRunInfo(ctx context.Context, runID string) (seq int64, asOf, computedAt string) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		return 0, "", ""
	}
	var s *int64
	var d, c *string
	if err := db.QueryRowContext(ctx,
		`SELECT run_seq, as_of_date::text, completed_at::text
		   FROM analytics.score_runs WHERE id = $1`, runID).Scan(&s, &d, &c); err != nil {
		return 0, "", ""
	}
	if s != nil {
		seq = *s
	}
	if d != nil {
		asOf = *d
	}
	if c != nil {
		computedAt = *c
	}
	return seq, asOf, computedAt
}

// RefreshAnalyticsScores recomputes the screen scores on an explicit admin request.
func RefreshAnalyticsScores(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	if !analyticsRefreshBusy.CompareAndSwap(false, true) {
		c.JSON(http.StatusConflict, gin.H{"error": "یک به‌روزرسانی امتیاز در حال اجراست", "busy": true})
		return
	}
	defer analyticsRefreshBusy.Store(false)

	started := time.Now()
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), analyticsRefreshTimeout)
	defer cancel()

	outPath := filepath.Join(root, filepath.FromSlash(analyticsRefreshOutPath))
	_ = os.Remove(outPath)
	_ = os.MkdirAll(filepath.Dir(outPath), 0o700)

	cmd := exec.CommandContext(ctx, analyticsRefreshPython(root),
		filepath.Join(root, filepath.FromSlash(analyticsRefreshScript)),
		"--mode", "RUN_IF_STALE",
		"--json-out", outPath,
	)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1")
	output, runErr := cmd.CombinedOutput()
	_ = os.WriteFile(filepath.Join(root, filepath.FromSlash(analyticsRefreshLogPath)), output, 0o600)

	if ctx.Err() == context.DeadlineExceeded {
		c.JSON(http.StatusGatewayTimeout, gin.H{
			"error": "به‌روزرسانی امتیازها از حد زمان (۸ دقیقه) گذشت؛ نتیجهٔ قبلی حفظ شد. لاگ سرور را ببینید.",
		})
		return
	}

	raw, readErr := os.ReadFile(outPath)
	if readErr != nil {
		msg := "به‌روزرسانی امتیازها اجرا نشد."
		if runErr != nil {
			msg = "به‌روزرسانی امتیازها ناموفق بود: " + analyticsTail(output)
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": msg})
		return
	}
	var res orchestrateResult
	if err := json.Unmarshal(raw, &res); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "خروجی به‌روزرسانی قابل خواندن نبود"})
		return
	}

	reply := analyticsRefreshResponse{
		Action:       res.Action,
		Recomputed:   res.Recomputed,
		Stale:        res.Staleness.Stale,
		StaleReasons: res.Staleness.Reasons,
		BlockedReason: res.BlockedReason,
		RunID:        res.LatestServingRun.ID,
		RunSeq:       res.LatestServingRun.RunSeq,
		AsOf:         res.LatestServingRun.AsOfDate,
		ComputedAt:   res.LatestServingRun.Completed,
	}
	if res.NewRun != nil && res.NewRun.StoredRunID != "" {
		reply.RunID = res.NewRun.StoredRunID
		reply.Population = res.NewRun.Population
		reply.RunSeq = res.NewRun.RunSeq
		reply.ComputedAt = res.NewRun.CompletedAt
		if res.RecomputeAsOf != "" {
			reply.AsOf = res.RecomputeAsOf
		}
		// Fallback for an orchestrator build that predates the run_seq field.
		if reply.RunSeq == 0 || reply.ComputedAt == "" {
			if seq, asOf, computedAt := analyticsRunInfo(c.Request.Context(), res.NewRun.StoredRunID); seq > 0 {
				reply.RunSeq, reply.AsOf, reply.ComputedAt = seq, asOf, computedAt
			}
		}
	}
	if reply.Population == 0 && res.NewRun != nil {
		reply.Population = res.NewRun.Population
	}
	reply.DurationMS = time.Since(started).Milliseconds()

	switch res.Action {
	case "RECOMPUTED":
		reply.Message = "امتیازها از دادهٔ فعلی بازمحاسبه شد."
	case "NOT_STALE":
		reply.Message = "دادهٔ تازه‌ای که امتیاز را عوض کند نیامده است؛ امتیاز فعلی به‌روز است."
	case "BLOCKED_DEGRADED_INGESTION":
		reply.Message = "به‌روزرسانی انجام نشد: یکی از دامنه‌های ورودی سالم نیست."
	case "RECOMPUTE_INCOMPLETE":
		reply.Message = "محاسبه کامل نشد؛ امتیاز قبلی حفظ شد."
		reply.Recomputed = false
	default:
		reply.Message = "وضعیت نامشخص از اجرای به‌روزرسانی"
	}

	status := http.StatusOK
	if res.Action == "BLOCKED_DEGRADED_INGESTION" || res.Action == "RECOMPUTE_INCOMPLETE" || (runErr != nil && res.Action == "") {
		status = http.StatusServiceUnavailable
	}
	c.JSON(status, reply)
}

// analyticsTail keeps the admin-facing error short; the full output is on disk.
func analyticsTail(output []byte) string {
	text := strings.TrimSpace(string(output))
	if text == "" {
		return "بدون خروجی"
	}
	lines := strings.Split(text, "\n")
	last := strings.TrimSpace(lines[len(lines)-1])
	if len(last) > 300 {
		last = last[len(last)-300:]
	}
	return last
}
