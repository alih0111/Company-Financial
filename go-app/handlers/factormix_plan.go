package handlers

import (
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type factorMixRow struct {
	Symbol        string   `json:"symbol"`
	Rank          *int     `json:"rank"`
	Score         *float64 `json:"score"`
	PreviousRank  *int     `json:"previous_rank"`
	PreviousScore *float64 `json:"previous_score"`
	PriceDate     string   `json:"price_date"`
	Reason        *string  `json:"reason"`
}
type factorMixSnapshot struct {
	StrategyID    string         `json:"strategy_id"`
	Date          string         `json:"date"`
	MarketDate    string         `json:"market_date"`
	ComputedAt    string         `json:"computed_at_utc"`
	PreviousDate  *string        `json:"previous_date"`
	EligibleCount int            `json:"eligible_count"`
	UniverseCount int            `json:"universe_count"`
	Rows          []factorMixRow `json:"rows"`
}
type planHolding struct {
	Symbol string  `json:"symbol"`
	Value  float64 `json:"value_toman"`
}

func normalizePlanSymbol(symbol string) string {
	return strings.Join(strings.Fields(strings.NewReplacer("ي", "ی", "ك", "ک", "\u200c", "").Replace(symbol)), "")
}
func parseFactorMixSnapshot(raw []byte) (factorMixSnapshot, error) {
	var ranking factorMixSnapshot
	err := json.Unmarshal(raw, &ranking)
	if err != nil {
		return ranking, err
	}
	if ranking.StrategyID != "RFA-FactorMix-033-Q40-Buffer8-v1.0.0" || ranking.Date == "" || ranking.ComputedAt == "" {
		return ranking, os.ErrInvalid
	}
	seen := map[string]bool{}
	for _, row := range ranking.Rows {
		key := normalizePlanSymbol(row.Symbol)
		if key == "" || seen[key] {
			return ranking, os.ErrInvalid
		}
		seen[key] = true
	}
	return ranking, nil
}
func limitedFactorMixRanking(c *gin.Context, raw []byte) (any, bool) {
	ranking, err := parseFactorMixSnapshot(raw)
	if err != nil {
		c.Status(503)
		return nil, false
	}
	q := normalizePlanSymbol(c.Query("q"))
	if len(q) > 120 {
		c.Status(400)
		return nil, false
	}
	rows := []factorMixRow{}
	for _, row := range ranking.Rows {
		if q == "" || strings.Contains(normalizePlanSymbol(row.Symbol), q) {
			rows = append(rows, row)
		}
	}
	start, end, ok := dataPage(c, len(rows))
	if !ok {
		return nil, false
	}
	ranking.Rows = rows[start:end]
	return ranking, true
}

func buildFactorMixPlan(ranking factorMixSnapshot, holdings []planHolding, cash float64) (gin.H, error) {
	if cash < 0 || math.IsNaN(cash) || math.IsInf(cash, 0) || cash > 1e16 || len(holdings) > 10 {
		return nil, fmt.Errorf("نقد معتبر و حداکثر ده دارایی وارد کنید.")
	}
	universe := map[string]factorMixRow{}
	for _, row := range ranking.Rows {
		universe[normalizePlanSymbol(row.Symbol)] = row
	}
	values := map[string]float64{}
	nav := cash
	for _, holding := range holdings {
		row, found := universe[normalizePlanSymbol(holding.Symbol)]
		if !found {
			return nil, fmt.Errorf("نماد واردشده در جهان این مدل نیست.")
		}
		if _, exists := values[row.Symbol]; exists || holding.Value <= 0 || holding.Value > 1e16 || math.IsNaN(holding.Value) || math.IsInf(holding.Value, 0) {
			return nil, fmt.Errorf("ارزش دارایی یا نماد تکراری معتبر نیست.")
		}
		values[row.Symbol] = holding.Value
		nav += holding.Value
	}
	if nav <= 0 || nav > 1e16 {
		return nil, fmt.Errorf("جمع دارایی و نقد معتبر نیست.")
	}
	eligible := []factorMixRow{}
	for _, row := range ranking.Rows {
		if row.Rank != nil && *row.Rank > 0 && row.Score != nil && (row.Reason == nil || *row.Reason == "") {
			eligible = append(eligible, row)
		}
	}
	sort.SliceStable(eligible, func(i, j int) bool { return *eligible[i].Rank < *eligible[j].Rank })
	if len(eligible) == 0 {
		return nil, fmt.Errorf("نماد واجد شرایطی برای پیشنهاد وجود ندارد.")
	}
	selected := []factorMixRow{}
	targets := map[string]bool{}
	for _, row := range eligible {
		if _, held := values[row.Symbol]; held && *row.Rank <= 8 && len(selected) < 5 {
			selected = append(selected, row)
			targets[row.Symbol] = true
		}
	}
	for _, row := range eligible {
		if len(selected) >= 5 {
			break
		}
		if !targets[row.Symbol] {
			selected = append(selected, row)
			targets[row.Symbol] = true
		}
	}
	ordered := append([]factorMixRow(nil), selected...)
	for _, row := range ranking.Rows {
		if _, held := values[row.Symbol]; held && !targets[row.Symbol] {
			ordered = append(ordered, row)
		}
	}
	rows := []gin.H{}
	changes := 0
	for _, row := range ordered {
		current := values[row.Symbol]
		weight := 0.0
		if targets[row.Symbol] {
			weight = .2
		}
		needed := (current > 0 && weight == 0) || (weight > 0 && (current == 0 || math.Abs(current/nav-weight) > .05+1e-12))
		delta := 0.0
		if needed {
			delta = weight*nav - current
		}
		action := "HOLD"
		if delta > 0 {
			action = "BUY"
		} else if delta < 0 {
			action = "SELL"
		}
		reason := "نگهداری در محدودهٔ مجاز"
		if weight == 0 {
			reason = "خارج از سبد هدف یا فاقد شرایط"
		} else if current == 0 {
			reason = "ورود برای پرکردن جای خالی"
		} else if needed {
			reason = "تنظیم انحراف بیش از ۵ واحد درصد"
		}
		if action != "HOLD" {
			changes++
		}
		rows = append(rows, gin.H{"symbol": row.Symbol, "rank": row.Rank, "current_toman": current, "current_weight": current / nav, "target_weight": weight, "target_toman": weight * nav, "delta_toman": delta, "action": action, "reason": reason})
	}
	return gin.H{"strategy_id": "RFA-FactorMix-033-M15-Buffer8-v1.0.0", "ranking_date": ranking.Date, "ranking_computed_at_utc": ranking.ComputedAt, "market_date": ranking.MarketDate, "nav_toman": nav, "cash_toman": cash, "rows": rows, "changes": changes, "missing_slots": 5 - len(selected), "amounts_before_costs": true, "executed": false}, nil
}

func PlanFactorMix(c *gin.Context) {
	var body struct {
		Holdings []planHolding `json:"holdings"`
		Cash     float64       `json:"cash_toman"`
	}
	if c.ShouldBindJSON(&body) != nil || len(body.Holdings) > 10 {
		c.JSON(400, gin.H{"error": "ورودی سبد معتبر نیست؛ حداکثر ده دارایی مجاز است."})
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		c.Status(503)
		return
	}
	raw, err := os.ReadFile(filepath.Join(root, ".runtime", "factormix-ranking", "latest.json"))
	if err != nil {
		c.JSON(503, gin.H{"error": "رتبه‌بندی معتبر هنوز موجود نیست."})
		return
	}
	ranking, err := parseFactorMixSnapshot(raw)
	if err != nil {
		c.Status(503)
		return
	}
	result, err := buildFactorMixPlan(ranking, body.Holdings, body.Cash)
	if err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	c.JSON(200, result)
}
