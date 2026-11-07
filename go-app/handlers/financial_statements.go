package handlers

import (
	"database/sql"
	"math"
	"net/http"
	"strconv"
	"strings"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// صورت‌های مالی کامل برای یک نماد — سود و زیان، ترازنامه و جریان نقد
// عملیاتی، از جدول miandore2 (خواندنیِ فقط‌خواندنی؛ هیچ مقداری اینجا
// بازمحاسبه یا در دیتابیس نوشته نمی‌شود).
//
// واحد مبالغ: کدال به ازای هر اعلام، واحد جدول را ناشر انتخاب می‌کند
// (ریال/هزار ریال/میلیون ریال/…) و مقادیر هم‌واحدِ همان گزارش ذخیره
// شده‌اند. در نتیجه:
//   - EPS ها بر حسب «ریال بر سهم» قطعی‌اند (عنوان سطر در کدال).
//   - درصدها و نسبت‌ها (حاشیه، رشد، نسبت جاری، …) بی‌واحد و قابل اتکا هستند.
//   - مقادیر مطلق فقط «هم‌واحد گزارش»‌اند؛ سنجش سازگاری هر ردیف با
//     لنگر EPS×سرمایه در فیلد eps_capital_anchor داده می‌شود تا کلاینت
//     در صورت مغایرت مقیاس، هشدار «واحد نامطمئن» نشان دهد.
// لنگر: Num1(EPS ریالی) × Num2(سرمایه) ≈ سود خالص × ۱۰۰۰ در ردیف‌های سالم
// (قرارداد مشابه NPUnitRatio در vw_AIStockMetrics).

type fsAmount struct {
	Current *float64 `json:"current"`
	LY      *float64 `json:"ly,omitempty"`
	FYPrev  *float64 `json:"fy_prev,omitempty"`
}

type fsIncomeStatement struct {
	EPS          *float64 `json:"eps_rial"`           // Num1_Value1 — ریال/سهم
	EPSLY        *float64 `json:"eps_ly_rial"`        // Num1_Value2 — ریال/سهم
	OperatingEPS *float64 `json:"operating_eps_rial"` // Num4_Value1 — ریال/سهم
	Capital      *float64 `json:"capital"`            // Num2_Value1 — هم‌واحد گزارش
	Revenue      fsAmount `json:"revenue"`
	Operating    fsAmount `json:"operating_profit"` // OperatingProfitNew — مقیاس تاریخی مخلوط (per-share/مطلق)
	FinanceCosts fsAmount `json:"finance_costs"`
	OtherNonOp   fsAmount `json:"other_non_operating"`
	NetProfit    fsAmount `json:"net_profit"`
}

type fsBalanceSheet struct {
	TotalAssets        fsAmount `json:"total_assets"`
	CurrentAssets      fsAmount `json:"current_assets"`
	TotalLiabilities   fsAmount `json:"total_liabilities"`
	CurrentLiabilities fsAmount `json:"current_liabilities"`
	TotalEquity        fsAmount `json:"total_equity"`
}

type fsCashFlow struct {
	Operating fsAmount `json:"operating"` // تجمعی از ابتدای سال مالی، مثل سود
}

type fsDerived struct {
	NetMarginPct          *float64 `json:"net_margin_pct"`
	RevenueYoYPct         *float64 `json:"revenue_yoy_pct"`
	NetProfitYoYPct       *float64 `json:"net_profit_yoy_pct"`
	EPSYoYPct             *float64 `json:"eps_yoy_pct"`
	CurrentRatio          *float64 `json:"current_ratio"`
	DebtToAssetsPct       *float64 `json:"debt_to_assets_pct"`
	CurrentAssetsPct      *float64 `json:"current_assets_pct"`
	CashConversionPct     *float64 `json:"cash_conversion_pct"`
	NonCurrentAssets      fsAmount `json:"non_current_assets"`
	NonCurrentLiabilities fsAmount `json:"non_current_liabilities"`
}

type fsPeriod struct {
	AmountsInRial    bool              `json:"amounts_in_rial,omitempty"`
	ReportDate       string            `json:"report_date"`
	DurationMonths   int               `json:"duration_months"`
	FiscalYear       int               `json:"fiscal_year"`
	UnitConsistent   *bool             `json:"unit_consistent"`
	EpsCapitalAnchor *float64          `json:"eps_capital_anchor"`
	IncomeStatement  fsIncomeStatement `json:"income_statement"`
	BalanceSheet     fsBalanceSheet    `json:"balance_sheet"`
	CashFlow         fsCashFlow        `json:"cash_flow"`
	Derived          fsDerived         `json:"derived"`
}

type fsResponse struct {
	CompanyName string     `json:"company_name"`
	UnitNote    string     `json:"unit_note"`
	Periods     []fsPeriod `json:"periods"`
}

const fsUnitNote = "EPS بر حسب ریال/سهم؛ مبالغ هم‌واحد گزارش‌های کدال ذخیره شده‌اند (واحد اعلامی بین گزارش‌ها متغیر است). درصدها و نسبت‌ها بی‌واحد هستند."

func fsNull(v sql.NullFloat64) *float64 {
	if !v.Valid {
		return nil
	}
	f := v.Float64
	return &f
}

func fsDiv(a, b *float64) *float64 {
	if a == nil || b == nil || *b == 0 {
		return nil
	}
	v := *a / *b
	return &v
}

func fsPct(part, whole *float64) *float64 {
	if part == nil || whole == nil || *whole == 0 {
		return nil
	}
	v := *part / *whole * 100
	return &v
}

func fsSub(a, b *float64) *float64 {
	if a == nil || b == nil {
		return nil
	}
	v := *a - *b
	return &v
}

// fsGrowthPct رشد درصدی a نسبت به b؛ مخرج صفر یا ناموجود → nil
// (رشد از مبنای صفر بی‌معناست).
func fsGrowthPct(a, b *float64) *float64 {
	if a == nil || b == nil || *b == 0 {
		return nil
	}
	v := (*a - *b) / math.Abs(*b) * 100
	return &v
}

// fsJalaliParts "1403/12/29" → (1403, 12, true)
func fsJalaliParts(reportDate string) (int, int, bool) {
	parts := strings.Split(strings.TrimSpace(reportDate), "/")
	if len(parts) < 2 {
		return 0, 0, false
	}
	year, errY := strconv.Atoi(strings.TrimSpace(parts[0]))
	month, errM := strconv.Atoi(strings.TrimSpace(parts[1]))
	if errY != nil || errM != nil || year < 1300 || month < 1 || month > 12 {
		return 0, 0, false
	}
	return year, month, true
}

// GetFinancialStatements سامان‌دهنده GET /api/financial-statements
func GetFinancialStatements(c *gin.Context) {
	companyName := strings.TrimSpace(c.Query("companyName"))
	if companyName == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "companyName is required"})
		return
	}

	limit := 12
	if v, err := strconv.Atoi(c.Query("limit")); err == nil && v > 0 {
		limit = v
	}
	if limit > 40 {
		limit = 40
	}
	if config.SQLServerMode() == "offline_expected" {
		getCanonicalFinancialStatements(c, companyName, limit)
		return
	}

	db := config.GetDB()
	defer db.Close()

	// جدیدترین گزارش‌ها اول؛ فقط ردیف‌هایی که تاریخ جلالی معتبر دارند
	// (همان قرارداد getProfitPoints).
	query := `
        SELECT TOP (@limit)
            CompanyName, ReportDate,
            Num1_Value1, Num1_Value2, Num2_Value1, Num4_Value1,
            RevenueNew, RevenueLastYear, RevenueFYPrev,
            OperatingProfitNew, OperatingProfitLastYear, OperatingProfitFYPrev,
            FinanceCostsNew, FinanceCostsLastYear,
            OtherNonOpNew, OtherNonOpLastYear,
            NetProfitAmount, NetProfitAmountLY, NetProfitAmountFYPrev,
            TotalAssets, TotalAssetsLY,
            CurrentAssets, CurrentAssetsLY,
            TotalLiabilities, TotalLiabilitiesLY,
            CurrentLiabilities, CurrentLiabilitiesLY,
            TotalEquity, TotalEquityLY,
            OperatingCashFlow, OperatingCashFlowLY, OperatingCashFlowFYPrev
        FROM dbo.miandore2
        WHERE CompanyName = @companyName
          AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
        ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
    `

	rows, err := db.Query(query,
		sql.Named("limit", limit),
		sql.Named("companyName", companyName),
	)
	if err != nil {
		// مثل GetSalesData: در حالت offline_expected خطای اتصال را
		// صریح و سریع اعلام کن؛ وگرنه خطای عمومی.
		if config.SQLServerMode() == "offline_expected" {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "financial statements unavailable", "reason": "sqlserver_offline_expected"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer rows.Close()

	periods := make([]fsPeriod, 0)
	for rows.Next() {
		var (
			companyNameCol, reportDate string
			eps, epsLY, capital, opEPS sql.NullFloat64
			rev, revLY, revFY          sql.NullFloat64
			op, opLY, opFY             sql.NullFloat64
			fc, fcLY                   sql.NullFloat64
			non, nonLY                 sql.NullFloat64
			np, npLY, npFY             sql.NullFloat64
			ta, taLY                   sql.NullFloat64
			ca, caLY                   sql.NullFloat64
			tl, tlLY                   sql.NullFloat64
			cl, clLY                   sql.NullFloat64
			eq, eqLY                   sql.NullFloat64
			ocf, ocfLY, ocfFY          sql.NullFloat64
		)
		if err := rows.Scan(
			&companyNameCol, &reportDate,
			&eps, &epsLY, &capital, &opEPS,
			&rev, &revLY, &revFY,
			&op, &opLY, &opFY,
			&fc, &fcLY,
			&non, &nonLY,
			&np, &npLY, &npFY,
			&ta, &taLY,
			&ca, &caLY,
			&tl, &tlLY,
			&cl, &clLY,
			&eq, &eqLY,
			&ocf, &ocfLY, &ocfFY,
		); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		p := fsPeriod{ReportDate: reportDate}

		// طول دوره تجمعی از ماه تاریخ جلالی: سال مالی عمدتاً با اسفند
		// تمام می‌شود → ماه ۳/۶/۹/۱۲ = تجمعی ۳/۶/۹/۱۲ ماهه.
		if year, month, ok := fsJalaliParts(reportDate); ok {
			if month == 12 {
				p.DurationMonths = 12
			} else {
				p.DurationMonths = month
			}
			p.FiscalYear = year
		}

		// لنگر سازگاری واحد ردیف: EPS × سرمایه ≈ سود خالص × ۱۰۰۰
		if eps.Valid && capital.Valid && np.Valid && np.Float64 != 0 && eps.Float64 != 0 {
			anchor := (eps.Float64 * capital.Float64) / (np.Float64 * 1000)
			p.EpsCapitalAnchor = &anchor
			consistent := math.Abs(anchor-1) <= 0.05
			p.UnitConsistent = &consistent
		}

		revCur, revLast, revPrev := fsNull(rev), fsNull(revLY), fsNull(revFY)
		npCur, npLast, npPrev := fsNull(np), fsNull(npLY), fsNull(npFY)
		epsCur, epsLYCur := fsNull(eps), fsNull(epsLY)

		p.IncomeStatement = fsIncomeStatement{
			EPS:          epsCur,
			EPSLY:        epsLYCur,
			OperatingEPS: fsNull(opEPS),
			Capital:      fsNull(capital),
			Revenue:      fsAmount{Current: revCur, LY: revLast, FYPrev: revPrev},
			Operating:    fsAmount{Current: fsNull(op), LY: fsNull(opLY), FYPrev: fsNull(opFY)},
			FinanceCosts: fsAmount{Current: fsNull(fc), LY: fsNull(fcLY)},
			OtherNonOp:   fsAmount{Current: fsNull(non), LY: fsNull(nonLY)},
			NetProfit:    fsAmount{Current: npCur, LY: npLast, FYPrev: npPrev},
		}

		p.BalanceSheet = fsBalanceSheet{
			TotalAssets:        fsAmount{Current: fsNull(ta), LY: fsNull(taLY)},
			CurrentAssets:      fsAmount{Current: fsNull(ca), LY: fsNull(caLY)},
			TotalLiabilities:   fsAmount{Current: fsNull(tl), LY: fsNull(tlLY)},
			CurrentLiabilities: fsAmount{Current: fsNull(cl), LY: fsNull(clLY)},
			TotalEquity:        fsAmount{Current: fsNull(eq), LY: fsNull(eqLY)},
		}

		p.CashFlow = fsCashFlow{
			Operating: fsAmount{Current: fsNull(ocf), LY: fsNull(ocfLY), FYPrev: fsNull(ocfFY)},
		}

		taCur := fsNull(ta)
		caCur := fsNull(ca)
		tlCur := fsNull(tl)
		clCur := fsNull(cl)
		ocfCur := fsNull(ocf)

		p.Derived = fsDerived{
			NetMarginPct:          fsPct(npCur, revCur),
			RevenueYoYPct:         fsGrowthPct(revCur, revLast),
			NetProfitYoYPct:       fsGrowthPct(npCur, npLast),
			EPSYoYPct:             fsGrowthPct(epsCur, epsLYCur),
			CurrentRatio:          fsDiv(caCur, clCur),
			DebtToAssetsPct:       fsPct(tlCur, taCur),
			CurrentAssetsPct:      fsPct(caCur, taCur),
			CashConversionPct:     fsPct(ocfCur, npCur),
			NonCurrentAssets:      fsAmount{Current: fsSub(taCur, caCur)},
			NonCurrentLiabilities: fsAmount{Current: fsSub(tlCur, clCur)},
		}

		periods = append(periods, p)
	}
	if err := rows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, fsResponse{
		CompanyName: companyName,
		UnitNote:    fsUnitNote,
		Periods:     periods,
	})
}
