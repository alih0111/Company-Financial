package qvt

import (
	"sort"
	"strings"
	"time"
)

type rankMissingFactor struct {
	Factor string  `json:"factor"`
	Label  string  `json:"label"`
	Weight float64 `json:"weight"`
	Kind   string  `json:"kind"`
	Reason string  `json:"reason"`
}

type rankTimingWindow struct {
	Factor        string `json:"factor"`
	Label         string `json:"label"`
	Reference     string `json:"reference"`
	Start         string `json:"start"`
	End           string `json:"end"`
	AnchorAgeDays int    `json:"anchor_age_days"`
}

var rankFactorLabels = map[string]string{
	"roe_level": "بازده حقوق مالکانه", "margins": "حاشیهٔ سود", "leverage": "اهرم بدهی",
	"cash_conversion": "تبدیل سود به نقد", "revenue_growth": "رشد درآمد", "earnings_growth": "رشد سود",
	"earnings_quality": "کیفیت سود", "interest_coverage": "پوشش هزینهٔ مالی", "margin_trend": "روند حاشیهٔ سود",
	"roe_stability": "ثبات بازده حقوق مالکانه", "momentum_6m_rel": "اختلاف بازده با بازار، بازهٔ هدف ۶ماهه",
	"momentum_3m_rel": "اختلاف بازده با بازار، بازهٔ هدف ۳ماهه", "relative_strength_6m_sector": "اختلاف بازده با صنعت، بازهٔ هدف ۶ماهه",
	"pe": "P/E", "pb": "P/B", "ps": "P/S", "liquidity": "نقدشوندگی", "low_volatility": "نوسان",
}

func rankEvidenceAxis(axis *rankAxis, cm map[string]any) {
	axis.ScoredFactors = []string{}
	axis.MissingFactors = []rankMissingFactor{}
	factors, _ := cm["factors"].(map[string]any)
	ids := []string{}
	for id := range factors {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		f, _ := factors[id].(map[string]any)
		included, _ := f["included"].(bool)
		if included {
			axis.ScoredFactors = append(axis.ScoredFactors, id)
			continue
		}
		weight, _ := qvtFloat(f, "weight")
		kind, reason := "missing", "دادهٔ معتبر برای محاسبه موجود نیست"
		switch {
		case qvtStr(f, "implementation") == "not_implemented":
			kind, reason = "not_implemented", "این عامل هنوز پیاده‌سازی نشده است"
		case strings.HasPrefix(qvtStr(f, "not_included_reason"), "policy_excluded"):
			kind, reason = "policy_excluded", "این عامل طبق سیاست فعلی وارد امتیاز نمی‌شود"
		case qvtStr(f, "normalization_status") == "insufficient_peers":
			kind, reason = "insufficient_peers", "همتای معتبر کافی برای مقایسه موجود نیست"
		default:
			if detail := rankBlockerDetail(id, f); detail != "" {
				reason = detail
			}
		}
		label := rankFactorLabels[id]
		if label == "" {
			label = id
		}
		axis.MissingFactors = append(axis.MissingFactors, rankMissingFactor{id, label, weight, kind, reason})
	}
}

// Matching covered weights alone cannot establish matching factor identities.
func rankAttachEvidence(entries []*rankEntry, qc, vc, tc map[string]any) {
	unions := map[string]map[string]bool{}
	for _, e := range entries {
		for i, axis := range []*rankAxis{&e.Q, &e.V, &e.T} {
			cm, _ := []map[string]any{qc, vc, tc}[i][e.CompanyID].(map[string]any)
			rankEvidenceAxis(axis, cm)
			key := e.ModelFamily + string(rune('Q'+i))
			if unions[key] == nil {
				unions[key] = map[string]bool{}
			}
			for _, id := range axis.ScoredFactors {
				unions[key][id] = true
			}
		}
		e.TimingWindows = []rankTimingWindow{}
		cm, _ := tc[e.CompanyID].(map[string]any)
		factors, _ := cm["factors"].(map[string]any)
		for _, id := range []string{"momentum_3m_rel", "momentum_6m_rel", "relative_strength_6m_sector"} {
			f, _ := factors[id].(map[string]any)
			market, _ := f["market_evidence"].(map[string]any)
			window, _ := market["window"].(map[string]any)
			start, end, ref := qvtStr(window, "base_date"), qvtStr(market, "last_trade_date"), qvtStr(window, "ref_date")
			if start == "" || end == "" {
				continue
			}
			a, errA := time.Parse("2006-01-02", start)
			r, errR := time.Parse("2006-01-02", ref)
			age := 0
			if errA == nil && errR == nil {
				age = int(r.Sub(a).Hours() / 24)
			}
			e.TimingWindows = append(e.TimingWindows, rankTimingWindow{id, rankFactorLabels[id], ref, start, end, age})
		}
	}
	for _, e := range entries {
		full := true
		for i, axis := range []*rankAxis{&e.Q, &e.V, &e.T} {
			full = full && len(axis.ScoredFactors) == len(unions[e.ModelFamily+string(rune('Q'+i))]) && len(axis.ScoredFactors) > 0
		}
		e.FullCoverage = full
		if full {
			e.Comparability, e.ComparabilityLabel = "full", "پوشش بیشینهٔ عوامل مشاهده‌شده؛ اعتبار داده و سودآوری جداگانه باید بررسی شود"
		} else {
			e.Comparability, e.ComparabilityLabel = "partial", "عوامل محاسبه‌شده با بعضی نمادها متفاوت است؛ امتیاز کل مستقیماً مقایسه‌پذیر نیست"
		}
	}
}
