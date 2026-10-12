package qvt

// QVT V2 pilot UI feed — read-only.
//
// Serves the REAL pilot artifacts produced by the analytics package
// (v2_q_observed_report.json / v2_value_pilot.json / v2_t_pilot.json),
// merged by stable company_id for the «تحلیل QVT — آزمایشی» page.
//
// Hard boundaries (identical to the pilot contracts):
//   - file reads only: no database access, no ingestion, no writes of any kind
//   - the three axes stay independent: no Q+V+T sum and no total-of-100 key
//     is ever emitted (guarded by a walk test)
//   - points are never renormalized over covered weight and companies are
//     never returned in score order (stable company_id order, coverage
//     differs across companies)
//   - if an artifact is missing, unreadable, or the as_of/cutoff/identity
//     checks fail, the endpoint refuses loudly instead of serving partial
//     or invented data — the UI shows the error, never sample rows

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// qvtDisclaimer is the exact pilot banner the UI must show — never reworded.
const qvtDisclaimer = "نسخه آزمایشی — اعتبار تاریخی اطلاعات مالی و قیمت‌ها به‌طور کامل تأیید نشده است. نتایج توصیه خرید و فروش نیستند."

// qvtBoundaries restates the pilot contract next to the data so the UI can
// never "forget" it without dropping the field.
var qvtBoundaries = gin.H{
	"axes_independent":      "Q و V و T سه محور مستقل‌اند — هیچ امتیاز کل از جمع سه محور تولید نمی‌شود",
	"no_renormalization":    "وزن مفقود بازتوزیع نمی‌شود؛ امتیاز مشاهده‌شده هرگز بر مبنای پوشش نرمال نمی‌شود",
	"no_final_rank":         "شرکت‌ها بر اساس امتیاز مشاهده‌شده به‌عنوان رتبه نهایی سرمایه‌گذاری مرتب نمی‌شوند؛ پوشش بین شرکت‌ها متفاوت است",
	"independent_systems":   "Data Confidence و Risk Gate مستقل‌اند و تا اجرای واقعی «ارزیابی نشده» می‌مانند",
	"exploratory_only":      "این خروجی آزمایشی است و سیگنال خرید/فروش نیست",
	"historical_strict":     "خروجی بدون شواهد PIT معتبر به‌عنوان بک‌تست پذیرفته نمی‌شود (pit_status: collected_at_bounded)",
}

// qvtAxisMaxWeight carries each axis's target weight so the UI renders
// «X از ۴۰» instead of implying completeness.
var qvtAxisMaxWeight = gin.H{"quality": 40.0, "valuation": 35.0, "timing": 25.0}

type qvtBundle struct {
	dir             string
	qPath, vPath, t string
	qMod, vMod, tMod time.Time
	Q, V, T         map[string]any
}

func qvtArtifactDir() string {
	if d := strings.TrimSpace(os.Getenv("QVT_V2_ARTIFACT_DIR")); d != "" {
		return d
	}
	// go-app CWD (go run / exe in go-app/) first, then repo-root CWD.
	candidates := []string{
		filepath.Join("..", "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output"),
		filepath.Join("canonical_postgres_v1_2_1", "analytics_canonical_v1", "output"),
	}
	for _, c := range candidates {
		if st, err := os.Stat(filepath.Join(c, "v2_t_pilot.json")); err == nil && !st.IsDir() {
			return c
		}
	}
	return candidates[0]
}

func qvtReadDoc(path string) (map[string]any, time.Time, error) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, time.Time{}, err
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, time.Time{}, err
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, time.Time{}, fmt.Errorf("bad json in %s: %w", filepath.Base(path), err)
	}
	return doc, st.ModTime().UTC(), nil
}

