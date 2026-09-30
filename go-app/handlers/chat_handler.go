package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"go-app/integration"

	"github.com/gin-gonic/gin"
)

// chat_handler.go — دستیار چت سرمایه‌گذاری.
// موتور پاسخ مبتنی بر قاعده است و فقط از دیتای امتیاز کمی canonical تغذیه می‌کند؛
// اگر متغیرهای AI_CHAT_URL/AI_API_KEY/AI_MODEL تنظیم شده باشند، پاسخ با یک LLM
// مبتنی بر همان داده‌ها تولید می‌شود و در خطا به موتور قاعده‌ای برمی‌گردیم.

type chatIncomingMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatRequestBody struct {
	Messages []chatIncomingMessage `json:"messages"`
}

type chatResponseBody struct {
	Reply     string   `json:"reply"`
	Intent    string   `json:"intent"`
	ToolsUsed []string `json:"tools_used,omitempty"`
}

var factorLabelsFa = map[string]string{
	"SalesGrowth":           "رشد فروش ۱۲ماهه",
	"SalesGrowth3M":         "رشد فروش سه‌ماهه اخیر",
	"RevenueGrowth":         "رشد درآمد",
	"OperatingProfitGrowth": "رشد سود عملیاتی",
	"NetProfitGrowth":       "رشد سود خالص",
	"OperatingMargin":       "حاشیه سود عملیاتی",
	"NetMargin":             "حاشیه سود خالص",
	"MarginTrend":           "روند حاشیه سود",
	"InterestCoverage":      "پوشش هزینه مالی",
	"EarningsQuality":       "کیفیت سود",
	"PE":                    "ارزش‌گذاری (P/E)",
	"PS":                    "ارزش‌گذاری (P/S)",
	"PB":                    "ارزش‌گذاری (P/B)",
	"Liquidity":             "نقدشوندگی",
	"Stability":             "پایداری فروش",
	"LowVolatility":         "کم‌نوسانی قیمت",
	"Momentum":              "مومنتوم ۳۰روزه",
	"ROERank":               "بازده حقوق صاحبان سهام",
	"Leverage":              "کنترل اهرم مالی",
	"CurrentRatio":          "نسبت جاری",
	"CashConversion":        "تبدیل سود به نقد",
}

// factorReasonOrder ترتیب اهمیت فاکتورها در «دلیل پیشنهاد» را مشخص می‌کند.
var factorReasonOrder = []string{
	"SalesGrowth", "NetProfitGrowth", "OperatingProfitGrowth", "RevenueGrowth",
	"OperatingMargin", "NetMargin", "ROERank", "PE", "PS", "PB",
	"Momentum", "LowVolatility", "Stability", "Liquidity", "InterestCoverage",
}

func normalizeFaText(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	var b strings.Builder
	for _, r := range s {
		switch {
		case r == '\u200c' || r == '\u200e' || r == '\u200f':
			continue
		case unicode.Is(unicode.Mn, r):
			continue
		case unicode.IsPunct(r) || unicode.IsSymbol(r):
			b.WriteRune(' ')
		default:
			b.WriteRune(r)
		}
	}
	s = strings.ReplaceAll(b.String(), "ي", "ی")
	s = strings.ReplaceAll(s, "ك", "ک")
	return strings.Join(strings.Fields(s), " ")
}

func toFaDigits(s string) string {
	fa := []rune("۰۱۲۳۴۵۶۷۸۹")
	out := []rune(s)
	for i, r := range out {
		if r >= '0' && r <= '9' {
			out[i] = fa[r-'0']
		}
	}
	return string(out)
}

func fmtNumFa(v float64, digits int) string {
	return toFaDigits(strconv.FormatFloat(v, 'f', digits, 64))
}

func fmtPctFa(v float64) string {
	if v >= 0 {
		return "+" + fmtNumFa(v, 1) + "٪"
	}
	return fmtNumFa(v, 1) + "٪"
}

func fmtRialFa(v float64) string {
	s := strconv.FormatFloat(v, 'f', 0, 64)
	var b strings.Builder
	n := len(s)
	for i := 0; i < n; i++ {
		b.WriteByte(s[i])
		if rem := n - i - 1; rem > 0 && rem%3 == 0 {
			b.WriteByte(',')
		}
	}
	return toFaDigits(b.String())
}

// fmtRialCompactFa مبالغ ریالی را برای خواندن انسانی کوتاه می‌کند.
func fmtRialCompactFa(v float64) string {
	abs := math.Abs(v)
	switch {
	case abs >= 1e15:
		return fmtNumFa(v/1e15, 2) + " میلیون میلیارد ریال"
	case abs >= 1e12:
		return fmtNumFa(v/1e12, 2) + " هزار میلیارد ریال"
	case abs >= 1e9:
		return fmtNumFa(v/1e9, 2) + " میلیارد ریال"
	case abs >= 1e6:
		return fmtNumFa(v/1e6, 2) + " میلیون ریال"
	default:
		return fmtRialFa(v) + " ریال"
	}
}

