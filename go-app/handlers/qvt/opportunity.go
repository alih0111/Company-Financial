package qvt

// ─────────────────────────────────────────────────────────────────────────────
// «فرصت‌های قابل بررسی بازار» (گام ۲-ک-۷ + ارتقای تصمیم‌محور ۲-ک-۸).
//
// هدف: کاربری که فرصت خواندن صدها نماد و هزاران ردیف مالی را ندارد، با باز
// کردن صفحه QVT در کمتر از یک دقیقه چند نامزد قابل‌دفاع برای «بررسی» پیدا
// کند، علت انتخاب و مهم‌ترین ریسک هرکدام را به زبان ساده ببیند و در صورت
// ناکافی بودن شواهد با نتیجهٔ ساختگی مواجه نشود.
//
// جایگاه: این موتور هیچ امتیاز جدیدی نمی‌سازد و هیچ فرمول/وزن رسمی Q/V/T را
// تغییر نمی‌دهد؛ فقط روی همان شواهدِ از پیش محاسبه‌شدهٔ همین snapshot
// (امتیازهای رسمی آرتیفکت، پوشش واقعی، Data Confidence، Risk Gate،
// همتایان معتبر discovery و کنترل مستقل تازگی قیمت) یک اولویت «نمایش» با
// قواعد ترتیبی صریح می‌سازد. ورودی یکسان → خروجی یکسان (بازتولیدپذیر).
//
// ارتقای ۲-ک-۸: «داشتن اطلاعات معتبر» با «جذاب بودن فرصت» یکی نیست. چهار
// موضوع مستقل ارزیابی می‌شود: (۱) کفایت/اعتبار شواهد — گیت‌های نسخهٔ قبل؛
// (۲) کیفیت واقعی کسب‌وکار (Q)؛ (۳) ارزندگی قابل دفاع نسبت به همتایان (V)؛
// (۴) شرایط ورود (T). آستانه‌های ارزیابی در سیاست نسخه‌دار و آشکار
// opportunity-decision-policy-v1 (opportunity_decision.go) منتشر می‌شوند و
// خروجی می‌تواند صفر نامزد جذاب داشته باشد.
//
// قواعد (نسخهٔ ۲ — همگی قابل تست، متن منتشرشده در qvtBoardRules):
//   D1 گیت‌های شواهد (لازم، نه کافی): هر سه امتیاز مشاهده‌شده + Risk Gate
//      غیر از blocked (review_required با دلیل نمایش داده می‌شود، نه مساوی
//      رد یا تأیید) + تازگی قیمت تأییدشده با کنترل مستقل.
//   D2 گروه‌های تصمیم:
//      «نامزدهای جذاب برای بررسی جدی» = گیت‌ها + گروه مقایسهٔ معتبر +
//      بنیادی غیرضعیف + ارزندگی قابل دفاع + ورود مناسب؛ در غیر این صورت
//      حتی با شواهد کامل جذاب اعلام نمی‌شود و «صفر نامزد» مجاز است.
//      «بنیادی مناسب، منتظر شرایط بهتر» = بنیادی غیرضعیف اما ارزندگی،
//      ورود، همتا یا تازگی مانع ارتقاست (شرط مشخص همراه است).
//      «ارزان به نظر می‌رسند، اما ریسک دارند» = ارزندگی ظاهری بالا همراه
//      با بنیادی ضعیف/شواهد ناکافی — value trap بالقوه.
//      «شواهد ناکافی یا دارای مانع» = Risk Gate=blocked یا امتیاز مفقود یا
//      بدون پروندهٔ قابل دفاع؛ هرگز در پیشنهاد اولیه نمی‌آید.
//   D3 قرائت ارزندگی: میانگین سادهٔ پرسنتایل عوامل P/E·P/B·P/S مشاهده‌شده
//      (فقط خوانش شفاف، نه امتیاز جدید)؛ «قابل دفاع» یعنی ارزان + گروه
//      همتای معتبر + تکیه بر چندگانه‌های سخت (P/E یا P/B)؛ زیان‌ده هرگز
//      ارزان قابل دفاع نیست.
//   D4 قرائت ورود: مومنتوم ۶ماههٔ نسبی (پرسنتایل) + نقدشوندگی مطلق واقعی
//      (کف سیاست)؛ مومنتوم مفقود یعنی ورود قابل قضاوت نیست.
//   D5 برای شرکت بدون گروه همتای معتبر: نتیجهٔ مبتنی بر شواهد مطلق جدا از
//      مقایسهٔ نسبی ارائه می‌شود؛ هیچ رتبهٔ نسبی و هیچ رتبه بین صنایع
//      ساخته نمی‌شود.
//   D6 ترتیب نمایش — کاملاً ترتیبی و بدون جمع/وزن: ۱) Risk Gate
//      (no_verified_blocker < review_required < insufficient_evidence)؛
//      ۲) اطمینان داده؛ ۳) لایه پارتو صعودی؛ ۴) سن قیمت؛ ۵-۷) Q سپس V
//      سپس T نزولی؛ ۸) نماد. گروه «ارزان‌نما» با میانگین پرسنتایل ارزندگی
//      نزولی نمایش داده می‌شود (ترتیب نمایش، نه رتبه). این «اولویت بررسی»
//      است، نه رتبهٔ بنیادی بین صنایع و نه امتیاز کل.
//   D7 حداکثر نامزد پیش‌فرض گروه جذاب: ۸ (داخل بازهٔ ۵–۱۰ مأموریت)؛ اگر
//      فقط ۲ نامزد قابل دفاع باشد همان ۲ نمایش داده می‌شود؛ اگر صفر باشد
//      صادقانه اعلام می‌شود.
//   D8 هیچ تعداد، نماد، صنعت یا آستانهٔ پنهانی hardcode نیست؛ آستانه‌ها
//      در decision_policy پاسخ منتشر می‌شوند.
//   D9 رشد سود تشخیصی (earnings_growth) و هر شاخص غیررسمی هرگز در «دلیل»
//      یا ترتیب نمی‌آید؛ فقط هشدار کیفی ثبت‌شدهٔ آن (در صورت وجود) در
//      «احتیاط» نمایش داده می‌شود. رشد درآمد رسمی (revenue_growth) فقط با
//      عدد خودش و به‌عنوان شاهد بنیادی می‌آید.
//   D10 مقدار مفقود هرگز صفر فرض یا بازتوزیع نمی‌شود.
//   D11 مقایسهٔ ارزندگی فقط درون گروه مقایسه‌پذیر معتبر «قابل دفاع» است.
// ─────────────────────────────────────────────────────────────────────────────

import (
	"fmt"
	"sort"
	"strings"

	"github.com/gin-gonic/gin"
)

const (
	boardGroupAttractive = "attractive_candidates"
	boardGroupWaiting    = "fundamentals_waiting"
	boardGroupCheapRisk  = "apparent_value_risk"
	boardGroupBlocked    = "blocked_or_insufficient"

	// boardDefaultVisible حداکثر نامزد پیش‌فرض گروه «جذاب» —
	// در بازهٔ ۵ تا ۱۰ مأموریت؛ در UI قابل گسترش به همهٔ گروه است.
	boardDefaultVisible = 8
)

