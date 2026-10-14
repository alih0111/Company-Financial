package qvt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func readResearchMap(path string) map[string]any {
	raw, err := os.ReadFile(path)
	if err != nil || len(raw) > 4*1024*1024 {
		return nil
	}
	var data map[string]any
	if json.Unmarshal(raw, &data) != nil {
		return nil
	}
	return data
}

// Publication is bound to the checked bytes, not merely an audit status string.
func qvtResearchSummary() map[string]any {
	root, err := filepath.Abs(filepath.Join("..", "qvt_backtest", "output"))
	if err != nil {
		return nil
	}
	raw, err := os.ReadFile(filepath.Join(root, "roadmap_latest.json"))
	if err != nil || len(raw) > 4*1024*1024 {
		return nil
	}
	var report map[string]any
	if json.Unmarshal(raw, &report) != nil || report["version"] != "qvt-roadmap-research-v1" ||
		report["mode"] != "research_only" || report["real_orders"] != float64(0) || report["promotion_ready"] != false {
		return nil
	}
	run, ok := report["run_path"].(string)
	if !ok {
		return nil
	}
	full, err := filepath.Abs(run)
	if err != nil {
		return nil
	}
	rel, err := filepath.Rel(root, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) || filepath.IsAbs(rel) {
		return nil
	}
	publication := readResearchMap(filepath.Join(full, "publication.json"))
	audit := readResearchMap(filepath.Join(full, "independent_audit.json"))
	checked, err := os.ReadFile(filepath.Join(full, "summary.json"))
	if err != nil || publication["status"] != "passed" || audit["status"] != "passed" {
		return nil
	}
	hash := sha256.Sum256(raw)
	checkedHash := sha256.Sum256(checked)
	if hash != checkedHash || publication["summary_sha256"] != hex.EncodeToString(hash[:]) {
		return nil
	}
	// Do not combine the newly published replay with comparisons calculated
	// from a different baseline while the research pipeline is still running.
	baseline := readResearchMap(filepath.Join(root, "reconstructed_latest.json"))
	if stringField(report, "baseline_run_path") == "" ||
		stringField(report, "baseline_run_path") != stringField(baseline, "run_path") {
		return nil
	}
	return map[string]any{
		"n_comparisons": report["n_comparisons"], "n_variants": report["n_variants"],
		"checked_scenarios": audit["checked_scenarios"], "gaps": report["gaps"],
		"generated_at": report["generated_at"], "promotion_ready": false,
		"promotion_gates": report["promotion_gates"], "uncertainty": report["uncertainty"],
		"chronological": qvtChronologicalSummary(root, report),
		"scope":         "historical_subset_research", "status_label": "بررسی عوامل و محدودیت اجرا انجام شده؛ مدل کامل هنوز تأیید نشده است",
	}
}

func qvtChronologicalSummary(root string, fixed map[string]any) map[string]any {
	raw, err := os.ReadFile(filepath.Join(root, "walkforward_latest.json"))
	if err != nil || len(raw) > 4*1024*1024 {
		return nil
	}
	var report map[string]any
	if json.Unmarshal(raw, &report) != nil || report["version"] != "chronological-selector-research-v1" ||
		report["mode"] != "research_only" || report["real_orders"] != float64(0) || report["promotion_ready"] != false ||
		stringField(report, "baseline_run_path") != stringField(fixed, "baseline_run_path") ||
		stringField(report, "fixed_research_run_path") != stringField(fixed, "run_path") {
		return nil
	}
	run, err := filepath.Abs(stringField(report, "run_path"))
	if err != nil {
		return nil
	}
	rel, err := filepath.Rel(root, run)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) || filepath.IsAbs(rel) {
		return nil
	}
	publication := readResearchMap(filepath.Join(run, "publication.json"))
	audit := readResearchMap(filepath.Join(run, "independent_audit.json"))
	chronology := readResearchMap(filepath.Join(run, "chronology_audit.json"))
	checked, err := os.ReadFile(filepath.Join(run, "summary.json"))
	hash := sha256.Sum256(raw)
	if err != nil || sha256.Sum256(checked) != hash || publication["status"] != "passed" ||
		publication["summary_sha256"] != hex.EncodeToString(hash[:]) || audit["status"] != "passed" || chronology["status"] != "passed" {
		return nil
	}
	return map[string]any{"n_comparisons": report["n_comparisons"], "annual_decisions": chronology["annual_decisions"],
		"status_label": "انتخاب روش با ترتیب زمانی و حساب پیوسته بررسی شد؛ این نتیجه هنوز شاهدِ تاریخچهٔ دیده‌نشده نیست"}
}

func qvtStrategyPreview() map[string]any {
	report := readResearchMap(filepath.Join("..", "qvt_paper", "output", "strategy_latest.json"))
	if report["version"] != "qvt-strategy-preview-v1" || report["mode"] != "simulation" ||
		report["real_orders"] != float64(0) || report["promotion_ready"] != false {
		return nil
	}
	zone, err := time.LoadLocation("Asia/Tehran")
	if err != nil {
		return nil
	}
	cutoff, err := time.Parse(time.RFC3339, stringField(report, "cutoff"))
	fresh := err == nil && !cutoff.After(time.Now()) && report["as_of"] == time.Now().In(zone).Format("2006-01-02") && report["snapshot_fresh"] == true
	if !fresh {
		report["positions"] = []any{}
		report["cash_weight"] = float64(1)
		report["snapshot_fresh"] = false
		report["status_label"] = "برای برنامهٔ امروز داده باید به‌روز شود"
	}
	return report
}

func stringField(data map[string]any, key string) string {
	value, _ := data[key].(string)
	return value
}
