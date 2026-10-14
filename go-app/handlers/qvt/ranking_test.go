package qvt

// Unit tests for the simple 0..100 review-priority ranking (گام ۲-ک-۱۱) —
// pure, no database, no real artifacts.
//
// Verified here:
//   - score == q_observed_points + v_observed_points + t_observed_points
//     (the three official observed aggregates; no division by covered weight,
//     no redistribution of missing-factor weight, no fabricated value)
//   - a company missing any axis points is NEVER scored (it is skipped, not
//     given a zero/substitute), so the ranked list only ever holds full-evidence
//     candidates
//   - status mapping from the official decision groups + the hard rule that a
//     proven Risk-Gate blocker can never be a buy-review candidate
//   - critical flags (proven blocker / conflicting validation) are surfaced
//     next to the score, never hidden behind a high score
//   - ranking is deterministic, score-descending with a symbol tie-break, and
//     ranks are contiguous 1..n
//   - the unscored list carries a precise reason per company and the scored +
//     unscored partition exactly equals the artifact universe
//   - endpoint integration: ranked + unscored + score_contract ship together

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestRankingFreshnessUsesBundleDateAndTehranDay(t *testing.T) {
	now := time.Date(2026, 10, 12, 21, 0, 0, 0, time.UTC)
	result := rankingFreshness("2026-10-08", now)
	if result["today"] != "2026-10-13" || result["age_calendar_days"] != 5 || result["status"] != "dated" {
		t.Fatalf("unexpected freshness: %v", result)
	}
	if rankingFreshness("invalid", now)["status"] != "unknown" {
		t.Fatal("unparseable bundle date must not be reported fresh")
	}
}

func rankBoard(t *testing.T, w *boardWorld) gin.H {
	t.Helper()
	return buildOpportunityBoard(w.input())
}

// rankCase یک شرکت کامل با اقتصاد قابل تنظیم می‌سازد.
func rankAddCase(w *boardWorld, c boardCase) { w.add(c) }

func rankFind(t *testing.T, arr []*rankEntry, sym string) *rankEntry {
	t.Helper()
	for _, e := range arr {
		if e.Symbol == sym {
			return e
		}
	}
	t.Fatalf("symbol %s not found in ranked list", sym)
	return nil
}

func TestRankingScoreIsSumOfObservedPoints(t *testing.T) {
	w := newBoardWorld()
	w.add(boardCase{id: "c1", sym: "الف", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 25.0, vp: 28.0, tp: 18.0, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})
	w.add(boardCase{id: "c2", sym: "ب", q: boardQGood(), v: boardVNotCheap(), t: boardTGood(),
		qp: 12.4, vp: 9.6, tp: 20.2, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.6})

	ranked := buildRankedEntries(rankBoard(t, w))
	if len(ranked) != 2 {
		t.Fatalf("ranked len = %d want 2", len(ranked))
	}
	e := rankFind(t, ranked, "الف")
	if e.Score != 71.0 { // 25+28+18
		t.Fatalf("score = %v want 71", e.Score)
	}
	e2 := rankFind(t, ranked, "ب")
	if e2.Score != 42.2 { // 12.4+9.6+20.2
		t.Fatalf("score = %v want 42.2", e2.Score)
	}
	// دقیقاً برابر مجموع سه عدد مشاهده‌شده — نه مقیاس‌شده، نه بازتوزیع‌شده
	if got := *e.Q.Points + *e.V.Points + *e.T.Points; rankRound1(got) != e.Score {
		t.Fatalf("score %v != sum of points %v", e.Score, rankRound1(got))
	}
}

