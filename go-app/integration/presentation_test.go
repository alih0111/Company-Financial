package integration

import "testing"

func TestMonthlyPresentationPercentageAndWow(t *testing.T) {
	cases := []struct {
		name       string
		prod, sal  float64
		amountRial float64
		wantPct    float64
		wantWow    int
	}{
		{"positive-normal", 100, 90, 5_000_000_000_000, 5000, 0},
		{"production-pos-sales-neg", 100, -1, 5_000_000_000_000, 5000, 1},
		{"production-neg-sales-pos", -100, 1, 5_000_000_000_000, 5000, -1},
		{"zero-amount", 10, 10, 0, 0, 0},
		{"rounding", 0, 0, 1_234_567_890, 1.23, 0},
	}
	for _, c := range cases {
		pct, wow := MonthlyPresentation(c.prod, c.sal, c.amountRial)
		if pct != c.wantPct || wow != c.wantWow {
			t.Fatalf("%s: got (%.2f,%d) want (%.2f,%d)", c.name, pct, wow, c.wantPct, c.wantWow)
		}
	}
}

func TestMonthlyPresentationNoScoringTokens(t *testing.T) {
	// Presentation must not depend on the banned legacy heuristics.
	pct, _ := MonthlyPresentation(1, 1, 2_000_000_000)
	if pct != 2 {
		t.Fatalf("expected 2, got %v", pct)
	}
}