// growthOutlierLimit آستانه‌ی نمایش نرخ رشد است. مخرج کوچک در داده‌ی واقعی
// نرخ‌هایی در حد میلیارد درصد تولید می‌کند؛ چنین عددی نمایش داده نمی‌شود چون
// گمراه‌کننده است (خود موتور هنگام رتبه‌بندی آن را می‌بُرد).
const growthOutlierLimit = 1000.0

// formatSnapMetric یک متریک snapshot را با واحدش قالب‌بندی می‌کند.
// bool دوم وقتی false است یعنی مقدار ناهنجار/غیرقابل‌نمایش است.
func formatSnapMetric(metricCode, unit string, v float64) (string, bool) {
	switch unit {
	case "percent":
		if math.Abs(v) > growthOutlierLimit {
			return "", false
		}
		return fmtPctFa(v), true
	case "percent_daily":
		if math.Abs(v) > 100 {
			return "", false
		}
		return fmtNumFa(v, 2) + "٪", true
	case "pct_point":
		if math.Abs(v) > growthOutlierLimit {
			return "", false
		}
		return fmtNumFa(v, 2) + " واحد درصد", true
	case "rial":
		return fmtRialCompactFa(v), true
	case "rial_per_share":
		return fmtRialFa(v) + " ریال", true
	case "score01":
		return fmtNumFa(v, 2), true
	case "ratio":
		// نسبت‌های بی‌بعد: P/E منفی یعنی زیان‌دهی، نه ارزانی.
		if metricCode == "pe" && v <= 0 {
			return "منفی (زیان‌ده)", true
		}
		return fmtNumFa(v, 2), true
	default:
		return fmtNumFa(v, 2), true
	}
}

// snapValue آخرین مقدار یک متریک را از snapshotهای باندل برمی‌گرداند.
type snapValue struct {
	metricCode string
	value      float64
	unit       string
	asOf       string
}

func latestSnapshots(page integration.SymbolPageCanonical) map[string]snapValue {
	out := map[string]snapValue{}
	for _, s := range page.MetricSnapshots {
		prev, ok := out[s.MetricCode]
		if ok && s.AsOfDate <= prev.asOf {
			continue
		}
		out[s.MetricCode] = snapValue{metricCode: s.MetricCode, value: s.Value, unit: s.Unit, asOf: s.AsOfDate}
	}
	return out
}

// snapLine یک خط «برچسب: مقدار» می‌سازد؛ اگر متریک موجود یا قابل‌نمایش نبود
// رشته‌ی خالی برمی‌گرداند تا خط حذف شود.
func snapLine(snaps map[string]snapValue, label, metricCode string, digits int) string {
	s, ok := snaps[metricCode]
	if !ok {
		return ""
	}
	if v, ok := formatSnapMetric(metricCode, s.unit, s.value); ok {
		return "• " + label + ": " + v + "\n"
	}
	return ""
}

// matchedCompany شرکتی که نام/نماد آن در متن کاربر آمده است؛ طولانی‌ترین تطبیق برنده است.
type matchedCompany struct {
	row   integration.AllScoreInputRow
	score int
}

func findCompanyMentions(text string, rows []integration.AllScoreInputRow) []matchedCompany {
	norm := normalizeFaText(text)
	tokens := strings.Fields(norm)
	var out []matchedCompany
	for _, r := range rows {
		best := 0
		if sym := normalizeFaText(r.Symbol); sym != "" {
			for _, t := range tokens {
				if t == sym && len([]rune(sym)) > best {
					best = len([]rune(sym))
				}
			}
		}
		if name := normalizeFaText(r.CompanyName); len([]rune(name)) >= 3 && strings.Contains(norm, name) {
			if len([]rune(name)) > best {
				best = len([]rune(name))
			}
		}
		if best > 0 {
			out = append(out, matchedCompany{row: r, score: best})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].score > out[j].score })
	seen := map[string]bool{}
	uniq := out[:0]
	for _, m := range out {
		key := m.row.CanonicalID + "|" + m.row.LegacyCompanyID
		if !seen[key] {
			seen[key] = true
			uniq = append(uniq, m)
		}
	}
	return uniq
}

