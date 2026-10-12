package qvt

// Unit tests for the «فرصت‌های قابل بررسی بازار» engine (گام ۲-ک-۷ + لایهٔ
// تصمیم ۲-ک-۸) — pure, no database, no real artifacts.
//
// Verified here:
//   - decision groups: attractive needs gates AND defensible economics —
//     waiting-on-value / waiting-on-entry / apparent-value-risk / no-case
//     are four distinct recorded outcomes; zero attractive is possible and
//     carries the honest note
//   - gates still gate: blocked (B2) or missing score or unverified freshness
//     or invalid peer group can never be an attractive candidate
//   - the ordering (D6) is strictly ordinal, deterministic, symbol tie-break
//   - reasons are traceable (numbers or recorded findings), never generic;
//     diagnostic earnings-growth NEVER appears as a positive reason — its
//     recorded warning can only appear under «احتیاط»
//   - review_when carries measurable monitoring conditions, not predictions
//   - perturbation: removing a source field (observed points) moves the
//     company out of the attractive group — no invented result
//   - endpoint integration: board ships with decision_policy and rules

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// ── fixtures ─────────────────────────────────────────────────────────────────

// boardFac مشخصهٔ یک فاکتور آرتیفکت برای تست تصمیم.
type boardFac struct {
	score   float64
	raw     *float64
	omitRaw bool
	status  string
	nSector *int
	warns   []string
}

func boardFacM(m map[string]boardFac) map[string]any {
	out := map[string]any{}
	for name, f := range m {
		fm := map[string]any{
			"weight": 5.0, "raw_status": "valid",
			"score": f.score, "score_kind": "percentile_combined", "included": true,
		}
		if !f.omitRaw {
			fm["raw_value"] = 1.0
			if f.raw != nil {
				fm["raw_value"] = *f.raw
			}
		}
		if f.status != "" {
			fm["raw_status"] = f.status
		}
		if f.nSector != nil {
			fm["n_valid_sector"] = float64(*f.nSector)
		}
		if len(f.warns) > 0 {
			ws := []any{}
			for _, w := range f.warns {
				ws = append(ws, w)
			}
			fm["warnings"] = ws
		}
		out[name] = fm
	}
	return out
}

// مجموعه‌های استاندارد عوامل — روی آستانه‌های سیاست کالیبره شده‌اند.
func boardQGood() map[string]boardFac {
	return map[string]boardFac{
		"roe_level": {score: 0.80}, "margins": {score: 0.60},
		"leverage": {score: 0.50}, "interest_coverage": {score: 0.50},
		"cash_conversion": {score: 0.70},
	}
}
func boardQWeak() map[string]boardFac {
	return map[string]boardFac{
		"roe_level": {score: 0.15}, "margins": {score: 0.30},
		"leverage": {score: 0.10}, "interest_coverage": {score: 0.25},
		"cash_conversion": {score: 0.15},
	}
}

// boardQGoodCashWeak بنیادی قوی با ROE بالا اما تبدیل نقد ضعیف — باید «مشروط»
// شود نه «جذاب بدون قید» (گام ۲-ک-۹: ضعف پشت ROE قوی پنهان نمی‌ماند).
func boardQGoodCashWeak() map[string]boardFac {
	m := boardQGood()
	m["cash_conversion"] = boardFac{score: 0.30}
	return m
}
func boardVCheap() map[string]boardFac {
	return map[string]boardFac{
		"pe": {score: 0.80, raw: f64Ptr(7.5)}, "pb": {score: 0.70, raw: f64Ptr(2.0)},
		"ps": {score: 0.60, raw: f64Ptr(1.0)},
	}
}
func boardVNotCheap() map[string]boardFac {
	return map[string]boardFac{
		"pe": {score: 0.30, raw: f64Ptr(25.0)}, "pb": {score: 0.40, raw: f64Ptr(6.0)},
		"ps": {score: 0.50, raw: f64Ptr(3.0)},
	}
}
func boardTGood() map[string]boardFac {
	return map[string]boardFac{
		"momentum_6m_rel":             {score: 0.80, raw: f64Ptr(0.50)},
		"relative_strength_6m_sector": {score: 0.70, raw: f64Ptr(0.30)},
		"liquidity":                   {score: 0.80, raw: f64Ptr(500e9)},
	}
}
func boardTHostile() map[string]boardFac {
	return map[string]boardFac{
		"momentum_6m_rel":             {score: 0.10, raw: f64Ptr(-0.50)},
		"relative_strength_6m_sector": {score: 0.05, raw: f64Ptr(-0.80)},
		"liquidity":                   {score: 0.80, raw: f64Ptr(500e9)},
	}
}

// boardWorld دنیای تست: شرکت‌های سه‌محوری + ردیف‌های discovery + آرتیفکت‌ها.
type boardWorld struct {
	comps    []*discCompany
	rows     []discModeRow
	px       map[string]*priceCheck
	overlays []qvtOverlayDoc
	q, v, t  map[string]any
}

