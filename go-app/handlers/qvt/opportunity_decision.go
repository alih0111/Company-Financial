package qvt

import (
	"fmt"
	"strings"
)

// ─────────────────────────────────────────────────────────────────────────────
// لایهٔ تصمیم اقتصادی برد فرصت‌ها (گام ۲-ک-۸) — ارزیابی مستقل چهار موضوع:
//   (۱) کفایت/اعتبار شواهد (گیت‌های ۲-ک-۷: پوشش، همتا، دروازه ریسک، تازگی)
//   (۲) کیفیت واقعی کسب‌وکار (Q)   (۳) ارزندگی قابل دفاع (V)   (۴) ورود (T)
//
// اصل پایه: «داشتن اطلاعات معتبر» با «جذاب بودن فرصت» یکی نیست. شرکت واجد
// گیت‌ها خودکار جذاب نیست؛ باید ترکیب قابل دفاع بنیادی + ارزندگی + ورود داشته
// باشد. خروجی می‌تواند صفر نامزد جذاب داشته باشد — و این نتیجهٔ صادقانه است.
//
// هیچ امتیاز ترکیبی جدیدی از ۱۰۰ ساخته نمی‌شود؛ هیچ وزن رسمی تغییر نمی‌کند؛
// مفقود هرگز صفر فرض نمی‌شود. همهٔ آستانه‌ها «سیاست آزمایشی نسخه‌دار و آشکار»
// این فایل‌اند (opportunity-decision-policy-v1)، در پاسخ API منتشر می‌شوند و
// حساسیت نتایج به آن‌ها در گزارش گام ۲-ک-۸ سنجیده شده است. هیچ ادعای
// اثبات آماری سودآوری وجود ندارد؛ خروجی فقط «نامزد بررسی» است.
//
// معنای اقتصادی هر خواندن (از قرارداد واقعی آرتیفکت‌ها استخراج شد):
//   - امتیاز هر فاکتور percentile_combined در [0,1] است و جهت مطلوب آن از
//     قبل در پرسنتایل اعمال شده (direction): عدد بالاتر = وضعیت بهتر نسبی
//     در جمعیت نرمال‌سازی همان محور. پس «بالاتر» بی‌معنای بهترِ مطلق است و
//     فقط جایگاه نسبی در جمعیت خانواده/بازار را می‌گوید.
//   - roe_level (وزن ۷، ضروری، بالاتر بهتر): سودآوری؛ margins (۶): حاشیهٔ
//     سود؛ leverage/interest_coverage: ریسک ساختار سرمایه؛ cash_conversion
//     و earnings_quality: کیفیت سود. roe_stability و margin_trend عمداً
//     خارج از دستهٔ ۲-B-5 هستند (not_implemented) و اینجا هم استفاده و هم
//     جایگزین نمی‌شوند — محدودیت صادقانه ثبت می‌شود.
//   - V: P/E فقط با سود TTM مثبت (زیان‌ده هرگز «ارزان» خوانده نمی‌شود)،
//     P/B فقط با حقوق صاحبان سهام مثبت؛ خارج از نوار اعتبار V1 فقط هشدار
//     می‌گیرد. میانگینِ سادهٔ پرسنتایل سه عامل، «خوانش ارزندگی» است —
//     نه امتیاز جدید: فقط میانگین‌گیری شفاف از همان پرسنتایل‌های رسمی.
//   - T: مومنتوم روی سری تعدیل‌شدهٔ واقعی بازار؛ نقدشوندگی ارزش معاملات
//     روزانهٔ واقعی است (ریال) — کف مطلق آن سیاست این فایل است.
// ─────────────────────────────────────────────────────────────────────────────

