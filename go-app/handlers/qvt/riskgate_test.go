package qvt

// Unit tests for the independent read-only Risk Gate (گام ۲-ح-۱، B1 اصلاح‌شده
// در گام ۲-ط-۱).
//
// The mission-mandated validation cases:
//   1. share-count/price timing warning alone must NOT block
//   2. a very high valuation ratio alone is NOT a data error
//   3. a truly proven blocker CAN produce the blocking status — B1 now ONLY
//      via the independent price source (pricecheck.go), never from re-reading
//      the warning text; B2 invalid raw on a scored factor
//   4. missing data is never confused with healthy data → insufficient_evidence
//   5. fundamental (economic) risk is separated from data errors
//   6. Risk Gate never changes any Q/V/T score — inputs byte-identical, and
//      the discovery payload is unchanged apart from the added gate block
//   7. real-artifact agreement is checked by the independent python oracle
//      (verification step, outside this suite)
//   8. browser run happens after the build (outside this suite)
//   + unknown warnings are kept without an error claim; file-level
//     as_of/cutoff consistency never becomes a per-company finding; a
//     no-warnings company is insufficient_evidence, never «تأییدشده»;
//     the price verdict degrades honestly when the source is unavailable.

import (
	"bytes"
	"net/http"
	"reflect"
	"strings"
	"testing"
)

// rgFor بدون شناسه/حکم قیمت — برای تست‌هایی که هشدار stale_price ندارند.
func rgFor(q, v, t map[string]any) riskGateEval {
	return riskGateFor("", q, v, t, nil)
}

func rgArea(t *testing.T, rg riskGateEval, key string) riskArea {
	t.Helper()
	for _, a := range rg.Areas {
		if a.Key == key {
			return a
		}
	}
	t.Fatalf("area %s missing", key)
	return riskArea{}
}

func rgWantStatus(t *testing.T, rg riskGateEval, areaKey, want string) {
	t.Helper()
	a := rgArea(t, rg, areaKey)
	if a.Status != want {
		t.Fatalf("area %s status = %q, want %q (findings: %+v gaps: %v)", areaKey, a.Status, want, a.Findings, a.EvidenceGaps)
	}
}

// 1. تعداد سهام قدیمی‌تر از قیمت، بدون اثبات اقدام شرکتی، هرگز blocked نمی‌سازد.
func TestRGShareSnapshotNeverBlocks(t *testing.T) {
	fx := dcFixture{ID: "a", Symbol: "الف", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"share_snapshot_older_than_price: share snapshot dates 3 days before the price trade date and the store carries no corporate-action evidence — capital-change consistency between the two dates is unprovable"}}
	rg := rgFor(dcFixAxes(fx))
	if rg.Status == rgBlocked || len(rg.Blockers) != 0 {
		t.Fatalf("share/price consistency alone must never block: status=%s blockers=%+v", rg.Status, rg.Blockers)
	}
	if rg.Status != rgReview {
		t.Fatalf("status = %s, want review_required", rg.Status)
	}
	data := rgArea(t, rg, areaData)
	if len(data.Findings) != 1 {
		t.Fatalf("data findings = %+v", data.Findings)
	}
	f := data.Findings[0]
	if f.Severity != sevConsistency || f.BlockingRule != "" || f.Category != "سازگاری تعداد سهام با قیمت" {
		t.Fatalf("finding = %+v — must be a consistency review, not a proven error", f)
	}
	if !strings.Contains(f.SeverityLabel, "خطای قطعی داده نیست") {
		t.Fatalf("severity label must deny proven error: %q", f.SeverityLabel)
	}
}

