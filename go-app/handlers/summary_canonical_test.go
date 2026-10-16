package handlers

import (
	"go-app/integration"
	"testing"
)

func TestSummaryDeduplicatesCanonicalAliasesBeforeLimit(t *testing.T) {
	rows := []integration.AllScoreInputRow{
		{CanonicalID: "issuer-a", LegacyCompanyID: "b", QuantScore: 80},
		{CanonicalID: "issuer-a", LegacyCompanyID: "a", QuantScore: 80},
		{CanonicalID: "issuer-b", LegacyCompanyID: "c", QuantScore: 70},
	}
	out := buildCanonicalSummary(rows, 2)
	if len(out) != 2 || out[0].CompanyID != "a" || out[1].CompanyID != "c" {
		t.Fatalf("aliases occupied a top slot or selection was unstable: %+v", out)
	}
	if rows[0].LegacyCompanyID != "b" {
		t.Fatal("input rows were mutated")
	}
}