// verdictRankFa رتبه را نسبت به کل بازار توصیف می‌کند (مطلق نیست، چون مقیاس
// امتیاز در هر اجرا می‌تواند متفاوت باشد).
func verdictRankFa(rank, total int) string {
	if total <= 1 {
		return "داده‌ی کافی برای مقایسه با بازار نیست."
	}
	p := float64(rank-1) / float64(total-1) // ۰ = بهترین
	switch {
	case p <= 0.05:
		return "از نظر فاکتورهای کمی جزو ۵٪ برتر بازار است."
	case p <= 0.2:
		return "از نظر فاکتورهای کمی جزو ۲۰٪ برتر بازار است."
	case p <= 0.5:
		return "از نظر فاکتورهای کمی بالاتر از نیمه‌ی پایین بازار است."
	case p <= 0.8:
		return "از نظر فاکتورهای کمی در نیمه‌ی پایین‌تر بازار قرار دارد."
	default:
		return "از نظر فاکتورهای کمی جزو ضعیف‌ترین‌های بازار است."
	}
}

func topFactorText(r integration.AllScoreInputRow, count int) []string {
	type fr struct {
		code  string
		rank  float64
		order int
	}
	var list []fr
	for code, rank := range r.FactorRanks {
		order := len(factorReasonOrder)
		for i, c := range factorReasonOrder {
			if c == code {
				order = i
				break
			}
		}
		list = append(list, fr{code: code, rank: rank, order: order})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].order != list[j].order {
			return list[i].order < list[j].order
		}
		return list[i].rank > list[j].rank
	})
	out := make([]string, 0, count)
	for i, f := range list {
		if i >= count {
			break
		}
		if f.rank <= 0 {
			continue
		}
		label := factorLabelsFa[f.code]
		if label == "" {
			label = f.code
		}
		out = append(out, fmt.Sprintf("• %s: بهتر از %s٪ بازار", label, fmtNumFa(f.rank*100, 0)))
	}
	return out
}

func weakestFactorText(r integration.AllScoreInputRow, count int) []string {
	type fr struct {
		label string
		rank  float64
	}
	var list []fr
	for code, rank := range r.FactorRanks {
		label := factorLabelsFa[code]
		if label == "" || rank <= 0 {
			continue
		}
		list = append(list, fr{label: label, rank: rank})
	}
	sort.Slice(list, func(i, j int) bool { return list[i].rank < list[j].rank })
	out := make([]string, 0, count)
	for i, f := range list {
		if i >= count {
			break
		}
		out = append(out, fmt.Sprintf("• %s: در %s٪ پایین بازار", f.label, fmtNumFa(f.rank*100, 0)))
	}
	return out
}

// topFactorInline همان دلایل را بدون بولت و برای استفاده درون‌خطی برمی‌گرداند.
func topFactorInline(r integration.AllScoreInputRow, count int) string {
	items := topFactorText(r, count)
	for i, s := range items {
		items[i] = strings.TrimPrefix(s, "• ")
	}
	return strings.Join(items, "، ")
}

func rawOr(r integration.AllScoreInputRow, code string) (float64, bool) {
	if v, ok := r.FactorRaw[code]; ok && v != 0 {
		return v, true
	}
	return 0, false
}

func companyRank(target integration.AllScoreInputRow, rows []integration.AllScoreInputRow) int {
	rank := 1
	for _, r := range rows {
		if r.QuantScore > target.QuantScore {
			rank++
		}
	}
	return rank
}

