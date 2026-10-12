package qvt

// Risk Gate مستقل و فقط‌خواندنی (گام ۲-ح-۱).
//
// قرارداد وضعیت‌ها:
//   blocked               — مانع معتبر و قابل اثبات طبق قاعده صریح (B1/B2)
//   review_required       — ریسک یا هشدار مهم ثبت‌شده که بررسی می‌خواهد
//   insufficient_evidence — شواهد برای تصمیم کافی نیست؛ به‌جای نتیجه‌گیری قطعی
//   no_verified_blocker   — در محدوده بررسی‌های انجام‌شده مانع اثبات‌شده‌ای
//                           یافت نشد (به معنی کم‌ریسک بودن یا تأیید
//                           سرمایه‌گذاری نیست)
//
// مرزهای سخت:
//   - سه حوزه مستقل: اعتبار داده (data) / ریسک بنیادی و ارزندگی
//     (fundamental) / ریسک بازار و ورود (market) — هشدارهای ارزندگی، داده و
//     شرایط ورود با هم مخلوط نمی‌شوند.
//   - ریسک اقتصادی واقعی (زیان‌دهی و امثال آن) الزاماً blocked نمی‌سازد.
//   - هیچ مانع سختی بدون دلیل معتبر و قاعده صریح صادر نمی‌شود.
//   - این ارزیابی حق تغییر، ضرب یا بازنرمال‌سازی هیچ امتیاز Q/V/T را ندارد —
//     فقط از هشدارها و متادیتای ثبت‌شده می‌خواند.
//   - سازگاری as_of/cutoff سه فایل، بررسی سطح snapshot است و از اعتبار
//     زمانی داده داخلی هر شرکت جدا می‌شود (snapshot_consistency جدا سرو
//     می‌شود؛ اینجا به حساب شرکت نوشته نمی‌شود).

import (
	"fmt"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"
)

const (
	rgBlocked = "blocked"
	rgReview  = "review_required"
	rgInsuff  = "insufficient_evidence"
	rgClear   = "no_verified_blocker"

	// قواعد blocking صریح — تنها مسیرهای مجاز برای وضعیت blocked.
	ruleB1 = "B1"
	ruleB2 = "B2"
)

var rgStatusLabels = map[string]string{
	rgBlocked: "مسدود — مانع اثبات‌شده",
	rgReview:  "نیازمند بررسی",
	rgInsuff:  "شواهد ناکافی برای تصمیم",
	rgClear:   "بدون مانع اثبات‌شده (≠ تأیید)",
}

var rgStatusNotes = map[string]string{
	rgBlocked: "حداقل یک مانع معتبر و قابل اثبات طبق قاعده صریح یافت شد؛ شواهد و شماره قاعده در blockers آمده است. این وضعیت هیچ امتیازی را تغییر نمی‌دهد.",
	rgReview:  "هیچ مانع اثبات‌شده‌ای یافت نشد اما هشدار یا ریسک مهمی ثبت شده که بررسی می‌خواهد؛ یافته‌ها با نوع و شدت و شواهد از هم جدا شده‌اند. این وضعیت تصمیم قطعی نیست.",
	rgInsuff:  "بررسی‌های لازم با شواهد موجود ناتمام ماند؛ به‌جای نتیجه‌گیری قطعی، شکاف شواهد فهرست شده است. شواهد ناکافی به معنی سالم بودن داده یا نبود ریسک نیست.",
	rgClear:   "در محدوده بررسی‌های انجام‌شده مانع اثبات‌شده‌ای یافت نشد؛ این به معنی کم‌ریسک بودن، تأیید سرمایه‌گذاری یا تأیید کامل داده نیست.",
}

