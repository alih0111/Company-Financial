package handlers

import (
	"database/sql"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// ExportScoresCSV خروجی CSV با تمام جزئیات امتیازات همه‌ی نمادها.
// مناسب برای ارسال به هوش مصنوعی یا باز کردن در Excel.
func ExportScoresCSV(c *gin.Context) {
	limit := parseIntQuery(c, "limit", 1000)
	if limit > 5000 {
		limit = 5000
	}

	minTrade := parseFloatQuery(c, "min_avg_trade_value_30d", 0)

	db := config.GetDB()
	defer db.Close()

	query := `
        SELECT TOP (@limit)
            Symbol,
            CompanyName,
            QuantScore,
            GrowthScore,
            ProfitabilityScore,
            ValuationScore,
            MarketScore,
            DataQualityScore,

            SalesGrowth12M,
            SalesGrowth3M,
            RevenueGrowthYoY,
            SalesStability,
            OperatingProfitGrowthYoY,
            NetProfitGrowth4Reports,

            OperatingMarginLatest,
            NetMarginLatest,
            OperatingMarginTrend,
            OperatingMargin12M,
            NetProfitMargin12M,
            InterestCoverage,
            NonOperatingPct,

            LatestEPS,
            LatestPrice,
            PEApprox,
            PSRatio,

            PriceReturn7D,
            PriceReturn30D,
            PriceReturn90D,

            AvgTradeValue30D,
            AvgVolume30D,
            Volatility30D,
            PricePosition90D,

            BadPEFlag,
            WeakSalesFlag,
            WeakOperatingProfitFlag,
            WeakLiquidityFlag,
            LossMakerFlag,
            WeakCoverageFlag,
            MarginContractionFlag
        FROM dbo.vw_AIStockMetrics
        WHERE ISNULL(AvgTradeValue30D, 0) >= @minTrade
        ORDER BY QuantScore DESC
	`

	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("minTrade", minTrade),
	)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	// هدر CSV با توضیحات فارسی
	header := []string{
		"نماد",
		"نام_شرکت",
		"امتیاز_کل",
		"امتیاز_رشد",
		"امتیاز_سودآوری",
		"امتیاز_ارزش‌گذاری",
		"امتیاز_بازار",
		"کیفیت_داده",

		"رشد_فروش_سالانه_٪",
		"رشد_فروش_۳ماهه_٪",
		"رشد_درآمد_YoY_٪",
		"ثبات_فروش",
		"رشد_سود_عملیاتی_٪",
		"رشد_سود_خالص_٪",

		"حاشیه_عملیاتی_٪",
		"حاشیه_خالص_٪",
		"روند_حاشیه_٪",
		"حاشیه_عملیاتی_۱۲ماه_٪",
		"حاشیه_خالص_۱۲ماه_٪",
		"پوشش_بهره",
		"سهم_غیرعملیاتی_٪",

		"EPS",
		"قیمت",
		"P/E",
		"P/S",

		"بازده_۷روز_٪",
		"بازده_۳۰روز_٪",
		"بازده_۹۰روز_٪",

		"ارزش_معاملات_۳۰روز",
		"حجم_میانگین_۳۰روز",
		"نوسان_۳۰روز_٪",
		"جایگاه_قیمتی_۹۰روز_٪",

		"فلگ_PE_نامعتبر",
		"فلگ_فروش_ضعیف",
		"فلگ_سود_عملیاتی_ضعیف",
		"فلگ_نقدشوندگی_ضعیف",
		"فلگ_زیان‌ده",
		"فلگ_پوشش_بهره_ضعیف",
		"فلگ_انقباض_حاشیه",
	}

	var sb strings.Builder

	// BOM برای Excel فارسی
	sb.WriteString("\uFEFF")

	// هدر
	sb.WriteString(strings.Join(header, ","))
	sb.WriteString("\n")

	count := 0
	for rows.Next() {
		var symbol, companyName sql.NullString
		var quant, growth, profit, val, market, quality sql.NullFloat64

		var sg12, sg3, revYoY, stability, opGrowth, netGrowth sql.NullFloat64
		var opMargin, netMargin, marginTrend, opMargin12, netMargin12, coverage, nonOp sql.NullFloat64
		var eps, price, pe, ps sql.NullFloat64
		var ret7, ret30, ret90 sql.NullFloat64
		var tradeVal, avgVol, volat, pos90 sql.NullFloat64
		var badPE, weakSales, weakOp, weakLiq, lossMaker, weakCov, marginCont sql.NullBool

		if err := rows.Scan(
			&symbol, &companyName,
			&quant, &growth, &profit, &val, &market, &quality,
			&sg12, &sg3, &revYoY, &stability, &opGrowth, &netGrowth,
			&opMargin, &netMargin, &marginTrend, &opMargin12, &netMargin12, &coverage, &nonOp,
			&eps, &price, &pe, &ps,
			&ret7, &ret30, &ret90,
			&tradeVal, &avgVol, &volat, &pos90,
			&badPE, &weakSales, &weakOp, &weakLiq, &lossMaker, &weakCov, &marginCont,
		); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		vals := []string{
			csvStr(symbol.String),
			csvStr(companyName.String),
			csvNum(quant.Float64, 1),
			csvNum(growth.Float64, 1),
			csvNum(profit.Float64, 1),
			csvNum(val.Float64, 1),
			csvNum(market.Float64, 1),
			csvPct(quality.Float64, 0),

			csvNum(sg12.Float64, 1),
			csvNum(sg3.Float64, 1),
			csvNum(revYoY.Float64, 1),
			csvNum(stability.Float64, 2),
			csvNum(opGrowth.Float64, 1),
			csvNum(netGrowth.Float64, 1),

			csvNum(opMargin.Float64, 1),
			csvNum(netMargin.Float64, 1),
			csvNum(marginTrend.Float64, 1),
			csvNum(opMargin12.Float64, 1),
			csvNum(netMargin12.Float64, 1),
			csvNum(coverage.Float64, 2),
			csvNum(nonOp.Float64, 1),

			csvNum(eps.Float64, 2),
			csvNum(price.Float64, 0),
			csvNum(pe.Float64, 1),
			csvNum(ps.Float64, 2),

			csvNum(ret7.Float64, 1),
			csvNum(ret30.Float64, 1),
			csvNum(ret90.Float64, 1),

			csvNum(tradeVal.Float64, 0),
			csvNum(avgVol.Float64, 0),
			csvNum(volat.Float64, 2),
			csvNum(pos90.Float64, 1),

			csvBool(badPE.Bool),
			csvBool(weakSales.Bool),
			csvBool(weakOp.Bool),
			csvBool(weakLiq.Bool),
			csvBool(lossMaker.Bool),
			csvBool(weakCov.Bool),
			csvBool(marginCont.Bool),
		}

		sb.WriteString(strings.Join(vals, ","))
		sb.WriteString("\n")
		count++
	}

	filename := fmt.Sprintf("stock_scores_%d_rows.csv", count)
	c.Header("Content-Type", "text/csv; charset=utf-8")
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	c.String(http.StatusOK, sb.String())
}

func csvStr(s string) string {
	s = strings.ReplaceAll(s, "\"", "'")
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.ReplaceAll(s, "\r", "")
	return "\"" + s + "\""
}

func csvNum(f float64, digits int) string {
	if f == 0 {
		return ""
	}
	return strconv.FormatFloat(f, 'f', digits, 64)
}

func csvPct(f float64, digits int) string {
	if f == 0 {
		return ""
	}
	return strconv.FormatFloat(f*100, 'f', digits, 64)
}

func csvBool(b bool) string {
	if b {
		return "بله"
	}
	return ""
}
