package handlers

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"go-app/config"
	"go-app/integration"
	"go-app/quant"
)

// chat_tools.go — ابزارهای دستیار سرمایه‌گذاری.
//
// قاعده‌ی اصلی: مدل زبانی هیچ عددی نمی‌سازد. هر عددی که به کاربر می‌رسد از یک
// ابزار می‌آید که یا مستقیم از PostgreSQL canonical می‌خواند یا با پکیج quant
// روی داده‌ی واقعی محاسبه می‌کند. ابزارها فقط خواندنی‌اند.

type chatTool struct {
	name        string
	description string
	parameters  map[string]any
	run         func(ctx context.Context, username string, args map[string]any) (string, error)
}

func argString(args map[string]any, key string) string {
	v, ok := args[key]
	if !ok || v == nil {
		return ""
	}
	switch t := v.(type) {
	case string:
		return strings.TrimSpace(t)
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	default:
		return strings.TrimSpace(fmt.Sprint(t))
	}
}

func argFloat(args map[string]any, key string, fallback float64) float64 {
	raw := argString(args, key)
	if raw == "" {
		return fallback
	}
	v, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return fallback
	}
	return v
}

func argInt(args map[string]any, key string, fallback, max int) int {
	raw := argString(args, key)
	if raw == "" {
		return fallback
	}
	v, err := strconv.Atoi(raw)
	if err != nil || v <= 0 {
		return fallback
	}
	if v > max {
		return max
	}
	return v
}

func argStringSlice(args map[string]any, key string) []string {
	v, ok := args[key]
	if !ok || v == nil {
		return nil
	}
	switch t := v.(type) {
	case []any:
		out := make([]string, 0, len(t))
		for _, item := range t {
			if s := strings.TrimSpace(fmt.Sprint(item)); s != "" {
				out = append(out, s)
			}
		}
		return out
	case string:
		parts := strings.Split(t, ",")
		out := make([]string, 0, len(parts))
		for _, s := range parts {
			if s = strings.TrimSpace(s); s != "" {
				out = append(out, s)
			}
		}
		return out
	default:
		return nil
	}
}

// rankText یک رتبه‌ی درصدی (۰..۱) را به عبارت فارسی «بهتر از X٪ بازار» تبدیل می‌کند.
func rankText(rank float64) string {
	return "بهتر از " + fmtNumFa(rank*100, 0) + "٪ بازار"
}

// ---------------------------------------------------------------------------
// ساخت ابزارها (به‌ازای هر درخواست، با نگاه به فهرست امتیازهای بارگذاری‌شده)
// ---------------------------------------------------------------------------