// 2. نسبت ارزندگی بسیار بالا به‌تنهایی خطای داده نیست — حوزه بنیادی/ارزندگی.
func TestRGValuationBandNotDataError(t *testing.T) {
	fx := dcFixture{ID: "b", Symbol: "ب", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"pe_above_v1_valid_band: pe 69.6 exceeds the V1 engine's own validity band (>60) — kept valid for winsorization, warned here"}}
	q, v, tc := dcFixAxes(fx)
	rg := rgFor(q, v, tc)
	rgWantStatus(t, rg, areaFundamental, rgReview)
	fnd := rgArea(t, rg, areaFundamental).Findings
	if len(fnd) != 1 || fnd[0].Severity != sevValuationBand || fnd[0].Area != areaFundamental {
		t.Fatalf("fundamental findings = %+v", fnd)
	}
	if fnd[0].Category != "نسبت P/E خارج از بازه مرجع" {
		t.Fatalf("category = %q", fnd[0].Category)
	}
	// حوزه داده از این هشدار هیچ یافته‌ای نمی‌گیرد — فقط شکاف شواهد
	data := rgArea(t, rg, areaData)
	for _, f := range data.Findings {
		if f.Kind == "pe_above_v1_valid_band" {
			t.Fatalf("valuation band leaked into the data area: %+v", f)
		}
	}
	rgWantStatus(t, rg, areaData, rgInsuff)
	if rg.Status != rgReview || len(rg.Blockers) != 0 {
		t.Fatalf("status=%s blockers=%d", rg.Status, len(rg.Blockers))
	}
	// و در Data Confidence هم یافته یکپارچگی مالی نیست
	cf := discConfidenceFor(q, v, tc)
	dcWantStatus(t, cf, "financial", dcNoFindings)
}

