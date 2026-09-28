// Command finalcanary runs a bounded, read-only FINAL canonical read canary
// across the endpoints judged ready (SalesData2, AllCompanyScores,
// CompanyScores, price-history). It drives the real Gin handlers through
// httptest against the live shadow PostgreSQL and legacy SQL Server, applies the
// identity eligibility guard, exercises automatic legacy fallback, and writes
// machine-readable artifacts.
//
// It never serves production traffic and never writes to either database.
//
// Usage (from go-app/):
//
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	go run ./cmd/finalcanary --inject normal
//	go run ./cmd/finalcanary --inject pg_unavailable
//	go run ./cmd/finalcanary --inject missing_run
package main

import (
	"context"
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"go-app/config"
	"go-app/handlers"
	"go-app/integration"
)

var representatives = []string{
	"وسپه", "خودرو", "بفجر", "دزهراوی", "کیمیا",
	"غاذر", "کسرا", "چکاپا", "افق", "هجرت",
}

var unsafeNames = []string{"جم پیلن", "های وب", "خاهن", "شخارک", "شکیمیا"}

const repeats = 5

type row struct {
	Endpoint    string
	Company     string
	Route       string
	Served      string
	HTTPStatus  int
	LegacyMs    float64
	CanonicalMs float64
	Exact       int
	Expected    int
	Unexpected  int
	Errors      int
	ScoreVersion string
	ScoreAsOf    string
	DataAsOf     string
	ScoreStale   string
	Note         string
}

func main() {
	inject := flag.String("inject", "normal", "normal | pg_unavailable | missing_run")
	_ = flag.String("out", "../integration_shadow_v1/output", "output directory")
	flag.Parse()

	if err := setupEnv(*inject); err != nil {
		fmt.Fprintln(os.Stderr, "setup:", err)
		os.Exit(1)
	}
	if err := run(*inject); err != nil {
		fmt.Fprintln(os.Stderr, "finalcanary error:", err)
		os.Exit(1)
	}
}

func setupEnv(inject string) error {
	os.Setenv("CDF_FUND_CANARY_ENABLED", "true")
	os.Setenv("CDF_FUND_CANARY_COMPANIES", strings.Join(representatives, ","))
	os.Setenv("CDF_FUND_CANARY_VERIFY", "true")
	os.Setenv("CDF_FUND_CANARY_TIMEOUT_MS", "3000")
	os.Setenv("CDF_PRICE_HISTORY_CANARY_ENABLED", "true")
	os.Setenv("CDF_PRICE_HISTORY_CANARY_SYMBOLS", strings.Join(representatives, ","))
	os.Setenv("CDF_PRICE_HISTORY_CANARY_VERIFY", "true")
	os.Setenv("CDF_PRICE_HISTORY_CANARY_TIMEOUT_MS", "3000")
	switch inject {
	case "normal":
		// keep configured canonical DB
	case "pg_unavailable":
		os.Setenv("CDF_CANONICAL_DB", "company_financial_nonexistent_zzz")
	case "missing_run":
		os.Setenv("CDF_CANONICAL_SCORE_VERSION", "canonical-v9-nonexistent")
	default:
		return fmt.Errorf("unknown inject %q", inject)
	}
	return nil
}

func router() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	g := gin.New()
	g.GET("/api/SalesData2", handlers.GetSalesData2)
	g.GET("/api/AllCompanyScores", handlers.GetCompanyScores)
	g.GET("/api/CompanyScores", handlers.GetCompanyScores2)
	g.GET("/api/price-history", handlers.GetPriceHistory)
	return g
}

func do(g *gin.Engine, path string) (int, float64, []byte) {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	w := httptest.NewRecorder()
	t0 := time.Now()
	g.ServeHTTP(w, req)
	ms := float64(time.Since(t0).Microseconds()) / 1000.0
	return w.Code, ms, w.Body.Bytes()
}