func TestRankingMissingAxisIsNeverScored(t *testing.T) {
	q := 10.0
	board := gin.H{
		boardGroupAttractive: []*boardEntry{},
		boardGroupWaiting:    []*boardEntry{},
		boardGroupCheapRisk:  []*boardEntry{},
		boardGroupBlocked: []*boardEntry{{
			CompanyID: "x", Symbol: "ناقص",
			Q: boardAxisStatus{Points: &q, Max: 40, Status: "computed"},
			V: boardAxisStatus{Max: 35, Status: "missing"}, // امتیاز ندارد
			T: boardAxisStatus{Points: &q, Max: 25, Status: "computed"},
		}},
	}
	ranked := buildRankedEntries(board)
	if len(ranked) != 0 {
		t.Fatalf("a company with a missing axis must not be scored; got %d", len(ranked))
	}
}

func TestRankingStatusMappingAndConditionalDowngrade(t *testing.T) {
	w := newBoardWorld()
	// جذاب بدون قید
	w.add(boardCase{id: "c1", sym: "جذاب", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 30, vp: 30, tp: 20, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})
	// مشروط: تبدیل نقد ضعیف → گروه منتظر، نه جذاب
	w.add(boardCase{id: "c2", sym: "مشروط", q: boardQGoodCashWeak(), v: boardVCheap(), t: boardTGood(),
		qp: 28, vp: 30, tp: 19, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})
	// ارزان‌نما: بنیادی ضعیف + ارزان
	w.add(boardCase{id: "c3", sym: "ارزان‌نما", q: boardQWeak(), v: boardVCheap(), t: boardTGood(),
		qp: 6, vp: 30, tp: 19, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})
	// بدون پرونده: بنیادی ضعیف و گران
	w.add(boardCase{id: "c4", sym: "بدون‌پرونده", q: boardQWeak(), v: boardVNotCheap(), t: boardTGood(),
		qp: 5, vp: 8, tp: 12, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})

	ranked := buildRankedEntries(rankBoard(t, w))
	if len(ranked) != 4 {
		t.Fatalf("ranked len = %d want 4", len(ranked))
	}
	if got := rankFind(t, ranked, "جذاب").Status; got != rankStatusBuyReview {
		t.Fatalf("جذاب status = %s want %s", got, rankStatusBuyReview)
	}
	mc := rankFind(t, ranked, "مشروط")
	if mc.Status != rankStatusWait {
		t.Fatalf("مشروط status = %s want %s", mc.Status, rankStatusWait)
	}
	if !mc.Conditional || len(mc.ConditionalReasons) == 0 {
		t.Fatalf("مشروط must carry conditional attribute + reasons")
	}
	if got := rankFind(t, ranked, "ارزان‌نما").Status; got != rankStatusWeak {
		t.Fatalf("ارزان‌نما status = %s want %s", got, rankStatusWeak)
	}
	if got := rankFind(t, ranked, "بدون‌پرونده").Status; got != rankStatusWeak {
		t.Fatalf("بدون‌پرونده status = %s want %s", got, rankStatusWeak)
	}
}

func TestRankingCriticalRiskNeverHiddenBehindHighScore(t *testing.T) {
	w := newBoardWorld()
	blocked := riskGateEval{
		Status: rgBlocked, StatusLabel: rgStatusLabels[rgBlocked],
		Blockers: []riskFinding{{BlockingRule: "B1", SeverityLabel: "اثبات‌شده"}},
	}
	// بهترین اقتصاد ممکن، اما مانع اثبات‌شدهٔ ریسک
	w.add(boardCase{id: "c1", sym: "پرمخاطره", q: boardQGood(), v: boardVCheap(), t: boardTGood(),
		qp: 32, vp: 33, tp: 22, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.9, riskGate: &blocked})

	ranked := buildRankedEntries(rankBoard(t, w))
	e := rankFind(t, ranked, "پرمخاطره")
	if e.Status == rankStatusBuyReview {
		t.Fatalf("a proven Risk-Gate blocker must never be buy-review")
	}
	if !e.Critical || len(e.CriticalFlags) == 0 {
		t.Fatalf("critical flag must be surfaced next to the score")
	}
	if e.Score <= 0 {
		t.Fatalf("score should still be computed from valid data")
	}
}