func newBoardWorld() *boardWorld {
	return &boardWorld{px: map[string]*priceCheck{}, q: map[string]any{}, v: map[string]any{}, t: map[string]any{}}
}

type boardCase struct {
	id, sym      string
	industry     string
	q, v, t      map[string]boardFac
	qp, vp, tp   float64
	comp         bool
	groupSize    int
	px           *priceCheck
	riskGate     *riskGateEval
	conf         string
	coverageQ    float64
}

func (w *boardWorld) add(c boardCase) {
	qp, vp, tp := c.qp, c.vp, c.tp
	if c.industry == "" {
		c.industry = "فلزات"
	}
	if c.coverageQ == 0 {
		c.coverageQ = 0.9
	}
	conf := c.conf
	if conf == "" {
		conf = "no_findings_recorded"
	}
	rg := riskGateEval{Status: rgClear, StatusLabel: rgStatusLabels[rgClear]}
	if c.riskGate != nil {
		rg = *c.riskGate
	}
	dc := &discCompany{
		CompanyID: c.id, Symbol: c.sym, Industry: c.industry, ModelFamily: "general",
		Q:          discAxis{Points: &qp, CoveredWeight: &qp, CoverageRatio: f64Ptr(c.coverageQ), ScoredFactors: []string{"roe_level", "margins"}, FactorIssues: []discFactorIssue{}},
		V:          discAxis{Points: &vp, CoveredWeight: &vp, CoverageRatio: f64Ptr(1.0), ScoredFactors: []string{"pe", "pb"}, FactorIssues: []discFactorIssue{}},
		T:          discAxis{Points: &tp, CoveredWeight: &tp, CoverageRatio: f64Ptr(1.0), ScoredFactors: []string{"momentum_6m_rel"}, FactorIssues: []discFactorIssue{}},
		Confidence: discConfidence{Overall: conf, OverallLabel: "—"},
		RiskGate:   rg,
	}
	row := discModeRow{
		CompanyID: c.id, Comparability: "comparable", GroupValid: c.comp,
		GroupSize: c.groupSize, GroupLabel: "گروه تست",
	}
	w.comps = append(w.comps, dc)
	w.rows = append(w.rows, row)
	w.px[c.id] = c.px
	w.q[c.id] = map[string]any{"company_id": c.id, "symbol": c.sym, "industry": c.industry, "factors": boardFacM(c.q)}
	w.v[c.id] = map[string]any{"company_id": c.id, "symbol": c.sym, "industry": c.industry, "factors": boardFacM(c.v)}
	w.t[c.id] = map[string]any{"company_id": c.id, "symbol": c.sym, "industry": c.industry, "factors": boardFacM(c.t)}
}

func (w *boardWorld) input() boardInput {
	return boardInput{
		companies: w.comps,
		balanced:  discModeResult{Mode: "balanced", Rows: w.rows},
		px:        w.px, overlays: w.overlays, asOf: "2026-10-08",
		qc: w.q, vc: w.v, tc: w.t, policy: defaultBoardDecisionPolicy(),
	}
}

func f64Ptr(f float64) *float64 { return &f }

func boardPxFresh(age int) *priceCheck {
	v := false
	return &priceCheck{Available: true, RowFound: true, Violation: &v, AgeDays: &age, PolicyDays: intPtr(7)}
}

// boardGroupOf خروجی موتور (اسلایس typed) را از مسیر JSON رد می‌کند تا
// دقیقاً همان چیزی را ببینیم که کلاینت می‌بیند.
func boardGroupOf(t *testing.T, board gin.H, key string) []map[string]any {
	t.Helper()
	raw, err := json.Marshal(board[key])
	if err != nil {
		t.Fatalf("marshal %s: %v", key, err)
	}
	var arr []map[string]any
	if err := json.Unmarshal(raw, &arr); err != nil {
		t.Fatalf("unmarshal %s: %v", key, err)
	}
	return arr
}

func boardEntryOf(t *testing.T, arr []map[string]any, i int) map[string]any {
	t.Helper()
	if i >= len(arr) {
		t.Fatalf("entry %d out of range (len=%d)", i, len(arr))
	}
	return arr[i]
}

func boardList(t *testing.T, e map[string]any, key string) []string {
	t.Helper()
	raw, err := json.Marshal(e[key])
	if err != nil {
		t.Fatalf("marshal %s: %v", key, err)
	}
	var out []string
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("unmarshal %s: %v", key, err)
	}
	return out
}

// boardMapOf هر مقدار gin.H را از مسیر JSON به map معمولی تبدیل می‌کند.
func boardMapOf(t *testing.T, v any) map[string]any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	return m
}