// boardDecisionPolicy سیاست تصمیم نسخه‌دار — همهٔ آستانه‌ها آشکار و منتشرشده.
type boardDecisionPolicy struct {
	Version string `json:"version"`

	// بنیادی (Q) — پرسنتایل عوامل رسمی
	QStrongRoe    float64 `json:"q_strong_roe"`    // roe_level ≥ این → سودآوری قوی
	QWeakRoe      float64 `json:"q_weak_roe"`      // roe_level < این → بنیادی ضعیف
	QStrongMargin float64 `json:"q_strong_margin"` // margins ≥ این برای «قوی»
	QSafetyMin    float64 `json:"q_safety_min"`    // حداقل یکی از اهرم/پوشش بهره ≥ این برای «قوی»
	QWeakFactor   float64 `json:"q_weak_factor"`   // آستانهٔ «فاکتور ضعیف» برای قاعدهٔ گستردگی
	QWeakFactorN  int     `json:"q_weak_factor_n"` // ≥ این تعداد از ۴ عامل هسته زیر آستانه → ضعیف

	// کیفیت سود (Q) — گام ۲-ک-۹: تبدیل نقد، ضعف پنهان‌شده پشت ROE قوی را آشکار می‌کند
	QCashMin float64 `json:"q_cash_min"` // پرسنتایل cash_conversion < این → قید کیفیت تبدیل نقد (جلوگیری از پنهان‌شدن ضعف بنیادی)

	// ارزندگی (V) — میانگین سادهٔ پرسنتایل عوامل مشاهده‌شده
	VCheap       float64 `json:"v_cheap"`        // میانگین ≥ این → ارزان نسبی
	VExpensive   float64 `json:"v_expensive"`    // میانگین < این → گران نسبی
	VMultipleMin float64 `json:"v_multiple_min"` // برای «قابل دفاع»، P/E یا P/B هم ≥ این (ارزندگی چندگانه فقط P/S-محور کافی نیست)
	// گام ۲-ک-۹: چندگانهٔ پشتیبان باید گروه نرمال‌سازی صنعتی کافی داشته باشد
	VMinSectorSupport int `json:"v_min_sector_support"` // n_valid_sector چندگانهٔ پشتیبان ≥ این

	// ورود (T)
	TMomentumOK      float64 `json:"t_momentum_ok"`      // مومنتوم ۶ماههٔ نسبی ≥ این → ورود مناسب
	TMomentumHostile float64 `json:"t_momentum_hostile"` // زیر این و همزمان RS زیر آستانه → ورود نامساعد
	TRsHostile       float64 `json:"t_rs_hostile"`
	TLiqFloorRial    float64 `json:"t_liq_floor_rial"` // کف مطلق نقدشوندگی (میانگین ارزش معامله روزانه، ریال)

	// متن سیاست — آشکار، نه پنهان
	Note string `json:"note"`
}

func defaultBoardDecisionPolicy() boardDecisionPolicy {
	return boardDecisionPolicy{
		Version: "opportunity-decision-policy-v2",
		// Q — روی توزیع واقعی ۶۲ شرکت سه‌محوری کالیبره شد؛ ±0.05 حساسیت
		// ناچیز روی گروه جذاب دارد (گزارش ۲-ک-۸، تحلیل حساسیت).
		QStrongRoe: 0.65, QWeakRoe: 0.35, QStrongMargin: 0.50, QSafetyMin: 0.35,
		QWeakFactor: 0.20, QWeakFactorN: 2,
		// Q(کیفیت سود) — گام ۲-ک-۹: پایین‌ترین دو پنجم جمعیت خانواده برای
		// تبدیل نقد = ضعف نسبی مهم. شرکتی که تنها بخش کمی از سود دفتری را به
		// جریان نقد عملیاتی تبدیل می‌کند نباید با اتکای ROE قوی «جذاب بدون
		// قید» خوانده شود. حساسیت در گزارش: 0.30 (بوعلی بی‌قید می‌ماند) /
		// 0.40 (پایه) / 0.50.
		QCashMin: 0.40,
		// V — تنها آستانه‌ای که شمارش گروه جذاب به آن حساس است:
		// 0.55→۲ نامزد، 0.60→۱ نامزد، 0.65→۰ نامزد (مستند در گزارش).
		VCheap: 0.60, VExpensive: 0.40, VMultipleMin: 0.50,
		// V(همتا) — چندگانهٔ پشتیبان ارزندگی باید حداقل ۵ هم‌صنعت معتبر در
		// جمعیت نرمال‌سازی داشته باشد؛ وگرنه رتبهٔ نسبی متکی به نمونهٔ کوچک است.
		VMinSectorSupport: 5,
		// T — مومنتوم ۶ماههٔ نسبی؛ کف نقدشوندگی ۱۰ میلیارد ریال در روز
		// (کمترین شرکت سه‌محوری فعلی ~۲۷ میلیارد ریال — کف امروز کسی را حذف
		// نمی‌کند و صرفاً محافظ snapshotهای بعدی است).
		TMomentumOK: 0.40, TMomentumHostile: 0.25, TRsHostile: 0.30, TLiqFloorRial: 10e9,
		Note: "سیاست آزمایشی آشکار این گام — هیچ آستانه‌ای پنهان نیست؛ " +
			"پرسنتایل‌ها از امتیازهای رسمی آرتیفکت می‌آیند و هیچ امتیاز جدیدی ساخته نمی‌شود؛ " +
			"خروجی فقط «نامزد بررسی» است، نه اثبات آماری سودآوری و نه توصیه خرید/فروش. " +
			"نسخهٔ ۲ (گام ۲-ک-۹) قید کیفیت تبدیل نقد و کفایت گروه همتای چندگانهٔ پشتیبان را افزود " +
			"تا ضعف بنیادی پشت ROE قوی پنهان نشود؛ رفتار نسخهٔ ۱ برای مقایسه حفظ شده است.",
	}
}

