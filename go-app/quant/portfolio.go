package quant

import (
	"math"
	"sort"
	"strings"
)

// portfolio.go — ساخت سبد ریسک‌محور.
//
// همه‌ی محاسبات قطعی و بدون حل‌کننده‌ی بیرونی است. هیچ‌جا «بازده انتظاری» از
// آینده پیش‌بینی نمی‌شود؛ آنچه گزارش می‌شود (نوسان، افت تاریخی، بازده تاریخی)
// صرفاً تاریخچه‌ی همان سبد با همین وزن‌ها روی همان پنجره است.
//
// مفروضات صریح:
//   - سال معاملاتی ۲۵۰ روز فرض می‌شود؛
//   - نرخ بدون ریسک صفر گرفته می‌شود (شاخص کل در دیتابیس موجود نیست)، پس
//     «شارپ‌مانند» فقط بازده/نوسان است، نه شارپ واقعی؛
//   - قیمت‌ها سری تنظیم‌شده‌ی بازار هستند و سود نقدی بازتاب کامل ندارد.

// Series یک سری قیمت با تاریخ است. Dates باید صعودی (قدیمی→جدید) باشد.
type Series struct {
	Key    string
	Dates  []string
	Prices []float64
}

// AlignedReturns سری‌ها را روی تقویم مشترک هم‌تراز می‌کند و ماتریس بازده روزانه
// می‌سازد. برای روزهایی که یک نماد معامله نداشته، آخرین قیمت جلو برده می‌شود
// (forward-fill) — روش استاندارد کوواریانس روی داده‌ی روزانه‌ی بازارهایی با
// توقف نماد.
//
// خروجی: تاریخ‌های بازده (به‌جز روز اول تقویم)، ماتریس بازده [nSeries][nDates]،
// starts[i] = اولین ستون معتبر سری i (روزهای پیش از شروع نماد صفرِ کاذب‌اند و
// نباید در کوواریانس وارد شوند) و ok[i] = آیا بازده معتبر کافی دارد.
func AlignedReturns(series []Series, minObs int) (dates []string, matrix [][]float64, starts []int, ok []bool) {
	n := len(series)
	if n == 0 {
		return nil, nil, nil, nil
	}
	// تقویم مشترک = اجتماع تاریخ‌ها (نه اشتراک) تا نمادهای کم‌معامله حذف نشوند.
	dateSet := map[string]struct{}{}
	for _, s := range series {
		for _, d := range s.Dates {
			dateSet[d] = struct{}{}
		}
	}
	all := make([]string, 0, len(dateSet))
	for d := range dateSet {
		all = append(all, d)
	}
	sort.Strings(all)

	matrix = make([][]float64, n)
	starts = make([]int, n)
	ok = make([]bool, n)
	for i, s := range series {
		px := forwardFill(s.Dates, s.Prices, all)
		rets := make([]float64, 0, len(px))
		valid := 0
		start := -1
		for j := 1; j < len(px); j++ {
			if px[j-1] > 0 && px[j] > 0 {
				rets = append(rets, (px[j]-px[j-1])/px[j-1])
				valid++
				if start < 0 {
					start = len(rets) - 1
				}
			} else {
				rets = append(rets, 0)
			}
		}
		matrix[i] = rets
		starts[i] = start
		ok[i] = minObs <= 0 || valid >= minObs
	}
	if len(all) > 0 {
		dates = all[1:]
	}
	return dates, matrix, starts, ok
}

// forwardFill قیمت هر تاریخ تقویم را برمی‌گرداند؛ روزهای قبل از شروعِ نماد صفر
// می‌مانند (بازده آن‌ها نامعتبر شمرده می‌شود) و روزهای توقف با آخرین قیمت پر می‌شوند.
func forwardFill(dates []string, prices []float64, calendar []string) []float64 {
	idx := make(map[string]int, len(dates))
	for i, d := range dates {
		idx[d] = i
	}
	out := make([]float64, len(calendar))
	last := 0.0
	for i, d := range calendar {
		if j, found := idx[d]; found && j < len(prices) && prices[j] > 0 {
			last = prices[j]
		}
		out[i] = last
	}
	return out
}