func newChatToolset(rows []integration.AllScoreInputRow) []chatTool {
	nlStr := "\n"
	byID := make(map[string]integration.AllScoreInputRow, len(rows))
	for _, r := range rows {
		byID[strings.ToLower(r.LegacyCompanyID)] = r
	}

	resolve := func(arg string) (integration.AllScoreInputRow, bool) {
		arg = strings.TrimSpace(arg)
		if arg == "" {
			return integration.AllScoreInputRow{}, false
		}
		if r, ok := byID[strings.ToLower(arg)]; ok {
			return r, true
		}
		mentions := findCompanyMentions(arg, rows)
		if len(mentions) == 0 {
			return integration.AllScoreInputRow{}, false
		}
		return mentions[0].row, true
	}

	// screen/candidate selection shared by several tools.
	filterRows := func(minScore, minLiquidityRank float64, liquidOnly bool) []integration.AllScoreInputRow {
		out := make([]integration.AllScoreInputRow, 0, len(rows))
		for _, r := range rows {
			if r.QuantScore < minScore {
				continue
			}
			if lr := r.FactorRanks["Liquidity"]; liquidOnly && lr > 0 && lr < minLiquidityRank {
				continue
			}
			out = append(out, r)
		}
		return out
	}

	sortRows := func(list []integration.AllScoreInputRow, by string) {
		switch by {
		case "liquidity":
			sort.SliceStable(list, func(i, j int) bool { return list[i].FactorRanks["Liquidity"] > list[j].FactorRanks["Liquidity"] })
		case "momentum":
			sort.SliceStable(list, func(i, j int) bool { return list[i].FactorRank("Momentum") > list[j].FactorRank("Momentum") })
		case "valuation":
			sort.SliceStable(list, func(i, j int) bool { return list[i].FactorRank("PE") > list[j].FactorRank("PE") })
		default:
			sort.SliceStable(list, func(i, j int) bool { return list[i].QuantScore > list[j].QuantScore })
		}
	}

	rowLine := func(r integration.AllScoreInputRow) string {
		var b strings.Builder
		b.WriteString(fmt.Sprintf("%s (نماد %s، شناسه %s) — امتیاز کمی %.1f", r.CompanyName, r.Symbol, r.LegacyCompanyID, r.QuantScore))
		if v, ok := rawOr(r, "PE"); ok && v > 0 {
			b.WriteString(fmt.Sprintf(" | P/E %.2f", v))
		}
		if v, ok := rawOr(r, "SalesGrowth"); ok && math.Abs(v) <= growthOutlierLimit {
			b.WriteString(fmt.Sprintf(" | رشد فروش %.1f٪", v))
		}
		if v, ok := rawOr(r, "Momentum"); ok {
			b.WriteString(fmt.Sprintf(" | بازده ۳۰روزه %.1f٪", v))
		}
		if lr, ok := r.FactorRanks["Liquidity"]; ok && lr > 0 {
			b.WriteString(" | نقدشوندگی: " + rankText(lr))
		}
		return b.String()
	}

	tools := []chatTool{
		{
			name:        "search_companies",
			description: "جست‌وجوی شرکت با نام، نماد یا بخشی از نام. برای پیدا کردن شرکتِ موردنظر کاربر و گرفتن شناسه‌ی آن.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query": map[string]any{"type": "string", "description": "نام یا نماد شرکت، مثلاً «فولاد» یا «کیمیا»"},
					"limit": map[string]any{"type": "integer", "description": "حداکثر تعداد نتیجه (پیش‌فرض ۱۰)"},
				},
				"required": []string{"query"},
			},
			run: func(_ context.Context, _ string, args map[string]any) (string, error) {
				q := argString(args, "query")
				if q == "" {
					return "", fmt.Errorf("query is required")
				}
				limit := argInt(args, "limit", 10, 30)
				hits := findCompanyMentions(q, rows)
				if len(hits) == 0 {
					return "شرکتی با این نام/نماد پیدا نشد.", nil
				}
				var b strings.Builder
				b.WriteString(fmt.Sprintf("نتایج جست‌وجو (%d):\n", min(len(hits), limit)))
				for i, m := range hits {
					if i >= limit {
						break
					}
					b.WriteString("- " + rowLine(m.row) + "\n")
				}
				return b.String(), nil
			},
		},
		{
			name:        "screen_companies",
			description: "غربال شرکت‌ها بر اساس امتیاز کمی، نقدشوندگی و مرتب‌سازی. برای «بهترین سهم‌ها»، «کم‌ریسک‌ترین» و فهرست‌های مشابه.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"min_quant_score":    map[string]any{"type": "number", "description": "حداقل امتیاز کمی (۰..۱۰۰)"},
					"min_liquidity_rank": map[string]any{"type": "number", "description": "حداقل رتبه‌ی نقدشوندگی (۰..۱)"},
					"liquid_only":        map[string]any{"type": "boolean", "description": "فقط سهم‌های نسبتاً نقدشونده"},
					"sort_by":            map[string]any{"type": "string", "enum": []string{"quant", "liquidity", "momentum", "valuation"}},
					"limit":              map[string]any{"type": "integer", "description": "تعداد نتیجه (پیش‌فرض ۱۰، حداکثر ۲۵)"},
				},
			},
			run: func(_ context.Context, _ string, args map[string]any) (string, error) {
				minScore := argFloat(args, "min_quant_score", 0)
				minLiq := argFloat(args, "min_liquidity_rank", 0.25)
				liquidOnly := argString(args, "liquid_only") != "false"
				limit := argInt(args, "limit", 10, 25)
				by := argString(args, "sort_by")
				list := filterRows(minScore, minLiq, liquidOnly)
				sortRows(list, by)
				if len(list) == 0 {
					return "با این فیلترها شرکتی پیدا نشد؛ فیلترها را ساده‌تر کن.", nil
				}
				if len(list) > limit {
					list = list[:limit]
				}
				var b strings.Builder
				b.WriteString(fmt.Sprintf("غربال (مرتب بر اساس %s، %d نتیجه از %d شرکت):\n", orDefault(by, "quant"), len(list), len(rows)))
				for i, r := range list {
					b.WriteString(fmt.Sprintf("%d. %s\n", i+1, rowLine(r)))
				}
				return b.String(), nil
			},
		},
		{
			name:        "get_company_profile",
			description: "پروفایل کامل کمّی یک شرکت: امتیاز کمی، امتیاز دسته‌ها، اعداد خام بنیادی (P/E، حاشیه‌ها، ROE، اهرم…)، نقاط قوت و ضعف بر پایه‌ی رتبه‌ی درصدی و محدودیت‌های داده.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"company": map[string]any{"type": "string", "description": "نام، نماد یا شناسه‌ی شرکت (۳۲ کاراکتر هگز)"},
				},
				"required": []string{"company"},
			},
			run: func(_ context.Context, _ string, args map[string]any) (string, error) {
				r, ok := resolve(argString(args, "company"))
				if !ok {
					return "", fmt.Errorf("company not found: %s", argString(args, "company"))
				}
				rank := companyRank(r, rows)
				var b strings.Builder
				b.WriteString(fmt.Sprintf("%s (نماد %s، شناسه %s)\n", r.CompanyName, r.Symbol, r.LegacyCompanyID))
				b.WriteString(fmt.Sprintf("امتیاز کمی %.1f از ۱۰۰ — رتبه %d از %d — %s\n", r.QuantScore, rank, len(rows), verdictRankFa(rank, len(rows))))
				b.WriteString(fmt.Sprintf("امتیاز دسته‌ها (مقیاس داخلی): رشد %.0f | سودآوری %.0f | ارزش‌گذاری %.0f | بازار %.0f\n",
					r.GrowthScore, r.ProfitabilityScore, r.ValuationScore, r.MarketScore))
				if r.Price > 0 {
					b.WriteString("قیمت: " + fmtRialCompactFa(r.Price) + "\n")
				}
				type fac struct {
					label string
					code  string
				}
				raws := []fac{
					{"P/E", "PE"}, {"P/S", "PS"}, {"P/B", "PB"},
					{"حاشیه سود عملیاتی", "OperatingMargin"}, {"حاشیه سود خالص", "NetMargin"}, {"ROE", "ROERank"},
					{"رشد فروش ۱۲ماهه", "SalesGrowth"}, {"رشد سود خالص", "NetProfitGrowth"},
					{"مومنتوم ۳۰روزه", "Momentum"}, {"نوسان", "LowVolatility"},
					{"نسبت جاری", "CurrentRatio"}, {"اهرم", "Leverage"}, {"تبدیل نقدی", "CashConversion"},
					{"پوشش هزینه مالی", "InterestCoverage"}, {"سهم غیرعملیاتی", "EarningsQuality"},
					{"میانگین ارزش معاملات", "Liquidity"},
				}
				var have, missing []string
				for _, f := range raws {
					v, ok := rawOr(r, f.code)
					if !ok {
						missing = append(missing, f.label)
						continue
					}
					var s string
					switch f.code {
					case "PE", "PS", "PB", "CurrentRatio", "Leverage", "CashConversion", "InterestCoverage":
						s = fmtNumFa(v, 2)
					case "Liquidity":
						s = fmtRialCompactFa(v)
					default:
						if math.Abs(v) > growthOutlierLimit {
							missing = append(missing, f.label+" (مقدار ناهنجار)")
							continue
						}
						s = fmtPctFa(v)
					}
					have = append(have, f.label+"="+s)
				}
				if len(have) > 0 {
					b.WriteString("اعداد بنیادی: " + strings.Join(have, " | ") + "\n")
				}
				if len(missing) > 0 {
					b.WriteString("بدون داده: " + strings.Join(missing, "، ") + "\n")
				}
				if s := topFactorText(r, 3); len(s) > 0 {
					b.WriteString("نقاط قوت:\n" + strings.Join(s, "\n") + "\n")
				}
				if w := weakestFactorText(r, 2); len(w) > 0 {
					b.WriteString("نقاط ضعف:\n" + strings.Join(w, "\n") + "\n")
				}
				return b.String(), nil
			},
		},
		{
			name:        "get_company_financials",
			description: "دوره‌های صورت سود و زیان و اعداد TTM یک شرکت (EPS، درآمد، سود عملیاتی، سود خالص، سرمایه).",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"company": map[string]any{"type": "string", "description": "نام، نماد یا شناسه‌ی شرکت"},
					"periods": map[string]any{"type": "integer", "description": "تعداد دوره‌های اخیر (پیش‌فرض ۶)"},
				},
				"required": []string{"company"},
			},
			run: func(ctx context.Context, _ string, args map[string]any) (string, error) {
				r, ok := resolve(argString(args, "company"))
				if !ok {
					return "", fmt.Errorf("company not found")
				}
				sh := integration.Default()
				if sh == nil {
					return "", fmt.Errorf("canonical source not configured")
				}
				page, err := sh.FetchSymbolPageCanonical(ctx, r.LegacyCompanyID)
				if err != nil {
					return "", err
				}
				periods := argInt(args, "periods", 6, 20)
				var b strings.Builder
				b.WriteString(fmt.Sprintf("صورت سود و زیان %s (%d دوره اخیر، مبالغ میلیون ریال):\n", r.CompanyName, periods))
				for i, f := range page.Financial {
					if i >= periods {
						break
					}
					b.WriteString(fmt.Sprintf("- دوره %s: EPS %.0f ریال | درآمد %.0f | سود عملیاتی %.0f | سود خالص %.0f | سرمایه %.0f\n",
						f.ReportDate, f.EPS, f.Revenue, f.OperatingProfit, f.NetProfit, f.Capital))
				}
				snaps := latestSnapshots(page)
				for _, code := range []string{"revenue_ttm", "net_profit_ttm", "operating_profit_ttm", "eps_ttm", "ocf_ttm"} {
					if s, ok := snaps[code]; ok {
						if v, ok := formatSnapMetric(code, s.unit, s.value); ok {
							b.WriteString(fmt.Sprintf("TTM %s = %s\n", code, v))
						}
					}
				}
				b.WriteString("as-of اجرای امتیازدهی: " + page.Metadata.ScoreAsOf + "\n")
				return b.String(), nil
			},
		},
		{
			name:        "get_monthly_sales",
			description: "فروش و تولید ماهانه‌ی یک شرکت (مبلغ و مقدار) برای تحلیل روند.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"company": map[string]any{"type": "string", "description": "نام، نماد یا شناسه‌ی شرکت"},
					"months":  map[string]any{"type": "integer", "description": "تعداد ماه (پیش‌فرض ۱۲)"},
				},
				"required": []string{"company"},
			},
			run: func(ctx context.Context, _ string, args map[string]any) (string, error) {
				r, ok := resolve(argString(args, "company"))
				if !ok {
					return "", fmt.Errorf("company not found")
				}
				sh := integration.Default()
				if sh == nil {
					return "", fmt.Errorf("canonical source not configured")
				}
				page, err := sh.FetchSymbolPageCanonical(ctx, r.LegacyCompanyID)
				if err != nil {
					return "", err
				}
				months := argInt(args, "months", 12, 60)
				if len(page.Monthly) == 0 {
					return "فعالیت ماهانه‌ای برای این شرکت ثبت نشده است.", nil
				}
				var b strings.Builder
				b.WriteString(fmt.Sprintf("فروش ماهانه %s (تازه‌ترین %d ماه):\n", r.CompanyName, months))
				for i, m := range page.Monthly {
					if i >= months {
						break
					}
					b.WriteString(fmt.Sprintf("- %s: مبلغ فروش %s | تولید %.0f | فروش مقداری %.0f\n",
						m.ReportDate, fmtRialCompactFa(m.SalesAmountRial), m.ProductionQuantity, m.SalesQuantity))
				}
				return b.String(), nil
			},
		},
		{
			name:        "get_price_stats",
			description: "آمار ریسک/بازده قیمت یک شرکت از تاریخچه‌ی واقعی: بازده ۳۰/۹۰/۲۵۰ روزه، نوسان سالانه‌شده، حداکثر افت و میانگین ارزش معاملات.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"company": map[string]any{"type": "string", "description": "نام، نماد یا شناسه‌ی شرکت"},
					"days":    map[string]any{"type": "integer", "description": "طول پنجره‌ی تاریخچه (پیش‌فرض ۳۶۵ روز معاملاتی)"},
				},
				"required": []string{"company"},
			},
			run: func(ctx context.Context, _ string, args map[string]any) (string, error) {
				r, ok := resolve(argString(args, "company"))
				if !ok {
					return "", fmt.Errorf("company not found")
				}
				sh := integration.Default()
				if sh == nil {
					return "", fmt.Errorf("canonical source not configured")
				}
				page, err := sh.FetchSymbolPageCanonical(ctx, r.LegacyCompanyID)
				if err != nil {
					return "", err
				}
				days := argInt(args, "days", 365, 1000)
				closes := marketClosesOldestFirst(page.Market)
				if len(closes) < 30 {
					return "تاریخچه‌ی قیمت کافی برای محاسبه‌ی ریسک موجود نیست.", nil
				}
				if len(closes) > days {
					closes = closes[len(closes)-days:]
				}
				rets := quant.DailyReturns(closes)
				var b strings.Builder
				b.WriteString(fmt.Sprintf("آمار قیمت %s (روی %d روز معاملاتی، از %s):\n", r.CompanyName, len(closes), page.Metadata.MarketAsOf))
				b.WriteString(fmt.Sprintf("- بازده کل دوره: %s\n", fmtPctFa(quant.CumulativeReturnPct(closes))))
				if v, ok := quant.WindowReturnPct(closes, 30); ok {
					b.WriteString(fmt.Sprintf("- بازده ۳۰ روزه: %s\n", fmtPctFa(v)))
				}
				if v, ok := quant.WindowReturnPct(closes, 90); ok {
					b.WriteString(fmt.Sprintf("- بازده ۹۰ روزه: %s\n", fmtPctFa(v)))
				}
				if v, ok := quant.WindowReturnPct(closes, 250); ok {
					b.WriteString(fmt.Sprintf("- بازده ۲۵۰ روزه: %s\n", fmtPctFa(v)))
				}
				b.WriteString(fmt.Sprintf("- نوسان سالانه‌شده: %s (روزانه %s)\n",
					fmtNumFa(quant.AnnualizedVolPct(rets, 250), 1)+"٪", fmtNumFa(quant.Stdev(rets)*100, 2)+"٪"))
				b.WriteString(fmt.Sprintf("- حداکثر افت: %s\n", fmtNumFa(quant.MaxDrawdownPct(closes), 1)+"٪"))
				b.WriteString(fmt.Sprintf("- انحراف نزولی سالانه‌شده: %s\n", fmtNumFa(quant.DownsideDeviationPct(rets, 250), 1)+"٪"))
				if vals := marketTradeValues(page.Market, 30); len(vals) > 0 {
					b.WriteString("- میانگین ارزش معاملات روزانه (۳۰ روز): " + fmtRialCompactFa(quant.Mean(vals)) + "\n")
				}
				b.WriteString("نکته: بنچمارک شاخص کل در دیتابیس موجود نیست، پس بتا محاسبه نمی‌شود.\n")
				return b.String(), nil
			},
		},
		{
			name:        "get_my_portfolio",
			description: "سبد فعلی کاربر با مقدار، میانگین بهای تمام‌شده، ارزش روز، سود/زیان و وزن هر نماد.",
			parameters:  map[string]any{"type": "object", "properties": map[string]any{}},
			run: func(ctx context.Context, username string, _ map[string]any) (string, error) {
				return readMyPortfolio(ctx, username)
			},
		},
		{
			name:        "compare_companies",
			description: "مقایسه‌ی چند شرکت در کنار هم روی امتیاز، ارزش‌گذاری، سودآوری، رشد، نقدشوندگی و ریسک.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"companies": map[string]any{
						"type":        "array",
						"items":       map[string]any{"type": "string"},
						"description": "فهرست نام/نماد/شناسه‌ی شرکت‌ها (۲ تا ۵ مورد)",
					},
				},
				"required": []string{"companies"},
			},
			run: func(ctx context.Context, _ string, args map[string]any) (string, error) {
				names := argStringSlice(args, "companies")
				if len(names) < 2 {
					return "", fmt.Errorf("at least two companies are required")
				}
				var b strings.Builder
				b.WriteString("مقایسه‌ی شرکت‌ها:\n")
				for _, n := range names {
					r, ok := resolve(n)
					if !ok {
						b.WriteString(fmt.Sprintf("- «%s»: پیدا نشد\n", n))
						continue
					}
					b.WriteString("- " + rowLine(r) + "\n")
					b.WriteString(fmt.Sprintf("  دسته‌ها: رشد %.0f | سودآوری %.0f | ارزش‌گذاری %.0f | بازار %.0f | نقدشوندگی: %s\n",
						r.GrowthScore, r.ProfitabilityScore, r.ValuationScore, r.MarketScore, rankText(r.FactorRank("Liquidity"))))
				}
				b.WriteString("برای هر شرکت می‌توانی get_price_stats را هم صدا بزنی تا ریسکش را ببینی.\n")
				return b.String(), nil
			},
		},
		{
			name:        "critique_my_portfolio",
			description: "نقد سبد واقعی کاربر: وزن‌ها، تمرکز (HHI و سهم سه نام اول)، پراکندگی صنعتی در برابر سقف، و نوسان/حداکثر افت تاریخی سبد.",
			parameters:  map[string]any{"type": "object", "properties": map[string]any{}},
			run: func(ctx context.Context, username string, _ map[string]any) (string, error) {
				_, holdings, ok := readPortfolioHoldings(ctx, username)
				if !ok || len(holdings) == 0 {
					return "سبدی برای نقد کردن وجود ندارد.", nil
				}
				total := 0.0
				for _, h := range holdings {
					total += h.qty * h.last
				}
				if total <= 0 {
					return "ارزش روز سبد صفر است (قیمت آخرین موجود نیست).", nil
				}
				sh := integration.Default()
				if sh == nil {
					return "", fmt.Errorf("canonical source not configured")
				}
				var series []quant.Series
				ids := make([]string, 0, len(holdings))
				weights := make([]float64, 0, len(holdings))
				var b strings.Builder
				b.WriteString(fmt.Sprintf("نقد سبد واقعی (%d نماد، ارزش روز %s):"+nlStr, len(holdings), fmtRialCompactFa(total)))
				hhi := 0.0
				type hv struct {
					sym  string
					comp string
					w    float64
				}
				var ws []hv
				for _, h := range holdings {
					w := h.qty * h.last / total
					weights = append(weights, w)
					hhi += w * w
					ws = append(ws, hv{h.symbol, h.name, w})
					if h.legacyID != "" {
						ids = append(ids, h.legacyID)
					}
				}
				sort.Slice(ws, func(i, j int) bool { return ws[i].w > ws[j].w })
				for i, x := range ws {
					if i >= 3 {
						break
					}
					b.WriteString(fmt.Sprintf("- تمرکز: %s با %.1f٪ از سبد"+nlStr, x.sym, x.w*100))
				}
				b.WriteString(fmt.Sprintf("- شاخص تمرکز HHI: %.2f (۱/n یعنی کاملاً هموزن برای n نماد)"+nlStr, hhi))

				metaByID := map[string]string{}
				if len(ids) > 0 {
					if mm, err := sh.FetchMarketMetaCanonical(ctx, ids); err == nil {
						for _, m := range mm {
							metaByID[m.LegacyCompanyID] = strings.TrimSpace(m.Category)
						}
					}
				}
				sector := map[string]float64{}
				for i, h := range holdings {
					g := "نامشخص"
					if h.legacyID != "" {
						if c, found := metaByID[h.legacyID]; found && c != "" {
							g = c
						}
					}
					sector[g] += weights[i] * 100
					_ = i
				}
				var cats []string
				for g := range sector {
					cats = append(cats, g)
				}
				sort.Strings(cats)
				b.WriteString("پراکندگی صنعتی (سقف پیشنهادی هر صنعت ۲۵٪):" + nlStr)
				for _, g := range cats {
					flag := ""
					if sector[g] > 25 {
						flag = "  ⚠️ بالای سقف"
					}
					b.WriteString(fmt.Sprintf("- %s: %.1f%%%s"+nlStr, g, sector[g], flag))
				}

				// ریسک تاریخی سبد واقعی
				for _, h := range holdings {
					if h.legacyID == "" {
						continue
					}
					if hist, err := sh.FetchPriceSeriesCanonical(ctx, h.legacyID, 300); err == nil && len(hist) >= 60 {
						s := quant.Series{Key: h.symbol}
						for j := len(hist) - 1; j >= 0; j-- {
							pp := hist[j].ClosingPrice
							if pp <= 0 {
								pp = hist[j].LastPrice
							}
							if pp > 0 {
								s.Dates = append(s.Dates, hist[j].Date)
								s.Prices = append(s.Prices, pp)
							}
						}
						series = append(series, s)
					}
				}
				if len(series) == len(holdings) && len(series) > 0 {
					_, rets, starts, okMask := quant.AlignedReturns(series, 60)
					usable := make([]int, 0, len(series))
					for i := range series {
						if okMask[i] {
							usable = append(usable, i)
						}
					}
					if len(usable) >= 2 {
						startRow := 0
						for _, st := range starts {
							if st > startRow {
								startRow = st
							}
						}
						cov := quant.ShrinkCovariance(quant.CovarianceMatrix(rets, startRow, 250), 0.3)
						wu := make([]float64, 0, len(usable))
						ru := make([][]float64, 0, len(usable))
						su := make([][]float64, len(usable))
						for a := range usable {
							wu = append(wu, weights[usable[a]])
							ru = append(ru, rets[usable[a]])
							su[a] = make([]float64, len(usable))
							for cIdx := range usable {
								su[a][cIdx] = cov[usable[a]][usable[cIdx]]
							}
						}
						vol := quant.PortfolioVolPct(wu, su)
						port := quant.PortfolioSeries(wu, ru)
						b.WriteString(fmt.Sprintf("- نوسان سالانه‌ی سبد: %.1f٪ | حداکثر افت: %.1f٪ (روی %d روز)"+nlStr,
							vol, quant.MaxDrawdownFromReturns(port), len(port)))
					}
				} else {
					b.WriteString("- تاریخچه‌ی کافی برای محاسبه‌ی نوسان سبد موجود نبود." + nlStr)
				}
				return b.String(), nil
			},
		},
		{
			name:        "get_my_preferences",
			description: "پروفایل ریسک و سرمایه‌ای که کاربر قبلاً ثبت کرده را برمی‌گرداند (اگر تنظیم شده باشد).",
			parameters:  map[string]any{"type": "object", "properties": map[string]any{}},
			run: func(ctx context.Context, username string, _ map[string]any) (string, error) {
				st, ok := getChatSettings(ctx, username)
				if !ok {
					return "تنظیماتی ثبت نشده است. اگر کاربر سطح ریسک (کم/متوسط/زیاد) یا سرمایه گفت، با set_my_preferences ثبت کن.", nil
				}
				var b strings.Builder
				b.WriteString("تنظیمات کاربر: ")
				if st.RiskLevel != "" {
					b.WriteString("سطح ریسک=" + st.RiskLevel + " ")
				}
				if st.HasCapital {
					b.WriteString("سرمایه=" + fmtRialCompactFa(st.CapitalRial))
				}
				b.WriteString("\n")
				return b.String(), nil
			},
		},
		{
			name:        "set_my_preferences",
			description: "ثبت/به‌روزرسانی سطح ریسک و سرمایه‌ی کاربر. فقط وقتی خود کاربر این‌ها را گفته صدا بزن.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"risk_level":   map[string]any{"type": "string", "enum": []string{"low", "medium", "high"}, "description": "سطح ریسک"},
					"capital_rial": map[string]any{"type": "number", "description": "سرمایه به ریال"},
				},
			},
			run: func(ctx context.Context, username string, args map[string]any) (string, error) {
				st := chatSettings{RiskLevel: argString(args, "risk_level")}
				if c := argString(args, "capital_rial"); c != "" {
					st.CapitalRial = argFloat(args, "capital_rial", 0)
					st.HasCapital = st.CapitalRial > 0
				}
				if st.RiskLevel == "" && !st.HasCapital {
					return "", fmt.Errorf("هیچ مقداری برای ذخیره ارسال نشد")
				}
				if err := upsertChatSettings(ctx, username, st); err != nil {
					return "", err
				}
				return "ثبت شد.", nil
			},
		},
		{
			name:        "build_portfolio",
			description: "ساخت سبد ریسک‌محور روی داده‌ی واقعی با سقف وزن. پیش‌فرض هموزن سقف‌دار است (در بک‌تست PIT بهترین شارپ)؛ min_variance افت تاریخی کمتر ولی بازده کمتر دارد. خروجی وزن‌ها و متریک‌های ریسک تاریخی همان سبد است.",
			parameters: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"risk_level":   map[string]any{"type": "string", "enum": []string{"low", "medium", "high"}, "description": "سطح ریسک: کم = سقف وزن پایین‌تر و نقدشوندگی سخت‌گیرانه‌تر"},
					"method":       map[string]any{"type": "string", "enum": []string{"equal", "min_variance", "inverse_vol"}, "description": "روش وزن‌دهی (پیش‌فرض equal: بالاترین شارپ در بک‌تست؛ min_variance حداکثر افت کمتر)"},
					"names":        map[string]any{"type": "integer", "description": "تعداد نمادهای سبد (اختیاری؛ پیش‌فرض بر اساس سطح ریسک)"},
					"max_weight":   map[string]any{"type": "number", "description": "سقف وزن هر نماد به درصد (اختیاری)"},
					"cash_buffer":  map[string]any{"type": "number", "description": "درصد نقد نگه‌داشته‌شده (اختیاری)"},
					"min_score":    map[string]any{"type": "number", "description": "حداقل امتیاز کمی برای ورود به سبد (اختیاری)"},
					"history_days": map[string]any{"type": "integer", "description": "طول پنجره‌ی تاریخچه برای کوواریانس (پیش‌فرض ۳۰۰ روز معاملاتی)"},
				},
			},
			run: func(ctx context.Context, username string, args map[string]any) (string, error) {
				return buildPortfolioTool(ctx, username, args, rows, resolve, rowLine)
			},
		},
	}

	return tools
}

