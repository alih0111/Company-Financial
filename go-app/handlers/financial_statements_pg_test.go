package handlers

import "testing"

func TestCanonicalFinancialFactsPreserveUnitsAndMissingValues(t *testing.T) {
	p := fsPeriod{AmountsInRial: true}
	revenue, profit, eps := 1000000000.0, 200000000.0, 125.0
	setCanonicalFinancialFact(&p, "revenue", "current", 1, &revenue, "rial")
	setCanonicalFinancialFact(&p, "net_profit", "current", 1, &profit, "rial")
	setCanonicalFinancialFact(&p, "eps", "current", 1, &eps, "rial_per_share")
	if p.IncomeStatement.EPS == nil || *p.IncomeStatement.EPS != 125 {
		t.Fatal("EPS units changed")
	}
	margin := fsPct(p.IncomeStatement.NetProfit.Current, p.IncomeStatement.Revenue.Current)
	if margin == nil || *margin != 20 {
		t.Fatal("margin incorrect")
	}
	if fsPct(nil, &revenue) != nil || fsPct(&revenue, nil) != nil {
		t.Fatal("missing values fabricated")
	}
	setCanonicalFinancialFact(&p, "revenue", "prior_year_same_period", 2, &revenue, "million_rial")
	if p.IncomeStatement.Revenue.LY != nil {
		t.Fatal("unconverted amount accepted")
	}
	setCanonicalFinancialFact(&p, "revenue", "restated", 1, &revenue, "rial")
	if p.IncomeStatement.Revenue.LY != nil {
		t.Fatal("restatement treated as prior year")
	}
	if p.IncomeStatement.Capital != nil || p.EpsCapitalAnchor != nil {
		t.Fatal("capital or anchor fabricated")
	}
}
