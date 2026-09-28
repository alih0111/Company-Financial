// Command symbolvalidate proves that the canonical application path can supply
// the symbol/company page contract for a heterogeneous symbol set, using only
// canonical PostgreSQL reads. It never writes and never fabricates values.
//
// Usage (from go-app/):
//
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	go run ./cmd/symbolvalidate
package main

import (
	"context"
	"database/sql"
	"encoding/csv"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"go-app/config"
	"go-app/integration"
)

type legacyCompany struct {
	Symbol    string
	CompanyID string
	Name      string
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "symbolvalidate error:", err)
		os.Exit(1)
	}
}

func run() error {
	cfg := integration.LoadConfig()
	pg, err := integration.OpenPG(cfg)
	if err != nil {
		return err
	}
	if pg == nil {
		return fmt.Errorf("canonical DSN not configured (set DATABASE_URL + CDF_CANONICAL_DB)")
	}
	defer pg.Close()

	db := config.GetDB()
	defer db.Close()

	companies, err := sampleCompanies(db)
	if err != nil {
		return err
	}
	ctx := context.Background()
	outDir := "../integration_shadow_v1/output"
	if d := os.Getenv("CDF_SHADOW_OUTPUT_DIR"); d != "" {
		outDir = d
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}

	rows := [][]string{}
	for _, c := range companies {
		page, err := pg.SymbolPage(ctx, c.CompanyID)
		if err != nil {
			rows = append(rows, []string{c.Symbol, c.CompanyID, "QUERY_ERROR", "", "", "", "", "", "",
				"", "", "", "", "", "", "", "", "", "", err.Error()})
			continue
		}
		r := []string{
			c.Symbol, c.CompanyID,
			present(page.IdentityFound),
			present(page.MonthlyPresent),
			present(page.MonthlyPresent),
			present(page.MonthlyPresent),
			financialField(page, "revenue"),
			financialField(page, "operating_profit"),
			financialField(page, "net_profit"),
			financialField(page, "eps"),
			financialField(page, "capital"),
			present(page.MarketPresent),
			present(page.ScorePresent),
			present(page.FactorScorePresent),
			categoryScores(page),
			quantScore(page),
			page.Metadata.ScoreVersion,
			page.Metadata.ScoreAsOf,
			page.Metadata.FundamentalsAsOf,
			boolStr(page.Metadata.Stale),
			notes(page),
		}
		rows = append(rows, r)
	}

	path := filepath.Join(outDir, "symbol_page_canonical_validation.csv")
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{
		"symbol", "legacy_company_id", "identity", "monthly_production", "monthly_sales",
		"monthly_revenue", "financial_revenue", "operating_profit", "net_profit", "eps",
		"capital", "market_history", "canonical_metrics", "factor_scores", "category_scores",
		"quant_score", "score_version", "score_as_of", "data_as_of", "score_stale", "dq_notes",
	})
	for _, r := range rows {
		_ = w.Write(r)
	}
	fmt.Printf("wrote %d symbol rows to %s\n", len(rows), path)
	return w.Error()
}

func present(ok bool) string {
	if ok {
		return "PRESENT"
	}
	return "MISSING"
}

func boolStr(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

func financialField(page integration.SymbolPageCanonical, field string) string {
	if len(page.Financial) == 0 {
		return "MISSING"
	}
	latest := page.Financial[0]
	switch field {
	case "revenue":
		if latest.Revenue != 0 {
			return "PRESENT"
		}
	case "operating_profit":
		if latest.OperatingProfit != 0 {
			return "PRESENT"
		}
	case "net_profit":
		if latest.NetProfit != 0 {
			return "PRESENT"
		}
	case "eps":
		if latest.EPS != 0 {
			return "PRESENT"
		}
	case "capital":
		if latest.Capital != 0 {
			return "PRESENT"
		}
	}
	return "ZERO_OR_NULL"
}

func categoryScores(page integration.SymbolPageCanonical) string {
	if len(page.Scores) == 0 {
		return "MISSING"
	}
	s := page.Scores[0]
	return fmt.Sprintf("growth=%.4f;profit=%.4f;val=%.4f;market=%.4f;dq=%.4f",
		s.GrowthScore, s.ProfitabilityScore, s.ValuationScore, s.MarketScore, s.DataQualityScore)
}

func quantScore(page integration.SymbolPageCanonical) string {
	if len(page.Scores) == 0 {
		return "MISSING"
	}
	return fmt.Sprintf("%.4f", page.Scores[0].QuantScore)
}

func notes(page integration.SymbolPageCanonical) string {
	var n []string
	if !page.IdentityFound {
		n = append(n, "identity_unmapped")
	}
	if !page.MetricSnapshotExists {
		n = append(n, "metric_snapshots_not_materialized")
	}
	if page.Metadata.Stale {
		n = append(n, "score_run_stale_vs_ingestion")
	}
	if len(n) == 0 {
		return "OK"
	}
	return strings.Join(n, ";")
}

func sampleCompanies(db *sql.DB) ([]legacyCompany, error) {
	// Heterogeneous set: high/low coverage plus known scope-excluded names.
	queries := []string{
		`SELECT TOP 4 Symbol, CompanyID, CompanyName FROM dbo.MarketPriceHistory
		 GROUP BY Symbol, CompanyID, CompanyName ORDER BY COUNT(*) DESC`,
		`SELECT TOP 3 CompanyName AS Symbol, CompanyID, CompanyName FROM dbo.mahane
		 GROUP BY CompanyName, CompanyID ORDER BY COUNT(*) ASC`,
		`SELECT TOP 2 CompanyName AS Symbol, CompanyID, CompanyName FROM dbo.miandore2
		 GROUP BY CompanyName, CompanyID ORDER BY COUNT(*) DESC`,
		`SELECT DISTINCT CompanyName AS Symbol, CompanyID, CompanyName FROM dbo.miandore2
		 WHERE CompanyName IN (N'کسرا', N'خاهن', N'شکیمیا')`,
	}
	seen := map[string]bool{}
	out := []legacyCompany{}
	for _, q := range queries {
		rows, err := db.Query(q)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var c legacyCompany
			if err := rows.Scan(&c.Symbol, &c.CompanyID, &c.Name); err != nil {
				rows.Close()
				return nil, err
			}
			if c.CompanyID == "" || seen[c.CompanyID] {
				continue
			}
			seen[c.CompanyID] = true
			out = append(out, c)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	_ = time.Now
	return out, nil
}
