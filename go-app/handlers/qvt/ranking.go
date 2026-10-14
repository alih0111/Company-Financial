package qvt

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// qvtExperimentalRankingDir اگر QVT_RANKING_BUNDLE_DIR تنظیم باشد و هر سه
// آرتیفکت را داشته باشد، آن مسیر را برمی‌گرداند؛ وگرنه "" (حالت رسمی).
// مسیر نسبی نسبت به پوشهٔ آرتیفکت رسمی حل می‌شود تا از CWD مستقل باشد.
func qvtExperimentalRankingDir(baseDir string) string {
	d := strings.TrimSpace(os.Getenv("QVT_RANKING_BUNDLE_DIR"))
	if d == "" {
		return ""
	}
	if !filepath.IsAbs(d) {
		d = filepath.Join(baseDir, d)
	}
	for _, n := range []string{"v2_q_observed_report.json", "v2_value_pilot.json", "v2_t_pilot.json"} {
		st, err := os.Stat(filepath.Join(d, n))
		if err != nil || st.IsDir() {
			return ""
		}
	}
	return d
}

// ─────────────────────────────────────────────────────────────────────────────
// صفحهٔ سادهٔ رتبه‌بندی (گام ۲-ک-۱۱) — یک شاخص آزمایشی مستقل ۰..۱۰۰ برای
// «اولویت بررسی»، فقط روی نامزدهایی که هر سه محور Q/V/T آن‌ها دادهٔ کافی و
// معتبر دارند (pilot_eligible در همان snapshot).
//
// قرارداد امتیاز (آشکار، بدون تغییر فرمول رسمی):
//   score = q_observed_points + v_observed_points + t_observed_points
//
//   * همین سه عدد، خروجی «مشاهده‌شدهٔ» رسمی آرتیفکت‌های Q/V/T هستند و وزن
//     عوامل درون هر محور همان وزن‌های رسمی (سقف ۴۰/۳۵/۲۵) است؛ پس سقف نظری
//     امتیاز ۱۰۰ است و ساختار وزن ۴۰٪ بنیادی + ۳۵٪ ارزندگی + ۲۵٪ ورود حفظ
//     می‌شود.
//   * امتیاز هرگز بر covered_weight تقسیم نمی‌شود و وزن عامل مفقود به عامل
//     مشاهده‌شده بازتوزیع نمی‌شود (قرارداد رسمی آرتیفکت Q). در نتیجه هرچه
//     پوشش یک محور کمتر باشد، امتیاز محافظه‌کارانه‌تر و سقف عملی همان شرکت
//     پایین‌تر است؛ این وضعیت برای هر شرکت با «کیفیت پوشش امتیاز» افشا می‌شود.
//   * عامل مفقود هرگز صفر فرض نمی‌شود؛ شرکت فاقد دادهٔ کافی اصلاً امتیاز
//     نمی‌گیرد و در فهرست «بدون امتیاز معتبر» با دلیل دقیق می‌آید.
//   * ریسک بحرانی هرگز پشت امتیاز بالا پنهان نمی‌شود: هر شرکت دارای مانع
//     اثبات‌شدهٔ دروازهٔ ریسک، وضعیت «ضعیف» می‌گیرد (هرگز «قابل بررسی برای
//     خرید») و پرچم بحرانی آن هم‌ردیف امتیاز نمایش داده می‌شود.
//
// این لایه هیچ تغییری در آرتیفکت‌ها، سیاست تصمیم، دروازهٔ ریسک یا وزن‌های
// رسمی ایجاد نمی‌کند؛ فقط خوانشِ ساده و رتبه‌بندی‌شدهٔ همان شواهد است.
// ─────────────────────────────────────────────────────────────────────────────

const (
	rankStatusBuyReview = "buy_review"
	rankStatusWait      = "wait"
	rankStatusWeak      = "weak"
)

var rankStatusLabels = map[string]string{
	rankStatusBuyReview: "قابل بررسی برای خرید",
	rankStatusWait:      "انتظار",
	rankStatusWeak:      "ضعیف",
}

// rankScoreCeiling سقف نظری شاخص = مجموع سقف وزن‌های رسمی سه محور.
const rankScoreCeiling = 100.0

// Freshness belongs to this bundle, independently of the V1 health endpoint.
// Calendar age is descriptive and does not claim a missing trading session.
func rankingFreshness(asOf string, now time.Time) gin.H {
	zone := time.FixedZone("Tehran", 3*60*60+30*60)
	today := now.In(zone).Format("2006-01-02")
	day := asOf
	if len(day) > 10 {
		day = day[:10]
	}
	stamp, err := time.Parse("2006-01-02", day)
	if err != nil {
		return gin.H{"status": "unknown", "as_of_date": day, "today": today, "age_calendar_days": nil}
	}
	current, _ := time.Parse("2006-01-02", today)
	age := int(current.Sub(stamp).Hours() / 24)
	status := "dated"
	if age == 0 {
		status = "same_day"
	} else if age < 0 {
		status = "future"
	}
	return gin.H{"status": status, "as_of_date": day, "today": today, "age_calendar_days": age}
}

type rankAxis struct {
	Points         *float64            `json:"points"`
	CoveredWeight  *float64            `json:"covered_weight"`
	Max            float64             `json:"max"`
	CoverageRatio  *float64            `json:"coverage_ratio"`
	NScored        int                 `json:"n_scored_factors"`
	NIssues        int                 `json:"n_factor_issues"`
	ScoredFactors  []string            `json:"scored_factors"`
	MissingFactors []rankMissingFactor `json:"missing_factors"`
}