func run(inject string) error {
	g := router()
	sh := integration.Default()
	ctx := context.Background()
	st := sh.RefreshStatus(ctx)

	db := config.GetDB()
	defer db.Close()

	outDir := "../integration_shadow_v1/output"
	if d := os.Getenv("CDF_SHADOW_OUTPUT_DIR"); d != "" {
		outDir = d
	}
	_ = os.MkdirAll(outDir, 0o755)

	rows := []row{}
	names := append([]string(nil), representatives...)
	names = append(names, unsafeNames...)

	// ---- guard classification (no server calls) ----
	guardRows := []row{}
	for _, n := range names {
		class := sh.EligibilityClass(n)
		eligible := sh.IsCanonicalEligible(n)
		guardRows = append(guardRows, row{
			Endpoint: "identity_guard", Company: n, Route: class,
			Served: fmt.Sprintf("eligible=%v", eligible),
		})
	}

	// ---- SalesData2 ----
	for _, n := range names {
		legacy := legacyMonthly(db, n)
		route := sh.SalesData2Route(n)
		served, canonMs, errText := classifySalesData2(ctx, sh, n)
		// HTTP path
		status, httpMs, body := do(g, "/api/SalesData2?companyName="+urlq(n))
		contractErr := validateSalesData2Body(body)
		r := row{Endpoint: "SalesData2", Company: n, Route: routeName(route), Served: served,
			HTTPStatus: status, CanonicalMs: canonMs, LegacyMs: httpMs, Note: joinNotes(errText, contractErr)}
		if sh.FundCanaryVerify() && served == "canonical" && len(legacy) > 0 {
			cres := sh.VerifySalesData2(ctx, legacy, 0)
			r.Exact, r.Expected, r.Unexpected, r.Errors = cres.Classifications[integration.ClassExactMatch], cres.ExpectedDiffs, cres.Unexpected, cres.Errors
		}
		rows = append(rows, r)
	}

	// ---- CompanyScores ----
	for _, n := range names {
		legacyRow, ok, _ := legacyCompanyScore(db, n)
		route := sh.CompanyScoresRoute(n)
		served, canonMs, errText := classifyCompanyScores(ctx, sh, n)
		status, httpMs, body := do(g, "/api/CompanyScores?companyName="+urlq(n))
		contractErr := validateCompanyScoresBody(body)
		r := row{Endpoint: "CompanyScores", Company: n, Route: routeName(route), Served: served,
			HTTPStatus: status, CanonicalMs: canonMs, LegacyMs: httpMs, Note: joinNotes(errText, contractErr)}
		if ok && sh.FundCanaryVerify() && served == "canonical" {
			cres := sh.VerifyCompanyScores(ctx, legacyRow, 0)
			r.Exact, r.Expected, r.Unexpected, r.Errors = cres.Classifications[integration.ClassExactMatch], cres.ExpectedDiffs, cres.Unexpected, cres.Errors
		}
		r.ScoreVersion, r.ScoreAsOf, r.DataAsOf, r.ScoreStale = metaFields(st)
		rows = append(rows, r)
	}

	// ---- AllCompanyScores (population-wide; one comparison) ----
	{
		legacyAll := legacyAllScores(db)
		route := sh.AllCompanyScoresRoute()
		served := "legacy"
		canonMs := 0.0
		errText := ""
		if canon, err := sh.FetchAllScoresCanonical(ctx); err == nil && len(canon) > 0 {
			served = "canonical"
		} else if err != nil {
			errText = err.Error()
			served = "fallback"
		} else {
			errText = "canonical empty"
			served = "fallback"
		}
		status, httpMs, body := do(g, "/api/AllCompanyScores")
		contractErr := validateAllScoresBody(body)
		r := row{Endpoint: "AllCompanyScores", Company: "(all)", Route: routeName(route), Served: served,
			HTTPStatus: status, CanonicalMs: canonMs, LegacyMs: httpMs, Note: joinNotes(errText, contractErr)}
		if sh.FundCanaryVerify() && served == "canonical" && len(legacyAll) > 0 {
			cres := sh.VerifyAllCompanyScores(ctx, legacyAll, 0)
			r.Exact, r.Expected, r.Unexpected, r.Errors = cres.Classifications[integration.ClassExactMatch], cres.ExpectedDiffs, cres.Unexpected, cres.Errors
		}
		r.ScoreVersion, r.ScoreAsOf, r.DataAsOf, r.ScoreStale = metaFields(st)
		rows = append(rows, r)
	}

	// ---- price-history ----
	for _, n := range names {
		legacy := legacyPrice(db, n, 30)
		route := sh.PriceHistoryRoute(n)
		served, canonMs, errText := classifyPrice(ctx, sh, n)
		status, httpMs, body := do(g, "/api/price-history?companyName="+urlq(n)+"&limit=30")
		contractErr := validatePriceBody(body)
		r := row{Endpoint: "price-history", Company: n, Route: routeName(route), Served: served,
			HTTPStatus: status, CanonicalMs: canonMs, LegacyMs: httpMs, Note: joinNotes(errText, contractErr)}
		if sh.CanaryVerify() && served == "canonical" && len(legacy) > 0 {
			cres := sh.VerifyCanaryPriceHistory(ctx, n, 30, legacy, 0)
			r.Exact, r.Expected, r.Unexpected, r.Errors = cres.Classifications[integration.ClassExactMatch], cres.ExpectedDiffs, cres.Unexpected, cres.Errors
		}
		rows = append(rows, r)
	}

	// latency repeats (bounded) for p50/p95
	lat := map[string][]float64{}
	for i := 0; i < repeats; i++ {
		for _, ep := range []struct{ name, path string }{
			{"SalesData2", "/api/SalesData2?companyName=" + urlq(representatives[0])},
			{"AllCompanyScores", "/api/AllCompanyScores"},
			{"CompanyScores", "/api/CompanyScores?companyName=" + urlq(representatives[0])},
			{"price-history", "/api/price-history?companyName=" + urlq(representatives[0]) + "&limit=90"},
		} {
			_, ms, _ := do(g, ep.path)
			lat[ep.name] = append(lat[ep.name], ms)
		}
	}

	if err := writeCSV(filepath.Join(outDir, "final_read_canary.csv"), rows); err != nil {
		return err
	}
	summary := buildSummary(inject, sh, st, rows, guardRows, lat)
	return writeJSON(filepath.Join(outDir, "final_read_canary_summary.json"), summary)
}

