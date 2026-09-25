// Command shadowcheck runs a bounded, read-only shadow comparison between the
// legacy SQL Server path and canonical PostgreSQL for the Phase-1 endpoints.
//
// It never writes to either database. It is intended to be run manually with:
//
//	set CDF_READ_MODE=shadow
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	go run ./cmd/shadowcheck
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"go-app/config"
	"go-app/integration"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "shadowcheck error:", err)
		os.Exit(1)
	}
}

func run() error {
	sh := integration.Default()
	if !sh.Enabled() {
		st := sh.Status()
		return fmt.Errorf("shadow reads are not enabled (mode=%s canonical_configured=%v err=%s); set CDF_READ_MODE=shadow and CDF_CANONICAL_DB",
			st.ReadMode, st.CanonicalConfigured, st.CanonicalError)
	}
	st := sh.RefreshStatus(context.Background())
	fmt.Printf("shadow status: mode=%s score_version=%s run=%s as_of=%s\n",
		st.ReadMode, st.ScoreVersion, st.ScoreRunID, st.ScoreAsOf)

	db := config.GetDB()
	defer db.Close()
	ctx := context.Background()

	results := []integration.EndpointResult{}

	// 1) Identity: full company name set.
	namesStart := time.Now()
	names, err := legacyCompanyNames(db)
	if err != nil {
		return fmt.Errorf("legacy company names: %w", err)
	}
	r1 := sh.CompareCompanyNames(ctx, names, time.Since(namesStart))
	results = append(results, r1)
	fmt.Printf("[1] %s legacy=%d canonical=%d matched=%d expected=%d unexpected=%d errors=%d\n",
		r1.Endpoint, r1.LegacyRows, r1.CanonicalRows, r1.Matched, r1.ExpectedDiffs, r1.Unexpected, r1.Errors)

	// 2) Analytics: top-N legacy score rows, then canonical by the same IDs.
	sumStart := time.Now()
	scores, err := legacyTopScores(db, 20, 0)
	if err != nil {
		return fmt.Errorf("legacy top scores: %w", err)
	}
	r2 := sh.CompareScores(ctx, scores, time.Since(sumStart))
	results = append(results, r2)
	fmt.Printf("[2] %s legacy=%d canonical=%d matched=%d expected=%d unexpected=%d errors=%d\n",
		r2.Endpoint, r2.LegacyRows, r2.CanonicalRows, r2.Matched, r2.ExpectedDiffs, r2.Unexpected, r2.Errors)

	// 3) Market: a bounded heterogeneous symbol sample drawn from the score rows.
	symbols := distinctSymbols(scores, 6)
	if len(symbols) == 0 {
		symbols = []string{"زگلدشت", "پسهند", "کربن"}
	}
	for _, sym := range symbols {
		mStart := time.Now()
		rows, err := legacyPriceHistory(db, sym, 30)
		if err != nil {
			fmt.Fprintf(os.Stderr, "legacy price history for %q: %v\n", sym, err)
			continue
		}
		r3 := sh.ComparePriceHistory(ctx, sym, 30, rows, time.Since(mStart))
		results = append(results, r3)
		fmt.Printf("[3] %s symbol=%s legacy=%d canonical=%d matched=%d expected=%d unexpected=%d errors=%d\n",
			r3.Endpoint, sym, r3.LegacyRows, r3.CanonicalRows, r3.Matched, r3.ExpectedDiffs, r3.Unexpected, r3.Errors)
	}

	// 4) Fundamentals: heterogeneous per-company samples for both endpoints.
	sampleNames, err := sampleCompanyNames(db)
	if err != nil {
		return fmt.Errorf("sample names: %w", err)
	}
	for _, name := range sampleNames {
		mStart := time.Now()
		monthly, err := legacyMonthly(db, name)
		if err != nil {
			fmt.Fprintf(os.Stderr, "legacy monthly for %q: %v\n", name, err)
			continue
		}
		r4 := sh.CompareSalesData2(ctx, monthly, time.Since(mStart))
		results = append(results, r4)
		fmt.Printf("[4] %s company=%s legacy=%d canonical=%d matched=%d expected=%d unexpected=%d errors=%d\n",
			r4.Endpoint, name, r4.LegacyRows, r4.CanonicalRows, r4.Matched, r4.ExpectedDiffs, r4.Unexpected, r4.Errors)

		fStart := time.Now()
		financial, err := legacyFinancial(db, name)
		if err != nil {
			fmt.Fprintf(os.Stderr, "legacy financial for %q: %v\n", name, err)
			continue
		}
		r5 := sh.CompareSalesData(ctx, financial, time.Since(fStart))
		results = append(results, r5)
		fmt.Printf("[5] %s company=%s legacy=%d canonical=%d matched=%d expected=%d unexpected=%d errors=%d\n",
			r5.Endpoint, name, r5.LegacyRows, r5.CanonicalRows, r5.Matched, r5.ExpectedDiffs, r5.Unexpected, r5.Errors)
	}

	if err := sh.Collector().Flush(); err != nil {
		return fmt.Errorf("flush summary: %w", err)
	}
	if err := os.MkdirAll(sh.Config().OutputDir, 0o755); err != nil {
		return err
	}
	diffPath := filepath.Join(sh.Config().OutputDir, "shadow_differences.csv")
	if err := integration.WriteDifferences(diffPath, results); err != nil {
		return fmt.Errorf("write differences: %w", err)
	}
	totals := integration.ClassificationTotals(results)
	fmt.Println("classification totals:", integration.JoinClasses(totals))

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(map[string]any{
		"score_version":     sh.Config().ScoreVersion,
		"comparison_rules":  integration.ComparisonRulesVersion,
		"classifications":   totals,
		"endpoint_results":  summarize(results),
	})
	return nil
}