type rankEntry struct {
	CompanyID   string `json:"company_id"`
	Symbol      string `json:"symbol"`
	Industry    string `json:"industry"`
	ModelFamily string `json:"model_family"`

	Rank         int     `json:"rank"`
	Score        float64 `json:"score"`
	rawScore     float64
	ScoreCeiling float64 `json:"score_ceiling"`

	Status       string `json:"status"`
	StatusLabel  string `json:"status_label"`
	StatusReason string `json:"status_reason"`

	MainReason string `json:"main_reason"`
	MainRisk   string `json:"main_risk"`

	Conditional             bool     `json:"conditional"`
	ConditionalReasons      []string `json:"conditional_reasons"`
	NegativeOperatingProfit bool     `json:"negative_operating_profit"`

	Critical      bool     `json:"critical"`
	CriticalFlags []string `json:"critical_flags"`

	RiskGateStatus string `json:"risk_gate_status"`
	RiskGateLabel  string `json:"risk_gate_label"`

	ValidationStatus string `json:"validation_status,omitempty"`
	ValidationLabel  string `json:"validation_status_label,omitempty"`

	ConfidenceOverall string `json:"confidence_overall"`
	ConfidenceLabel   string `json:"confidence_label"`

	// کیفیت امتیاز: کمینهٔ پوشش سه محور — هر چه کمتر، سقف امتیاز محافظه‌کارانه‌تر.
	CoverageMin          *float64 `json:"coverage_min"`
	ScoreConfidence      string   `json:"score_confidence"`
	ScoreConfidenceLabel string   `json:"score_confidence_label"`

	// کامل بودن داده و مقایسه‌پذیری.
	//   PracticalCeiling = مجموع وزن‌های پوشش‌داده‌شدهٔ سه محور؛ بیشترین امتیازی
	//   که این نماد با پوشش فعلی می‌توانست بگیرد. تفاوت آن با ۱۰۰ صرفاً ناشی از
	//   دادهٔ مفقود است، نه ضعف عملکرد.
	//   FullCoverage یعنی پوشش این نماد با بیشترین پوشش مشاهده‌شده در هر سه محور
	//   برابر است؛ در این حالت امتیازش مستقیماً با سایر نمادهای FullCoverage
	//   مقایسه‌پذیر است.
	PracticalCeiling   float64 `json:"practical_ceiling"`
	FullCoverage       bool    `json:"full_coverage"`
	Comparability      string  `json:"comparability"`
	ComparabilityLabel string  `json:"comparability_label"`

	// اندازه و اعتبار گروه همتای متوازن (خانواده + صنعت + پوشش فاکتور یکسان).
	// اگر کمتر از ۵ همتا باشد، رتبهٔ نسبی درون‌صنعت معتبر نیست و فقط قرائت
	// مطلق (پرسنتایل خانواده) خوانده می‌شود؛ گروه دوشرکتی هرگز معادل مقایسهٔ
	// صنعتی معتبر معرفی نمی‌شود.
	PeerGroupSize  int    `json:"peer_group_size"`
	PeerGroupValid bool   `json:"peer_group_valid"`
	PeerGroupLabel string `json:"peer_group_label"`

	// تحلیل حساسیت (غیررسمی): اگر وزن پوشش‌داده‌شدهٔ هر محور با بیشترین پوشش
	// مشاهده‌شده یکسان می‌شد (چگالی امتیاز محور ثابت می‌ماند)، این نماد چه
	// رتبه‌ای می‌گرفت. این عدد/رتبه «امتیاز» نیست و مبنای تصمیم قرار نمی‌گیرد؛
	// فقط نشان می‌دهد رتبهٔ خام تا چه حد به تفاوت پوشش حساس است.
	ExtrapolatedScore float64 `json:"extrapolated_score"`
	SensitivityRank   int     `json:"sensitivity_rank"`
	RankShift         int     `json:"rank_shift"`

	Q rankAxis `json:"q"`
	V rankAxis `json:"v"`
	T rankAxis `json:"t"`

	BoardGroup      string             `json:"board_group"`
	BoardGroupLabel string             `json:"board_group_label"`
	GroupReason     string             `json:"group_reason"`
	Why             []string           `json:"why"`
	Careful         []string           `json:"careful"`
	ReviewWhen      []string           `json:"review_when"`
	TimingWindows   []rankTimingWindow `json:"timing_windows"`
}

type rankUnscoredAxis struct {
	Points            *float64 `json:"points"`
	Present           bool     `json:"present"`
	Eligible          bool     `json:"eligible"`
	CoverageRatio     *float64 `json:"coverage_ratio"`
	CoveredWeight     *float64 `json:"covered_weight"`
	Max               float64  `json:"max"`
	MissingEssentials []string `json:"missing_essentials"`
	BlockerDetails    []string `json:"blocker_details,omitempty"`
}

type rankUnscored struct {
	CompanyID   string `json:"company_id"`
	Symbol      string `json:"symbol"`
	Industry    string `json:"industry"`
	ModelFamily string `json:"model_family"`

	ReasonCode   string   `json:"reason_code"`
	ReasonLabel  string   `json:"reason_label"`
	BlockingAxes []string `json:"blocking_axes"`

	Q rankUnscoredAxis `json:"q"`
	V rankUnscoredAxis `json:"v"`
	T rankUnscoredAxis `json:"t"`
}

func rankAxisFromBoard(a boardAxisStatus) rankAxis {
	return rankAxis{
		Points: a.Points, CoveredWeight: a.CoveredWeight, Max: a.Max,
		CoverageRatio: a.CoverageRatio, NScored: a.NScored, NIssues: a.NIssues,
	}
}

// rankScoreOnly مجموع سه امتیاز مشاهده‌شده؛ false اگر هر محور امتیاز نداشته باشد.
func rankScoreOnly(e *boardEntry) (float64, bool) {
	if e.Q.Points == nil || e.V.Points == nil || e.T.Points == nil {
		return 0, false
	}
	return *e.Q.Points + *e.V.Points + *e.T.Points, true
}

func rankRound1(x float64) float64 { return math.Round(x*10) / 10 }