// 3. مانع واقعاً اثبات‌شده، وضعیت محدودسازی درست می‌سازد — و B1 فقط از
// کنترل مستقل منبع قیمت می‌آید، هرگز از بازخوانی متن هشدار.
func TestRGProvenErrorBlocks(t *testing.T) {
	staleFx := dcFixture{ID: "c", Symbol: "پ", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"stale_price: latest trade is 12 days before as_of (freshness policy 7 days) — the last real trade, marked not hidden"}}
	qc, vc, tcm := dcFixAxes(staleFx)
	pol7 := 7
	// (الف) متن قابل بازخوانی اما بدون کنترل مستقل: فقط «مشکوک» + شکاف شواهد
	rg0 := riskGateFor("c", qc, vc, tcm, nil)
	if rg0.Status == rgBlocked || len(rg0.Blockers) != 0 {
		t.Fatalf("text parsing alone must never block: status=%s blockers=%+v", rg0.Status, rg0.Blockers)
	}
	rgWantStatus(t, rg0, areaData, rgReview)
	foundGap := false
	for _, g := range rg0.EvidenceGaps {
		if strings.Contains(g, "B1") {
			foundGap = true
		}
	}
	if !foundGap {
		t.Fatalf("missing independent verification must be listed as an evidence gap: %v", rg0.EvidenceGaps)
	}
	// (ب) کنترل مستقل منبع، نقض سیاست را اثبات می‌کند → blocked با قاعده B1
	age12 := 12
	viol := true
	rg := riskGateFor("c", qc, vc, tcm, map[string]*priceCheck{"c": {
		Requested: true, Available: true, RowFound: true,
		Note: "آخرین قیمت ۱۲ روز قبل از as_of است", Source: priceCheckSource,
		CompanyID: "c", SecurityID: "sec-1", LastTradeDate: "2026-09-26",
		CollectedAt: "2026-09-26T12:00:00+00:00", AsOfDate: "2026-10-08",
		AgeDays: &age12, PolicyDays: &pol7, PolicyBasis: priceCheckBasis,
		WindowRule: priceCheckWindow, Violation: &viol,
	}})
	if rg.Status != rgBlocked {
		t.Fatalf("independently verified policy violation must block, status = %s", rg.Status)
	}
	rgWantStatus(t, rg, areaData, rgBlocked)
	if len(rg.Blockers) != 1 || rg.Blockers[0].BlockingRule != ruleB1 {
		t.Fatalf("blockers = %+v", rg.Blockers)
	}
	if rg.Blockers[0].Severity != sevProvenPolicy {
		t.Fatalf("B1 severity must be proven_policy_violation (separate from data error), got %s", rg.Blockers[0].Severity)
	}
	joined := strings.Join(rg.Blockers[0].Evidence, " | ")
	for _, want := range []string{"market.price_observations", "sec-1", "2026-09-26", "12", "7"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("blocker evidence must carry the independent source row: missing %q in %q", want, joined)
		}
	}
	// (ج) کنترل مستقل، نقض را بازتولید نمی‌کند → هشدار حفظ می‌شود اما مانع نیست
	age3 := 3
	noViol := false
	rgC := riskGateFor("c", qc, vc, tcm, map[string]*priceCheck{"c": {
		Requested: true, Available: true, RowFound: true,
		Note: "آخرین قیمت ۳ روز قبل از as_of است", Source: priceCheckSource,
		CompanyID: "c", SecurityID: "sec-1", LastTradeDate: "2026-10-05",
		AgeDays: &age3, PolicyDays: &pol7, Violation: &noViol,
	}})
	if rgC.Status == rgBlocked || len(rgC.Blockers) != 0 {
		t.Fatalf("contradicted staleness must not block: status=%s blockers=%+v", rgC.Status, rgC.Blockers)
	}
	rgWantStatus(t, rgC, areaData, rgReview)
	if !strings.Contains(strings.Join(rgCAreaDataEvidence(rgC), " | "), "بازتولید نشد") {
		t.Fatalf("contradiction must be recorded in evidence: %+v", rgCAreaDataEvidence(rgC))
	}
	// (د) منبع در دسترس نیست → هشدار مشکوک + شکاف، هرگز blocked
	rgD := riskGateFor("c", qc, vc, tcm, map[string]*priceCheck{"c": {
		Requested: true, Available: false, RowFound: false,
		Note: "کنترل ممکن نشد: canonical DSN تنظیم نشده", CompanyID: "c",
		PolicyDays: &pol7, AsOfDate: "2026-10-08",
	}})
	if rgD.Status == rgBlocked || len(rgD.Blockers) != 0 {
		t.Fatalf("unavailable price source must never block: status=%s blockers=%+v", rgD.Status, rgD.Blockers)
	}
	rgWantStatus(t, rgD, areaData, rgReview)
	// (هـ) بدون متن قابل بازخوانی اما با حکم مستقل منبع → باز هم اثبات از منبع می‌آید
	fx2 := dcFixture{ID: "c2", Symbol: "پ۲", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"stale_price: freshness problem recorded without parseable dates"}}
	q2, v2, t2 := dcFixAxes(fx2)
	rg2 := riskGateFor("c2", q2, v2, t2, map[string]*priceCheck{"c2": {
		Requested: true, Available: true, RowFound: true, Source: priceCheckSource,
		CompanyID: "c2", SecurityID: "sec-2", LastTradeDate: "2026-09-20",
		AgeDays: &age12, PolicyDays: &pol7, Violation: &viol,
	}})
	if rg2.Status != rgBlocked || len(rg2.Blockers) != 1 || rg2.Blockers[0].BlockingRule != ruleB1 {
		t.Fatalf("DB-verified violation must block even without parseable text: status=%s blockers=%+v", rg2.Status, rg2.Blockers)
	}
	// (و) B2: فاکتور امتیازگرفته با raw_status نامعتبر — داده اثبات‌شده بد در امتیاز
	fx3 := dcFixture{ID: "c3", Symbol: "پ۳", QPts: 20, VPts: 15, TPts: 10,
		QRawStatus: map[string]string{"margins": "invalid"}}
	q3, v3, t3 := dcFixAxes(fx3)
	rg3 := riskGateFor("c3", q3, v3, t3, nil)
	if rg3.Status != rgBlocked {
		t.Fatalf("B2 must block, status = %s", rg3.Status)
	}
	b2Found := false
	for _, b := range rg3.Blockers {
		if b.BlockingRule == ruleB2 {
			b2Found = true
		}
	}
	if !b2Found {
		t.Fatalf("B2 blocker missing: %+v", rg3.Blockers)
	}
}

// rgCAreaDataEvidence یافته‌های حوزه داده را برای بررسی متن شواهد برمی‌گرداند.
func rgCAreaDataEvidence(rg riskGateEval) []string {
	for _, a := range rg.Areas {
		if a.Key == areaData {
			var out []string
			for _, f := range a.Findings {
				out = append(out, f.Evidence...)
			}
			return out
		}
	}
	return nil
}

