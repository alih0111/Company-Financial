package integration

import "testing"

// The canonical SalesData chart must keep the full history, order oldest ->
// newest, and derive a nonzero bar per period from EPS. The earlier net_profit
// derivation collapsed the chart to a single bar.
func TestFinancialAscendingAndEpsPresentation(t *testing.T) {
	in := []FinancialInputRow{
		{LegacyCompanyID: "c", ReportDate: "1405/03/31", EPS: 300},
		{LegacyCompanyID: "c", ReportDate: "1404/12/29", EPS: 200},
		{LegacyCompanyID: "c", ReportDate: "1404/09/30", EPS: 100},
		{LegacyCompanyID: "c", ReportDate: "1404/06/31", EPS: 50},
	}
	out := OrderFinancialAscending(in)
	if len(out) != len(in) {
		t.Fatalf("history collapsed: %d vs %d", len(out), len(in))
	}
	if out[0].ReportDate != "1404/06/31" || out[len(out)-1].ReportDate != "1405/03/31" {
		t.Fatalf("not chronological ASC: %s..%s", out[0].ReportDate, out[len(out)-1].ReportDate)
	}
	if EpsPercentage(out[0].EPS) != 50 || EpsPercentage(out[3].EPS) != 300 {
		t.Fatalf("EPS presentation wrong")
	}
}

func TestMonthlyAscending(t *testing.T) {
	out := OrderMonthlyAscending([]MonthlyInputRow{
		{ReportDate: "1405/04/31"}, {ReportDate: "1405/03/31"}, {ReportDate: "1405/02/31"},
	})
	if out[0].ReportDate != "1405/02/31" || out[2].ReportDate != "1405/04/31" {
		t.Fatalf("monthly not ASC: %s..%s", out[0].ReportDate, out[2].ReportDate)
	}
}

// Score-detail display contract: percentile ranks (0..1) drive fills; raw values
// that canonical-v1 does not materialize are nil (explicit missing -> JSON null).
func TestFactorRankAndRawNull(t *testing.T) {
	ranks := map[string]float64{"SalesGrowth": 0.95, "PE": 0.4}
	raw := map[string]float64{} // canonical-v1 has no raw values
	if FactorRank(ranks, "SalesGrowth") != 0.95 || FactorRank(ranks, "PE") != 0.4 {
		t.Fatalf("rank mapping wrong")
	}
	if r := FactorRank(ranks, "SalesGrowth"); r < 0 || r > 1 {
		t.Fatalf("rank out of bounds: %v", r)
	}
	if FactorRaw(raw, "SalesGrowth") != nil {
		t.Fatalf("unmaterialized raw value must be nil/null")
	}
	if v := FactorRaw(map[string]float64{"PE": 12.5}, "PE"); v == nil || *v != 12.5 {
		t.Fatalf("materialized raw value not returned")
	}
}
