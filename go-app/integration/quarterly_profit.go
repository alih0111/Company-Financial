package integration

import (
	"sort"
	"strconv"
	"strings"
)

// QuarterlyProfitPoint is the explicit quarterly-profit chart contract.
//
// CumulativeProfit is the period's cumulative (YTD) net-profit proxy in the
// source unit; QuarterlyProfit is the standalone quarter derived by subtracting
// the previous period of the SAME fiscal year. FiscalYear is taken from the
// Jalali period prefix (canonical migrated statements do not carry fiscal
// metadata), so it is a documented fiscal-year proxy.
type QuarterlyProfitPoint struct {
	PeriodEndDate    string
	FiscalYear       int
	Quarter          int
	CumulativeProfit float64
	QuarterlyProfit  float64
	SourceReportID   string
}

// ProfitProxyValue returns the cumulative net-profit proxy for a period:
// EPS x Capital, which equals the legacy mixed-scale net-profit proxy exactly and
// is the metric the legacy chart plotted. A single consistent series is used for
// every period so the quarterly subtraction stays in one unit.
//
// IMPORTANT: for most companies the legacy source (miandore2.NetProfitAmount) has
// null net profit for every historical period, so this proxy is the only complete
// deterministic cumulative profit series. True historical net profit is
// source-absent. This is a presentation value only and is never stored as a
// canonical fact.
func ProfitProxyValue(r FinancialInputRow) float64 {
	return r.EPS * r.Capital
}

// DeriveQuarterlyProfit converts a newest-first financial series into a
// chronological standalone-quarter profit series, subtracting only within the
// same fiscal year (Jalali year of the period). It never subtracts across years.
func DeriveQuarterlyProfit(rows []FinancialInputRow) []QuarterlyProfitPoint {
	ordered := OrderFinancialAscending(rows)
	points := make([]QuarterlyProfitPoint, 0, len(ordered))
	prevYear := -1
	prevCumulative := 0.0
	quarterInYear := 0
	for _, r := range ordered {
		year, _ := jalaliYearMonth(r.ReportDate)
		cum := ProfitProxyValue(r)
		if year != prevYear {
			quarterInYear = 0
			prevCumulative = 0
			prevYear = year
		}
		quarterInYear++
		standalone := cum
		if quarterInYear > 1 {
			standalone = cum - prevCumulative
		}
		prevCumulative = cum
		points = append(points, QuarterlyProfitPoint{
			PeriodEndDate:    r.ReportDate,
			FiscalYear:       year,
			Quarter:          quarterInYear,
			CumulativeProfit: cum,
			QuarterlyProfit:  standalone,
		})
	}
	return points
}

// OrderQuarterlyByPeriod is used by tests/tools to expose a stable chronological
// ordering.
func OrderQuarterlyByPeriod(points []QuarterlyProfitPoint) []QuarterlyProfitPoint {
	out := append([]QuarterlyProfitPoint(nil), points...)
	sort.SliceStable(out, func(i, j int) bool { return out[i].PeriodEndDate < out[j].PeriodEndDate })
	return out
}

// jalaliYearMonth extracts the Jalali year and month from a period text such as
// "1404/09/30".
func jalaliYearMonth(period string) (int, int) {
	parts := strings.SplitN(strings.TrimSpace(period), "/", 3)
	if len(parts) < 2 {
		return 0, 0
	}
	y, _ := strconv.Atoi(parts[0])
	m, _ := strconv.Atoi(parts[1])
	return y, m
}