// riskFinding یک یافته ریسک با نوع، شدت، دلیل و شواهد واقعی ثبت‌شده.
type riskFinding struct {
	Kind          string   `json:"kind"`
	Axis          string   `json:"axis"`
	Area          string   `json:"area"`
	Category      string   `json:"category"`
	Severity      string   `json:"severity"`
	SeverityLabel string   `json:"severity_label"`
	Reason        string   `json:"reason"`
	Evidence      []string `json:"evidence"`
	GateEffect    string   `json:"gate_effect"`
	BlockingRule  string   `json:"blocking_rule,omitempty"`
}

// riskArea وضعیت یک حوزه ریسک با یافته‌ها و شکاف شواهدش.
type riskArea struct {
	Key          string        `json:"key"`
	Title        string        `json:"title"`
	Status       string        `json:"status"`
	StatusLabel  string        `json:"status_label"`
	Findings     []riskFinding `json:"findings"`
	EvidenceGaps []string      `json:"evidence_gaps"`
	Checks       []string      `json:"checks"`
}

// riskGateEval خروجی کامل دروازه ریسک برای یک شرکت.
type riskGateEval struct {
	Status         string        `json:"status"`
	StatusLabel    string        `json:"status_label"`
	StatusNote     string        `json:"status_note"`
	Areas          []riskArea    `json:"areas"`
	Blockers       []riskFinding `json:"blockers"`
	ReviewFindings []riskFinding `json:"review_findings"`
	EvidenceGaps   []string      `json:"evidence_gaps"`
	WarningKinds   []string      `json:"warning_kinds"`
	Note           string        `json:"note"`
}

var rgAreaTitles = map[string]string{
	areaData:        "الف — اعتبار داده",
	areaFundamental: "ب — ریسک بنیادی و ارزندگی",
	areaMarket:      "ج — ریسک بازار و ورود",
}

var rgAreaChecks = map[string][]string{
	areaData: {
		"اسکن فهرست هشدارهای مالی (Q/V) و معاملاتی (T)",
		"raw_status فاکتورهای امتیازگرفته — قاعده B2 (داده نامعتبر/قرنطینه‌شده در امتیاز)",
		"تازگی قیمت مرجع — کنترل مستقل از منبع واقعی market.price_observations در پنجره PIT آرتیفکت (قاعده B1 اصلاح‌شده)",
		"شواهد PIT/تاریخ انتشار هر محور",
		"سازگاری تعداد سهام و قیمت — فقط بازبینی؛ به‌تنهایی هرگز مانع نیست",
	},
	areaFundamental: {
		"اسکن هشدارهای سودآوری ثبت‌شده (loss_maker، turned_to_loss، negative_operating_profit)",
		"اسکن نسبت‌های ارزندگی خارج از بازه مرجع (pe/pb/ps_above_v1_valid_band)",
		"اهرم و پوشش بهره: فقط در صورت وجود شواهد معتبر ارزیابی می‌شود — بدون شواهد هیچ نتیجه‌ای صادر نمی‌شود",
	},
	areaMarket: {
		"اسکن هشدارهای نقدشوندگی و ترکیب پنجره معاملاتی",
		"اسکن پرش‌های مشکوک قیمت در سری تعدیل‌شده",
		"محدودیت‌های فاکتورهای T از factor_issues ثبت‌شده",
	},
}

func rgFindingFrom(e warnEvidence) riskFinding {
	ev := []string{"متن ثبت‌شده در آرتیفکت: " + e.Text}
	f := riskFinding{
		Kind:          e.Kind,
		Axis:          e.Axis,
		Area:          e.Class.Area,
		Category:      e.Class.Category,
		Severity:      e.Class.Severity,
		SeverityLabel: sevLabels[e.Class.Severity],
		Reason:        e.Class.Reason,
		Evidence:      ev,
		GateEffect:    e.Class.Effect,
	}
	if e.Unknown {
		f.Evidence = append(f.Evidence, "نوع هشدار در جدول طبقه‌بندی ثبت نیست — بدون ادعای خطا نمایش داده می‌شود")
	}
	return f
}