func companyAnalysisReply(r integration.AllScoreInputRow, rows []integration.AllScoreInputRow, page *integration.SymbolPageCanonical) string {
	var b strings.Builder
	b.WriteString(fmt.Sprintf("📊 تحلیل «%s»\n\n", r.CompanyName))

	snaps := map[string]snapValue{}
	if page != nil {
		snaps = latestSnapshots(*page)
	}
	hiddenOutliers := 0
	metric := func(label, code string) (string, bool) {
		s, ok := snaps[code]
		if !ok {
			return "", false
		}
		v, ok := formatSnapMetric(code, s.unit, s.value)
		if !ok {
			hiddenOutliers++
			return "", false
		}
		return label + ": " + v, true
	}
	row := func(pairs ...[2]string) {
		items := make([]string, 0, len(pairs))
		for _, p := range pairs {
			if s, ok := metric(p[0], p[1]); ok {
				items = append(items, s)
			}
		}
		if len(items) > 0 {
			b.WriteString("• " + strings.Join(items, " | ") + "\n")
		}
	}

	rank := companyRank(r, rows)
	b.WriteString(fmt.Sprintf("• امتیاز کمی: %s از ۱۰۰ (رتبه‌ی %s از %s شرکت)\n",
		fmtNumFa(r.QuantScore, 1), toFaDigits(strconv.Itoa(rank)), toFaDigits(strconv.Itoa(len(rows)))))
	b.WriteString(fmt.Sprintf("• امتیاز دسته‌ها (مقیاس داخلی): رشد %s | سودآوری %s | ارزش‌گذاری %s | بازار %s\n",
		fmtNumFa(r.GrowthScore, 0), fmtNumFa(r.ProfitabilityScore, 0), fmtNumFa(r.ValuationScore, 0), fmtNumFa(r.MarketScore, 0)))
	if r.Price > 0 {
		b.WriteString(fmt.Sprintf("• قیمت آخرین: %s\n", fmtRialCompactFa(r.Price)))
	}

	row([2]string{"P/E", "pe"}, [2]string{"P/S", "ps"}, [2]string{"P/B", "pb"})
	row([2]string{"حاشیه سود عملیاتی", "operating_margin"}, [2]string{"حاشیه سود خالص", "net_margin"}, [2]string{"ROE", "roe"})
	row([2]string{"رشد فروش ۱۲ماهه", "sales_growth_12m"}, [2]string{"رشد درآمد", "revenue_growth"}, [2]string{"رشد سود خالص", "net_profit_growth"})
	row([2]string{"بازده ۳۰روزه", "price_momentum_30d"}, [2]string{"نوسان روزانه", "volatility_30d"}, [2]string{"میانگین ارزش معاملات", "avg_trade_value_30d"})
	row([2]string{"نسبت جاری", "current_ratio"}, [2]string{"اهرم (بدهی/دارایی)", "debt_ratio"}, [2]string{"تبدیل سود به نقد", "cash_conversion"})
	row([2]string{"درآمد TTM", "revenue_ttm"}, [2]string{"سود خالص TTM", "net_profit_ttm"}, [2]string{"EPS", "eps_ttm"})

	if hiddenOutliers > 0 {
		b.WriteString(fmt.Sprintf("• (%s نرخ رشد به‌دلیل مخرج کوچک در گزارش، قابل نمایش نبود)\n", toFaDigits(strconv.Itoa(hiddenOutliers))))
	}

	balanceSheet := 0
	for _, code := range []string{"roe", "current_ratio", "debt_ratio", "cash_conversion"} {
		if _, ok := snaps[code]; ok {
			balanceSheet++
		}
	}

	if strengths := topFactorText(r, 3); len(strengths) > 0 {
		b.WriteString("\nنقاط قوت:\n" + strings.Join(strengths, "\n") + "\n")
	}
	if weak := weakestFactorText(r, 2); len(weak) > 0 {
		b.WriteString("\nنقاط ضعف:\n" + strings.Join(weak, "\n") + "\n")
	}

	b.WriteString("\nجمع‌بندی: " + verdictRankFa(rank, len(rows)) + "\n")
	if lr, ok := r.FactorRanks["Liquidity"]; ok && lr > 0 && lr < 0.2 {
		b.WriteString("⚠️ نقدشوندگی این سهم پایین است؛ برای معامله‌ی حجیم ریسک دارد.\n")
	}

	// محدودیت‌های داده: کاربر باید بداند تحلیل روی چه چیزی سوار است.
	var limits []string
	if balanceSheet == 0 {
		limits = append(limits, "صورت‌های ترازنامه‌ای برای این نماد در دیتابیس موجود نیست (عوامل ROE/نسبت جاری/اهرم محاسبه نشده)")
	} else if balanceSheet < 4 {
		limits = append(limits, "برخی اقلام ترازنامه‌ای این نماد ناقص است")
	}
	if page != nil && page.Metadata.Stale {
		limits = append(limits, "داده‌ی بازار جدیدتر از آخرین اجرای امتیازدهی است")
	}
	if len(limits) > 0 {
		b.WriteString("\nمحدودیت‌ها: " + strings.Join(limits, "؛ ") + ".\n")
	}

	if page != nil {
		var asOf []string
		if len(page.Monthly) > 0 && page.Monthly[0].ReportDate != "" {
			asOf = append(asOf, "آخرین فعالیت ماهانه: "+toFaDigits(page.Monthly[0].ReportDate))
		}
		if len(page.Financial) > 0 && page.Financial[0].ReportDate != "" {
			asOf = append(asOf, "آخرین گزارش مالی: "+toFaDigits(page.Financial[0].ReportDate))
		}
		if page.Metadata.MarketAsOf != "" {
			asOf = append(asOf, "داده‌ی بازار: "+toFaDigits(page.Metadata.MarketAsOf))
		}
		if len(asOf) > 0 {
			b.WriteString(strings.Join(asOf, " | ") + "\n")
		}
	}

	b.WriteString("\n⚠️ این تحلیل فقط بر اساس داده‌های کمی همین سامانه است و توصیه‌ی خرید/فروش نیست.")
	return b.String()
}