// CovarianceMatrix ماتریس کوواریانس نمونه‌ای سری‌های بازده را می‌سازد و در صورت
// annualize>0 آن را با تعداد روزهای معاملاتی سالانه‌سازی می‌کند.
//
// startRow مشخص می‌کند از کدام ستون به بعد همه‌ی سری‌ها داده‌ی واقعی دارند؛
// ستون‌های قبل از آن (پیش از شروع معامله‌ی بعضی نمادها) صفرِ کاذب‌اند و باید
// نادیده گرفته شوند، وگرنه کوواریانس به سمت صفر کشیده می‌شود.
func CovarianceMatrix(returns [][]float64, startRow int, annualize int) [][]float64 {
	n := len(returns)
	cov := make([][]float64, n)
	for i := range cov {
		cov[i] = make([]float64, n)
	}
	if n == 0 {
		return cov
	}
	if startRow < 0 {
		startRow = 0
	}
	rows := len(returns[0])
	for i := 1; i < n; i++ {
		if len(returns[i]) < rows {
			rows = len(returns[i])
		}
	}
	if rows-startRow < 2 {
		return cov
	}
	means := make([]float64, n)
	count := float64(rows - startRow)
	for i := 0; i < n; i++ {
		sum := 0.0
		for t := startRow; t < rows; t++ {
			sum += returns[i][t]
		}
		means[i] = sum / count
	}
	for i := 0; i < n; i++ {
		for j := i; j < n; j++ {
			s := 0.0
			for t := startRow; t < rows; t++ {
				s += (returns[i][t] - means[i]) * (returns[j][t] - means[j])
			}
			c := s / (count - 1)
			if annualize > 0 {
				c *= float64(annualize)
			}
			cov[i][j] = c
			cov[j][i] = c
		}
	}
	return cov
}

// ShrinkCovariance کوواریانس را به قطرش شرینک می‌کند: (۱−λ)Σ + λ·diag(Σ).
// λ=۰ یعنی کوواریانس خام و λ=۱ یعنی فقط واریانس‌های منفرد (بدون همبستگی).
// این کار واریانس نمونه‌ای را در تعداد دارایی‌های زیاد پایدار می‌کند.
func ShrinkCovariance(cov [][]float64, lambda float64) [][]float64 {
	n := len(cov)
	if n == 0 {
		return cov
	}
	if lambda < 0 {
		lambda = 0
	}
	if lambda > 1 {
		lambda = 1
	}
	out := make([][]float64, n)
	for i := range out {
		out[i] = make([]float64, n)
		for j := range out[i] {
			if i == j {
				out[i][j] = cov[i][j]
			} else {
				out[i][j] = (1 - lambda) * cov[i][j]
			}
		}
	}
	return out
}

// InverseVolWeights وزن معکوس‌نوسان می‌سازد (مجموع = ۱).
func InverseVolWeights(cov [][]float64) []float64 {
	n := len(cov)
	w := make([]float64, n)
	if n == 0 {
		return w
	}
	sum := 0.0
	for i := 0; i < n; i++ {
		v := cov[i][i]
		if v <= 0 {
			w[i] = 0
			continue
		}
		w[i] = 1 / math.Sqrt(v)
		sum += w[i]
	}
	return normalizeOrEqual(w, sum)
}

// MaxWeightWeights وزن‌دهی هموزن با همان سقف وزن است (حالت شفاف/قاعده‌ای).
func MaxWeightWeights(n int, capWeight float64) []float64 {
	w := make([]float64, n)
	if n == 0 {
		return w
	}
	for i := range w {
		w[i] = 1.0 / float64(n)
	}
	return ApplyCap(w, capWeight)
}

// MinVarianceWeights وزن‌های کم‌واریانس را با گرادیان تصویری روی سیمپلکس
// (w≥۰، Σw=۱، w≤capWeight) پیدا می‌کند. بدون حل‌کننده‌ی بیرونی و بدون تصادف:
// گام با کران گرگورین بزرگ‌ترین مقدار ویژه تخمین زده می‌شود تا همگرا باشد.
func MinVarianceWeights(cov [][]float64, capWeight float64, iterations int) []float64 {
	n := len(cov)
	if n == 0 {
		return nil
	}
	if iterations <= 0 {
		iterations = 800
	}
	w := make([]float64, n)
	for i := range w {
		w[i] = 1.0 / float64(n)
	}
	w = ApplyCap(w, capWeight)

	// کران گرگورین: بیشینه‌ی مجموع قدرمطلق سطرها ≥ بزرگ‌ترین مقدار ویژه.
	lipschitz := 0.0
	for i := 0; i < n; i++ {
		row := 0.0
		for j := 0; j < n; j++ {
			row += math.Abs(cov[i][j])
		}
		if row > lipschitz {
			lipschitz = row
		}
	}
	if lipschitz <= 0 {
		return w
	}
	step := 1.0 / lipschitz

	for it := 0; it < iterations; it++ {
		// گرادیان: 2·Σw ؛ مؤلفه‌ی ثابت میانگین حذف می‌شود تا جهت روی سیمپلکس بماند.
		grad := make([]float64, n)
		for i := 0; i < n; i++ {
			s := 0.0
			for j := 0; j < n; j++ {
				s += cov[i][j] * w[j]
			}
			grad[i] = s
		}
		mb := Mean(grad)
		for i := 0; i < n; i++ {
			w[i] -= 2 * step * (grad[i] - mb)
		}
		w = ApplyCap(w, capWeight)
	}
	return w
}

