package qvt

// Discovery view for the QVT V2 pilot — read-only, artifact files only.
//
// «کشف فرصت‌ها»: turns the merged pilot snapshot into an honest candidate
// list. Four discovery modes over the SAME triple-eligible universe:
//
//	balanced — transparent Pareto dominance layers, computed ONLY inside
//	           comparable groups (same model_family + industry + identical
//	           scored-factor set on each of the three axes). Groups with
//	           fewer than 5 comparable members get NO balanced ranking.
//	quality / value / timing — display order by that axis's observed
//	           points, annotated with the within-group rank; the global
//	           order is explicitly a display order, never a valid
//	           cross-industry fundamental rank.
//
// Hard boundaries (identical to report.go):
//   - artifact file reads only for scores/coverage/warnings; the ONLY
//     database touch is the read-only price-freshness verification
//     (market.price_observations, default_transaction_read_only=on session)
//     documented in pricecheck.go — no writes of any kind
//   - no Q+V+T sum, no total-of-100, no renormalization over coverage —
//     a missing factor never becomes a zero and never helps a company
//   - identical scored-factor sets ⇒ identical covered weights, so
//     grouping by them never compares different weight coverage
//   - ordering is fully deterministic: points, then symbol (Persian-safe
//     byte order), so the same snapshot always yields the same list
//   - if artifacts are missing or the snapshot/identity gates fail, the
//     endpoint refuses loudly — no sample rows, no invented groups