// rgApplyB1 حکم مستقل منبع قیمت را روی یافته stale_price می‌نشاند (گام
// ۲-ط-۱). بازخوانی عدد از متن هشدار اثبات مستقل نیست؛ تنها چهار مسیر داریم:
//   - حکم منبع، نقض سیاست را اثبات کند → blocked (قاعده B1، شدت
//     «نقض اثبات‌شده سیاست» — جدا از «خطای داده»)
//   - حکم منبع، نقض را بازتولید نکند → هشدار مشکوک می‌ماند و تناقض ثبت می‌شود
//   - منبع در دسترس نباشد یا ردیفی نیابد → هشدار مشکوک می‌ماند + شکاف شواهد
// اثبات مستقل انجام نشده، هیچ‌وقت ادعای «مانع اثبات‌شده» صادر نمی‌شود.
func rgApplyB1(f riskFinding, e warnEvidence, pc *priceCheck) (riskFinding, []string) {
	if e.Kind != "stale_price" {
		return f, nil
	}
	if e.StaleParseable {
		f.Evidence = append(f.Evidence,
			fmt.Sprintf("بازخوانی متن ثبت‌شده (فقط نمایشی — اثبات مستقل نیست): آخرین معامله %d روز و سیاست همان متن %d روز", e.StaleDays, e.StalePolicy))
	}
	var gaps []string
	switch {
	case pc == nil:
		f.Evidence = append(f.Evidence, "کنترل مستقل تازگی قیمت در این پاسخ انجام نشده است — هشدار مشکوک می‌ماند و ادعای «مانع اثبات‌شده» ندارد")
		gaps = append(gaps, "تازگی قیمت (B1): کنترل مستقل از منبع قیمت در این پاسخ انجام نشده — ادعای «مانع اثبات‌شده» نداریم")
	case !pc.Available:
		f.Evidence = append(f.Evidence, "کنترل مستقل تازگی قیمت ممکن نشد — "+pc.Note)
		gaps = append(gaps, "تازگی قیمت (B1): کنترل مستقل از منبع قیمت ممکن نشد ("+pc.Note+") — هشدار «مشکوک» می‌ماند و ادعای «مانع اثبات‌شده» ندارد")
	case !pc.RowFound:
		f.Evidence = append(f.Evidence, "کنترل مستقل: "+pc.Note+" — ادعای «آخرین معامله» از منبع مستقل تأیید نمی‌شود؛ هشدار مشکوک می‌ماند")
		gaps = append(gaps, "تازگی قیمت (B1): منبع مستقل برای این شرکت در پنجره PIT ردیف قیمتی نیافت — اثبات یا رد نقض ممکن نیست")
	case pc.Violation != nil && *pc.Violation:
		f.Severity = sevProvenPolicy
		f.SeverityLabel = sevLabels[sevProvenPolicy]
		f.GateEffect = effectBlocked
		f.BlockingRule = ruleB1
		f.Reason = "قاعده B1 (اصلاح‌شده گام ۲-ط-۱): کنترل مستقل منبع واقعی قیمت، نقض سیاست تازگی ثبت‌شده در آرتیفکت را اثبات کرد — نقض سیاست مسدودسازی صریح است و از «خطای داده» جدا نگه داشته می‌شود"
		f.Evidence = append(f.Evidence,
			"کنترل مستقل از "+priceCheckSource,
			fmt.Sprintf("ردیف مستقل: security_id=%s، آخرین trade_date=%s (collected_at=%s) در پنجره PIT آرتیفکت — %s", pc.SecurityID, pc.LastTradeDate, pc.CollectedAt, priceCheckWindow),
			fmt.Sprintf("سن قیمت: %d روز تقویمی تا as_of %s در مقابل سیاست %d روز (منبع سیاست: construction.freshness_policy آرتیفکت V) — %d > %d: نقض سیاست اثبات می‌شود", *pc.AgeDays, pc.AsOfDate, *pc.PolicyDays, *pc.AgeDays, *pc.PolicyDays))
	case pc.Violation != nil && !*pc.Violation:
		f.Evidence = append(f.Evidence,
			"کنترل مستقل از "+priceCheckSource,
			fmt.Sprintf("ردیف مستقل: security_id=%s، آخرین trade_date=%s (collected_at=%s) — %s", pc.SecurityID, pc.LastTradeDate, pc.CollectedAt, priceCheckWindow),
			fmt.Sprintf("سن قیمت: %d روز تقویمی ≤ سیاست %d روز — ادعای متن هشدار در منبع مستقل بازتولید نشد؛ هشدار حفظ شد اما مانع اثبات‌شده نیست", *pc.AgeDays, *pc.PolicyDays))
	default:
		// ردیف یافت شد اما سیاست تازگی در آرتیفکت ثبت نشده — سنجش نقض ناممکن
		f.Evidence = append(f.Evidence,
			"کنترل مستقل از "+priceCheckSource,
			fmt.Sprintf("ردیف مستقل: security_id=%s، آخرین trade_date=%s (collected_at=%s)", pc.SecurityID, pc.LastTradeDate, pc.CollectedAt),
			"سیاست تازگی (construction.freshness_policy) در آرتیفکت ثبت نشده — سنجش نقض ممکن نیست؛ هشدار مشکوک می‌ماند و ادعای «مانع اثبات‌شده» ندارد")
		gaps = append(gaps, "تازگی قیمت (B1): خط‌مشی تازگی در آرتیفکت ثبت نشده است — حتی با ردیف مستقل منبع، سنجش نقض سیاست ناممکن است")
	}
	return f, gaps
}

