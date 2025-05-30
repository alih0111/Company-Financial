package handlers

import (
	"math"
	"strings"
)

func normalizePersian(s string) string {
	return strings.ReplaceAll(
		strings.ReplaceAll(s, "ي", "ی"),
		"ك", "ک",
	)
}

func extract(data []StockRow, f func(StockRow) float64) []float64 {
	out := make([]float64, len(data))
	for i, row := range data {
		out[i] = f(row)
	}
	return out
}

func round(val float64, places int) float64 {
	factor := math.Pow(10, float64(places))
	return math.Round(val*factor) / factor
}

func rollingMean(series []float64, window int) []float64 {
	out := make([]float64, len(series))
	for i := range series {
		if i >= window-1 {
			sum := 0.0
			for j := i - window + 1; j <= i; j++ {
				sum += series[j]
			}
			out[i] = sum / float64(window)
		}
	}
	return out
}

func rollingStdDev(series []float64, window int) []float64 {
	out := make([]float64, len(series))
	for i := range series {
		if i >= window-1 {
			mean := 0.0
			for j := i - window + 1; j <= i; j++ {
				mean += series[j]
			}
			mean /= float64(window)

			variance := 0.0
			for j := i - window + 1; j <= i; j++ {
				diff := series[j] - mean
				variance += diff * diff
			}
			out[i] = math.Sqrt(variance / float64(window))
		}
	}
	return out
}

func shift(series []float64, n int) []float64 {
	out := make([]float64, len(series))
	for i := range series {
		if i >= n {
			out[i] = series[i-n]
		}
	}
	return out
}

func subtractSeries(a, b []float64) []float64 {
	out := make([]float64, len(a))
	for i := range a {
		if i < len(b) {
			out[i] = a[i] - b[i]
		}
	}
	return out
}

func computeRSI(prices []float64, period int) []float64 {
	deltas := make([]float64, len(prices))
	for i := 1; i < len(prices); i++ {
		deltas[i] = prices[i] - prices[i-1]
	}

	gain := make([]float64, len(prices))
	loss := make([]float64, len(prices))
	for i, d := range deltas {
		if d > 0 {
			gain[i] = d
		} else {
			loss[i] = -d
		}
	}

	avgGain := rollingMean(gain, period)
	avgLoss := rollingMean(loss, period)

	rsi := make([]float64, len(prices))
	for i := range prices {
		if avgLoss[i] == 0 {
			rsi[i] = 100
		} else {
			rs := avgGain[i] / avgLoss[i]
			rsi[i] = 100 - (100 / (1 + rs))
		}
	}
	return rsi
}

func ema(series []float64, span int) []float64 {
	alpha := 2.0 / (float64(span) + 1)
	out := make([]float64, len(series))
	for i := range series {
		if i == 0 {
			out[i] = series[i]
		} else {
			out[i] = alpha*series[i] + (1-alpha)*out[i-1]
		}
	}
	return out
}

func percentChange(series []float64) []float64 {
	out := make([]float64, len(series))
	for i := 1; i < len(series); i++ {
		if series[i-1] != 0 {
			out[i] = (series[i] - series[i-1]) / series[i-1]
		}
	}
	return out
}

func rollingSlope(series []float64, window int) []float64 {
	out := make([]float64, len(series))
	for i := range series {
		if i >= window-1 {
			x := make([]float64, window)
			y := make([]float64, window)
			for j := 0; j < window; j++ {
				x[j] = float64(j)
				y[j] = series[i-window+1+j]
			}
			out[i] = linearSlope(x, y)
		}
	}
	return out
}

func linearSlope(x, y []float64) float64 {
	n := float64(len(x))
	if n == 0 {
		return 0
	}
	sumX, sumY, sumXY, sumX2 := 0.0, 0.0, 0.0, 0.0
	for i := range x {
		sumX += x[i]
		sumY += y[i]
		sumXY += x[i] * y[i]
		sumX2 += x[i] * x[i]
	}
	den := n*sumX2 - sumX*sumX
	if den == 0 {
		return 0
	}
	return (n*sumXY - sumX*sumY) / den
}