// 4. داده مفقود با داده سالم اشتباه گرفته نمی‌شود.
func TestRGMissingDataNotHealthy(t *testing.T) {
	fx := dcFixture{ID: "e", Symbol: "ج", QPts: 18, VPts: 15, TPts: 10, QCov: 0.6,
		QMissing: []string{"margin_trend"}} // بدون هیچ هشدار ثبت‌شده
	rg := rgFor(dcFixAxes(fx))
	if rg.Status != rgInsuff {
		t.Fatalf("no-warnings company with missing data must be insufficient_evidence, got %s — missing data must not read as healthy", rg.Status)
	}
	rgWantStatus(t, rg, areaData, rgInsuff)
	rgWantStatus(t, rg, areaFundamental, rgClear)
	rgWantStatus(t, rg, areaMarket, rgClear)
	if len(rg.EvidenceGaps) == 0 {
		t.Fatalf("evidence gaps must be listed, not hidden")
	}
	// Data Confidence هم در همان داده، یافته کامل‌بودن دارد
	cf := discConfidenceFor(dcFixAxes(fx))
	dcWantStatus(t, cf, "completeness", dcFindings)
}

// 5. ریسک بنیادی (اقتصادی) از خطای داده تفکیک می‌شود و مسدودکننده نیست.
func TestRGFundamentalSeparatedFromData(t *testing.T) {
	fx := dcFixture{ID: "f", Symbol: "چ", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"loss_maker: net_profit_ttm is negative — P/E is NOT computed; a loss maker can never read as cheaply valued"},
		TrdWarns: []string{"turned_to_loss: positive prior-year base turned into a loss — the negative percent is the standard-formula change, not a desirable growth outcome; loss state recorded independently"}}
	q, v, tc := dcFixAxes(fx)
	rg := rgFor(q, v, tc)
	rgWantStatus(t, rg, areaFundamental, rgReview)
	fnd := rgArea(t, rg, areaFundamental).Findings
	if len(fnd) != 2 {
		t.Fatalf("fundamental findings = %+v", fnd)
	}
	for _, f := range fnd {
		if f.Severity != sevEconomic || f.Area != areaFundamental {
			t.Fatalf("finding = %+v", f)
		}
	}
	// حوزه داده هیچ یافته‌ای از این‌ها نمی‌گیرد
	for _, f := range rgArea(t, rg, areaData).Findings {
		if f.Kind == "loss_maker" || f.Kind == "turned_to_loss" {
			t.Fatalf("economic risk leaked into the data area: %+v", f)
		}
	}
	// ریسک اقتصادی واقعی الزاماً مسدودکننده نیست
	if rg.Status == rgBlocked || len(rg.Blockers) != 0 {
		t.Fatalf("economic risk must not block: status=%s blockers=%+v", rg.Status, rg.Blockers)
	}
	// و در Data Confidence یافته یکپارچگی مالی نیست
	cf := discConfidenceFor(q, v, tc)
	dcWantStatus(t, cf, "financial", dcNoFindings)
}

// 6. Risk Gate هیچ امتیاز Q/V/T را تغییر نمی‌دهد — ورودی‌ها بایت‌به‌بایت.
func TestRGNeverMutatesInputsOrScores(t *testing.T) {
	fx := dcFixture{ID: "h", Symbol: "خ", QPts: 20, VPts: 15, TPts: 10, QCov: 0.6,
		QMissing: []string{"margin_trend"},
		FinWarns: []string{"magnitude_anomaly: growth 174551.0% beyond (-2000.0, 2000.0)"},
		TrdWarns: []string{"suspected_unadjusted_gap: gap"},
		QHasDC:   true, QPitCounts: map[string]any{"unverified_no_publication_date": 3.0}}
	q, v, tc := dcFixAxes(fx)
	before := dcSnapshot(t, q, v, tc)
	_ = rgFor(q, v, tc)
	after := dcSnapshot(t, q, v, tc)
	if !bytes.Equal(before, after) {
		t.Fatalf("riskGateFor mutated its inputs:\nbefore %s\nafter  %s", before, after)
	}
	if q["q_observed_points"] != 20.0 || v["v_observed_points"] != 15.0 || tc["t_observed_points"] != 10.0 {
		t.Fatalf("scores must be untouched")
	}
}