// rgB2Scan قاعده B2: فاکتورِ امتیازگرفته‌ای که raw_status آن صراحتاً
// نامعتبر/قرنطینه‌شده باشد — یعنی داده اثبات‌شده بد داخل امتیاز. در آرتیفکت
// واقعی فعلی هیچ نمونه‌ای ندارد (بررسی شد) اما قاعده منتشر می‌ماند.
func rgB2Scan(qcm, vcm, tcm map[string]any) (bool, []string) {
	axes := []struct {
		name string
		cm   map[string]any
	}{{"Q", qcm}, {"V", vcm}, {"T", tcm}}
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
			if !included {
				continue
			}
			rs := qvtStr(f, "raw_status")
			if rs == "invalid" || strings.Contains(strings.ToLower(rs), "quarant") {
				return true, []string{
					fmt.Sprintf("فاکتور امتیازگرفته %s در محور %s با raw_status=%s — داده نامعتبر/قرنطینه‌شده در امتیاز استفاده شده است", id, ax.name, rs),
					"متن ثبت‌شده: " + firstNonEmpty(qvtStr(f, "not_included_reason"), "raw_status: "+rs),
				}
			}
		}
	}
	return false, nil
}

// rgPitGaps شکاف شواهد منشأ/زمانی هر محور را برمی‌گرداند — فقدان provenance
// خطا نیست اما بررسی را ناتمام می‌گذارد.
func rgPitGaps(axis string, cm map[string]any) []string {
	var gaps []string
	dcRaw, ok := cm["data_confidence"].(map[string]any)
	if !ok {
		return []string{fmt.Sprintf("محور %s: بلوک data_confidence در آرتیفکت ثبت نشده — تأیید زمانی منشأ این محور ممکن نیست", axis)}
	}
	pit, ok := dcRaw["pit_status_counts"].(map[string]any)
	if !ok {
		return []string{fmt.Sprintf("محور %s: شواهد ردیابی منبع (pit_status_counts) ثبت نشده — تأیید زمانی منشأ ممکن نیست", axis)}
	}
	keys := make([]string, 0, len(pit))
	for k := range pit {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		n, ok := pit[k].(float64)
		if !ok || n <= 0 {
			continue
		}
		if k == "unverified_no_publication_date" {
			gaps = append(gaps, fmt.Sprintf("محور %s: %.0f ورودی بدون تاریخ انتشار (unverified_no_publication_date) — تأیید زمانی منشأ ممکن نیست؛ شکاف شواهد است، نه خطای اثبات‌شده", axis, n))
		} else {
			gaps = append(gaps, fmt.Sprintf("محور %s: %.0f ورودی با وضعیت PIT «%s» — قابل تأیید نیست", axis, n, k))
		}
	}
	return gaps
}

