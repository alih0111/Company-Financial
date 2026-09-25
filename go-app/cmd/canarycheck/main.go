// Command canarycheck runs a bounded, read-only live simulation of the
// price-history canonical canary against the shadow/test PostgreSQL database and
// the legacy SQL Server. It never enables production traffic and never writes.
//
// Usage (from go-app/):
//
//	set CDF_READ_MODE=legacy
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	set CDF_PRICE_HISTORY_CANARY_ENABLED=true
//	set CDF_PRICE_HISTORY_CANARY_SYMBOLS=کیمیا,غاذر,...
//	set CDF_PRICE_HISTORY_CANARY_VERIFY=true
//	go run ./cmd/canarycheck
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"go-app/config"
	"go-app/integration"
)

const legacyQuery = `
	SELECT TOP (@limit)
		CONVERT(NVARCHAR(20), GregorianDate, 23) AS gdate,
		ISNULL(JalaliDate, ''), ISNULL(ClosingPrice,0), ISNULL(LastPrice,0),
		ISNULL(HighPrice,0), ISNULL(LowPrice,0), ISNULL(Volume,0),
		ISNULL(TradeValue,0), ISNULL(ClosingChangePercent,0)
	FROM dbo.MarketPriceHistory
	WHERE CompanyName = @name OR Symbol = @name
	ORDER BY GregorianDate DESC`

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "canarycheck error:", err)
		os.Exit(1)
	}
}