func qvtLoadBundle(dir string) (*qvtBundle, error) {
	b := &qvtBundle{dir: dir}
	paths := []struct {
		p    *string
		m    *time.Time
		name string
	}{
		{&b.qPath, &b.qMod, "v2_q_observed_report.json"},
		{&b.vPath, &b.vMod, "v2_value_pilot.json"},
		{&b.t, &b.tMod, "v2_t_pilot.json"},
	}
	for _, f := range paths {
		full := filepath.Join(dir, f.name)
		doc, mod, err := qvtReadDoc(full)
		if err != nil {
			return nil, fmt.Errorf("آرتیفکت‌های پایلوت QVT V2 در دسترس نیستند — خروجی واقعی یافت نشد و هیچ داده نمونه‌ای نمایش داده نمی‌شود (فایل %s در %s: %v)", f.name, dir, err)
		}
		*f.p = full
		*f.m = mod
		switch f.name {
		case "v2_q_observed_report.json":
			b.Q = doc
		case "v2_value_pilot.json":
			b.V = doc
		default:
			b.T = doc
		}
	}
	return b, nil
}

// qvtParseInstant accepts the two artifact formats: RFC3339
// ("2026-10-08T23:59:00+00:00") and the Q report's space-separated
// "2026-10-08 23:59:00+00:00".
func qvtParseInstant(s string) (time.Time, error) {
	s = strings.TrimSpace(s)
	for _, layout := range []string{time.RFC3339, "2006-01-02 15:04:05Z07:00", "2006-01-02T15:04:05Z07:00"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t.UTC(), nil
		}
	}
	return time.Time{}, fmt.Errorf("unparseable instant %q", s)
}

// qvtCheckConsistency enforces the mission gate: the three artifacts must
// describe the same snapshot instant and the same companies before merging.
func qvtCheckConsistency(b *qvtBundle) (string, string, []string) {
	var problems []string
	qAsOf, _ := b.Q["as_of"].(string)
	vAsOf, _ := b.V["as_of"].(string)
	tAsOf, _ := b.T["as_of"].(string)
	vCut, _ := b.V["cutoff"].(string)
	tCut, _ := b.T["cutoff"].(string)

	instants := []struct {
		label, raw string
	}{
		{"q.as_of", qAsOf},
		{"v.cutoff", vCut},
		{"t.cutoff", tCut},
	}
	var base time.Time
	for _, i := range instants {
		t, err := qvtParseInstant(i.raw)
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s غیرقابل تفسیر است: %q", i.label, i.raw))
			continue
		}
		if !base.IsZero() && !t.Equal(base) {
			problems = append(problems, fmt.Sprintf("%s (%s) با%s (%s) یکی نیست", i.label, i.raw, instants[0].label, instants[0].raw))
		}
		if base.IsZero() {
			base = t
		}
	}
	if vAsOf != tAsOf {
		problems = append(problems, fmt.Sprintf("v.as_of (%s) با t.as_of (%s) یکی نیست", vAsOf, tAsOf))
	}
	if !base.IsZero() && base.Format("2006-01-02") != vAsOf {
		problems = append(problems, fmt.Sprintf("تاریخ snapshot (%s) با cutoff (%s) هم‌خوان نیست", vAsOf, base.Format("2006-01-02")))
	}
	return vAsOf, vCut, problems
}