type epView struct {
	Endpoint   string `json:"endpoint"`
	Legacy     int    `json:"legacy_rows"`
	Canonical  int    `json:"canonical_rows"`
	Matched    int    `json:"matched"`
	Expected   int    `json:"expected_diffs"`
	Unexpected int    `json:"unexpected_diffs"`
	Errors     int    `json:"errors"`
}

func summarize(results []integration.EndpointResult) []epView {
	out := make([]epView, 0, len(results))
	for _, r := range results {
		out = append(out, epView{r.Endpoint, r.LegacyRows, r.CanonicalRows, r.Matched, r.ExpectedDiffs, r.Unexpected, r.Errors})
	}
	return out
}

// --- legacy read-only helpers (harness only) ---

func legacyCompanyNames(db *sql.DB) ([]string, error) {
	rows, err := db.Query("SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

func legacyTopScores(db *sql.DB, limit int, minTrade float64) ([]integration.ScoreInputRow, error) {
	const q = `
		SELECT TOP (@limit)
			CompanyID, Symbol, CompanyName,
			QuantScore, DataQualityScore,
			GrowthScore, ProfitabilityScore, ValuationScore, MarketScore,
			ScoreVersion
		FROM dbo.vw_AIStockMetrics
		WHERE ISNULL(AvgTradeValue30D, 0) >= @minTrade
		ORDER BY QuantScore DESC`
	rows, err := db.Query(q, sql.Named("limit", limit), sql.Named("minTrade", minTrade))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]integration.ScoreInputRow, 0, limit)
	for rows.Next() {
		var r integration.ScoreInputRow
		var sym, name, ver sql.NullString
		var qs, dq, g, p, v, m sql.NullFloat64
		if err := rows.Scan(&r.LegacyCompanyID, &sym, &name, &qs, &dq, &g, &p, &v, &m, &ver); err != nil {
			return nil, err
		}
		r.Symbol, r.CompanyName, r.ScoreVersion = sym.String, name.String, ver.String
		r.QuantScore, r.DataQualityScore = nf(qs), nf(dq)
		r.GrowthScore, r.ProfitabilityScore = nf(g), nf(p)
		r.ValuationScore, r.MarketScore = nf(v), nf(m)
		out = append(out, r)
	}
	return out, rows.Err()
}