func orDefault(v, fallback string) string {
	if strings.TrimSpace(v) == "" {
		return fallback
	}
	return v
}

// marketClosesOldestFirst سری بازار canonical (نویز تازه‌ترین‌اول) را برمی‌گرداند.
func marketClosesOldestFirst(market []integration.MarketInputRow) []float64 {
	out := make([]float64, 0, len(market))
	for i := len(market) - 1; i >= 0; i-- {
		p := market[i].ClosingPrice
		if p <= 0 {
			p = market[i].LastPrice
		}
		if p > 0 {
			out = append(out, p)
		}
	}
	return out
}

func marketTradeValues(market []integration.MarketInputRow, limit int) []float64 {
	out := make([]float64, 0, limit)
	for i := 0; i < len(market) && i < limit; i++ {
		if v := market[i].TradeValue; v > 0 {
			out = append(out, v)
		}
	}
	return out
}

// portfolioHoldingRow یک ردیف سبد کاربر با آخرین قیمت بازار و شناسه‌ها.
type portfolioHoldingRow struct {
	symbol, name             string
	qty, avgCost, cost, last float64
	securityID               string
	legacyID                 string
}

// readPortfolioHoldings سبد کاربر را از PostgreSQL canonical می‌خواند و هم
// ارزش روز کل و هم ردیف‌ها را برمی‌گرداند تا هم ابزار متنی و هم محاسبه‌ی گردش
// سبد از یک منبع تغذیه شوند.
func readPortfolioHoldings(ctx context.Context, username string) (float64, []portfolioHoldingRow, bool) {
	if strings.TrimSpace(username) == "" {
		return 0, nil, false
	}
	db, err := config.GetPG()
	if err != nil || db == nil {
		return 0, nil, false
	}
	uid, ok, err := userIDByUsername(ctx, db, username)
	if err != nil || !ok {
		return 0, nil, false
	}
	const q = `
		SELECT COALESCE(a.symbol, ''), COALESCE(a.name, ''), p.quantity,
		       COALESCE(p.avg_cost_rial, 0), COALESCE(p.cost_basis_rial, 0),
		       COALESCE((
		           SELECT po.closing_price_rial FROM market.price_observations po
		           WHERE po.security_id = a.security_id AND po.price_series = 'adjusted'
		           ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
		           LIMIT 1), 0),
		       a.security_id::text,
		       COALESCE((SELECT lem.legacy_key FROM core.legacy_entity_map lem
		                 WHERE lem.entity_type = 'company' AND lem.target_uuid = c.id
		                 AND lem.legacy_key ~ '^[0-9a-f]{32}$' LIMIT 1), '')
		FROM portfolio.positions p
		JOIN portfolio.assets a ON a.id = p.asset_id
		JOIN portfolio.portfolios pf ON pf.id = p.portfolio_id
		LEFT JOIN core.securities sec ON sec.id = a.security_id
		LEFT JOIN core.companies c ON c.id = sec.company_id
		WHERE pf.user_id = $1::uuid AND pf.is_active = true
		ORDER BY p.id`
	rows, err := db.QueryContext(ctx, q, uid)
	if err != nil {
		return 0, nil, false
	}
	defer rows.Close()

	total := 0.0
	var list []portfolioHoldingRow
	for rows.Next() {
		var h portfolioHoldingRow
		if err := rows.Scan(&h.symbol, &h.name, &h.qty, &h.avgCost, &h.cost, &h.last,
			&h.securityID, &h.legacyID); err != nil {
			return 0, nil, false
		}
		if h.cost == 0 {
			h.cost = h.qty * h.avgCost
		}
		list = append(list, h)
		total += h.qty * h.last
	}
	if rows.Err() != nil {
		return 0, nil, false
	}
	return total, list, len(list) > 0
}