func recommendReply(rows []integration.AllScoreInputRow) string {
	if len(rows) == 0 {
		return "فعلاً داده‌ی امتیازی برای شرکت‌ها در دسترس نیست."
	}
	sorted := rowsSortedByScore(rows)
	// فیلتر نقدشوندگی: اگر شرکت‌های نقدشونده کافی بود، فقط بین آنها انتخاب کن
	liquid := make([]integration.AllScoreInputRow, 0, len(sorted))
	for _, r := range sorted {
		if lr, ok := r.FactorRanks["Liquidity"]; !ok || lr == 0 || lr >= 0.25 {
			liquid = append(liquid, r)
		}
	}
	pool := liquid
	if len(pool) < 5 {
		pool = sorted
	}
	var b strings.Builder
	b.WriteString("🏆 بر اساس امتیاز کمی سامانه، این نمادها بالاترین ترکیب رشد/سودآوری/ارزش‌گذاری/بازار را دارند:\n\n")
	count := 5
	if len(pool) < count {
		count = len(pool)
	}
	for i := 0; i < count; i++ {
		r := pool[i]
		b.WriteString(fmt.Sprintf("%s. «%s» — امتیاز %s (رتبه‌ی %s از %s)\n",
			toFaDigits(strconv.Itoa(i+1)), r.CompanyName, fmtNumFa(r.QuantScore, 1),
			toFaDigits(strconv.Itoa(companyRank(r, rows))), toFaDigits(strconv.Itoa(len(rows)))))
		if reasons := topFactorInline(r, 2); reasons != "" {
			b.WriteString(reasons + "\n")
		}
		if r.Price > 0 {
			b.WriteString(fmt.Sprintf("قیمت: %s ریال\n", fmtRialFa(r.Price)))
		}
		b.WriteString("\n")
	}
	b.WriteString("برای دیدن تحلیل کامل هر کدام، اسم شرکت را بنویس (مثلاً: تحلیل فولاد).\n")
	b.WriteString("⚠️ این فهرست صرفاً رتبه‌بندی کمی است و توصیه‌ی خرید/فروش نیست.")
	return b.String()
}

func weakestReply(rows []integration.AllScoreInputRow) string {
	sorted := rowsSortedByScore(rows)
	var b strings.Builder
	b.WriteString("🔻 شرکت‌های با پایین‌ترین امتیاز کمی (ریسک بالاتر از نظر داده‌های کمی):\n\n")
	count := 5
	if len(sorted) < count {
		count = len(sorted)
	}
	for i := 0; i < count; i++ {
		r := sorted[len(sorted)-1-i]
		b.WriteString(fmt.Sprintf("%s. «%s» — امتیاز %s\n", toFaDigits(strconv.Itoa(i+1)), r.CompanyName, fmtNumFa(r.QuantScore, 1)))
	}
	b.WriteString("\nامتیاز پایین به معنای «قطعاً ضرر» نیست، اما از نظر فاکتورهای کمی ضعیف‌تر از بازار است.")
	return b.String()
}

func compareReply(a, b integration.AllScoreInputRow) string {
	var out strings.Builder
	out.WriteString(fmt.Sprintf("⚖️ مقایسه «%s» و «%s»\n\n", a.CompanyName, b.CompanyName))
	rows := []struct {
		label string
		va    string
		vb    string
	}{
		{"امتیاز کمی", fmtNumFa(a.QuantScore, 1), fmtNumFa(b.QuantScore, 1)},
		{"رشد", fmtNumFa(a.GrowthScore, 0), fmtNumFa(b.GrowthScore, 0)},
		{"سودآوری", fmtNumFa(a.ProfitabilityScore, 0), fmtNumFa(b.ProfitabilityScore, 0)},
		{"ارزش‌گذاری", fmtNumFa(a.ValuationScore, 0), fmtNumFa(b.ValuationScore, 0)},
		{"بازار", fmtNumFa(a.MarketScore, 0), fmtNumFa(b.MarketScore, 0)},
	}
	for _, row := range rows {
		out.WriteString(fmt.Sprintf("• %s: %s در برابر %s\n", row.label, row.va, row.vb))
	}
	winner, loser := a, b
	if b.QuantScore > a.QuantScore {
		winner, loser = b, a
	}
	out.WriteString(fmt.Sprintf("\nبرتری کمی با «%s» است (اختلاف %s نمره).\n", winner.CompanyName, fmtNumFa(winner.QuantScore-loser.QuantScore, 1)))
	if wa := topFactorInline(winner, 2); wa != "" {
		out.WriteString("قوت‌های برترِ " + winner.CompanyName + ": " + wa + "\n")
	}
	out.WriteString("\n⚠️ مقایسه فقط بر پایه امتیازهای کمی سامانه است و توصیه‌ی خرید/فروش نیست.")
	return out.String()
}