// کدهای «چرا در گروه جذاب نیست» — پایدار و قابل تست؛ شمارش آن‌ها در
// counts.not_in_attractive_reasons منتشر می‌شود (برای هر شرکت فقط مانع اصلی).
const (
	boardExOk             = "ok"
	boardExRiskBlocked    = "risk_gate_blocked"
	boardExMissingScore   = "missing_scores"
	boardExWeakNoCase     = "weak_no_case"
	boardExApparentValue  = "apparent_value_weak_fundamentals"
	boardExSmallGroup     = "small_group"
	boardExFreshness      = "price_freshness_unverified"
	boardExDecisionValue  = "decision_value_not_defensible"
	boardExDecisionEntry  = "decision_entry_not_ok"
	boardExConditional    = "conditional_quality_caveat"
)

type boardAxisStatus struct {
	Points        *float64 `json:"points"`
	Max           float64  `json:"max"`
	CoveredWeight *float64 `json:"covered_weight"`
	CoverageRatio *float64 `json:"coverage_ratio"`
	NScored       int      `json:"n_scored_factors"`
	NIssues       int      `json:"n_factor_issues"`
	Status        string   `json:"status"` // computed | missing
}

type boardEntry struct {
	CompanyID   string   `json:"company_id"`
	Symbol      string   `json:"symbol"`
	Industry    string   `json:"industry"`
	ModelFamily string   `json:"model_family"`
	Group       string   `json:"group"`
	Conclusion  string   `json:"conclusion"`
	GroupReason string   `json:"group_reason"`
	TopReason   string   `json:"top_reason"`
	TopRisk     string   `json:"top_risk"`
	Why         []string `json:"why"`
	Careful     []string `json:"careful"`
	ReviewWhen  []string `json:"review_when"`

	Q boardAxisStatus `json:"q"`
	V boardAxisStatus `json:"v"`
	T boardAxisStatus `json:"t"`

	// لایهٔ تصمیم ۲-ک-۸ — همهٔ اعداد از آرتیفکت همان snapshot
	Fundamental      string   `json:"fundamental"`
	FundamentalLabel string   `json:"fundamental_label"`
	FundamentalNote  []string `json:"fundamental_note"`
	RoePct           *float64 `json:"roe_pct"`
	MarginPct        *float64 `json:"margin_pct"`
	LevPct           *float64 `json:"leverage_pct"`
	IcPct            *float64 `json:"interest_coverage_pct"`
	CashConversionPct *float64 `json:"cash_conversion_pct"`
	ValueMean        *float64 `json:"value_mean"`
	ValueLabel       string   `json:"value_label"`
	ValueCheap       bool     `json:"value_cheap"`
	ValueDefensible  bool     `json:"value_defensible"`
	ValueNote        []string `json:"value_note"`
	ValueBasisNote   string   `json:"value_basis_note,omitempty"`
	Entry            string   `json:"entry"`
	EntryLabel       string   `json:"entry_label"`
	EntryNote        []string `json:"entry_note"`
	// گام ۲-ک-۹ — قید کیفیت: شرکت واجد گیت‌ها اما با ضعف بنیادی پنهان‌شده
	// (تبدیل نقد ضعیف / سود عملیاتی منفی) هرگز «جذاب بدون قید» نمی‌شود.
	Conditional          bool     `json:"conditional"`
	ConditionalReasons   []string `json:"conditional_reasons"`
	NegativeOperatingProfit bool  `json:"negative_operating_profit"`

	ParetoLayer *int   `json:"pareto_layer,omitempty"`
	GroupSize   int    `json:"group_size"`
	GroupLabel  string `json:"group_label"`

	RiskGateStatus    string `json:"risk_gate_status"`
	RiskGateLabel     string `json:"risk_gate_label"`
	ConfidenceOverall string `json:"confidence_overall"`
	ConfidenceLabel   string `json:"confidence_label"`

	PriceFreshness   *priceCheck `json:"price_freshness"`
	FreshnessLabel   string      `json:"freshness_label"`
	ValidationStatus string      `json:"validation_status,omitempty"`
	ValidationLabel  string      `json:"validation_status_label,omitempty"`

	DisplayRank int `json:"display_rank"`
}

// رتبه‌های ترتیبی — فقط برای مقایسهٔ وضعیت‌ها، نه ساخت امتیاز.
var boardRiskRank = map[string]int{rgClear: 0, rgReview: 1, rgInsuff: 2, rgBlocked: 3}

// review_required قبل از insufficient_evidence: یافتهٔ ثبت‌شده برای بررسی
// شواهدِ موجود است؛ ناتمام ماندن بررسی‌ها جایگاه شواهد را ضعیف‌تر می‌کند.
var boardConfRank = map[string]int{"no_findings_recorded": 0, "findings": 1, "not_evaluable": 2}

var boardSevRank = map[string]int{
	sevUnknown: 0, sevProvenance: 1, sevMarketStruct: 2, sevValuationBand: 3,
	sevConsistency: 4, sevEconomic: 5, sevSuspect: 6, sevProvenError: 7, sevProvenPolicy: 8,
}

type boardInput struct {
	companies []*discCompany
	balanced  discModeResult
	px        map[string]*priceCheck
	overlays  []qvtOverlayDoc
	asOf      string
	// آرتیفکت‌های خام سه محور — لایهٔ تصمیم پرسنتایل/raw عوامل را از همین‌ها
	// می‌خواند؛ هیچ منبع دیگری وارد نمی‌شود.
	qc, vc, tc map[string]any
	policy     boardDecisionPolicy
}

// boardFreshnessVerified تنها تعریف مجاز «تأیید تازگی قیمت»: منبع مستقل
// پاسخ داده، ردیف یافت شده و نقض سیاست اثبات نشده باشد.
func boardFreshnessVerified(pc *priceCheck) bool {
	return pc != nil && pc.Available && pc.RowFound &&
		pc.Violation != nil && !*pc.Violation
}

func boardFreshnessLabel(pc *priceCheck) string {
	switch {
	case pc == nil:
		return "تازگی قیمت کنترل مستقل نشد"
	case !pc.Available:
		return "تازگی قیمت کنترل مستقل نشد — منبع در دسترس نبود"
	case !pc.RowFound:
		return "ردیف قیمت مستقل در پنجره PIT یافت نشد"
	case pc.Violation == nil:
		return "سیاست تازگی در آرتیفکت ثبت نشده — سنجش نقض ممکن نیست"
	case *pc.Violation:
		return fmt.Sprintf("نقض سیاست تازگی اثبات شد — سن قیمت %d روز > سیاست %d روز", *pc.AgeDays, *pc.PolicyDays)
	default:
		return fmt.Sprintf("تازگی قیمت تأیید شد — %d روز ≤ سیاست %d روز", *pc.AgeDays, *pc.PolicyDays)
	}
}

func boardAxisFrom(a discAxis, max float64) boardAxisStatus {
	st := boardAxisStatus{
		Points: a.Points, Max: max,
		CoveredWeight: a.CoveredWeight, CoverageRatio: a.CoverageRatio,
		NScored: len(a.ScoredFactors), NIssues: len(a.FactorIssues),
		Status: "computed",
	}
	if a.Points == nil {
		st.Status = "missing"
	}
	return st
}

func boardCoverPct(s boardAxisStatus) string {
	if s.CoverageRatio != nil {
		return fmt.Sprintf("%.0f", *s.CoverageRatio*100)
	}
	if s.CoveredWeight != nil && s.Max > 0 {
		return fmt.Sprintf("%.0f", *s.CoveredWeight/s.Max*100)
	}
	return ""
}