// 6b. پاسخ discovery با Risk Gate هم برای شرکت‌های هم‌امتیاز یکسان می‌ماند و
// بلوک دروازه ریسک/قرارداد/سازگاری snapshot را حمل می‌کند.
func TestRGDiscoveryPayloadNeutrality(t *testing.T) {
	dir := t.TempDir()
	clean := dcFixture{ID: "x1", Symbol: "الف", QPts: 25, VPts: 20, TPts: 15}
	warned := dcFixture{ID: "x2", Symbol: "ب", QPts: 25, VPts: 20, TPts: 15,
		QCov: 0.6, QScored: []string{"margins", "roe_level"}, QMissing: []string{"margin_trend"},
		FinWarns: []string{"magnitude_anomaly: growth 174551.0% beyond (-2000.0, 2000.0)"},
		TrdWarns: []string{"suspected_unadjusted_gap: gap"},
		QHasDC:   true, QPitCounts: map[string]any{"unverified_no_publication_date": 2.0}}
	q1, v1, t1 := dcFixAxes(clean)
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
	d := qvtDecode(t, w)
	if _, ok := d["risk_gate_rules"]; !ok {
		t.Fatalf("risk_gate_rules missing from discovery response")
	}
	sc, ok := d["snapshot_consistency"].(map[string]any)
	if !ok || sc["consistent"] != true {
		t.Fatalf("snapshot_consistency missing/inconsistent: %v", d["snapshot_consistency"])
	}
	files := sc["files"].(map[string]any)
	if files["q"].(map[string]any)["sha256"] == "" || files["v"].(map[string]any)["cutoff"] == "" {
		t.Fatalf("snapshot files must carry sha256/as_of/cutoff: %v", files)
	}

	var x1, x2 map[string]any
	for _, c := range d["companies"].([]any) {
		switch c.(map[string]any)["company_id"] {
		case "x1":
			x1 = c.(map[string]any)
		case "x2":
			x2 = c.(map[string]any)
		}
	}
	if x1 == nil || x2 == nil {
		t.Fatalf("companies missing")
	}
	// امتیازها مستقل از هشدارها
	if x1["q"].(map[string]any)["points"] != 25.0 || x2["q"].(map[string]any)["points"] != 25.0 {
		t.Fatalf("points must be identical regardless of warnings")
	}
	// بلوک دروازه ریسک با شکل درست و بدون null
	valid := map[string]bool{rgBlocked: true, rgReview: true, rgInsuff: true, rgClear: true}
	for cid, c := range map[string]map[string]any{"x1": x1, "x2": x2} {
		rg := c["risk_gate"].(map[string]any)
		if !valid[rg["status"].(string)] {
			t.Fatalf("%s: invalid gate status %v", cid, rg["status"])
		}
		if len(rg["areas"].([]any)) != 3 {
			t.Fatalf("%s: want 3 areas", cid)
		}
		for _, k := range []string{"blockers", "review_findings", "evidence_gaps", "warning_kinds"} {
			if rg[k] == nil {
				t.Fatalf("%s: %s is null", cid, k)
			}
		}
	}
	if x1["risk_gate"].(map[string]any)["status"] != rgInsuff {
		t.Fatalf("clean company with missing provenance must be insufficient_evidence, got %v", x1["risk_gate"].(map[string]any)["status"])
	}
	if x2["risk_gate"].(map[string]any)["status"] != rgReview {
		t.Fatalf("warned company must be review_required, got %v", x2["risk_gate"].(map[string]any)["status"])
	}
	// فهرست کوتاه در پاسخ هست؛ با دو شرکت در دو گروه تک‌نفره (گروه نامعتبر)
	// خالی می‌ماند و شمارش non_ranked صادقانه گزارش می‌شود
	sl, ok := d["shortlist"].(map[string]any)
	if !ok {
		t.Fatalf("shortlist missing from discovery response")
	}
	if n := len(sl["groups"].([]any)); n != 0 {
		t.Fatalf("no valid group exists in this fixture, shortlist groups = %d", n)
	}
	if sl["counts"].(map[string]any)["companies"].(float64) != 0 {
		t.Fatalf("shortlist companies must be 0 here, got %v", sl["counts"])
	}
	if sl["non_ranked"].(map[string]any)["n"].(float64) != 2 {
		t.Fatalf("non_ranked must count both small-group companies, got %v", sl["non_ranked"])
	}
	if _, ok := d["price_source"].(map[string]any); !ok {
		t.Fatalf("price_source meta missing")
	}
}