// riskGateFor دروازه ریسک یک شرکت را از سه بلوک واقعی آرتیفکت ارزیابی می‌کند.
// فقط‌خواندنی؛ هر سه حوزه همیشه با آرایه‌های غیر-null سرو می‌شوند.
// cid برای وصل کردن حکم مستقل قیمت (قاعده B1) لازم است؛ px نگاشت
// company_id → نتیجه کنترل منبع قیمت است و می‌تواند nil باشد (کنترل انجام
// نشده → فقط شکاف شواهد، هیچ ادعای مانع).
func riskGateFor(cid string, qcm, vcm, tcm map[string]any, px map[string]*priceCheck) riskGateEval {
	axes := []struct {
		name      string
		cm        map[string]any
		listKey   string // فهرست هشداری که طبق قرارداد ثبت در این محور انتظار می‌رود
		pointsKey string
	}{
		{"Q", qcm, "financial_warnings", "q_observed_points"},
		{"V", vcm, "financial_warnings", "v_observed_points"},
		{"T", tcm, "trading_warnings", "t_observed_points"},
	}

	areas := map[string]*riskArea{}
	for _, k := range []string{areaData, areaFundamental, areaMarket} {
		areas[k] = &riskArea{
			Key: k, Title: rgAreaTitles[k],
			Findings: []riskFinding{}, EvidenceGaps: []string{}, Checks: rgAreaChecks[k],
		}
	}
	g := riskGateEval{
		Blockers: []riskFinding{}, ReviewFindings: []riskFinding{}, EvidenceGaps: []string{},
		WarningKinds: []string{},
	}

	evidences := collectWarnings(qcm, vcm, tcm)
	kindSet := map[string]bool{}
	staleGapAdded := false
	for _, e := range evidences {
		f, gaps := rgApplyB1(rgFindingFrom(e), e, px[cid])
		if a := areas[f.Area]; a != nil {
			a.Findings = append(a.Findings, f)
		}
		if f.GateEffect == effectBlocked {
			g.Blockers = append(g.Blockers, f)
		} else if f.GateEffect == effectReview {
			g.ReviewFindings = append(g.ReviewFindings, f)
		}
		if len(gaps) > 0 && !staleGapAdded {
			areas[areaData].EvidenceGaps = append(areas[areaData].EvidenceGaps, gaps...)
			staleGapAdded = true
		}
		kindSet[e.Kind] = true
	}
	for k := range kindSet {
		g.WarningKinds = append(g.WarningKinds, k)
	}
	sort.Strings(g.WarningKinds)

	// ── شکاف‌های شواهد (داده) ───────────────────────────────────────────
	dataGaps := areas[areaData]
	for _, ax := range axes {
		if ax.cm == nil {
			dataGaps.EvidenceGaps = append(dataGaps.EvidenceGaps,
				fmt.Sprintf("محور %s در آرتیفکت‌های موجود غایب است — بررسی‌های این محور ناتمام می‌ماند", ax.name))
			continue
		}
		if _, ok := qvtFloat(ax.cm, "coverage_ratio"); !ok {
			dataGaps.EvidenceGaps = append(dataGaps.EvidenceGaps,
				fmt.Sprintf("محور %s: فیلد پوشش ثبت نشده — بررسی پوشش ناتمام", ax.name))
		}
		if !warnListSeen(ax.cm, ax.listKey) {
			dataGaps.EvidenceGaps = append(dataGaps.EvidenceGaps,
				fmt.Sprintf("محور %s: فهرست هشدار %s ثبت نشده — اسکن هشدار این محور ناتمام است (نبود فهرست به معنی نبود هشدار نیست)", ax.name, ax.listKey))
		}
		dataGaps.EvidenceGaps = append(dataGaps.EvidenceGaps, rgPitGaps(ax.name, ax.cm)...)
	}
	// حوزه بازار هم اسکن فهرست معاملاتی T را لازم دارد
	if tcm != nil && !warnListSeen(tcm, "trading_warnings") {
		areas[areaMarket].EvidenceGaps = append(areas[areaMarket].EvidenceGaps,
			"محور T: فهرست هشدار معاملاتی ثبت نشده — اسکن ریسک بازار ناتمام است")
	}

	// ── قاعده B2 ────────────────────────────────────────────────────────
	if hit, ev := rgB2Scan(qcm, vcm, tcm); hit {
		b := riskFinding{
			Kind: "b2_invalid_raw_in_scored_factor", Axis: "Q/V/T", Area: areaData,
			Category: "داده نامعتبر/قرنطینه‌شده در امتیاز", Severity: sevProvenError,
			SeverityLabel: sevLabels[sevProvenError],
			Reason:        "قاعده B2: فاکتوری که در امتیاز استفاده شده raw_status نامعتبر/قرنطینه‌شده دارد — خطای داده اثبات‌شده",
			Evidence:      ev, GateEffect: effectBlocked, BlockingRule: ruleB2,
		}
		areas[areaData].Findings = append(areas[areaData].Findings, b)
		g.Blockers = append(g.Blockers, b)
	}

	// ── وضعیت هر حوزه: blocked > review_required > insufficient > clear ──
	areaStatus := func(a *riskArea) {
		review := false
		for _, f := range a.Findings {
			if f.GateEffect == effectBlocked {
				a.Status, a.StatusLabel = rgBlocked, rgStatusLabels[rgBlocked]
				return
			}
			if f.GateEffect == effectReview {
				review = true
			}
		}
		switch {
		case review:
			a.Status, a.StatusLabel = rgReview, rgStatusLabels[rgReview]
		case len(a.EvidenceGaps) > 0:
			a.Status, a.StatusLabel = rgInsuff, rgStatusLabels[rgInsuff]
		default:
			a.Status, a.StatusLabel = rgClear, rgStatusLabels[rgClear]
		}
	}
	for _, a := range areas {
		areaStatus(a)
	}

	g.Areas = []riskArea{*areas[areaData], *areas[areaFundamental], *areas[areaMarket]}
	for _, a := range g.Areas {
		g.EvidenceGaps = append(g.EvidenceGaps, a.EvidenceGaps...)
	}

	rank := map[string]int{rgClear: 0, rgInsuff: 1, rgReview: 2, rgBlocked: 3}
	worst := rgClear
	for _, a := range g.Areas {
		if rank[a.Status] > rank[worst] {
			worst = a.Status
		}
	}
	g.Status = worst
	g.StatusLabel = rgStatusLabels[worst]
	g.StatusNote = rgStatusNotes[worst]
	g.Note = "«بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن یا تأیید سرمایه‌گذاری نیست؛ ریسک اقتصادی واقعی الزاماً مسدودکننده نیست؛ Risk Gate فقط‌خواندنی است و هیچ امتیاز Q/V/T را تغییر نمی‌دهد."
	return g
}

