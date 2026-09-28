package integration

import "math"

// This file defines the API-boundary presentation derivation for the legacy
// SalesData2 (monthly activity) response. The values are presentation-only and
// are NEVER stored as canonical facts. See FUNDAMENTALS_PRESENTATION_CONTRACT.md.
//
// Legacy reference (go-app/handlers/sales_data2.go):
//
//	s.Value1 /= 1e6; s.Value2 /= 1e6; s.Value3 /= 1e6
//	s.Percentage = round(s.Value3*1000*100) / 100
//	wow = +1 if Value1>0 && (Value2<0 || Value3<0); -1 if Value1<0 && (Value2>0 || Value3>0); else 0

// monthlyAmountDivisor converts canonical IRR to the legacy presentation scale.
// sales_amount_rial / 1e9 == reported_million_rial / 1e3.
const monthlyAmountDivisor = 1e9

// OrderFinancialAscending reverses the canonical newest-first financial rows to
// oldest-first so the chart renders left=older, right=newer.
func OrderFinancialAscending(rows []FinancialInputRow) []FinancialInputRow {
	out := make([]FinancialInputRow, len(rows))
	for i := range rows {
		out[len(rows)-1-i] = rows[i]
	}
	return out
}

// OrderMonthlyAscending reverses the canonical newest-first monthly rows to
// oldest-first for the chart.
func OrderMonthlyAscending(rows []MonthlyInputRow) []MonthlyInputRow {
	out := make([]MonthlyInputRow, len(rows))
	for i := range rows {
		out[len(rows)-1-i] = rows[i]
	}
	return out
}

// EpsPercentage is the canonical SalesData chart bar height: the period EPS
// (rial_per_share) rounded to 2 decimals. EPS is complete across the report
// history, unlike canonical net_profit which is materialized only for the
// latest report for most companies and would collapse the chart to one bar.
func EpsPercentage(eps float64) float64 {
	return math.Round(eps*100) / 100
}

// FactorRank returns a canonical factor percentile (0..1) from a rank map.
func FactorRank(ranks map[string]float64, code string) float64 {
	if ranks == nil {
		return 0
	}
	return ranks[code]
}

// FactorRaw returns a canonical factor raw value pointer, or nil when the value
// was not materialized (explicit missing -> JSON null in the UI).
func FactorRaw(raw map[string]float64, code string) *float64 {
	if raw == nil {
		return nil
	}
	v, ok := raw[code]
	if !ok {
		return nil
	}
	x := v
	return &x
}

// IncomeStatementPresentation derives the SalesData chart fields from canonical
// net-profit facts (current, prior year same period, prior fiscal year). The
// legacy EPS-times-Capital heuristic is DEPRECATED and never used. This is an
// explicitly defined canonical presentation, not a canonical fact.
//
//	percentage = round(net_profit_rial / 1e6, 2)
//	wow        = +1 / -1 / 0 from the sign relation of the three canonical values
func IncomeStatementPresentation(netProfitCurrent, netProfitPriorYear, netProfitPriorFiscal float64) (percentage float64, wow int) {
	percentage = math.Round(netProfitCurrent/1e6*100) / 100
	switch {
	case netProfitCurrent > 0 && (netProfitPriorYear < 0 || netProfitPriorFiscal < 0):
		wow = 1
	case netProfitCurrent < 0 && (netProfitPriorYear > 0 || netProfitPriorFiscal > 0):
		wow = -1
	default:
		wow = 0
	}
	return percentage, wow
}

// MonthlyPresentation derives the legacy SalesData2 presentation fields from a
// canonical monthly row. Both inputs and outputs are unit-explicit; no scale
// guessing is performed.
//
//	percentage = round(sales_amount_rial / 1e9, 2)
//	wow        = +1 / -1 / 0 from the sign relation of the three canonical values
//
// Zero/NULL handling: canonical zero is a real zero; the wow relation is strict
// (a zero component never triggers a sign conflict).
func MonthlyPresentation(productionQuantity, salesQuantity, salesAmountRial float64) (percentage float64, wow int) {
	percentage = math.Round(salesAmountRial/monthlyAmountDivisor*100) / 100
	switch {
	case productionQuantity > 0 && (salesQuantity < 0 || salesAmountRial < 0):
		wow = 1
	case productionQuantity < 0 && (salesQuantity > 0 || salesAmountRial > 0):
		wow = -1
	default:
		wow = 0
	}
	return percentage, wow
}