// rankStatusFor وضعیت بررسی را از گروه تصمیم موجود و پرچم‌های بحرانی می‌سازد.
// سه حالت: buy_review | wait | weak. هیچ آستانهٔ امتیازیِ ساختگی ساخته
// نمی‌شود؛ نگاشت از گروه تصمیمِ سیاست رسمی است تا با بقیهٔ صفحه سازگار بماند.
func rankStatusFor(e *boardEntry) (string, string, []string) {
	flags := []string{}
	status := rankStatusWeak
	reason := ""
	switch e.Group {
	case boardGroupAttractive:
		status = rankStatusBuyReview
		reason = "همهٔ آستانه‌های اعلامی سیاست تصمیم پاس شده و مانع/قید کیفیت ثبت‌نشده است."
	case boardGroupWaiting:
		status = rankStatusWait
		reason = "بنیادی مناسب اما شرط تصمیم کامل نیست؛ منتظر شرایط بهتر."
	case boardGroupCheapRisk:
		status = rankStatusWeak
		reason = "ارزندگی ظاهری همراه با ضعف بنیادی — نیازمند احتیاط جدی."
	default: // blocked_or_insufficient
		status = rankStatusWeak
		reason = "پروندهٔ قابل دفاع برای بررسی خرید ساخته نشد (ضعف بنیادی و ارزندگی غیرقابل دفاع)."
	}

	// ریسک بحرانی هرگز پشت امتیاز بالا پنهان نمی‌شود.
	if e.RiskGateStatus == rgBlocked {
		status = rankStatusWeak
		flags = append(flags, "مانع اثبات‌شدهٔ دروازهٔ ریسک — در هیچ حالتی نامزد بررسی خرید نیست")
		reason = "دروازهٔ ریسک مانع اثبات‌شده ثبت کرده است؛ صرف‌نظر از امتیاز، نامزد بررسی خرید نیست."
	}
	if e.ValidationStatus == "conflicting" {
		flags = append(flags, "اعتبارسنجی مستقل متناقض — شواهد با منبع دوم هم‌خوان نیست")
	}
	if e.Conditional && status == rankStatusBuyReview {
		status = rankStatusWait
		reason = "واجد آستانه‌ها اما قید کیفیت اقتصادی ثبت‌شده؛ «جذاب بدون قید» اعلام نمی‌شود."
	}
	return status, reason, flags
}

func rankScoreConfidence(minCov *float64) (string, string) {
	if minCov == nil {
		return "unknown", "نامعلوم (پوشش محاسبه‌نشد)"
	}
	switch {
	case *minCov >= 0.90:
		return "high", "بالا"
	case *minCov >= 0.70:
		return "medium", "متوسط"
	default:
		return "low", "پایین (پوشش محور ناقص — سقف امتیاز محافظه‌کارانه است)"
	}
}

func rankMinCoverage(e *boardEntry) *float64 {
	var min *float64
	for _, a := range []boardAxisStatus{e.Q, e.V, e.T} {
		if a.CoverageRatio == nil {
			return nil
		}
		if min == nil || *a.CoverageRatio < *min {
			v := *a.CoverageRatio
			min = &v
		}
	}
	return min
}

func rankBoardGroupLabel(g string) string {
	switch g {
	case boardGroupAttractive:
		return "نامزد جذاب برای بررسی جدی"
	case boardGroupWaiting:
		return "بنیادی مناسب — منتظر شرایط بهتر"
	case boardGroupCheapRisk:
		return "ارزان‌نما — نیازمند احتیاط جدی"
	default:
		return "شواهد ناکافی یا دارای مانع"
	}
}

// buildRankedEntries ۶۲ نامزد سه‌محوری را به یک فهرست رتبه‌بندی‌شده تبدیل می‌کند.
func buildRankedEntries(board gin.H) []*rankEntry {
	groups := []string{boardGroupAttractive, boardGroupWaiting, boardGroupCheapRisk, boardGroupBlocked}
	out := []*rankEntry{}
	for _, g := range groups {
		list, _ := board[g].([]*boardEntry)
		for _, e := range list {
			score, ok := rankScoreOnly(e)
			if !ok {
				// این حالت در جامعهٔ سه‌محوری رخ نمی‌دهد (همهٔ محورها امتیاز
				// دارند)؛ اگر رخ دهد، شرکت امتیاز نمی‌گیرد و به فهرست بی‌امتیاز
				// می‌رود — هرگز مقدار ساختگی ساخته نمی‌شود.
				continue
			}
			status, statusReason, flags := rankStatusFor(e)
			minCov := rankMinCoverage(e)
			confCode, confLabel := rankScoreConfidence(minCov)
			why := e.Why
			if why == nil {
				why = []string{}
			}
			careful := e.Careful
			if careful == nil {
				careful = []string{}
			}
			reviewWhen := e.ReviewWhen
			if reviewWhen == nil {
				reviewWhen = []string{}
			}
			condReasons := e.ConditionalReasons
			if condReasons == nil {
				condReasons = []string{}
			}
			qa, va, ta := rankAxisFromBoard(e.Q), rankAxisFromBoard(e.V), rankAxisFromBoard(e.T)
			out = append(out, &rankEntry{
				CompanyID: e.CompanyID, Symbol: e.Symbol, Industry: e.Industry, ModelFamily: e.ModelFamily,
				Score: rankRound1(score), rawScore: score, ScoreCeiling: rankScoreCeiling,
				Status: status, StatusLabel: rankStatusLabels[status], StatusReason: statusReason,
				MainReason: e.TopReason, MainRisk: e.TopRisk,
				Conditional: e.Conditional, ConditionalReasons: condReasons,
				NegativeOperatingProfit: e.NegativeOperatingProfit,
				Critical:                len(flags) > 0, CriticalFlags: flags,
				RiskGateStatus: e.RiskGateStatus, RiskGateLabel: e.RiskGateLabel,
				ValidationStatus: e.ValidationStatus, ValidationLabel: e.ValidationLabel,
				ConfidenceOverall: e.ConfidenceOverall, ConfidenceLabel: e.ConfidenceLabel,
				CoverageMin: minCov, ScoreConfidence: confCode, ScoreConfidenceLabel: confLabel,
				PracticalCeiling: rankRound1(rankCW(qa) + rankCW(va) + rankCW(ta)),
				PeerGroupSize:    e.GroupSize, PeerGroupValid: e.GroupSize >= 5,
				PeerGroupLabel: e.GroupLabel,
				Q:              qa, V: va, T: ta,
				BoardGroup: e.Group, BoardGroupLabel: rankBoardGroupLabel(e.Group),
				GroupReason: e.GroupReason, Why: why, Careful: careful, ReviewWhen: reviewWhen,
			})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].rawScore != out[j].rawScore {
			return out[i].rawScore > out[j].rawScore
		}
		if out[i].Symbol != out[j].Symbol {
			return out[i].Symbol < out[j].Symbol
		}
		return out[i].CompanyID < out[j].CompanyID
	})
	for i := range out {
		out[i].Rank = i + 1
	}
	rankAttachSensitivity(out)
	return out
}

// rankCW وزن پوشش‌داده‌شدهٔ یک محور (۰ اگر نامعلوم).
func rankCW(a rankAxis) float64 {
	if a.CoveredWeight == nil {
		return 0
	}
	return *a.CoveredWeight
}