func marketOverviewReply(rows []integration.AllScoreInputRow) string {
	if len(rows) == 0 {
		return "فعلاً داده‌ی امتیازی برای شرکت‌ها در دسترس نیست."
	}
	sorted := rowsSortedByScore(rows)
	sum := 0.0
	scores := make([]float64, 0, len(rows))
	for _, r := range rows {
		sum += r.QuantScore
		scores = append(scores, r.QuantScore)
	}
	avg := sum / float64(len(rows))
	sort.Float64s(scores)
	median := scores[len(scores)/2]
	above60 := 0
	for _, v := range scores {
		if v >= 60 {
			above60++
		}
	}
	var b strings.Builder
	b.WriteString("📈 نمای کلی بازار بر اساس آخرین اجرای امتیازدهی:\n\n")
	b.WriteString(fmt.Sprintf("• تعداد شرکت‌های امتیازدهی‌شده: %s\n", toFaDigits(strconv.Itoa(len(rows)))))
	b.WriteString(fmt.Sprintf("• میانگین امتیاز کمی: %s | میانه: %s\n", fmtNumFa(avg, 1), fmtNumFa(median, 1)))
	b.WriteString(fmt.Sprintf("• شرکت‌های با امتیاز ۶۰ به بالا: %s\n", toFaDigits(strconv.Itoa(above60))))
	b.WriteString("\nسه امتیاز برتر بازار:\n")
	for i := 0; i < 3 && i < len(sorted); i++ {
		b.WriteString(fmt.Sprintf("%s. «%s» — %s\n", toFaDigits(strconv.Itoa(i+1)), sorted[i].CompanyName, fmtNumFa(sorted[i].QuantScore, 1)))
	}
	b.WriteString("\nمی‌توانی اسم هر شرکت را بنویسی تا تحلیلش را ببینم، یا بپرسی «بهترین سهم‌ها برای سرمایه‌گذاری چی هست؟»")
	return b.String()
}

func greetingReply() string {
	return "سلام! 👋 من دستیار تحلیل همین سامانه هستم و جواب‌هایم بر اساس داده‌ی امتیاز کمی شرکت‌های بازار است.\n\n" +
		"می‌توانی این‌ها را از من بپرسی:\n" +
		"• «بهترین سهم‌ها برای سرمایه‌گذاری چی هست؟»\n" +
		"• «تحلیل فولاد» (اسم هر شرکت)\n" +
		"• «مقایسه فولاد و فملی»\n" +
		"• «وضعیت بازار چطوره؟»\n\n" +
		"⚠️ پاسخ‌ها توصیه‌ی سرمایه‌گذاری نیستند؛ فقط تحلیل داده‌های کمی هستند."
}

func rowsSortedByScore(rows []integration.AllScoreInputRow) []integration.AllScoreInputRow {
	sorted := append([]integration.AllScoreInputRow(nil), rows...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].QuantScore > sorted[j].QuantScore })
	return sorted
}

// buildChatContext برای مسیر LLM: خلاصه‌ی فشرده داده‌های مرتبط با پرسش کاربر.
// وقتی باندل کامل شرکت موجود است، اعداد واقعی (با واحد) هم ضمیمه می‌شوند تا
// مدل مجبور نباشد از رتبه‌ها عدد استنتاج کند.
func buildChatContext(rows []integration.AllScoreInputRow, mentions []matchedCompany, page *integration.SymbolPageCanonical) string {
	var b strings.Builder
	b.WriteString(fmt.Sprintf("تعداد کل شرکت‌های امتیازدهی‌شده: %d\n", len(rows)))
	b.WriteString("سطرها: نام | نماد | امتیازکمی | رشد | سودآوری | ارزش‌گذاری | بازار | P/E | رشدفروش٪ | قیمت(ریال)\n")
	for _, m := range mentions {
		r := m.row
		b.WriteString(fmt.Sprintf("مرتبط با پرسش: %s | %s | %.1f | %.0f | %.0f | %.0f | %.0f | %.1f | %.1f | %.0f\n",
			r.CompanyName, r.Symbol, r.QuantScore, r.GrowthScore, r.ProfitabilityScore, r.ValuationScore, r.MarketScore, r.PE, r.SalesGrowth, r.Price))
	}
	if page != nil {
		snaps := latestSnapshots(*page)
		b.WriteString("متریک‌های واقعی شرکتِ پرسش (کد=مقدار/واحد، as-of=" + page.Metadata.ScoreAsOf + "):\n")
		codes := make([]string, 0, len(snaps))
		for code := range snaps {
			codes = append(codes, code)
		}
		sort.Strings(codes)
		for _, code := range codes {
			s := snaps[code]
			b.WriteString(fmt.Sprintf("  %s=%.4f (%s)\n", code, s.value, s.unit))
		}
		if len(page.Monthly) > 0 {
			m := page.Monthly[0]
			b.WriteString(fmt.Sprintf("  آخرین فعالیت ماهانه %s: تولید %.0f، فروش %.0f، مبلغ فروش %s\n",
				m.ReportDate, m.ProductionQuantity, m.SalesQuantity, fmtRialCompactFa(m.SalesAmountRial)))
		}
		for i := 0; i < 2 && i < len(page.Financial); i++ {
			f := page.Financial[i]
			b.WriteString(fmt.Sprintf("  صورت سود و زیان %s: EPS %.0f ریال، درآمد %.0f میلیون ریال، سود خالص %.0f میلیون ریال\n",
				f.ReportDate, f.EPS, f.Revenue, f.NetProfit))
		}
	}
	sorted := rowsSortedByScore(rows)
	for i := 0; i < 10 && i < len(sorted); i++ {
		r := sorted[i]
		b.WriteString(fmt.Sprintf("برتر#%d: %s | %s | %.1f | %.0f | %.0f | %.0f | %.0f | %.1f | %.1f | %.0f\n",
			i+1, r.CompanyName, r.Symbol, r.QuantScore, r.GrowthScore, r.ProfitabilityScore, r.ValuationScore, r.MarketScore, r.PE, r.SalesGrowth, r.Price))
	}
	return b.String()
}

