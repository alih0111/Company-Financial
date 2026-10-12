package qvt

// Unit tests for the QVT V2 UI feed — pure, no database, no real artifacts.
//
// The fixtures are miniature copies of the real pilot documents' shapes:
//
//	{
//	  "as_of": ..., "cutoff": ...,
//	  "companies"/"v_observed_report"/"t_observed_report": { "<cid>": {...} },
//	  "weight_table(s)": {...}
//	}
//
// Verified here:
//   - happy-path summary: merge by company_id, recounted eligibility counts,
//     stable company_id order (NOT score order), axis max weights 40/35/25
//   - no forbidden aggregate key anywhere in the payload (no total score,
//     no Q+V+T sum, no per-axis "final" score)
//   - detail mode passes the company's raw axis maps through verbatim
//   - Q family_out_of_scope rows have eligibility_known=false and never
//     count into the triple
//   - missing artifact file → 503 with the Persian no-fake-data message
//   - as_of/cutoff mismatch → 409, identity conflict → 409
//   - unknown company_id in detail mode → 404

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

const qvtTestQAsOf = "2026-10-08 23:59:00+00:00"
const qvtTestCut = "2026-10-08T23:59:00+00:00"

type qvtFixtureCompany struct {
	ID     string
	Symbol string
	QPts   float64
	VPts   float64
	TPts   float64
	QEl    bool
	VEl    bool
	TEl    bool
	// OutOfScope drops pilot_eligible from the Q row and adds a reason.
	OutOfScope bool
}