// ---- classification helpers ----

func classifySalesData2(ctx context.Context, sh *integration.Shadow, name string) (string, float64, string) {
	if sh.SalesData2Route(name) != integration.RouteCanary {
		return "legacy", 0, ""
	}
	t0 := time.Now()
	rows, err := sh.FetchSalesData2Canonical(ctx, name)
	ms := float64(time.Since(t0).Microseconds()) / 1000.0
	if err != nil {
		return "fallback", ms, err.Error()
	}
	if len(rows) == 0 {
		return "fallback", ms, "canonical empty"
	}
	return "canonical", ms, ""
}

func classifyCompanyScores(ctx context.Context, sh *integration.Shadow, name string) (string, float64, string) {
	if sh.CompanyScoresRoute(name) != integration.RouteCanary {
		return "legacy", 0, ""
	}
	t0 := time.Now()
	b, err := sh.FetchCompanyScoreCanonical(ctx, name)
	ms := float64(time.Since(t0).Microseconds()) / 1000.0
	if err != nil {
		return "fallback", ms, err.Error()
	}
	if !b.HasScore {
		return "fallback", ms, "canonical score missing"
	}
	return "canonical", ms, ""
}

func classifyPrice(ctx context.Context, sh *integration.Shadow, name string) (string, float64, string) {
	if sh.PriceHistoryRoute(name) != integration.RouteCanary {
		return "legacy", 0, ""
	}
	t0 := time.Now()
	rows, err := sh.FetchPriceHistoryCanonical(ctx, name, 30)
	ms := float64(time.Since(t0).Microseconds()) / 1000.0
	if err != nil {
		return "fallback", ms, err.Error()
	}
	if len(rows) == 0 {
		return "fallback", ms, "canonical empty"
	}
	return "canonical", ms, ""
}

