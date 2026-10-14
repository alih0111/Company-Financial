package qvt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestResearchPublicationRequiresExactCheckedBytes(t *testing.T) {
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	base := t.TempDir()
	app := filepath.Join(base, "go-app")
	run := filepath.Join(base, "qvt_backtest", "output", "roadmap_test")
	if err := os.MkdirAll(app, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(run, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(app); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(old) })
	report := map[string]any{"version": "qvt-roadmap-research-v1", "mode": "research_only", "real_orders": 0, "promotion_ready": false, "run_path": run, "baseline_run_path": "baseline_test"}
	raw, _ := json.Marshal(report)
	write := func(path string, value []byte) {
		t.Helper()
		if err := os.WriteFile(path, value, 0600); err != nil {
			t.Fatal(err)
		}
	}
	latest := filepath.Join(filepath.Dir(run), "roadmap_latest.json")
	baseline := filepath.Join(filepath.Dir(run), "reconstructed_latest.json")
	write(baseline, []byte(`{"run_path":"baseline_test"}`))
	write(latest, raw)
	write(filepath.Join(run, "summary.json"), raw)
	write(filepath.Join(run, "independent_audit.json"), []byte(`{"status":"passed","checked_scenarios":55}`))
	if qvtResearchSummary() != nil {
		t.Fatal("unpublished result admitted")
	}
	hash := sha256.Sum256(raw)
	pub, _ := json.Marshal(map[string]any{"status": "passed", "summary_sha256": hex.EncodeToString(hash[:])})
	write(filepath.Join(run, "publication.json"), pub)
	if qvtResearchSummary() == nil {
		t.Fatal("valid checked result refused")
	}
	write(baseline, []byte(`{"run_path":"newer_baseline"}`))
	if qvtResearchSummary() != nil {
		t.Fatal("comparisons from another baseline admitted")
	}
	write(baseline, []byte(`{"run_path":"baseline_test"}`))
	write(latest, append(raw, ' '))
	if qvtResearchSummary() != nil {
		t.Fatal("unchecked bytes admitted")
	}
}