func legacyPriceHistory(db *sql.DB, symbol string, limit int) ([]integration.MarketInputRow, error) {
	const q = `
		SELECT TOP (@limit)
			CONVERT(NVARCHAR(20), GregorianDate, 23) AS gdate,
			ISNULL(JalaliDate, '') AS jdate,
			ISNULL(ClosingPrice, 0), ISNULL(LastPrice, 0),
			ISNULL(HighPrice, 0), ISNULL(LowPrice, 0),
			ISNULL(Volume, 0), ISNULL(TradeValue, 0),
			ISNULL(ClosingChangePercent, 0)
		FROM dbo.MarketPriceHistory
		WHERE CompanyName = @name OR Symbol = @name
		ORDER BY GregorianDate DESC`
	rows, err := db.Query(q, sql.Named("limit", limit), sql.Named("name", symbol))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]integration.MarketInputRow, 0, limit)
	for rows.Next() {
		var r integration.MarketInputRow
		var jd sql.NullString
		var cp, lp, hp, lo, vol, tv, ch sql.NullFloat64
		if err := rows.Scan(&r.Date, &jd, &cp, &lp, &hp, &lo, &vol, &tv, &ch); err != nil {
			return nil, err
		}
		r.JalaliDate = jd.String
		r.ClosingPrice, r.LastPrice = nf(cp), nf(lp)
		r.HighPrice, r.LowPrice = nf(hp), nf(lo)
		r.Volume, r.TradeValue, r.ChangePercent = nf(vol), nf(tv), nf(ch)
		out = append(out, r)
	}
	return out, rows.Err()
}

// sampleCompanyNames returns a heterogeneous set: strong monthly coverage,
// strong financial coverage, sparse-data companies and known unmapped names.
func sampleCompanyNames(db *sql.DB) ([]string, error) {
	const q = `
		SELECT name FROM (
			SELECT TOP 3 CompanyName AS name, COUNT(*) c FROM dbo.mahane GROUP BY CompanyName ORDER BY c DESC
		) a
		UNION
		SELECT name FROM (
			SELECT TOP 3 CompanyName AS name, COUNT(*) c FROM dbo.miandore2 GROUP BY CompanyName ORDER BY c DESC
		) b
		UNION
		SELECT name FROM (
			SELECT TOP 2 CompanyName AS name, COUNT(*) c FROM dbo.mahane GROUP BY CompanyName ORDER BY c ASC
		) d
		UNION
		SELECT CompanyName AS name FROM dbo.miandore2
		WHERE CompanyName IN (N'خاهن', N'شخارک', N'شکیمیا', N'کسرا')`
	rows, err := db.Query(q)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	seen := map[string]bool{}
	out := []string{}
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			return nil, err
		}
		if n != "" && !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	return out, rows.Err()
}

func legacyMonthly(db *sql.DB, companyName string) ([]integration.MonthlyInputRow, error) {
	const q = `
		SELECT CompanyID, ReportDate, ISNULL(Value1,0), ISNULL(Value2,0), ISNULL(Value3,0)
		FROM dbo.mahane WHERE CompanyName = @name ORDER BY ReportDate DESC`
	rows, err := db.Query(q, sql.Named("name", companyName))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []integration.MonthlyInputRow{}
	for rows.Next() {
		var r integration.MonthlyInputRow
		var v1, v2, v3 float64
		if err := rows.Scan(&r.LegacyCompanyID, &r.ReportDate, &v1, &v2, &v3); err != nil {
			return nil, err
		}
		r.ProductionQuantity, r.SalesQuantity = v1, v2
		r.ReportedSalesAmount, r.SalesAmountRial = v3, v3
		out = append(out, r)
	}
	return out, rows.Err()
}

func legacyFinancial(db *sql.DB, companyName string) ([]integration.FinancialInputRow, error) {
	const q = `
		SELECT CompanyID, ReportDate,
		       ISNULL(Num1_Value1,0), ISNULL(RevenueNew,0), ISNULL(OperatingProfitNew,0),
		       ISNULL(NetProfitAmount,0), ISNULL(Num2_Value1,0)
		FROM dbo.miandore2 WHERE CompanyName = @name ORDER BY ReportDate DESC`
	rows, err := db.Query(q, sql.Named("name", companyName))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []integration.FinancialInputRow{}
	for rows.Next() {
		var r integration.FinancialInputRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.ReportDate, &r.EPS, &r.Revenue,
			&r.OperatingProfit, &r.NetProfit, &r.Capital); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func nf(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}

func distinctSymbols(rows []integration.ScoreInputRow, max int) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, r := range rows {
		s := r.Symbol
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
		if len(out) >= max {
			break
		}
	}
	return out
}
