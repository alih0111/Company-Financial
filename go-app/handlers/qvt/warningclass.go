package qvt

// طبقه‌بندی واحد هشدارهای ثبت‌شده در آرتیفکت‌ها — مالکیت واحد (گام ۲-ح-۱).
//
// هر نوع هشدار دقیقاً یک مالک دارد: یک حوزه در Risk Gate (data /
// fundamental / market) و حداکثر یک بُعد در Data Confidence. طبقه‌بندی فقط از
// متن شواهد ثبت‌شده در آرتیفکت پیروی می‌کند:
//   - هیچ نوع هشداری دور ریخته نمی‌شود (ناشناخته‌ها با برچسب «ناشناخته» می‌مانند)
//   - هیچ هشداری بدون مدرک، «خطای قطعی داده» معرفی نمی‌شود
//   - ریسک اقتصادی (زیان‌دهی) و نسبت‌های ارزندگی خارج از بازه، هشدار داده
//     نیستند — از یکپارچگی داده جدا شده‌اند و به حوزه بنیادی/ارزندگی می‌روند
//   - سازگاری تعداد سهام و قیمت به‌تنهایی خطای قطعی نیست: «نیازمند بررسی» است
//
// شدت‌ها (vocab منتشرشده در qvtRiskGateRules):
//   proven_data_error  — خطای اثبات‌شده داده؛ فقط از شواهد خودِ داده (B2)
//   proven_policy_violation — نقض اثبات‌شده یک سیاست مسدودسازی صریح (B1 با
//                        کنترل مستقل منبع قیمت)؛ از «خطای داده» جدا است
//   suspected_data_issue — مشکوک به مشکل داده، با شواهد ثبت‌شده
//   consistency_review — نیازمند بررسی سازگاری؛ خطای قطعی نیست
//   economic_risk      — ریسک اقتصادی واقعی؛ نه الزاماً خطای اطلاعات
//   valuation_band     — خارج از بازه مرجع ارزندگی؛ خطای داده نیست
//   market_structure   — نکته ساختاری بازار/نقدشوندگی
//   provenance_note    — نکته منشأ داده؛ قابل ردیابی
//   unknown            — ناشناخته؛ بدون ادعای خطا

import (
	"regexp"
	"strconv"
	"strings"
)

const (
	areaData        = "data"
	areaFundamental = "fundamental"
	areaMarket      = "market"

	sevProvenError   = "proven_data_error"
	sevProvenPolicy  = "proven_policy_violation"
	sevSuspect       = "suspected_data_issue"
	sevConsistency   = "consistency_review"
	sevEconomic      = "economic_risk"
	sevValuationBand = "valuation_band"
	sevMarketStruct  = "market_structure"
	sevProvenance    = "provenance_note"
	sevUnknown       = "unknown"

	effectBlocked = "blocked"
	effectReview  = "review_required"
	effectNone    = "none"
)

var sevLabels = map[string]string{
	sevProvenError:   "خطای اثبات‌شده داده",
	sevProvenPolicy:  "نقض اثبات‌شده سیاست تازگی قیمت — از خطای داده جدا است، اما طبق قاعده B1 مانع صریح است",
	sevSuspect:       "مشکوک به مشکل داده — با شواهد ثبت‌شده",
	sevConsistency:   "نیازمند بررسی سازگاری — خطای قطعی داده نیست",
	sevEconomic:      "ریسک اقتصادی واقعی — نه الزاماً خطای اطلاعات",
	sevValuationBand: "خارج از بازه مرجع ارزندگی — خطای داده نیست",
	sevMarketStruct:  "نکته ساختاری بازار/نقدشوندگی",
	sevProvenance:    "نکته منشأ داده — قابل ردیابی",
	sevUnknown:       "ناشناخته — بدون ادعای خطا",
}

// warnClass is the single published owner of one warning kind.
type warnClass struct {
	Area     string // data | fundamental | market
	Category string // «نوع» — توصیف کوتاه فارسی
	Severity string
	Effect   string // blocked | review_required | none
	Serious  bool   // در Data Confidence «هشدار جدی» (فقط مشکوک‌های جدی به مشکل داده)
	DCDim    string // بُعد اطمینان داده؛ "" یعنی یافته اطمینان داده نیست
	Reason   string // چرا این طبقه‌بندی
}