// rankMaxCovered بیشترین وزن پوشش‌داده‌شدهٔ هر محور در میان نامزدها؛ مبنای
// «یکسان‌سازی پوشش» در تحلیل حساسیت. اگر هیچ نامزدی نباشد، سقف نظری می‌آید.
func rankMaxCovered(entries []*rankEntry) (mq, mv, mt float64) {
	for _, e := range entries {
		if c := rankCW(e.Q); c > mq {
			mq = c
		}
		if c := rankCW(e.V); c > mv {
			mv = c
		}
		if c := rankCW(e.T); c > mt {
			mt = c
		}
	}
	if mq == 0 {
		mq = 40
	}
	if mv == 0 {
		mv = 35
	}
	if mt == 0 {
		mt = 25
	}
	return
}

// rankAttachSensitivity پوشش کامل/جزئی و تحلیل حساسیت غیررسمی را پر می‌کند.
// هیچ‌کدام امتیاز رسمی نیست: PracticalCeiling سقف حاصل از دادهٔ موجود است و
// ExtrapolatedScore فقط چگالی امتیاز مشاهده‌شده را به پوشش بیشینه تعمیم می‌دهد.
func rankAttachSensitivity(entries []*rankEntry) {
	if len(entries) == 0 {
		return
	}
	mq, mv, mt := rankMaxCovered(entries)
	for _, e := range entries {
		full := rankCW(e.Q) == mq && rankCW(e.V) == mv && rankCW(e.T) == mt
		e.FullCoverage = full
		if full {
			e.Comparability = "full"
			e.ComparabilityLabel = "پوشش کامل — مستقیماً با نمادهای پوشش‌کامل مقایسه‌پذیر"
		} else {
			e.Comparability = "partial"
			e.ComparabilityLabel = "پوشش جزئی — سقف امتیاز این نماد از دادهٔ مفقود پایین‌تر است (نه از ضعف عملکرد)"
		}
		e.ExtrapolatedScore = rankExtrapolated(e, mq, mv, mt)
	}
	// رتبهٔ حساسیت: ترتیب نزولی بر پایهٔ امتیاز تعمیم‌یافته (غیررسمی).
	order := make([]*rankEntry, len(entries))
	copy(order, entries)
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].ExtrapolatedScore != order[j].ExtrapolatedScore {
			return order[i].ExtrapolatedScore > order[j].ExtrapolatedScore
		}
		return order[i].Symbol < order[j].Symbol
	})
	for i, e := range order {
		e.SensitivityRank = i + 1
		e.RankShift = e.SensitivityRank - e.Rank
	}
}

// rankExtrapolated چگالی امتیاز مشاهده‌شدهٔ هر محور را به بیشترین پوشش
// مشاهده‌شده تعمیم می‌دهد (counterfactual). امتیاز رسمی نیست.
func rankExtrapolated(e *rankEntry, mq, mv, mt float64) float64 {
	pts := func(a rankAxis, maxW float64) float64 {
		if a.Points == nil || rankCW(a) <= 0 {
			return 0
		}
		return *a.Points * maxW / rankCW(a)
	}
	return rankRound1(pts(e.Q, mq) + pts(e.V, mv) + pts(e.T, mt))
}

// rankAvgRanks رتبهٔ میانگین برای پیوندها (tie) — پیش‌نیاز اسپیرمن.
func rankAvgRanks(v []float64) []float64 {
	n := len(v)
	idx := make([]int, n)
	for i := range idx {
		idx[i] = i
	}
	sort.SliceStable(idx, func(i, j int) bool { return v[idx[i]] < v[idx[j]] })
	rk := make([]float64, n)
	for i := 0; i < n; {
		j := i
		for j+1 < n && v[idx[j+1]] == v[idx[i]] {
			j++
		}
		avg := float64(i+j)/2 + 1
		for k := i; k <= j; k++ {
			rk[idx[k]] = avg
		}
		i = j + 1
	}
	return rk
}

// rankSpearman ضریب همبستگی رتبه‌ای اسپیرمن (با میانگین‌گیری برای پیوندها).
func rankSpearman(a, b []float64) float64 {
	n := len(a)
	if n < 2 || n != len(b) {
		return 0
	}
	ra, rb := rankAvgRanks(a), rankAvgRanks(b)
	ma, mb := 0.0, 0.0
	for i := 0; i < n; i++ {
		ma += ra[i]
		mb += rb[i]
	}
	ma /= float64(n)
	mb /= float64(n)
	num, da, db := 0.0, 0.0, 0.0
	for i := 0; i < n; i++ {
		num += (ra[i] - ma) * (rb[i] - mb)
		da += (ra[i] - ma) * (ra[i] - ma)
		db += (rb[i] - mb) * (rb[i] - mb)
	}
	if da == 0 || db == 0 {
		return 0
	}
	return num / math.Sqrt(da*db)
}

// rankCoverageImpact سنجه‌های اثر پوشش بر رتبه‌بندی را از خود داده می‌سازد
// (شفاف و بازتولیدپذیر) تا ادعای «مقایسه‌پذیری» بدون عدد مطرح نشود.
func rankCoverageImpact(entries []*rankEntry) gin.H {
	raw := make([]float64, 0, len(entries))
	ext := make([]float64, 0, len(entries))
	qcov := make([]float64, 0, len(entries))
	nFull, nPartial := 0, 0
	maxShift, nShift5, nShift10 := 0, 0, 0
	minCeil, maxCeil := 0.0, 0.0
	topCount := len(entries)
	if topCount > 10 {
		topCount = 10
	}
	topOverlap := 0
	for _, e := range entries {
		if e.Rank <= topCount && e.SensitivityRank <= topCount {
			topOverlap++
		}
		raw = append(raw, e.Score)
		ext = append(ext, e.ExtrapolatedScore)
		if e.Q.CoverageRatio != nil {
			qcov = append(qcov, *e.Q.CoverageRatio)
		}
		if e.FullCoverage {
			nFull++
		} else {
			nPartial++
		}
		s := e.RankShift
		if s < 0 {
			s = -s
		}
		if s > maxShift {
			maxShift = s
		}
		if s > 5 {
			nShift5++
		}
		if s > 10 {
			nShift10++
		}
		if minCeil == 0 || e.PracticalCeiling < minCeil {
			minCeil = e.PracticalCeiling
		}
		if e.PracticalCeiling > maxCeil {
			maxCeil = e.PracticalCeiling
		}
	}
	// رتبه‌های پیوسته برای مقایسهٔ رتبه‌ای
	rank1 := make([]float64, len(entries))
	rank2 := make([]float64, len(entries))
	for i, e := range entries {
		rank1[i] = float64(e.Rank)
		rank2[i] = float64(e.SensitivityRank)
	}
	return gin.H{
		"n_scored":                           len(entries),
		"n_full_coverage":                    nFull,
		"n_partial_coverage":                 nPartial,
		"spearman_raw_vs_coverage_equalized": rankRound3(rankSpearman(rank1, rank2)),
		"spearman_score_vs_q_coverage":       rankRound3(rankSpearman(raw, qcov)),
		"max_rank_shift":                     maxShift,
		"n_shift_gt5":                        nShift5,
		"n_shift_gt10":                       nShift10,
		"practical_ceiling_min":              minCeil,
		"practical_ceiling_max":              maxCeil,
		"top10_overlap":                      topOverlap,
		"top10_count":                        topCount,
		"interpretation":                     fmt.Sprintf("از %d نماد بالای فهرست، %d نماد در تحلیل حساسیت پوشش نیز در همان فهرست باقی می‌مانند. تفاوت پوشش داده بر امتیاز اثر دارد؛ این تحلیل، دقت پیش‌بینی یا سودآوری را اثبات نمی‌کند.", topCount, topOverlap),
	}
}

