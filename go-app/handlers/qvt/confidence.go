package qvt

// Data Confidence — مستقل از امتیاز Q/V/T، فقط‌خواندنی و توضیح‌پذیر (گام ۲-ز-۱).
//
// قرارداد:
//   - پنج بُعد مستقل: completeness / temporal / provenance / financial / market
//   - هر بُعد فقط از فیلدهای واقعی و هشدارهای ثبت‌شده در همان سه آرتیفکت
//     می‌خواند؛ هیچ provenance، تاریخ، مقدار مالی یا «عدد اطمینان» ساخته
//     نمی‌شود. خروجی فقط وضعیت + دلایل قابل ردیابی است.
//   - وضعیت هر بُعد: findings (یافته ثبت‌شده) / no_findings (بدون یافته
//     ثبت‌شده — معادل تأیید نیست) / not_evaluable (شواهد کافی نیست).
//   - «هشدار جدی» فقط هشدارهایی است که متن ثبت‌شده در آرتیفکت صراحتاً
//     مشکوک/خارج از بازه اعتبار/غیرقابل‌اثبات بودن داده را اعلام می‌کند؛
//     نبود آن به معنی نبود ریسک یا تأیید کامل داده نیست.
//   - انواع هشدار ناشناخته دور ریخته نمی‌شوند: با برچسب «ناشناخته» و
//     محافظه‌کارانه جدی نمایش داده می‌شوند، بدون ادعای خطای قطعی.
//   - Risk Gate مستقل در riskgate.go ارزیابی ریسک را با قواعد صریح انجام
//     می‌دهد؛ این ارزیابی جایگزین آن نیست و فقط شواهد داده را می‌سنجد.
//   - این ارزیابی هیچ فیلد امتیاز/پوشش/واجدشرایطی را نمی‌سازد یا تغییر
//     نمی‌دهد — فقط از متادیتا می‌خواند.
//
// ثبت هشدار در آرتیفکت‌های واقعی: financial_warnings فقط در Q و V،
// trading_warnings فقط در T — پس ارزیابی‌پذیری هر بُعد از کلیدهای
// دیده‌شده در بلوک‌های موجود تعیین می‌شود، نه از فرض.

import (
	"fmt"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"
)

// dcStatus values for every dimension.
const (
	dcFindings     = "findings"
	dcNoFindings   = "no_findings"
	dcNotEvaluable = "not_evaluable"
)

type dcDimension struct {
	Key     string   `json:"key"`
	Title   string   `json:"title"`
	Sources string   `json:"sources"`
	Status  string   `json:"status"`
	Reasons []string `json:"reasons"`
}

type discConfidence struct {
	Overall         string         `json:"overall"` // findings | no_findings_recorded | not_evaluable
	OverallLabel    string         `json:"overall_label"`
	OverallNote     string         `json:"overall_note"`
	DimensionCounts map[string]int `json:"dimension_counts"`
	Dimensions      []dcDimension  `json:"dimensions"`
	SeriousWarnings []string       `json:"serious_warnings"`
	SeriousNote     string         `json:"serious_note"`
}

// dcDimensionMeta — هر بُعد فقط از فیلدهای واقعی خودش می‌خواند. بعد از
// بازکالیبراسیون گام ۲-ح-۱، ریسک‌های اقتصادی و نسبت‌های ارزندگی دیگر یافته
// اطمینان داده نیستند (مالکیت واحد در warningclass.go).
var dcDimensionMeta = []struct {
	key, title, sources string
}{
	{"completeness", "کامل بودن داده و فاکتورهای ضروری",
		"coverage_ratio و covered_weight و essential_status و فاکتورهای included در هر سه آرتیفکت Q/V/T"},
	{"temporal", "سازگاری زمانی تاریخ‌ها",
		"هشدار ثبت‌شده stale_price و share_snapshot_older_than_price (سازگاری تعداد سهام با قیمت — بازبینی، نه خطای قطعی)"},
	{"provenance", "قابلیت ردیابی منابع (Provenance)",
		"data_confidence.pit_status_counts در آرتیفکت‌ها و هشدار ثبت‌شده order3_recovered_from_raw_letter"},
	{"financial", "یکپارچگی داده مالی",
		"risk_gate.financial_warnings از انواع یکپارچگی داده مالی (magnitude_anomaly) و raw_status فاکتورهای امتیازگرفته"},
	{"market", "یکپارچگی داده بازار",
		"risk_gate.trading_warnings و financial_warnings از انواع داده بازار (suspected_unadjusted_gap، liquidity_window_composition)"},
}