// qvtCompanies pulls the per-company maps out of an axis document, walking
// the pilot nesting (v_observed_report / t_observed_report).
func qvtCompanies(doc map[string]any, nesting string) map[string]any {
	node := any(doc)
	if nesting != "" {
		next, ok := node.(map[string]any)[nesting]
		if !ok {
			return map[string]any{}
		}
		node = next
	}
	m, _ := node.(map[string]any)["companies"].(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

func qvtStr(m map[string]any, key string) string {
	s, _ := m[key].(string)
	return s
}

func qvtFloat(m map[string]any, key string) (float64, bool) {
	f, ok := m[key].(float64)
	return f, ok
}

// qvtNestedStr reads m[k1][k2]... as a string, "" when any hop is missing.
func qvtNestedStr(m map[string]any, keys ...string) string {
	node := any(m)
	for _, k := range keys {
		next, ok := node.(map[string]any)[k]
		if !ok {
			return ""
		}
		node = next
	}
	s, _ := node.(string)
	return s
}

func qvtStrSlice(m map[string]any, keys ...string) []string {
	node := any(m)
	for _, k := range keys {
		next, ok := node.(map[string]any)[k]
		if !ok {
			return nil
		}
		node = next
	}
	arr, ok := node.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(arr))
	for _, v := range arr {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// qvtAxisView is the display-facing summary of one axis for one company.
// It carries the axis's own points and covered weight next to the target
// weight, so the UI always shows «X از ۲۵» with real coverage — never a
// completed score.
type qvtAxisView struct {
	Present              bool     `json:"present"`
	Points               *float64 `json:"points"`
	CoveredWeight        *float64 `json:"covered_weight"`
	MaxWeight            float64  `json:"max_weight"`
	CoverageRatio        *float64 `json:"coverage_ratio"`
	CoverageThresholdMet *bool    `json:"coverage_threshold_met"`
	PilotEligible        bool     `json:"pilot_eligible"`
	// EligibilityKnown is false for rows that carry no eligibility verdict at
	// all (Q's family_out_of_scope rows) — the UI renders «خارج از دامنه»,
	// never a silent "not eligible".
	EligibilityKnown     bool     `json:"eligibility_known"`
	EssentialMissing     []string `json:"essential_missing,omitempty"`
	AggregationStatus    string   `json:"aggregation_status,omitempty"`
	ScopeReason          string   `json:"scope_reason,omitempty"`
	DataConfidenceStatus string   `json:"data_confidence_status,omitempty"`
	RiskGateStatus       string   `json:"risk_gate_status,omitempty"`
	FinancialWarnings    []string `json:"financial_warnings,omitempty"`
	TradingWarnings      []string `json:"trading_warnings,omitempty"`
	NWarnings            int      `json:"n_warnings"`
}

func qvtAxisViewFrom(cm map[string]any, pointsKey string, maxWeight float64) *qvtAxisView {
	v := &qvtAxisView{Present: cm != nil, MaxWeight: maxWeight}
	if cm == nil {
		return v
	}
	if f, ok := qvtFloat(cm, pointsKey); ok {
		v.Points = &f
	}
	if f, ok := qvtFloat(cm, "covered_weight"); ok {
		v.CoveredWeight = &f
	}
	if f, ok := qvtFloat(cm, "coverage_ratio"); ok {
		v.CoverageRatio = &f
	}
	if b, ok := cm["coverage_threshold_met"].(bool); ok {
		v.CoverageThresholdMet = &b
	}
	if b, ok := cm["pilot_eligible"].(bool); ok {
		v.PilotEligible = b
		v.EligibilityKnown = true
	}
	v.EssentialMissing = qvtStrSlice(cm, "essential_status", "missing")
	v.AggregationStatus = qvtStr(cm, "aggregation_status")
	v.ScopeReason = qvtStr(cm, "reason")
	v.DataConfidenceStatus = qvtNestedStr(cm, "data_confidence", "status")
	v.RiskGateStatus = qvtNestedStr(cm, "risk_gate", "status")
	if s := qvtStrSlice(cm, "risk_gate", "financial_warnings"); len(s) > 0 {
		v.FinancialWarnings = s
		v.NWarnings += len(s)
	}
	if s := qvtStrSlice(cm, "risk_gate", "trading_warnings"); len(s) > 0 {
		v.TradingWarnings = s
		v.NWarnings += len(s)
	}
	return v
}

type qvtCompanyRow struct {
	CompanyID        string        `json:"company_id"`
	Symbol           string        `json:"symbol"`
	ModelFamily      string        `json:"model_family"`
	Industry         string        `json:"industry"`
	Q                *qvtAxisView  `json:"q"`
	V                *qvtAxisView  `json:"v"`
	T                *qvtAxisView  `json:"t"`
	AllThreeEligible bool          `json:"all_three_eligible"`
	AnyEligible      bool          `json:"any_axis_eligible"`
}

// qvtCheckIdentity refuses to merge companies whose stable identity fields
// disagree across axes — the mission requires identity verification before
// combining, and a silent union would hide a broken join key.
func qvtCheckIdentity(qc, vc, tc map[string]any) []string {
	ids := map[string]bool{}
	for cid := range qc {
		ids[cid] = true
	}
	for cid := range vc {
		ids[cid] = true
	}
	for cid := range tc {
		ids[cid] = true
	}
	var conflicts []string
	for _, cid := range sortedKeys(ids) {
		fields := []string{"symbol", "model_family", "industry"}
		for _, field := range fields {
			var vals []string
			var axes []string
			for _, src := range []struct {
				axis string
				m    map[string]any
			}{{"q", qc}, {"v", vc}, {"t", tc}} {
				cm, ok := src.m[cid].(map[string]any)
				if !ok {
					continue
				}
				vals = append(vals, qvtStr(cm, field))
				axes = append(axes, src.axis)
			}
			for i := 1; i < len(vals); i++ {
				if vals[i] != vals[0] {
					conflicts = append(conflicts, fmt.Sprintf("ناسازگاری هویت شرکت %s در فیلد %s: %s=%q در مقابل %s=%q", cid, field, axes[0], vals[0], axes[i], vals[i]))
					break
				}
			}
		}
	}
	return conflicts
}

func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// GetQvtV2Report serves the merged pilot view.
//
//	GET /api/qvt-v2                  → summary rows for the table
//	GET /api/qvt-v2?company_id=<id>  → full three-axis detail for one company
func GetQvtV2Report(c *gin.Context) {
	b, err := qvtLoadBundle(qvtArtifactDir())
	if err != nil {
		c.Header("Cache-Control", "no-store")
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": err.Error()})
		return
	}

	asOf, cutoff, problems := qvtCheckConsistency(b)
	if len(problems) > 0 {
		c.Header("Cache-Control", "no-store")
		c.JSON(http.StatusConflict, gin.H{
			"error":      "اسنپ‌شات سه آرتیفکت هم‌خوان نیست — ادغام رد شد؛ هیچ داده‌ی جعلی جایگزین نمی‌شود",
			"problems":   problems,
			"disclaimer": qvtDisclaimer,
		})
		return
	}

	qc := qvtCompanies(b.Q, "")
	vc := qvtCompanies(b.V, "v_observed_report")
	tc := qvtCompanies(b.T, "t_observed_report")

	if conflicts := qvtCheckIdentity(qc, vc, tc); len(conflicts) > 0 {
		c.Header("Cache-Control", "no-store")
		c.JSON(http.StatusConflict, gin.H{
			"error":      "هویت شرکت‌ها بین محورها ناسازگار است — ادغام رد شد",
			"conflicts":  conflicts,
			"disclaimer": qvtDisclaimer,
		})
		return
	}

	if cid := strings.TrimSpace(c.Query("company_id")); cid != "" {
		qvtServeDetail(c, b, qc, vc, tc, cid, asOf, cutoff)
		return
	}
	qvtServeSummary(c, b, qc, vc, tc, asOf, cutoff)
}

func qvtServeSummary(c *gin.Context, b *qvtBundle, qc, vc, tc map[string]any, asOf, cutoff string) {
	ids := map[string]bool{}
	for cid := range qc {
		ids[cid] = true
	}
	for cid := range vc {
		ids[cid] = true
	}
	for cid := range tc {
		ids[cid] = true
	}
	cids := make([]string, 0, len(ids))
	for cid := range ids {
		cids = append(cids, cid)
	}
	sort.Strings(cids)

	rows := make([]qvtCompanyRow, 0, len(cids))
	var nQ, nV, nT, nQV, nQT, nVT, nAll, nAny int
	for _, cid := range cids {
		qcm, _ := qc[cid].(map[string]any)
		vcm, _ := vc[cid].(map[string]any)
		tcm, _ := tc[cid].(map[string]any)
		first := map[string]any{"symbol": "", "model_family": "", "industry": ""}
		for _, cm := range []map[string]any{qcm, vcm, tcm} {
			if cm == nil {
				continue
			}
			for k, v := range first {
				if v == "" {
					if s := qvtStr(cm, k); s != "" {
						first[k] = s
					}
				}
			}
		}
		q := qvtAxisViewFrom(qcm, "q_observed_points", 40.0)
		v := qvtAxisViewFrom(vcm, "v_observed_points", 35.0)
		t := qvtAxisViewFrom(tcm, "t_observed_points", 25.0)
		row := qvtCompanyRow{
			CompanyID:   cid,
			Symbol:      first["symbol"].(string),
			ModelFamily: first["model_family"].(string),
			Industry:    first["industry"].(string),
			Q:           q,
			V:           v,
			T:           t,
		}
		known := func(a *qvtAxisView) bool { return a.Present && a.EligibilityKnown }
		if known(q) && q.PilotEligible {
			nQ++
			nAny++
		}
		if known(v) && v.PilotEligible {
			nV++
			nAny++
		}
		if known(t) && t.PilotEligible {
			nT++
			nAny++
		}
		if known(q) && known(v) && q.PilotEligible && v.PilotEligible {
			nQV++
		}
		if known(q) && known(t) && q.PilotEligible && t.PilotEligible {
			nQT++
		}
		if known(v) && known(t) && v.PilotEligible && t.PilotEligible {
			nVT++
		}
		row.AllThreeEligible = known(q) && known(v) && known(t) && q.PilotEligible && v.PilotEligible && t.PilotEligible
		if row.AllThreeEligible {
			nAll++
		}
		row.AnyEligible = (known(q) && q.PilotEligible) || (known(v) && v.PilotEligible) || (known(t) && t.PilotEligible)
		if row.AnyEligible {
			nAny++
		}
		rows = append(rows, row)
	}

	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, gin.H{
		"stage":      "qvt_v2_ui_view",
		"pilot":      true,
		"disclaimer": qvtDisclaimer,
		"boundaries": qvtBoundaries,
		"as_of":      asOf,
		"cutoff":     cutoff,
		"axis_targets": gin.H{
			"quality":   40.0,
			"valuation": 35.0,
			"timing":    25.0,
		},
		"consistency": gin.H{
			"checked":            true,
			"as_of_cutoff_match": true,
			"identity_conflicts": 0,
			"companies":          len(cids),
		},
		"counts": gin.H{
			"n_total":       len(cids),
			"n_q_eligible":  nQ,
			"n_v_eligible":  nV,
			"n_t_eligible":  nT,
			"n_q_and_v":     nQV,
			"n_q_and_t":     nQT,
			"n_v_and_t":     nVT,
			"n_all_three":   nAll,
		},
		"companies": rows,
		"sources": gin.H{
			"q": gin.H{"file": filepath.Base(b.qPath), "modified_at": b.qMod.Format(time.RFC3339)},
			"v": gin.H{"file": filepath.Base(b.vPath), "modified_at": b.vMod.Format(time.RFC3339)},
			"t": gin.H{"file": filepath.Base(b.t), "modified_at": b.tMod.Format(time.RFC3339)},
		},
	})
}

func qvtServeDetail(c *gin.Context, b *qvtBundle, qc, vc, tc map[string]any, cid, asOf, cutoff string) {
	qcm, qok := qc[cid].(map[string]any)
	vcm, vok := vc[cid].(map[string]any)
	tcm, tok := tc[cid].(map[string]any)
	if !qok && !vok && !tok {
		c.Header("Cache-Control", "no-store")
		c.JSON(http.StatusNotFound, gin.H{
			"error":      "شرکتی با این شناسه در آرتیفکت‌های پایلوت یافت نشد",
			"company_id": cid,
			"disclaimer": qvtDisclaimer,
		})
		return
	}
	symbol, family, industry := "", "", ""
	for _, cm := range []map[string]any{qcm, vcm, tcm} {
		if cm == nil {
			continue
		}
		if symbol == "" {
			symbol = qvtStr(cm, "symbol")
		}
		if family == "" {
			family = qvtStr(cm, "model_family")
		}
		if industry == "" {
			industry = qvtStr(cm, "industry")
		}
	}

	var qAny, vAny, tAny any
	if qok {
		qAny = any(qcm)
	}
	if vok {
		vAny = any(vcm)
	}
	if tok {
		tAny = any(tcm)
	}

	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, gin.H{
		"stage":      "qvt_v2_ui_detail",
		"pilot":      true,
		"disclaimer": qvtDisclaimer,
		"boundaries": qvtBoundaries,
		"as_of":      asOf,
		"cutoff":     cutoff,
		"company": gin.H{
			"company_id":   cid,
			"symbol":       symbol,
			"model_family": family,
			"industry":     industry,
			"axes": gin.H{
				"q": qAny,
				"v": vAny,
				"t": tAny,
			},
			"axis_max_weights": qvtAxisMaxWeight,
		},
		"weight_tables": gin.H{
			"q": b.Q["weight_table"],
			"v": b.V["weight_tables"],
			"t": b.T["weight_tables"],
		},
		"policy": gin.H{
			"q": b.Q["policy"],
		},
	})
}