// warnKindMap — نگاشت منتشرشده و تک‌مالک. متن هر هشدار در آرتیفکت با
// «kind: شواهد» می‌آید؛ این جدول فقط معنای هر kind را بر اساس همان شواهد
// تثبیت می‌کند.
var warnKindMap = map[string]warnClass{
	"stale_price": {
		Area: areaData, Category: "تازگی قیمت مرجع نسبت به تاریخ snapshot",
		Severity: sevSuspect, Effect: effectReview, Serious: true, DCDim: "temporal",
		Reason: "قیمت مرجع قدیمی‌تر از خط‌مشی تازگی آرتیفکت گزارش شده است؛ مبنای سیاست «روز تقویمی» است (pilot_v2_value.py: (as_of − price_trade_date).days). ارتقا به «نقض اثبات‌شده سیاست» و مانع B1 فقط با کنترل مستقل از منبع واقعی قیمت ممکن است — بازخوانی عدد از متن هشدار اثبات مستقل نیست (گام ۲-ط-۱)",
	},
	"share_snapshot_older_than_price": {
		Area: areaData, Category: "سازگاری تعداد سهام با قیمت",
		Severity: sevConsistency, Effect: effectReview, Serious: false, DCDim: "temporal",
		Reason: "به‌تنهایی خطای قطعی داده نیست؛ متن آرتیفکت صراحتاً می‌گوید سازگاری «unprovable» است — وضعیت درست «نیازمند بررسی سازگاری تعداد سهام و قیمت» است، نه خطای اثبات‌شده",
	},
	"magnitude_anomaly": {
		Area: areaData, Category: "مقدار مالی خارج از بازه معقول ثبت‌شده",
		Severity: sevSuspect, Effect: effectReview, Serious: true, DCDim: "financial",
		Reason: "مشکوک به مشکل داده است؛ متن آرتیفکت آن را «kept as real data» ثبت کرده و تصمیم را به Risk Gate واگذار کرده — بدون مدرک خطا، مانع قطعی صادر نمی‌شود",
	},
	"suspected_unadjusted_gap": {
		Area: areaMarket, Category: "پرش مشکوک قیمت در سری تعدیل‌شده",
		Severity: sevSuspect, Effect: effectReview, Serious: true, DCDim: "market",
		Reason: "مشکوک به مشکل داده با شواهد عددی ثبت‌شده (تاریخ و درصد پرش)؛ علت می‌تواند اقدام شرکتی اعمال‌نشده یا حفره داده باشد و از داده موجود قابل تفکیک نیست",
	},
	"liquidity_window_composition": {
		Area: areaMarket, Category: "ترکیب پنجره نقدشوندگی",
		Severity: sevMarketStruct, Effect: effectReview, Serious: false, DCDim: "market",
		Reason: "نکته ساختاری بازار و شرایط ورود: جلسات بدون معامله داخل پنجره ثبت و شمرده شده‌اند — خطای داده نیست",
	},
	"verified_reopening_repricing": {
		Area: areaMarket, Category: "تغییر واقعی قیمت هنگام بازگشایی",
		Severity: sevMarketStruct, Effect: effectReview, Serious: false, DCDim: "market",
		Reason: "توقف معاملات و مرجع قیمت با منبع مستقل تطبیق یافته است؛ تغییر قیمت ریسک واقعی بازار است و به‌تنهایی مشکل اثبات‌شده داده نیست",
	},
	"shared_reference_before_calendar_window": {
		Area: areaMarket, Category: "بازهٔ واقعی بازده طولانی‌تر از بازهٔ هدف",
		Severity: sevMarketStruct, Effect: effectReview, Serious: false, DCDim: "temporal",
		Reason: "قیمت پایهٔ مشترک پیش از ابتدای بازهٔ تقویمی است؛ تاریخ واقعی شروع و پایان افشا می‌شود و این فاصله به‌تنهایی خطای داده نیست",
	},
	"order3_recovered_from_raw_letter": {
		Area: areaData, Category: "منشأ مقدار: بازیابی از نامه خام",
		Severity: sevProvenance, Effect: effectNone, Serious: false, DCDim: "provenance",
		Reason: "مقدار با شناسه نامه خام قابل ردیابی است؛ منشأ ثبت شده و به‌تنهایی نه خطای داده است و نه مانع",
	},
	"loss_maker": {
		Area: areaFundamental, Category: "زیان‌دهی TTM",
		Severity: sevEconomic, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "ریسک اقتصادی است نه خطای اطلاعات؛ موتور V نیز برای زیان‌ده P/E محاسبه نمی‌کند (متن آرتیفکت)",
	},
	"negative_operating_profit": {
		Area: areaFundamental, Category: "سود عملیاتی منفی",
		Severity: sevEconomic, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "ریسک اقتصادی واقعی است؛ متن آرتیفکت صراحتاً «kept as data» می‌گوید — اقتصاد شرکت، نه خطای ثبت داده",
	},
	"turned_to_loss": {
		Area: areaFundamental, Category: "تبدیل سود به زیان",
		Severity: sevEconomic, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "ریسک اقتصادی است؛ درصد منفی خروجی فرمول استاندارد تغییر است، نه خطای محاسبه (متن آرتیفکت)",
	},
	"pe_above_v1_valid_band": {
		Area: areaFundamental, Category: "نسبت P/E خارج از بازه مرجع",
		Severity: sevValuationBand, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "نسبت واقعی و معتبر است اما از بازه اعتبار موتور V1 خارج شده — هشدار محدوده ارزندگی/نیازمند بررسی نسبت، نه خطای یکپارچگی داده",
	},
	"pb_above_v1_valid_band": {
		Area: areaFundamental, Category: "نسبت P/B خارج از بازه مرجع",
		Severity: sevValuationBand, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "نسبت واقعی و معتبر است اما از بازه اعتبار موتور V1 خارج شده — هشدار محدوده ارزندگی/نیازمند بررسی نسبت، نه خطای یکپارچگی داده",
	},
	"ps_above_v1_valid_band": {
		Area: areaFundamental, Category: "نسبت P/S خارج از بازه مرجع",
		Severity: sevValuationBand, Effect: effectReview, Serious: false, DCDim: "",
		Reason: "نسبت واقعی و معتبر است اما از بازه اعتبار موتور V1 خارج شده — هشدار محدوده ارزندگی/نیازمند بررسی نسبت، نه خطای یکپارچگی داده",
	},
}

