package qvt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestCashReviewBoundToPublication(t *testing.T) {
	root := t.TempDir()
	run := filepath.Join(root, "run")
	os.Mkdir(run, 0700)
	write := func(path string, value any) {
		b, e := json.Marshal(value)
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(path, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	raw := []byte(`{"version":"cash-backed-review-v1","mode":"development_review","promotion_ready":false,"real_orders":0,"ranked":[]}`)
	os.WriteFile(filepath.Join(run, "ranking.json"), raw, 0600)
	hash := sha256.Sum256(raw)
	digest := hex.EncodeToString(hash[:])
	write(filepath.Join(run, "publication.json"), map[string]any{"status": "passed", "real_orders": 0, "bundle_sha256": digest})
	write(filepath.Join(root, "owner_current_latest.json"), map[string]any{"run_path": run, "bundle_sha256": digest})
	if _, e := readCashReview(root); e != nil {
		t.Fatal(e)
	}
	os.WriteFile(filepath.Join(run, "ranking.json"), append(raw, ' '), 0600)
	if _, e := readCashReview(root); e == nil {
		t.Fatal("changed bytes accepted")
	}
	write(filepath.Join(root, "owner_current_latest.json"), map[string]any{"run_path": filepath.Dir(root), "bundle_sha256": digest})
	if _, e := readCashReview(root); e == nil {
		t.Fatal("outside root accepted")
	}
}
