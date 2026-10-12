package qvt

// Unit tests for the read-only Data Confidence evaluation (گام ۲-ز-۱).
//
// The seven mission scenarios plus the core safety property:
//   1. structurally complete data with no provable provenance
//   2. inconsistent dates (stale_price) → temporal finding
//   3. suspect/quarantined financial data (magnitude_anomaly, raw_status)
//   4. suspect price jump / price-vs-share-count timing (market warnings)
//   5. missing data (coverage < 1, not-scored factors) → completeness finding
//   6. company with no recorded warnings but insufficient info → honest
//      «بدون یافته ثبت‌شده / ارزیابی‌ناپذیر», never a clean bill of health
//   7. high scores alongside a serious data warning → finding stands,
//      scores are untouched
//   - DC never mutates its inputs and never changes points, coverage,
//     eligibility, grouping or ordering: same scores + different warnings
//     yield byte-identical discovery rows.

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/gin-gonic/gin"
)

type dcFixture struct {
	ID, Symbol  string
	Industry    string // empty → «صنعت آزمون»
	QPts        float64
	VPts        float64
	TPts        float64
	QCov        float64           // Q coverage_ratio; V/T are 1.0
	QScored     []string          // override the default Q scored set
	QMissing    []string          // Q factors with included=false
	QRawStatus  map[string]string // scored Q factor → raw_status override
	FinWarns    []string          // → V.financial_warnings
	TrdWarns    []string          // → T.trading_warnings
	QPitCounts  map[string]any    // → Q.data_confidence.pit_status_counts
	VTPitCounts map[string]any    // → V/T.data_confidence.pit_status_counts (empty map = recorded-clean)
	QHasDC      bool              // include data_confidence in Q
	NoDC        bool              // omit data_confidence everywhere
	NoRiskGate  bool              // omit risk_gate everywhere
	NoCoverage  bool              // omit coverage fields in every axis
}

func dcBuildAxis(fx dcFixture, pointsKey string, points, cov float64, scored []string) map[string]any {
	factors := discFactorSet(scored)
	// Q-scoped knobs only touch the Q axis, mirroring the real artifacts
	isQ := pointsKey == "q_observed_points"
	if isQ {
		for _, id := range fx.QMissing {
			factors[id] = map[string]any{
				"weight": 3, "direction": "higher", "included": false,
				"not_included_reason":  "raw_missing: inputs absent — never a zero",
				"normalization_status": "pending_data",
			}
		}
		for id, rs := range fx.QRawStatus {
			if f, ok := factors[id].(map[string]any); ok {
				f["raw_status"] = rs
			}
		}
	}
	industry := fx.Industry
	if industry == "" {
		industry = "صنعت آزمون"
	}
	row := map[string]any{
		"company_id": fx.ID, "symbol": fx.Symbol, "model_family": "general", "industry": industry,
		pointsKey:        points,
		"covered_weight": cov * 30.0, "missing_weight": (1 - cov) * 30.0,
		"coverage_ratio": cov, "coverage_threshold_met": true,
		"essential_status": map[string]any{"required": []string{"margins"}, "missing": []any{}, "all_satisfied": true},
		"pilot_eligible":   true,
		"factors":          factors,
	}
	if !fx.NoDC {
		dcRow := map[string]any{"status": "not_evaluated"}
		if isQ && fx.QPitCounts != nil {
			dcRow["pit_status_counts"] = fx.QPitCounts
		}
		if !isQ && fx.VTPitCounts != nil {
			dcRow["pit_status_counts"] = fx.VTPitCounts
		}
		if isQ && fx.QHasDC || !isQ {
			row["data_confidence"] = dcRow
		}
	}
	if !fx.NoRiskGate {
		switch {
		case pointsKey == "t_observed_points":
			row["risk_gate"] = map[string]any{"status": "not_evaluated", "trading_warnings": dcWarnStrings(fx.TrdWarns)}
		case pointsKey == "v_observed_points":
			row["risk_gate"] = map[string]any{"status": "not_evaluated", "financial_warnings": dcWarnStrings(fx.FinWarns)}
		default:
			row["risk_gate"] = map[string]any{"status": "not_evaluated", "financial_warnings": []any{}}
		}
	}
	if fx.NoCoverage {
		delete(row, "coverage_ratio")
		delete(row, "covered_weight")
		delete(row, "missing_weight")
	}
	return row
}