// unknownClass بر اساس منشأ فهرست (مالی/معاملاتی) مالک هشدار ناشناخته را
// می‌سازد: دور ریخته نمی‌شود، اما بدون مدرک خطای قطعی معرفی نمی‌شود.
func unknownClass(origin string) warnClass {
	if origin == "trading" {
		return warnClass{
			Area: areaMarket, Category: "هشدار ناشناخته (فهرست معاملاتی)",
			Severity: sevUnknown, Effect: effectReview, Serious: true, DCDim: "market",
			Reason: "نوع هشدار در جدول طبقه‌بندی ثبت نیست؛ نمایش داده می‌شود، بدون ادعای خطا محافظه‌کارانه نیازمند بررسی است",
		}
	}
	return warnClass{
		Area: areaData, Category: "هشدار ناشناخته (فهرست مالی)",
		Severity: sevUnknown, Effect: effectReview, Serious: true, DCDim: "financial",
		Reason: "نوع هشدار در جدول طبقه‌بندی ثبت نیست؛ نمایش داده می‌شود، بدون ادعای خطا محافظه‌کارانه نیازمند بررسی است",
	}
}

// warnEvidence یک هشدار ثبت‌شده با متن واقعی و طبقه‌بندی نهایی آن.
type warnEvidence struct {
	Kind, Text     string
	Axis           string // Q | V | T
	Origin         string // financial | trading
	Class          warnClass
	Unknown        bool
	StaleDays      int  // اعداد بازخوانی‌شده از متن ثبت‌شده — فقط برای نمایش
	StalePolicy    int  // «اثبات مستقل» نیست؛ قاعده B1 به کنترل منبع قیمت نیاز دارد
	StaleParseable bool // متن دو عدد داشت یا نه
}

// stalePriceRe متن واقعی هشدار stale_price را می‌خواند:
// «latest trade is 12 days before as_of (freshness policy 7 days)».
var stalePriceRe = regexp.MustCompile(`latest trade is (\d+) days before as_of \(freshness policy (\d+) days\)`)

// collectWarnings همه هشدارهای ثبت‌شده سه محور را با طبقه‌بندی واحد برمی‌گرداند.
// فقط‌خواندنی است؛ هیچ بلوکی را تغییر نمی‌دهد.
func collectWarnings(qcm, vcm, tcm map[string]any) []warnEvidence {
	axes := []struct {
		name string
		cm   map[string]any
	}{{"Q", qcm}, {"V", vcm}, {"T", tcm}}
	var out []warnEvidence
	for _, ax := range axes {
		if ax.cm == nil {
			continue
		}
		rg, ok := ax.cm["risk_gate"].(map[string]any)
		if !ok {
			continue
		}
		for origin, key := range map[string]string{"financial": "financial_warnings", "trading": "trading_warnings"} {
			arr, _ := rg[key].([]any)
			for _, wv := range arr {
				ws, ok := wv.(string)
				if !ok || strings.TrimSpace(ws) == "" {
					continue
				}
				kind := ws
				if i := strings.Index(ws, ":"); i >= 0 {
					kind = ws[:i]
				}
				e := warnEvidence{Kind: kind, Text: ws, Axis: ax.name, Origin: origin}
				cls, known := warnKindMap[kind]
				if known {
					e.Class = cls
				} else {
					e.Unknown = true
					e.Class = unknownClass(origin)
				}
				if kind == "stale_price" {
					if m := stalePriceRe.FindStringSubmatch(ws); m != nil {
						days, _ := strconv.Atoi(m[1])
						pol, _ := strconv.Atoi(m[2])
						e.StaleDays, e.StalePolicy, e.StaleParseable = days, pol, true
					}
					// توجه (گام ۲-ط-۱): این اعداد فقط بازخوانی متن ثبت‌شده‌اند و
					// هرگز وضعیت blocked نمی‌سازند — اثبات B1 فقط از کنترل
					// مستقل منبع قیمت (pricecheck.go) می‌آید.
				}
				out = append(out, e)
			}
		}
	}
	return out
}

// warnListSeen گزارش می‌دهد آیا کلید فهرست هشدار در بلوک risk_gate این محور
// اصلاً ثبت شده است یا نه — مبنای تفکیک «بررسی شد و چیزی نبود» از «بررسی ناممکن».
func warnListSeen(cm map[string]any, key string) bool {
	if cm == nil {
		return false
	}
	rg, ok := cm["risk_gate"].(map[string]any)
	if !ok {
		return false
	}
	_, present := rg[key]
	return present
}
