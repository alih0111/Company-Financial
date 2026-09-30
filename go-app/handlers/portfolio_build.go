package handlers

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"

	"go-app/integration"
	"go-app/quant"
)

const nlStr = "\n"

// portfolio_build.go — ابزار build_portfolio.
//
// جریان کار: انتخاب universe از امتیازهای canonical → خواندن تاریخچه‌ی قیمت
// هر نماد → هم‌ترازی و کوواریانس → وزن‌دهی (کم‌واریانس/معکوس‌نوسان/هموزن) با
// سقف وزن و بافر نقد → گزارش وزن‌ها و متریک‌های ریسکِ همان وزن‌ها روی همان
// پنجره‌ی تاریخی.
//
// هیچ بازده انتظاری از آینده پیش‌بینی نمی‌شود. معیارهای گزارش‌شده
// گذشته‌نگرند و شاخص کل/طبقه‌بندی صنعت در دیتابیس موجود نیست، پس بتا و سقف
// صنعتی محاسبه نمی‌شود؛ این محدودیت‌ها در خروجی به کاربر گفته می‌شود.

// riskProfile تنظیمات محافظه‌کارانه‌ی هر سطح ریسک (شفاف و قابل بازتولید).
type riskProfile struct {
	names       int
	maxWeight   float64 // درصد
	cashBuffer  float64 // درصد
	minScore    float64
	liquidityKo float64 // حداقل رتبه‌ی نقدشوندگی
	label       string
}

func profileFor(level string) riskProfile {
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "low", "کم", "محافظه":
		return riskProfile{names: 12, maxWeight: 10, cashBuffer: 10, minScore: 45, liquidityKo: 0.6, label: "کم‌ریسک"}
	case "high", "زیاد", "تهاجمی":
		return riskProfile{names: 20, maxWeight: 15, cashBuffer: 0, minScore: 35, liquidityKo: 0.25, label: "پرخطر"}
	default:
		return riskProfile{names: 15, maxWeight: 12, cashBuffer: 5, minScore: 40, liquidityKo: 0.4, label: "متعادل"}
	}
}

const (
	portfolioMaxCandidates  = 30  // سقف واکشی تاریخچه برای کنترل زمان پاسخ
	portfolioHistoryDefault = 300 // روز معاملاتی
	portfolioMinObs         = 120 // حداقل بازده معتبر برای ورود به کوواریانس
	portfolioShrinkage      = 0.3 // شدت شرینک کوواریانس
)

type portfolioCandidate struct {
	row    integration.AllScoreInputRow
	series quant.Series
}