func metaFields(st integration.Status) (string, string, string, string) {
	version := st.ScoreVersion
	if version == "" {
		version = "(none)"
	}
	return version, st.ScoreAsOf, st.DataAsOf, fmt.Sprintf("%v", st.ScoreStale)
}

func routeName(r integration.PriceRoute) string {
	switch r {
	case integration.RouteCanary:
		return "canary"
	case integration.RouteShadow:
		return "shadow"
	default:
		return "legacy"
	}
}

func joinNotes(parts ...string) string {
	out := []string{}
	for _, p := range parts {
		if strings.TrimSpace(p) != "" {
			out = append(out, p)
		}
	}
	return strings.Join(out, "; ")
}

// ---- contract validators ----

func validateSalesData2Body(b []byte) string {
	var arr []map[string]any
	if err := json.Unmarshal(b, &arr); err != nil {
		return "invalid json"
	}
	for _, r := range arr {
		for _, k := range []string{"companyName", "companyID", "reportDate", "value1", "value2", "value3", "percentage", "wow"} {
			if _, ok := r[k]; !ok {
				return "missing key " + k
			}
		}
	}
	return ""
}

func validateAllScoresBody(b []byte) string {
	var arr []map[string]any
	if err := json.Unmarshal(b, &arr); err != nil {
		return "invalid json"
	}
	for _, r := range arr {
		for _, k := range []string{"company_id", "company_name", "sales_growth", "eps_growth", "pe", "price", "Stable", "operation"} {
			if _, ok := r[k]; !ok {
				return "missing key " + k
			}
		}
		break
	}
	return ""
}

func validateCompanyScoresBody(b []byte) string {
	var arr []map[string]any
	if err := json.Unmarshal(b, &arr); err != nil {
		return "invalid json"
	}
	if len(arr) == 0 {
		return ""
	}
	for _, k := range []string{"companyID", "companyName", "salesGrowth", "epsGrowth", "finalScore"} {
		if _, ok := arr[0][k]; !ok {
			return "missing key " + k
		}
	}
	return ""
}

func validatePriceBody(b []byte) string {
	var arr []map[string]any
	if err := json.Unmarshal(b, &arr); err != nil {
		return "invalid json"
	}
	if len(arr) == 0 {
		return ""
	}
	for _, k := range []string{"date", "jalali_date", "closing_price", "last_price", "high_price", "low_price", "volume", "trade_value", "change_percent"} {
		if _, ok := arr[0][k]; !ok {
			return "missing key " + k
		}
	}
	return ""
}

// ---- summary ----