// ApplyCap وزن‌ها را روی {w≥۰، Σw=۱، w≤cap} تصویر می‌کند (پرکردن آبی).
func ApplyCap(w []float64, capWeight float64) []float64 {
	n := len(w)
	if n == 0 {
		return w
	}
	if capWeight <= 0 || capWeight > 1 {
		capWeight = 1
	}
	if float64(n)*capWeight < 1 {
		// سقف با تعداد دارایی‌ها سازگار نیست؛ هموزن می‌شویم.
		out := make([]float64, n)
		for i := range out {
			out[i] = 1.0 / float64(n)
		}
		return out
	}
	out := append([]float64(nil), w...)
	for i := range out {
		if out[i] < 0 {
			out[i] = 0
		}
		if out[i] > capWeight {
			out[i] = capWeight
		}
	}
	// بازتوزیع باقیمانده بین وزن‌های غیرسقفی
	for round := 0; round < 100; round++ {
		sum := 0.0
		for _, v := range out {
			sum += v
		}
		diff := 1.0 - sum
		if math.Abs(diff) < 1e-12 {
			break
		}
		free := make([]int, 0, n)
		for i, v := range out {
			if diff > 0 && v < capWeight {
				free = append(free, i)
			} else if diff < 0 && v > 0 {
				free = append(free, i)
			}
		}
		if len(free) == 0 {
			break
		}
		share := diff / float64(len(free))
		for _, i := range free {
			out[i] += share
			if out[i] < 0 {
				out[i] = 0
			}
			if out[i] > capWeight {
				out[i] = capWeight
			}
		}
	}
	return out
}

func normalizeOrEqual(w []float64, sum float64) []float64 {
	n := len(w)
	if n == 0 {
		return w
	}
	if sum <= 0 {
		out := make([]float64, n)
		for i := range out {
			out[i] = 1.0 / float64(n)
		}
		return out
	}
	out := make([]float64, n)
	for i := range out {
		out[i] = w[i] / sum
	}
	return out
}

// PortfolioVolPct نوسان سالانه‌ی سبد را از کوواریانس (سالانه‌شده) برمی‌گرداند.
func PortfolioVolPct(w []float64, covAnnual [][]float64) float64 {
	n := len(w)
	if n == 0 {
		return 0
	}
	s := 0.0
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			s += w[i] * w[j] * covAnnual[i][j]
		}
	}
	if s <= 0 {
		return 0
	}
	return math.Sqrt(s) * 100.0
}

// PortfolioSeries بازده روزانه‌ی سبد را با وزن‌های ثابت می‌سازد.
func PortfolioSeries(w []float64, returns [][]float64) []float64 {
	n := len(w)
	if n == 0 || len(returns) == 0 {
		return nil
	}
	length := 0
	for i := 0; i < n; i++ {
		if len(returns[i]) > length {
			length = len(returns[i])
		}
	}
	out := make([]float64, length)
	for t := 0; t < length; t++ {
		s := 0.0
		for i := 0; i < n; i++ {
			if t < len(returns[i]) {
				s += w[i] * returns[i][t]
			}
		}
		out[t] = s
	}
	return out
}

// MaxDrawdownFromReturns حداکثر افت (درصد، ≤۰) را از سری بازده می‌سازد.
func MaxDrawdownFromReturns(rets []float64) float64 {
	eq := 1.0
	peak := 1.0
	worst := 0.0
	for _, r := range rets {
		eq *= 1 + r
		if eq > peak {
			peak = eq
		}
		if peak > 0 {
			if dd := (eq/peak - 1) * 100.0; dd < worst {
				worst = dd
			}
		}
	}
	return worst
}

// CumulativeFromReturns بازده کل (درصد) سری بازده‌ی مرکب.
func CumulativeFromReturns(rets []float64) float64 {
	eq := 1.0
	for _, r := range rets {
		eq *= 1 + r
	}
	return (eq - 1) * 100.0
}

// SharpeLike بازده/نوسان سالانه‌شده با نرخ بدون ریسک صفر.
func SharpeLike(rets []float64, tradingDays int) float64 {
	vol := AnnualizedVolPct(rets, tradingDays)
	if vol <= 0 {
		return 0
	}
	annRet := Mean(rets) * float64(tradingDays) * 100.0
	return annRet / vol
}