const chatSystemPromptFa = "تو دستیار تحلیل مالی فارسی‌زبان یک سامانه‌ی غربالگری بورس تهران هستی. " +
	"فقط بر اساس داده‌هایی که در پیام کاربر (بخش DATA:) داده شده جواب بده؛ عدد از خودت نساز. " +
	"اگر داده کافی نیست، صادقانه بگو چه داده‌ای موجود نیست. پاسخ کوتاه، خوانا و با بولت بده. " +
	"در پایان هر تحلیل یک خط اضافه کن: «این تحلیل بر اساس داده‌های کمی است و توصیه خرید/فروش نیست.»"

// callAIChat پاسخ LLM را با پرامپت سیستم چت می‌سازد؛ در نبود تنظیمات یا در خطا رشته‌ی خالی برمی‌گرداند.
func callAIChat(dataContext string, history []chatIncomingMessage) string {
	chatURL := strings.TrimSpace(os.Getenv("AI_CHAT_URL"))
	apiKey := strings.TrimSpace(os.Getenv("AI_API_KEY"))
	model := strings.TrimSpace(os.Getenv("AI_MODEL"))
	if chatURL == "" || apiKey == "" {
		return ""
	}
	if model == "" {
		model = "default"
	}
	messages := make([]chatMessage, 0, len(history)+2)
	messages = append(messages, chatMessage{Role: "system", Content: chatSystemPromptFa})
	start := 0
	if len(history) > 6 {
		start = len(history) - 6
	}
	for _, m := range history[start:] {
		if m.Role != "user" && m.Role != "assistant" {
			continue
		}
		messages = append(messages, chatMessage{Role: m.Role, Content: m.Content})
	}
	messages = append(messages, chatMessage{Role: "user", Content: "DATA:\n" + dataContext})

	bodyBytes, err := json.Marshal(chatRequest{Model: model, Temperature: 0.3, Messages: messages})
	if err != nil {
		return ""
	}
	httpReq, err := http.NewRequest(http.MethodPost, chatURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return ""
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+apiKey)
	client := &http.Client{Timeout: 45 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	respBytes, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ""
	}
	var parsed chatResponse
	if err := json.Unmarshal(respBytes, &parsed); err != nil || len(parsed.Choices) == 0 {
		return ""
	}
	return strings.TrimSpace(parsed.Choices[0].Message.Content)
}

