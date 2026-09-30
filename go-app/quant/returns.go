// Package quant holds the deterministic portfolio/risk math used by the
// investment assistant.
//
// Rules that keep this package honest:
//   - pure Go, no external solver and no randomness;
//   - every function documents its units (percent vs fraction) and the order it
//     expects its input in;
//   - missing data is never fabricated: callers pass only real observations and
//     check lengths themselves.
//
// Price series are always handled oldest→newest inside this package; callers
// flip the canonical (newest-first) read order before calling.
package quant

import "math"

// DailyReturns converts a close series (oldest→newest) into simple daily
// returns as fractions. Non-positive or missing prices break the chain and are
// skipped, so len(returns) <= len(closes)-1.
func DailyReturns(closes []float64) []float64 {
	if len(closes) < 2 {
		return nil
	}
	out := make([]float64, 0, len(closes)-1)
	for i := 1; i < len(closes); i++ {
		prev, cur := closes[i-1], closes[i]
		if prev <= 0 || cur <= 0 {
			continue
		}
		out = append(out, (cur-prev)/prev)
	}
	return out
}

// Mean returns the arithmetic mean of xs (0 for an empty slice).
func Mean(xs []float64) float64 {
	if len(xs) == 0 {
		return 0
	}
	sum := 0.0
	for _, x := range xs {
		sum += x
	}
	return sum / float64(len(xs))
}

// Stdev returns the sample standard deviation (0 for fewer than two points).
func Stdev(xs []float64) float64 {
	if len(xs) < 2 {
		return 0
	}
	m := Mean(xs)
	sq := 0.0
	for _, x := range xs {
		d := x - m
		sq += d * d
	}
	return math.Sqrt(sq / float64(len(xs)-1))
}

// AnnualizedVolPct annualizes the volatility of a daily-return series to a
// percentage, using a 365-day calendar (Tehran market trades ~250 days/year;
// pass tradingDays explicitly when you need the trading-calendar figure).
func AnnualizedVolPct(dailyReturns []float64, tradingDays int) float64 {
	if tradingDays <= 0 {
		tradingDays = 250
	}
	return Stdev(dailyReturns) * math.Sqrt(float64(tradingDays)) * 100.0
}

// DownsideDeviationPct is the annualized downside deviation in percent,
// computed against a zero minimum acceptable return.
func DownsideDeviationPct(dailyReturns []float64, tradingDays int) float64 {
	if tradingDays <= 0 {
		tradingDays = 250
	}
	var sq []float64
	for _, r := range dailyReturns {
		if r < 0 {
			sq = append(sq, r*r)
		}
	}
	if len(sq) == 0 {
		return 0
	}
	return math.Sqrt(Mean(sq)) * math.Sqrt(float64(tradingDays)) * 100.0
}

// CumulativeReturnPct is the total return over the window in percent
// (oldest→newest closes).
func CumulativeReturnPct(closes []float64) float64 {
	if len(closes) < 2 || closes[0] <= 0 {
		return 0
	}
	return (closes[len(closes)-1]/closes[0] - 1) * 100.0
}

// MaxDrawdownPct is the worst peak-to-trough decline in percent (<= 0) over the
// given close series (oldest→newest).
func MaxDrawdownPct(closes []float64) float64 {
	if len(closes) < 2 {
		return 0
	}
	peak := closes[0]
	worst := 0.0
	for _, c := range closes {
		if c <= 0 {
			continue
		}
		if c > peak {
			peak = c
		}
		if peak > 0 {
			dd := (c/peak - 1) * 100.0
			if dd < worst {
				worst = dd
			}
		}
	}
	return worst
}

// WindowReturnPct is the return over the last n trading points in percent,
// where closes is oldest→newest (n=30 → last 30 sessions).
func WindowReturnPct(closes []float64, n int) (float64, bool) {
	if len(closes) < 2 || n <= 0 {
		return 0, false
	}
	if len(closes) <= n {
		n = len(closes) - 1
	}
	start := closes[len(closes)-1-n]
	end := closes[len(closes)-1]
	if start <= 0 {
		return 0, false
	}
	return (end/start - 1) * 100.0, true
}

// Correlation is the Pearson correlation of two equal-length series.
func Correlation(a, b []float64) float64 {
	n := len(a)
	if n < 2 || len(b) < n {
		return 0
	}
	ma, mb := Mean(a[:n]), Mean(b[:n])
	var cov, va, vb float64
	for i := 0; i < n; i++ {
		da, db := a[i]-ma, b[i]-mb
		cov += da * db
		va += da * da
		vb += db * db
	}
	if va == 0 || vb == 0 {
		return 0
	}
	return cov / math.Sqrt(va*vb)
}
