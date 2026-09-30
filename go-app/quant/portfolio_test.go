package quant

import (
	"math"
	"testing"
)

func almostEqual(a, b, tol float64) bool { return math.Abs(a-b) <= tol }

func TestForwardFillAndAlignedReturns(t *testing.T) {
	// سری A روی دو تاریخ مشترک و یک تاریخ اختصاصی؛ سری B یک روز عقب‌تر شروع می‌شود.
	a := Series{Key: "A", Dates: []string{"d1", "d2", "d3"}, Prices: []float64{100, 110, 121}}
	b := Series{Key: "B", Dates: []string{"d2", "d3"}, Prices: []float64{50, 55}}

	dates, matrix, starts, ok := AlignedReturns([]Series{a, b}, 1)
	// تقویم [d1,d2,d3] است و بازده‌ها روی [d2,d3] تعریف می‌شوند.
	if len(dates) != 2 {
		t.Fatalf("expected 2 return dates, got %d (%v)", len(dates), dates)
	}
	if starts[0] != 0 || starts[1] != 1 {
		t.Fatalf("series start columns wrong: %v", starts)
	}
	if !ok[0] || !ok[1] {
		t.Fatalf("both series should be usable: %v", ok)
	}
	// A: +10%, +10% ; B در d1 هنوز شروع نشده و در d2 با forward-fill صفر بازده می‌گیرد.
	if !almostEqual(matrix[0][0], 0.10, 1e-9) || !almostEqual(matrix[0][1], 0.10, 1e-9) {
		t.Fatalf("A returns wrong: %v", matrix[0])
	}
	if !almostEqual(matrix[1][0], 0, 1e-12) {
		t.Fatalf("B first return should be 0 (not started yet): %v", matrix[1])
	}
	if !almostEqual(matrix[1][1], 0.10, 1e-9) {
		t.Fatalf("B second return should be +10%%: %v", matrix[1])
	}
}

func TestInverseVolWeightsDiagonal(t *testing.T) {
	// کوواریانس قطری: وزن معکوس‌نوسان باید دقیقاً متناسب با 1/σ باشد.
	// σ1=0.01، σ2=0.02 → w ∝ 100 و 50 → ۲/۳ و ۱/۳
	cov := [][]float64{
		{0.0001, 0},
		{0, 0.0004},
	}
	w := InverseVolWeights(cov)
	if !almostEqual(w[0], 2.0/3.0, 1e-9) || !almostEqual(w[1], 1.0/3.0, 1e-9) {
		t.Fatalf("inverse-vol weights wrong: %v", w)
	}
	if !almostEqual(w[0]+w[1], 1, 1e-12) {
		t.Fatalf("weights must sum to 1: %v", w)
	}
}

func TestApplyCapRespectsCapAndSum(t *testing.T) {
	w := ApplyCap([]float64{0.9, 0.05, 0.05}, 0.5)
	for i, v := range w {
		if v > 0.5+1e-12 {
			t.Fatalf("cap violated at %d: %v", i, v)
		}
		if v < 0 {
			t.Fatalf("negative weight at %d: %v", i, v)
		}
	}
	sum := w[0] + w[1] + w[2]
	if !almostEqual(sum, 1, 1e-9) {
		t.Fatalf("weights must still sum to 1, got %v", sum)
	}
	// سقف ناسازگار (۳ دارایی، سقف ۰.۲) → هموزن
	we := ApplyCap([]float64{0.5, 0.5, 0}, 0.2)
	if !almostEqual(we[0], 1.0/3.0, 1e-9) {
		t.Fatalf("incompatible cap should fall back to equal weights: %v", we)
	}
}

func TestMinVarianceFavoursLowVolAsset(t *testing.T) {
	// دو دارایی ناهمبسته با نوسان مختلف: وزن دارایی کم‌نوسان‌تر باید بیشتر باشد
	// و نوسان سبد باید کمتر از دارایی پرنوسان و معکوس‌نوسان ساده باشد.
	cov := [][]float64{
		{0.0004, 0}, // σ=2%
		{0, 0.0025}, // σ=5%
	}
	w := MinVarianceWeights(cov, 0.9, 2000)
	if w[0] <= w[1] {
		t.Fatalf("low-vol asset should get more weight: %v", w)
	}
	if !almostEqual(w[0]+w[1], 1, 1e-9) {
		t.Fatalf("weights must sum to 1: %v", w)
	}
	// حل تحلیلی کم‌واریانس دو دارایی ناهمبسته: w1 = σ2²/(σ1²+σ2²)
	want := 0.0025 / (0.0004 + 0.0025)
	if !almostEqual(w[0], want, 5e-3) {
		t.Fatalf("min-variance weight off: got %.4f want %.4f", w[0], want)
	}
	// با همبستگی منفی شدید، نوسان سبد باید از هر دو دارایی کمتر شود.
	covNeg := [][]float64{
		{0.0004, -0.0009},
		{-0.0009, 0.0025},
	}
	wn := MinVarianceWeights(covNeg, 0.95, 4000)
	vol := PortfolioVolPct(wn, covNeg)
	if vol >= 2.0*100 {
		t.Fatalf("hedged portfolio vol should be far below the riskiest asset: %v", vol)
	}
}