var dcSeriousNote = "«هشدار جدی» یعنی متن ثبت‌شده در آرتیفکت مشکوک جدی به مشکل داده است — نه خطای اثبات‌شده و نه ریسک اقتصادی؛ ریسک اقتصادی (زیان‌دهی) و نسبت‌های ارزندگی خارج از بازه، هشدار داده نیستند و در Risk Gate جدا ارزیابی می‌شوند؛ نبود هشدار جدی به معنی نبود ریسک یا تأیید کامل داده نیست."

// dcMissingFactorSummary lists not-scored factors as «id (reason-kind)».
func dcMissingFactorSummary(cm map[string]any) []string {
	factors, _ := cm["factors"].(map[string]any)
	ids := make([]string, 0, len(factors))
	for id := range factors {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	out := []string{}
	for _, id := range ids {
		f, _ := factors[id].(map[string]any)
		if f == nil {
			continue
		}
		included := false
		if b, ok := f["included"].(bool); ok {
			included = b
		} else if f["score"] != nil {
			included = true
		}
		if included {
			continue
		}
		reason := firstNonEmpty(qvtStr(f, "not_included_reason"), qvtStr(f, "raw_status"))
		kind := reason
		if i := strings.Index(reason, ":"); i >= 0 {
			kind = reason[:i]
		}
		out = append(out, fmt.Sprintf("%s (%s)", id, kind))
	}
	return out
}

// dcEssentialMissing returns the recorded missing essential factors.
func dcEssentialMissing(cm map[string]any) []string {
	ess, _ := cm["essential_status"].(map[string]any)
	raw, _ := ess["missing"].([]any)
	out := []string{}
	for _, v := range raw {
		if s, ok := v.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	return out
}

// dcPitFinding reports non-zero PIT counts recorded for one axis.
func dcPitFinding(axis string, pit map[string]any) ([]string, bool) {
	keys := make([]string, 0, len(pit))
	for k := range pit {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	reasons := []string{}
	found := false
	for _, k := range keys {
		n, ok := pit[k].(float64)
		if !ok || n <= 0 {
			continue
		}
		found = true
		if k == "unverified_no_publication_date" {
			reasons = append(reasons, fmt.Sprintf("محور %s: %.0f ورودی بدون تاریخ انتشار ثبت شده (unverified_no_publication_date) — قابل اثبات نیست", axis, n))
		} else {
			reasons = append(reasons, fmt.Sprintf("محور %s: %.0f ورودی با وضعیت PIT «%s»", axis, n, k))
		}
	}
	return reasons, found
}

// discConfidenceFor evaluates the five DC dimensions for one company from
// its three raw axis blocks (any of which may be absent — the detail panel
// also serves non-triple-eligible companies). Read-only over the maps.
func discConfidenceFor(qcm, vcm, tcm map[string]any) discConfidence {
	axes := []struct {
		name string
		cm   map[string]any
	}{{"Q", qcm}, {"V", vcm}, {"T", tcm}}

	dims := map[string]*dcDimension{}
	for _, m := range dcDimensionMeta {
		dims[m.key] = &dcDimension{Key: m.key, Title: m.title, Sources: m.sources, Reasons: []string{}}
	}

	// ── completeness ────────────────────────────────────────────────────
	comp := dims["completeness"]
	anyCoverage := false
	for _, ax := range axes {
		if ax.cm == nil {
			continue
		}
		cov, ok := qvtFloat(ax.cm, "coverage_ratio")
		if !ok {
			comp.Reasons = append(comp.Reasons, fmt.Sprintf("محور %s: فیلد پوشش در آرتیفکت ثبت نشده — این محور در این بُعد ارزیابی‌ناپذیر است", ax.name))
			continue
		}
		anyCoverage = true
		var axisFindings []string
		if cov < 1.0 {
			cw, _ := qvtFloat(ax.cm, "covered_weight")
			mw, _ := qvtFloat(ax.cm, "missing_weight")
			axisFindings = append(axisFindings, fmt.Sprintf("پوشش %s کامل نیست: %.0f از %.0f وزن (%.0f%%)", ax.name, cw, cw+mw, cov*100))
		}
		if missing := dcMissingFactorSummary(ax.cm); len(missing) > 0 {
			axisFindings = append(axisFindings, fmt.Sprintf("فاکتورهای نمره‌نگرفته %s: %s", ax.name, strings.Join(missing, "؛ ")))
		}
		if ess := dcEssentialMissing(ax.cm); len(ess) > 0 {
			axisFindings = append(axisFindings, fmt.Sprintf("فاکتورهای ضروری غایب %s: %s", ax.name, strings.Join(ess, "، ")))
		}
		if len(axisFindings) > 0 {
			comp.Status = dcFindings
			comp.Reasons = append(comp.Reasons, axisFindings...)
		}
	}
	if !anyCoverage && comp.Status == "" {
		comp.Status = dcNotEvaluable
		comp.Reasons = append(comp.Reasons, "هیچ محور قابل ارزیابی با فیلد پوشش در دسترس نیست")
	} else if comp.Status == "" {
		comp.Status = dcNoFindings
	}

	// ── recorded warnings — از لایه طبقه‌بندی واحد (warningclass.go) ────
	// ریسک‌های اقتصادی و نسبت‌های ارزندگی (DCDim == "") یافته اطمینان داده
	// نیستند و به Risk Gate می‌روند.
	type dcHit struct {
		axis, text string
		serious    bool
		unknown    bool
	}
	hits := map[string][]dcHit{} // dimension → hits
	finListSeen := warnListSeen(qcm, "financial_warnings") || warnListSeen(vcm, "financial_warnings") || warnListSeen(tcm, "financial_warnings")
	trdListSeen := warnListSeen(qcm, "trading_warnings") || warnListSeen(vcm, "trading_warnings") || warnListSeen(tcm, "trading_warnings")
	for _, e := range collectWarnings(qcm, vcm, tcm) {
		if e.Class.DCDim == "" {
			continue
		}
		hits[e.Class.DCDim] = append(hits[e.Class.DCDim], dcHit{axis: e.Axis, text: e.Text, serious: e.Class.Serious, unknown: e.Unknown})
	}

	warnReasons := func(dim string) []string {
		out := []string{}
		for _, h := range hits[dim] {
			note := ""
			if h.unknown {
				note = " (نوع هشدار در جدول طبقه‌بندی نیست — با برچسب «ناشناخته» و به‌صورت محافظه‌کارانه جدی نمایش داده می‌شود)"
			}
			out = append(out, fmt.Sprintf("[%s] %s%s", h.axis, h.text, note))
		}
		return out
	}

	// ── temporal / market / financial from recorded warnings ───────────
	// evaluable iff a list that could record its kinds was actually seen
	warnDim := func(dim string, evaluable bool) {
		d := dims[dim]
		d.Reasons = append(d.Reasons, warnReasons(dim)...)
		switch {
		case len(hits[dim]) > 0:
			d.Status = dcFindings
		case evaluable:
			d.Status = dcNoFindings
		default:
			d.Status = dcNotEvaluable
			d.Reasons = append(d.Reasons, "فهرست هشدار مرتبط در آرتیفکت‌های موجود ثبت نشده است — ارزیابی‌ناپذیر")
		}
	}
	warnDim("temporal", finListSeen)
	warnDim("market", finListSeen || trdListSeen)
	warnDim("financial", finListSeen)

	// financial integrity also examines raw_status of scored factors
	if dims["financial"].Status != dcNotEvaluable {
		for _, ax := range axes {
			if ax.cm == nil {
				continue
			}
			factors, _ := ax.cm["factors"].(map[string]any)
			ids := make([]string, 0, len(factors))
			for id := range factors {
				ids = append(ids, id)
			}
			sort.Strings(ids)
			for _, id := range ids {
				f, _ := factors[id].(map[string]any)
				if f == nil {
					continue
				}
				included := false
				if b, ok := f["included"].(bool); ok {
					included = b
				} else if f["score"] != nil {
					included = true
				}
				rs := qvtStr(f, "raw_status")
				if included && rs != "" && rs != "valid" {
					dims["financial"].Status = dcFindings
					dims["financial"].Reasons = append(dims["financial"].Reasons,
						fmt.Sprintf("فاکتور امتیازگرفته %s در محور %s با raw_status غیرمعتبر: %s", id, ax.name, rs))
				}
			}
		}
	}

	// ── provenance ──────────────────────────────────────────────────────
	prov := dims["provenance"]
	evaluableAxes := 0
	provFindings := false
	for _, ax := range axes {
		if ax.cm == nil {
			continue
		}
		dcRaw, ok := ax.cm["data_confidence"].(map[string]any)
		if !ok {
			prov.Reasons = append(prov.Reasons, fmt.Sprintf("محور %s: بلوک data_confidence در آرتیفکت ثبت نشده — شواهد ردیابی این محور ارزیابی‌ناپذیر است", ax.name))
			continue
		}
		pit, ok := dcRaw["pit_status_counts"].(map[string]any)
		if !ok {
			prov.Reasons = append(prov.Reasons, fmt.Sprintf("محور %s: شواهد ردیابی منبع (pit_status_counts) در آرتیفکت ثبت نشده — ارزیابی‌ناپذیر", ax.name))
			continue
		}
		evaluableAxes++
		reasons, found := dcPitFinding(ax.name, pit)
		if found {
			provFindings = true
		}
		prov.Reasons = append(prov.Reasons, reasons...)
	}
	if len(hits["provenance"]) > 0 {
		provFindings = true
		prov.Reasons = append(prov.Reasons, warnReasons("provenance")...)
	}
	switch {
	case evaluableAxes == 0 && len(hits["provenance"]) == 0:
		prov.Status = dcNotEvaluable
	case provFindings:
		prov.Status = dcFindings
	default:
		prov.Status = dcNoFindings
	}

	// ── serious warnings + overall ──────────────────────────────────────
	seriousSet := map[string]bool{}
	for _, list := range hits {
		for _, h := range list {
			if h.serious {
				kind := h.text
				if i := strings.Index(kind, ":"); i >= 0 {
					kind = kind[:i]
				}
				seriousSet[kind] = true
			}
		}
	}
	serious := make([]string, 0, len(seriousSet))
	for k := range seriousSet {
		serious = append(serious, k)
	}
	sort.Strings(serious)

	counts := map[string]int{"findings": 0, "no_findings": 0, "not_evaluable": 0}
	ordered := make([]dcDimension, 0, len(dcDimensionMeta))
	allUnevaluable := true
	anyFindings := false
	for _, m := range dcDimensionMeta {
		d := dims[m.key]
		counts[d.Status]++
		ordered = append(ordered, *d)
		if d.Status != dcNotEvaluable {
			allUnevaluable = false
		}
		if d.Status == dcFindings {
			anyFindings = true
		}
	}

	res := discConfidence{
		Dimensions:      ordered,
		SeriousWarnings: serious,
		SeriousNote:     dcSeriousNote,
		DimensionCounts: counts,
	}
	switch {
	case allUnevaluable:
		res.Overall = "not_evaluable"
		res.OverallLabel = "ارزیابی‌ناپذیر"
		res.OverallNote = "هیچ بُعدی با شواهد کافی ارزیابی نشد؛ هیچ تأیید یا ردی از داده ساخته نشد."
	case anyFindings:
		res.Overall = "findings"
		res.OverallLabel = "دارای یافته ثبت‌شده"
		res.OverallNote = "حداقل یک بُعد یافته ثبت‌شده دارد؛ منبع و متن هر یافته در dimensions آمده است."
	default:
		res.Overall = "no_findings_recorded"
		res.OverallLabel = "بدون یافته ثبت‌شده (معادل تأیید کامل داده نیست)"
		res.OverallNote = "در بُعدهای قابل ارزیابی هیچ یافته‌ای ثبت نشده؛ این به معنی تأیید کامل داده یا کم‌ریسک بودن نیست."
	}
	return res
}

// qvtConfidenceRules is published once per discovery/detail response so the
// contract is auditable from the UI itself.
var qvtConfidenceRules = gin.H{
	"what_it_is":       "ارزیابی مستقل و توضیح‌پذیر شواهد داده — جدا از امتیازهای Q/V/T و جدا از Risk Gate؛ فقط وضعیت هر بُعد و دلایل قابل ردیابی، بدون هیچ عدد اطمینان",
	"no_numeric_score": "در این مرحله هیچ امتیاز عددی Data Confidence ساخته نمی‌شود؛ فرمول عددی تأیید نشده است",
	"statuses": gin.H{
		dcFindings:     "یافته ثبت‌شده در آرتیفکت — همراه منبع و متن اصلی",
		dcNoFindings:   "بدون یافته ثبت‌شده — معادل تأیید نیست؛ نبود شواهد هرگز به معنی تأیید شدن نیست",
		dcNotEvaluable: "شواهد کافی برای ارزیابی این بُعد وجود ندارد",
	},
	"overall": gin.H{
		"findings":             "حداقل یک بُعد یافته ثبت‌شده دارد",
		"no_findings_recorded": "بُعدهای قابل ارزیابی بدون یافته — معادل تأیید کامل داده نیست",
		"not_evaluable":        "هیچ بُعدی با شواهد کافی ارزیابی نشد",
	},
	"dimensions":           dcDimensionMeta,
	"warning_kind_map":     qvtWarnClassRows(),
	"unknown_warning_rule": "نوع هشداری که در جدول طبقه‌بندی نیست دور ریخته نمی‌شود؛ در بُعد منشأ خود با برچسب «ناشناخته» و به‌صورت محافظه‌کارانه جدی نمایش داده می‌شود و هیچ ادعای خطای قطعی درباره آن نمی‌شود",
	"serious_rule":         dcSeriousNote,
	"risk_gate_unchanged":  "Risk Gate مستقل (کنار همین ارزیابی در پاسخ) وضعیت ریسک را با قواعد صریح صادر می‌کند؛ این ارزیابی فقط شواهد داده را می‌سنجد، جایگزین آن نیست و هیچ عدد اطمینان نمی‌سازد",
	"recalibrated":         "بازکالیبراسیون گام ۲-ح-۱: نسبت‌های ارزندگی خارج از بازه مرجع و ریسک‌های اقتصادی (زیان‌دهی) دیگر یافته اطمینان داده نیستند و به Risk Gate (حوزه بنیادی/ارزندگی) منتقل شدند؛ سازگاری تعداد سهام و قیمت «نیازمند بررسی» است نه هشدار جدی؛ «هشدار جدی» فقط مشکوک‌های جدی به مشکل داده است",
	"no_score_change":      "این ارزیابی فقط از متادیتا می‌خواند؛ هیچ امتیاز مشاهده‌شده Q/V/T، پوشش، واجد شرایطی یا ترتیبی تغییر نمی‌کند",
}