// readMyPortfolio سبد کاربر را به شکل متنی برای مدل آماده می‌کند.
func readMyPortfolio(ctx context.Context, username string) (string, error) {
	if strings.TrimSpace(username) == "" {
		return "کاربر مشخص نیست.", nil
	}
	totalValue, list, ok := readPortfolioHoldings(ctx, username)
	if !ok {
		return "سبدی برای این کاربر ثبت نشده است.", nil
	}
	var b strings.Builder
	b.WriteString(fmt.Sprintf("سبد فعلی کاربر (%d نماد، ارزش روز کل %s):\n", len(list), fmtRialCompactFa(totalValue)))
	for _, h := range list {
		mv := h.qty * h.last
		weight := 0.0
		if totalValue > 0 {
			weight = mv / totalValue * 100.0
		}
		gain := mv - h.cost
		gainPct := 0.0
		if h.cost > 0 {
			gainPct = gain / h.cost * 100.0
		}
		name := h.symbol
		if name == "" {
			name = h.name
		}
		b.WriteString(fmt.Sprintf("- %s: مقدار %.0f | میانگین خرید %s | ارزش روز %s | وزن %.1f٪ | سود/زیان %s (%.1f٪)\n",
			name, h.qty, fmtRialFa(h.avgCost), fmtRialCompactFa(mv), weight, fmtRialCompactFa(gain), gainPct))
	}
	return b.String(), nil
}
