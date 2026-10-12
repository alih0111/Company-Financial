package qvt

// Evidence overlay (گام ۲-ک-۱ محور پنجم): the provenance reports produced by
// provenance_v1 runners (publish_recovery / valuation_audit /
// qt_economic_audit) are bound to the sha256 of the three artifacts they
// were computed for. This module surfaces them ONLY when their recorded
// snapshot_binding matches the CURRENT bundle hashes — an overlay whose
// binding does not match is reported as stale/absent and is never silently
// merged into fresh data.

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
)

type qvtOverlayBinding struct {
	Q      string `json:"q"`
	V      string `json:"v"`
	T      string `json:"t"`
	AsOf   string `json:"as_of"`
	Cutoff string `json:"cutoff"`
}

type qvtOverlayDoc struct {
	File     string
	Kind     string // publish_recovery | valuation_audit | qt_economic_audit
	SHA256   string
	Binding  qvtOverlayBinding
	Computed map[string]json.RawMessage // per-company payloads (lazily kept)
}

// overlayCompany برای یک شرکت چه چیزی از گزارش‌های ممیزی مستقل می‌دانیم.
type overlayCompany struct {
	PublishRecovery       *json.RawMessage `json:"publish_recovery,omitempty"`
	ValuationAudit        *json.RawMessage `json:"valuation_audit,omitempty"`
	IndependentValidation *json.RawMessage `json:"independent_validation,omitempty"`
	DecisionDossier       *json.RawMessage `json:"decision_dossier,omitempty"`
	QFactorDiagnostics    *json.RawMessage `json:"q_factor_diagnostics,omitempty"`
	EgEconomicAudit       *json.RawMessage `json:"eg_economic_audit,omitempty"`
}

var (
	overlayMu    sync.Mutex
	overlayCache = map[string]overlayCacheEntry{}
)

type overlayCacheEntry struct {
	mod   int64
	size  int64
	doc   *qvtOverlayDoc
	valid bool
}

// qvtOverlayDirs جایگاه گزارش‌های ممیزی را از محیط/چیدمان مخزن حدس می‌زند
// (QVT_EVIDENCE_OVERLAY_DIR override دارد). چون artDir هم می‌تواند پوشهٔ
// باندل منتشرشده باشد (manifest mode، حتی بیرون از مخزن در sandbox) و هم
// پوشهٔ آرتیفکت‌ها (direct mode)، از سه ریشه عبور می‌کنیم — artDir، cwd و
// پوشهٔ executable — و از هرکدام تا ۶ سطح بالا می‌رویم؛ اولین ریشه‌ای که
// provenance_v1/output واقعی داشته باشد برنده است. حدس مسیر هرگز جای گیت
// binding را نمی‌گیرد (گیت در qvtLoadOverlays اجرا می‌شود).
func qvtOverlayDirs(artDir string) []string {
	var dirs []string
	if d := strings.TrimSpace(os.Getenv("QVT_EVIDENCE_OVERLAY_DIR")); d != "" {
		dirs = append(dirs, d)
	}
	roots := []string{artDir}
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, wd)
	}
	if exe, err := os.Executable(); err == nil {
		roots = append(roots, filepath.Dir(exe))
	}
	for _, root := range roots {
		cur := root
		for i := 0; i < 7 && cur != ""; i++ {
			cand := filepath.Join(cur, "provenance_v1", "output")
			if st, err := os.Stat(cand); err == nil && st.IsDir() {
				dirs = append(dirs, cand)
				break
			}
			next := filepath.Dir(cur)
			if next == cur {
				break
			}
			cur = next
		}
	}
	dirs = append(dirs, filepath.Join("provenance_v1", "output"))
	return dirs
}