func dcWarnStrings(list []string) []any {
	out := make([]any, 0, len(list))
	for _, w := range list {
		out = append(out, w)
	}
	return out
}

func dcFixAxes(fx dcFixture) (q, v, t map[string]any) {
	cov := fx.QCov
	if cov == 0 {
		cov = 1.0
	}
	qScored := []string{"margins", "roe_level", "sales_growth"}
	if len(fx.QScored) > 0 {
		qScored = fx.QScored
	}
	return dcBuildAxis(fx, "q_observed_points", fx.QPts, cov, qScored),
		dcBuildAxis(fx, "v_observed_points", fx.VPts, 1.0, []string{"pe", "pb"}),
		dcBuildAxis(fx, "t_observed_points", fx.TPts, 1.0, []string{"liquidity", "momentum"})
}

func dcDim(t *testing.T, cf discConfidence, key string) dcDimension {
	t.Helper()
	for _, d := range cf.Dimensions {
		if d.Key == key {
			return d
		}
	}
	t.Fatalf("dimension %s missing", key)
	return dcDimension{}
}

func dcWantStatus(t *testing.T, cf discConfidence, key, want string) {
	t.Helper()
	if got := dcDim(t, cf, key).Status; got != want {
		t.Fatalf("dimension %s status = %q, want %q (reasons: %v)", key, got, want, dcDim(t, cf, key).Reasons)
	}
}

// ── the seven mission scenarios ─────────────────────────────────────────────

// 1. structurally complete, but provenance is not provable.
func TestDCCompleteStructureUnprovableProvenance(t *testing.T) {
	fx := dcFixture{ID: "a", Symbol: "الف", QPts: 20, VPts: 15, TPts: 10,
		QHasDC: true, QPitCounts: map[string]any{"unverified_no_publication_date": 6.0}}
	q, v, tc := dcFixAxes(fx)
	cf := discConfidenceFor(q, v, tc)
	dcWantStatus(t, cf, "completeness", dcNoFindings)
	dcWantStatus(t, cf, "provenance", dcFindings)
	prov := dcDim(t, cf, "provenance")
	if !reflect.DeepEqual(prov.Reasons, []string{
		"محور Q: 6 ورودی بدون تاریخ انتشار ثبت شده (unverified_no_publication_date) — قابل اثبات نیست",
		"محور V: شواهد ردیابی منبع (pit_status_counts) در آرتیفکت ثبت نشده — ارزیابی‌ناپذیر",
		"محور T: شواهد ردیابی منبع (pit_status_counts) در آرتیفکت ثبت نشده — ارزیابی‌ناپذیر",
	}) {
		t.Fatalf("provenance reasons = %v", prov.Reasons)
	}
	if cf.Overall != "findings" || len(cf.SeriousWarnings) != 0 {
		t.Fatalf("overall=%s serious=%v — unprovable provenance must be a non-serious finding", cf.Overall, cf.SeriousWarnings)
	}
}

// 2. inconsistent dates → temporal finding, and it is serious.
func TestDCInconsistentDates(t *testing.T) {
	fx := dcFixture{ID: "b", Symbol: "ب", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"stale_price: latest trade is 12 days before as_of (freshness policy 7 days) — the last real trade, marked not hidden"}}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "temporal", dcFindings)
	dcWantStatus(t, cf, "financial", dcNoFindings) // stale_price belongs to temporal, not financial
	if !reflect.DeepEqual(cf.SeriousWarnings, []string{"stale_price"}) {
		t.Fatalf("serious = %v", cf.SeriousWarnings)
	}
}