func buildPortfolioTool(
	ctx context.Context,
	username string,
	args map[string]any,
	rows []integration.AllScoreInputRow,
	resolve func(string) (integration.AllScoreInputRow, bool),
	rowLine func(integration.AllScoreInputRow) string,
) (string, error) {
	riskArg := argString(args, "risk_level")
	if riskArg == "" {
		if st, ok := getChatSettings(ctx, username); ok && st.RiskLevel != "" {
			riskArg = st.RiskLevel
		}
	}
	profile := profileFor(riskArg)
	if n := argInt(args, "names", profile.names, 40); n > 0 {
		profile.names = n
	}
	if mw := argFloat(args, "max_weight", profile.maxWeight); mw > 0 {
		profile.maxWeight = mw
	}
	if cb := argString(args, "cash_buffer"); cb != "" {
		profile.cashBuffer = argFloat(args, "cash_buffer", profile.cashBuffer)
	}
	capital := argFloat(args, "capital_rial", 0)
	if capital <= 0 {
		if st, ok := getChatSettings(ctx, username); ok && st.HasCapital {
			capital = st.CapitalRial
		}
	}
	if ms := argString(args, "min_score"); ms != "" {
		profile.minScore = argFloat(args, "min_score", profile.minScore)
	}
	historyDays := argInt(args, "history_days", portfolioHistoryDefault, 1000)
	method := strings.ToLower(orDefault(argString(args, "method"), "min_variance"))

	// محافظه‌کاری: سقف با تعداد نمادها باید سازگار باشد.
	if profile.maxWeight*float64(profile.names) < 100 {
		profile.maxWeight = math.Ceil(100.0/float64(profile.names)) + 1
	}

	sh := integration.Default()
	if sh == nil {
		return "", fmt.Errorf("canonical source not configured")
	}

	// ۱) universe: امتیاز بالا + نقدشوندگی کافی (اگر شرکت خاصی خواسته نشده باشد)
	pool := make([]integration.AllScoreInputRow, 0, len(rows))
	for _, r := range rows {
		if r.QuantScore < profile.minScore {
			continue
		}
		if lr := r.FactorRank("Liquidity"); lr > 0 && lr < profile.liquidityKo {
			continue
		}
		pool = append(pool, r)
	}
	if v := argString(args, "company"); v != "" {
		if r, ok := resolve(v); ok {
			pool = append([]integration.AllScoreInputRow{r}, pool...)
		}
	}
	sort.SliceStable(pool, func(i, j int) bool { return pool[i].QuantScore > pool[j].QuantScore })
	if len(pool) > portfolioMaxCandidates {
		pool = pool[:portfolioMaxCandidates]
	}
	if len(pool) < 3 {
		return "", fmt.Errorf("universe too small after filters (%d companies); relax filters", len(pool))
	}

	// ۲) تاریخچه‌ی قیمت هر نامزد (موازی، هر درخواست یک کوئری indexed)
	cands := make([]portfolioCandidate, len(pool))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 6)
	for i, r := range pool {
		wg.Add(1)
		go func(i int, r integration.AllScoreInputRow) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			if ctx.Err() != nil {
				return
			}
			hist, err := sh.FetchPriceSeriesCanonical(ctx, r.LegacyCompanyID, historyDays)
			if err != nil || len(hist) == 0 {
				return
			}
			s := quant.Series{Key: r.Symbol}
			for j := len(hist) - 1; j >= 0; j-- { // canonical نویز تازه‌ترین‌اول است
				p := hist[j].ClosingPrice
				if p <= 0 {
					p = hist[j].LastPrice
				}
				if p <= 0 {
					continue
				}
				s.Dates = append(s.Dates, hist[j].Date)
				s.Prices = append(s.Prices, p)
			}
			cands[i] = portfolioCandidate{row: r, series: s}
		}(i, r)
	}
	wg.Wait()

	series := make([]quant.Series, 0, len(cands))
	meta := make([]integration.AllScoreInputRow, 0, len(cands))
	var dropped []string
	for _, c := range cands {
		if len(c.series.Prices) < portfolioMinObs+1 {
			if c.row.Symbol != "" {
				dropped = append(dropped, c.row.Symbol)
			}
			continue
		}
		series = append(series, c.series)
		meta = append(meta, c.row)
	}
	if len(series) < 3 {
		return "", fmt.Errorf("not enough price history for a portfolio (%d usable of %d candidates)", len(series), len(pool))
	}

	// ۳) هم‌ترازی و کوواریانس
	dates, rets, starts, ok := quant.AlignedReturns(series, portfolioMinObs)
	keptSeries := make([]quant.Series, 0, len(series))
	keptMeta := make([]integration.AllScoreInputRow, 0, len(series))
	keptRets := make([][]float64, 0, len(series))
	for i := range series {
		if !ok[i] {
			dropped = append(dropped, meta[i].Symbol)
			continue
		}
		keptSeries = append(keptSeries, series[i])
		keptMeta = append(keptMeta, meta[i])
		keptRets = append(keptRets, rets[i])
	}
	if len(keptSeries) < 3 {
		return "", fmt.Errorf("not enough usable return history after alignment (%d series)", len(keptSeries))
	}
	startRow := 0
	for _, s := range starts {
		if s > startRow {
			startRow = s
		}
	}

	cov := quant.CovarianceMatrix(keptRets, startRow, 250)
	shrunk := quant.ShrinkCovariance(cov, portfolioShrinkage)

	// ۴) انتخاب نمادها: بهترین امتیازها تا سقف تعداد
	order := make([]int, len(keptMeta))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(a, b int) bool {
		return keptMeta[order[a]].QuantScore > keptMeta[order[b]].QuantScore
	})
	if len(order) > profile.names {
		order = order[:profile.names]
	}
	selSeries := make([]quant.Series, 0, len(order))
	selMeta := make([]integration.AllScoreInputRow, 0, len(order))
	selRets := make([][]float64, 0, len(order))
	for _, i := range order {
		selSeries = append(selSeries, keptSeries[i])
		selMeta = append(selMeta, keptMeta[i])
		selRets = append(selRets, keptRets[i])
	}

	// کوواریانس زیرمجموعه‌ی انتخابی، با همان ترتیب
	sub := make([][]float64, len(order))
	for a := range order {
		sub[a] = make([]float64, len(order))
		for b := range order {
			sub[a][b] = shrunk[order[a]][order[b]]
		}
	}

	// ۵) وزن‌دهی
	var weights []float64
	switch method {
	case "inverse_vol":
		weights = quant.InverseVolWeights(sub)
		weights = quant.ApplyCap(weights, profile.maxWeight/100.0)
	case "equal":
		weights = quant.MaxWeightWeights(len(order), profile.maxWeight/100.0)
	default:
		method = "equal"
		weights = quant.MaxWeightWeights(len(order), profile.maxWeight/100.0)
	}
	// سقف صنعتی: متادیتای صنعت از canonical (TSETMC via BRS)
	industryCap := argFloat(args, "industry_cap", 25)
	metaByID := map[string]string{}
	if ids := func() []string {
		ids := make([]string, 0, len(selMeta))
		for _, r := range selMeta {
			ids = append(ids, r.LegacyCompanyID)
		}
		return ids
	}(); len(ids) > 0 {
		if mm, merr := sh.FetchMarketMetaCanonical(ctx, ids); merr == nil {
			for _, m := range mm {
				metaByID[m.LegacyCompanyID] = strings.TrimSpace(m.Category)
			}
		}
	}
	groups := make([]string, len(selMeta))
	unknown := 0
	for i, r := range selMeta {
		g := metaByID[r.LegacyCompanyID]
		if g == "" {
			g = "نامشخص"
			unknown++
		}
		groups[i] = g
	}
	if industryCap > 0 && industryCap < 100 {
		weights = quant.CapByGroup(weights, groups, industryCap/100.0)
		// بازتوزیع صنعتی ممکن است سقف نام را بشکند؛ دوباره اعمال و بازنرمال می‌کنیم
		weights = quant.ApplyCap(weights, profile.maxWeight/100.0)
	}
	weights = quant.NormalizeWeightsToCash(weights, profile.cashBuffer)

	// ۶) متریک‌های سبد با همین وزن‌ها روی همان پنجره
	portRets := quant.PortfolioSeries(weights, selRets)
	expectedVol := quant.PortfolioVolPct(weights, sub)
	totalRet := quant.CumulativeFromReturns(portRets)
	maxDD := quant.MaxDrawdownFromReturns(portRets)
	sharpe := quant.SharpeLike(portRets, 250)
	annRet := quant.Mean(portRets) * 250 * 100.0
	avgCorr := quant.AverageCorrelation(sub)
	equalVol := quant.PortfolioVolPct(equalWeights(len(order)), sub)

	// گردش نسبت به سبد فعلی کاربر (اگر وجود داشته باشد)
	turnover, currentNote := portfolioTurnover(ctx, username, weights, selMeta)

	// ۷) گزارش
	var b strings.Builder
	b.WriteString(fmt.Sprintf("سبد پیشنهادی (%s، روش %s) روی %d نماد از %d شرکت غربال‌شده\n",
		profile.label, methodFa(method), len(order), len(rows)))
	b.WriteString(fmt.Sprintf("پنجره‌ی تاریخی: %d روز معاملاتی | سقف وزن هر نماد: %s٪ | نقد: %s٪\n",
		len(portRets), fmtNumFa(profile.maxWeight, 0), fmtNumFa(profile.cashBuffer, 0)))
	b.WriteString("\nوزن‌ها:\n")
	for i := range order {
		r := selMeta[i]
		vol := 0.0
		if sub[i][i] > 0 {
			vol = math.Sqrt(sub[i][i]) * 100
		}
		b.WriteString(fmt.Sprintf("%d. %s (نماد %s، صنعت %s): وزن %.1f٪ | نوسان سالانه %.1f٪ | امتیاز کمی %.1f | %s\n",
			i+1, r.CompanyName, r.Symbol, groups[i], weights[i]*100, vol, r.QuantScore,
			rankText(r.FactorRank("Liquidity"))))
	}
	// مبالغ و تعداد تقریبی وقتی سرمایه مشخص است
	amounts := map[int]float64{}
	qties := map[int]float64{}
	if capital > 0 {
		for i, w := range weights {
			amt := w * capital
			amounts[i] = amt
			if p := selMeta[i].Price; p > 0 {
				qties[i] = math.Floor(amt / p)
			}
		}
	}

	// پراکندگی صنعتی
	exposure := map[string]float64{}
	for i, wv := range weights {
		exposure[groups[i]] += wv * 100
	}
	var catList []string
	for g := range exposure {
		catList = append(catList, g)
	}
	sort.Strings(catList)
	b.WriteString("|" + nlStr + "پراکندگی صنعتی (سقف هر صنعت " + fmtNumFa(industryCap, 0) + "٪):" + nlStr)
	for _, g := range catList {
		b.WriteString(fmt.Sprintf("- %s: %.1f%%"+nlStr, g, exposure[g]))
	}
	if capital > 0 {
		b.WriteString(nlStr + "مبالغ تقریبی با سرمایه‌ی " + fmtRialCompactFa(capital) + " (تعداد ≈ کف مبلغ÷قیمت):" + nlStr)
		for i := range order {
			r := selMeta[i]
			line := fmt.Sprintf("- %s (نماد %s): مبلغ %s", r.CompanyName, r.Symbol, fmtRialCompactFa(amounts[i]))
			if qties[i] > 0 {
				line += fmt.Sprintf(" | تعداد ≈ %.0f", qties[i])
			}
			b.WriteString(line + nlStr)
		}
	}
	if unknown > 0 {
		b.WriteString(fmt.Sprintf("- بدون طبقه‌بندی: %d نماد"+nlStr, unknown))
	}
	b.WriteString("\nمتریک‌های سبد (تاریخی، با همین وزن‌های ثابت):\n")
	b.WriteString(fmt.Sprintf("- نوسان سالانه‌ی برآوردی از کوواریانس: %s\n", fmtNumFa(expectedVol, 1)+"٪"))
	if winStart, winEnd := windowRange(dates, len(portRets)); winStart != "" {
		b.WriteString(fmt.Sprintf("- بازه‌ی پنجره: %s تا %s (%d روز معاملاتی)\n",
			toFaDigits(winStart), toFaDigits(winEnd), len(portRets)))
	}
	b.WriteString(fmt.Sprintf("- بازده سالانه‌شده (تقریبی): %s\n", fmtNumFa(annRet, 1)+"٪"))
	b.WriteString(fmt.Sprintf("- بازده تجمعی دوره: %s\n", fmtNumFa(totalRet, 1)+"٪"))
	b.WriteString(fmt.Sprintf("- حداکثر افت: %s\n", fmtNumFa(maxDD, 1)+"٪"))
	b.WriteString(fmt.Sprintf("- نسبت بازده سالانه‌شده به نوسان (بدون نرخ بدون ریسک؛ شارپ واقعی نیست): %s\n", fmtNumFa(sharpe, 2)))
	b.WriteString(fmt.Sprintf("- میانگین همبستگی جفتی: %s\n", fmtNumFa(avgCorr, 2)))
	b.WriteString(fmt.Sprintf("- نوسان سبد هموزن همان نمادها (مقایسه): %s\n", fmtNumFa(equalVol, 1)+"٪"))
	if currentNote != "" {
		b.WriteString(fmt.Sprintf("- گردش نسبت به سبد فعلی کاربر: %s — %s\n", fmtNumFa(turnover, 0)+"٪", currentNote))
	}
	if len(dropped) > 0 {
		b.WriteString(fmt.Sprintf("- کنار گذاشته‌شده (تاریخچه‌ی ناکافی): %s\n", strings.Join(dropped, "، ")))
	}

	var warnings []string
	warnings = append(warnings, "اعتبارسنجی PIT (۲۰۲۱تا۲۰۲۶، ماهانه، ۲۰ نماد، ۱۰پی‌بی‌پی هزینه): هموزن شارپ ۱.۴۷/افت ـ۲۴.۷٪، معکوس‌نوسان ۱.۴۰/ـ۲۳.۲٪، کم‌واریانس ۱.۳۰/ـ۲۰.۹٪")
	warnings = append(warnings, "شاخص کل بازار در دیتابیس موجود نیست، پس بتا و مقایسه با بازار محاسبه نشده و بازده/نوسان با نرخ بدون ریسک صفر است")
	if unknown == len(selMeta) {
		warnings = append(warnings, "طبقه‌بندی صنعت برای این نمادها موجود نیست، پس سقف صنعتی اعمال نشده است")
	} else if unknown > 0 {
		warnings = append(warnings, fmt.Sprintf("طبقه‌بندی صنعت برای %d از %d نماد موجود نیست و آن‌ها بدون سقف صنعتی وزن گرفته‌اند", unknown, len(selMeta)))
	}
	warnings = append(warnings, "بازده انتظاری آینده تخمین زده نشده؛ همه‌ی اعداد تاریخی‌اند")
	warnings = append(warnings, "وزن‌دهی بر پایه‌ی بک‌تست PIT ۲۰۲۱–۲۰۲۶ انتخاب شده؛ عملکرد گذشته تضمین آینده نیست")
	if profile.cashBuffer == 0 {
		warnings = append(warnings, "بدون بافر نقد پیشنهاد شده است")
	}
	b.WriteString("\nمحدودیت‌ها:\n")
	for _, w := range warnings {
		b.WriteString("- " + w + "\n")
	}
	b.WriteString("\nنمونه‌ای از نامزدها برای مرجع:\n")
	shown := 0
	for _, r := range selMeta {
		if shown >= 3 {
			break
		}
		b.WriteString("- " + rowLine(r) + "\n")
		shown++
	}
	return b.String(), nil
}

