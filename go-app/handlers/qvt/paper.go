package qvt

import (
	"encoding/json"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
)

// Shared model experiment, unrelated to a user's real holdings. Only the local
// forward journal can write it; this endpoint never generates orders or targets.
func GetQvtV2Paper(c *gin.Context) {
	path := os.Getenv("QVT_PAPER_SUMMARY_FILE")
	if path == "" {
		path = filepath.Join("..", "qvt_paper", "output", "latest.json")
	}
	c.Header("Cache-Control", "no-store")
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		c.JSON(200, gin.H{"status": "not_started", "status_label": "آزمایش هنوز شروع نشده است", "positions": []any{}, "real_orders": 0})
		return
	}
	if err != nil || len(raw) > 1024*1024 {
		c.JSON(503, gin.H{"error": "خلاصهٔ آزمایش در دسترس نیست"})
		return
	}
	var summary map[string]any
	if json.Unmarshal(raw, &summary) != nil || summary["version"] != "qvt-paper-forward-v1" ||
		summary["mode"] != "reference_only" || summary["real_orders"] != float64(0) {
		c.JSON(503, gin.H{"error": "خلاصهٔ آزمایش با قرارداد این نسخه سازگار نیست"})
		return
	}
	summary["observer"] = paperObserverStatus()
	summary["historical"] = qvtHistoricalSummary()
	summary["research"] = qvtResearchSummary()
	summary["strategy"] = qvtStrategyPreview()
	c.JSON(200, summary)
}

func qvtHistoricalSummary() map[string]any {
	if result := qvtReconstructedSummary(); result != nil {
		return result
	}
	path := filepath.Join("..", "qvt_backtest", "output", "latest.json")
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) > 1024*1024 {
		return nil
	}
	var report map[string]any
	if json.Unmarshal(raw, &report) != nil || report["version"] != "qvt-timing-history-v1" || report["exact_live_model"] != false {
		return nil
	}
	perf, ok := report["performance"].(map[string]any)
	if !ok {
		return nil
	}
	return map[string]any{
		"scope": "timing_only", "score_ceiling": report["score_ceiling"], "start": report["as_of_start"], "end": report["as_of_end"],
		"n_dates": report["n_dates"], "n_symbols": report["n_symbols"], "full_qvt_status": report["full_qvt_status"],
		"top10": perf["TIMING_TOP10_0.005"], "benchmark": perf["MATCHED_EQUAL_WEIGHT_0.005"],
	}
}

func qvtReconstructedSummary() map[string]any {
	path := filepath.Join("..", "qvt_backtest", "output", "reconstructed_latest.json")
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) > 1024*1024 {
		return nil
	}
	var report map[string]any
	if json.Unmarshal(raw, &report) != nil || report["version"] != "qvt-reconstructed-history-v1" || report["exact_live_model"] != false {
		return nil
	}
	run, ok := report["run_path"].(string)
	if !ok {
		return nil
	}
	auditRaw, err := os.ReadFile(filepath.Join(run, "audit.json"))
	var audit map[string]any
	if err != nil || len(auditRaw) > 1024*1024 || json.Unmarshal(auditRaw, &audit) != nil || audit["status"] != "passed" {
		return nil
	}
	perf, ok := report["performance"].(map[string]any)
	if !ok {
		return nil
	}
	cadences := []map[string]any{}
	for _, label := range []string{"1m", "6m"} {
		top, tok := perf["QVT_TOP10_"+label+"_0.005"].(map[string]any)
		benchmark, bok := perf["MATCHED_EQUAL_WEIGHT_"+label+"_0.005"].(map[string]any)
		if !tok || !bok {
			return nil
		}
		cadences = append(cadences, map[string]any{"id": label, "top10": top, "benchmark": benchmark})
	}
	return map[string]any{
		"scope": "reconstructed_subset", "score_ceiling": report["score_ceiling"],
		"start":   cadences[0]["top10"].(map[string]any)["execution_start"],
		"end":     cadences[0]["top10"].(map[string]any)["execution_end"],
		"n_dates": report["n_dates"], "n_symbols": report["n_symbols"], "full_qvt_status": report["full_qvt_status"],
		"top10": cadences[0]["top10"], "benchmark": cadences[0]["benchmark"], "cadences": cadences,
		"drawdown_frequency": "daily", "min_complete": report["min_complete"], "max_complete": report["max_complete"],
	}
}