// boardDecisionPolicyV1 سیاست گام ۲-ک-۸ — فقط برای مقایسهٔ رفتار نسخهٔ قبلی در
// تست و گزارش (بدون قید کیفیت نقد و بدون کف همتای چندگانه). endpoint منتشرشده
// همیشه نسخهٔ جاری (v2) را می‌سازد.
func boardDecisionPolicyV1() boardDecisionPolicy {
	p := defaultBoardDecisionPolicy()
	p.Version = "opportunity-decision-policy-v1"
	p.QCashMin = 0
	p.VMinSectorSupport = 0
	p.Note = "سیاست گام ۲-ک-۸ (بدون قید کیفیت نقد و بدون کف همتای چندگانهٔ پشتیبان) — فقط برای مقایسهٔ نسخه‌ها"
	return p
}

// boardFactorStat خلاصهٔ یک فاکتور از آرتیفکت — فقط چیزی که تصمیم می‌خواند.
type boardFactorStat struct {
	Score     *float64 `json:"score"`
	RawValue  *float64 `json:"raw_value"`
	RawStatus string   `json:"raw_status"`
	Weight    float64  `json:"weight"`
	NSector   *int     `json:"n_valid_sector"` // پشتیبانی جمعیت نرمال‌سازی صنعتی (برای اعتبار چندگانه)
	Warnings  []string `json:"warnings,omitempty"`
}

func boardFactorStats(cm map[string]any) map[string]boardFactorStat {
	out := map[string]boardFactorStat{}
	factors, _ := cm["factors"].(map[string]any)
	for id, fv := range factors {
		f, _ := fv.(map[string]any)
		if f == nil {
			continue
		}
		st := boardFactorStat{RawStatus: qvtStr(f, "raw_status")}
		if s, ok := qvtFloat(f, "score"); ok {
			st.Score = &s
		}
		if rv, ok := qvtFloat(f, "raw_value"); ok {
			st.RawValue = &rv
		}
		if w, ok := qvtFloat(f, "weight"); ok {
			st.Weight = w
		}
		if ns, ok := qvtFloat(f, "n_valid_sector"); ok {
			n := int(ns)
			st.NSector = &n
		}
		st.Warnings = qvtStrSlice(f, "warnings")
		out[id] = st
	}
	return out
}