// boardCountsGroups قرارداد صریح گام ۲-ک-۱۰: بخش groups شمارش‌ها.
func boardCountsGroups(t *testing.T, board gin.H) map[string]any {
	t.Helper()
	return boardMapOf(t, boardMapOf(t, board["counts"])["groups"])
}

// boardCountsAttrs بخش attributes شمارش‌ها — صفت‌های مستقل از گروه.
func boardCountsAttrs(t *testing.T, board gin.H) map[string]any {
	t.Helper()
	return boardMapOf(t, boardMapOf(t, board["counts"])["attributes"])
}

func boardCountInt(m map[string]any, k string) int {
	if v, ok := m[k].(float64); ok {
		return int(v)
	}
	return -1
}

// boardAssertGroupsReconcile ناوردای قرارداد: مجموع چهار گروه = جامعهٔ سه‌محوری.
func boardAssertGroupsReconcile(t *testing.T, board gin.H) {
	t.Helper()
	g := boardCountsGroups(t, board)
	sum := boardCountInt(g, "attractive_candidates") + boardCountInt(g, "fundamentals_waiting") +
		boardCountInt(g, "apparent_value_risk") + boardCountInt(g, "blocked_or_insufficient")
	if sum != boardCountInt(g, "total") || sum != boardCountInt(g, "universe") {
		t.Fatalf("group partition broken: sum=%d total=%d universe=%d", sum, g["total"], g["universe"])
	}
	if rec, _ := g["reconciles"].(bool); !rec {
		t.Fatalf("groups.reconciles must be true: %+v", g)
	}
	// هیچ کلید صفتی نباید داخل groups باشد (جمع ظاهری گمراه‌کننده ممنوع)
	for _, k := range []string{"conditional", "conditional_candidates", "n_conditional_blocking",
		"risk_review_required", "price_freshness_verified", "negative_operating_profit"} {
		if _, bad := g[k]; bad {
			t.Fatalf("group counts must not contain attribute key %q", k)
		}
	}
}