func buildSummary(inject string, sh *integration.Shadow, st integration.Status, rows, guard []row, lat map[string][]float64) map[string]any {
	type agg struct {
		Requests    int
		Canonical   int
		Legacy      int
		Fallback    int
		HTTPErrors  int
		Exact       int
		Expected    int
		Unexpected  int
		Errors      int
	}
	byEP := map[string]*agg{}
	var unexpectedTotal, httpErrTotal, fallbackTotal int
	for _, r := range rows {
		a := byEP[r.Endpoint]
		if a == nil {
			a = &agg{}
			byEP[r.Endpoint] = a
		}
		a.Requests++
		switch r.Served {
		case "canonical":
			a.Canonical++
		case "fallback":
			a.Fallback++
			fallbackTotal++
		default:
			a.Legacy++
		}
		if r.HTTPStatus != 200 {
			a.HTTPErrors++
			httpErrTotal++
		}
		a.Exact += r.Exact
		a.Expected += r.Expected
		a.Unexpected += r.Unexpected
		a.Errors += r.Errors
		unexpectedTotal += r.Unexpected + r.Errors
	}
	eps := map[string]any{}
	for ep, a := range byEP {
		eps[ep] = map[string]any{
			"requests": a.Requests, "canonical_served": a.Canonical, "legacy_served": a.Legacy,
			"fallbacks": a.Fallback, "http_errors": a.HTTPErrors,
			"comparison_exact": a.Exact, "comparison_expected": a.Expected,
			"comparison_unexpected": a.Unexpected, "errors": a.Errors,
			"latency_median_ms": median(lat[ep]), "latency_p95_ms": pct(lat[ep], 0.95),
		}
	}
	guardResult := map[string]any{}
	for _, g := range guard {
		guardResult[g.Company] = map[string]string{"classification": g.Route, "eligible": strings.TrimPrefix(g.Served, "eligible=")}
	}
	gate := "FINAL_CANONICAL_READ_CANARY_PASS"
	errs := []string{}
	if unexpectedTotal != 0 {
		gate = "FINAL_CANONICAL_READ_CANARY_FAIL"
		errs = append(errs, fmt.Sprintf("%d unexpected comparison differences/errors", unexpectedTotal))
	}
	if httpErrTotal != 0 {
		gate = "FINAL_CANONICAL_READ_CANARY_FAIL"
		errs = append(errs, fmt.Sprintf("%d HTTP errors", httpErrTotal))
	}
	// identity guard: unsafe names must never be canonical-eligible
	for _, g := range guard {
		for _, u := range unsafeNames {
			if g.Company == u && strings.TrimPrefix(g.Served, "eligible=") == "true" {
				gate = "FINAL_CANONICAL_READ_CANARY_FAIL"
				errs = append(errs, "unsafe identity became eligible: "+u)
			}
		}
	}
	return map[string]any{
		"generated_at":      time.Now().UTC().Format(time.RFC3339),
		"inject":            inject,
		"read_mode":         st.ReadMode,
		"canonical_configured": st.CanonicalConfigured,
		"canonical_reachable":  st.CanonicalReachable,
		"score_version":     st.ScoreVersion,
		"score_run_id":      st.ScoreRunID,
		"score_as_of":       st.ScoreAsOf,
		"data_as_of":        st.DataAsOf,
		"score_stale":       st.ScoreStale,
		"endpoints":         eps,
		"identity_guard":    guardResult,
		"unexpected_total":  unexpectedTotal,
		"fallback_total":    fallbackTotal,
		"http_errors_total": httpErrTotal,
		"failures":          errs,
		"gate":              gate,
	}
}

// ---- legacy readers (harness only) ----

func legacyMonthly(db *sql.DB, name string) []integration.MonthlyInputRow {
	rows, err := db.Query(`SELECT CompanyID, ReportDate, ISNULL(Value1,0), ISNULL(Value2,0), ISNULL(Value3,0)
		FROM dbo.mahane WHERE CompanyName=@n ORDER BY ReportDate`, sql.Named("n", name))
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []integration.MonthlyInputRow{}
	for rows.Next() {
		var r integration.MonthlyInputRow
		var v1, v2, v3 float64
		if rows.Scan(&r.LegacyCompanyID, &r.ReportDate, &v1, &v2, &v3) == nil {
			r.ProductionQuantity, r.SalesQuantity = v1, v2
			r.ReportedSalesAmount, r.SalesAmountRial = v3, v3
			out = append(out, r)
		}
	}
	return out
}

