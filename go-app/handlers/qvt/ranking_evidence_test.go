package qvt

import "testing"

func TestEqualWeightDifferentFactorsAreNotFullCoverage(t *testing.T) {
	factor := func(id string) map[string]any {
		return map[string]any{"factors": map[string]any{id: map[string]any{"included": true, "weight": 3.0}}}
	}
	entries := []*rankEntry{{CompanyID: "a", ModelFamily: "general"}, {CompanyID: "b", ModelFamily: "general"}}
	q := map[string]any{"a": factor("interest_coverage"), "b": factor("earnings_quality")}
	v := map[string]any{"a": factor("pe"), "b": factor("pe")}
	rankAttachEvidence(entries, q, v, v)
	if entries[0].FullCoverage || entries[1].FullCoverage {
		t.Fatal("matching weights with different factors must not imply complete coverage")
	}
}

func TestRankingDistinguishesPolicyAndMissingData(t *testing.T) {
	var axis rankAxis
	rankEvidenceAxis(&axis, map[string]any{"factors": map[string]any{
		"earnings_growth":   map[string]any{"weight": 3.0, "included": false, "not_included_reason": "policy_excluded_step"},
		"interest_coverage": map[string]any{"weight": 3.0, "included": false, "normalization_status": "not_ranked_raw_missing"},
	}})
	kinds := map[string]string{}
	for _, f := range axis.MissingFactors {
		kinds[f.Factor] = f.Kind
	}
	if kinds["earnings_growth"] != "policy_excluded" || kinds["interest_coverage"] != "missing" {
		t.Fatal(kinds)
	}
	if rankBlockerDetail("momentum_6m_rel", map[string]any{"validation_reason": "return_window_mismatch: dates differ"}) == "" {
		t.Fatal("date mismatch must have a user-facing reason")
	}
}

func TestVerifiedMarketWarningsAreNotSeriousDataErrors(t *testing.T) {
	for _, kind := range []string{"verified_reopening_repricing", "shared_reference_before_calendar_window"} {
		class, ok := warnKindMap[kind]
		if !ok || class.Serious || class.Effect != effectReview || class.Severity != sevMarketStruct {
			t.Fatalf("incorrect market-warning classification: %s", kind)
		}
	}
}