// نتیجهٔ تصمیم برای یک شرکت — همهٔ اعداد قابل ردیابی به آرتیفکت همان snapshot.
type boardDecision struct {
	Fundamental       string   `json:"fundamental"` // strong | acceptable | weak | insufficient
	FundamentalLabel  string   `json:"fundamental_label"`
	FundamentalNote   []string `json:"fundamental_note"` // اعداد واقعی
	RoePct            *float64 `json:"roe_pct"`          // پرسنتایل عوامل هسته Q — جدا از متن
	MarginPct         *float64 `json:"margin_pct"`
	LevPct            *float64 `json:"leverage_pct"`
	IcPct             *float64 `json:"interest_coverage_pct"`
	CashConversionPct *float64 `json:"cash_conversion_pct"` // پرسنتایل تبدیل نقد (گام ۲-ک-۹)
	ValueMean         *float64 `json:"value_mean"`          // میانگین سادهٔ پرسنتایل عوامل V مشاهده‌شده
	ValueCheap        bool     `json:"value_cheap"`
	ValueDefensible   bool     `json:"value_defensible"` // ارزان + گروه همتای معتبر + تکیه بر P/E یا P/B
	ValueLabel        string   `json:"value_label"`
	ValueNote         []string `json:"value_note"`
	ValueBasisNote    string   `json:"value_basis_note,omitempty"` // هشدار مبنای سرمایه/قیمت در ارزندگی
	Entry             string   `json:"entry"`                      // ok | neutral | hostile | insufficient
	EntryLabel        string   `json:"entry_label"`
	EntryNote         []string `json:"entry_note"`
	Attractive        bool     `json:"attractive"`
	// گام ۲-ک-۹ — قیدهای اقتصادی/اعتباری که «جذاب بدون قید» را ناممکن می‌کنند
	Conditional        bool     `json:"conditional"`
	ConditionalReasons []string `json:"conditional_reasons"`
	NegOperatingProfit bool     `json:"negative_operating_profit"`
	Blockers           []string `json:"blockers"`    // چرا الان جذاب نیست — ترتیبی و عددی
	ReviewWhen         []string `json:"review_when"` // شرایط پایش و بررسی مجدد — سنجش‌پذیر
}

const (
	boardFundStrong       = "strong"
	boardFundAcceptable   = "acceptable"
	boardFundWeak         = "weak"
	boardFundInsufficient = "insufficient"

	boardEntryOK           = "ok"
	boardEntryNeutral      = "neutral"
	boardEntryHostile      = "hostile"
	boardEntryInsufficient = "insufficient"
)

var boardFundLabels = map[string]string{
	boardFundStrong: "قوی", boardFundAcceptable: "قابل قبول",
	boardFundWeak: "ضعیف", boardFundInsufficient: "شواهد ناکافی",
}
var boardEntryLabels = map[string]string{
	boardEntryOK: "مناسب", boardEntryNeutral: "خنثی",
	boardEntryHostile: "نامساعد", boardEntryInsufficient: "شواهد ناکافی",
}

// hasWarn پیشوند هشدار را در فاکتور جست‌وجو می‌کند.
func hasWarn(st boardFactorStat, prefix string) bool {
	for _, w := range st.Warnings {
		if strings.HasPrefix(w, prefix) {
			return true
		}
	}
	return false
}

func fmtScore(s *float64) string {
	if s == nil {
		return "مفقود"
	}
	return fmt.Sprintf("%.2f", *s)
}