import (
	"fmt"
	"net/http"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// qvtDiscoveryMinGroupSize is the mission threshold: below 5 comparable
// members a balanced ranking is declared invalid, never silently shown.
const qvtDiscoveryMinGroupSize = 5

type qvtDiscoveryMode string

const (
	discModeBalanced qvtDiscoveryMode = "balanced"
	discModeQuality  qvtDiscoveryMode = "quality"
	discModeValue    qvtDiscoveryMode = "value"
	discModeTiming   qvtDiscoveryMode = "timing"
)

var qvtDiscoveryModes = []qvtDiscoveryMode{discModeBalanced, discModeQuality, discModeValue, discModeTiming}

var qvtDiscoveryModeTitles = map[qvtDiscoveryMode]string{
	discModeBalanced: "متوازن — برتری چندمحوری با لایه‌های پارتو",
	discModeQuality:  "بنیادی قوی — اولویت Q",
	discModeValue:    "ارزنده‌تر — اولویت V",
	discModeTiming:   "ورود مناسب‌تر — اولویت T",
}

// ── extracted per-company data ───────────────────────────────────────────────

// discFactorIssue is one concrete data limitation, surfaced (never hidden):
// a factor that did not score, or a scored factor whose raw value is not valid.
type discFactorIssue struct {
	Factor string `json:"factor"`
	Kind   string `json:"kind"` // "not_included" | "raw_not_valid"
	Reason string `json:"reason,omitempty"`
}

type discAxis struct {
	Points        *float64          `json:"points"`
	CoveredWeight *float64          `json:"covered_weight"`
	CoverageRatio *float64          `json:"coverage_ratio"`
	MaxWeight     float64           `json:"max_weight"`
	ScoredFactors []string          `json:"scored_factors"`
	FactorIssues  []discFactorIssue `json:"factor_issues"`
}

type discWarnings struct {
	N         int      `json:"n"`
	Financial []string `json:"financial,omitempty"`
	Trading   []string `json:"trading,omitempty"`
}

type discCompany struct {
	CompanyID   string         `json:"company_id"`
	Symbol      string         `json:"symbol"`
	ModelFamily string         `json:"model_family"`
	Industry    string         `json:"industry"`
	Q           discAxis       `json:"q"`
	V           discAxis       `json:"v"`
	T           discAxis       `json:"t"`
	Warnings    discWarnings   `json:"warnings"`
	Confidence  discConfidence `json:"confidence"`
	RiskGate    riskGateEval   `json:"risk_gate"`
}

func discAxisFrom(cm map[string]any, pointsKey string, maxWeight float64) discAxis {
	// خالی ولی غیر-nil: پاسخ JSON هرگز factor_issues/scored_factors=null ندارد
	a := discAxis{MaxWeight: maxWeight, ScoredFactors: []string{}, FactorIssues: []discFactorIssue{}}
	if f, ok := qvtFloat(cm, pointsKey); ok {
		a.Points = &f
	}
	if f, ok := qvtFloat(cm, "covered_weight"); ok {
		a.CoveredWeight = &f
	}
	if f, ok := qvtFloat(cm, "coverage_ratio"); ok {
		a.CoverageRatio = &f
	}
	factors, _ := cm["factors"].(map[string]any)
	ids := make([]string, 0, len(factors))
	for id := range factors {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		f, _ := factors[id].(map[string]any)
		if f == nil {
			continue
		}
		included := false
		if b, ok := f["included"].(bool); ok {
			included = b
		} else if f["score"] != nil {
			included = true
		}
		if included {
			a.ScoredFactors = append(a.ScoredFactors, id)
			if rs := qvtStr(f, "raw_status"); rs != "" && rs != "valid" {
				a.FactorIssues = append(a.FactorIssues, discFactorIssue{
					Factor: id, Kind: "raw_not_valid",
					Reason: firstNonEmpty(qvtStr(f, "not_included_reason"), "raw_status: "+rs),
				})
			}
			continue
		}
		a.FactorIssues = append(a.FactorIssues, discFactorIssue{
			Factor: id, Kind: "not_included",
			Reason: firstNonEmpty(qvtStr(f, "not_included_reason"), qvtStr(f, "raw_status")),
		})
	}
	return a
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}

func discWarningsFrom(cm map[string]any) (fin, trd []string) {
	fin = qvtStrSlice(cm, "risk_gate", "financial_warnings")
	trd = qvtStrSlice(cm, "risk_gate", "trading_warnings")
	return fin, trd
}

// discExtractCompanies extracts the discovery universe: exactly the companies
// that are known-eligible on all three axes in this snapshot. nAll is the
// total company count across the three artifacts (for honest context).
// Confidence/RiskGate are attached later by discAttachEvaluations, after the
// independent price checks are known — the balanced mode needs only points.
func discExtractCompanies(qc, vc, tc map[string]any) (companies []*discCompany, nAll int) {
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
	nAll = len(ids)
	cids := make([]string, 0, len(ids))
	for cid := range ids {
		cids = append(cids, cid)
	}
	sort.Strings(cids)

	for _, cid := range cids {
		qcm, _ := qc[cid].(map[string]any)
		vcm, _ := vc[cid].(map[string]any)
		tcm, _ := tc[cid].(map[string]any)
		eligible := func(cm map[string]any) bool {
			if cm == nil {
				return false
			}
			b, ok := cm["pilot_eligible"].(bool)
			return ok && b
		}
		if !(eligible(qcm) && eligible(vcm) && eligible(tcm)) {
			continue
		}
		dc := &discCompany{
			CompanyID:   cid,
			Symbol:      firstNonEmpty(qvtStr(qcm, "symbol"), qvtStr(vcm, "symbol"), qvtStr(tcm, "symbol")),
			ModelFamily: firstNonEmpty(qvtStr(qcm, "model_family"), qvtStr(vcm, "model_family"), qvtStr(tcm, "model_family")),
			Industry:    firstNonEmpty(qvtStr(qcm, "industry"), qvtStr(vcm, "industry"), qvtStr(tcm, "industry")),
			Q:           discAxisFrom(qcm, "q_observed_points", 40.0),
			V:           discAxisFrom(vcm, "v_observed_points", 35.0),
			T:           discAxisFrom(tcm, "t_observed_points", 25.0),
		}
		for _, cm := range []map[string]any{qcm, vcm, tcm} {
			fin, trd := discWarningsFrom(cm)
			if len(fin) > 0 {
				dc.Warnings.Financial = append(dc.Warnings.Financial, fin...)
			}
			if len(trd) > 0 {
				dc.Warnings.Trading = append(dc.Warnings.Trading, trd...)
			}
		}
		dc.Warnings.N = len(dc.Warnings.Financial) + len(dc.Warnings.Trading)
		companies = append(companies, dc)
	}
	return companies, nAll
}

// discAttachEvaluations confidence و دروازه ریسک هر شرکت را با حکم مستقل
// قیمت (برای B1) کامل می‌کند — بعد از این مرحله شرکت‌ها کامل‌اند.
func discAttachEvaluations(companies []*discCompany, qc, vc, tc map[string]any, px map[string]*priceCheck) {
	for _, dc := range companies {
		qcm, _ := qc[dc.CompanyID].(map[string]any)
		vcm, _ := vc[dc.CompanyID].(map[string]any)
		tcm, _ := tc[dc.CompanyID].(map[string]any)
		dc.Confidence = discConfidenceFor(qcm, vcm, tcm)
		dc.RiskGate = riskGateFor(dc.CompanyID, qcm, vcm, tcm, px)
	}
}

// cidsNeedingPriceCheck شرکت‌هایی که کنترل مستقل قیمت لازم دارند. گام ۲-ک-۹:
// این مجموعه به همهٔ شرکت‌های جامعهٔ سه‌محوری گسترش یافت تا «تاریخ دقیق آخرین
// قیمت معتبر و سن آن» برای هر نامزد و برای صداقت زمانی snapshot در دست باشد
// (پیش‌تر فقط اعضای فهرست کوتاه + هشدار stale_price کنترل می‌شدند). کوئری
// یک کوئری تجمیعی روی همهٔ شناسه‌هاست؛ هزینه‌اش ناچیز و فقط‌خواندنی است.
func cidsNeedingPriceCheck(companies []*discCompany, balanced discModeResult) []string {
	seen := map[string]bool{}
	var out []string
	add := func(cid string) {
		if !seen[cid] {
			seen[cid] = true
			out = append(out, cid)
		}
	}
	for _, dc := range companies {
		add(dc.CompanyID)
	}
	for _, r := range balanced.Rows {
		if r.Comparability == "comparable" {
			add(r.CompanyID)
		}
	}
	return out
}

// ── فهرست کوتاه کاربردی (گام ۲-ط-۱) ─────────────────────────────────────────

// shortlistEntry یک نامزد اولویت‌دار: شرکت کامل (امتیازها/پوشش/هشدارها/
// اطمینان داده/دروازه ریسک) + جایگاه لایه پارتو + کنترل مستقل تازگی قیمت.
type shortlistEntry struct {
	*discCompany
	ParetoLayer *int        `json:"pareto_layer"`
	GroupRank   *int        `json:"group_rank,omitempty"`
	GroupSize   int         `json:"group_size"`
	GroupLabel  string      `json:"group_label"`
	Reason      string      `json:"reason"`
	Price       *priceCheck `json:"price_freshness"`

	// وضعیت اعتبارسنجی اقتصادی مستقل (۲-ک-۲) — از overlay متصل به همین
	// snapshot می‌آید؛ مستقل از امتیازها و Risk Gate و بدون هیچ امتیازی
	ValidationStatus      string `json:"validation_status,omitempty"`
	ValidationStatusLabel string `json:"validation_status_label,omitempty"`
	ValidationNeedsReview bool   `json:"validation_needs_review"`
	ValidationReason      string `json:"validation_reason,omitempty"`
}

// shortlistGroup یک گروه مقایسه‌پذیر معتبر — صنعت واقعی از داده، نه گروه
// بازتعریف‌شده؛ اگر در snapshot بعدی گروه‌ها تغییر کنند همین ساختار با
// داده جدید پر می‌شود.
type shortlistGroup struct {
	GroupLabel  string           `json:"group_label"`
	Industry    string           `json:"industry"`
	ModelFamily string           `json:"model_family"`
	GroupSize   int              `json:"group_size"`
	Entries     []shortlistEntry `json:"entries"`
}

// discShortlistFrom فهرست کوتاه را از ردیف‌های حالت متوازن می‌سازد: فقط
// ردیف‌های comparable گروه‌های معتبر؛ اعضای لایه ۱ ابتدا (ترتیب همان
// تولیدشده توسط discBuildBalanced: لایه صعودی سپس نماد).
func discShortlistFrom(balanced discModeResult, companies []*discCompany, px map[string]*priceCheck) (groups []*shortlistGroup, nCompanies int) {
	byCid := map[string]*discCompany{}
	for _, dc := range companies {
		byCid[dc.CompanyID] = dc
	}
	groups = []*shortlistGroup{}
	byLabel := map[string]*shortlistGroup{}
	var labels []string
	for _, r := range balanced.Rows {
		if r.Comparability != "comparable" || r.ParetoLayer == nil {
			continue
		}
		dc := byCid[r.CompanyID]
		if dc == nil {
			continue
		}
		g := byLabel[r.GroupLabel]
		if g == nil {
			g = &shortlistGroup{
				GroupLabel: r.GroupLabel, Industry: dc.Industry,
				ModelFamily: dc.ModelFamily, GroupSize: r.GroupSize,
				Entries: []shortlistEntry{},
			}
			byLabel[r.GroupLabel] = g
			labels = append(labels, r.GroupLabel)
		}
		g.Entries = append(g.Entries, shortlistEntry{
			discCompany: dc, ParetoLayer: r.ParetoLayer, GroupRank: r.GroupRank,
			GroupSize: r.GroupSize, GroupLabel: r.GroupLabel,
			Reason: r.Reason, Price: px[r.CompanyID],
		})
		nCompanies++
	}
	sort.Strings(labels)
	for _, lbl := range labels {
		groups = append(groups, byLabel[lbl])
	}
	return groups, nCompanies
}

var qvtShortlistRules = gin.H{
	"basis":           "فقط گروه‌های مقایسه‌پذیر معتبر حالت متوازن: خانواده + صنعت واقعی + مجموعه فاکتورهای امتیازگرفته یکسان در هر سه محور + حداقل ۵ همتا؛ هیچ گروه مصنوعی برای پر کردن فهرست ساخته نمی‌شود",
	"order":           "اعضای لایه ۱ پارتو ابتدا نمایش داده می‌شوند؛ داخل هر گروه مرتب‌سازی بر اساس Q یا V یا T فقط بین همان اعضا و فقط به‌عنوان ترتیب نمایش مجاز است",
	"not_a_signal":    "لایه ۱ پارتو فقط یعنی هیچ همتای گروهی بر آن عضو غالب نیست — سیگنال خرید، بهترین سهم بازار یا امتیاز نهایی نیست؛ Data Confidence و Risk Gate هم حق تغییر امتیازها یا لایه‌ها را ندارند",
	"layers":          "لایه‌ها از غلبه پارتو روی سه امتیاز مشاهده‌شده داخل گروه ساخته می‌شوند؛ امتیاز مفقود هرگز صفر فرض نمی‌شود و شرکت بدون امتیاز کامل به مقایسه وارد نمی‌شود",
	"price_freshness": "تاریخ آخرین قیمت از منبع مستقل market.price_observations در همان پنجره PIT آرتیفکت (فقط‌خواندنی) کنترل می‌شود؛ سن تقویمی با سیاست تازگی آرتیفکت سنجیده می‌شود و اگر منبع در دسترس نباشد صریح گفته می‌شود — هیچ عددی جایگزین نمی‌شود",
	"non_ranked":      "شرکت‌های فاقد رتبه متوازن (گروه کمتر از ۵ همتا) در جدول اصلی صفحه با دلیل دقیق نامقایسه‌پذیری قابل مشاهده‌اند؛ از فهرست کوتاه حذف نشده‌اند — فقط مبنای مقایسه معتبر ندارند",
	"no_score_change": "این فهرست هیچ امتیاز جدیدی نمی‌سازد؛ Q/V/T مشاهده‌شده و پوشش واقعی همان آرتیفکت‌هاست",
}

// ── comparable groups ────────────────────────────────────────────────────────

// discGroupKey: same family + same industry + identical scored-factor set
// per relevant axis. Identical scored sets mean identical covered weights,
// so companies compared inside a group really carry the same weight basis.
func discGroupKey(dc *discCompany, mode qvtDiscoveryMode) string {
	sets := map[qvtDiscoveryMode][][]string{
		discModeBalanced: {dc.Q.ScoredFactors, dc.V.ScoredFactors, dc.T.ScoredFactors},
		discModeQuality:  {dc.Q.ScoredFactors},
		discModeValue:    {dc.V.ScoredFactors},
		discModeTiming:   {dc.T.ScoredFactors},
	}
	parts := []string{dc.ModelFamily, dc.Industry}
	for _, s := range sets[mode] {
		parts = append(parts, strings.Join(s, ","))
	}
	return strings.Join(parts, "|")
}

func discGroupLabel(dc *discCompany) string {
	return fmt.Sprintf("صنعت «%s» / خانواده %s", dc.Industry, dc.ModelFamily)
}

// ── Pareto dominance ─────────────────────────────────────────────────────────

type discScores struct{ q, v, t float64 }

// discDominates: a dominates b iff a is not worse on all three observed
// scores and strictly better on at least one. Pure, deterministic, and
// only ever applied between members of the same comparable group.
func discDominates(a, b discScores) bool {
	return a.q >= b.q && a.v >= b.v && a.t >= b.t &&
		(a.q > b.q || a.v > b.v || a.t > b.t)
}

// discParetoLayers peels non-dominated fronts; layer 1 = not dominated by
// any group member. Returns one layer number per member, in member order.
func discParetoLayers(members []discScores) []int {
	n := len(members)
	layer := make([]int, n)
	alive := make([]bool, n)
	for i := range alive {
		alive[i] = true
	}
	current := 0
	for done := 0; done < n; {
		current++
		var front []int
		for i := 0; i < n; i++ {
			if !alive[i] {
				continue
			}
			dominated := false
			for j := 0; j < n; j++ {
				if j != i && alive[j] && discDominates(members[j], members[i]) {
					dominated = true
					break
				}
			}
			if !dominated {
				front = append(front, i)
			}
		}
		for _, i := range front {
			layer[i] = current
			alive[i] = false
			done++
		}
		if len(front) == 0 { // defensive: cannot happen with total order peeling
			for i := range alive {
				if alive[i] {
					layer[i] = current
					done++
				}
			}
			break
		}
	}
	return layer
}

// ── per-mode rows ────────────────────────────────────────────────────────────

type discModeRow struct {
	CompanyID     string `json:"company_id"`
	DisplayOrder  int    `json:"display_order"`
	Comparability string `json:"comparability"` // comparable | small_group | missing_scores
	ParetoLayer   *int   `json:"pareto_layer,omitempty"`
	GroupRank     *int   `json:"group_rank,omitempty"`
	GroupSize     int    `json:"group_size"`
	GroupValid    bool   `json:"group_valid"`
	GroupLabel    string `json:"group_label"`
	Reason        string `json:"reason"`
}

type discModeCounts struct {
	Companies   int `json:"companies"`
	Ranked      int `json:"ranked"`
	NotRanked   int `json:"not_ranked"`
	GroupsTotal int `json:"groups_total"`
	GroupsValid int `json:"groups_valid"`
}

type discModeResult struct {
	Mode      string         `json:"mode"`
	Title     string         `json:"title"`
	OrderNote string         `json:"order_note"`
	Counts    discModeCounts `json:"counts"`
	Rows      []discModeRow  `json:"rows"`
}

type discMember struct {
	dc      *discCompany
	scores  discScores
	missing bool // at least one axis has no observed points
}

func discMembers(group []*discCompany) []discMember {
	ms := make([]discMember, 0, len(group))
	for _, dc := range group {
		m := discMember{dc: dc}
		if dc.Q.Points == nil || dc.V.Points == nil || dc.T.Points == nil {
			m.missing = true
		} else {
			m.scores = discScores{*dc.Q.Points, *dc.V.Points, *dc.T.Points}
		}
		ms = append(ms, m)
	}
	return ms
}

// discAxisPoints picks the observed points for the mode's single axis.
func discAxisPoints(dc *discCompany, mode qvtDiscoveryMode) *float64 {
	switch mode {
	case discModeQuality:
		return dc.Q.Points
	case discModeValue:
		return dc.V.Points
	case discModeTiming:
		return dc.T.Points
	}
	return nil
}

var discAxisNames = map[qvtDiscoveryMode]string{
	discModeQuality: "Q",
	discModeValue:   "V",
	discModeTiming:  "T",
}

func discBuildBalanced(companies []*discCompany) discModeResult {
	res := discModeResult{
		Mode:  string(discModeBalanced),
		Title: qvtDiscoveryModeTitles[discModeBalanced],
		OrderNote: "ترتیب نمایش: ابتدا گروه‌های دارای مقایسه معتبر (حداقل ۵ همتای قابل‌مقایسه) با لایه پارتو صعودی و سپس نماد؛ " +
			"لایه‌های پارتو فقط ابزار کشف‌اند — نه امتیاز نهایی، نه رتبه خرید، نه ارزیابی ریسک.",
	}
	groups := map[string][]*discCompany{}
	var keys []string
	for _, dc := range companies {
		k := discGroupKey(dc, discModeBalanced)
		if _, ok := groups[k]; !ok {
			keys = append(keys, k)
		}
		groups[k] = append(groups[k], dc)
	}
	sort.Strings(keys)

	type orderedGroup struct {
		key     string
		members []*discCompany
		valid   bool
	}
	var validGroups, invalidGroups []orderedGroup
	for _, k := range keys {
		g := groups[k]
		sort.Slice(g, func(i, j int) bool { return g[i].Symbol < g[j].Symbol })
		og := orderedGroup{key: k, members: g, valid: len(g) >= qvtDiscoveryMinGroupSize}
		if og.valid {
			validGroups = append(validGroups, og)
		} else {
			invalidGroups = append(invalidGroups, og)
		}
	}
	// deterministic group order: by first member's industry+family label
	byLabel := func(a, b orderedGroup) bool {
		return discGroupLabel(a.members[0]) < discGroupLabel(b.members[0])
	}
	sort.SliceStable(validGroups, func(i, j int) bool { return byLabel(validGroups[i], validGroups[j]) })
	sort.SliceStable(invalidGroups, func(i, j int) bool { return byLabel(invalidGroups[i], invalidGroups[j]) })

	res.Counts.Companies = len(companies)
	res.Counts.GroupsTotal = len(validGroups) + len(invalidGroups)
	res.Counts.GroupsValid = len(validGroups)

	order := 0
	for _, g := range validGroups {
		ms := discMembers(g.members)
		// missing-score members cannot enter dominance; peel the rest
		var sc []discScores
		idx := map[int]int{} // member index → scores index
		for i, m := range ms {
			if !m.missing {
				idx[i] = len(sc)
				sc = append(sc, m.scores)
			}
		}
		layers := make([]int, len(ms))
		if len(sc) > 0 {
			ls := discParetoLayers(sc)
			for i, si := range idx {
				layers[i] = ls[si]
			}
		}
		// layer asc, then symbol; missing-score members last (no layer)
		idxs := make([]int, len(ms))
		for i := range idxs {
			idxs[i] = i
		}
		sort.SliceStable(idxs, func(a, b int) bool {
			ma, mb := ms[idxs[a]], ms[idxs[b]]
			switch {
			case ma.missing != mb.missing:
				return !ma.missing
			case !ma.missing && layers[idxs[a]] != layers[idxs[b]]:
				return layers[idxs[a]] < layers[idxs[b]]
			}
			return ma.dc.Symbol < mb.dc.Symbol
		})
		for _, i := range idxs {
			m := ms[i]
			row := discModeRow{
				CompanyID:  m.dc.CompanyID,
				GroupSize:  len(g.members),
				GroupValid: true,
				GroupLabel: discGroupLabel(m.dc),
			}
			if m.missing {
				row.Comparability = "missing_scores"
				row.Reason = "امتیاز مشاهده‌شده در دسترس نیست — شرکت در مقایسه پارتو وارد نشده و هیچ جایگزینی برای امتیاز مفقود ساخته نشد"
			} else {
				l := layers[i]
				row.ParetoLayer = &l
				row.Comparability = "comparable"
				row.Reason = fmt.Sprintf("لایه پارتو %d در گروه مقایسه‌پذیر «%s» (%d همتا با پوشش فاکتورهای امتیازگرفته یکسان در هر سه محور)", l, m.dc.Industry, len(g.members))
				if l == 1 {
					row.Reason += " — هیچ همتای گروهی در هیچ‌یک از سه محور بر آن غالب نیست"
				}
				res.Counts.Ranked++
			}
			row.DisplayOrder = order
			order++
			res.Rows = append(res.Rows, row)
		}
	}
	for _, g := range invalidGroups {
		for _, m := range discMembers(g.members) {
			row := discModeRow{
				CompanyID:  m.dc.CompanyID,
				GroupSize:  len(g.members),
				GroupValid: false,
				GroupLabel: discGroupLabel(m.dc),
				Reason: fmt.Sprintf("گروه مقایسه «%s» تنها %d عضو دارد (حداقل ۵ عضو لازم است) — رتبه‌بندی متوازن برای این گروه صادر نشد؛ شرکت فقط نمایش داده می‌شود",
					m.dc.Industry, len(g.members)),
			}
			if m.missing {
				row.Comparability = "missing_scores"
				row.Reason = "امتیاز مشاهده‌شده در دسترس نیست و گروه مقایسه نیز کمتر از حداقل اعضاست — هیچ رتبه‌ای صادر نشد"
			} else {
				row.Comparability = "small_group"
			}
			row.DisplayOrder = order
			order++
			res.Rows = append(res.Rows, row)
		}
		res.Counts.NotRanked += len(g.members)
	}
	// valid-group members that could not enter dominance (missing scores)
	res.Counts.NotRanked += res.Counts.Companies - res.Counts.Ranked - res.Counts.NotRanked
	return res
}

// discBuildSingleAxis orders by one axis's observed points (display order,
// never a cross-group fundamental rank) and annotates the within-group rank.
func discBuildSingleAxis(companies []*discCompany, mode qvtDiscoveryMode) discModeResult {
	axis := discAxisNames[mode]
	res := discModeResult{
		Mode:  string(mode),
		Title: qvtDiscoveryModeTitles[mode],
		OrderNote: fmt.Sprintf("ترتیب نمایش بر اساس امتیاز مشاهده‌شده %s (نزولی) است؛ این ترتیب بین گروه‌های پوشش/صنعت متفاوت «رتبه بنیادی معتبر» نیست — "+
			"رتبه معتبر فقط داخل گروه مقایسه‌پذیر (خانواده + صنعت + پوشش فاکتور یکسان) تعریف می‌شود و محدودیت‌های داده هر شرکت همراه آن نمایش داده می‌شود.", axis),
	}
	groups := map[string][]*discCompany{}
	var keys []string
	for _, dc := range companies {
		k := discGroupKey(dc, mode)
		if _, ok := groups[k]; !ok {
			keys = append(keys, k)
		}
		groups[k] = append(groups[k], dc)
	}
	sort.Strings(keys)

	groupRank := map[string]int{}
	groupSize := map[string]int{}
	groupValid := map[string]bool{}
	for _, k := range keys {
		g := groups[k]
		sort.SliceStable(g, func(i, j int) bool {
			pi, pj := discAxisPoints(g[i], mode), discAxisPoints(g[j], mode)
			switch {
			case pi != nil && pj != nil:
				if *pi != *pj {
					return *pi > *pj
				}
				return g[i].Symbol < g[j].Symbol
			case pi != nil:
				return true
			case pj != nil:
				return false
			}
			return g[i].Symbol < g[j].Symbol
		})
		groupSize[k] = len(g)
		groupValid[k] = len(g) >= qvtDiscoveryMinGroupSize
		r := 0
		for _, m := range g {
			if discAxisPoints(m, mode) != nil {
				r++
				groupRank[m.CompanyID] = r
			}
		}
	}

	res.Counts.Companies = len(companies)
	res.Counts.GroupsTotal = len(keys)
	for _, v := range groupValid {
		if v {
			res.Counts.GroupsValid++
		}
	}

	ordered := make([]*discCompany, len(companies))
	copy(ordered, companies)
	sort.SliceStable(ordered, func(i, j int) bool {
		pi, pj := discAxisPoints(ordered[i], mode), discAxisPoints(ordered[j], mode)
		switch {
		case pi != nil && pj != nil:
			if *pi != *pj {
				return *pi > *pj
			}
			return ordered[i].Symbol < ordered[j].Symbol
		case pi != nil:
			return true
		case pj != nil:
			return false
		}
		return ordered[i].Symbol < ordered[j].Symbol
	})

	order := 0
	for _, dc := range ordered {
		k := discGroupKey(dc, mode)
		row := discModeRow{
			CompanyID:  dc.CompanyID,
			GroupSize:  groupSize[k],
			GroupValid: groupValid[k],
			GroupLabel: discGroupLabel(dc),
		}
		if p := discAxisPoints(dc, mode); p != nil {
			r := groupRank[dc.CompanyID]
			row.GroupRank = &r
			row.Comparability = "comparable"
			row.Reason = fmt.Sprintf("رتبه %d در گروه مقایسه‌پذیر «%s» (%d همتا با پوشش %s یکسان) بر اساس امتیاز مشاهده‌شده %s = %.2f", r, dc.Industry, groupSize[k], axis, axis, *p)
			if !groupValid[k] {
				row.Reason += fmt.Sprintf(" — گروه کمتر از %d همتاست؛ رتبه گروه صرفاً اطلاعی است", qvtDiscoveryMinGroupSize)
				row.Comparability = "small_group"
			}
			res.Counts.Ranked++
		} else {
			row.Comparability = "missing_scores"
			row.Reason = fmt.Sprintf("امتیاز مشاهده‌شده %s در دسترس ندارد — انتهای فهرست نمایش داده می‌شود و هیچ مقدار جایگزینی برای آن ساخته نشد", axis)
			res.Counts.NotRanked++
		}
		row.DisplayOrder = order
		order++
		res.Rows = append(res.Rows, row)
	}
	return res
}

// ── handler ──────────────────────────────────────────────────────────────────

var qvtDiscoveryRules = gin.H{
	"universe":       "فقط شرکت‌های واجد شرایط هر سه محور Q و V و T در همین snapshot؛ تعداد از داده واقعی بازشماری می‌شود",
	"group_key":      "خانواده + صنعت + مجموعه فاکتورهای امتیازگرفته (included) هر محور؛ مجموعه یکسان یعنی وزن پوشیده واقعاً یکسان است",
	"min_group_size": qvtDiscoveryMinGroupSize,
	"min_group_rule": "گروه با کمتر از ۵ عضو قابل‌مقایسه: رتبه‌بندی متوازن آن نامعتبر اعلام می‌شود و رتبه گروه در حالت‌های تک‌محوری فقط اطلاعی است؛ با ادغام صنایع یا حذف شروط فهرست مصنوعی ساخته نمی‌شود",
	"dominance":      "A بر B غالب است فقط اگر در هر سه امتیاز مشاهده‌شده کمتر نباشد و حداقل در یکی بهتر باشد؛ مقایسه فقط داخل گروه انجام می‌شود",
	"tie_break":      "امتیاز برابر → ترتیب نماد (پایدار و قطعی)؛ هیچ جمع یا میانگین ساده Q/V/T برای انتخاب بهترین ساخته نمی‌شود",
	"no_renorm":      "وزن مفقود بازتوزیع نمی‌شود؛ مفقود صفر فرض نمی‌شود؛ امتیاز مشاهده‌شده هرگز بر مبنای پوشش نرمال نمی‌شود",
	"not_a_rank":     "خروجی فقط کاندیدای بررسی بیشتر است، نه توصیه خرید؛ ترتیب نمایش سراسری در حالت‌های تک‌محوری رتبه بنیادی معتبر بین صنایع نیست",
	"warnings_kept":  "هشدارهای مالی/معاملاتی و محدودیت‌های فاکتور هر شرکت حفظ و نمایش داده می‌شود؛ نبود هشدار هرگز به معنی کم‌ریسک بودن نیست",
}

// GetQvtV2Discovery serves GET /api/qvt-v2/discovery — the «کشف فرصت‌ها» feed.
func GetQvtV2Discovery(c *gin.Context) {
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
			"error":      "اسنپ‌شات سه آرتیفکت هم‌خوان نیست — کشف فرصت‌ها رد شد؛ هیچ داده‌ی جعلی جایگزین نمی‌شود",
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
			"error":      "هویت شرکت‌ها بین محورها ناسازگار است — کشف فرصت‌ها رد شد",
			"conflicts":  conflicts,
			"disclaimer": qvtDisclaimer,
		})
		return
	}

	companies, nAll := discExtractCompanies(qc, vc, tc)

	// حالت متوازن اول ساخته می‌شود (فقط به امتیازها/پوشش نیاز دارد) تا
	// مجموعه شرکت‌های نیازمند کنترل مستقل قیمت مشخص شود: اعضای فهرست کوتاه +
	// هر شرکت دارای هشدار stale_price (قاعده B1).
	balanced := discBuildBalanced(companies)
	policy := bundlePricePolicy(b)
	asOfDate := qvtStr(b.V, "as_of")
	checkCids := cidsNeedingPriceCheck(companies, balanced)
	px, pxAvail, pxNote := priceChecksFor(checkCids, qvtStr(b.V, "cutoff"), asOfDate, policy)

	discAttachEvaluations(companies, qc, vc, tc, px)

	modes := gin.H{}
	for _, m := range qvtDiscoveryModes {
		var r discModeResult
		if m == discModeBalanced {
			r = balanced
		} else {
			r = discBuildSingleAxis(companies, m)
		}
		modes[string(m)] = r
	}
	shortlistGroups, nShort := discShortlistFrom(balanced, companies, px)
	// وضعیت اعتبارسنجی مستقل هر نامزد از overlay متصل به همین snapshot —
	// غیبت overlay یعنی «ارزیابی نشده»، هرگز «تأییدشده».
	// Entries از نوع مقدار است؛ جهش واقعی فقط با اندیس/اشاره‌گر ممکن است.
	overlays := qvtLoadOverlays(b.dir, b)
	for _, g := range shortlistGroups {
		for i := range g.Entries {
			e := &g.Entries[i]
			ovc := overlayForCompany(overlays, e.CompanyID)
			iv, ok := ovc["independent_validation"].(map[string]any)
			if !ok {
				continue
			}
			e.ValidationStatus, _ = iv["status"].(string)
			e.ValidationStatusLabel, _ = iv["status_label"].(string)
			switch e.ValidationStatus {
			case "consistent_but_not_independent", "conflicting",
				"insufficient_evidence":
				e.ValidationNeedsReview = true
			}
			if reasons, ok := iv["reasons"].([]any); ok && len(reasons) > 0 {
				e.ValidationReason, _ = reasons[0].(string)
			}
		}
	}
	// «فرصت‌های قابل بررسی بازار» (گام ۲-ک-۷): موتور ترتیبی شفاف روی همان
	// شواهد همین پاسخ (امتیازهای رسمی، پوشش، اطمینان داده، دروازه ریسک،
	// همتایان معتبر و کنترل تازگی قیمت) — هیچ منبع اضافه‌ای نمی‌خواند و
	// هیچ امتیاز جدیدی نمی‌سازد.
	opportunityBoard := buildOpportunityBoard(boardInput{
		companies: companies,
		balanced:  balanced,
		px:        px,
		overlays:  overlays,
		asOf:      asOf,
		qc:        qc,
		vc:        vc,
		tc:        tc,
		policy:    defaultBoardDecisionPolicy(),
	})

	shortlist := gin.H{
		"title":        "نامزدهای اولویت‌دار برای بررسی",
		"basis":        "شرکت‌هایی که هم واجد شرایط هر سه محورند و هم در یک گروه مقایسه‌پذیر معتبر (خانواده + صنعت + پوشش فاکتور یکسان + حداقل ۵ همتا) قرار دارند — تعداد از داده زنده محاسبه می‌شود",
		"not_a_signal": "این فهرست نامزد بررسی بیشتر است، نه توصیه خرید؛ لایه ۱ پارتو «بهترین سهم بازار» نیست و هیچ امتیاز کل یا رتبه خریدی اینجا ساخته نمی‌شود",
		"counts":       gin.H{"groups": len(shortlistGroups), "companies": nShort},
		"groups":       shortlistGroups,
		"non_ranked": gin.H{
			"n":    balanced.Counts.NotRanked,
			"note": "شرکت‌های فاقد رتبه متوازن در جدول اصلی و حالت‌های دیگر صفحه با دلیل دقیق نامقایسه‌پذیری (گروه کمتر از ۵ همتا یا امتیاز مفقود) نمایش داده می‌شوند؛ مسیر مشاهده مستقل آنها حفظ شده است",
		},
	}

	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, gin.H{
		"stage":      "qvt_v2_discovery",
		"pilot":      true,
		"disclaimer": qvtDisclaimer,
		"boundaries": qvtBoundaries,
		"as_of":      asOf,
		"cutoff":     cutoff,
		"universe": gin.H{
			"n_all_artifacts":   nAll,
			"n_triple_eligible": len(companies),
			"note":              "نمای کشف فقط روی شرکت‌های واجد شرایط هر سه محور کار می‌کند؛ نمای «همه شرکت‌ها» در همان صفحه کل ۲۷۱ شرکت را با همان قواعد نمایش می‌دهد",
		},
		"mode_rules":           qvtDiscoveryRules,
		"shortlist_rules":      qvtShortlistRules,
		"confidence_rules":     qvtConfidenceRules,
		"risk_gate_rules":      qvtRiskGateRules,
		"price_source":         priceSourceMeta(pxAvail, pxNote),
		"snapshot_consistency": snapshotConsistencyOf(b),
		"companies":            companies,
		"modes":                modes,
		"shortlist":            shortlist,
		"opportunity_board":    opportunityBoard,
		"sources": gin.H{
			"q": gin.H{"file": filepath.Base(b.qPath), "modified_at": b.qMod.Format(time.RFC3339), "sha256": b.qSHA, "as_of": qvtStr(b.Q, "as_of")},
			"v": gin.H{"file": filepath.Base(b.vPath), "modified_at": b.vMod.Format(time.RFC3339), "sha256": b.vSHA, "as_of": qvtStr(b.V, "as_of"), "cutoff": qvtStr(b.V, "cutoff")},
			"t": gin.H{"file": filepath.Base(b.t), "modified_at": b.tMod.Format(time.RFC3339), "sha256": b.tSHA, "as_of": qvtStr(b.T, "as_of"), "cutoff": qvtStr(b.T, "cutoff")},
		},
	})
}