func loadOverlayDoc(path string) (*qvtOverlayDoc, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	overlayMu.Lock()
	ce, cached := overlayCache[path]
	overlayMu.Unlock()
	if cached && ce.mod == st.ModTime().UnixNano() && ce.size == st.Size() && ce.valid {
		return ce.doc, nil
	}
	var head struct {
		SnapshotBinding struct {
			Q      map[string]any `json:"q"`
			V      map[string]any `json:"v"`
			T      map[string]any `json:"t"`
			AsOf   any            `json:"as_of"`
			Cutoff any            `json:"cutoff"`
		} `json:"snapshot_binding"`
	}
	if err := json.Unmarshal(raw, &head); err != nil {
		overlayMu.Lock()
		overlayCache[path] = overlayCacheEntry{mod: st.ModTime().UnixNano(), size: st.Size(), valid: false}
		overlayMu.Unlock()
		return nil, fmt.Errorf("پارس overlay %s: %v", filepath.Base(path), err)
	}
	sha := func(m map[string]any) string {
		s, _ := m["sha256"].(string)
		return s
	}
	doc := &qvtOverlayDoc{
		File:   filepath.Base(path),
		Kind:   overlayKindOf(filepath.Base(path)),
		SHA256: sha256OfBytes(raw),
		Binding: qvtOverlayBinding{
			Q:      sha(head.SnapshotBinding.Q),
			V:      sha(head.SnapshotBinding.V),
			T:      sha(head.SnapshotBinding.T),
			AsOf:   first10(head.SnapshotBinding.AsOf),
			Cutoff: first10(head.SnapshotBinding.Cutoff),
		},
	}
	// per-company payloads only for the two per-company reports
	var companies map[string]json.RawMessage
	switch doc.Kind {
	case "publish_recovery":
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	case "valuation_audit":
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	case "independent_validation":
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	case "decision_dossier":
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	case "q_factor_diagnostics":
		// گام ۲-ک-۵: شاخص‌های بنیادی در حال اعتبارسنجی — کاملاً تشخیصی؛
		// هیچ مسیری به امتیاز رسمی Q ندارد و فقط با گیت binding همین
		// snapshot سرو می‌شود.
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	case "eg_economic_audit":
		// گام ۲-ک-۶: ممیزی اقتصادی مستقل earnings_growth — per-company برای
		// ۶۲ شرکت سه‌محوری؛ کاملاً تشخیصی، بدون هیچ مسیری به امتیاز رسمی Q
		// (policy exclusion گام ۲-ب-۶ دست‌نخورده می‌ماند) و فقط با گیت
		// binding همین snapshot سرو می‌شود.
		var full struct {
			Companies map[string]json.RawMessage `json:"companies"`
		}
		if json.Unmarshal(raw, &full) == nil {
			companies = full.Companies
		}
	}
	doc.Computed = companies
	overlayMu.Lock()
	overlayCache[path] = overlayCacheEntry{mod: st.ModTime().UnixNano(), size: st.Size(), valid: true, doc: doc}
	overlayMu.Unlock()
	return doc, nil
}

// first10 برش امن ۱۰ کاراکتر اول برای نمایش تاریخ (روی هر ورودی‌ای).
func first10(v any) string {
	s := strings.TrimSpace(fmt.Sprintf("%v", v))
	if len(s) > 10 {
		s = s[:10]
	}
	return s
}

func overlayKindOf(base string) string {
	switch {
	case strings.HasPrefix(base, "publish_recovery_"):
		return "publish_recovery"
	case strings.HasPrefix(base, "valuation_audit_"):
		return "valuation_audit"
	case strings.HasPrefix(base, "qt_economic_audit_"):
		return "qt_economic_audit"
	case strings.HasPrefix(base, "independent_validation_"):
		return "independent_validation"
	case strings.HasPrefix(base, "decision_dossier_"):
		return "decision_dossier"
	case strings.HasPrefix(base, "q_factor_diagnostics_"):
		return "q_factor_diagnostics"
	case strings.HasPrefix(base, "eg_economic_audit_"):
		return "eg_economic_audit"
	}
	return ""
}

// qvtLoadOverlays همه گزارش‌های ممیزیِ متصل به همین snapshot را برمی‌گرداند.
func qvtLoadOverlays(artDir string, b *qvtBundle) []qvtOverlayDoc {
	var out []qvtOverlayDoc
	seen := map[string]bool{}
	for _, dir := range qvtOverlayDirs(artDir) {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, e := range entries {
			if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
				continue
			}
			if overlayKindOf(e.Name()) == "" {
				continue
			}
			path := filepath.Join(dir, e.Name())
			abs, err := filepath.Abs(path)
			if err == nil {
				path = abs
			}
			if seen[path] {
				continue
			}
			seen[path] = true
			doc, err := loadOverlayDoc(path)
			if err != nil {
				continue
			}
			// binding gate: the overlay belongs to THIS snapshot only
			if doc.Binding.Q == b.qSHA && doc.Binding.V == b.vSHA &&
				doc.Binding.T == b.tSHA {
				out = append(out, *doc)
			}
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].File < out[j].File })
	return out
}

// overlayForCompany داده‌های per-company را از overlayهای متصل استخراج می‌کند.
func overlayForCompany(overlays []qvtOverlayDoc, cid string) gin.H {
	res := gin.H{}
	for _, oc := range overlays {
		if oc.Computed == nil {
			continue
		}
		if raw, ok := oc.Computed[cid]; ok {
			var v any
			if json.Unmarshal(raw, &v) == nil {
				res[oc.Kind] = v
			}
		}
	}
	return res
}