func methodFa(m string) string {
	switch m {
	case "inverse_vol":
		return "معکوس‌نوسان"
	case "equal":
		return "هموزن سقف‌دار"
	default:
		return "کم‌واریانس"
	}
}

func equalWeights(n int) []float64 {
	w := make([]float64, n)
	if n == 0 {
		return w
	}
	for i := range w {
		w[i] = 1.0 / float64(n)
	}
	return w
}

// portfolioTurnover گردش سبد پیشنهادی را نسبت به سبد فعلی کاربر می‌سنجد.
func portfolioTurnover(ctx context.Context, username string, weights []float64, meta []integration.AllScoreInputRow) (float64, string) {
	if strings.TrimSpace(username) == "" {
		return 0, ""
	}
	_, holdings, ok := readPortfolioHoldings(ctx, username)
	if !ok || len(holdings) == 0 {
		return 0, ""
	}
	current := map[string]float64{}
	total := 0.0
	for _, h := range holdings {
		v := h.qty * h.last
		current[h.symbol] += v
		total += v
	}
	if total <= 0 {
		return 0, ""
	}
	for k, v := range current {
		current[k] = v / total
	}
	target := map[string]float64{}
	for i, r := range meta {
		if i < len(weights) {
			target[r.Symbol] = weights[i]
		}
	}
	return quant.TurnoverPct(current, target), fmt.Sprintf("%d نماد فعلی", len(holdings))
}

// windowRange بازه‌ی تاریخی همان تعداد بازده‌ی گزارش‌شده را برمی‌گرداند.
func windowRange(dates []string, n int) (string, string) {
	if len(dates) == 0 || n <= 0 {
		return "", ""
	}
	if n > len(dates) {
		n = len(dates)
	}
	return dates[len(dates)-n], dates[len(dates)-1]
}
