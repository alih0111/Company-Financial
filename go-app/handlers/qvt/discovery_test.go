package qvt

// Unit tests for the discovery feed — pure, no database, no real artifacts.
//
// Verified here:
//   - balanced mode: transparent Pareto layers, only inside comparable
//     groups; layer-1 reason; deterministic layer-then-symbol order
//   - groups require identical scored-factor sets per axis: different
//     coverage ⇒ different group ⇒ no dominance is ever applied across
//     coverage boundaries
//   - small groups (<5): balanced ranking declared invalid, rows still
//     shown with the honest reason, never silently dropped
//   - single-axis modes: display order by observed points with within-group
//     ranks; switching mode really changes the results
//   - the core honesty property: a company with less coverage but higher
//     raw points is never given an artificial multi-axis advantage — its
//     missing factor stays listed, nothing is renormalized, and no
//     total/100 key exists anywhere in the payload
//   - the discovery universe is exactly the triple-eligible companies
//   - gates: missing artifact → 503, snapshot mismatch → 409

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

type discFixture struct {
	ID, Symbol, Industry, Family string
	QPts, VPts, TPts             float64
	QEl, VEl, TEl                bool
	QScored, VScored, TScored    []string
	QNotScored                   map[string]string // factor id → not_included_reason
	OutOfScope                   bool              // Q row without pilot_eligible
	TNilPoints                   bool              // T row without observed points
}

func discFactorSet(ids []string) map[string]any {
	out := map[string]any{}
	for _, id := range ids {
		out[id] = map[string]any{
			"weight": 3, "essential": true, "direction": "higher",
			"raw_status": "valid", "raw_value": 1.0,
			"normalization_status": "ranked", "n_valid_market_family": 50, "n_valid_sector": 3,
			"score": 0.5, "score_kind": "percentile_combined",
			"included": true, "contribution_points": 1.5,
		}
	}
	return out
}