// فهرست کوتاه (گام ۲-ط-۱): فقط گروه‌های مقایسه‌پذیر معتبر وارد فهرست
// می‌شوند؛ اعضای لایه ۱ پارتو ابتدا؛ گروه کوچک حذف می‌شود اما صادقانه
// شمرده می‌شود؛ هر ورودی دلیل لایه و کنترل قیمت (اینجا: منبع در دسترس
// نیست → تخریب محترمانه) دارد.
func TestShortlistGroupingAndOrdering(t *testing.T) {
	dir := t.TempDir()
	mk := func(id, sym, ind string, q, v, tt float64) dcFixture {
		return dcFixture{ID: id, Symbol: sym, Industry: ind, QPts: q, VPts: v, TPts: tt}
	}
	// گروه سیمان با ۵ عضو (لایه‌های پارتو ۱ تا ۴) + گروه شیمیایی با ۲ عضو
	fixtures := []dcFixture{
		mk("s1", "س۱", "سیمان", 30, 20, 15), // L1 — غالب بر همه
		mk("s2", "س۲", "سیمان", 28, 22, 14), // L1 — بهتر در V
		mk("s3", "س۳", "سیمان", 10, 5, 3),   // تحت غالب همه → آخرین لایه
		mk("s4", "س۴", "سیمان", 20, 10, 8),  // L3
		mk("s5", "س۵", "سیمان", 25, 15, 12), // L2
		mk("k1", "ک۱", "شیمیایی", 20, 20, 20),
		mk("k2", "ک۲", "شیمیایی", 15, 15, 15),
	}
	qs, vs, ts := map[string]any{}, map[string]any{}, map[string]any{}
	for _, fx := range fixtures {
		q, v, tt := dcFixAxes(fx)
		qs[fx.ID], vs[fx.ID], ts[fx.ID] = q, v, tt
	}
	discWriteArtifacts(t, dir, qs, vs, ts)
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	w := qvtDo(newGinDiscovery(), "/api/qvt-v2/discovery")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d := qvtDecode(t, w)
	sl := d["shortlist"].(map[string]any)
	groups := sl["groups"].([]any)
	if len(groups) != 1 {
		t.Fatalf("only the 5-member cement group is valid, groups = %d", len(groups))
	}
	g := groups[0].(map[string]any)
	if g["group_label"].(string) != "صنعت «سیمان» / خانواده general" {
		t.Fatalf("group label = %q — must come from real industry data", g["group_label"])
	}
	entries := g["entries"].([]any)
	if len(entries) != 5 {
		t.Fatalf("cement entries = %d, want 5", len(entries))
	}
	// ترتیب: لایه صعودی — s1, s2 (لایه ۱)، s5 (لایه ۲)، s4 (لایه ۳)، s3 (لایه ۴)
	wantOrder := []string{"s1", "s2", "s5", "s4", "s3"}
	wantLayer := map[string]float64{"s1": 1, "s2": 1, "s5": 2, "s4": 3, "s3": 4}
	for i, want := range wantOrder {
		e := entries[i].(map[string]any)
		if e["company_id"].(string) != want {
			t.Fatalf("entry %d = %s, want %s (pareto order broken)", i, e["company_id"], want)
		}
		if e["pareto_layer"].(float64) != wantLayer[want] {
			t.Fatalf("%s pareto_layer = %v, want %v", want, e["pareto_layer"], wantLayer[want])
		}
		if e["price_freshness"] == nil {
			t.Fatalf("entry %s must carry price_freshness (honest unavailable here)", e["company_id"])
		}
		if e["reason"].(string) == "" || e["group_size"].(float64) != 5 {
			t.Fatalf("entry %s must carry layer reason and group size", e["company_id"])
		}
	}
	if first := entries[0].(map[string]any); first["pareto_layer"].(float64) != 1 {
		t.Fatalf("first entry must be pareto layer 1")
	}
	if sl["counts"].(map[string]any)["companies"].(float64) != 5 {
		t.Fatalf("shortlist companies = %v, want 5", sl["counts"])
	}
	if sl["non_ranked"].(map[string]any)["n"].(float64) != 2 {
		t.Fatalf("non_ranked = %v, want 2 (the two-member chemical group)", sl["non_ranked"])
	}
	// شرکت‌های گروه کوچک در companies کامل می‌مانند — مسیر مشاهده مستقل حفظ است
	if len(d["companies"].([]any)) != 7 {
		t.Fatalf("companies list must stay complete: %d", len(d["companies"].([]any)))
	}
}