func legacyCompanyScore(db *sql.DB, name string) (integration.CompanyScoreInputRow, bool, error) {
	out := integration.CompanyScoreInputRow{}
	var id string
	salesRows, err := db.Query(`SELECT ISNULL(Value3,0) FROM dbo.mahane WHERE CompanyName=@n ORDER BY ReportDate`, sql.Named("n", name))
	if err != nil {
		return out, false, err
	}
	var salesVals []float64
	for salesRows.Next() {
		var v float64
		if salesRows.Scan(&v) == nil {
			salesVals = append(salesVals, v)
		}
	}
	salesRows.Close()
	epsRows, err := db.Query(`SELECT CompanyID, ISNULL(Product1,0) FROM dbo.miandore2 WHERE CompanyName=@n ORDER BY ReportDate`, sql.Named("n", name))
	if err != nil {
		return out, false, err
	}
	var epsVals []float64
	for epsRows.Next() {
		var cid string
		var v float64
		if epsRows.Scan(&cid, &v) == nil {
			id = cid
			epsVals = append(epsVals, v)
		}
	}
	epsRows.Close()
	if id == "" && len(salesVals) == 0 {
		return out, false, nil
	}
	var pe, price float64
	_ = db.QueryRow(`SELECT ISNULL(PE,0), ISNULL(Price,0) FROM codal.dbo.FullPE WHERE CompanyName=@n`, sql.Named("n", name)).Scan(&pe, &price)
	var salesGrowth, epsGrowth float64
	if len(salesVals) >= 24 {
		recent := meanOf(salesVals[len(salesVals)-12:])
		previous := meanOf(salesVals[len(salesVals)-24 : len(salesVals)-12])
		if previous != 0 {
			salesGrowth = (recent - previous) / math.Abs(previous) * 100
		}
	}
	if len(epsVals) >= 8 {
		recent := meanOf(epsVals[len(epsVals)-4:])
		previous := meanOf(epsVals[len(epsVals)-8 : len(epsVals)-4])
		if previous != 0 {
			epsGrowth = (recent - previous) / math.Abs(previous) * 100
		}
	} else if len(epsVals) >= 5 && epsVals[len(epsVals)-5] != 0 {
		epsGrowth = (epsVals[len(epsVals)-1] - epsVals[len(epsVals)-5]) / math.Abs(epsVals[len(epsVals)-5]) * 100
	}
	out = integration.CompanyScoreInputRow{
		LegacyCompanyID: id, CompanyName: name,
		SalesGrowth: round2(salesGrowth), EPSGrowth: round2(epsGrowth),
		PE: round2(pe), Price: round2(price), FinalScore: 0,
	}
	return out, true, nil
}