// 3. suspect financial data: out-of-band magnitude + invalid raw_status on a scored factor.
func TestDCSuspectFinancialData(t *testing.T) {
	fx := dcFixture{ID: "c", Symbol: "پ", QPts: 20, VPts: 15, TPts: 10,
		FinWarns:   []string{"magnitude_anomaly: growth 174551.0% beyond (-2000.0, 2000.0) — kept as real data; winsorization / Risk Gate decide later"},
		QRawStatus: map[string]string{"margins": "imputed_from_letter"}}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "financial", dcFindings)
	fin := dcDim(t, cf, "financial")
	if len(fin.Reasons) != 2 {
		t.Fatalf("financial reasons = %v", fin.Reasons)
	}
	if !reflect.DeepEqual(cf.SeriousWarnings, []string{"magnitude_anomaly"}) {
		t.Fatalf("serious = %v — raw_status issue is a finding, not a published serious kind", cf.SeriousWarnings)
	}
}

//  4. suspect price jump (market) and price/share-count timing (temporal
//     review — بازکالیبراسیون گام ۲-ح-۱: سازگاری تعداد سهام/قیمت دیگر هشدار
//     جدی نیست و به بُعد زمانی منتقل شد).
func TestDCMarketDataIntegrity(t *testing.T) {
	fx := dcFixture{ID: "d", Symbol: "ت", QPts: 20, VPts: 15, TPts: 10,
		TrdWarns: []string{"suspected_unadjusted_gap: 2026-05-24 close moves +22.9% from 2026-02-25 — no continuous TSE session can do this; the adjusted series left a corporate-action adjustment or a data hole unapplied"},
		FinWarns: []string{"share_snapshot_older_than_price: share snapshot dates 3 days before the price trade date and the store carries no corporate-action evidence — capital-change consistency between the two dates is unprovable"}}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "temporal", dcFindings)
	dcWantStatus(t, cf, "market", dcFindings)
	mkt := dcDim(t, cf, "market")
	if len(mkt.Reasons) != 1 {
		t.Fatalf("market reasons = %v — share/price consistency belongs to temporal now", mkt.Reasons)
	}
	want := []string{"suspected_unadjusted_gap"}
	if !reflect.DeepEqual(cf.SeriousWarnings, want) {
		t.Fatalf("serious = %v, want %v — consistency review is not a serious data warning", cf.SeriousWarnings, want)
	}
	// liquidity_window_composition is recorded evidence but not serious
	fx2 := dcFixture{ID: "d2", Symbol: "ث", QPts: 20, VPts: 15, TPts: 10,
		TrdWarns: []string{"liquidity_window_composition: 1 no-trade sessions (zero value) and 0 missing-value sessions inside the window — counted, never fabricated"}}
	cf2 := discConfidenceFor(dcFixAxes(fx2))
	dcWantStatus(t, cf2, "market", dcFindings)
	if len(cf2.SeriousWarnings) != 0 {
		t.Fatalf("liquidity composition must not be serious, got %v", cf2.SeriousWarnings)
	}
	// ریسک اقتصادی و نسبت ارزندگی: یافته اطمینان داده نیستند — به Risk Gate
	fx3 := dcFixture{ID: "d3", Symbol: "ث۳", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{
			"loss_maker: net_profit_ttm is negative — P/E is NOT computed; a loss maker can never read as cheaply valued",
			"pe_above_v1_valid_band: pe 69.6 exceeds the V1 engine's own validity band (>60) — kept valid for winsorization, warned here",
		}}
	cf3 := discConfidenceFor(dcFixAxes(fx3))
	dcWantStatus(t, cf3, "financial", dcNoFindings)
	if len(cf3.SeriousWarnings) != 0 {
		t.Fatalf("economic/valuation warnings are not data-confidence findings, got %v", cf3.SeriousWarnings)
	}
}