// rankPeerGroupImpact سنجهٔ اعتبار مقایسهٔ صنعتی را از اندازهٔ گروه همتای
// متوازن می‌سازد: گروه کمتر از ۵ عضو، رتبهٔ نسبی درون‌صنعت معتبر ندارد و
// فقط قرائت مطلق خوانده می‌شود (گروه دوشرکتی هرگز مقایسهٔ صنعتی معتبر نیست).
func rankPeerGroupImpact(entries []*rankEntry) gin.H {
	if len(entries) == 0 {
		return gin.H{"n": 0}
	}
	nValid, nSmall, nNotEval := 0, 0, 0
	minSize := 0
	top10Small := 0
	for i, e := range entries {
		switch {
		case e.PeerGroupSize == 0:
			// خارج از نامزدهای متوازن (ارزان‌نما/بدون‌پرونده) — گروه ارزیابی نشده
			nNotEval++
		case e.PeerGroupValid:
			nValid++
		default:
			nSmall++
			if i < 10 {
				top10Small++
			}
		}
		if e.PeerGroupSize > 0 && (minSize == 0 || e.PeerGroupSize < minSize) {
			minSize = e.PeerGroupSize
		}
	}
	return gin.H{
		"n_scored":              len(entries),
		"n_valid_group":         nValid,
		"n_small_group":         nSmall,
		"n_group_not_evaluated": nNotEval,
		"min_group_size":        minSize,
		"top10_small_group":     top10Small,
		"min_group_rule":        5,
		"interpretation": "گروه همتای متوازن (خانواده + صنعت + پوشش فاکتور یکسان) باید حداقل ۵ عضو داشته باشد " +
			"تا رتبهٔ نسبی درون‌صنعت معتبر باشد. برای گروه‌های کوچک‌تر، سیستم رتبهٔ نسبی صنعت را صادر نمی‌کند و " +
			"فقط قرائت مطلق (پرسنتایل خانواده) را نشان می‌دهد؛ یک گروه دوشرکتی هرگز معادل مقایسهٔ صنعتی معتبر " +
			"معرفی نمی‌شود. این محدودیت جدا از پوشش داده است.",
	}
}

func rankRound3(x float64) float64 { return math.Round(x*1000) / 1000 }

// rankCoveragePlan برنامهٔ مشخص تکمیل داده برای مقایسه‌پذیرکردن امتیاز را
// از قرارداد آرتیفکت Q توضیح می‌دهد (بدون ساخت امتیاز جدید).
func rankCoveragePlan() gin.H {
	return gin.H{
		"goal":                 "تکمیل دادهٔ معتبر هر سه محور و روشن‌کردن موانع واقعی هر نماد.",
		"why_q_only":           "پوشش بنیادی، ارزندگی و شرایط ورود از بستهٔ جاری خوانده می‌شود؛ دلیل هر مورد ناقص در فهرست نمادهای بدون امتیاز آمده است.",
		"structural_gap":       "بعضی عوامل بنیادی هنوز خارج از دامنهٔ پیاده‌سازی یا سیاست محاسبه هستند؛ مدل بنیادی خانواده‌های بانک، بیمه و سرمایه‌گذاری نیز مستقل باید تکمیل شود.",
		"differentiating_gaps": "سقف عملی هر سهم از وزن عوامل معتبر همان سهم محاسبه می‌شود؛ فقدان داده یا غیرقابل‌استفاده‌بودن یک نسبت، عملکرد صفر محسوب نمی‌شود.",
		"residual_causes":      "کمبود صورت مالی، سابقهٔ کوتاه یا قیمت قدیمی، جهش مشکوک در تاریخچهٔ تعدیل‌شده، نسبت اقتصادی نامعتبر و کمبود همتا علت‌های جدا هستند و راه‌حل یکسان ندارند.",
		"steps": []string{
			"جمع‌آوری گزارش شرکت اصلی با هویت، واحد، تاریخ ستون و زمان انتشار قابل اثبات.",
			"تکمیل تاریخچهٔ تعدیل‌شده و بررسی رویدادهای شرکتی؛ حفظ توقف ارزیابی روی جهش مشکوک.",
			"تکمیل مدل تخصصی گروه‌های خارج از دامنه؛ پرنکردن نسبت نامعتبر با دادهٔ ساختگی.",
			"تولید هم‌زمان هر سه محور با cutoff واقعی و اعلام آخرین تاریخ قیمت.",
		},
		"success_criterion": "کاهش نقص قابل رفع با شواهد معتبر؛ همهٔ نمادها الزاماً از دروازهٔ امتیاز کامل عبور نمی‌کنند.",
		"not_a_new_score":   "وزن مفقود بازتوزیع نمی‌شود و فرمول امتیاز با افزایش پوشش تغییر نمی‌کند.",
	}
}