// validationActionsFor فهرست جمع‌وجور «اقدامات لازم برای اعتبارسنجی» برای
// یک شرکت — هیچ اقدامی امتیاز یا رتبه‌ای نمی‌سازد و هیچ کدام خودکار اجرا
// نمی‌شوند؛ فقط کارهای واقعیِ باقی‌مانده را صریح می‌کند.
func validationActionsFor(chain *evidenceChain, overlay gin.H) []gin.H {
	acts := []gin.H{}
	add := func(title, detail, priority string) {
		acts = append(acts, gin.H{"title": title, "detail": detail, "priority": priority})
	}

	// شواهد بازیابی‌شده publish_recovery برای این شرکت؟
	verifiedRows, totalRows := 0, 0
	if pr, ok := overlay["publish_recovery"].(map[string]any); ok {
		if rows, ok := pr["scoring_rows"].([]any); ok {
			totalRows = len(rows)
			for _, r := range rows {
				m, _ := r.(map[string]any)
				res, _ := m["resolved"].(map[string]any)
				if st, _ := res["status"].(string); st == "verified_publication_date" {
					verifiedRows++
				}
			}
		}
	}

	// وضعیت اعتبارسنجی اقتصادی مستقل (۲-ک-۲) — فقط اقدام صریح می‌سازد،
	// نه امتیاز و نه تغییر رتبه
	if iv, ok := overlay["independent_validation"].(map[string]any); ok {
		st, _ := iv["status"].(string)
		firstReason := ""
		if reasons, ok := iv["reasons"].([]any); ok && len(reasons) > 0 {
			firstReason, _ = reasons[0].(string)
		}
		switch st {
		case "conflicting":
			add("رفع تعارض اعتبارسنجی مستقل",
				firstReason, "P0")
		case "consistent_but_not_independent":
			add("بستن حلقه‌های اثبات‌نشدهٔ اعتبارسنجی مستقل",
				firstReason, "P0")
		case "insufficient_evidence":
			add("تکمیل شواهد ناکافی اعتبارسنجی مستقل",
				firstReason, "P1")
		}
	}

	if chain == nil {
		return acts
	}
	for _, ax := range chain.Axes {
		for _, it := range ax.Items {
			if it.Structural || it.Status == evVerified {
				continue
			}
			switch it.Key {
			case "q_financial_origin", "v_fundamentals_origin":
				if verifiedRows > 0 {
					add("تکمیل تاریخ انتشار گزارش‌های مالی",
						fmt.Sprintf("شواهد بازیابی‌شده آماده است: %d از %d ردیف امتیازساز تاریخ انتشار تأییدشده دارند (publish_recovery) — ثبت در published_at نیازمند تصمیم بازبینی است", verifiedRows, totalRows),
						"P0")
				} else {
					add("تکمیل تاریخ انتشار گزارش‌های مالی",
						"ثبت published_at واقعی از متادیتای نامه کدال برای گزارش‌های مهاجرت legacy — بدون حدس و بدون الگوی تأخیر", "P0")
				}
			case "v_shares_input":
				if len(it.Conflicts) > 0 {
					add("بازبینی ارزندگی پس از رویداد سرمایه",
						"رویداد معتبر تغییر سرمایه در بازه snapshot سهام تا قیمت — محاسبه پیشنهادی جایگزین در valuation_audit ثبت شده و جایگزین خودکار V نمی‌شود", "P0")
				} else {
					add("بستن شکاف زمانی سهام↔قیمت",
						"اتصال موتور V به share_events/corporate_actions با معناشناسی CONFIRMED تا فاصله چندروزه snapshot/قیمت به‌صورت خودکار ممیزی شود", "P1")
				}
			case "v_corporate_actions":
				add("تکمیل معناشناسی اقدامات شرکتی",
					"دسته‌بندی event_semantics_status برای ردیف‌های UNCLASSIFIED جدول corporate_actions", "P1")
			case "t_price_window":
				add("پوشش قیمت‌های با وقفه",
					"نمادهایی که آخرین قیمتشان از سیاست ۷ روز قدیمی‌تر است — تکمیل منبع قیمت پیش از تکیه بر T", "P1")
			}
		}
	}
	// dedupe بر اساس عنوان — «تکمیل تاریخ انتشار» برای Q و V یکی است
	seen := map[string]bool{}
	uniq := acts[:0]
	for _, a := range acts {
		t, _ := a["title"].(string)
		if seen[t] {
			continue
		}
		seen[t] = true
		uniq = append(uniq, a)
	}
	acts = uniq
	if len(acts) > 5 {
		acts = acts[:5]
	}
	return acts
}