func legacyFetch(ctx context.Context, db *sql.DB, symbol string, limit int) func() ([]integration.MarketInputRow, error) {
	return func() ([]integration.MarketInputRow, error) {
		rows, err := db.QueryContext(ctx, legacyQuery, sql.Named("limit", limit), sql.Named("name", symbol))
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := []integration.MarketInputRow{}
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
}

func run() error {
	sh := integration.Default()
	if !sh.Enabled() {
		st := sh.Status()
		return fmt.Errorf("canonical not available (mode=%s canary=%v err=%s)", st.ReadMode, st.CanaryEnabled, st.CanonicalError)
	}
	if !sh.CanaryEnabled() {
		return fmt.Errorf("price-history canary is not enabled; set CDF_PRICE_HISTORY_CANARY_ENABLED=true")
	}
	st := sh.RefreshStatus(context.Background())
	fmt.Printf("canary status: enabled=%v symbols=%d verify=%v timeout_ms=%d canonical_reachable=%v\n",
		st.CanaryEnabled, st.CanarySymbolCount, st.CanaryVerify, st.CanaryTimeoutMS, st.CanonicalReachable)

	db := config.GetDB()
	defer db.Close()
	ctx := context.Background()
	const limit = 30

	// 1) Representative allowlisted symbols.
	symbols := canarySymbols(sh)
	if len(symbols) == 0 {
		symbols = []string{"کیمیا", "غاذر", "سباقر", "دقاضی", "دارو", "فایرا"}
	}

	// Legacy-only baseline characterization for the same symbols (bounded).
	legacySamples := []float64{}
	for _, sym := range symbols {
		for i := 0; i < 3; i++ {
			t0 := time.Now()
			_, err := legacyFetch(ctx, db, sym, limit)()
			ms := float64(time.Since(t0).Microseconds()) / 1000.0
			if err == nil {
				legacySamples = append(legacySamples, ms)
				sh.RecordLegacyBaselineLatency(ms)
			}
		}
	}
	fmt.Printf("legacy baseline: n=%d median=%.2fms p95=%.2fms\n", len(legacySamples), pct(legacySamples, 0.5), pct(legacySamples, 0.95))

	for _, sym := range symbols {
		sh.RecordCanaryRequest()
		if sh.PriceHistoryRoute(sym) != integration.RouteCanary {
			// Not selected: legacy-served, no canonical attempt.
			lf := legacyFetch(ctx, db, sym, limit)
			rows, err := lf()
			if err != nil {
				fmt.Fprintf(os.Stderr, "legacy %q: %v\n", sym, err)
				continue
			}
			sh.RecordLegacyServed(integration.CanarySample{Symbol: sym, Route: "legacy", Result: "served", RowCount: len(rows)})
			fmt.Printf("[legacy] %s rows=%d (not selected)\n", sym, len(rows))
			continue
		}
		sh.RecordCanarySelected()
		res := sh.ResolvePriceHistory(ctx,
			func(c context.Context) ([]integration.MarketInputRow, error) {
				return sh.FetchPriceHistoryCanonical(c, sym, limit)
			},
			legacyFetch(ctx, db, sym, limit),
		)
		record(sh, sym, res)
		if res.Outcome == integration.OutcomeCanonicalServed && sh.CanaryVerify() {
			legacyRows, err := legacyFetch(ctx, db, sym, limit)()
			if err == nil {
				cres := sh.VerifyCanaryPriceHistory(ctx, sym, limit, legacyRows, 0)
				sh.RecordCanaryComparison(sym, cres)
				fmt.Printf("[canary] %s rows=%d exact=%d expected=%d unexpected=%d errors=%d\n",
					sym, len(res.Rows), cres.Classifications[integration.ClassExactMatch], cres.ExpectedDiffs, cres.Unexpected, cres.Errors)
				continue
			}
		}
		fmt.Printf("[%s] %s rows=%d canon_ms=%.2f legacy_ms=%.2f\n", res.Outcome, sym, len(res.Rows), res.CanonicalMs, res.LegacyMs)
	}

	// 2) Unknown symbol: canonical empty -> deterministic fallback.
	sh.RecordCanaryRequest()
	sh.RecordCanarySelected()
	unknown := "__NO_SUCH_SYMBOL__"
	ures := sh.ResolvePriceHistory(ctx,
		func(c context.Context) ([]integration.MarketInputRow, error) { return sh.FetchPriceHistoryCanonical(c, unknown, limit) },
		legacyFetch(ctx, db, unknown, limit),
	)
	record(sh, unknown, ures)
	fmt.Printf("[unknown] outcome=%s rows=%d\n", ures.Outcome, len(ures.Rows))

	// 3) PostgreSQL unavailable (injected canonical error) -> fallback.
	sh.RecordCanaryRequest()
	sh.RecordCanarySelected()
	fres := sh.ResolvePriceHistory(ctx,
		func(context.Context) ([]integration.MarketInputRow, error) { return nil, fmt.Errorf("injected: pg unavailable") },
		legacyFetch(ctx, db, symbols[0], limit),
	)
	record(sh, symbols[0], fres)
	fmt.Printf("[pg-unavailable] outcome=%s rows=%d\n", fres.Outcome, len(fres.Rows))

	// 4) Both unavailable.
	sh.RecordCanaryRequest()
	sh.RecordCanarySelected()
	both := sh.ResolvePriceHistory(ctx,
		func(context.Context) ([]integration.MarketInputRow, error) { return nil, fmt.Errorf("injected: pg unavailable") },
		func() ([]integration.MarketInputRow, error) { return nil, fmt.Errorf("injected: sqlserver unavailable") },
	)
	record(sh, symbols[0], both)
	if both.Outcome == integration.OutcomeFallbackFailed {
		sh.RecordLegacyFallbackError()
	}
	fmt.Printf("[both-unavailable] outcome=%s\n", both.Outcome)

	if err := sh.FlushCanaryDiagnostics(); err != nil {
		return fmt.Errorf("flush canary diagnostics: %w", err)
	}
	st = sh.RefreshStatus(context.Background())
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(map[string]any{
		"canary_enabled":    st.CanaryEnabled,
		"symbols":           symbols,
		"timeout_ms":        st.CanaryTimeoutMS,
		"read_mode":         st.ReadMode,
	})
}

func record(sh *integration.Shadow, symbol string, res integration.CanaryResult) {
	total := res.CanonicalMs + res.LegacyMs
	switch res.Outcome {
	case integration.OutcomeCanonicalServed:
		sh.RecordCanarySuccess(integration.CanarySample{Symbol: symbol, Route: "canonical", Result: "served", RowCount: len(res.Rows), CanonicalMs: res.CanonicalMs, TotalMs: total})
	case integration.OutcomeFallbackServed:
		sh.RecordCanaryFallback(integration.CanarySample{Symbol: symbol, Route: "fallback", Result: "legacy", RowCount: len(res.Rows), Fallback: true, Error: es(res.CanonicalErr), CanonicalMs: res.CanonicalMs, LegacyMs: res.LegacyMs, TotalMs: total})
	default:
		sh.RecordCanaryFallback(integration.CanarySample{Symbol: symbol, Route: "fallback", Result: "error", Fallback: true, Error: es(res.CanonicalErr) + "; legacy: " + es(res.LegacyErr), CanonicalMs: res.CanonicalMs, LegacyMs: res.LegacyMs, TotalMs: total})
	}
}

func pct(v []float64, p float64) float64 {
	if len(v) == 0 {
		return 0
	}
	cp := append([]float64(nil), v...)
	for i := 1; i < len(cp); i++ {
		for j := i; j > 0 && cp[j-1] > cp[j]; j-- {
			cp[j-1], cp[j] = cp[j], cp[j-1]
		}
	}
	if p <= 0 {
		return cp[0]
	}
	if p >= 1 {
		return cp[len(cp)-1]
	}
	return cp[int(p*float64(len(cp)-1))]
}

func canarySymbols(sh *integration.Shadow) []string {
	// Read the allowlist back from the environment (normalized at load time).
	raw := os.Getenv("CDF_PRICE_HISTORY_CANARY_SYMBOLS")
	out := []string{}
	for _, s := range splitComma(raw) {
		out = append(out, s)
	}
	return out
}

func splitComma(s string) []string {
	out := []string{}
	cur := ""
	for _, r := range s {
		if r == ',' {
			if cur != "" {
				out = append(out, cur)
			}
			cur = ""
			continue
		}
		cur += string(r)
	}
	if cur != "" {
		out = append(out, cur)
	}
	return out
}

func es(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func nf(n sql.NullFloat64) float64 {
	if n.Valid {
		return n.Float64
	}
	return 0
}

var _ = time.Second