// boardDecideQ کیفیت بنیادی را فقط از عوامل رسمی Q می‌سازد. roe_stability و
// margin_trend (خارج از دستهٔ ۲-B-5) خوانده یا جایگزین نمی‌شوند.
func boardDecideQ(pol boardDecisionPolicy, qcm map[string]any) (string, []string) {
	f := boardFactorStats(qcm)
	roe, mar := f["roe_level"], f["margins"]
	lev, ic := f["leverage"], f["interest_coverage"]
	note := []string{}
	add := func(format string, a ...any) {
		note = append(note, fmt.Sprintf(format, a...))
	}
	if roe.Score != nil {
		add("پرسنتایل roe_level = %s (وزن ۷ از ۴۰، جمعیت خانواده)", fmtScore(roe.Score))
	}
	if mar.Score != nil {
		add("پرسنتایل margins = %s (وزن ۶)", fmtScore(mar.Score))
	}
	if lev.Score != nil {
		add("پرسنتایل leverage = %s (وزن ۴)", fmtScore(lev.Score))
	}
	if ic.Score != nil {
		add("پرسنتایل interest_coverage = %s (وزن ۳)", fmtScore(ic.Score))
	}
	if f["roe_stability"].Score == nil && f["margin_trend"].Score == nil {
		add("roe_stability و margin_trend خارج از دستهٔ ۲-B-5 هستند (not_implemented) — پایداری سود در این snapshot قابل سنجش نیست")
	}
	// زیان‌دهی: از قرارداد V — P/E با سود منفی محاسبه نمی‌شود
	if pe := f["pe"]; hasWarn(pe, "loss_maker") {
		return boardFundWeak, append(note, "زیان‌ده (سود TTM منفی) — P/E محاسبه‌نشده؛ زیان‌دهی ضعف بنیادی است")
	}
	// سود عملیاتی منفی — روی همهٔ فاکتورهای Q جست‌وجو می‌شود (نه فقط پوشش بهره)
	// تا ضعف کیفیت سود در هیچ فاکتوری پنهان نماند. ترتیب ثابت برای تکرارپذیری.
	for _, fid := range []string{"cash_conversion", "earnings_quality", "interest_coverage",
		"leverage", "margins", "revenue_growth", "roe_level"} {
		if hasWarn(f[fid], "negative_operating_profit") {
			return boardFundWeak, append(note,
				fmt.Sprintf("سود عملیاتی منفی (هشدار ثبت‌شده در فاکتور %s) — سود خالص احتمالی از اقلام غیرعملیاتی/غیرتکراری؛ ضعف بنیادی واقعی", fid))
		}
	}
	// قاعدهٔ گستردگی: ≥2 از ۴ عامل هسته زیر آستانهٔ ضعف
	weakN := 0
	for _, st := range []boardFactorStat{roe, mar, lev, ic} {
		if st.Score != nil && *st.Score < pol.QWeakFactor {
			weakN++
		}
	}
	if weakN >= pol.QWeakFactorN {
		return boardFundWeak, append(note, fmt.Sprintf("%d از ۴ عامل هسته (سودآوری/حاشیه/اهرم/پوشش) پرسنتایل زیر %.2f دارند", weakN, pol.QWeakFactor))
	}
	if roe.Score != nil && *roe.Score < pol.QWeakRoe {
		return boardFundWeak, append(note, fmt.Sprintf("پرسنتایل roe_level زیر آستانهٔ %.2f است", pol.QWeakRoe))
	}
	if roe.Score == nil && mar.Score != nil && *mar.Score < pol.QWeakRoe {
		return boardFundWeak, append(note, "roe_level مفقود و پرسنتایل margins زیر آستانهٔ ضعف است")
	}
	if roe.Score == nil && mar.Score == nil {
		return boardFundInsufficient, append(note, "نه roe_level و نه margins مشاهده نشده — کیفیت بنیادی قابل ارزیابی نیست")
	}
	// قوی: سودآوری بالا + حاشیهٔ قابل قبول + ساختار سرمایهٔ دست‌کم قابل قبول
	strongOK := roe.Score != nil && *roe.Score >= pol.QStrongRoe &&
		mar.Score != nil && *mar.Score >= pol.QStrongMargin
	safetyOK := (lev.Score != nil && *lev.Score >= pol.QSafetyMin) ||
		(ic.Score != nil && *ic.Score >= pol.QSafetyMin)
	if strongOK && safetyOK {
		return boardFundStrong, note
	}
	return boardFundAcceptable, note
}

