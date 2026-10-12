package qvt

// Tests for the snapshot-binding gate of the evidence overlay: a provenance
// report is surfaced ONLY when its recorded sha256 triple equals the live
// bundle hashes; otherwise it is invisible (stale), never merged.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func writeArtifact(t *testing.T, dir, name, content string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256([]byte(content))
	return hex.EncodeToString(sum[:])
}

func TestOverlayBindingGate(t *testing.T) {
	root := t.TempDir()
	artDir := filepath.Join(root, "artifacts")
	ovDir := filepath.Join(root, "overlay")
	for _, d := range []string{artDir, ovDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	qsha := writeArtifact(t, artDir, "v2_q_observed_report.json", `{"as_of":"2026-10-08"}`)
	vsha := writeArtifact(t, artDir, "v2_value_pilot.json", `{"as_of":"2026-10-08"}`)
	tsha := writeArtifact(t, artDir, "v2_t_pilot.json", `{"as_of":"2026-10-08"}`)
	b := &qvtBundle{dir: artDir, qSHA: qsha, vSHA: vsha, tSHA: tsha}

	binding := map[string]any{
		"q":      map[string]any{"sha256": qsha},
		"v":      map[string]any{"sha256": vsha},
		"t":      map[string]any{"sha256": tsha},
		"as_of":  "2026-10-08",
		"cutoff": "2026-10-08T23:59:00+00:00",
	}
	mk := func(name string, bind map[string]any, cid string) {
		doc := map[string]any{"snapshot_binding": bind,
			"companies": map[string]any{
				cid: map[string]any{"q_origin_after": "verified_from_source",
					"scoring_rows": []any{map[string]any{
						"resolved": map[string]any{"status": "verified_publication_date",
							"publish_at": "2026-10-05T09:00:00+03:30"}}}},
			}}
		raw, _ := json.Marshal(doc)
		if err := os.WriteFile(filepath.Join(ovDir, name), raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	mk("publish_recovery_2026-10-08_match.json", binding, "cid-1")
	stale := map[string]any{
		"q": map[string]any{"sha256": "0000"}, "v": map[string]any{"sha256": vsha},
		"t": map[string]any{"sha256": tsha}, "as_of": "2026-10-08"}
	mk("publish_recovery_2026-10-07_stale.json", stale, "cid-1")

	t.Setenv("QVT_EVIDENCE_OVERLAY_DIR", ovDir)
	overlays := qvtLoadOverlays(artDir, b)
	if len(overlays) != 1 {
		t.Fatalf("only the binding-matching overlay must load, got %d", len(overlays))
	}
	if overlays[0].Kind != "publish_recovery" {
		t.Fatalf("wrong kind: %s", overlays[0].Kind)
	}
	ovc := overlayForCompany(overlays, "cid-1")
	pr, ok := ovc["publish_recovery"].(map[string]any)
	if !ok {
		t.Fatalf("per-company payload missing: %+v", ovc)
	}
	if pr["q_origin_after"] != "verified_from_source" {
		t.Fatalf("payload wrong: %+v", pr)
	}
	// company absent from overlay -> empty
	if got := overlayForCompany(overlays, "cid-other"); len(got) != 0 {
		t.Fatalf("absent company must yield empty overlay: %+v", got)
	}
	// actions derived from chain+overlay must not panic with nil chain
	acts := validationActionsFor(nil, ovc)
	if len(acts) != 0 {
		t.Fatalf("nil chain must yield no actions")
	}
}

// پرونده تصمیم‌یار (۲-ک-۳): kind جدید decision_dossier باید مثل بقیهٔ
// overlayها شناخته شود، per-company بخواند و گیت binding رویش اجرا شود.
func TestDecisionDossierOverlay(t *testing.T) {
	root := t.TempDir()
	artDir := filepath.Join(root, "artifacts")
	ovDir := filepath.Join(root, "overlay")
	for _, d := range []string{artDir, ovDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	qsha := writeArtifact(t, artDir, "v2_q_observed_report.json", `{"as_of":"2026-10-08"}`)
	vsha := writeArtifact(t, artDir, "v2_value_pilot.json", `{"as_of":"2026-10-08"}`)
	tsha := writeArtifact(t, artDir, "v2_t_pilot.json", `{"as_of":"2026-10-08"}`)
	b := &qvtBundle{dir: artDir, qSHA: qsha, vSHA: vsha, tSHA: tsha}

	binding := map[string]any{
		"q": map[string]any{"sha256": qsha}, "v": map[string]any{"sha256": vsha},
		"t": map[string]any{"sha256": tsha}, "as_of": "2026-10-08",
		"cutoff": "2026-10-08T23:59:00+00:00",
	}
	dd := map[string]any{"snapshot_binding": binding,
		"companies": map[string]any{
			"cid-1": map[string]any{
				"symbol": "بوعلی",
				"sections": map[string]any{
					"summary": map[string]any{
						"why_review":      []any{"قوی‌ترین فاکتور: ROE"},
						"main_risk":       []any{"هشدار ثبت‌شده"},
						"needed_evidence": []any{"نامهٔ فصلی بعدی"}}}}}}
	raw, _ := json.Marshal(dd)
	if err := os.WriteFile(filepath.Join(ovDir, "decision_dossier_2026-10-08_x.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}

	t.Setenv("QVT_EVIDENCE_OVERLAY_DIR", ovDir)
	overlays := qvtLoadOverlays(artDir, b)
	if len(overlays) != 1 || overlays[0].Kind != "decision_dossier" {
		t.Fatalf("decision_dossier overlay must load with its kind, got %+v", overlays)
	}
	ovc := overlayForCompany(overlays, "cid-1")
	got, ok := ovc["decision_dossier"].(map[string]any)
	if !ok {
		t.Fatalf("per-company dossier payload missing: %+v", ovc)
	}
	if got["symbol"] != "بوعلی" {
		t.Fatalf("dossier payload wrong: %+v", got)
	}
	if ovc2 := overlayForCompany(overlays, "cid-other"); len(ovc2) != 0 {
		t.Fatalf("absent company must yield empty overlay: %+v", ovc2)
	}
}

// ممیزی اقتصادی earnings_growth (گام ۲-ک-۶): kind جدید eg_economic_audit
// باید شناخته شود، per-company بخواند و فقط با binding همین snapshot سرو شود.
// فاکتور policy-excluded گام ۲-ب-۶ است — payload هیچ مسیری به امتیاز رسمی
// Q ندارد و فقط تشخیصی نمایش داده می‌شود.
func TestEgEconomicAuditOverlay(t *testing.T) {
	root := t.TempDir()
	artDir := filepath.Join(root, "artifacts")
	ovDir := filepath.Join(root, "overlay")
	for _, d := range []string{artDir, ovDir} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	qsha := writeArtifact(t, artDir, "v2_q_observed_report.json", `{"as_of":"2026-10-08"}`)
	vsha := writeArtifact(t, artDir, "v2_value_pilot.json", `{"as_of":"2026-10-08"}`)
	tsha := writeArtifact(t, artDir, "v2_t_pilot.json", `{"as_of":"2026-10-08"}`)
	b := &qvtBundle{dir: artDir, qSHA: qsha, vSHA: vsha, tSHA: tsha}

	binding := map[string]any{
		"q": map[string]any{"sha256": qsha}, "v": map[string]any{"sha256": vsha},
		"t": map[string]any{"sha256": tsha}, "as_of": "2026-10-08",
		"cutoff": "2026-10-08T23:59:00+00:00",
	}
	doc := map[string]any{"snapshot_binding": binding,
		"companies": map[string]any{
			"cid-1": map[string]any{
				"symbol":  "غمینو",
				"verdict": "verified_with_limitation",
				"components": map[string]any{
					"net_profit_growth_pct": map[string]any{"status": "valid"}}}}}
	stale := map[string]any{"snapshot_binding": map[string]any{
		"q": map[string]any{"sha256": "0000"}, "v": map[string]any{"sha256": vsha},
		"t": map[string]any{"sha256": tsha}},
		"companies": map[string]any{"cid-1": map[string]any{"verdict": "stale"}}}
	for name, docX := range map[string]map[string]any{
		"eg_economic_audit_2026-10-08_match.json": doc,
		"eg_economic_audit_2026-10-07_stale.json": stale} {
		raw, _ := json.Marshal(docX)
		if err := os.WriteFile(filepath.Join(ovDir, name), raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}

	t.Setenv("QVT_EVIDENCE_OVERLAY_DIR", ovDir)
	overlays := qvtLoadOverlays(artDir, b)
	if len(overlays) != 1 || overlays[0].Kind != "eg_economic_audit" {
		t.Fatalf("only binding-matching eg_economic_audit must load, got %+v", overlays)
	}
	ovc := overlayForCompany(overlays, "cid-1")
	got, ok := ovc["eg_economic_audit"].(map[string]any)
	if !ok || got["verdict"] != "verified_with_limitation" {
		t.Fatalf("per-company audit payload wrong: %+v", ovc)
	}
	if got2 := overlayForCompany(overlays, "cid-other"); len(got2) != 0 {
		t.Fatalf("absent company must yield empty overlay: %+v", got2)
	}
}