func TestRankingSortedAndRankContiguous(t *testing.T) {
	w := newBoardWorld()
	pts := []struct {
		id, sym    string
		qp, vp, tp float64
	}{{"a", "ز", 10, 10, 10}, {"b", "الف", 20, 20, 20}, {"c", "م", 15, 15, 15}}
	for _, p := range pts {
		w.add(boardCase{id: p.id, sym: p.sym, q: boardQGood(), v: boardVCheap(), t: boardTGood(),
			qp: p.qp, vp: p.vp, tp: p.tp, comp: true, groupSize: 8, px: boardPxFresh(1), coverageQ: 0.8})
	}
	ranked := buildRankedEntries(rankBoard(t, w))
	for i := 1; i < len(ranked); i++ {
		if ranked[i-1].Score < ranked[i].Score {
			t.Fatalf("not score-descending at %d", i)
		}
	}
	for i, e := range ranked {
		if e.Rank != i+1 {
			t.Fatalf("rank at %d = %d want %d", i, e.Rank, i+1)
		}
	}
	// determinism
	again := buildRankedEntries(rankBoard(t, w))
	for i := range ranked {
		if ranked[i].CompanyID != again[i].CompanyID || ranked[i].Score != again[i].Score {
			t.Fatalf("ranking is not deterministic at %d", i)
		}
	}
}

func TestRankingUnscoredReasonsAndPartition(t *testing.T) {
	qc := map[string]any{
		"c1": map[string]any{"symbol": "واجد", "industry": "فلزات", "pilot_eligible": true,
			"coverage_ratio": 0.8, "covered_weight": 24.0,
			"essential_status": map[string]any{"missing": []any{}}},
		"c2": map[string]any{"symbol": "بدون‌ضروری", "industry": "فلزات", "pilot_eligible": false,
			"coverage_ratio": 0.3, "covered_weight": 9.0,
			"essential_status": map[string]any{"missing": []any{"margins", "roe_level"}}},
	}
	vc := map[string]any{
		"c1": map[string]any{"symbol": "واجد", "pilot_eligible": true, "coverage_ratio": 1.0,
			"essential_status": map[string]any{"missing": []any{}}},
		"c2": map[string]any{"symbol": "بدون‌ضروری", "pilot_eligible": true, "coverage_ratio": 1.0,
			"essential_status": map[string]any{"missing": []any{}}},
	}
	tc := map[string]any{
		"c1": map[string]any{"symbol": "واجد", "pilot_eligible": true, "coverage_ratio": 1.0,
			"essential_status": map[string]any{"missing": []any{}}},
		// c2 در T غایب است → no_data_t
	}
	scored := map[string]bool{"c1": true}
	un := buildUnscored(qc, vc, tc, scored)
	if len(un) != 1 {
		t.Fatalf("unscored len = %d want 1", len(un))
	}
	u := un[0]
	if u.CompanyID != "c2" {
		t.Fatalf("unscored company = %s want c2", u.CompanyID)
	}
	// c2 در Q عامل ضروری مفقود دارد و در T غایب است → دو محور مسدودکننده
	if len(u.BlockingAxes) != 2 || u.BlockingAxes[0] != "Q" {
		t.Fatalf("blocking axes = %v want [Q T]", u.BlockingAxes)
	}
	if u.ReasonCode != "missing_essential_q" {
		t.Fatalf("reason code = %s want missing_essential_q", u.ReasonCode)
	}
	if u.ReasonLabel == "" {
		t.Fatalf("reason label must be present")
	}
	// شرکت واجد هرگز در فهرست بی‌امتیاز نمی‌آید
	for _, x := range un {
		if x.CompanyID == "c1" {
			t.Fatalf("scored company must never appear unscored")
		}
	}
	// هیچ فیلد امتیازی در ساختار بی‌امتیاز وجود ندارد (عدم ساخت امتیاز جعلی)
	raw, _ := json.Marshal(u)
	if s := string(raw); strings.Contains(s, `"score"`) || strings.Contains(s, `"rank"`) {
		t.Fatalf("unscored entry must not carry a score/rank: %s", s)
	}
}