// rankAxisElig خوانش واجد‌بودن یک محور از آرتیفکت خام (برای فهرست بی‌امتیاز).
func rankAxisElig(cm map[string]any, max float64) rankUnscoredAxis {
	a := rankUnscoredAxis{Max: max, MissingEssentials: []string{}}
	if cm == nil {
		return a
	}
	a.Present = true
	for _, key := range []string{"q_observed_points", "v_observed_points", "t_observed_points"} {
		if points, ok := qvtFloat(cm, key); ok {
			a.Points = &points
			break
		}
	}
	if b, ok := cm["pilot_eligible"].(bool); ok {
		a.Eligible = b
	}
	if f, ok := qvtFloat(cm, "coverage_ratio"); ok {
		a.CoverageRatio = &f
	}
	if f, ok := qvtFloat(cm, "covered_weight"); ok {
		a.CoveredWeight = &f
	}
	if es, ok := cm["essential_status"].(map[string]any); ok {
		if ms, ok := es["missing"].([]any); ok {
			for _, m := range ms {
				if s, ok := m.(string); ok {
					a.MissingEssentials = append(a.MissingEssentials, s)
				}
			}
		}
	}
	if qvtStr(cm, "aggregation_status") == "family_out_of_scope" {
		a.BlockerDetails = append(a.BlockerDetails, "مدل بنیادی تخصصی این گروه هنوز پیاده‌سازی نشده است؛ جمع‌آوری بیشتر به‌تنهایی این مانع را رفع نمی‌کند")
	}
	factors, _ := cm["factors"].(map[string]any)
	for _, fid := range a.MissingEssentials {
		factor, _ := factors[fid].(map[string]any)
		detail := rankBlockerDetail(fid, factor)
		if detail != "" {
			a.BlockerDetails = append(a.BlockerDetails, detail)
		}
	}
	return a
}

func rankBlockerDetail(fid string, factor map[string]any) string {
	reason := qvtStr(factor, "validation_reason")
	status := qvtStr(factor, "normalization_status")
	switch {
	case strings.HasPrefix(reason, "insufficient_history_"):
		return "سابقهٔ قیمت برای بازهٔ لازم کافی نیست"
	case strings.HasPrefix(reason, "suspected_unadjusted_gap"):
		return "جهش مشکوک در قیمت تعدیل‌شده؛ تاریخچه و رویداد شرکتی باید راستی‌آزمایی شود"
	case strings.HasPrefix(reason, "price_stale"):
		return "قیمت قدیمی است و نیاز به تازه‌سازی دارد"
	case strings.HasPrefix(reason, "window_span_too_long"):
		return "توقف یا فاصلهٔ طولانی معاملات؛ شرایط ورود قابل محاسبه نیست"
	case strings.HasPrefix(reason, "return_window_mismatch"):
		return "تاریخ شروع یا پایان بازده با بازهٔ مقایسهٔ بازار یکسان نیست؛ مقایسه معتبر نیست"
	case strings.HasPrefix(reason, "insufficient_sector_benchmark"):
		return "تعداد همتای صنعت با بازهٔ زمانی یکسان کافی نیست"
	case status == "not_ranked_raw_not_applicable" && fid == "pe":
		return "سود دوازده‌ماهه مثبت نیست؛ نسبت P/E معتبر قابل محاسبه نیست و این کمبود داده محسوب نمی‌شود"
	case status == "not_ranked_raw_not_applicable" && fid == "pb":
		return "حقوق مالکانه مثبت نیست؛ نسبت P/B معتبر قابل محاسبه نیست و این کمبود داده محسوب نمی‌شود"
	case status == "insufficient_peers":
		return "تعداد همتای معتبر برای مقایسه کافی نیست"
	}
	return ""
}

var rankAxisNames = map[string]string{"Q": "بنیادی (Q)", "V": "ارزندگی (V)", "T": "ورود (T)"}

// buildUnscored فهرست شرکت‌های فاقد امتیاز معتبر را با دلیل دقیق می‌سازد.
// یک شرکت می‌تواند در چند محور مشکل داشته باشد؛ همهٔ محورهای مسدودکننده ثبت
// می‌شوند و کد دلیل از نخستین محور (به ترتیب Q،V،T) می‌آید.
func buildUnscored(qc, vc, tc map[string]any, scored map[string]bool) []*rankUnscored {
	ids := map[string]bool{}
	for cid := range qc {
		ids[cid] = true
	}
	for cid := range vc {
		ids[cid] = true
	}
	for cid := range tc {
		ids[cid] = true
	}
	cids := make([]string, 0, len(ids))
	for cid := range ids {
		if !scored[cid] {
			cids = append(cids, cid)
		}
	}
	sort.Strings(cids)

	out := []*rankUnscored{}
	for _, cid := range cids {
		qcm, _ := qc[cid].(map[string]any)
		vcm, _ := vc[cid].(map[string]any)
		tcm, _ := tc[cid].(map[string]any)
		u := &rankUnscored{
			CompanyID: cid,
			Symbol:    firstNonEmpty(qvtStr(qcm, "symbol"), qvtStr(vcm, "symbol"), qvtStr(tcm, "symbol")),
			Industry:  firstNonEmpty(qvtStr(qcm, "industry"), qvtStr(vcm, "industry"), qvtStr(tcm, "industry")),
			ModelFamily: firstNonEmpty(qvtStr(qcm, "model_family"), qvtStr(vcm, "model_family"),
				qvtStr(tcm, "model_family")),
			Q: rankAxisElig(qcm, 40), V: rankAxisElig(vcm, 35), T: rankAxisElig(tcm, 25),
			BlockingAxes: []string{},
		}
		var parts []string
		blocking := []struct {
			key  string
			axis rankUnscoredAxis
		}{{"Q", u.Q}, {"V", u.V}, {"T", u.T}}
		primaryCode := ""
		for _, b := range blocking {
			if b.axis.Present && b.axis.Eligible {
				continue
			}
			u.BlockingAxes = append(u.BlockingAxes, b.key)
			name := rankAxisNames[b.key]
			var reason string
			var code string
			switch {
			case len(b.axis.BlockerDetails) > 0:
				reason = name + ": " + strings.Join(b.axis.BlockerDetails, "؛ ")
				code = "blocked_" + strings.ToLower(b.key)
			case !b.axis.Present:
				reason = "دادهٔ " + name + " در snapshot ثبت نشده"
				code = "no_data_" + strings.ToLower(b.key)
			case len(b.axis.MissingEssentials) > 0:
				reason = "عوامل ضروری " + name + " مفقود است: " + strings.Join(b.axis.MissingEssentials, ", ")
				code = "missing_essential_" + strings.ToLower(b.key)
			case b.axis.CoverageRatio != nil && *b.axis.CoverageRatio == 0:
				reason = "دادهٔ کافی برای " + name + " موجود نیست (پوشش ۰٪)"
				code = "no_data_" + strings.ToLower(b.key)
			default:
				reason = "پوشش " + name + " زیر آستانهٔ واجد‌بودن است"
				if b.axis.CoverageRatio != nil {
					reason = "پوشش " + name + " زیر آستانه است (" +
						rankPct(b.axis.CoverageRatio) + ")"
				}
				code = "low_coverage_" + strings.ToLower(b.key)
			}
			parts = append(parts, reason)
			if primaryCode == "" {
				primaryCode = code
			}
		}
		if primaryCode == "" {
			primaryCode = "not_eligible"
		}
		if len(parts) == 0 {
			parts = append(parts, "دادهٔ معتبر کافی برای امتیازدهی ثبت نشده")
		}
		u.ReasonCode = primaryCode
		u.ReasonLabel = strings.Join(parts, "؛ ") + " — امتیاز کامل تا رفع موانع محاسبه نمی‌شود."
		out = append(out, u)
	}
	return out
}