// AverageCorrelation میانگین همبستگی جفتی (خارج از قطر) را برمی‌گرداند.
func AverageCorrelation(cov [][]float64) float64 {
	n := len(cov)
	if n < 2 {
		return 0
	}
	sum, count := 0.0, 0
	for i := 0; i < n; i++ {
		for j := i + 1; j < n; j++ {
			si, sj := math.Sqrt(cov[i][i]), math.Sqrt(cov[j][j])
			if si <= 0 || sj <= 0 {
				continue
			}
			sum += cov[i][j] / (si * sj)
			count++
		}
	}
	if count == 0 {
		return 0
	}
	return sum / float64(count)
}

// TurnoverPct گردش یک‌طرفه‌ی سبد را نسبت به وزن‌های فعلی محاسبه می‌کند
// (۰.۵·Σ|wهدف − wفعلی|) و آن را به درصد کل سبد برمی‌گرداند.
func TurnoverPct(current, target map[string]float64) float64 {
	keys := map[string]struct{}{}
	for k := range current {
		keys[k] = struct{}{}
	}
	for k := range target {
		keys[k] = struct{}{}
	}
	sum := 0.0
	for k := range keys {
		sum += math.Abs(target[k] - current[k])
	}
	return sum / 2 * 100.0
}

// NormalizeWeightsToCash وزن‌ها را طوری مقیاس می‌دهد که مجموع سبد سهام برابر
// (۱ − بافر نقد) شود.
func NormalizeWeightsToCash(w []float64, cashBufferPct float64) []float64 {
	if cashBufferPct < 0 {
		cashBufferPct = 0
	}
	if cashBufferPct > 90 {
		cashBufferPct = 90
	}
	scale := 1 - cashBufferPct/100.0
	sum := 0.0
	for _, v := range w {
		sum += v
	}
	if sum <= 0 {
		return w
	}
	out := make([]float64, len(w))
	for i, v := range w {
		out[i] = v / sum * scale
	}
	return out
}

// TruncateName برای نمایش امن نام در لاگ.
func TruncateName(s string) string {
	s = strings.TrimSpace(s)
	if len([]rune(s)) <= 40 {
		return s
	}
	return string([]rune(s)[:40]) + "…"
}

// CapByGroup وزن هر گروه (مثلاً صنعت) را به groupCap از کل سبد محدود می‌کند:
// اعضای گروه‌های بالاسقف به‌تناسب کوچک می‌شوند و مازاد میان گروه‌های زیر سقف
// به‌تناسب وزنشان بازتوزیع می‌شود؛ خروجی همیشه مجموعاً ۱ است. تک‌گذره و قطعی.
func CapByGroup(w []float64, groups []string, groupCap float64) []float64 {
	n := len(w)
	if n == 0 || len(groups) != n || groupCap <= 0 || groupCap >= 1 {
		return w
	}
	total := 0.0
	for _, v := range w {
		total += v
	}
	if total <= 0 {
		return w
	}
	allowance := groupCap * total
	exposure := map[string]float64{}
	for i, v := range w {
		exposure[groups[i]] += v
	}
	reserved := 0.0
	over := map[string]bool{}
	for g, e := range exposure {
		if e > allowance {
			over[g] = true
			reserved += allowance
		} else {
			reserved += e
		}
	}
	out := append([]float64(nil), w...)
	if len(over) == 0 {
		return out
	}
	remaining := total - reserved
	if remaining <= 0 {
		// ظرفیت بازتوزیع صفر است؛ فقط گروه‌های بالاسقف به سقف می‌رسند.
		for g := range over {
			factor := allowance / exposure[g]
			for i, v := range out {
				if groups[i] == g {
					out[i] = v * factor
				}
			}
		}
		return out
	}
	// مازاد گروه‌های بالاسقف بین اعضای گروه‌های سالم به نسبت وزنشان
	overExposure := 0.0
	for g := range exposure {
		if over[g] {
			overExposure += exposure[g]
		}
	}
	excess := overExposure - float64(countTrue(over))*allowance
	underExposure := total - overExposure
	remFactor := (underExposure + excess) / underExposure
	for i, v := range out {
		if over[groups[i]] {
			out[i] = v * (allowance / exposure[groups[i]])
		} else {
			out[i] = v * remFactor
		}
	}
	return out
}

func countTrue(m map[string]bool) int {
	c := 0
	for _, v := range m {
		if v {
			c++
		}
	}
	return c
}