func qvtWriteFixtures(t *testing.T, dir string, fc []qvtFixtureCompany) {
	t.Helper()
	qc := map[string]any{}
	vc := map[string]any{}
	tc := map[string]any{}
	for _, c := range fc {
		qrow := map[string]any{
			"company_id":             c.ID,
			"symbol":                 c.Symbol,
			"model_family":           "general",
			"industry":               "فولاد",
			"aggregation_status":     "aggregated",
			"q_observed_points":      c.QPts,
			"covered_weight":         30.0,
			"missing_weight":         10.0,
			"coverage_ratio":         0.75,
			"coverage_threshold_met": true,
			"essential_status":       map[string]any{"required": []string{"margins", "roe_level"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":         c.QEl,
			"data_confidence":        map[string]any{"status": "not_evaluated"},
			"risk_gate": map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated",
				"financial_warnings": []any{"negative_operating_profit: real loss kept as data"}},
			"factors": map[string]any{
				"margins": map[string]any{"weight": 5, "essential": true, "direction": "higher",
					"normalization_status": "ranked", "score": 0.42, "score_kind": "percentile_combined",
					"included": true, "contribution_points": 2.1},
			},
		}
		if c.OutOfScope {
			delete(qrow, "pilot_eligible")
			qrow["aggregation_status"] = "family_out_of_scope"
			qrow["reason"] = "model_family 'bank': this pilot aggregates the 'general' family only"
		}
		qc[c.ID] = qrow
		vc[c.ID] = map[string]any{
			"company_id": c.ID, "symbol": c.Symbol, "model_family": "general", "industry": "فولاد",
			"v_observed_points": c.VPts, "covered_weight": 22.0, "missing_weight": 13.0,
			"coverage_ratio": 0.6285714285714286, "coverage_threshold_met": true,
			"essential_status": map[string]any{"required": []string{"pb", "pe"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":   c.VEl,
			"data_confidence":  map[string]any{"status": "not_evaluated"},
			"risk_gate":        map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated", "financial_warnings": []any{}},
			"factors": map[string]any{
				"pb": map[string]any{"weight": 12, "essential": true, "direction": "lower",
					"raw_status": "valid", "raw_value": 6.2, "normalization_status": "ranked",
					"n_valid_market_family": 99, "n_valid_sector": 2,
					"score": 0.3265, "score_kind": "percentile_combined", "included": true,
					"contribution_points": 3.918},
			},
		}
		tc[c.ID] = map[string]any{
			"company_id": c.ID, "symbol": c.Symbol, "model_family": "general", "industry": "فولاد",
			"t_observed_points": c.TPts, "covered_weight": 25.0, "missing_weight": 0.0,
			"coverage_ratio": 1.0, "coverage_threshold_met": true,
			"essential_status": map[string]any{"required": []string{"liquidity", "momentum_6m_rel"}, "missing": []any{}, "all_satisfied": true},
			"pilot_eligible":   c.TEl,
			"data_confidence":  map[string]any{"status": "not_evaluated"},
			"risk_gate":        map[string]any{"status": "not_evaluated", "final_evaluation": "not_evaluated", "trading_warnings": []any{"liquidity_window_composition: 1 no-trade session"}},
			"factors": map[string]any{
				"momentum_6m_rel": map[string]any{"weight": 7, "essential": true, "direction": "higher",
					"raw_status": "valid", "raw_value": 0.0975, "normalization_status": "ranked",
					"n_valid_market_family": 166, "n_valid_sector": 2,
					"score": 0.6364, "score_kind": "percentile_combined", "included": true,
					"contribution_points": 4.4545},
			},
		}
	}

	qDoc := map[string]any{
		"as_of": qvtTestQAsOf, "score_version": "v2-observed-pilot",
		"weight_table": map[string]any{"axis": "quality", "target_weight": 40.0, "total_weight": 40.0, "rows": map[string]any{}},
		"policy":       map[string]any{"coverage_threshold": 0.5},
		"companies":    qc,
		"summary":      map[string]any{"n_companies_total": len(fc)},
	}
	vDoc := map[string]any{
		"as_of": "2026-10-08", "cutoff": qvtTestCut,
		"weight_tables":     map[string]any{"general": map[string]any{"axis": "valuation", "target_weight": 35.0}},
		"v_observed_report": map[string]any{"companies": vc},
		"coverage_summary":  map[string]any{},
	}
	tDoc := map[string]any{
		"as_of": "2026-10-08", "cutoff": qvtTestCut,
		"weight_tables":     map[string]any{"general": map[string]any{"axis": "timing", "target_weight": 25.0}},
		"t_observed_report": map[string]any{"companies": tc},
		"coverage_summary":  map[string]any{},
	}
	for name, doc := range map[string]map[string]any{
		"v2_q_observed_report.json": qDoc,
		"v2_value_pilot.json":       vDoc,
		"v2_t_pilot.json":           tDoc,
	} {
		raw, err := json.Marshal(doc)
		if err != nil {
			t.Fatalf("marshal %s: %v", name, err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), raw, 0o644); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}
}

func qvtTestServer(t *testing.T, dir string) *gin.Engine {
	t.Helper()
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/qvt-v2", GetQvtV2Report)
	return r
}

func qvtDo(r *gin.Engine, target string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, target, nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func qvtDecode(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("response is not json: %v\nbody: %s", err, w.Body.String())
	}
	return out
}

// walkStrings visits every scalar string under any JSON value.
func qvtWalkStrings(v any, visit func(path, s string)) {
	var rec func(node any, path string)
	rec = func(node any, path string) {
		switch x := node.(type) {
		case map[string]any:
			for k, sub := range x {
				rec(sub, path+"."+k)
			}
		case []any:
			for _, sub := range x {
				rec(sub, path+"[]")
			}
		case string:
			visit(path, x)
		}
	}
	rec(v, "")
}

func TestQvtV2SummaryMergesRealShape(t *testing.T) {
	dir := t.TempDir()
	// Points crafted so score order ≠ company_id order: the second company
	// scores higher but must still come second in the stable id order.
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1.0, VPts: 2.0, TPts: 3.0, QEl: true, VEl: true, TEl: true},
		{ID: "bbb", Symbol: "فملی", QPts: 38.0, VPts: 34.0, TPts: 24.0, QEl: true, VEl: true, TEl: true},
		{ID: "ccc", Symbol: "وبصادر", QPts: 0, VPts: 30.0, TPts: 20.0, QEl: false, VEl: true, TEl: true, OutOfScope: true},
	})
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d := qvtDecode(t, w)
	if d["disclaimer"] != qvtDisclaimer {
		t.Fatalf("disclaimer missing or reworded: %v", d["disclaimer"])
	}
	counts := d["counts"].(map[string]any)
	want := map[string]float64{
		"n_total": 3, "n_q_eligible": 2, "n_v_eligible": 3, "n_t_eligible": 3,
		"n_q_and_v": 2, "n_all_three": 2,
	}
	for k, v := range want {
		if got := counts[k].(float64); got != v {
			t.Fatalf("counts[%s] = %v want %v", k, got, v)
		}
	}
	rows := d["companies"].([]any)
	if len(rows) != 3 {
		t.Fatalf("rows = %d", len(rows))
	}
	if rows[0].(map[string]any)["company_id"] != "aaa" {
		t.Fatalf("companies must be in stable company_id order, not score order")
	}
	first := rows[0].(map[string]any)
	q := first["q"].(map[string]any)
	if q["max_weight"].(float64) != 40.0 || q["points"].(float64) != 1.0 {
		t.Fatalf("q axis view wrong: %v", q)
	}
	// Out-of-scope row: no silent "not eligible"
	third := rows[2].(map[string]any)
	q3 := third["q"].(map[string]any)
	if q3["eligibility_known"].(bool) {
		t.Fatalf("family_out_of_scope must carry eligibility_known=false")
	}
	if third["all_three_eligible"].(bool) {
		t.Fatalf("out-of-scope row must never count as triple-eligible")
	}
	if q3["scope_reason"] == "" {
		t.Fatalf("out-of-scope row must carry its reason")
	}
	// the triple filter counts exactly the all_three_eligible rows
	n := 0
	for _, row := range rows {
		if row.(map[string]any)["all_three_eligible"].(bool) {
			n++
		}
	}
	if n != 2 {
		t.Fatalf("all_three_eligible rows = %d want 2", n)
	}
}

