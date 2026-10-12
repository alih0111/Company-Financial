package qvt

// DB-free tests for the opt-in manifest reader (manifest.go): happy path,
// hash tamper, wrong manifest hash, missing bundle, conflicting chain, and
// the no-hidden-fallback rule when QVT_MANIFEST_DIR is set but broken.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func mkManifestFixtures(t *testing.T) (legacyDir, pubDir string, qf, vf, tf string) {
	t.Helper()
	root := t.TempDir()
	legacyDir = filepath.Join(root, "legacy")
	pubDir = filepath.Join(root, "published")
	if err := os.MkdirAll(legacyDir, 0o755); err != nil {
		t.Fatal(err)
	}
	// legacy direct files (valid) — proves manifest mode never silently
	// falls back to them.
	for name, doc := range map[string]map[string]any{
		"v2_q_observed_report.json": {"as_of": "2026-10-08 23:59:00+00:00",
			"summary": map[string]any{"n_pilot_eligible": 98}},
		"v2_value_pilot.json": {"as_of": "2026-10-08",
			"coverage_summary": map[string]any{"n_v_pilot_eligible": 98}},
		"v2_t_pilot.json": {"as_of": "2026-10-08"},
	} {
		raw, _ := json.Marshal(doc)
		if err := os.WriteFile(filepath.Join(legacyDir, name), raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	// published bundle: run dir + manifest + LATEST
	runID := "pub-2026-10-08-qtest-vtest-ttest"
	bundle := filepath.Join(pubDir, runID)
	if err := os.MkdirAll(bundle, 0o755); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"v2_q_observed_report.json": `{"as_of":"2026-10-08 23:59:00+00:00","summary":{"n_pilot_eligible":98}}`,
		"v2_value_pilot.json":       `{"as_of":"2026-10-08","coverage_summary":{"n_v_pilot_eligible":98}}`,
		"v2_t_pilot.json":           `{"as_of":"2026-10-08"}`,
	}
	hashes := map[string]string{}
	for name, content := range files {
		if err := os.WriteFile(filepath.Join(bundle, name), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256([]byte(content))
		hashes[name] = hex.EncodeToString(sum[:])
	}
	man := map[string]any{
		"manifest_version": 1,
		"run_id":           runID,
		"published_at":     "2026-10-09T06:00:00+00:00",
		"artifact_files": map[string]any{
			"q": map[string]any{"file": "v2_q_observed_report.json", "sha256": hashes["v2_q_observed_report.json"], "size_bytes": len(files["v2_q_observed_report.json"])},
			"v": map[string]any{"file": "v2_value_pilot.json", "sha256": hashes["v2_value_pilot.json"], "size_bytes": len(files["v2_value_pilot.json"])},
			"t": map[string]any{"file": "v2_t_pilot.json", "sha256": hashes["v2_t_pilot.json"], "size_bytes": len(files["v2_t_pilot.json"])},
		},
		"chain_validation": map[string]any{"status": "verified_from_source"},
		"sidecars":         []any{},
	}
	manRaw, _ := json.Marshal(man)
	if err := os.WriteFile(filepath.Join(bundle, "manifest.json"), manRaw, 0o644); err != nil {
		t.Fatal(err)
	}
	manSum := sha256.Sum256(manRaw)
	latest := map[string]any{"run_id": runID,
		"manifest_sha256": hex.EncodeToString(manSum[:])}
	latestRaw, _ := json.Marshal(latest)
	if err := os.WriteFile(filepath.Join(pubDir, "LATEST.json"), latestRaw, 0o644); err != nil {
		t.Fatal(err)
	}
	return legacyDir, pubDir, hashes["v2_q_observed_report.json"],
		hashes["v2_value_pilot.json"], hashes["v2_t_pilot.json"]
}

func TestManifestReaderHappyPath(t *testing.T) {
	_, pubDir, qsha, _, _ := mkManifestFixtures(t)
	b, err := qvtLoadBundleFromManifest(pubDir)
	if err != nil {
		t.Fatalf("expected success, got %v", err)
	}
	if b.Q == nil || b.V == nil || b.T == nil {
		t.Fatal("bundle docs not populated")
	}
	if b.qSHA != qsha {
		t.Fatalf("q sha mismatch %s != %s", b.qSHA, qsha)
	}
	if !b.loadStable {
		t.Fatal("manifest bundle must be loadStable")
	}
	if b.manifest == nil || !strings.HasPrefix(b.manifest.RunID, "pub-2026-10-08") {
		t.Fatalf("manifest info missing: %+v", b.manifest)
	}
	if !strings.Contains(b.manifest.PublishedAt, "2026-10-09") {
		t.Fatalf("published_at wrong: %q", b.manifest.PublishedAt)
	}
}

func TestManifestReaderRejectsTamperedArtifact(t *testing.T) {
	legacyDir, pubDir, _, _, _ := mkManifestFixtures(t)
	// overwrite an artifact copy inside the bundle with different content
	b, err := qvtLoadBundleFromManifest(pubDir)
	if err != nil {
		t.Fatalf("pre-check failed: %v", err)
	}
	_ = b
	vf := filepath.Join(pubDir, "pub-2026-10-08-qtest-vtest-ttest", "v2_value_pilot.json")
	if err := os.WriteFile(vf, []byte(`{"as_of":"2026-10-08","coverage_summary":{"n_v_pilot_eligible":97}}`), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = qvtLoadBundleFromManifest(pubDir)
	if err == nil {
		t.Fatal("tampered artifact must be refused")
	}
	if !strings.Contains(err.Error(), "hash") {
		t.Fatalf("error should name the hash step, got: %v", err)
	}
	_ = legacyDir
}

func TestManifestReaderRejectsWrongManifestHash(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	latestPath := filepath.Join(pubDir, "LATEST.json")
	var latest map[string]any
	raw, _ := os.ReadFile(latestPath)
	_ = json.Unmarshal(raw, &latest)
	latest["manifest_sha256"] = strings.Repeat("0", 64)
	lr, _ := json.Marshal(latest)
	if err := os.WriteFile(latestPath, lr, 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil || !strings.Contains(err.Error(), "manifest") {
		t.Fatalf("wrong manifest hash must be refused, got %v", err)
	}
}

func TestManifestReaderRejectsMissingBundle(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	var latest map[string]any
	raw, _ := os.ReadFile(filepath.Join(pubDir, "LATEST.json"))
	_ = json.Unmarshal(raw, &latest)
	latest["run_id"] = "pub-does-not-exist"
	lr, _ := json.Marshal(latest)
	_ = os.WriteFile(filepath.Join(pubDir, "LATEST.json"), lr, 0o644)
	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil {
		t.Fatal("missing bundle must be refused")
	}
}

func TestManifestReaderRejectsConflictingChain(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	// rewrite manifest with a conflicting chain status + matching hash in LATEST
	manPath := filepath.Join(pubDir, "pub-2026-10-08-qtest-vtest-ttest", "manifest.json")
	raw, _ := os.ReadFile(manPath)
	var man map[string]any
	_ = json.Unmarshal(raw, &man)
	man["chain_validation"] = map[string]any{"status": "conflicting"}
	mr, _ := json.Marshal(man)
	_ = os.WriteFile(manPath, mr, 0o644)
	sum := sha256.Sum256(mr)
	latestPath := filepath.Join(pubDir, "LATEST.json")
	var latest map[string]any
	lr0, _ := os.ReadFile(latestPath)
	_ = json.Unmarshal(lr0, &latest)
	latest["manifest_sha256"] = hex.EncodeToString(sum[:])
	lr, _ := json.Marshal(latest)
	_ = os.WriteFile(latestPath, lr, 0o644)
	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil || !strings.Contains(err.Error(), "conflicting") {
		t.Fatalf("conflicting chain must be refused, got %v", err)
	}
}

func TestManifestModeHasNoHiddenFallback(t *testing.T) {
	legacyDir, pubDir, _, _, _ := mkManifestFixtures(t)
	t.Setenv("QVT_MANIFEST_DIR", pubDir)
	// manifest dir exists but LATEST is missing -> loud error, and the valid
	// legacy files next door must NOT be used as a silent fallback.
	if err := os.Remove(filepath.Join(pubDir, "LATEST.json")); err != nil {
		t.Fatal(err)
	}
	_, err := qvtLoadBundle(legacyDir) // env set -> manifest mode active
	if err == nil {
		t.Fatal("manifest mode with broken manifest dir must fail loudly")
	}
	if !strings.Contains(err.Error(), "LATEST.json") {
		t.Fatalf("error should mention the failing step, got: %v", err)
	}
}

func TestDirectModeUnchangedWhenEnvUnset(t *testing.T) {
	legacyDir, pubDir, _, _, _ := mkManifestFixtures(t)
	t.Setenv("QVT_MANIFEST_DIR", "")
	b, err := qvtLoadBundle(legacyDir)
	if err != nil {
		t.Fatalf("legacy path must work when env unset, got %v", err)
	}
	if b.manifest != nil {
		t.Fatal("no manifest info expected in direct mode")
	}
	if b.Q == nil || b.V == nil || b.T == nil {
		t.Fatal("legacy bundle not populated")
	}
	_ = pubDir
}

func TestBundleIntegrityReportsPublicationMode(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	b, err := qvtLoadBundleFromManifest(pubDir)
	if err != nil {
		t.Fatal(err)
	}
	bi := bundleIntegrityOf(b)
	pub, ok := bi["publication"].(gin.H)
	if !ok || pub["mode"] != "manifest_bundle" {
		t.Fatalf("publication block wrong: %+v", bi["publication"])
	}
	if pub["run_id"] != b.manifest.RunID {
		t.Fatalf("run_id mismatch in publication block")
	}
	// direct mode bundle
	legacyDir := t.TempDir()
	for name, doc := range map[string]map[string]any{
		"v2_q_observed_report.json": {"as_of": "2026-10-08"},
		"v2_value_pilot.json":       {"as_of": "2026-10-08"},
		"v2_t_pilot.json":           {"as_of": "2026-10-08"},
	} {
		r, _ := json.Marshal(doc)
		_ = os.WriteFile(filepath.Join(legacyDir, name), r, 0o644)
	}
	b2, err := qvtLoadBundle(legacyDir)
	if err != nil {
		t.Fatal(err)
	}
	bi2 := bundleIntegrityOf(b2)
	pub2 := bi2["publication"].(gin.H)
	if pub2["mode"] != "direct_files" {
		t.Fatalf("direct mode publication wrong: %+v", pub2)
	}
}

// sidecar ثبت‌شده در manifest بخشی از باندل است: فایل باید داخل باندل باشد و
// هشش بخواند؛ دستکاری یا نبود فایل = رد بلند (بسته ناقص سرو نمی‌شود).
func mkSidecarFixture(t *testing.T, pubDir, content string) {
	t.Helper()
	manPath := filepath.Join(pubDir, "pub-2026-10-08-qtest-vtest-ttest", "manifest.json")
	raw, _ := os.ReadFile(manPath)
	var man map[string]any
	if err := json.Unmarshal(raw, &man); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256([]byte(content))
	man["sidecars"] = []any{map[string]any{
		"file":       "publish_recovery_test.json",
		"sha256":     hex.EncodeToString(sum[:]),
		"size_bytes": len(content),
	}}
	mr, _ := json.Marshal(man)
	if err := os.WriteFile(manPath, mr, 0o644); err != nil {
		t.Fatal(err)
	}
	mSum := sha256.Sum256(mr)
	latestPath := filepath.Join(pubDir, "LATEST.json")
	var latest map[string]any
	lr0, _ := os.ReadFile(latestPath)
	_ = json.Unmarshal(lr0, &latest)
	latest["manifest_sha256"] = hex.EncodeToString(mSum[:])
	lr, _ := json.Marshal(latest)
	_ = os.WriteFile(latestPath, lr, 0o644)
}

func TestManifestReaderVerifiesSidecarHash(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	bundle := filepath.Join(pubDir, "pub-2026-10-08-qtest-vtest-ttest")
	content := `{"snapshot_binding":{}}`
	// happy: sidecar file present with matching hash
	if err := os.WriteFile(filepath.Join(bundle, "publish_recovery_test.json"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	mkSidecarFixture(t, pubDir, content)
	if _, err := qvtLoadBundleFromManifest(pubDir); err != nil {
		t.Fatalf("valid sidecar must load, got %v", err)
	}
	// tampered sidecar content -> refuse at the sidecar hash step
	if err := os.WriteFile(filepath.Join(bundle, "publish_recovery_test.json"), []byte(`{"tampered":true}`), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil || !strings.Contains(err.Error(), "sidecar") {
		t.Fatalf("tampered sidecar must be refused naming the sidecar step, got %v", err)
	}
}

func TestManifestReaderRejectsMissingSidecarFile(t *testing.T) {
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	// manifest lists a sidecar whose file is NOT in the bundle -> incomplete
	// bundle, loud refusal (no silent skip)
	mkSidecarFixture(t, pubDir, `{"snapshot_binding":{}}`)
	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil || !strings.Contains(err.Error(), "sidecar") {
		t.Fatalf("missing sidecar file must be refused, got %v", err)
	}
}

func TestManifestReaderRejectsHashlessSidecarRecord(t *testing.T) {
	// ۲-ک-۴ P2: رکورد sidecar بدون file/sha256 نقض قرارداد بسته است —
	// باید رد صریح شود، نه اینکه نادیده گرفته شود.
	_, pubDir, _, _, _ := mkManifestFixtures(t)
	manPath := filepath.Join(pubDir, "pub-2026-10-08-qtest-vtest-ttest", "manifest.json")
	raw, _ := os.ReadFile(manPath)
	var man map[string]any
	if err := json.Unmarshal(raw, &man); err != nil {
		t.Fatal(err)
	}
	man["sidecars"] = []any{map[string]any{"file": "publish_recovery_test.json"}}
	mr, _ := json.Marshal(man)
	if err := os.WriteFile(manPath, mr, 0o644); err != nil {
		t.Fatal(err)
	}
	mSum := sha256.Sum256(mr)
	latestPath := filepath.Join(pubDir, "LATEST.json")
	var latest map[string]any
	lr0, _ := os.ReadFile(latestPath)
	_ = json.Unmarshal(lr0, &latest)
	latest["manifest_sha256"] = hex.EncodeToString(mSum[:])
	lr, _ := json.Marshal(latest)
	_ = os.WriteFile(latestPath, lr, 0o644)

	_, err := qvtLoadBundleFromManifest(pubDir)
	if err == nil || !strings.Contains(err.Error(), "sidecar") {
		t.Fatalf("hashless sidecar record must be refused explicitly, got %v", err)
	}
}

func TestManifestBundleMatchesDirectFiles(t *testing.T) {
	// ۲-ک-۴ P2 sandbox: در حالت manifest باید همان داده‌ای سرو شود که
	// direct_files می‌دهد — Q/V/T و hashهای binding باید یک‌به‌یک برابرند.
	legacyDir, pubDir, qSHA, vSHA, tSHA := mkManifestFixtures(t)
	direct, err := qvtLoadBundle(legacyDir)
	if err != nil {
		t.Fatalf("direct load failed: %v", err)
	}
	viaManifest, err := qvtLoadBundleFromManifest(pubDir)
	if err != nil {
		t.Fatalf("manifest load failed: %v", err)
	}
	if direct.qSHA != viaManifest.qSHA || direct.vSHA != viaManifest.vSHA ||
		direct.tSHA != viaManifest.tSHA {
		t.Fatalf("binding hashes differ: direct %s/%s/%s manifest %s/%s/%s",
			direct.qSHA, direct.vSHA, direct.tSHA,
			viaManifest.qSHA, viaManifest.vSHA, viaManifest.tSHA)
	}
	if qSHA != direct.qSHA || vSHA != direct.vSHA || tSHA != direct.tSHA {
		t.Fatalf("fixture hashes mismatch")
	}
	for _, pair := range [][2]map[string]any{
		{direct.Q, viaManifest.Q}, {direct.V, viaManifest.V}, {direct.T, viaManifest.T},
	} {
		araw, _ := json.Marshal(pair[0])
		braw, _ := json.Marshal(pair[1])
		if string(araw) != string(braw) {
			t.Fatalf("manifest bundle content differs from direct files:\n%s\n%s", araw, braw)
		}
	}
}