func rankPct(v *float64) string {
	if v == nil {
		return "—"
	}
	return fmt.Sprintf("%.1f%%", *v*100)
}

// rankScoreContract قرارداد آشکار امتیاز برای ممیزی از خود UI.
func rankScoreContract() gin.H {
	return gin.H{
		"version":               "qvt-ranking-contract-v2",
		"score_name":            "امتیاز مشاهده‌شدهٔ آزمایشی",
		"formula":               "score = q_observed_points + v_observed_points + t_observed_points",
		"weights":               "ساختار وزن رسمی حفظ شده: بنیادی ۴۰٪ (Q) + ارزندگی ۳۵٪ (V) + شرایط ورود ۲۵٪ (T)؛ سقف نظری امتیاز ۱۰۰",
		"full_coverage_meaning": "سقف نظری ۱۰۰ است؛ سقف عملی از مجموع وزن عوامل معتبر همان نماد به دست می‌آید. پوشش کامل یعنی بیشترین پوشش مشاهده‌شدهٔ بسته در هر محور، نه لزوماً همهٔ عوامل نظری. حداقل و حداکثر سقف عملی در تحلیل پوشش همین پاسخ گزارش می‌شود",
		"no_redistribution":     "امتیاز هرگز بر covered_weight تقسیم نمی‌شود و وزن عامل مفقود به عامل مشاهده‌شده بازتوزیع نمی‌شود (قرارداد رسمی آرتیفکت Q)؛ در نتیجه پوشش ناقص، سقف امتیاز را محافظه‌کارانه پایین می‌آورد و این برای هر شرکت افشا می‌شود",
		"no_fabrication":        "عامل مفقود هرگز صفر فرض نمی‌شود؛ شرکت فاقد دادهٔ کافی امتیاز نمی‌گیرد و با دلیل دقیق در فهرست «بدون امتیاز معتبر» می‌آید",
		"eligibility":           "امتیاز فقط برای نمادی صادر می‌شود که هر سه محور بنیادی، ارزندگی و شرایط ورود او در همین بسته واجد شرایط باشند؛ تعداد از دادهٔ همین بسته محاسبه می‌شود",
		"critical_not_hidden":   "مانع اثبات‌شدهٔ دروازهٔ ریسک، اعتبارسنجی متناقض یا قید کیفیت اقتصادی هم‌ردیف امتیاز نمایش داده می‌شود و شرکت دارای مانع هرگز وضعیت «قابل بررسی برای خرید» نمی‌گیرد",
		"status_map":            "وضعیت از گروه تصمیم سیاست رسمی نگاشت می‌شود: جذاب→قابل بررسی برای خرید، منتظر/مشروط→انتظار، ارزان‌نما و بدون‌پرونده→ضعیف؛ مانع اثبات‌شدهٔ ریسک همیشه→ضعیف",
		"comparability": "این امتیاز مجموع امتیازهای مشاهده‌شدهٔ سه محور است، نه یک رتبه‌بندی اقتصادی کاملاً مقایسه‌پذیر: " +
			"پوشش داده بین نامزدها ممکن است یکسان نباشد و پوشش کمتر سقف امتیاز را پایین می‌آورد " +
			"(نه عملکرد را). آرتیفکت رسمی Q خود تصریح می‌کند که شرکت‌ها هرگز بر پایهٔ q_observed_points رتبه‌بندی نمی‌شوند چون پوشش تفاوت دارد. " +
			"به همین دلیل نام آن «امتیاز مشاهده‌شدهٔ آزمایشی» است و تا اثبات مقایسه‌پذیری، رتبه‌بندی رسمی اقتصادی نیست. " +
			"هر سهم «سقف عملی» (مجموع وزن پوشش‌داده‌شده) و «کامل بودن پوشش» خود را نشان می‌دهد",
		"weights_untouched":     "هیچ وزن رسمی Q/V/T تغییر نکرده و هیچ عامل جدیدی ساخته نشده؛ تحلیل حساسیت (rank_shift/sensitivity_rank) فقط برای سنجش اثر پوشش است و امتیاز رسمی نیست",
		"is_experimental_index": "این یک شاخص آزمایشی مستقل برای اولویت بررسی است، نه فرمول رسمی QVT و نه توصیه خرید/فروش. هیچ ادعای دقت پیش‌بینی بدون بک‌تست PIT معتبر وجود ندارد",
	}
}

