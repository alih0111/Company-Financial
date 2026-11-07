package handlers

import (
	"context"
	"database/sql"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"net/http"
	"time"
)

func getCanonicalFinancialStatements(c *gin.Context, companyName string, limit int) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(503, gin.H{"error": "صورت‌های مالی موقتاً در دسترس نیست"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 6*time.Second)
	defer cancel()
	companies, err := db.QueryContext(ctx, `SELECT DISTINCT co.id::text FROM core.companies co LEFT JOIN core.securities s ON s.company_id=co.id
		WHERE co.is_active AND (co.display_name=$1 OR co.normalized_name=$1 OR s.codal_symbol=$1 OR co.id::text=$1) LIMIT 2`, normalizePersian(companyName))
	if err != nil {
		c.JSON(503, gin.H{"error": "جست‌وجوی شرکت ناموفق بود"})
		return
	}
	var ids []string
	for companies.Next() {
		var id string
		if companies.Scan(&id) != nil {
			companies.Close()
			c.Status(503)
			return
		}
		ids = append(ids, id)
	}
	err = companies.Err()
	companies.Close()
	if err != nil {
		c.Status(503)
		return
	}
	if len(ids) == 0 {
		c.JSON(404, gin.H{"error": "شرکت پیدا نشد"})
		return
	}
	if len(ids) > 1 {
		c.JSON(409, gin.H{"error": "نام شرکت مبهم است؛ نماد دقیق را انتخاب کنید"})
		return
	}
	// Pick one complete parse of one report version per period and statement;
	// never mix metrics from superseded versions or unfinished parsing runs.
	rows, err := db.QueryContext(ctx, `WITH ranked AS (
		SELECT fs.*,COALESCE(r.jalali_period_text,fs.period_end_date::text) AS display_date,
		 row_number() OVER (PARTITION BY fs.period_end_date,fs.statement_type ORDER BY r.published_at DESC NULLS LAST,rv.version_no DESC,pr.finished_at DESC,fs.id DESC) AS priority
		FROM fundamentals.financial_statements fs JOIN ingestion.reports r ON r.id=fs.report_id
		JOIN ingestion.report_versions rv ON rv.id=fs.report_version_id
		JOIN ingestion.parse_runs pr ON pr.id=fs.parse_run_id
		WHERE fs.company_id=$1 AND pr.status='completed' AND (r.published_at IS NULL OR r.published_at<=now())
		AND (r.period_end_date IS NULL OR r.period_end_date=fs.period_end_date)
	), dates AS (SELECT DISTINCT period_end_date FROM ranked WHERE priority=1 ORDER BY period_end_date DESC LIMIT $2)
	SELECT fs.period_end_date::text,fs.display_date,COALESCE(fs.duration_months,0),COALESCE(fs.fiscal_year,0),
	 f.metric_code,f.comparison_type,f.period_order,f.canonical_value,COALESCE(f.canonical_unit,'')
	FROM ranked fs JOIN dates d ON d.period_end_date=fs.period_end_date
	JOIN fundamentals.financial_facts f ON f.statement_id=fs.id
	WHERE fs.priority=1 ORDER BY fs.period_end_date DESC,fs.statement_type,f.metric_code,f.period_order`, ids[0], limit)
	if err != nil {
		c.JSON(503, gin.H{"error": "خواندن صورت‌های مالی ناموفق بود"})
		return
	}
	defer rows.Close()
	periods := []fsPeriod{}
	indices := map[string]int{}
	for rows.Next() {
		var date, display, metric, unit string
		var comparison sql.NullString
		var duration, year, order int
		var value sql.NullFloat64
		if rows.Scan(&date, &display, &duration, &year, &metric, &comparison, &order, &value, &unit) != nil {
			c.Status(503)
			return
		}
		index, ok := indices[date]
		if !ok {
			index = len(periods)
			indices[date] = index
			periods = append(periods, fsPeriod{ReportDate: display, AmountsInRial: true})
		}
		p := &periods[index]
		if duration > 0 {
			p.DurationMonths = duration
		}
		if year > 0 {
			p.FiscalYear = year
		}
		setCanonicalFinancialFact(p, metric, comparison.String, order, fsNull(value), unit)
	}
	if rows.Err() != nil {
		c.Status(503)
		return
	}
	for i := range periods {
		p := &periods[i]
		inc, bs, cf := p.IncomeStatement, p.BalanceSheet, p.CashFlow
		p.Derived = fsDerived{
			NetMarginPct: fsPct(inc.NetProfit.Current, inc.Revenue.Current), RevenueYoYPct: fsGrowthPct(inc.Revenue.Current, inc.Revenue.LY),
			NetProfitYoYPct: fsGrowthPct(inc.NetProfit.Current, inc.NetProfit.LY), EPSYoYPct: fsGrowthPct(inc.EPS, inc.EPSLY),
			CurrentRatio: fsDiv(bs.CurrentAssets.Current, bs.CurrentLiabilities.Current), DebtToAssetsPct: fsPct(bs.TotalLiabilities.Current, bs.TotalAssets.Current),
			CurrentAssetsPct: fsPct(bs.CurrentAssets.Current, bs.TotalAssets.Current), CashConversionPct: fsPct(cf.Operating.Current, inc.NetProfit.Current),
			NonCurrentAssets: fsAmount{Current: fsSub(bs.TotalAssets.Current, bs.CurrentAssets.Current)}, NonCurrentLiabilities: fsAmount{Current: fsSub(bs.TotalLiabilities.Current, bs.CurrentLiabilities.Current)},
		}
	}
	c.JSON(http.StatusOK, fsResponse{CompanyName: companyName, UnitNote: "منبع PostgreSQL؛ مبالغ پولی بر حسب ریال و EPS بر حسب ریال/سهم است. مقادیر ناموجود نمایش داده نمی‌شوند. برای تبدیل مبالغ به هر سهم، شواهد تعداد سهام در تاریخ گزارش لازم است؛ از سرمایهٔ اسمی تعداد سهام استنتاج نمی‌شود.", Periods: periods})
}

