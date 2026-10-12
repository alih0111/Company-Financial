package qvt

// Opt-in versioned-bundle reader (گام ۲-ک-۱ محور چهارم).
//
// The producers keep writing the three artifact files exactly as before;
// publish_bundle.py (analytics_canonical_v1) additionally publishes a
// versioned, immutable bundle + manifest + atomically-swapped LATEST.json.
// This reader consumes that bundle ONLY when QVT_MANIFEST_DIR is set:
//   - unset            -> legacy direct-file path (unchanged behaviour)
//   - set + valid      -> bundle read, every file hash-verified against the
//                         manifest, chain validation re-checked
//   - set + ANY error  -> loud refusal, NEVER a silent fallback to the
//                         direct files (an inconsistent mix must not be served)
//
// Rollback = point LATEST.json back to the previous run_id (the publisher
// keeps every bundle dir immutable) or clear QVT_MANIFEST_DIR. Scores are
// byte-identical either way — the manifest only pins which copies are read.
//
// The manifest's run_id is a publication-bundle identity derived from
// content hashes; it is NOT a producer run identity and published_at is the
// bundle publication instant, never a data production date.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type qvtLatest struct {
	RunID          string `json:"run_id"`
	ManifestSHA256 string `json:"manifest_sha256"`
}

type qvtManifestFile struct {
	File      string `json:"file"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
}

type qvtManifest struct {
	ManifestVersion int                        `json:"manifest_version"`
	RunID           string                     `json:"run_id"`
	PublishedAt     string                     `json:"published_at"`
	ArtifactFiles   map[string]qvtManifestFile `json:"artifact_files"`
	ChainValidation map[string]any             `json:"chain_validation"`
	Sidecars        []map[string]any           `json:"sidecars"`
}

type qvtBundleManifest struct {
	RunID           string
	PublishedAt     string
	ManifestSHA256  string
	Dir             string
	Sidecars        []map[string]any
	ChainValidation map[string]any
}

// qvtManifestDir activates manifest mode; empty means opt-out.
func qvtManifestDir() string {
	return strings.TrimSpace(os.Getenv("QVT_MANIFEST_DIR"))
}

func sha256OfBytes(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// qvtLoadBundleFromManifest reads LATEST.json -> manifest.json -> the three
// artifact copies, verifying every hash on the way. Any failure is loud.
func qvtLoadBundleFromManifest(mdir string) (*qvtBundle, error) {
	refuse := func(step string, err error) (*qvtBundle, error) {
		return nil, fmt.Errorf("خواندن بسته منتشرشده شکست خورد (مرحله %s): %v", step, err)
	}
	latestRaw, err := os.ReadFile(filepath.Join(mdir, "LATEST.json"))
	if err != nil {
		return refuse("LATEST.json", err)
	}
	var latest qvtLatest
	if err := json.Unmarshal(latestRaw, &latest); err != nil {
		return refuse("پارس LATEST.json", err)
	}
	if strings.TrimSpace(latest.RunID) == "" {
		return refuse("اعتبارسنجی LATEST.json",
			fmt.Errorf("run_id خالی است"))
	}
	manPath := filepath.Join(mdir, latest.RunID, "manifest.json")
	manRaw, err := os.ReadFile(manPath)
	if err != nil {
		return refuse("manifest.json", err)
	}
	manSHA := sha256OfBytes(manRaw)
	if latest.ManifestSHA256 != "" && manSHA != latest.ManifestSHA256 {
		return refuse("تطبیق hash manifest",
			fmt.Errorf("sha256 manifest.json با LATEST.json نمی‌خواند: %s != %s",
				manSHA, latest.ManifestSHA256))
	}
	var man qvtManifest
	if err := json.Unmarshal(manRaw, &man); err != nil {
		return refuse("پارس manifest.json", err)
	}
	if st, _ := man.ChainValidation["status"].(string); st != "verified_from_source" {
		return refuse("اعتبارسنجی زنجیره",
			fmt.Errorf("chain_validation.status = %q — بسته ناسازگار سرو نمی‌شود", st))
	}
	bundleDir := filepath.Join(mdir, latest.RunID)
	b := &qvtBundle{dir: bundleDir}
	for _, f := range []struct {
		key, name string
		dst       *map[string]any
		sha       *string
		size      *int64
	}{
		{"q", "v2_q_observed_report.json", &b.Q, &b.qSHA, &b.qSize},
		{"v", "v2_value_pilot.json", &b.V, &b.vSHA, &b.vSize},
		{"t", "v2_t_pilot.json", &b.T, &b.tSHA, &b.tSize},
	} {
		mf, ok := man.ArtifactFiles[f.key]
		if !ok || mf.File != f.name {
			return refuse("manifest",
				fmt.Errorf("manifest فایل %s را با نام %q فهرست نکرده است", f.key, f.name))
		}
		raw, err := os.ReadFile(filepath.Join(bundleDir, mf.File))
		if err != nil {
			return refuse("خواندن "+mf.File, err)
		}
		if int64(len(raw)) != mf.SizeBytes {
			return refuse("اندازه "+mf.File,
				fmt.Errorf("%d != %d", len(raw), mf.SizeBytes))
		}
		got := sha256OfBytes(raw)
		if got != mf.SHA256 {
			return refuse("hash "+mf.File,
				fmt.Errorf("%s != %s", got, mf.SHA256))
		}
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			return refuse("پارس "+mf.File, err)
		}
		*f.dst = doc
		*f.sha = got
		*f.size = int64(len(raw))
	}
	b.loadStable = true // immutable bundle + every hash verified above
	// sidecarهای ثبت‌شده در manifest هم بخشی از بسته‌اند: هر فایل باید همین
	// نسخهٔ هش‌شده باشد؛ وگرنه بسته ناقص/دستکاری‌شده سرو نمی‌شود. رکوردِ
	// بدون هش هم خودش نقض قرارداد است و رد صریح می‌شود (۲-ک-۴ P2).
	for _, sc := range man.Sidecars {
		fn, _ := sc["file"].(string)
		wantSHA, _ := sc["sha256"].(string)
		if strings.TrimSpace(fn) == "" || strings.TrimSpace(wantSHA) == "" {
			return refuse("اعتبارسنجی sidecar",
				fmt.Errorf("رکورد sidecar بدون file/sha256 در manifest — "+
					"بسته ناقص ثبت شده و سرو نمی‌شود"))
		}
		scRaw, err := os.ReadFile(filepath.Join(bundleDir, fn))
		if err != nil {
			return refuse("خواندن sidecar "+fn, err)
		}
		if got := sha256OfBytes(scRaw); got != wantSHA {
			return refuse("hash sidecar "+fn,
				fmt.Errorf("%s != %s", got, wantSHA))
		}
		if w, _ := sc["size_bytes"].(float64); w > 0 &&
			int64(len(scRaw)) != int64(w) {
			return refuse("اندازه sidecar "+fn,
				fmt.Errorf("%d != %.0f", len(scRaw), w))
		}
	}
	b.manifest = &qvtBundleManifest{
		RunID:           man.RunID,
		PublishedAt:     man.PublishedAt,
		ManifestSHA256:  manSHA,
		Dir:             mdir,
		Sidecars:        man.Sidecars,
		ChainValidation: man.ChainValidation,
	}
	return b, nil
}