// boardDecideV ارزندگی را می‌خواند: میانگین سادهٔ پرسنتایل عوامل V مشاهده‌شده
// + قابلیت دفاع (گروه همتا + تکیه بر چندگانه‌های سخت P/E یا P/B). زیان‌ده
// هرگز «ارزان قابل دفاع» نمی‌شود.
func boardDecideV(pol boardDecisionPolicy, vcm map[string]any, comparableValid bool) (*float64, bool, bool, string, string, []string) {
	f := boardFactorStats(vcm)
	pe, pb, ps := f["pe"], f["pb"], f["ps"]
	note := []string{}
	add := func(format string, a ...any) {
		note = append(note, fmt.Sprintf(format, a...))
	}
	if pe.RawValue != nil {
		add("P/E خام = %s (پرسنتایل %s)", boardTrimFloat(*pe.RawValue), fmtScore(pe.Score))
	} else if len(pe.Warnings) > 0 {
		add("P/E محاسبه نشده: %s", headWarn(pe.Warnings))
	}
	if pb.RawValue != nil {
		add("P/B خام = %s (پرسنتایل %s)", boardTrimFloat(*pb.RawValue), fmtScore(pb.Score))
	}
	if ps.RawValue != nil {
		add("P/S خام = %s (پرسنتایل %s)", boardTrimFloat(*ps.RawValue), fmtScore(ps.Score))
	}
	basis := ""
	for _, st := range []boardFactorStat{pe, pb, ps} {
		if hasWarn(st, "share_snapshot_older_than_price") {
			basis = "تاریخچهٔ سهام قدیمی‌تر از قیمت ترید است و شواهد تغییرات سرمایه بین دو تاریخ ثبت نشده — مبنای بازار در ارزندگی نیازمند بررسی"
			break
		}
	}
	if basis != "" {
		add(basis)
	}
	var mean *float64
	sum, n := 0.0, 0
	for _, st := range []boardFactorStat{pe, pb, ps} {
		if st.Score != nil {
			sum += *st.Score
			n++
		}
	}
	if n > 0 {
		m := sum / float64(n)
		mean = &m
		label := "میانه"
		cheap := m >= pol.VCheap
		if cheap {
			label = "ارزان نسبی"
		} else if m < pol.VExpensive {
			label = "گران نسبی"
		}
		// پشتیبانی جمعیت نرمال‌سازی صنعتی چندگانهٔ پشتیبان (گام ۲-ک-۹):
		// اگر چندگانه‌ای که ارزندگی را «قابل دفاع» می‌کند در صنعت خود کمتر از
		// کف سیاست هم‌صنعت معتبر داشته باشد، رتبهٔ نسبی متکی به نمونهٔ کوچک است
		// و قابل دفاع تأیید نمی‌شود.
		supportOK := func(st boardFactorStat) bool {
			if pol.VMinSectorSupport <= 0 || st.NSector == nil {
				return true
			}
			return *st.NSector >= pol.VMinSectorSupport
		}
		peStrong := pe.Score != nil && *pe.Score >= pol.VMultipleMin
		pbStrong := pb.Score != nil && *pb.Score >= pol.VMultipleMin
		support := (peStrong && supportOK(pe)) || (pbStrong && supportOK(pb))
		defensible := cheap && comparableValid &&
			!hasWarn(pe, "loss_maker") && support
		if cheap && !comparableValid {
			add("ارزندگی فقط در جمعیت خانواده سنجیده شده — گروه مقایسهٔ درون‌صنعت معتبر نیست، پس «قابل دفاع نسبی» تأیید نمی‌شود")
		}
		if cheap && comparableValid && !support && (peStrong || pbStrong) {
			low := "P/E"
			ns := pe.NSector
			if !peStrong || !supportOK(pe) {
				low, ns = "P/B", pb.NSector
			}
			nstr := "؟"
			if ns != nil {
				nstr = fmt.Sprintf("%d", *ns)
			}
			add("چندگانهٔ پشتیبان ارزندگی (%s) در جمعیت صنعتی فقط %s هم‌صنعت معتبر دارد (کف سیاست %d) — رتبهٔ نسبی متکی به نمونهٔ کوچک، قابل دفاع تأیید نشد",
				low, nstr, pol.VMinSectorSupport)
		}
		if hasWarn(pe, "loss_maker") {
			add("زیان‌ده — ارزندگی ظاهری از شاخص‌های کتاب/فروش معیار دفاع ارزندگی سودمحور نیست")
		}
		return mean, cheap, defensible, label, basis, note
	}
	return nil, false, false, "شواهد ناکافی", "", append(note, "هیچ‌یک از P/E·P/B·P/S مشاهده نشده — ارزندگی قابل ارزیابی نیست")
}

