// Command readstatus prints the canonical analytics freshness/version metadata
// that the Go read path exposes to the application. Read-only.
//
// Usage (from go-app/):
//
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	go run ./cmd/readstatus
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	_ "go-app/config" // loads .env so DATABASE_URL is available
	"go-app/integration"
)

func main() {
	cfg := integration.LoadConfig()
	pg, err := integration.OpenPG(cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, "readstatus error:", err)
		os.Exit(1)
	}
	if pg == nil {
		fmt.Fprintln(os.Stderr, "canonical DSN not configured")
		os.Exit(1)
	}
	defer pg.Close()

	ctx := context.Background()
	info, err := pg.SelectScoreRun(ctx, cfg.ScoreVersion)
	if err != nil {
		fmt.Fprintln(os.Stderr, "select score run:", err)
		os.Exit(1)
	}
	meta, err := pg.Metadata(ctx, cfg.ScoreVersion)
	if err != nil {
		fmt.Fprintln(os.Stderr, "metadata:", err)
		os.Exit(1)
	}
	out := map[string]any{
		"score_version":   cfg.ScoreVersion,
		"score_run_id":    info.RunID,
		"score_as_of":     info.AsOfDate,
		"source_cutoff_at": info.SourceCutoffAt,
		"code_version":    info.CodeVer,
		"data_as_of":      meta.FundamentalsAsOf,
		"market_as_of":    meta.MarketAsOf,
		"score_stale":     meta.Stale,
		"completed":       info.Completed,
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(out)
}