// 5. missing data → completeness finding with the exact reasons.
func TestDCMissingData(t *testing.T) {
	fx := dcFixture{ID: "e", Symbol: "ج", QPts: 18, VPts: 15, TPts: 10, QCov: 0.6,
		QMissing: []string{"margin_trend", "roe_stability"}}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "completeness", dcFindings)
	comp := dcDim(t, cf, "completeness")
	if len(comp.Reasons) != 2 ||
		comp.Reasons[0] != "پوشش Q کامل نیست: 18 از 30 وزن (60%)" ||
		comp.Reasons[1] != "فاکتورهای نمره‌نگرفته Q: margin_trend (raw_missing)؛ roe_stability (raw_missing)" {
		t.Fatalf("completeness reasons = %v", comp.Reasons)
	}
}

// 6. no recorded warnings and insufficient info → never a clean verdict.
func TestDCNoWarningsInsufficientInfo(t *testing.T) {
	fx := dcFixture{ID: "f", Symbol: "چ", QPts: 20, VPts: 15, TPts: 10, NoRiskGate: true, NoDC: true}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "temporal", dcNotEvaluable)
	dcWantStatus(t, cf, "market", dcNotEvaluable)
	dcWantStatus(t, cf, "financial", dcNotEvaluable)
	dcWantStatus(t, cf, "provenance", dcNotEvaluable)
	dcWantStatus(t, cf, "completeness", dcNoFindings) // coverage is evaluable and clean
	if cf.Overall != "no_findings_recorded" {
		t.Fatalf("overall = %s", cf.Overall)
	}
	if cf.OverallLabel != "بدون یافته ثبت‌شده (معادل تأیید کامل داده نیست)" {
		t.Fatalf("label = %s", cf.OverallLabel)
	}
	// and when even coverage is unreadable, the whole evaluation is refused
	fx.NoCoverage = true
	cf2 := discConfidenceFor(dcFixAxes(fx))
	if cf2.Overall != "not_evaluable" {
		t.Fatalf("overall = %s, want not_evaluable", cf2.Overall)
	}
}

// 7. high scores next to a serious data warning: the finding stands and the
// scores themselves are untouched.
func TestDCHighScoreSeriousWarning(t *testing.T) {
	fx := dcFixture{ID: "g", Symbol: "ح", QPts: 39, VPts: 34, TPts: 24,
		FinWarns: []string{"magnitude_anomaly: growth 174551.0% beyond (-2000.0, 2000.0) — kept as real data; winsorization / Risk Gate decide later"}}
	q, v, tc := dcFixAxes(fx)
	cf := discConfidenceFor(q, v, tc)
	if cf.Overall != "findings" || !reflect.DeepEqual(cf.SeriousWarnings, []string{"magnitude_anomaly"}) {
		t.Fatalf("overall=%s serious=%v", cf.Overall, cf.SeriousWarnings)
	}
	if q["q_observed_points"] != 39.0 || v["v_observed_points"] != 34.0 || tc["t_observed_points"] != 24.0 {
		t.Fatalf("DC must never touch scores")
	}
}

// ── safety properties ───────────────────────────────────────────────────────

// DC reads metadata only: its inputs are byte-identical before and after.
func TestDCNeverMutatesInputs(t *testing.T) {
	fx := dcFixture{ID: "h", Symbol: "خ", QPts: 20, VPts: 15, TPts: 10, QCov: 0.6,
		QMissing: []string{"margin_trend"},
		FinWarns: []string{"pe_above_v1_valid_band: pe 69.6 exceeds the V1 engine's own validity band (>60) — kept valid for winsorization, warned here"},
		TrdWarns: []string{"suspected_unadjusted_gap: gap"},
		QHasDC:   true, QPitCounts: map[string]any{"unverified_no_publication_date": 3.0}}
	q, v, tc := dcFixAxes(fx)
	before := dcSnapshot(t, q, v, tc)
	_ = discConfidenceFor(q, v, tc)
	after := dcSnapshot(t, q, v, tc)
	if !bytes.Equal(before, after) {
		t.Fatalf("discConfidenceFor mutated its inputs:\nbefore %s\nafter  %s", before, after)
	}
}

func dcSnapshot(t *testing.T, q, v, tcm map[string]any) []byte {
	t.Helper()
	raw, err := json.Marshal([]map[string]any{q, v, tcm})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return raw
}