// ── endpoint integration ─────────────────────────────────────────────────────

func rankServer(t *testing.T, fx []discFixture) *gin.Engine {
	t.Helper()
	dir := t.TempDir()
	discWriteFixtures(t, dir, fx)
	t.Setenv("QVT_V2_ARTIFACT_DIR", dir)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/qvt-v2/ranking", GetQvtV2Ranking)
	return r
}

func TestRankingEndpointShipsRankedUnscoredContract(t *testing.T) {
	fx := []discFixture{
		{ID: "1", Symbol: "الف", Industry: "فلزات", QPts: 20, VPts: 25, TPts: 15,
			QEl: true, VEl: true, TEl: true, QScored: []string{"margins", "roe_level"},
			VScored: []string{"pe", "pb"}, TScored: []string{"liquidity", "momentum_6m_rel"}},
		{ID: "2", Symbol: "ب", Industry: "فلزات", QPts: 0, VPts: 25, TPts: 15,
			QEl: false, VEl: true, TEl: true, QScored: []string{}, QNotScored: map[string]string{"roe_level": "pending_data"},
			VScored: []string{"pe", "pb"}, TScored: []string{"liquidity", "momentum_6m_rel"}},
	}
	r := rankServer(t, fx)
	w := qvtDo(r, "/api/qvt-v2/ranking")
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", w.Code, w.Body.String())
	}
	d := qvtDecode(t, w)
	ranked, _ := d["ranked"].([]any)
	unscored, _ := d["unscored"].([]any)
	if len(ranked) != 1 {
		t.Fatalf("ranked len = %d want 1 (only the triple-eligible)", len(ranked))
	}
	if len(unscored) != 1 {
		t.Fatalf("unscored len = %d want 1", len(unscored))
	}
	uni, _ := d["universe"].(map[string]any)
	if uni["n_scored"].(float64) != 1 || uni["n_unscored"].(float64) != 1 {
		t.Fatalf("universe partition wrong: %v", uni)
	}
	if _, ok := d["score_contract"]; !ok {
		t.Fatalf("score_contract must ship with the ranking")
	}
	sc, _ := d["score_contract"].(map[string]any)
	if sc["formula"] != "score = q_observed_points + v_observed_points + t_observed_points" {
		t.Fatalf("formula contract changed: %v", sc["formula"])
	}
	if d["score_name"] != "امتیاز مشاهده‌شدهٔ آزمایشی" {
		t.Fatalf("score_name must ship: %v", d["score_name"])
	}
	if sc["score_name"] != "امتیاز مشاهده‌شدهٔ آزمایشی" {
		t.Fatalf("score_contract must carry score_name: %v", sc["score_name"])
	}
	if _, ok := sc["comparability"]; !ok {
		t.Fatalf("score_contract must disclose comparability")
	}
	if _, ok := sc["full_coverage_meaning"]; !ok {
		t.Fatalf("score_contract must explain what full coverage means (Q 31/40 -> 91)")
	}
	if _, ok := d["coverage_impact"]; !ok {
		t.Fatalf("coverage_impact must ship with the ranking")
	}
	if _, ok := d["data_completion_plan"]; !ok {
		t.Fatalf("data_completion_plan must ship with the ranking")
	}
	pg, ok := d["peer_group_impact"].(map[string]any)
	if !ok {
		t.Fatalf("peer_group_impact must ship with the ranking")
	}
	if _, ok := pg["interpretation"]; !ok {
		t.Fatalf("peer_group_impact must carry an interpretation")
	}
}