func TestPortfolioMetricsOnHandComputedSeries(t *testing.T) {
	// بازده‌های ساده: +10%، −10% → بازده کل 1.1*0.9-1 = −1%
	rets := []float64{0.10, -0.10}
	if got := CumulativeFromReturns(rets); !almostEqual(got, -1.0, 1e-9) {
		t.Fatalf("cumulative return wrong: %v", got)
	}
	// حداکثر افت نقطه‌به‌نقطه: از اوج 1.1 به 0.99 → −10%
	if got := MaxDrawdownFromReturns(rets); !almostEqual(got, -10.0, 1e-9) {
		t.Fatalf("max drawdown wrong: %v", got)
	}
	// نوسان سالانه‌شده: انحراف معیار نمونه‌ای دو بازده = 0.141421 → ×√250
	wantVol := 0.14142135623730951 * math.Sqrt(250) * 100
	if got := AnnualizedVolPct(rets, 250); !almostEqual(got, wantVol, 1e-6) {
		t.Fatalf("annualized vol wrong: got %v want %v", got, wantVol)
	}
}

func TestShrinkageAndCorrelation(t *testing.T) {
	cov := [][]float64{
		{0.04, 0.02},
		{0.02, 0.09},
	}
	s := ShrinkCovariance(cov, 0.5)
	if !almostEqual(s[0][0], 0.04, 1e-12) {
		t.Fatalf("diagonal must be preserved: %v", s)
	}
	if !almostEqual(s[0][1], 0.01, 1e-12) {
		t.Fatalf("off-diagonal must shrink by (1-lambda): %v", s)
	}
	corr := AverageCorrelation(cov)
	want := 0.02 / (math.Sqrt(0.04) * math.Sqrt(0.09))
	if !almostEqual(corr, want, 1e-12) {
		t.Fatalf("correlation wrong: got %v want %v", corr, want)
	}
}

func TestTurnoverAndCashBuffer(t *testing.T) {
	cur := map[string]float64{"A": 0.5, "B": 0.5}
	tgt := map[string]float64{"A": 0.8, "C": 0.2}
	// Σ|Δ| = 0.3 + 0.5 + 0.2 = 1.0 → گردش یک‌طرفه ۵۰٪
	if got := TurnoverPct(cur, tgt); !almostEqual(got, 50.0, 1e-9) {
		t.Fatalf("turnover wrong: %v", got)
	}
	w := NormalizeWeightsToCash([]float64{0.6, 0.4}, 10)
	if !almostEqual(w[0]+w[1], 0.9, 1e-12) {
		t.Fatalf("cash buffer not applied: %v", w)
	}
}

func TestPortfolioVolFromCovariance(t *testing.T) {
	cov := [][]float64{
		{0.04, 0.0},
		{0.0, 0.04},
	}
	// با وزن هموزن، نوسان سبد = σ/√2 = 20%/1.414 = 14.14%
	got := PortfolioVolPct([]float64{0.5, 0.5}, cov)
	if !almostEqual(got, 20.0/math.Sqrt2, 1e-9) {
		t.Fatalf("portfolio vol wrong: %v", got)
	}
}

func TestCapByGroupRedistributesExcess(t *testing.T) {
	// دو صنعت: صنعت A با ۷۰٪ وزن باید به ۴۰٪ سقف برسد و مازاد به صنعت B برود.
	w := []float64{0.35, 0.35, 0.30}
	groups := []string{"فلزات", "فلزات", "شیمی"}
	got := CapByGroup(w, groups, 0.40)
	sum := got[0] + got[1] + got[2]
	if !almostEqual(sum, 1, 1e-9) {
		t.Fatalf("weights must sum to 1: %v", got)
	}
	if got[0]+got[1] > 0.40+1e-9 {
		t.Fatalf("industry cap violated: %v", got)
	}
	if got[2] <= 0.30 {
		t.Fatalf("uncapped group should absorb the excess: %v", got)
	}
	// بدون تخطی، تغییری نمی‌کند
	same := CapByGroup([]float64{0.3, 0.3, 0.4}, []string{"الف", "ب", "ج"}, 0.4)
	if !almostEqual(same[0], 0.3, 1e-12) || !almostEqual(same[2], 0.4, 1e-12) {
		t.Fatalf("compliant input must be unchanged: %v", same)
	}
}