// qvtRiskGateRules قرارداد منتشرشده دروازه ریسک — از خود UI قابل ممیزی است.
var qvtRiskGateRules = gin.H{
	"what_it_is": "دروازه ریسک فقط‌خواندنی روی شواهد ثبت‌شده در سه آرتیفکت؛ برای هر شرکت سه حوزه را مستقل ارزیابی می‌کند و وضعیت + یافته‌ها + شکاف شواهد را با نوع و شدت و دلیل و شواهد واقعی می‌دهد",
	"read_only":  "Risk Gate هیچ امتیاز Q/V/T را تغییر، ضرب یا بازنرمال نمی‌کند و در موتور امتیاز هیچ دخالتی ندارد",
	"statuses": gin.H{
		rgBlocked: "مانع معتبر و قابل اثبات طبق قاعده صریح — تنها با یکی از قواعد B1/B2",
		rgReview:  "ریسک یا هشدار مهم ثبت‌شده که بررسی می‌خواهد — تصمیم قطعی نیست",
		rgInsuff:  "شواهد برای تصمیم کافی نیست — به‌جای نتیجه‌گیری قطعی، شکاف‌ها فهرست می‌شوند",
		rgClear:   "در محدوده بررسی‌های انجام‌شده مانع اثبات‌شده‌ای یافت نشد — به معنی کم‌ریسک بودن یا تأیید سرمایه‌گذاری نیست",
	},
	"status_precedence": "blocked > review_required > insufficient_evidence > no_verified_blocker؛ این ترتیب هم در هر حوزه و هم در وضعیت کل اعمال می‌شود و یافته‌های بازبینی و شکاف شواهد حتی وقتی وضعیت بالاتری تعیین می‌کنند، همیشه نمایش داده می‌شوند",
	"areas": []gin.H{
		{"key": areaData, "title": rgAreaTitles[areaData], "covers": "داده مالی مشکوک یا قرنطینه‌شده، اعتبار قیمت تعدیل‌شده، سازگاری تعداد سهام و قیمت، فقدان provenance یا داده حیاتی، وضعیت محاسبات و مخرج‌ها"},
		{"key": areaFundamental, "title": rgAreaTitles[areaFundamental], "covers": "سوددهی منفی یا تبدیل سود به زیان، اهرم و پوشش بهره فقط با شواهد معتبر، نسبت‌های ارزندگی غیرعادی، محدودیت کیفیت سود"},
		{"key": areaMarket, "title": rgAreaTitles[areaMarket], "covers": "نقدشوندگی، پرش‌های مشکوک قیمت، داده‌های زمانی نامعتبر، محدودیت‌های فاکتورهای T"},
	},
	"blocking_rules": []gin.H{
		{"id": ruleB1, "rule": "stale_price ثبت‌شده که تنها با کنترل مستقل از منبع واقعی قیمت اثبات شود: آخرین ردیف قیمت security فعال شرکت (انتخاب مطابق موتور: is_primary سپس بیشترین ردیف قیمت) در پنجره PIT آرتیفکت (collected_at ≤ cutoff) از market.price_observations خوانده می‌شود؛ اگر سن تقویمی آن از سیاست تازگی آرتیفکت بیشتر باشد، نقض سیاست اثبات شده است", "evidence_required": "متن هشدار آرتیفکت + ردیف مستقل منبع (security_id، trade_date، collected_at) + سن محاسبه‌شده + سیاست خوانده‌شده از construction.freshness_policy آرتیفکت V", "policy_basis": "روز تقویمی — pilot_v2_value.py: price_age_days = (as_of − price_trade_date).days؛ این سرویس سیاست یا مبنا را تغییر نمی‌دهد", "note": "بازخوانی عدد از متن هشدار اثبات مستقل نیست (گام ۲-ط-۱): اگر منبع در دسترس نباشد، ردیفی نیابد، یا نقض بازتولید نشود، هشدار «مشکوک/نیازمند بررسی» می‌ماند و هرگز blocked صادر نمی‌شود؛ خطای قیمت، نقض سیاست تازگی و ریسک اقتصادی مستقل نگه داشته می‌شوند"},
		{"id": ruleB2, "rule": "فاکتورِ امتیازگرفته‌ای که raw_status آن نامعتبر یا قرنطینه‌شده باشد (داده اثبات‌شده بد داخل امتیاز)", "evidence_required": "raw_status فاکتور در آرتیفکت", "note": "در snapshot فعلی هیچ نمونه‌ای ندارد — قاعده برای آینده منتشر می‌شود"},
	},
	"price_verification": priceSourceMeta(true, ""),
	"never_blocks":              "ریسک اقتصادی (زیان‌دهی/تبدیل سود به زیان/سود عملیاتی منفی)، نسبت‌های ارزندگی خارج از بازه مرجع، سازگاری تعداد سهام با قیمت، و شکاف provenance هرگز به‌تنهایی blocked صادر نمی‌کنند؛ مانع سختی بدون دلیل معتبر و قاعده صریح صادر نمی‌شود",
	"evidence_gap_rule":         "فقدان provenance یا نبود فهرست هشدار خطا نیست اما بررسی را ناتمام می‌گذارد؛ در آن حوزه insufficient_evidence ثبت می‌شود و شکاف با متن دقیق فهرست می‌شود",
	"severity_vocabulary":       sevLabels,
	"warning_kind_map":          qvtWarnClassRows(),
	"unknown_warning_rule":      "هشدار ناشناخته دور ریخته نمی‌شود؛ با شدت «ناشناخته» و اثر «نیازمند بررسی» نمایش داده می‌شود و هیچ ادعای خطای قطعی درباره آن نمی‌شود",
	"snapshot_consistency_rule": "هم‌خوانی as_of/cutoff سه فایل یک بررسی سطح snapshot است و جداگانه در snapshot_consistency سرو می‌شود؛ به حساب اعتبار زمانی داده داخلی هیچ شرکتی نوشته نمی‌شود",
	"no_score_change":           "این ارزیابی فقط از هشدارها و متادیتای ثبت‌شده می‌خواند؛ هیچ امتیاز مشاهده‌شده، پوشش، واجدشرایطی یا ترتیبی ساخته یا تغییر نمی‌دهد",
}