// boardWhyReasons دلایل «چرا این نماد؟» — حداکثر ۳، هرکدام با عدد قابل
// ردیابی از آرتیفکت؛ هیچ عبارت کلی بدون شواهد.
func boardWhyReasons(e *boardEntry) []string {
	var out []string
	qp := ""
	if c := boardCoverPct(e.Q); c != "" {
		qp = fmt.Sprintf("، پوشش Q %s%%", c)
	}
	out = append(out, fmt.Sprintf(
		"بنیادی (%s): پرسنتایل roe_level=%s، پرسنتایل حاشیهٔ سود=%s، پرسنتایل اهرم=%s، پرسنتایل پوشش بهره=%s%s",
		e.FundamentalLabel, boardPctOf(e.RoePct), boardPctOf(e.MarginPct),
		boardPctOf(e.LevPct), boardPctOf(e.IcPct), qp))
	if e.ValueMean != nil {
		line := fmt.Sprintf("ارزندگی: میانگین پرسنتایل P/E·P/B·P/S = %s (%s)", fmtScore(e.ValueMean), e.ValueLabel)
		if e.ValueDefensible && e.GroupSize > 0 {
			line += fmt.Sprintf(" — قابل دفاع در گروه مقایسهٔ %d همتای هم‌صنعت", e.GroupSize)
		}
		out = append(out, line)
	}
	if len(e.EntryNote) > 0 {
		out = append(out, "ورود: "+strings.Join(e.EntryNote, "؛ "))
	}
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

// boardPctOf پرسنتایل را با برچسب صادقانهٔ مفقود برمی‌گرداند.
func boardPctOf(p *float64) string {
	if p == nil {
		return "مفقود"
	}
	return fmt.Sprintf("%.2f", *p)
}

// mapOfAny ادعای نوع امن برای نقشهٔ شرکت‌های آرتیفکت.
func mapOfAny(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

// boardWorstReviewFindings یک یافتهٔ نیازمند بررسی با بالاترین شدت ثبت‌شده.
func boardWorstReviewFinding(g riskGateEval) *riskFinding {
	var worst *riskFinding
	for i := range g.ReviewFindings {
		f := &g.ReviewFindings[i]
		if worst == nil || boardSevRank[f.Severity] > boardSevRank[worst.Severity] {
			worst = f
		}
	}
	return worst
}

// boardCarefulReasons «چرا ممکن است انتخاب خوبی نباشد؟» — حداکثر ۳، فقط از
// یافته‌ها و اعداد ثبت‌شده؛ ترتیب: مانع > یافتهٔ بررسی > هشدار جدی داده >
// ضعف بنیادی عددی > مبنای سرمایه/قیمت > پوشش ناقص > هشدار کیفی رشد سود >
// تازگی.
func boardCarefulReasons(e *boardEntry, dc *discCompany, ovc gin.H, pol boardDecisionPolicy) []string {
	var out []string
	// قید کیفیت اقتصادی (گام ۲-ک-۹) اول می‌آید: مهم‌ترین چیزی که کاربر باید
	// دربارهٔ «جذاب‌نبودن بدون قید» این شرکت بداند.
	for _, c := range e.ConditionalReasons {
		out = append(out, "قید کیفیت: "+c)
	}
	if len(dc.RiskGate.Blockers) > 0 {
		b := dc.RiskGate.Blockers[0]
		rule := b.BlockingRule
		if rule == "" {
			rule = "—"
		}
		out = append(out, fmt.Sprintf("مانع اثبات‌شده (قاعده %s، %s): %s", rule, b.SeverityLabel, b.Reason))
	}
	if f := boardWorstReviewFinding(dc.RiskGate); f != nil {
		out = append(out, fmt.Sprintf("«%s» — %s: %s", f.Kind, f.SeverityLabel, f.Reason))
	}
	if len(dc.Confidence.SeriousWarnings) > 0 {
		out = append(out, "هشدار جدی دادهٔ ثبت‌شده: "+dc.Confidence.SeriousWarnings[0])
	}
	for _, ax := range []struct {
		name string
		s    boardAxisStatus
	}{{"Q", e.Q}, {"V", e.V}, {"T", e.T}} {
		if ax.s.CoverageRatio != nil && *ax.s.CoverageRatio < 1.0 {
			out = append(out, fmt.Sprintf("پوشش %s کامل نیست: %s%% از وزن %.0f — وزن مفقود بازتوزیع نشده و مفقود صفر فرض نشده است",
				ax.name, boardCoverPct(ax.s), ax.s.Max))
			break
		}
	}
	if e.Fundamental != boardFundInsufficient {
		for _, pair := range []struct {
			name string
			p    *float64
		}{{"margins", e.MarginPct}, {"leverage", e.LevPct}, {"interest_coverage", e.IcPct}, {"roe_level", e.RoePct}} {
			if pair.p != nil && *pair.p < pol.QWeakFactor {
				out = append(out, fmt.Sprintf("نقطهٔ ضعف عددی بنیادی: پرسنتایل %s = %s زیر آستانهٔ ضعف %.2f", pair.name, fmtScore(pair.p), pol.QWeakFactor))
				break
			}
		}
	}
	if e.ValueBasisNote != "" {
		out = append(out, "مبنای ارزندگی: "+e.ValueBasisNote)
	}
	if e.Group == boardGroupWaiting && strings.Contains(e.GroupReason, "تازگی") {
		out = append(out, e.FreshnessLabel+" — تا کنترل تازگی، قضاوت دربارهٔ «الان» محدود است")
	}
	if w := boardEgCaution(ovc); w != "" {
		out = append(out, w)
	}
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

// boardEgCaution هشدار کیفی ممیزی مستقل رشد سود (۲-ک-۶) را — فقط به‌عنوان
// احتیاط و فقط در صورت ثبت‌شده بودن — برمی‌گرداند؛ رشد هرگز دلیل جذابیت
// نمی‌شود (D9).
func boardEgCaution(ovc gin.H) string {
	eg, ok := ovc["eg_economic_audit"].(map[string]any)
	if !ok {
		return ""
	}
	ws, _ := eg["warnings"].([]any)
	if len(ws) == 0 {
		return ""
	}
	w, _ := ws[0].(string)
	if w == "" {
		return ""
	}
	return "ممیزی رشد سود (تشخیصی، خارج از امتیاز رسمی): " + w
}

// boardReviewWhen «چه زمانی ارزش بررسی مجدد دارد؟» — شرایط پایش سنجش‌پذیر،
// نه پیش‌بینی قیمت و نه دستور خرید؛ هر شرط به یک مانع مشخص با عدد فعلی وصل است.
func boardReviewWhen(e *boardEntry, dc *discCompany, pol boardDecisionPolicy, asOf string) []string {
	out := []string{}
	add := func(format string, a ...any) {
		out = append(out, fmt.Sprintf(format, a...))
	}
	if e.Group == boardGroupAttractive {
		add("مانیتور نسبت به همتایان: خروج میانگین پرسنتایل P/E·P/B·P/S از آستانهٔ %.2f یا افت پرسنتایل roe_level زیر %.2f ⇒ بازبینی نامزد", pol.VCheap, pol.QWeakRoe)
	}
	if e.Conditional {
		add("رفع قید کیفیت ثبت‌شده در snapshot بعدی: پرسنتایل cash_conversion به ≥%.2f (فعلاً %s) و رفع سود عملیاتی منفی — تا آن زمان «مشروط» می‌ماند و جذاب بدون قید اعلام نمی‌شود",
			pol.QCashMin, boardPctOf(e.CashConversionPct))
	}
	if dc.RiskGate.Status == rgBlocked && len(dc.RiskGate.Blockers) > 0 {
		add("رفع مستند مانع دروازه ریسک (قاعده %s) — تا آن زمان خارج از پیشنهاد اولیه می‌ماند", firstNonEmpty(dc.RiskGate.Blockers[0].BlockingRule, "—"))
	}
	if e.Fundamental == boardFundWeak {
		add("بهبود پرسنتایل roe_level به ≥%.2f و رفع هشدارهای کیفی سود (فعلاً: %s)", pol.QWeakRoe, boardPctOf(e.RoePct))
	}
	if e.Fundamental == boardFundInsufficient {
		add("تکمیل شواهد بنیادی در snapshot بعدی (roe_level یا margins مشاهده‌شده) — فعلاً ارزیابی ممکن نیست")
	}
	if e.Fundamental != boardFundWeak && e.Fundamental != boardFundInsufficient && !e.ValueDefensible {
		add("رسیدن میانگین پرسنتایل P/E·P/B·P/S به ≥%.2f در snapshot بعدی (فعلاً: %s — %s)", pol.VCheap, fmtScore(e.ValueMean), e.ValueLabel)
	}
	if e.GroupSize > 0 && e.GroupSize < 5 {
		add("تشکیل گروه مقایسهٔ درون‌صنعت با ≥۵ همتا در snapshot بعدی (فعلاً %d عضو در «%s») تا ارزندگی نسبی قابل تأیید شود", e.GroupSize, e.Industry)
	}
	if e.Entry != boardEntryOK {
		add("بازگشت شرایط ورود به آستانه: پرسنتایل مومنتوم ۶ماههٔ نسبی ≥%.2f و نقدشوندگی بالای کف سیاست (فعلاً: %s)", pol.TMomentumOK, e.EntryLabel)
	}
	if e.PriceFreshness == nil || !boardFreshnessVerified(e.PriceFreshness) {
		add("تأیید تازگی قیمت در کنترل مستقل (سیاست %s روز) — تا آن زمان نامزد فرصت «الان» نمی‌شود", freshnessPolicyDays(e))
	}
	add("پایش گزارش‌های فصلی بعد برای تداوم شواهد همین snapshot (%s)", asOf)
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

func freshnessPolicyDays(e *boardEntry) string {
	if e.PriceFreshness != nil && e.PriceFreshness.PolicyDays != nil {
		return fmt.Sprintf("%d", *e.PriceFreshness.PolicyDays)
	}
	return "؟"
}

// boardLessPriority مقایسهٔ ترتیبی گروه «جذاب» — دقیقاً طبق D6.
func boardLessPriority(a, b *boardEntry) bool {
	if ra, rb := boardRiskRank[a.RiskGateStatus], boardRiskRank[b.RiskGateStatus]; ra != rb {
		return ra < rb
	}
	if ca, cb := boardConfRank[a.ConfidenceOverall], boardConfRank[b.ConfidenceOverall]; ca != cb {
		return ca < cb
	}
	if a.ParetoLayer != nil && b.ParetoLayer != nil && *a.ParetoLayer != *b.ParetoLayer {
		return *a.ParetoLayer < *b.ParetoLayer
	}
	if (a.ParetoLayer == nil) != (b.ParetoLayer == nil) {
		return b.ParetoLayer == nil // دارای لایه قبل از بدون‌لایه
	}
	if a.PriceFreshness != nil && b.PriceFreshness != nil &&
		a.PriceFreshness.AgeDays != nil && b.PriceFreshness.AgeDays != nil &&
		*a.PriceFreshness.AgeDays != *b.PriceFreshness.AgeDays {
		return *a.PriceFreshness.AgeDays < *b.PriceFreshness.AgeDays
	}
	for _, pair := range []struct{ x, y *float64 }{{a.Q.Points, b.Q.Points}, {a.V.Points, b.V.Points}, {a.T.Points, b.T.Points}} {
		if pair.x != nil && pair.y != nil && *pair.x != *pair.y {
			return *pair.x > *pair.y
		}
	}
	if a.Symbol != b.Symbol {
		return a.Symbol < b.Symbol
	}
	return a.CompanyID < b.CompanyID
}

// boardLessWaiting ترتیب گروه «منتظر شرایط بهتر» — همان زنجیرهٔ D6 با یک
// کلید اضافه: بنیادی قوی قبل از قابل‌قبول (ترتیب نمایش، نه رتبه).
func boardLessWaiting(a, b *boardEntry) bool {
	if fa, fb := boardFundRank(a.Fundamental), boardFundRank(b.Fundamental); fa != fb {
		return fa < fb
	}
	return boardLessPriority(a, b)
}

func boardFundRank(f string) int {
	switch f {
	case boardFundStrong:
		return 0
	case boardFundAcceptable:
		return 1
	default:
		return 2
	}
}

// buildOpportunityBoard موتور انتخاب را روی ورودی‌های discovery اجرا می‌کند.
// خالص است: هیچ فایل یا DB اضافه‌ای نمی‌خواند و هیچ ورودی را تغییر نمی‌دهد.
func buildOpportunityBoard(in boardInput) gin.H {
	rows := map[string]discModeRow{}
	for _, r := range in.balanced.Rows {
		rows[r.CompanyID] = r
	}
	ovcCache := map[string]gin.H{}
	ovcFor := func(cid string) gin.H {
		if v, ok := ovcCache[cid]; ok {
			return v
		}
		v := overlayForCompany(in.overlays, cid)
		ovcCache[cid] = v
		return v
	}

	entries := map[string][]*boardEntry{}
	notAttractive := map[string]int{}
	for _, code := range []string{boardExOk, boardExRiskBlocked, boardExMissingScore, boardExWeakNoCase,
		boardExApparentValue, boardExSmallGroup, boardExFreshness, boardExDecisionValue, boardExDecisionEntry,
		boardExConditional} {
		notAttractive[code] = 0
	}
	blockedBreakdown := map[string]int{"risk_gate_blocked": 0, "missing_scores": 0, "no_defensible_case": 0}
	conclusion := map[string]string{
		boardGroupAttractive: "نامزد جذاب برای بررسی جدی",
		boardGroupWaiting:    "بنیادی مناسب — منتظر شرایط بهتر",
		boardGroupCheapRisk:  "ارزان‌نما — نیازمند احتیاط جدی",
		boardGroupBlocked:    "شواهد ناکافی یا دارای مانع",
	}

	for _, dc := range in.companies {
		e := &boardEntry{
			CompanyID: dc.CompanyID, Symbol: dc.Symbol,
			Industry: dc.Industry, ModelFamily: dc.ModelFamily,
			Q: boardAxisFrom(dc.Q, 40), V: boardAxisFrom(dc.V, 35), T: boardAxisFrom(dc.T, 25),
			RiskGateStatus:    dc.RiskGate.Status,
			RiskGateLabel:     dc.RiskGate.StatusLabel,
			ConfidenceOverall: dc.Confidence.Overall,
			ConfidenceLabel:   dc.Confidence.OverallLabel,
		}
		ovc := ovcFor(dc.CompanyID)
		if iv, ok := ovc["independent_validation"].(map[string]any); ok {
			e.ValidationStatus, _ = iv["status"].(string)
			e.ValidationLabel, _ = iv["status_label"].(string)
		}

		missingAxis := ""
		for _, ax := range []struct {
			name string
			s    boardAxisStatus
		}{{"Q", e.Q}, {"V", e.V}, {"T", e.T}} {
			if ax.s.Status == "missing" {
				missingAxis = ax.name
				break
			}
		}

		pc := in.px[dc.CompanyID]
		e.PriceFreshness = pc
		e.FreshnessLabel = boardFreshnessLabel(pc)
		row := rows[dc.CompanyID]
		comparableValid := row.Comparability == "comparable" && row.GroupValid
		freshOK := boardFreshnessVerified(pc)

		// لایهٔ تصمیم اقتصادی — مستقل از گیت‌ها محاسبه می‌شود تا شرکت‌های
		// بدون گروه همتا هم قرائت مطلق داشته باشند (D5)
		d := boardDecide(in.policy,
			mapOfAny(in.qc[dc.CompanyID]), mapOfAny(in.vc[dc.CompanyID]), mapOfAny(in.tc[dc.CompanyID]),
			comparableValid, freshOK)
		e.Fundamental, e.FundamentalLabel = d.Fundamental, d.FundamentalLabel
		e.FundamentalNote = d.FundamentalNote
		e.RoePct, e.MarginPct, e.LevPct, e.IcPct = d.RoePct, d.MarginPct, d.LevPct, d.IcPct
		e.CashConversionPct = d.CashConversionPct
		e.Conditional, e.ConditionalReasons = d.Conditional, d.ConditionalReasons
		e.NegativeOperatingProfit = d.NegOperatingProfit
		e.ValueMean, e.ValueLabel, e.ValueCheap, e.ValueDefensible = d.ValueMean, d.ValueLabel, d.ValueCheap, d.ValueDefensible
		e.ValueNote, e.ValueBasisNote = d.ValueNote, d.ValueBasisNote
		e.Entry, e.EntryLabel, e.EntryNote = d.Entry, d.EntryLabel, d.EntryNote

		var exCode string
		switch {
		case dc.RiskGate.Status == rgBlocked:
			exCode = boardExRiskBlocked
			e.Group = boardGroupBlocked
			b := "مانع اثبات‌شده در دروازه ریسک"
			if len(dc.RiskGate.Blockers) > 0 {
				b = "مانع اثبات‌شده (قاعده " + dc.RiskGate.Blockers[0].BlockingRule + "): " + dc.RiskGate.Blockers[0].SeverityLabel
			}
			e.GroupReason = "خارج از پیشنهاد اولیه — " + b + ". دلیل کامل در دروازه ریسک شرکت آمده است؛ رفع آن باید مستند باشد."
		case missingAxis != "":
			exCode = boardExMissingScore
			e.Group = boardGroupBlocked
			e.GroupReason = fmt.Sprintf("خارج از پیشنهاد اولیه — امتیاز مشاهده‌شدهٔ محور %s در دسترس نیست؛ هیچ مقدار جایگزینی ساخته نمی‌شود و شواهد برای قضاوت کافی نیست", missingAxis)
		case e.Fundamental == boardFundWeak || e.Fundamental == boardFundInsufficient:
			if d.ValueCheap {
				exCode = boardExApparentValue
				e.Group = boardGroupCheapRisk
				e.GroupReason = fmt.Sprintf("ارزان‌نما: میانگین پرسنتایل ارزندگی %s اما بنیادی %s (%s) — ارزندگی ظاهری ممکن است محصول ضعف بنیادی باشد؛ خارج از پیشنهاد اولیه",
					fmtScore(d.ValueMean), e.FundamentalLabel, lastNote(d.FundamentalNote))
			} else {
				exCode = boardExWeakNoCase
				e.Group = boardGroupBlocked
				e.GroupReason = fmt.Sprintf("خارج از پیشنهاد اولیه — بدون پروندهٔ قابل دفاع: بنیادی %s (%s) و ارزندگی ارزان نسبی نیست (میانگین پرسنتایل %s، آستانهٔ %.2f)",
					e.FundamentalLabel, lastNote(d.FundamentalNote), fmtScore(d.ValueMean), in.policy.VCheap)
			}
		case !comparableValid:
			exCode = boardExSmallGroup
			e.Group = boardGroupWaiting
			size := row.GroupSize
			if size == 0 {
				size = 1
			}
			e.GroupSize = size
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			e.GroupReason = fmt.Sprintf("بنیادی %s اما گروه مقایسهٔ درون‌صنعت «%s» فقط %d عضو دارد (حداقل ۵ همتا لازم است) — قرائت مطلق: roe پرسنتایل %s، ارزندگی خانواده %s؛ رتبهٔ نسبی صنعت صادر نمی‌شود",
				e.FundamentalLabel, dc.Industry, size,
				boardPctOf(d.RoePct), fmtScore(d.ValueMean))
		case !freshOK:
			exCode = boardExFreshness
			e.Group = boardGroupWaiting
			e.GroupSize = row.GroupSize
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			e.GroupReason = fmt.Sprintf("بنیادی %s اما تازگی قیمت تأیید نشده (%s) — تا تأیید تازگی، نامزد فرصت «الان» نمی‌شود",
				e.FundamentalLabel, e.FreshnessLabel)
		case !d.ValueDefensible:
			exCode = boardExDecisionValue
			e.Group = boardGroupWaiting
			e.GroupSize = row.GroupSize
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			note := fmt.Sprintf("بنیادی %s اما ارزندگی قابل دفاع نیست: میانگین پرسنتایل P/E·P/B·P/S = %s (آستانهٔ %.2f — %s)",
				e.FundamentalLabel, fmtScore(d.ValueMean), in.policy.VCheap, d.ValueLabel)
			if d.ValueCheap {
				note += "؛ ارزان است اما تکیهٔ چندگانه‌های سخت (P/E یا P/B) یا گروه همتا کافی نیست"
			}
			e.GroupReason = note + " — منتظر شرایط بهتر"
		case d.Entry != boardEntryOK:
			exCode = boardExDecisionEntry
			e.Group = boardGroupWaiting
			e.GroupSize = row.GroupSize
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			e.GroupReason = fmt.Sprintf("بنیادی %s و ارزندگی %s اما شرایط ورود %s (پرسنتایل مومنتوم ۶ماههٔ نسبی زیر آستانهٔ %.2f) — منتظر بهبود ورود",
				e.FundamentalLabel, d.ValueLabel, e.EntryLabel, in.policy.TMomentumOK)
		case d.Conditional:
			// گام ۲-ک-۹: گیت‌ها و ارزندگی و ورود همه پاس شده‌اند، اما قید کیفیت
			// اقتصادی ثبت شده — «جذاب بدون قید» نمی‌شود و به گروه «مشروط/منتظر»
			// می‌رود؛ قید دقیقاً همان‌هایی است که در «احتیاط» و «بازبینی» می‌آید.
			exCode = boardExConditional
			e.Group = boardGroupWaiting
			e.GroupSize = row.GroupSize
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			reason := "نامزد مشروط برای بررسی: بنیادی " + e.FundamentalLabel +
				"، ارزندگی قابل دفاع، ورود مناسب — اما قید کیفیت اقتصادی ثبت شده و «جذاب بدون قید» اعلام نمی‌شود: " +
				strings.Join(d.ConditionalReasons, "؛ ")
			e.GroupReason = reason + " — منتظر رفع قید در snapshot بعدی"
		default:
			exCode = boardExOk
			e.Group = boardGroupAttractive
			e.GroupSize = row.GroupSize
			e.GroupLabel = row.GroupLabel
			e.ParetoLayer = row.ParetoLayer
			e.GroupReason = fmt.Sprintf("نامزد جذاب برای بررسی جدی: بنیادی %s (پرسنتایل roe_level %s)، ارزندگی قابل دفاع در گروه مقایسهٔ %d همتا (میانگین پرسنتایل %s)، شرایط ورود مناسب — همهٔ آستانه‌های اعلامی سیاست تصمیم %s پاس شد، مانع اثبات‌شده‌ای ثبت نیست و قید کیفیت اختصاصی وجود ندارد. توجه: قیدهای جهانی همین snapshot (وضعیت دروازه ریسک، مبنای سهام↔قیمت، پرووننس) برای این نامزد هم منتشر شده و «بدون قید اختصاصی» به معنای بی‌ریسک بودن نیست",
				e.FundamentalLabel, boardPctOf(d.RoePct), row.GroupSize, fmtScore(d.ValueMean), in.policy.Version)
		}
		if e.Group == boardGroupAttractive {
			notAttractive[boardExOk]++
		} else {
			notAttractive[exCode]++
		}
		if e.Group == boardGroupBlocked {
			switch {
			case dc.RiskGate.Status == rgBlocked:
				blockedBreakdown["risk_gate_blocked"]++
			case missingAxis != "":
				blockedBreakdown["missing_scores"]++
			default:
				blockedBreakdown["no_defensible_case"]++
			}
		}

		e.Conclusion = conclusion[e.Group]
		if e.Group != boardGroupBlocked {
			e.Why = boardWhyReasons(e)
		} else {
			e.Why = []string{}
		}
		e.Careful = boardCarefulReasons(e, dc, ovc, in.policy)
		e.ReviewWhen = boardReviewWhen(e, dc, in.policy, in.asOf)
		if len(e.Careful) > 0 {
			e.TopRisk = e.Careful[0]
		}
		if len(e.Why) > 0 {
			e.TopReason = e.Why[0]
		}
		entries[e.Group] = append(entries[e.Group], e)
	}

	// گروه‌های خالی هرگز nil سرو نمی‌شوند — آرایهٔ خالی صادقانه، نه null
	ensure := func(k string) []*boardEntry {
		if entries[k] == nil {
			return []*boardEntry{}
		}
		return entries[k]
	}
	attractive := ensure(boardGroupAttractive)
	sort.SliceStable(attractive, func(i, j int) bool { return boardLessPriority(attractive[i], attractive[j]) })
	for i, e := range attractive {
		e.DisplayRank = i + 1
	}
	waiting := ensure(boardGroupWaiting)
	sort.SliceStable(waiting, func(i, j int) bool { return boardLessWaiting(waiting[i], waiting[j]) })
	cheapRisk := ensure(boardGroupCheapRisk)
	sort.SliceStable(cheapRisk, func(i, j int) bool {
		// ترتیب نمایش: apparent-ارزان‌تر اول؛ مقایسهٔ عدد، نه رتبه
		a, b := cheapRisk[i], cheapRisk[j]
		if (a.ValueMean == nil) != (b.ValueMean == nil) {
			return b.ValueMean == nil
		}
		if a.ValueMean != nil && b.ValueMean != nil && *a.ValueMean != *b.ValueMean {
			return *a.ValueMean > *b.ValueMean
		}
		if a.Symbol != b.Symbol {
			return a.Symbol < b.Symbol
		}
		return a.CompanyID < b.CompanyID
	})
	blockedList := ensure(boardGroupBlocked)
	sort.SliceStable(blockedList, func(i, j int) bool {
		// مانع اثبات‌شده قبل از امتیاز مفقود، قبل از بدون‌پرونده — سپس نماد
		rank := func(e *boardEntry) int {
			if e.RiskGateStatus == rgBlocked {
				return 0
			}
			if e.Q.Status == "missing" || e.V.Status == "missing" || e.T.Status == "missing" {
				return 1
			}
			return 2
		}
		if ra, rb := rank(blockedList[i]), rank(blockedList[j]); ra != rb {
			return ra < rb
		}
		if blockedList[i].Symbol != blockedList[j].Symbol {
			return blockedList[i].Symbol < blockedList[j].Symbol
		}
		return blockedList[i].CompanyID < blockedList[j].CompanyID
	})

	// ── قرارداد صریح شمارش (گام ۲-ک-۱۰) ────────────────────────────────────
	// چهار گروه تصمیم mutually exclusive اند و مجموعشان دقیقاً برابر جامعهٔ
	// سه‌محوری است. صفت‌ها (conditional، negative_operating_profit، …) مستقل
	// از گروه‌اند و هرگز به شمارش گروه‌ها افزوده نمی‌شوند؛ صفت‌ها می‌توانند با
	// هر گروهی هم‌پوشانی داشته باشند. این تفکیک در counts.groups و
	// counts.attributes منتشر می‌شود تا جمع ظاهری گمراه‌کننده (گروه+صفت) از
	// بین برود.
	nConditionalInWaiting, nConditionalTotal, nNegOpTotal := 0, 0, 0
	for _, list := range entries {
		for _, e := range list {
			if e.Conditional {
				nConditionalTotal++
			}
			if e.NegativeOperatingProfit {
				nNegOpTotal++
			}
		}
	}
	for _, e := range waiting {
		if e.Conditional {
			nConditionalInWaiting++
		}
	}
	// nCondBlocking: تنها مانعِ «جذاب‌نشدن» همین قید کیفیت بوده (وگرنه جذاب
	// می‌شد) — این عدد معنادارِ تصمیم است، نه شمار کل دارندگان قید.
	nCondBlocking := notAttractive[boardExConditional]
	// تازگی قیمت و دروازه ریسک در سطح کل snapshot خلاصه می‌شوند تا کاربر
	// بداند تصمیم روی چه وضعیت جهانی داده‌ای بنا شده است (گام ۲-ک-۹).
	nFreshVerified, nRiskReview := 0, 0
	for _, dc := range in.companies {
		if boardFreshnessVerified(in.px[dc.CompanyID]) {
			nFreshVerified++
		}
		if dc.RiskGate.Status == rgReview {
			nRiskReview++
		}
	}
	// ناوردای قرارداد: مجموع چهار گروه باید برابر جامعهٔ سه‌محوری باشد.
	groupTotal := len(attractive) + len(waiting) + len(cheapRisk) + len(blockedList)
	reconciles := groupTotal == len(in.companies)

	noneNote := ""
	if len(attractive) == 0 {
		noneNote = fmt.Sprintf("با قواعد و آستانه‌های اعلامی سیاست تصمیم %s، در حال حاضر هیچ نمادی همهٔ آستانه‌ها را بدون «قید کیفیت اختصاصی» پاس نمی‌کند — این نتیجهٔ صادقانهٔ شواهد است؛ داشتن دادهٔ معتبر به معنی جذاب بودن فرصت نیست و هیچ نامزدی برای پر کردن فهرست ساخته نمی‌شود. توجه: قیدهای «جهانی snapshot» (وضعیت دروازه ریسک، مبنای سهام↔قیمت، پرووننس) برای همهٔ شرکت‌ها از جمله نامزدهای گروه ۱ منتشر می‌شود و «بدون قید اختصاصی» هرگز به معنای بی‌ریسک بودن نیست.", in.policy.Version)
		if nConditionalInWaiting > 0 {
			noneNote += fmt.Sprintf(" %d نامزد «مشروط» (واجد آستانه‌ها اما با قید کیفیت اقتصادی ثبت‌شده) در گروه «بنیادی مناسب — منتظر شرایط بهتر / مشروط» نمایش داده می‌شود؛ %d مورد تنها و تنها به‌دلیل همین قید از گروه جذاب بیرون مانده و قید هرکدام صریح آمده است.",
				nConditionalInWaiting, nCondBlocking)
		}
	}

	systemicCaveats := []string{
		fmt.Sprintf("دروازه ریسک: %d از %d شرکت سه‌محوری وضعیت «نیازمند بررسی» دارند — این وضعیت نه رد قطعی است و نه تأیید و نه معادل نبود ریسک معتبر؛ یافته‌های ثبت‌شده هر شرکت در کارت آن آمده است.", nRiskReview, len(in.companies)),
		fmt.Sprintf("تازگی قیمت مستقل: برای %d از %d شرکت سه‌محوری تأیید شد (سن ≤ سیاست تازگی آرتیفکت).", nFreshVerified, len(in.companies)),
		"مبنای سهام↔قیمت در این snapshot برای اکثر شرکت‌ها «اثبات‌نشده» است (تاریخچهٔ سهام چند روز قدیمی‌تر از قیمت و بدون شاهد اقدام شرکتی) — نسبت‌های متکی به سرمایه نیازمند بررسی‌اند و این وضعیت جهانی snapshot است، نه دفاع یا رد یک شرکت خاص.",
		"بخشی از عوامل بنیادی از نامهٔ خام بازیابی‌شده‌اند (پرووننس order3) و «تأییدنشدهٔ مستقل» می‌مانند.",
	}

	return gin.H{
		"title":           "فرصت‌های قابل بررسی بازار",
		"subtitle":        "حداکثر چند نامزد با ترکیب قابل دفاع بنیادی + ارزندگی + ورود — ساخته‌شده فقط از شواهد نسخه‌دار همین snapshot؛ داشتن دادهٔ معتبر به‌تنهایی جذابیت نیست",
		"not_a_signal":    "این فهرست توصیهٔ خرید/فروش، امتیاز از ۱۰۰ یا رتبهٔ بنیادی بین صنایع نیست؛ «نامزد جذاب» یعنی همهٔ آستانه‌های اعلامی سیاست تصمیم پاس شد و شواهد برای صرف وقت بررسی کافی است",
		"as_of":           in.asOf,
		"default_visible": boardDefaultVisible,
		"empty_note":      noneNote,
		"systemic_caveats": systemicCaveats,
		"counts": gin.H{
			// گروه‌های تصمیم — mutually exclusive؛ مجموع باید برابر جامعهٔ سه‌محوری باشد.
			"groups": gin.H{
				"attractive_candidates":   len(attractive),
				"fundamentals_waiting":    len(waiting),
				"apparent_value_risk":     len(cheapRisk),
				"blocked_or_insufficient": len(blockedList),
				"total":                   groupTotal,
				"universe":                len(in.companies),
				"mutually_exclusive":      true,
				"reconciles":              reconciles,
			},
			// صفت‌های مستقل از گروه (هرگز به شمارش گروه‌ها افزوده نمی‌شوند؛ مجاز به هم‌پوشانی با هر گروه).
			"attributes": gin.H{
				"conditional_total":         nConditionalTotal,
				"conditional_in_waiting":    nConditionalInWaiting,
				"conditional_blocking":      nCondBlocking,
				"negative_operating_profit": nNegOpTotal,
				"risk_review_required":      nRiskReview,
				"price_freshness_verified":  nFreshVerified,
			},
			"n_triple_universe":         len(in.companies),
			"not_in_attractive_reasons": notAttractive,
			"blocked_breakdown":         blockedBreakdown,
		},
		"attractive_candidates":   attractive,
		"fundamentals_waiting":    waiting,
		"apparent_value_risk":     cheapRisk,
		"blocked_or_insufficient": blockedList,
		"decision_policy":         in.policy,
		"rules":                   qvtBoardRules,
		"engine_note":             "موتور ترتیبی شفاف (go-app/handlers/qvt/opportunity.go + opportunity_decision.go — قواعد نسخهٔ ۳): ورودی یکسان → خروجی یکسان؛ هیچ تعداد، نماد، صنعت یا آستانهٔ پنهانی hardcode نشده و هیچ امتیاز جدیدی ساخته نمی‌شود",
	}
}

// qvtBoardRules قرارداد منتشرشدهٔ موتور انتخاب — از خود UI قابل ممیزی است.
var qvtBoardRules = gin.H{
	"version": "opportunity-rules-v4",
	"counting_contract": "قرارداد صریح شمارش (گام ۲-ک-۱۰): چهار گروه تصمیم (attractive_candidates، fundamentals_waiting، apparent_value_risk، blocked_or_insufficient) mutually exclusive اند و مجموعشان دقیقاً برابر جامعهٔ سه‌محوری است — در counts.groups با ناوردای reconciles منتشر می‌شود. صفت‌ها (conditional، negative_operating_profit، risk_review_required، price_freshness_verified) در counts.attributes مستقل‌اند، ممکن است با هر گروهی هم‌پوشانی داشته باشند و هرگز به شمارش گروه‌ها افزوده نمی‌شوند",
	"conditional_is_attribute": "«مشروط» یک صفت مستقل است، نه گروه تصمیم. شرکتی که همهٔ آستانه‌های سیاست را پاس می‌کند اما قید کیفیت اقتصادی ثبت‌شده دارد در گروه «بنیادی مناسب — منتظر شرایط بهتر» با پرچم conditional=true و دلیل صریح نمایش داده می‌شود؛ conditional_in_waiting شمار آن‌ها و conditional_blocking شمار مواردی است که تنها مانع‌شان همین قید بوده",
	"caveat_scope": "«بدون قید اختصاصی» فقط به قید کیفیت اقتصادی در سطح خود شرکت (تبدیل نقد ضعیف / سود عملیاتی منفی) اشاره دارد و هرگز به معنای بی‌ریسک بودن یا تأیید قطعی نیست. قیدهای جهانی snapshot (وضعیت دروازه ریسک، مبنای سهام↔قیمت، پرووننس order3) برای همهٔ شرکت‌ها از جمله نامزدهای گروه ۱ منتشر می‌شوند",
	"risk_gate_scope": "وضعیت دروازه ریسک «نیازمند بررسی» (review_required) یک قید جهانی snapshot است که در این snapshot برای همهٔ ۶۲ شرکت ثبت شده؛ Admissions فقط Risk Gate=blocked را رد می‌کند، زیرا review_required «یافتهٔ ثبت‌شده برای بررسی» است نه رد یا تأیید و نه معادل نبود ریسک معتبر. بنابراین کاهش یک کف اقتصاد اختصاصی (مثلاً cash_conversion) می‌تواند نامزد «بدون قید اختصاصی» بسازد در حالی که قید جهانی review_required همچنان برایش منتشر می‌شود — این دو سطح سازگارند و ناسازگاری قبلی صرفاً در واژگان «بدون قید» بود",
	"admission": "گروه «نامزدهای جذاب» علاوه بر گیت‌های شواهد (هر سه امتیاز مشاهده‌شده، گروه مقایسه‌پذیر معتبر با حداقل ۵ همتا، Risk Gate غیر از blocked، تازگی قیمت تأییدشده) به ترکیب تصمیم نیاز دارد: بنیادی غیرضعیف + ارزندگی قابل دفاع + ورود مناسب + نبود قید کیفیت اقتصادی اختصاصی؛ همهٔ آستانه‌ها در decision_policy منتشر شده است",
	"groups": "چهار گروه (متباین و مجموع‌بخش): (۱) نامزدهای جذاب برای بررسی جدی — ترکیب قابل دفاع بنیادی/ارزندگی/ورود بدون مانع و بدون قید کیفیت اختصاصی؛ (۲) بنیادی مناسب، منتظر شرایط بهتر — شامل نامزدهای «مشروط» (واجد آستانه‌ها اما با قید کیفیت اقتصادی ثبت‌شده) با ذکر صریح قید؛ (۳) ارزان به نظر می‌رسند اما ریسک دارند — ارزندگی ظاهری با بنیادی ضعیف؛ (۴) شواهد ناکافی یا دارای مانع — هرگز در پیشنهاد اولیه",
	"quality_caveat": "گام ۲-ک-۹: شرکتی که ROE قوی دارد اما پرسنتایل cash_conversion آن زیر کف سیاست است (یا سود عملیاتی منفی دارد) «جذاب بدون قید اختصاصی» نمی‌شود و به گروه مشروط می‌رود — ضعف بنیادی پشت Q قوی پنهان نمی‌ماند",
	"value_sector_support": "گام ۲-ک-۹: ارزندگی «قابل دفاع» فقط اگر چندگانهٔ پشتیبان (P/E یا P/B) در جمعیت نرمال‌سازی صنعتی خود حداقل ۵ هم‌صنعت معتبر داشته باشد؛ نمونهٔ کوچک رتبهٔ نسبی قابل دفاع نمی‌سازد",
	"evidence_vs_attractive": "داشتن اطلاعات معتبر با جذاب بودن فرصت یکی نیست؛ شرکت واجد گیت‌ها خودکار جذاب اعلام نمی‌شود و خروجی می‌تواند صفر نامزد جذاب داشته باشد — این نتیجهٔ صادقانه است",
	"reading_rules": "معنای اقتصادی هر عدد از قرارداد آرتیفکت استخراج شده: پرسنتایل‌ها جهت‌دار هستند (بالاتر = بهترِ نسبی در جمعیت)، P/E فقط با سود مثبت، P/B فقط با حقوق صاحبان سهام مثبت؛ ارزندگی = میانگین سادهٔ پرسنتایل عوامل مشاهده‌شده (خوانش شفاف، نه امتیاز جدید). در UI هر عدد بنیادی به‌صراحت «پرسنتایل» برچسب می‌خورد تا با نسبت مالی خام اشتباه نشود",
	"order": "ترتیب نمایش کاملاً ترتیبی و بدون جمع/وزن است: ۱) وضعیت Risk Gate ۲) اطمینان داده ۳) لایه پارتو صعودی ۴) سن قیمت ۵-۷) Q سپس V سپس T نزولی ۸) نماد؛ گروه «ارزان‌نما» با میانگین پرسنتایل ارزندگی نزولی نمایش داده می‌شود — ترتیب نمایش، نه رتبه",
	"order_is_not_rank": "این ترتیب فقط اولویت صرف وقت بررسی است؛ رتبهٔ بنیادی بین گروه‌های صنایع متفاوت نیست و هیچ امتیاز کل یا رتبهٔ خرید از آن ساخته نمی‌شود",
	"default_limit": "حداکثر ۸ نامزد پیش‌فرض گروه جذاب (بازهٔ ۵–۱۰)؛ اگر شواهد کمتر باشد همان تعداد کمتر و اگر صفر باشد صادقانه اعلام می‌شود — هیچ نامزدی برای پر کردن فهرست اضافه نمی‌شود",
	"no_hardcode": "هیچ تعداد، نماد، صنعت یا آستانهٔ پنهانی hardcode نیست؛ آستانه‌های تصمیم در decision_policy پاسخ منتشر می‌شوند و حساسیت نتایج به آن‌ها در گزارش گام سنجیده شده است",
	"no_diagnostic_reason": "رشد سود تشخیصی (earnings_growth) و هر شاخص غیررسمی هرگز دلیل انتخاب یا عامل ترتیب نیست؛ فقط هشدار کیفی ثبت‌شدهٔ آن در بخش «احتیاط» می‌آید",
	"missing_never_zero": "مقدار مفقود صفر فرض یا بازتوزیع نمی‌شود؛ شرکت با امتیاز مفقود وارد مقایسه/اولویت نمی‌شود؛ roe_stability و margin_trend (خارج از دستهٔ ۲-B-5) خوانده یا جایگزین نمی‌شوند و این محدودیت صادقانه ثبت است",
	"value_within_group": "ارزندگی «قابل دفاع» فقط با گروه مقایسه‌پذیر معتبر (هم‌صنعت، هم‌خانواده، هم‌پوشانی) و تکیه بر چندگانه‌های سخت P/E یا P/B صادر می‌شود؛ زیان‌ده هرگز ارزان قابل دفاع نیست",
	"absolute_vs_relative": "برای شرکت فاقد گروه همتای معتبر، قرائت مطلق (پرسنتایل جمعیت خانواده) جدا از مقایسهٔ نسبی ارائه می‌شود و هیچ رتبه نسبی بین آن و دیگران ساخته نمی‌شود",
	"data_vs_economic_risk": "ریسک داده (Risk Gate/اطمینان داده) از ریسک اقتصادی جدا است؛ review_required رد قطعی یا تأیید نیست و با دلیل نمایش داده می‌شود؛ در این snapshot همهٔ ۶۲ شرکت «نیازمند بررسی»اند و این وضعیت به‌صورت برجسته در ابتدای برد منتشر می‌شود",
	"freshness_gate": "تازگی قیمت فقط با کنترل مستقل منبع واقعی (market.price_observations در پنجره PIT) تأیید می‌شود؛ کنترل‌نشده یعنی نامزد فرصت «الان» نمی‌شود ولی با هشدار در گروه دوم می‌ماند",
	"traceable_reasons": "هر قضاوت متنی با عدد یا ارجاع به یافتهٔ ثبت‌شده همراه است؛ عبارت کلی بدون شواهد تولید نمی‌شود",
	"three_questions": "برای هر نامزد سه بخش کوتاه: «چرا این نماد؟» (حداکثر ۳ دلیل عددی)، «چرا ممکن است انتخاب خوبی نباشد؟» (حداکثر ۳ یافته/ضعف عددی)، «چه زمانی ارزش بررسی مجدد دارد؟» (شرایط پایش سنجش‌پذیر، نه پیش‌بینی قیمت)",
}