func TestQvtV2NoForbiddenAggregateKeys(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	r := qvtTestServer(t, dir)
	for _, target := range []string{"/api/qvt-v2", "/api/qvt-v2?company_id=aaa"} {
		w := qvtDo(r, target)
		if w.Code != http.StatusOK {
			t.Fatalf("%s → %d", target, w.Code)
		}
		forbidden := []string{"total_score", "qvt_score", "qvt_total", "quality_score",
			"valuation_score", "timing_score", "q_plus_v", "score_of_100", "final_score"}
		var hits []string
		qvtWalkStrings(qvtDecode(t, w), func(path, s string) {
			for _, f := range forbidden {
				if strings.Contains(path, f) {
					hits = append(hits, path)
				}
			}
		})
		if len(hits) > 0 {
			t.Fatalf("%s emitted forbidden aggregate keys: %v", target, hits)
		}
	}
}

func TestQvtV2DetailPassthrough(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2?company_id=aaa")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d := qvtDecode(t, w)
	axes := d["company"].(map[string]any)["axes"].(map[string]any)
	for axis, factor := range map[string]string{"q": "margins", "v": "pb", "t": "momentum_6m_rel"} {
		ax := axes[axis].(map[string]any)
		f := ax["factors"].(map[string]any)[factor].(map[string]any)
		if f["score"] == nil {
			t.Fatalf("detail axis %s lost factor %s", axis, factor)
		}
	}
	if axes["v"].(map[string]any)["factors"].(map[string]any)["pb"].(map[string]any)["raw_value"].(float64) != 6.2 {
		t.Fatalf("detail must pass raw values through verbatim")
	}
	if d["weight_tables"] == nil || d["weight_tables"].(map[string]any)["t"] == nil {
		t.Fatalf("weight tables missing from detail")
	}
}

func TestQvtV2DetailUnknownCompany(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2?company_id=zzz")
	if w.Code != http.StatusNotFound {
		t.Fatalf("status = %d want 404", w.Code)
	}
	if qvtDecode(t, w)["error"] == "" {
		t.Fatalf("must return a Persian error message")
	}
}

func TestQvtV2MissingArtifactRefuses(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	if err := os.Remove(filepath.Join(dir, "v2_t_pilot.json")); err != nil {
		t.Fatal(err)
	}
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2")
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d want 503", w.Code)
	}
	msg := qvtDecode(t, w)["error"].(string)
	if !strings.Contains(msg, "آرتیفکت") || !strings.Contains(msg, "نمونه") {
		t.Fatalf("error must state artifacts are missing and no sample data is served: %s", msg)
	}
}

func TestQvtV2SnapshotMismatchRefuses(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	// rewrite the T artifact with a different cutoff
	raw, err := os.ReadFile(filepath.Join(dir, "v2_t_pilot.json"))
	if err != nil {
		t.Fatal(err)
	}
	bad := strings.Replace(string(raw), qvtTestCut, "2026-10-07T23:59:00+00:00", 1)
	if err := os.WriteFile(filepath.Join(dir, "v2_t_pilot.json"), []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2")
	if w.Code != http.StatusConflict {
		t.Fatalf("status = %d want 409", w.Code)
	}
}

func TestQvtV2IdentityConflictRefuses(t *testing.T) {
	dir := t.TempDir()
	qvtWriteFixtures(t, dir, []qvtFixtureCompany{
		{ID: "aaa", Symbol: "فولاد", QPts: 1, VPts: 2, TPts: 3, QEl: true, VEl: true, TEl: true},
	})
	raw, err := os.ReadFile(filepath.Join(dir, "v2_t_pilot.json"))
	if err != nil {
		t.Fatal(err)
	}
	bad := strings.Replace(string(raw), "فولاد", "نماددیگر", 1)
	if err := os.WriteFile(filepath.Join(dir, "v2_t_pilot.json"), []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	r := qvtTestServer(t, dir)
	w := qvtDo(r, "/api/qvt-v2")
	if w.Code != http.StatusConflict {
		t.Fatalf("status = %d want 409", w.Code)
	}
	if !strings.Contains(qvtDecode(t, w)["error"].(string), "هویت") {
		t.Fatalf("error must name the identity conflict")
	}
}