// boardDecideT شرایط ورود: مومنتوم ۶ماههٔ نسبی + نقدشوندگی مطلق واقعی.
func boardDecideT(pol boardDecisionPolicy, tcm map[string]any) (string, []string) {
	f := boardFactorStats(tcm)
	m6, rs, liq := f["momentum_6m_rel"], f["relative_strength_6m_sector"], f["liquidity"]
	note := []string{}
	add := func(format string, a ...any) {
		note = append(note, fmt.Sprintf(format, a...))
	}
	if m6.RawValue == nil || m6.Score == nil {
		add("مومنتوم ۶ماههٔ نسبی مشاهده نشده — پنجرهٔ محاسبه ناکافی؛ ورود قابل قضاوت نیست")
		return boardEntryInsufficient, note
	}
	add("اختلاف بازده با بازار در بازهٔ هدف ۶ماهه = %s واحد درصد (پرسنتایل %s)", pctFmt(*m6.RawValue), fmtScore(m6.Score))
	if liq.RawValue != nil {
		add("نقدشوندگی واقعی ≈ %s میلیارد ریال ارزش معامله روزانه (پرسنتایل %s)", bnFmt(*liq.RawValue), fmtScore(liq.Score))
		if *liq.RawValue < pol.TLiqFloorRial {
			add("نقدشوندگی زیر کف مطلق سیاست (%s میلیارد ریال) — ورود برای بررسی جدی قابل دفاع نیست", bnFmt(pol.TLiqFloorRial))
			return boardEntryInsufficient, note
		}
	} else {
		add("نقدشوندگی مشاهده نشده — ورود قابل قضاوت نیست")
		return boardEntryInsufficient, note
	}
	if rs.RawValue != nil {
		add("اختلاف بازده با صنعت در بازهٔ هدف ۶ماهه = %s واحد درصد (پرسنتایل %s)", pctFmt(*rs.RawValue), fmtScore(rs.Score))
	}
	if *m6.Score >= pol.TMomentumOK {
		return boardEntryOK, note
	}
	if *m6.Score < pol.TMomentumHostile && rs.Score != nil && *rs.Score < pol.TRsHostile {
		add("مومنتوم و قدرت نسبی هر دو پایین‌تر از آستانه‌های سیاست — روند بازار خلاف جهت نامزد است")
		return boardEntryHostile, note
	}
	return boardEntryNeutral, note
}