// GetQvtV2Ranking serves GET /api/qvt-v2/ranking — the simple 0..100 ranked
// review-priority list over the same read-only snapshot.
func GetQvtV2Ranking(c *gin.Context) {
	// مسیر آزمایشی (۲-ک-۱۳): اگر QVT_RANKING_BUNDLE_DIR تنظیم و شامل هر سه
	// آرتیفکت باشد، همان بستهٔ نسخه‌دار سرو می‌شود؛ هیچ فایل رسمی overwrite
	// نمی‌شود و در نبود این متغیر رفتار کاملاً بدون تغییر است.
	dir := qvtArtifactDir()
	expDir := qvtExperimentalRankingDir(dir)
	var b *qvtBundle
	var err error
	if expDir != "" {
		b, err = qvtLoadBundleDirect(expDir)
	} else {
		b, err = qvtLoadBundle(dir)
	}
	if err != nil {
		c.Header("Cache-Control", "no-store")
		c.JSON(503, gin.H{"error": err.Error()})
		return
	}
	asOf, cutoff, problems := qvtCheckConsistency(b)
	if len(problems) > 0 {
		c.Header("Cache-Control", "no-store")
		c.JSON(409, gin.H{
			"error":      "اسنپ‌شات سه آرتیفکت هم‌خوان نیست — رتبه‌بندی رد شد؛ هیچ داده‌ی جعلی جایگزین نمی‌شود",
			"problems":   problems,
			"disclaimer": qvtDisclaimer,
		})
		return
	}
	qc := qvtCompanies(b.Q, "")
	vc := qvtCompanies(b.V, "v_observed_report")
	tc := qvtCompanies(b.T, "t_observed_report")
	if conflicts := qvtCheckIdentity(qc, vc, tc); len(conflicts) > 0 {
		c.Header("Cache-Control", "no-store")
		c.JSON(409, gin.H{
			"error":      "هویت شرکت‌ها بین محورها ناسازگار است — رتبه‌بندی رد شد",
			"conflicts":  conflicts,
			"disclaimer": qvtDisclaimer,
		})
		return
	}

	companies, nAll := discExtractCompanies(qc, vc, tc)
	balanced := discBuildBalanced(companies)
	policy := bundlePricePolicy(b)
	asOfDate := qvtStr(b.V, "as_of")
	checkCids := cidsNeedingPriceCheck(companies, balanced)
	px, pxAvail, pxNote := priceChecksFor(checkCids, qvtStr(b.V, "cutoff"), asOfDate, policy)
	discAttachEvaluations(companies, qc, vc, tc, px)
	overlays := qvtLoadOverlays(b.dir, b)
	board := buildOpportunityBoard(boardInput{
		companies: companies, balanced: balanced, px: px, overlays: overlays,
		asOf: asOf, qc: qc, vc: vc, tc: tc, policy: defaultBoardDecisionPolicy(),
	})

	ranked := buildRankedEntries(board)
	rankAttachEvidence(ranked, qc, vc, tc)
	scoredIDs := map[string]bool{}
	for _, r := range ranked {
		scoredIDs[r.CompanyID] = true
	}
	unscored := buildUnscored(qc, vc, tc, scoredIDs)

	c.Header("Cache-Control", "no-store")
	c.JSON(200, gin.H{
		"stage":      "qvt_v2_ranking",
		"pilot":      true,
		"disclaimer": qvtDisclaimer,
		"boundaries": qvtBoundaries,
		"as_of":      asOf,
		"freshness":  rankingFreshness(asOf, time.Now()),
		"data_dates": b.Q["data_dates"],
		"cutoff":     cutoff,
		"title":      "رتبه‌بندی سادهٔ اولویت بررسی",
		"score_name": "امتیاز مشاهده‌شدهٔ آزمایشی",
		"subtitle": "یک امتیاز آزمایشی ۰..۱۰۰ روی نمادهایی که هر سه محور Q/V/T آن‌ها دادهٔ کافی و معتبر دارند — " +
			"مجموع امتیازهای مشاهده‌شدهٔ رسمی، برای دیدن سریع اینکه کدام سهم ارزش بررسی دارد و چرا",
		"not_a_signal": "این امتیاز توصیه خرید/فروش و نه پیش‌بینی قیمت است؛ شاخص آزمایشی اولویت بررسی است. " +
			"نمرهٔ پایین به‌تنهایی سیگنال فروش قطعی نیست و نمرهٔ بالا به‌تنهایی به معنای بی‌ریسک بودن نیست. " +
			"کامل بودن پوشش داده نیز در امتیاز اثر دارد: پوشش کمتر یعنی سقف امتیاز پایین‌تر، نه لزوماً سهم ضعیف‌تر. " +
			"همچنین نمادهایی که گروه همتای متوازن‌شان کمتر از ۵ عضو دارد، رتبهٔ نسبی درون‌صنعت معتبر ندارند و فقط با معیار مطلق خوانده می‌شوند.",
		"score_ceiling": rankScoreCeiling,
		"universe": gin.H{
			"n_all_artifacts": nAll,
			"n_scored":        len(ranked),
			"n_unscored":      len(unscored),
			"note": "کل نمادهای سه آرتیفکت نمایش داده می‌شوند؛ فقط نمادهای دارای دادهٔ کافی و معتبر " +
				"امتیاز می‌گیرند و بقیه در فهرست «بدون امتیاز معتبر» با دلیل دقیق می‌آیند",
		},
		"score_contract":       rankScoreContract(),
		"coverage_impact":      rankCoverageImpact(ranked),
		"peer_group_impact":    rankPeerGroupImpact(ranked),
		"data_completion_plan": rankCoveragePlan(),
		"sensitivity_note": "sensitivity_rank و rank_shift یک تحلیل حساسیت غیررسمی‌اند: اگر وزن پوشش‌داده‌شدهٔ " +
			"هر محور با بیشترین پوشش مشاهده‌شده یکسان می‌شد، این نماد چه رتبه‌ای می‌گرفت. این اعداد امتیاز رسمی " +
			"نیستند و مبنای تصمیم قرار نمی‌گیرند؛ فقط نشان می‌دهند رتبهٔ خام تا چه حد به تفاوت پوشش داده حساس است",
		"status_legend": gin.H{
			rankStatusBuyReview: rankStatusLabels[rankStatusBuyReview],
			rankStatusWait:      rankStatusLabels[rankStatusWait],
			rankStatusWeak:      rankStatusLabels[rankStatusWeak],
		},
		"snapshot_consistency": snapshotConsistencyOf(b),
		"experimental_bundle": gin.H{
			"active": expDir != "",
			"dir":    expDir,
			"note":   "پوشش بنیادی و ارزندگی با داده‌های تکمیلی کدال محاسبه شده است؛ تاریخ رتبه‌بندی و محور شرایط ورود همان تاریخ اعلام‌شدهٔ بسته است.",
		},
		"price_source": priceSourceMeta(pxAvail, pxNote),
		"ranked":       ranked,
		"unscored":     unscored,
		"sources": gin.H{
			"q": gin.H{"as_of": qvtStr(b.Q, "as_of"), "sha256": b.qSHA},
			"v": gin.H{"as_of": qvtStr(b.V, "as_of"), "cutoff": qvtStr(b.V, "cutoff"), "sha256": b.vSHA},
			"t": gin.H{"as_of": qvtStr(b.T, "as_of"), "cutoff": qvtStr(b.T, "cutoff"), "sha256": b.tSHA},
		},
	})
}