func setCanonicalFinancialFact(p *fsPeriod, metric, comparison string, order int, value *float64, unit string) {
	if value == nil {
		return
	}
	switch comparison {
	case "current":
		order = 1
	case "prior_year_same_period":
		order = 2
	case "prior_fiscal_year":
		order = 3
	case "":
	default:
		return
	}
	if metric == "eps" || metric == "operating_eps" {
		if unit != "rial_per_share" {
			return
		}
		if metric == "eps" && order == 1 {
			p.IncomeStatement.EPS = value
		}
		if metric == "eps" && order == 2 {
			p.IncomeStatement.EPSLY = value
		}
		if metric == "operating_eps" && order == 1 {
			p.IncomeStatement.OperatingEPS = value
		}
		return
	}
	if unit != "rial" {
		return
	}
	if metric == "capital" && order == 1 {
		p.IncomeStatement.Capital = value
		return
	}
	fields := map[string]*fsAmount{
		"revenue": &p.IncomeStatement.Revenue, "operating_profit": &p.IncomeStatement.Operating, "net_profit": &p.IncomeStatement.NetProfit,
		"finance_cost": &p.IncomeStatement.FinanceCosts, "other_non_operating": &p.IncomeStatement.OtherNonOp,
		"total_assets": &p.BalanceSheet.TotalAssets, "current_assets": &p.BalanceSheet.CurrentAssets, "total_liabilities": &p.BalanceSheet.TotalLiabilities,
		"current_liabilities": &p.BalanceSheet.CurrentLiabilities, "total_equity": &p.BalanceSheet.TotalEquity, "operating_cash_flow": &p.CashFlow.Operating,
	}
	if field := fields[metric]; field != nil {
		switch order {
		case 1:
			field.Current = value
		case 2:
			field.LY = value
		case 3:
			field.FYPrev = value
		}
	}
}