// هشدار ناشناخته حذف نمی‌شود و بدون ادعای خطا نمایش داده می‌شود.
func TestRGUnknownWarningKeptNoErrorClaim(t *testing.T) {
	fx := dcFixture{ID: "u", Symbol: "د", QPts: 20, VPts: 15, TPts: 10,
		FinWarns: []string{"brand_new_unmapped_warning: something the classifier has never seen"},
		TrdWarns: []string{"brand_new_trading_warning: also unknown"}}
	rg := rgFor(dcFixAxes(fx))
	want := []string{"brand_new_trading_warning", "brand_new_unmapped_warning"}
	if !reflect.DeepEqual(rg.WarningKinds, want) {
		t.Fatalf("warning_kinds = %v, want %v", rg.WarningKinds, want)
	}
	if len(rg.ReviewFindings) != 2 {
		t.Fatalf("review findings = %+v", rg.ReviewFindings)
	}
	for _, f := range rg.ReviewFindings {
		if f.Severity != sevUnknown || f.GateEffect != effectReview {
			t.Fatalf("unknown warning must stay unknown/review: %+v", f)
		}
		if strings.Contains(f.SeverityLabel, "خطای اثبات‌شده") {
			t.Fatalf("unknown warning must carry no proven-error claim: %q", f.SeverityLabel)
		}
	}
	if rg.Status != rgReview {
		t.Fatalf("status = %s, want review_required", rg.Status)
	}
}

// سازگاری as_of/cutoff سه فایل سطح snapshot است — به حساب شرکت نوشته نمی‌شود؛
// و شرکتی با شواهد ناکافی هرگز «تأییدشده» معرفی نمی‌شود.
func TestRGSnapshotConsistencySeparateAndNoFalseClean(t *testing.T) {
	fx := dcFixture{ID: "s", Symbol: "س", QPts: 20, VPts: 15, TPts: 10, NoRiskGate: true}
	rg := rgFor(dcFixAxes(fx))
	for _, f := range rgArea(t, rg, areaData).Findings {
		if strings.Contains(f.Category, "snapshot") || strings.Contains(f.Kind, "as_of") {
			t.Fatalf("file-level as_of/cutoff became a company finding: %+v", f)
		}
	}
	// فهرست هشدار ثبت نشده → اسکن ناتمام → شواهد ناکافی، نه «بدون مانع»
	rgWantStatus(t, rg, areaData, rgInsuff)
	rgWantStatus(t, rg, areaMarket, rgInsuff)
	if rg.Status != rgInsuff {
		t.Fatalf("status = %s, want insufficient_evidence", rg.Status)
	}
	if rg.Status == rgClear {
		t.Fatalf("insufficient-evidence company must never be presented as cleared")
	}
	// و شرکتی که همه بررسی‌هاش ممکن و بدون یافته بوده هم با قید ≠ تأیید سرو می‌شود
	fx2 := dcFixture{ID: "s2", Symbol: "س۲", QPts: 20, VPts: 15, TPts: 10,
		QHasDC: true, QPitCounts: map[string]any{}, VTPitCounts: map[string]any{}}
	rg2 := rgFor(dcFixAxes(fx2))
	if rg2.Status != rgClear {
		t.Fatalf("fully-checked clean company should be no_verified_blocker, got %s (gaps: %v)", rg2.Status, rg2.EvidenceGaps)
	}
	if !strings.Contains(rg2.StatusLabel, "≠ تأیید") {
		t.Fatalf("clear label must carry the ≠ تأیید caveat: %q", rg2.StatusLabel)
	}
}