// qvtWarnClassRows جدول طبقه‌بندی را برای JSON می‌سازد (مرتب و پایدار).
func qvtWarnClassRows() []gin.H {
	kinds := make([]string, 0, len(warnKindMap))
	for k := range warnKindMap {
		kinds = append(kinds, k)
	}
	sort.Strings(kinds)
	rows := make([]gin.H, 0, len(kinds))
	for _, k := range kinds {
		c := warnKindMap[k]
		rows = append(rows, gin.H{
			"kind": k, "area": c.Area, "category": c.Category,
			"severity": c.Severity, "severity_label": sevLabels[c.Severity],
			"effect": c.Effect, "dc_dimension": c.DCDim, "reason": c.Reason,
		})
	}
	return rows
}

// snapshotConsistencyOf بررسی سطح snapshot: هم‌خوانی تاریخ‌های سه فایل —
// جدا از اعتبار زمانی داده داخلی هر شرکت.
func snapshotConsistencyOf(b *qvtBundle) gin.H {
	_, _, problems := qvtCheckConsistency(b)
	return gin.H{
		"files": gin.H{
			"q": gin.H{"as_of": qvtStr(b.Q, "as_of"), "cutoff": qvtStr(b.Q, "cutoff"), "sha256": b.qSHA},
			"v": gin.H{"as_of": qvtStr(b.V, "as_of"), "cutoff": qvtStr(b.V, "cutoff"), "sha256": b.vSHA},
			"t": gin.H{"as_of": qvtStr(b.T, "as_of"), "cutoff": qvtStr(b.T, "cutoff"), "sha256": b.tSHA},
		},
		"consistent": len(problems) == 0,
		"problems":   problems,
		"note":       "این بررسی فقط هم‌خوانی تاریخ‌های snapshot سه فایل است (گیت ورودی endpoint) و از اعتبار زمانی داده داخلی هر شرکت جدا می‌شود؛ تازگی قیمت و سازگاری تعداد سهام هر شرکت در Risk Gate همان شرکت ارزیابی می‌شود، نه اینجا.",
	}
}