// TestRankingPeerGroupValidity: گروه همتای متوازن کمتر از ۵ عضو نباید معتبر
// تلقی شود؛ اندازه و اعتبار گروه باید در هر ردیف افشا شود.
func TestRankingPeerGroupValidity(t *testing.T) {
	big := rankBoardEntry("pg-big", "BIG", 20, 28, 22, 31, 35, 25)
	big.GroupSize = 7
	small := rankBoardEntry("pg-small", "SML", 20, 28, 22, 31, 35, 25)
	small.GroupSize = 2
	// گروه ارزیابی‌نشده (خارج از نامزدهای متوازن) نباید «گروه کوچک» شمرده شود
	notEval := rankBoardEntry("pg-none", "NON", 20, 28, 22, 31, 35, 25)
	notEval.GroupSize = 0
	entries := buildRankedEntries(gin.H{
		boardGroupWaiting: []*boardEntry{big, small, notEval},
	})
	byID := map[string]*rankEntry{}
	for _, e := range entries {
		byID[e.CompanyID] = e
	}
	if !byID["pg-big"].PeerGroupValid || byID["pg-big"].PeerGroupSize != 7 {
		t.Fatalf("7-peer group must be valid: %+v", byID["pg-big"])
	}
	if byID["pg-small"].PeerGroupValid || byID["pg-small"].PeerGroupSize != 2 {
		t.Fatalf("2-peer group must NOT be valid: %+v", byID["pg-small"])
	}
	if byID["pg-none"].PeerGroupValid || byID["pg-none"].PeerGroupSize != 0 {
		t.Fatalf("unevaluated group must stay 0/invalid: %+v", byID["pg-none"])
	}
	imp := rankPeerGroupImpact(entries)
	if imp["n_valid_group"].(int) != 1 || imp["n_small_group"].(int) != 1 {
		t.Fatalf("peer group impact counts wrong: %v", imp)
	}
	if imp["n_group_not_evaluated"].(int) != 1 {
		t.Fatalf("unevaluated group must be counted separately: %v", imp)
	}
	if imp["min_group_rule"].(int) != 5 {
		t.Fatalf("min group rule must be 5: %v", imp)
	}
}

// ── comparability / sensitivity ──────────────────────────────────────────────

func rankBoardEntry(id, sym string, qp, vp, tp, cwq, cwv, cwt float64) *boardEntry {
	return &boardEntry{
		CompanyID: id, Symbol: sym, Industry: "فلزات", Group: boardGroupWaiting,
		Q: boardAxisStatus{Points: f64Ptr(qp), CoveredWeight: f64Ptr(cwq), Max: 40, Status: "computed"},
		V: boardAxisStatus{Points: f64Ptr(vp), CoveredWeight: f64Ptr(cwv), Max: 35, Status: "computed"},
		T: boardAxisStatus{Points: f64Ptr(tp), CoveredWeight: f64Ptr(cwt), Max: 25, Status: "computed"},
	}
}