// ۱) لایهٔ تصمیم: پنج شرکت با گیت‌های یکسان (گروه معتبر + تازگی تأییدشده)
// اما اقتصاد متفاوت → پنج سرنوشت متفاوت و قابل توضیح.
func TestBoardDecisionGroups(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c-att", sym: "جذاب", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	w.add(boardCase{id: "c-waitval", sym: "منتظرحفظه", q: boardQGood(), v: boardVNotCheap(), t: boardTGood(),
		qp: 30, vp: 12, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	w.add(boardCase{id: "c-waitentry", sym: "منتظرو", q: boardQGood(), v: boardVCheap(), t: boardTHostile(),
		qp: 30, vp: 24, tp: 5, comp: true, groupSize: 6, px: boardPxFresh(2)})
	w.add(boardCase{id: "c-cheapweak", sym: "ارزان‌ضعیف", q: boardQWeak(), v: boardVCheap(), t: boardTGood(),
		qp: 12, vp: 26, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	w.add(boardCase{id: "c-nocase", sym: "بی‌پرونده", q: boardQWeak(), v: boardVNotCheap(), t: boardTGood(),
		qp: 12, vp: 12, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board := buildOpportunityBoard(w.input())

	att := boardGroupOf(t, board, "attractive_candidates")
	if len(att) != 1 || att[0]["company_id"] != "c-att" {
		t.Fatalf("attractive must hold only c-att: %+v", att)
	}
	if att[0]["fundamental"] != "strong" {
		t.Fatalf("c-att fundamental must be strong, got %v", att[0]["fundamental"])
	}
	if att[0]["value_defensible"] != true || att[0]["entry"] != "ok" {
		t.Fatalf("c-att value/entry must pass: %+v", att[0])
	}
	// شرایط پایش نامزد جذاب: مانیتور عددی، نه پیش‌بینی
	rw := boardList(t, att[0], "review_when")
	if len(rw) == 0 || !strings.Contains(rw[0], "مانیتور") {
		t.Fatalf("attractive review_when must carry the numeric monitor condition: %+v", rw)
	}
	// دلایل عددی قابل ردیابی
	why := boardList(t, att[0], "why")
	if len(why) < 2 {
		t.Fatalf("attractive why must carry fundamental+value+entry lines: %+v", why)
	}
	if !strings.Contains(why[0], "roe_level") || !strings.Contains(why[1], "میانگین پرسنتایل") {
		t.Fatalf("why lines must be numeric: %+v", why)
	}

	wait := boardGroupOf(t, board, "fundamentals_waiting")
	if len(wait) != 2 {
		t.Fatalf("waiting must hold waitval+waitentry, got %d: %+v", len(wait), wait)
	}
	byID := map[string]map[string]any{}
	for _, e := range wait {
		byID[e["company_id"].(string)] = e
	}
	if e := byID["c-waitval"]; e == nil || !strings.Contains(e["group_reason"].(string), "ارزندگی قابل دفاع نیست") {
		t.Fatalf("waitval reason must name value blocker: %+v", e)
	}
	if e := byID["c-waitentry"]; e == nil || !strings.Contains(e["group_reason"].(string), "شرایط ورود") {
		t.Fatalf("waitentry reason must name entry blocker: %+v", e)
	}

	cheap := boardGroupOf(t, board, "apparent_value_risk")
	if len(cheap) != 1 || cheap[0]["company_id"] != "c-cheapweak" {
		t.Fatalf("apparent_value_risk must hold c-cheapweak: %+v", cheap)
	}
	if !strings.Contains(cheap[0]["group_reason"].(string), "ارزان‌نما") {
		t.Fatalf("cheap-risk reason must name the trap: %+v", cheap[0]["group_reason"])
	}

	blocked := boardGroupOf(t, board, "blocked_or_insufficient")
	if len(blocked) != 1 || blocked[0]["company_id"] != "c-nocase" {
		t.Fatalf("blocked must hold c-nocase: %+v", blocked)
	}
	if !strings.Contains(blocked[0]["group_reason"].(string), "بدون پروندهٔ قابل دفاع") {
		t.Fatalf("no-case reason must be explicit: %+v", blocked[0]["group_reason"])
	}

	counts := boardMapOf(t, board["counts"])
	if int(counts["n_triple_universe"].(float64)) != 5 {
		t.Fatalf("universe = %v, want 5", counts["n_triple_universe"])
	}
	nia := boardMapOf(t, counts["not_in_attractive_reasons"])
	sum := 0.0
	for _, v := range nia {
		sum += v.(float64)
	}
	if sum != 5 {
		t.Fatalf("not_in_attractive_reasons must reconcile to 5: %v", nia)
	}
	boardAssertGroupsReconcile(t, board)
}

// ۲) گیت‌ها همچنان گیت‌اند: اقتصاد خوب هرگز مانع اثبات‌شده/شواهد مفقود/
// تازگی تأییدنشده/گروه ناعتبر را جبران نمی‌کند.
func TestBoardGatesStillGate(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c-blk", sym: "مسدود", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2),
		riskGate: &riskGateEval{Status: rgBlocked, StatusLabel: rgStatusLabels[rgBlocked],
			Blockers: []riskFinding{{Kind: "b2_invalid_raw_in_scored_factor", BlockingRule: "B2", Severity: sevProvenError}}}})
	w.add(boardCase{id: "c-small", sym: "کوچک", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: false, groupSize: 2, px: boardPxFresh(2)})
	w.add(boardCase{id: "c-stale", sym: "کهنه", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6,
		px: &priceCheck{Available: true, RowFound: true, Violation: boolPtr(true), AgeDays: intPtr(20), PolicyDays: intPtr(7)}})
	board := buildOpportunityBoard(w.input())

	if got := boardGroupOf(t, board, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("none of the gated companies may be attractive, got %d", len(got))
	}
	blocked := boardEntryOf(t, boardGroupOf(t, board, "blocked_or_insufficient"), 0)
	if blocked["company_id"] != "c-blk" || !strings.Contains(blocked["group_reason"].(string), "B2") {
		t.Fatalf("blocker rule must be named: %+v", blocked["group_reason"])
	}
	wait := boardGroupOf(t, board, "fundamentals_waiting")
	if len(wait) != 2 {
		t.Fatalf("waiting must hold small+stale, got %d", len(wait))
	}
	for _, e := range wait {
		reason := e["group_reason"].(string)
		switch e["company_id"] {
		case "c-small":
			if !strings.Contains(reason, "همتا") || !strings.Contains(reason, "۵") {
				t.Fatalf("small-group reason must name peers and threshold: %s", reason)
			}
			if e["value_defensible"] != false {
				t.Fatalf("small-group company must not get a defensible relative value claim")
			}
		case "c-stale":
			if !strings.Contains(reason, "تازگی") {
				t.Fatalf("stale reason must name freshness: %s", reason)
			}
		default:
			t.Fatalf("unexpected waiting entry %v", e["company_id"])
		}
	}
}


// ۳) صفر نامزد جذاب ممکن و صادقانه است.
func TestBoardZeroAttractivePossible(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "الف", q: boardQWeak(), v: boardVCheap(), t: boardTGood(),
		qp: 12, vp: 26, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	w.add(boardCase{id: "c2", sym: "ب", q: boardQWeak(), v: boardVNotCheap(), t: boardTGood(),
		qp: 12, vp: 12, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board := buildOpportunityBoard(w.input())
	if got := boardGroupOf(t, board, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("zero attractive expected, got %d", len(got))
	}
	if strings.TrimSpace(board["empty_note"].(string)) == "" {
		t.Fatalf("empty attractive group must carry the honest note")
	}
	if boardCountInt(boardCountsGroups(t, board), "attractive_candidates") != 0 {
		t.Fatalf("count must be zero")
	}
	boardAssertGroupsReconcile(t, board)
}

// ۴) قاعدهٔ ترتیب D6 — ریسک قبل از کیفیت؛ اطمینان داده قبل از لایه؛
// لایه قبل از تازگی؛ Q فقط تساوی‌شکن؛ قطعیت کامل.
func TestBoardOrderIsOrdinalNotComposite(t *testing.T) {
	mk := func(id, sym string, q float64, rgStatus, conf string, layer int, age int) *boardEntry {
		qp := q
		vp, tp := 10.0, 10.0
		l := layer
		a := age
		viol := false
		return &boardEntry{
			CompanyID: id, Symbol: sym, Q: boardAxisStatus{Points: &qp, Max: 40},
			V: boardAxisStatus{Points: &vp}, T: boardAxisStatus{Points: &tp},
			RiskGateStatus: rgStatus, ConfidenceOverall: conf,
			ParetoLayer:    &l,
			PriceFreshness: &priceCheck{Available: true, RowFound: true, Violation: &viol, AgeDays: &a},
		}
	}
	highQ := mk("c1", "الف", 39, rgReview, "no_findings_recorded", 1, 3)
	lowQ := mk("c2", "ب", 5, rgClear, "no_findings_recorded", 1, 3)
	findings := mk("c3", "پ", 30, rgClear, "findings", 1, 3)
	layer2 := mk("c4", "ت", 30, rgClear, "no_findings_recorded", 2, 3)
	oldPx := mk("c5", "ث", 30, rgClear, "no_findings_recorded", 1, 6)

	entries := []*boardEntry{highQ, lowQ, findings, layer2, oldPx}
	sort.SliceStable(entries, func(i, j int) bool { return boardLessPriority(entries[i], entries[j]) })
	want := []string{"c2", "c5", "c4", "c3", "c1"}
	for i, e := range entries {
		if e.CompanyID != want[i] {
			t.Fatalf("order[%d] = %s, want %s (D6 violated)", i, e.CompanyID, want[i])
		}
	}
	entries2 := []*boardEntry{oldPx, layer2, findings, lowQ, highQ}
	sort.SliceStable(entries2, func(i, j int) bool { return boardLessPriority(entries2[i], entries2[j]) })
	for i := range entries {
		if entries[i].CompanyID != entries2[i].CompanyID {
			t.Fatalf("nondeterministic order: %s vs %s", entries[i].CompanyID, entries2[i].CompanyID)
		}
	}
	t1 := mk("cx", "ژ", 20, rgClear, "no_findings_recorded", 1, 3)
	t2 := mk("cy", "چ", 20, rgClear, "no_findings_recorded", 1, 3)
	pair := []*boardEntry{t2, t1}
	sort.SliceStable(pair, func(i, j int) bool { return boardLessPriority(pair[i], pair[j]) })
	if pair[0].Symbol != "چ" || pair[1].Symbol != "ژ" {
		t.Fatalf("symbol tie-break broken: %s before %s", pair[0].Symbol, pair[1].Symbol)
	}
}

// ۵) دلایل قابل ردیابی + رشد سود تشخیصی هرگز دلیل مثبت نیست (D9).
func TestBoardReasonsTraceableNoDiagGrowth(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c-eg", sym: "رشد", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	egPayload := map[string]any{
		"verdict": "verified_with_limitation",
		"warnings": []any{
			"net_profit_growth_pct: بزرگی رشد 428000000٪ بیش از باند اقتصادی ۲۰۰٪ — اثر تورم/پایهٔ کوچک محتمل",
		},
	}
	raw, _ := json.Marshal(egPayload)
	w.overlays = []qvtOverlayDoc{{
		Kind:     "eg_economic_audit",
		Computed: map[string]json.RawMessage{"c-eg": raw},
	}}
	board := buildOpportunityBoard(w.input())

	e := boardEntryOf(t, boardGroupOf(t, board, "attractive_candidates"), 0)
	why := boardList(t, e, "why")
	if len(why) == 0 || len(why) > 3 {
		t.Fatalf("why must have 1..3 items, got %d", len(why))
	}
	for _, s := range why {
		if strings.Contains(s, "رشد سود") {
			t.Fatalf("diagnostic growth must never be a positive reason: %s", s)
		}
		if !strings.ContainsAny(s, "0123456789۰۱۲۳۴۵۶۷۸۹") {
			t.Fatalf("every reason must carry a traceable number/reference: %s", s)
		}
	}
	careful := boardList(t, e, "careful")
	foundEg := false
	for _, s := range careful {
		if strings.Contains(s, "ممیزی رشد سود") {
			foundEg = true
		}
	}
	if !foundEg {
		t.Fatalf("eg quality warning must appear under «احتیاط»: %+v", careful)
	}
	if e["top_reason"].(string) != why[0] || e["top_risk"].(string) != careful[0] {
		t.Fatalf("top fields must mirror first list items")
	}
}

// ۶) تغییر دادهٔ منبع نتیجه را می‌شکند، نه اینکه ساختگی بماند.
func TestBoardPerturbationMovesCompanyOut(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "الف", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	full := buildOpportunityBoard(w.input())
	if got := boardGroupOf(t, full, "attractive_candidates"); len(got) != 1 {
		t.Fatalf("sanity: full evidence+economics → attractive, got %d", len(got))
	}
	w.comps[0].V.Points = nil // شبیه‌سازی نبود دادهٔ منبع
	pert := buildOpportunityBoard(w.input())
	if got := boardGroupOf(t, pert, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("perturbed source must NOT stay an attractive candidate, got %d", len(got))
	}
	e := boardEntryOf(t, boardGroupOf(t, pert, "blocked_or_insufficient"), 0)
	if !strings.Contains(e["group_reason"].(string), "V") {
		t.Fatalf("exclusion reason must name the missing axis: %+v", e["group_reason"])
	}
}

// ۷) انتگرال endpoint: board در پاسخ discovery هست، شمارش‌ها سازگارند،
// سیاست تصمیم و قواعد منتشر می‌شوند و بدون منبع قیمت هیچ نامزد جذابی نیست.
func TestBoardInDiscoveryResponse(t *testing.T) {
	var fx []discFixture
	for i := 0; i < 6; i++ {
		fx = append(fx, discFixture{
			ID: fmt.Sprintf("c-%02d", i), Symbol: fmt.Sprintf("س%02d", i),
			Industry: "فلزات", QPts: float64(20 + i), VPts: 15, TPts: 10,
			QEl: true, VEl: true, TEl: true,
			QScored: []string{"roe_level", "margins"}, VScored: []string{"pe", "pb", "ps"}, TScored: []string{"momentum_6m_rel", "liquidity"},
		})
	}
	fx = append(fx,
		discFixture{ID: "c-s1", Symbol: "ک۱", Industry: "دارو", QPts: 25, VPts: 15, TPts: 10, QEl: true, VEl: true, TEl: true, QScored: []string{"roe_level", "margins"}, VScored: []string{"pe", "pb", "ps"}, TScored: []string{"momentum_6m_rel", "liquidity"}},
		discFixture{ID: "c-s2", Symbol: "ک۲", Industry: "دارو", QPts: 22, VPts: 15, TPts: 10, QEl: true, VEl: true, TEl: true, QScored: []string{"roe_level", "margins"}, VScored: []string{"pe", "pb", "ps"}, TScored: []string{"momentum_6m_rel", "liquidity"}})
	fx = append(fx, discFixture{ID: "c-nt", Symbol: "بی‌تی", Industry: "فلزات", QPts: 25, VPts: 15, QEl: true, VEl: true, TEl: true, QScored: []string{"roe_level", "margins"}, VScored: []string{"pe", "pb", "ps"}, TScored: []string{"momentum_6m_rel", "liquidity"}, TNilPoints: true})

	r := discServer(t, fx)
	d := discFetch(t, r)
	board, ok := d["opportunity_board"].(map[string]any)
	if !ok {
		t.Fatalf("opportunity_board missing from discovery response")
	}
	g := boardCountsGroups(t, board)
	nAtt := boardCountInt(g, "attractive_candidates")
	nWait := boardCountInt(g, "fundamentals_waiting")
	nBlocked := boardCountInt(g, "blocked_or_insufficient")
	// بدون DSN قیمت، تازگی هیچ‌کس تأیید نمی‌شود → هیچ نامزد جذابی نیست
	if nAtt != 0 {
		t.Fatalf("without price source attractive_candidates must be 0, got %d", nAtt)
	}
	// ۶ عضو گروه معتبر (تازگی تأییدنشده) + ۲ عضو گروه کوچک → «منتظر شرایط بهتر»
	if nWait != 8 {
		t.Fatalf("fundamentals_waiting = %d, want 8", nWait)
	}
	if nBlocked != 1 {
		t.Fatalf("blocked_or_insufficient = %d, want 1 (missing T)", nBlocked)
	}
	if boardCountInt(g, "total") != 9 || boardCountInt(g, "universe") != 9 {
		t.Fatalf("groups must partition the triple universe: %+v", g)
	}
	boardAssertGroupsReconcile(t, board)
	if strings.TrimSpace(board["empty_note"].(string)) == "" {
		t.Fatalf("empty attractive group must carry the honest note in the endpoint too")
	}
	if _, ok := board["rules"].(map[string]any); !ok {
		t.Fatalf("board rules must be published with the payload")
	}
	pol, ok := board["decision_policy"].(map[string]any)
	if !ok || pol["version"] != "opportunity-decision-policy-v2" {
		t.Fatalf("decision policy must be published with version v2: %+v", pol)
	}
	wait := boardGroupOf(t, board, "fundamentals_waiting")
	if len(wait) == 0 || !strings.Contains(wait[0]["group_reason"].(string), "تازگی") &&
		!strings.Contains(wait[0]["group_reason"].(string), "همتا") {
		t.Fatalf("waiting reasons must name freshness or peers: %+v", wait[0]["group_reason"])
	}
}

// TestBoardConditionalQualityCaveat (گام ۲-ک-۹): بنیادی قوی با ROE بالا اما
// تبدیل نقد ضعیف نباید «جذاب بدون قید» شود — باید «مشروط» و در گروه دوم با
// ذکر صریح قید بیاید. سیاست نسخهٔ ۱ (بدون قید) همان شرکت را جذاب می‌دید؛ این
// تست تفاوت رفتاری دو نسخه را تثبیت می‌کند.
func TestBoardConditionalQualityCaveat(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "قیدنقد", q: boardQGoodCashWeak(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 25, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board := buildOpportunityBoard(w.input())

	if got := boardGroupOf(t, board, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("weak cash conversion must NOT be an unconditional attractive candidate, got %d", len(got))
	}
	wait := boardGroupOf(t, board, "fundamentals_waiting")
	if len(wait) != 1 {
		t.Fatalf("conditional candidate must land in waiting group, got %d", len(wait))
	}
	if cond, _ := wait[0]["conditional"].(bool); !cond {
		t.Fatalf("entry must be flagged conditional: %+v", wait[0])
	}
	cr := boardList(t, wait[0], "conditional_reasons")
	if len(cr) == 0 || !strings.Contains(cr[0], "cash_conversion") {
		t.Fatalf("conditional reason must name the weakening factor: %v", cr)
	}
	// قید باید در «احتیاط» و «بازبینی» هم دیده شود
	care := boardList(t, wait[0], "careful")
	if len(care) == 0 || !strings.Contains(care[0], "قید کیفیت") {
		t.Fatalf("careful must surface the quality caveat first: %v", care)
	}
	if rw := boardList(t, wait[0], "review_when"); len(rw) == 0 {
		t.Fatalf("conditional candidate must carry a measurable re-review condition")
	}
	attrs := boardCountsAttrs(t, board)
	if boardCountInt(attrs, "conditional_in_waiting") != 1 || boardCountInt(attrs, "conditional_total") != 1 {
		t.Fatalf("conditional must be counted as an attribute (in_waiting/total=1): %v", attrs)
	}
	if boardCountInt(attrs, "conditional_blocking") != 1 {
		t.Fatalf("the caveat is the only blocker here — conditional_blocking must be 1: %v", attrs)
	}
	boardAssertGroupsReconcile(t, board)
	// نسخهٔ ۱ سیاست (بدون قید) همان شرکت را جذاب می‌بیند — رفتار نسخهٔ قبل حفظ است
	in1 := w.input()
	in1.policy = boardDecisionPolicyV1()
	boardV1 := buildOpportunityBoard(in1)
	if got := boardGroupOf(t, boardV1, "attractive_candidates"); len(got) != 1 {
		t.Fatalf("policy v1 must still see this as attractive (comparison baseline), got %d", len(got))
	}
}

// TestBoardNegativeOperatingProfitBlocks (گام ۲-ک-۹): سود عملیاتی منفی —
// حتی اگر بیلان/فروش ارزان باشد — باید بنیادی را ضعیف و شرکت را از گروه جذاب
// و از «بنیادی مناسب» بیرون کند (ارزان‌نما).
func TestBoardNegativeOperatingProfit(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "سودعملیاتیمنفی", q: map[string]boardFac{
		"roe_level": {score: 0.30}, "margins": {score: 0.20},
		"leverage": {score: 0.40}, "interest_coverage": {score: 0.05,
			warns: []string{"negative_operating_profit: coverage computed from a real operating loss"}},
		"cash_conversion": {score: 0.90},
	}, v: boardVCheap(), t: boardTGood(), qp: 8, vp: 25, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board := buildOpportunityBoard(w.input())
	if got := boardGroupOf(t, board, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("negative operating profit must not be attractive, got %d", len(got))
	}
	if got := boardGroupOf(t, board, "apparent_value_risk"); len(got) != 1 {
		t.Fatalf("cheap + weak(negative op) must be apparent value risk, got %d", len(got))
	}
}

// TestBoardValueSectorSupportRequired (گام ۲-ک-۹): چندگانهٔ پشتیبان ارزندگی با
// گروه نرمال‌سازی صنعتی کوچک نباید «قابل دفاع» تأیید شود.
func TestBoardValueSectorSupportRequired(t *testing.T) {
	// P/E پشتیبان با تنها ۲ هم‌صنعت معتبر → قابل دفاع نیست → گروه انتظار
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "نمونهکوچک", q: boardQGood(), v: map[string]boardFac{
		"pe": {score: 0.80, raw: f64Ptr(7.0), nSector: intPtr(2)},
		"pb": {score: 0.70, raw: f64Ptr(2.0), nSector: intPtr(2)},
		"ps": {score: 0.60, raw: f64Ptr(1.0), nSector: intPtr(2)},
	}, t: boardTGood(), qp: 30, vp: 25, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board := buildOpportunityBoard(w.input())
	if got := boardGroupOf(t, board, "attractive_candidates"); len(got) != 0 {
		t.Fatalf("tiny sector support must not be a defensible attractive candidate, got %d", len(got))
	}
	// کنترل: همان شرکت با پشتیبانی کافی → جذاب
	w2 := newBoardWorld()
	w2.add(boardCase{id: "c1", sym: "نمونهبزرگ", q: boardQGood(), v: map[string]boardFac{
		"pe": {score: 0.80, raw: f64Ptr(7.0), nSector: intPtr(30)},
		"pb": {score: 0.70, raw: f64Ptr(2.0), nSector: intPtr(16)},
		"ps": {score: 0.60, raw: f64Ptr(1.0), nSector: intPtr(16)},
	}, t: boardTGood(), qp: 30, vp: 25, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2)})
	board2 := buildOpportunityBoard(w2.input())
	if got := boardGroupOf(t, board2, "attractive_candidates"); len(got) != 1 {
		t.Fatalf("adequate sector support must allow attractive, got %d", len(got))
	}
}

// TestBoardSystemicCaveatsPublished (گام ۲-ک-۹): قیدهای جهانی snapshot
// (review_required، تازگی، مبنای سهام↔قیمت، پرووننس order3) منتشر می‌شوند.
func TestBoardSystemicCaveatsPublished(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "الف", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 25, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2),
		riskGate: &riskGateEval{Status: rgReview, StatusLabel: rgStatusLabels[rgReview]}})
	board := buildOpportunityBoard(w.input())
	cav := boardList(t, board, "systemic_caveats")
	if len(cav) < 3 {
		t.Fatalf("systemic caveats must be published: %v", cav)
	}
	attrs := boardCountsAttrs(t, board)
	if boardCountInt(attrs, "risk_review_required") != 1 {
		t.Fatalf("review_required must be published as an attribute: %v", attrs)
	}
	boardAssertGroupsReconcile(t, board)
}

