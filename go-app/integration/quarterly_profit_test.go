package integration

import "testing"

func fp(report string, eps, capital, netProfit float64) FinancialInputRow {
	return FinancialInputRow{LegacyCompanyID: "c", ReportDate: report, EPS: eps, Capital: capital, NetProfit: netProfit}
}

func TestQuarterlyProfitDerivationWithinFiscalYear(t *testing.T) {
	// newest-first input; FY1404 cumulative proxy
	rows := []FinancialInputRow{
		fp("1404/12/29", 2747, 7_940_000, 0),
		fp("1404/09/30", 1849, 7_940_000, 0),
		fp("1404/06/31", 1149, 7_940_000, 0),
		fp("1404/03/31", 2759, 1_400_000, 0),
	}
	pts := DeriveQuarterlyProfit(rows)
	if len(pts) != 4 {
		t.Fatalf("want 4 periods got %d", len(pts))
	}
	if pts[0].PeriodEndDate != "1404/03/31" || pts[3].PeriodEndDate != "1404/12/29" {
		t.Fatalf("not chronological")
	}
	// Q1 standalone == cumulative; Q2 = cum2-cum1; etc. all within same year.
	if pts[0].Quarter != 1 || pts[3].Quarter != 4 {
		t.Fatalf("quarter numbering wrong: %d %d", pts[0].Quarter, pts[3].Quarter)
	}
	if pts[1].QuarterlyProfit != pts[1].CumulativeProfit-pts[0].CumulativeProfit {
		t.Fatalf("Q2 subtraction wrong")
	}
	if pts[2].QuarterlyProfit != pts[2].CumulativeProfit-pts[1].CumulativeProfit {
		t.Fatalf("Q3 subtraction wrong")
	}
	if pts[3].QuarterlyProfit != pts[3].CumulativeProfit-pts[2].CumulativeProfit {
		t.Fatalf("Q4 subtraction wrong")
	}
}

func TestQuarterlyProfitNoCrossYearSubtraction(t *testing.T) {
	rows := []FinancialInputRow{
		fp("1405/03/31", 500, 1_000_000, 0), // Q1 FY1405
		fp("1404/12/29", 400, 1_000_000, 0), // last of FY1404
	}
	pts := DeriveQuarterlyProfit(rows)
	// chronological: 1404/12/29 (Q1 of its year in this 1-period group), then 1405/03/31 new year Q1
	if pts[1].FiscalYear != 1405 || pts[1].Quarter != 1 {
		t.Fatalf("cross-year: new year must reset to Q1, got %+v", pts[1])
	}
	if pts[1].QuarterlyProfit != pts[1].CumulativeProfit {
		t.Fatalf("Q1 of a new fiscal year must not subtract the prior year")
	}
}

func TestQuarterlyProfitNegativeAndProxy(t *testing.T) {
	// proxy = EPS*Capital; negative (loss) supported
	rows := []FinancialInputRow{
		fp("1404/06/31", -50, 1_000_000, 0), // cum -5e7
		fp("1404/03/31", 100, 1_000_000, 0), // cum 1e8
	}
	pts := DeriveQuarterlyProfit(rows)
	if pts[0].QuarterlyProfit != 100_000_000 {
		t.Fatalf("Q1 wrong: %v", pts[0].QuarterlyProfit)
	}
	if pts[1].QuarterlyProfit != -150_000_000 {
		t.Fatalf("negative Q2 wrong: %v", pts[1].QuarterlyProfit)
	}
	// proxy is EPS*Capital (NOT raw EPS), never net_profit-driven units
	if ProfitProxyValue(fp("1404/06/31", 3, 1000, 999)) != 3000 {
		t.Fatalf("proxy must be EPS*Capital, got %v", ProfitProxyValue(fp("", 3, 1000, 999)))
	}
}

func TestQuarterlyProfitMissingPriorQuarter(t *testing.T) {
	// year starts with Q3 (no prior quarter in that year) -> standalone == cumulative (no bogus subtraction)
	rows := []FinancialInputRow{fp("1404/09/30", 10, 1000, 0)}
	pts := DeriveQuarterlyProfit(rows)
	if pts[0].QuarterlyProfit != pts[0].CumulativeProfit {
		t.Fatalf("missing prior quarter must not subtract")
	}
}