// TestRankingComparabilityAndSensitivity: پوشش نابرابر باید افشا شود (سقف عملی،
// پوشش کامل/جزئی) و تحلیل حساسیت باید جهت اثر پوشش را درست نشان دهد — بدون آنکه
// امتیاز رسمی تغییر کند.
func TestRankingComparabilityAndSensitivity(t *testing.T) {
	a := rankBoardEntry("a", "الف", 24.8, 28, 22, 31, 35, 25) // density Q=0.8, full cover
	b := rankBoardEntry("b", "ب", 15.5, 28, 22, 31, 35, 25)   // density Q=0.5, full cover
	c := rankBoardEntry("c", "ج", 15.0, 28, 22, 25, 35, 25)   // density Q=0.6, PARTIAL Q

	ranked := buildRankedEntries(gin.H{
		boardGroupAttractive: []*boardEntry{},
		boardGroupWaiting:    []*boardEntry{a, b, c},
		boardGroupCheapRisk:  []*boardEntry{},
		boardGroupBlocked:    []*boardEntry{},
	})
	if len(ranked) != 3 {
		t.Fatalf("ranked len = %d want 3", len(ranked))
	}

	ea, eb, ec := rankFind(t, ranked, "الف"), rankFind(t, ranked, "ب"), rankFind(t, ranked, "ج")

	// امتیاز خام = مجموع سه امتیاز مشاهده‌شده (بدون تغییر)
	if ea.Score != 74.8 || eb.Score != 65.5 || ec.Score != 65.0 {
		t.Fatalf("raw scores changed: %v %v %v", ea.Score, eb.Score, ec.Score)
	}
	// سقف عملی = مجموع وزن پوشش‌داده‌شده؛ برای پوشش ناقص کمتر از پوشش کامل
	if ea.PracticalCeiling != 91 || ec.PracticalCeiling != 85 {
		t.Fatalf("practical ceiling wrong: a=%v c=%v", ea.PracticalCeiling, ec.PracticalCeiling)
	}
	// پوشش کامل فقط برای آن‌هایی که پوشش هر سه محور بیشینه است
	if !ea.FullCoverage || !eb.FullCoverage || ec.FullCoverage {
		t.Fatalf("full_coverage flags wrong: a=%v b=%v c=%v", ea.FullCoverage, eb.FullCoverage, ec.FullCoverage)
	}
	if ea.Comparability != "full" || ec.Comparability != "partial" {
		t.Fatalf("comparability labels wrong: a=%s c=%s", ea.Comparability, ec.Comparability)
	}
	// تعمیم چگالی: c با پوشش جزئی در امتیاز خام افتاده ولی چگالی‌اش از b بهتر است
	if ec.ExtrapolatedScore <= eb.ExtrapolatedScore {
		t.Fatalf("c (density .6) must outrank b (density .5) under coverage-equalized: %v vs %v",
			ec.ExtrapolatedScore, eb.ExtrapolatedScore)
	}
	if ec.SensitivityRank != 2 || ec.RankShift != -1 {
		t.Fatalf("c sensitivity rank/shift = %d/%d want 2/-1", ec.SensitivityRank, ec.RankShift)
	}
	if eb.SensitivityRank != 3 || eb.RankShift != 1 {
		t.Fatalf("b sensitivity rank/shift = %d/%d want 3/+1", eb.SensitivityRank, eb.RankShift)
	}
	if ea.RankShift != 0 {
		t.Fatalf("top full-coverage name should not shift: %d", ea.RankShift)
	}

	// سنجهٔ اثر پوشش باید واقعی و از داده ساخته شود
	imp := rankCoverageImpact(ranked)
	if imp["n_full_coverage"].(int) != 2 || imp["n_partial_coverage"].(int) != 1 {
		t.Fatalf("coverage counts wrong: %v", imp)
	}
	if imp["max_rank_shift"].(int) != 1 {
		t.Fatalf("max rank shift = %v want 1", imp["max_rank_shift"])
	}
	sp := imp["spearman_raw_vs_coverage_equalized"].(float64)
	if sp <= 0 || sp >= 0.999 {
		t.Fatalf("spearman raw vs equalized = %v want positive but <1 (a real shift exists)", sp)
	}
}

// TestRankingSpearmanHelper sanity: هویت → +1، وارون کامل → -1.
func TestRankingSpearmanHelper(t *testing.T) {
	x := []float64{1, 2, 3, 4, 5}
	if v := rankSpearman(x, x); v < 0.999 {
		t.Fatalf("identical vectors spearman = %v want ~1", v)
	}
	rev := []float64{5, 4, 3, 2, 1}
	if v := rankSpearman(x, rev); v > -0.999 {
		t.Fatalf("reversed vectors spearman = %v want ~-1", v)
	}
}

func TestRankingBlockersDistinguishEconomicAndDataLimits(t *testing.T) {
	loss := rankBlockerDetail("pe", map[string]any{"normalization_status": "not_ranked_raw_not_applicable"})
	if !strings.Contains(loss, "کمبود داده محسوب نمی‌شود") {
		t.Fatalf("loss maker must not be described as absent financial data: %s", loss)
	}
	gap := rankBlockerDetail("momentum_6m_rel", map[string]any{"validation_reason": "suspected_unadjusted_gap_in_window: evidence"})
	if !strings.Contains(gap, "رویداد شرکتی") {
		t.Fatalf("adjustment refusal must retain actionable cause: %s", gap)
	}
}