// TestBoardRiskGateScopeConsistentWithCaveat (گام ۲-ک-۱۰): سازگاری معنای «بدون
// قید اختصاصی» با جایگاه Risk Gate. review_required یک قید جهانی snapshot است
// که برای همه ثبت می‌شود و به‌تنهایی مانع گروه ۱ نیست (زیرا «نیازمند بررسی» نه
// رد است نه تأیید)، اما متن تصمیم گروه ۱ باید صراحتاً قید جهانی را افشا کند و
// واژهٔ «بدون قید» به «بدون قید اختصاصی» مقید باشد. همچنین شمارش گروه‌ها باید
// مستقل از صفت‌ها مجموع‌بخش بماند.
func TestBoardRiskGateScopeConsistentWithCaveat(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c-att", sym: "جذاب", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 24, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2),
		riskGate: &riskGateEval{Status: rgReview, StatusLabel: rgStatusLabels[rgReview]}})
	w.add(boardCase{id: "c-weak", sym: "ضعیف", q: boardQWeak(), v: boardVNotCheap(), t: boardTGood(),
		qp: 12, vp: 12, tp: 20, comp: true, groupSize: 6, px: boardPxFresh(2),
		riskGate: &riskGateEval{Status: rgReview, StatusLabel: rgStatusLabels[rgReview]}})
	board := buildOpportunityBoard(w.input())

	attrs := boardCountsAttrs(t, board)
	if boardCountInt(attrs, "risk_review_required") != 2 {
		t.Fatalf("review_required must count 2 as attribute: %v", attrs)
	}
	att := boardGroupOf(t, board, "attractive_candidates")
	if len(att) != 1 {
		t.Fatalf("review_required must not block group-1 by itself, got %d", len(att))
	}
	reason := att[0]["group_reason"].(string)
	if !strings.Contains(reason, "بدون قید اختصاصی") {
		t.Fatalf("group-1 reason must scope the caveat wording to «اختصاصی»: %s", reason)
	}
	if !strings.Contains(reason, "دروازه ریسک") {
		t.Fatalf("group-1 reason must disclose the systemic risk-gate caveat: %s", reason)
	}
	rules := boardMapOf(t, board["rules"])
	if rules["version"] != "opportunity-rules-v4" {
		t.Fatalf("rules version must be v4: %v", rules["version"])
	}
	if _, ok := rules["counting_contract"]; !ok {
		t.Fatalf("counting contract must be published in rules")
	}
	boardAssertGroupsReconcile(t, board)
}