// Chat هندلر POST /api/chat است.
func Chat(c *gin.Context) {
	var body chatRequestBody
	if err := c.ShouldBindJSON(&body); err != nil || len(body.Messages) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "messages is required"})
		return
	}
	userMsg := ""
	for i := len(body.Messages) - 1; i >= 0; i-- {
		if body.Messages[i].Role == "user" {
			userMsg = strings.TrimSpace(body.Messages[i].Content)
			break
		}
	}
	if userMsg == "" {
		c.JSON(http.StatusOK, chatResponseBody{Reply: greetingReply(), Intent: "greeting"})
		return
	}

	sh := integration.Default()
	if sh == nil {
		c.JSON(http.StatusOK, chatResponseBody{Reply: "اتصال به منبع داده برقرار نیست؛ بعداً دوباره تلاش کن.", Intent: "error"})
		return
	}
	rows, err := sh.FetchSummaryCanonical(c.Request.Context())
	if err != nil || len(rows) == 0 {
		c.JSON(http.StatusOK, chatResponseBody{
			Reply:  "الان به دیتای امتیازدهی دسترسی ندارم. لطفاً چند دقیقه‌ی دیگر دوباره امتحان کن.",
			Intent: "data_unavailable",
		})
		return
	}

	// مسیر اصلی: حلقه‌ی ابزار با مدل زبانی (همه‌ی اعداد از ابزارها می‌آیند).
	// در نبود کلید یا در خطا، بی‌صدا به موتور قاعده‌ای برمی‌گردیم.
	if aiConfigured() {
		if reply, used, err := runChatAgent(c, userMsg, body.Messages, nil); err == nil && strings.TrimSpace(reply) != "" {
			c.JSON(http.StatusOK, chatResponseBody{Reply: reply, Intent: "agent", ToolsUsed: used})
			return
		} else if err != nil {
			log.Printf("chat: agent failed, falling back to rules: %v", err)
		}
	}

	c.JSON(http.StatusOK, ruleFallbackReply(c, userMsg, body))
}

// ruleFallbackReply موتور قاعده‌ای (و مسیر LLM تک‌مرحله‌ای) وقتی agent در
// دسترس نیست؛ هم توسط Chat و هم ChatStream استفاده می‌شود.
func ruleFallbackReply(c *gin.Context, userMsg string, body chatRequestBody) chatResponseBody {
	sh := integration.Default()
	if sh == nil {
		return chatResponseBody{Reply: "اتصال به منبع داده برقرار نیست؛ بعداً دوباره تلاش کن.", Intent: "error"}
	}
	rows, err := sh.FetchSummaryCanonical(c.Request.Context())
	if err != nil || len(rows) == 0 {
		return chatResponseBody{Reply: "الان به دیتای امتیازدهی دسترسی ندارم. لطفاً چند دقیقه‌ی دیگر دوباره امتحان کن.", Intent: "data_unavailable"}
	}
	norm := normalizeFaText(userMsg)
	mentions := findCompanyMentions(userMsg, rows)

	// باندل کامل canonical شرکتِ نام‌برده‌شده (اعداد واقعی: TTM، حاشیه‌ها،
	// ارزش معاملات، صورت‌های مالی). در نبود آن، تحلیل روی امتیازها می‌ماند.
	var page *integration.SymbolPageCanonical
	if len(mentions) > 0 {
		if p, perr := sh.FetchSymbolPageCanonical(c.Request.Context(), mentions[0].row.LegacyCompanyID); perr == nil && p.IdentityFound {
			page = &p
		}
	}

	ruleReply, intent := buildRuleReply(norm, rows, mentions, page)

	reply := ruleReply
	if !aiConfigured() {
		if llmReply := callAIChat(buildChatContext(rows, mentions, page), body.Messages); llmReply != "" {
			reply = llmReply
		}
	}
	return chatResponseBody{Reply: reply, Intent: intent}
}

// buildRuleReply موتور قاعده‌ای پاسخ: تطبیق نیت بر اساس کلیدواژه‌های فارسی.
func buildRuleReply(norm string, rows []integration.AllScoreInputRow, mentions []matchedCompany, page *integration.SymbolPageCanonical) (string, string) {
	has := func(words ...string) bool {
		for _, w := range words {
			if strings.Contains(norm, w) {
				return true
			}
		}
		return false
	}

	// ۱) مقایسه دو شرکت
	if len(mentions) >= 2 && (has("مقایسه", "بهتر", "کدوم", "کدام") || strings.Contains(norm, " یا ")) {
		a, b := mentions[0].row, mentions[1].row
		if a.CanonicalID != b.CanonicalID || a.LegacyCompanyID != b.LegacyCompanyID {
			return compareReply(a, b), "compare"
		}
	}
	// ۲) تحلیل یک شرکت
	if len(mentions) > 0 {
		return companyAnalysisReply(mentions[0].row, rows, page), "company"
	}
	// ۳) پیشنهاد خرید
	if has("پیشنهاد", "بهترین", "بخرم", "خرید", "سبد", "گزینه", "سرمایه گذاری", "سرمایه‌گذاری", "توصیه") {
		return recommendReply(rows), "recommend"
	}
	// ۴) ضعیف‌ترین‌ها
	if has("بدترین", "ضعیف ترین", "ضعیف‌ترین", "دور باشم") {
		return weakestReply(rows), "weakest"
	}
	// ۵) سلام و کمک
	if has("سلام", "درود", "خوبی", "چیکار", "کمک", "چی بلدی", "چه بلدی") {
		return greetingReply(), "greeting"
	}
	// ۶) وضعیت بازار و حالت پیش‌فرض
	return marketOverviewReply(rows), "market"
}