func discWriteFixtures(t *testing.T, dir string, fx []discFixture) {
	t.Helper()
	qc := map[string]any{}
	vc := map[string]any{}
	tc := map[string]any{}
	for _, c := range fx {
		fam := c.Family
		if fam == "" {
			fam = "general"
		}
		qFactors := discFactorSet(c.QScored)
		for id, reason := range c.QNotScored {
			qFactors[id] = map[string]any{
				"weight": 3, "direction": "higher", "included": false,
				"not_included_reason": reason, "normalization_status": "pending_data",
			}
		}
		qrow := map[string]any{
			"company_id": c.ID, "symbol": c.Symbol, "model_family": fam, "industry": c.Industry,
			"aggregation_status": "aggregated", "q_observed_points": c.QPts,
			"covered_weight": float64(len(c.QScored)) * 3.0, "missing_weight": (10 - float64(len(c.QScored))) * 3.0,
			"coverage_ratio": float64(len(c.QScored)) * 3.0 / 30.0, "coverage_threshold_met": true,
			"essential_status": map[string]any{"required": []string{"margins"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":   c.QEl,
			"data_confidence":  map[string]any{"status": "not_evaluated"},
			"risk_gate":        map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated", "financial_warnings": []any{}},
			"factors":          qFactors,
		}
		if c.OutOfScope {
			delete(qrow, "pilot_eligible")
			qrow["aggregation_status"] = "family_out_of_scope"
			qrow["reason"] = "model_family 'bank': this pilot aggregates the 'general' family only"
		}
		qc[c.ID] = qrow
		vc[c.ID] = map[string]any{
			"company_id": c.ID, "symbol": c.Symbol, "model_family": fam, "industry": c.Industry,
			"v_observed_points": c.VPts, "covered_weight": float64(len(c.VScored)) * 3.0,
			"missing_weight": 0.0, "coverage_ratio": 1.0, "coverage_threshold_met": true,
			"essential_status": map[string]any{"required": []string{"pb"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":   c.VEl,
			"data_confidence":  map[string]any{"status": "not_evaluated"},
			"risk_gate":        map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated", "financial_warnings": []any{}},
			"factors":          discFactorSet(c.VScored),
		}
		trow := map[string]any{
			"company_id": c.ID, "symbol": c.Symbol, "model_family": fam, "industry": c.Industry,
			"t_observed_points": c.TPts, "covered_weight": float64(len(c.TScored)) * 3.0,
			"missing_weight": 0.0, "coverage_ratio": 1.0, "coverage_threshold_met": true,
			"essential_status": map[string]any{"required": []string{"liquidity"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":   c.TEl,
			"data_confidence":  map[string]any{"status": "not_evaluated"},
			"risk_gate":        map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated", "trading_warnings": []any{}},
			"factors":          discFactorSet(c.TScored),
		}
		if c.TNilPoints {
			delete(trow, "t_observed_points")
		}
		tc[c.ID] = trow
	}
	docs := map[string]map[string]any{
		"v2_q_observed_report.json": {
			"as_of": qvtTestQAsOf, "score_version": "v2-observed-pilot",
			"weight_table": map[string]any{"axis": "quality", "target_weight": 40.0},
			"policy":       map[string]any{"coverage_threshold": 0.5},
			"companies":    qc,
		},
		"v2_value_pilot.json": {
			"as_of": "2026-10-08", "cutoff": qvtTestCut,
			"v_observed_report": map[string]any{"companies": vc},
		},
		"v2_t_pilot.json": {
			"as_of": "2026-10-08", "cutoff": qvtTestCut,
			"t_observed_report": map[string]any{"companies": tc},
		},
	}
	for name, doc := range docs {
		raw, err := json.Marshal(doc)
		if err != nil {
			t.Fatalf("marshal %s: %v", name, err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), raw, 0o644); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}
}

func discServer(t *testing.T, fx []discFixture) *gin.Engine {
	t.Helper()
	dir := t.TempDir()
	discWriteFixtures(t, dir, fx)
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/qvt-v2/discovery", GetQvtV2Discovery)
	return r
}

func discFetch(t *testing.T, r *gin.Engine) map[string]any {
	t.Helper()
	w := qvtDo(r, "/api/qvt-v2/discovery")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	return qvtDecode(t, w)
}

func discMode(t *testing.T, d map[string]any, mode string) map[string]any {
	t.Helper()
	m, ok := d["modes"].(map[string]any)[mode].(map[string]any)
	if !ok {
		t.Fatalf("mode %s missing from response", mode)
	}
	return m
}

func discRows(t *testing.T, m map[string]any) []map[string]any {
	t.Helper()
	arr, ok := m["rows"].([]any)
	if !ok {
		t.Fatalf("rows missing")
	}
	out := make([]map[string]any, 0, len(arr))
	for _, r := range arr {
		out = append(out, r.(map[string]any))
	}
	return out
}

func discRowIDs(rows []map[string]any) []string {
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r["company_id"].(string))
	}
	return ids
}

func discCounts(t *testing.T, m map[string]any) map[string]float64 {
	t.Helper()
	c, ok := m["counts"].(map[string]any)
	if !ok {
		t.Fatalf("counts missing")
	}
	out := map[string]float64{}
	for k, v := range c {
		out[k] = v.(float64)
	}
	return out
}

var discStdSet = []string{"f1", "f2", "f3"}
var discHalfSet = []string{"f1", "f2"}

func sameSetFixture(id, symbol, industry string, q, v, tt float64) discFixture {
	return discFixture{ID: id, Symbol: symbol, Industry: industry, QPts: q, VPts: v, TPts: tt,
		QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet}
}

func TestDiscoveryBalancedParetoLayers(t *testing.T) {
	// p1 dominates everyone; p3/p4/p5 form the second front; p2 is last.
	r := discServer(t, []discFixture{
		sameSetFixture("p1", "الف", "شیمیایی", 10, 10, 10),
		sameSetFixture("p3", "ب", "شیمیایی", 10, 9, 9),
		sameSetFixture("p4", "پ", "شیمیایی", 9, 10, 9),
		sameSetFixture("p5", "ت", "شیمیایی", 9.5, 9.5, 9.5),
		sameSetFixture("p2", "ث", "شیمیایی", 9, 9, 9),
	})
	d := discFetch(t, r)
	m := discMode(t, d, "balanced")
	c := discCounts(t, m)
	if c["groups_total"] != 1 || c["groups_valid"] != 1 || c["ranked"] != 5 || c["not_ranked"] != 0 {
		t.Fatalf("counts wrong: %v", c)
	}
	rows := discRows(t, m)
	gotLayers := map[string]float64{}
	for _, row := range rows {
		if row["comparability"] != "comparable" {
			t.Fatalf("all rows must be comparable: %v", row)
		}
		l, ok := row["pareto_layer"].(float64)
		if !ok {
			t.Fatalf("layer missing for %v", row)
		}
		gotLayers[row["company_id"].(string)] = l
	}
	want := map[string]float64{"p1": 1, "p3": 2, "p4": 2, "p5": 2, "p2": 3}
	for id, l := range want {
		if gotLayers[id] != l {
			t.Fatalf("layer[%s] = %v want %v", id, gotLayers[id], l)
		}
	}
	// order: layer asc, then symbol (UTF-8 byte order: ب < ت < پ)
	if got := discRowIDs(rows); strings.Join(got, ",") != "p1,p3,p5,p4,p2" {
		t.Fatalf("display order = %v", got)
	}
	// layer-1 reason states no peer dominates it on any axis
	for _, row := range rows {
		if row["company_id"] == "p1" && !strings.Contains(row["reason"].(string), "هیچ همتای گروهی") {
			t.Fatalf("layer-1 reason wrong: %v", row["reason"])
		}
	}
	// mode note keeps pareto as discovery aid only
	if !strings.Contains(m["order_note"].(string), "ابزار کشف") {
		t.Fatalf("order_note must mark layers as discovery aid: %v", m["order_note"])
	}
}

func TestDiscoveryBalancedSmallGroupInvalid(t *testing.T) {
	r := discServer(t, []discFixture{
		sameSetFixture("a", "الف", "دارو", 10, 10, 10),
		sameSetFixture("b", "ب", "دارو", 9, 9, 9),
		sameSetFixture("c", "پ", "دارو", 8, 8, 8),
	})
	d := discFetch(t, r)
	m := discMode(t, d, "balanced")
	c := discCounts(t, m)
	if c["groups_valid"] != 0 || c["ranked"] != 0 || c["not_ranked"] != 3 || c["companies"] != 3 {
		t.Fatalf("counts wrong: %v", c)
	}
	for _, row := range discRows(t, m) {
		if row["comparability"] != "small_group" {
			t.Fatalf("small group must be flagged: %v", row)
		}
		if _, ok := row["pareto_layer"]; ok {
			t.Fatalf("invalid group must not emit a pareto layer: %v", row)
		}
		if !strings.Contains(row["reason"].(string), "رتبه‌بندی متوازن") || !strings.Contains(row["reason"].(string), "۵") {
			t.Fatalf("reason must declare invalid balanced ranking: %v", row["reason"])
		}
	}
}

func TestDiscoveryGroupingRequiresIdenticalScoredFactors(t *testing.T) {
	// b covers one fewer Q factor (6/9 weight vs 9/9) — never grouped with a.
	r := discServer(t, []discFixture{
		{ID: "a", Symbol: "الف", Industry: "فولاد", QPts: 20, VPts: 10, TPts: 10,
			QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
		{ID: "b", Symbol: "ب", Industry: "فولاد", QPts: 25, VPts: 10, TPts: 10,
			QEl: true, VEl: true, TEl: true, QScored: discHalfSet, VScored: discStdSet, TScored: discStdSet,
			QNotScored: map[string]string{"f3": "raw_missing: the factor's inputs are absent — a missing factor has no score share, never a zero-performance reading"}},
	})
	d := discFetch(t, r)
	m := discMode(t, d, "balanced")
	c := discCounts(t, m)
	if c["groups_total"] != 2 || c["groups_valid"] != 0 || c["ranked"] != 0 {
		t.Fatalf("different scored sets must split groups: %v", c)
	}
	// quality mode: each in its own single-member group; ranks are informational
	qm := discMode(t, d, "quality")
	for _, row := range discRows(t, qm) {
		if row["group_size"].(float64) != 1 || row["group_valid"].(bool) {
			t.Fatalf("single-member group must be invalid: %v", row)
		}
		if !strings.Contains(row["reason"].(string), "اطلاعی") {
			t.Fatalf("reason must mark informational rank: %v", row["reason"])
		}
	}
	// b's missing factor stays listed with its real reason — never zero-filled
	comps := d["companies"].([]any)
	for _, co := range comps {
		cm := co.(map[string]any)
		if cm["company_id"] != "b" {
			continue
		}
		issues := cm["q"].(map[string]any)["factor_issues"].([]any)
		found := false
		for _, is := range issues {
			im := is.(map[string]any)
			if im["factor"] == "f3" && strings.Contains(im["reason"].(string), "raw_missing") {
				found = true
			}
		}
		if !found {
			t.Fatalf("b's not-scored factor must surface with its reason: %v", issues)
		}
	}
}

func TestDiscoverySingleAxisOrderAndModeSwitch(t *testing.T) {
	r := discServer(t, []discFixture{
		{ID: "a", Symbol: "الف", Industry: "فولاد", QPts: 30, VPts: 10, TPts: 5,
			QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
		{ID: "b", Symbol: "ب", Industry: "فولاد", QPts: 25, VPts: 20, TPts: 6,
			QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
		{ID: "c", Symbol: "پ", Industry: "دارو", QPts: 28, VPts: 15, TPts: 7,
			QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
	})
	d := discFetch(t, r)
	qm := discMode(t, d, "quality")
	if got := discRowIDs(discRows(t, qm)); strings.Join(got, ",") != "a,c,b" {
		t.Fatalf("quality display order = %v want a,c,b", got)
	}
	vm := discMode(t, d, "value")
	if got := discRowIDs(discRows(t, vm)); strings.Join(got, ",") != "b,c,a" {
		t.Fatalf("value display order = %v want b,c,a", got)
	}
	tm := discMode(t, d, "timing")
	if got := discRowIDs(discRows(t, tm)); strings.Join(got, ",") != "c,b,a" {
		t.Fatalf("timing display order = %v want c,b,a", got)
	}
	// within-group ranks: a=1,b=2 in فولاد; c=1 in دارو
	for _, row := range discRows(t, qm) {
		id := row["company_id"].(string)
		var want float64
		switch id {
		case "a":
			want = 1
		case "b":
			want = 2
		case "c":
			want = 1
		}
		if row["group_rank"].(float64) != want {
			t.Fatalf("group_rank[%s] = %v want %v", id, row["group_rank"], want)
		}
	}
	// the single-axis order must never claim cross-group validity
	if !strings.Contains(qm["order_note"].(string), "رتبه بنیادی معتبر") {
		t.Fatalf("order_note must deny cross-group validity: %v", qm["order_note"])
	}
}

// TestDiscoveryMissingCoverageNoArtificialAdvantage is the core honesty test:
// less coverage with higher raw points buys no multi-axis advantage, nothing
// is renormalized, the missing factor stays listed, and no total exists.
func TestDiscoveryMissingCoverageNoArtificialAdvantage(t *testing.T) {
	r := discServer(t, []discFixture{
		{ID: "a", Symbol: "الف", Industry: "فولاد", QPts: 20, VPts: 10, TPts: 10,
			QEl: true, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
		{ID: "b", Symbol: "ب", Industry: "فولاد", QPts: 25, VPts: 10, TPts: 10,
			QEl: true, VEl: true, TEl: true, QScored: discHalfSet, VScored: discStdSet, TScored: discStdSet,
			QNotScored: map[string]string{"f3": "raw_missing: inputs absent"}},
	})
	d := discFetch(t, r)

	// balanced: b must not dominate a — they are in different groups, and both
	// groups are below the minimum size, so no layers/ranking exist at all.
	m := discMode(t, d, "balanced")
	c := discCounts(t, m)
	if c["groups_total"] != 2 || c["groups_valid"] != 0 || c["ranked"] != 0 {
		t.Fatalf("no cross-coverage dominance allowed: %v", c)
	}
	for _, row := range discRows(t, m) {
		if _, ok := row["pareto_layer"]; ok {
			t.Fatalf("no pareto layer may be emitted across coverage groups: %v", row)
		}
	}

	// quality: b's higher raw points order it first as a DISPLAY order only.
	qm := discMode(t, d, "quality")
	if got := discRowIDs(discRows(t, qm)); strings.Join(got, ",") != "b,a" {
		t.Fatalf("quality display order = %v want b,a", got)
	}
	if !strings.Contains(qm["order_note"].(string), "رتبه بنیادی معتبر") {
		t.Fatalf("display order must be disclaimed: %v", qm["order_note"])
	}
	for _, row := range discRows(t, qm) {
		if row["company_id"] == "b" {
			if row["group_valid"].(bool) {
				t.Fatalf("b's small group must not be valid")
			}
			if !strings.Contains(row["reason"].(string), "اطلاعی") {
				t.Fatalf("b's rank must be marked informational: %v", row["reason"])
			}
		}
	}

	// b's Q points stay exactly the artifact value — never renormalized over
	// its smaller coverage, and the missing factor is still listed.
	for _, co := range d["companies"].([]any) {
		cm := co.(map[string]any)
		if cm["company_id"] == "b" {
			q := cm["q"].(map[string]any)
			if q["points"].(float64) != 25 {
				t.Fatalf("b q points must pass through verbatim: %v", q["points"])
			}
			if q["covered_weight"].(float64) == q["max_weight"].(float64) {
				t.Fatalf("b coverage must stay honest (not full): %v", q)
			}
			if len(q["factor_issues"].([]any)) == 0 {
				t.Fatalf("b must list its not-scored factor")
			}
			if sf := q["scored_factors"].([]any); len(sf) != 2 {
				t.Fatalf("b scored factors = %v want 2", sf)
			}
		}
	}

	// no forbidden aggregate/renormalization key anywhere in the payload
	forbidden := []string{"total_score", "qvt_score", "qvt_total", "score_of_100",
		"final_score", "renormalized", "normalized_points", "weighted_total"}
	var hits []string
	qvtWalkStrings(d, func(path, s string) {
		for _, f := range forbidden {
			if strings.Contains(path, f) {
				hits = append(hits, path)
			}
		}
	})
	if len(hits) > 0 {
		t.Fatalf("forbidden aggregate keys in discovery payload: %v", hits)
	}
}

func TestDiscoveryTieBreakDeterministic(t *testing.T) {
	// equal observed points → stable symbol order, byte-identical responses
	fx := []discFixture{
		sameSetFixture("a", "بت", "فولاد", 10, 10, 10),
		sameSetFixture("b", "الف", "فولاد", 10, 10, 10),
		sameSetFixture("c", "پ", "فولاد", 10.5, 10, 10),
	}
	r := discServer(t, fx)
	d1 := discFetch(t, r)
	d2 := discFetch(t, r)
	raw1, _ := json.Marshal(d1["modes"])
	raw2, _ := json.Marshal(d2["modes"])
	if string(raw1) != string(raw2) {
		t.Fatalf("discovery must be deterministic for the same snapshot")
	}
	qm := discMode(t, d1, "quality")
	if got := discRowIDs(discRows(t, qm)); strings.Join(got, ",") != "c,b,a" {
		t.Fatalf("tie must break by symbol: %v", got)
	}
	// direct dominance unit check: equal scores never dominate
	if discDominates(discScores{10, 10, 10}, discScores{10, 10, 10}) {
		t.Fatalf("equal scores must not dominate")
	}
	if !discDominates(discScores{10, 10, 10}, discScores{9, 10, 10}) {
		t.Fatalf("strictly better must dominate")
	}
	if discDominates(discScores{10, 9, 10}, discScores{9, 10, 10}) {
		t.Fatalf("cross-axis trade-off must not dominate")
	}
}

func TestDiscoveryUniverseIsTripleEligible(t *testing.T) {
	r := discServer(t, []discFixture{
		sameSetFixture("a", "الف", "فولاد", 10, 10, 10),
		sameSetFixture("b", "ب", "فولاد", 9, 9, 9),
		sameSetFixture("c", "پ", "فولاد", 8, 8, 8),
		{ID: "vonly", Symbol: "ت", Industry: "فولاد", QPts: 0, VPts: 9, TPts: 9,
			QEl: false, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet},
		{ID: "oos", Symbol: "ث", Industry: "فولاد", QPts: 0, VPts: 9, TPts: 9,
			QEl: false, VEl: true, TEl: true, QScored: discStdSet, VScored: discStdSet, TScored: discStdSet,
			OutOfScope: true},
	})
	d := discFetch(t, r)
	u := d["universe"].(map[string]any)
	if u["n_all_artifacts"].(float64) != 5 || u["n_triple_eligible"].(float64) != 3 {
		t.Fatalf("universe wrong: %v", u)
	}
	if got := len(d["companies"].([]any)); got != 3 {
		t.Fatalf("discovery companies = %d want 3", got)
	}
}

func TestDiscoveryMissingArtifactRefuses(t *testing.T) {
	r := discServer(t, []discFixture{sameSetFixture("a", "الف", "فولاد", 10, 10, 10)})
	dir := os.Getenv("QVT_V2_ARTIFACT_DIR")
	if err := os.Remove(filepath.Join(dir, "v2_t_pilot.json")); err != nil {
		t.Fatal(err)
	}
	w := qvtDo(r, "/api/qvt-v2/discovery")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d want 503", w.Code)
	}
}

func TestDiscoverySnapshotMismatchRefuses(t *testing.T) {
	r := discServer(t, []discFixture{sameSetFixture("a", "الف", "فولاد", 10, 10, 10)})
	raw, err := os.ReadFile(filepath.Join(os.Getenv("QVT_V2_ARTIFACT_DIR"), "v2_t_pilot.json"))
	if err != nil {
		t.Fatal(err)
	}
	bad := strings.Replace(string(raw), qvtTestCut, "2026-10-07T23:59:00+00:00", 1)
	if err := os.WriteFile(filepath.Join(os.Getenv("QVT_V2_ARTIFACT_DIR"), "v2_t_pilot.json"), []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	w := qvtDo(r, "/api/qvt-v2/discovery")
	if w.Code != http.StatusConflict {
		t.Fatalf("status = %d want 409", w.Code)
	}
	if !strings.Contains(qvtDecode(t, w)["error"].(string), "کشف فرصت") {
		t.Fatalf("error must name the discovery refusal")
	}
}