// Same scores with different warnings: identical discovery rows (order,
// layers, points) — only the confidence block differs. DC never
// manufactures an advantage or a rank.
func TestDCDoesNotChangeDiscoveryRows(t *testing.T) {
	dir := t.TempDir()
	clean := dcFixture{ID: "x1", Symbol: "الف", QPts: 25, VPts: 20, TPts: 15}
	q1, v1, t1 := dcFixAxes(clean)
	warned := dcFixture{ID: "x2", Symbol: "ب", QPts: 25, VPts: 20, TPts: 15,
		QCov: 0.6, QScored: []string{"margins", "roe_level"}, QMissing: []string{"margin_trend"},
		FinWarns: []string{"magnitude_anomaly: growth 174551.0% beyond (-2000.0, 2000.0)"},
		TrdWarns: []string{"suspected_unadjusted_gap: gap"},
		QHasDC:   true, QPitCounts: map[string]any{"unverified_no_publication_date": 2.0}}
	q2, v2, t2 := dcFixAxes(warned)
	discWriteArtifacts(t, dir,
		map[string]any{"x1": q1, "x2": q2},
		map[string]any{"x1": v1, "x2": v2},
		map[string]any{"x1": t1, "x2": t2})
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	w := qvtDo(newGinDiscovery(), "/api/qvt-v2/discovery")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d2 := qvtDecode(t, w)
	d1 := discFetch(t, discServer(t, []discFixture{discFixture{ID: "x1", Symbol: "الف", Industry: "صنعت آزمون", QPts: 25, VPts: 20, TPts: 15, QEl: true, VEl: true, TEl: true}}))

	rows1 := discRows(t, discMode(t, d1, "balanced"))
	rows2 := discRows(t, discMode(t, d2, "balanced"))
	// strip x2 from d2's rows before comparing — identical scores must rank alike
	var kept []map[string]any
	for _, r := range rows2 {
		if r["company_id"] == "x1" {
			kept = append(kept, r)
		}
	}
	if len(kept) != 1 || !reflect.DeepEqual(rows1[0], kept[0]) {
		t.Fatalf("balanced row for identical scores changed when warnings differ:\n%v\n%v", rows1[0], kept[0])
	}
	// points in companies[] are untouched
	comps := d2["companies"].([]any)
	var x1, x2 map[string]any
	for _, c := range comps {
		switch c.(map[string]any)["company_id"] {
		case "x1":
			x1 = c.(map[string]any)
		case "x2":
			x2 = c.(map[string]any)
		}
	}
	if x1["q"].(map[string]any)["points"] != 25.0 || x2["q"].(map[string]any)["points"] != 25.0 {
		t.Fatalf("points must be identical regardless of warnings")
	}
	cf1, cf2 := x1["confidence"].(map[string]any), x2["confidence"].(map[string]any)
	if cf1 == nil || cf2 == nil {
		t.Fatalf("confidence block missing from companies[]")
	}
	if cf1["overall"] != "no_findings_recorded" {
		t.Fatalf("clean company overall = %v", cf1["overall"])
	}
	if cf2["overall"] != "findings" || len(cf2["serious_warnings"].([]any)) == 0 {
		t.Fatalf("warned company overall = %v serious = %v", cf2["overall"], cf2["serious_warnings"])
	}
	if _, ok := d2["confidence_rules"]; !ok {
		t.Fatalf("confidence_rules missing from discovery response")
	}
}

// Unknown warning kinds are kept, conservatively serious, never dropped.
func TestDCUnknownWarningKind(t *testing.T) {
	fx := dcFixture{ID: "u", Symbol: "د", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"brand_new_unmapped_warning: something the classifier has never seen"},
		TrdWarns: []string{"brand_new_trading_warning: also unknown"}}
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "financial", dcFindings)
	dcWantStatus(t, cf, "market", dcFindings)
	want := []string{"brand_new_trading_warning", "brand_new_unmapped_warning"}
	if !reflect.DeepEqual(cf.SeriousWarnings, want) {
		t.Fatalf("serious = %v, want %v", cf.SeriousWarnings, want)
	}
	fin := dcDim(t, cf, "financial")
	if len(fin.Reasons) != 1 || !bytes.HasPrefix([]byte(fin.Reasons[0]), []byte("[V] ")) {
		t.Fatalf("financial reasons = %v", fin.Reasons)
	}
}