func legacyAllScores(db *sql.DB) []integration.AllScoreInputRow {
	salesMap := map[string][]float64{}
	nameMap := map[string]string{}
	srows, err := db.Query(`SELECT CompanyID, CompanyName, ISNULL(Value3,0) FROM dbo.mahane ORDER BY CompanyID, ReportDate`)
	if err != nil {
		return nil
	}
	for srows.Next() {
		var id, name string
		var v float64
		if srows.Scan(&id, &name, &v) == nil {
			salesMap[id] = append(salesMap[id], v)
			nameMap[id] = name
		}
	}
	srows.Close()
	epsMap := map[string][]float64{}
	opNew := map[string][]float64{}
	revNew := map[string][]float64{}
	erows, err := db.Query(`SELECT CompanyID, CompanyName, ISNULL(Product1,0), ISNULL(OperatingProfitNew,0), ISNULL(RevenueNew,0) FROM dbo.miandore2 ORDER BY CompanyID, ReportDate`)
	if err != nil {
		return nil
	}
	for erows.Next() {
		var id, name string
		var p1, op, rev float64
		if erows.Scan(&id, &name, &p1, &op, &rev) == nil {
			epsMap[id] = append(epsMap[id], p1)
			opNew[id] = append(opNew[id], op)
			revNew[id] = append(revNew[id], rev)
			if _, ok := nameMap[id]; !ok {
				nameMap[id] = name
			}
		}
	}
	erows.Close()
	type peD struct{ PE, Price float64 }
	peMap := map[string]peD{}
	prows, _ := db.Query(`SELECT TOP (1000) CompanyName, ISNULL(PE,0), ISNULL(Price,0) FROM codal.dbo.FullPE`)
	if prows != nil {
		for prows.Next() {
			var name string
			var pe, price float64
			if prows.Scan(&name, &pe, &price) == nil {
				peMap[name] = peD{pe, price}
			}
		}
		prows.Close()
	}
	seen := map[string]bool{}
	for id := range salesMap {
		seen[id] = true
	}
	for id := range epsMap {
		seen[id] = true
	}
	out := []integration.AllScoreInputRow{}
	for id := range seen {
		name := nameMap[id]
		var salesGrowth, epsGrowth, operation float64
		if s := salesMap[id]; len(s) >= 24 {
			recent := meanOf(s[len(s)-12:])
			previous := meanOf(s[len(s)-24 : len(s)-12])
			if previous != 0 {
				salesGrowth = (recent - previous) / math.Abs(previous) * 100
			}
		}
		if e := epsMap[id]; len(e) >= 8 {
			recent := meanOf(e[len(e)-4:])
			previous := meanOf(e[len(e)-8 : len(e)-4])
			if previous != 0 {
				epsGrowth = (recent - previous) / math.Abs(previous) * 100
			}
		} else if len(e) >= 5 && e[len(e)-5] != 0 {
			epsGrowth = (e[len(e)-1] - e[len(e)-5]) / math.Abs(e[len(e)-5]) * 100
		}
		if len(opNew[id]) > 0 && len(revNew[id]) > 0 {
			o := opNew[id][len(opNew[id])-1]
			rv := revNew[id][len(revNew[id])-1]
			if rv != 0 {
				operation = o / rv * 100
			}
		}
		pd := peMap[name]
		out = append(out, integration.AllScoreInputRow{
			LegacyCompanyID: id, CompanyName: name,
			SalesGrowth: round2(salesGrowth), EPSGrowth: round2(epsGrowth),
			PE: round2(pd.PE), Price: round2(pd.Price), Operation: round2(operation),
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EPSGrowth > out[j].EPSGrowth })
	return out
}

func legacyPrice(db *sql.DB, name string, limit int) []integration.MarketInputRow {
	rows, err := db.Query(`SELECT TOP (@l) CONVERT(NVARCHAR(20), GregorianDate, 23), ISNULL(JalaliDate,''),
		ISNULL(ClosingPrice,0), ISNULL(LastPrice,0), ISNULL(HighPrice,0), ISNULL(LowPrice,0),
		ISNULL(Volume,0), ISNULL(TradeValue,0), ISNULL(ClosingChangePercent,0)
		FROM dbo.MarketPriceHistory WHERE CompanyName=@n OR Symbol=@n ORDER BY GregorianDate DESC`,
		sql.Named("l", limit), sql.Named("n", name))
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []integration.MarketInputRow{}
	for rows.Next() {
		var r integration.MarketInputRow
		var jd sql.NullString
		var cp, lp, hp, lo, vol, tv, ch sql.NullFloat64
		if rows.Scan(&r.Date, &jd, &cp, &lp, &hp, &lo, &vol, &tv, &ch) == nil {
			r.JalaliDate = jd.String
			r.ClosingPrice, r.LastPrice, r.HighPrice, r.LowPrice = nf(cp), nf(lp), nf(hp), nf(lo)
			r.Volume, r.TradeValue, r.ChangePercent = nf(vol), nf(tv), nf(ch)
			out = append(out, r)
		}
	}
	return out
}

// ---- io helpers ----

func writeCSV(path string, rows []row) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"endpoint", "company", "route", "served", "http_status", "legacy_ms", "canonical_ms",
		"exact", "expected", "unexpected", "errors", "score_version", "score_as_of", "data_as_of", "score_stale", "note"})
	for _, r := range rows {
		_ = w.Write([]string{r.Endpoint, r.Company, r.Route, r.Served, fmt.Sprint(r.HTTPStatus),
			fmt.Sprintf("%.3f", r.LegacyMs), fmt.Sprintf("%.3f", r.CanonicalMs),
			fmt.Sprint(r.Exact), fmt.Sprint(r.Expected), fmt.Sprint(r.Unexpected), fmt.Sprint(r.Errors),
			r.ScoreVersion, r.ScoreAsOf, r.DataAsOf, r.ScoreStale, r.Note})
	}
	return w.Error()
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}

func urlq(s string) string { return strings.ReplaceAll(s, " ", "%20") }

func median(v []float64) float64 { return pct(v, 0.5) }

func pct(v []float64, p float64) float64 {
	if len(v) == 0 {
		return 0
	}
	cp := append([]float64(nil), v...)
	sort.Float64s(cp)
	if p <= 0 {
		return cp[0]
	}
	if p >= 1 {
		return cp[len(cp)-1]
	}
	return cp[int(p*float64(len(cp)-1))]
}

func round2(v float64) float64 { return math.Round(v*100) / 100 }

func meanOf(v []float64) float64 {
	if len(v) == 0 {
		return 0
	}
	var s float64
	for _, x := range v {
		s += x
	}
	return s / float64(len(v))
}

func nf(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}