// boardDecide ترکیب سه ارزیابی مستقل + گیت‌های شواهد → تصمیم نامزد.
// هیچ پیچیدگی پنهانی نیست: blockers ترتیبی و عددی‌اند و همان‌هایی که در
// «چه زمانی ارزش بررسی مجدد دارد؟» به شرط سنجش‌پذیر تبدیل می‌شوند.
func boardDecide(pol boardDecisionPolicy, qcm, vcm, tcm map[string]any, comparableValid, freshOK bool) *boardDecision {
	d := &boardDecision{Blockers: []string{}, ReviewWhen: []string{}, ConditionalReasons: []string{}}
	d.Fundamental, d.FundamentalNote = boardDecideQ(pol, qcm)
	d.FundamentalLabel = boardFundLabels[d.Fundamental]
	qf := boardFactorStats(qcm)
	if qf != nil {
		d.RoePct = qf["roe_level"].Score
		d.MarginPct = qf["margins"].Score
		d.LevPct = qf["leverage"].Score
		d.IcPct = qf["interest_coverage"].Score
		d.CashConversionPct = qf["cash_conversion"].Score
	}
	// سود عملیاتی منفی (برای علامت‌گذاری مستقل در خروجی)
	for _, fid := range []string{"cash_conversion", "earnings_quality", "interest_coverage",
		"leverage", "margins", "revenue_growth", "roe_level"} {
		if hasWarn(qf[fid], "negative_operating_profit") {
			d.NegOperatingProfit = true
			break
		}
	}
	var basis string
	d.ValueMean, d.ValueCheap, d.ValueDefensible, d.ValueLabel, basis, d.ValueNote = boardDecideV(pol, vcm, comparableValid)
	d.ValueBasisNote = basis
	d.Entry, d.EntryNote = boardDecideT(pol, tcm)
	d.EntryLabel = boardEntryLabels[d.Entry]

	// قیدهای کیفیت (گام ۲-ک-۹): ضعف بنیادی که پشت ROE قوی پنهان می‌ماند،
	// «جذاب بدون قید» را ناممکن می‌کند. این‌ها مانع قطعی (blocker) نیستند
	// چون داده معتبر و رتبهٔ رسمی است؛ اما اجازه نمی‌دهند شرکت بی‌قید جذاب شود.
	cashWeak := false
	if pol.QCashMin > 0 && d.CashConversionPct != nil && *d.CashConversionPct < pol.QCashMin {
		cashWeak = true
		d.ConditionalReasons = append(d.ConditionalReasons, fmt.Sprintf(
			"کیفیت تبدیل نقد ضعیف: پرسنتایل cash_conversion = %s زیر کف سیاست %.2f — سود دفتری به‌اندازهٔ کافی به جریان نقد عملیاتی تبدیل نشده",
			fmtScore(d.CashConversionPct), pol.QCashMin))
	}
	if d.NegOperatingProfit {
		d.ConditionalReasons = append(d.ConditionalReasons, "سود عملیاتی منفی ثبت‌شده — سود خالص از اقلام غیرعملیاتی است")
	}
	d.Conditional = cashWeak || d.NegOperatingProfit

	// ترتیب blockers: بنیادی → ارزندگی → ورود → همتا → تازگی
	switch d.Fundamental {
	case boardFundWeak:
		d.Blockers = append(d.Blockers, "کیفیت بنیادی ضعیف ارزیابی شد ("+lastNote(d.FundamentalNote)+")")
	case boardFundInsufficient:
		d.Blockers = append(d.Blockers, "شواهد بنیادی برای ارزیابی کیفیت کافی نیست")
	}
	if d.Fundamental != boardFundWeak && d.Fundamental != boardFundInsufficient {
		if !d.ValueCheap {
			d.Blockers = append(d.Blockers, fmt.Sprintf("ارزندگی ارزان نسبی نیست: میانگین پرسنتایل P/E·P/B·P/S = %s (آستانهٔ سیاست %.2f)", fmtScore(d.ValueMean), pol.VCheap))
		} else if !d.ValueDefensible {
			d.Blockers = append(d.Blockers, "ارزندگی ارزان است اما قابل دفاع نسبی تأیید نشد (گروه همتا یا تکیهٔ چندگانه‌های سخت ناکافی)")
		}
	}
	switch d.Entry {
	case boardEntryHostile:
		d.Blockers = append(d.Blockers, "شرایط ورود نامساعد: مومنتوم و قدرت نسبی زیر آستانه‌های سیاست")
	case boardEntryInsufficient:
		d.Blockers = append(d.Blockers, "شواهد ورود ناکافی: مومنتوم یا نقدشوندگی قابل قضاوت نیست")
	case boardEntryNeutral:
		d.Blockers = append(d.Blockers, "شرایط ورود خنثی: مومنتوم ۶ماههٔ نسبی زیر آستانهٔ مناسب است اما هنوز نامساعد نیست")
	}
	if !comparableValid && d.Fundamental != boardFundWeak && d.Fundamental != boardFundInsufficient {
		d.Blockers = append(d.Blockers, "گروه مقایسهٔ درون‌صنعت معتبر نیست — ارزندگی نسبی قابل تأیید نیست و هیچ رتبه نسبی صادر نمی‌شود")
	}
	if !freshOK {
		d.Blockers = append(d.Blockers, "تازگی قیمت با کنترل مستقل تأیید نشده — نامزد فرصت «الان» نمی‌شود")
	}
	d.Attractive = len(d.Blockers) == 0 && !d.Conditional &&
		(d.Fundamental == boardFundStrong || d.Fundamental == boardFundAcceptable)
	return d
}

func lastNote(notes []string) string {
	if len(notes) == 0 {
		return ""
	}
	return notes[len(notes)-1]
}

func headWarn(ws []string) string {
	if len(ws) == 0 {
		return ""
	}
	s := ws[0]
	if i := strings.Index(s, ":"); i > 0 {
		s = s[i+1:]
	}
	return strings.TrimSpace(s)
}

func boardTrimFloat(v float64) string {
	if v >= 1000 {
		return fmt.Sprintf("%.0f", v)
	}
	return fmt.Sprintf("%.1f", v)
}

func pctFmt(v float64) string {
	return fmt.Sprintf("%+.1f", v*100)
}

func bnFmt(v float64) string {
	return fmt.Sprintf("%.0f", v/1e9)
}