// Discovery payload always carries five dimensions with valid statuses and
// a null-free confidence block; detail carries it too.
func TestDCPayloadShapeAndDetail(t *testing.T) {
	dir := t.TempDir()
	fx := dcFixture{ID: "aaa", Symbol: "الف", QPts: 20, VPts: 15, TPts: 10, QHasDC: true,
		QPitCounts: map[string]any{"unverified_no_publication_date": 4.0}}
	q, v, tc := dcFixAxes(fx)
	discWriteArtifacts(t, dir, map[string]any{"aaa": q}, map[string]any{"aaa": v}, map[string]any{"aaa": tc})
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	gin2 := newGinDiscovery()
	w := qvtDo(gin2, "/api/qvt-v2/discovery")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d := qvtDecode(t, w)
	comps := d["companies"].([]any)
	c0 := comps[0].(map[string]any)["confidence"].(map[string]any)
	dims := c0["dimensions"].([]any)
	if len(dims) != 5 {
		t.Fatalf("want 5 dimensions, got %d", len(dims))
	}
	valid := map[string]bool{"findings": true, "no_findings": true, "not_evaluable": true}
	var keys []string
	for _, dv := range dims {
		dm := dv.(map[string]any)
		if !valid[dm["status"].(string)] {
			t.Fatalf("invalid status %v", dm["status"])
		}
		if dm["reasons"] == nil || dm["sources"] == nil || dm["title"] == nil {
			t.Fatalf("null field in dimension %v", dm["key"])
		}
		keys = append(keys, dm["key"].(string))
	}
	want := []string{"completeness", "temporal", "provenance", "financial", "market"}
	if !reflect.DeepEqual(keys, want) {
		t.Fatalf("dimension order = %v", keys)
	}
	counts := c0["dimension_counts"].(map[string]any)
	var sum float64
	for _, v := range counts {
		sum += v.(float64)
	}
	if sum != 5 {
		t.Fatalf("dimension_counts must sum to 5: %v", counts)
	}
	if c0["serious_warnings"] == nil || c0["serious_note"] == nil || c0["overall_label"] == nil {
		t.Fatalf("null field in confidence block: %v", c0)
	}

	// detail endpoint
	srv := qvtTestServer(t, dir)
	w2 := qvtDo(srv, "/api/qvt-v2?company_id=aaa")
	if w2.Code != http.StatusOK {
		t.Fatalf("detail status = %d", w2.Code)
	}
	det := qvtDecode(t, w2)
	if det["confidence"] == nil || det["confidence_rules"] == nil {
		t.Fatalf("detail must carry confidence + confidence_rules")
	}
	detDims := det["confidence"].(map[string]any)["dimensions"].([]any)
	if len(detDims) != 5 {
		t.Fatalf("detail dimensions = %d", len(detDims))
	}
}

// ── fixture plumbing ────────────────────────────────────────────────────────

func discWriteArtifacts(t *testing.T, dir string, qs, vs, ts map[string]any) {
	t.Helper()
	docs := map[string]map[string]any{
		"v2_q_observed_report.json": {
			"as_of": qvtTestQAsOf, "score_version": "v2-observed-pilot",
			"weight_table": map[string]any{"axis": "quality", "target_weight": 40.0},
			"policy":       map[string]any{"coverage_threshold": 0.5},
			"companies":    qs,
		},
		"v2_value_pilot.json": {
			"as_of": "2026-10-08", "cutoff": qvtTestCut,
			"v_observed_report": map[string]any{"companies": vs},
		},
		"v2_t_pilot.json": {
			"as_of": "2026-10-08", "cutoff": qvtTestCut,
			"t_observed_report": map[string]any{"companies": ts},
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

func newGinDiscovery() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/qvt-v2/discovery", GetQvtV2Discovery)
	return r
}
