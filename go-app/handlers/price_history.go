package handlers

import (
	"context"
	"database/sql"
	"net/http"
	"strings"
	"time"

	"go-app/config"
	"go-app/integration"

	"github.com/gin-gonic/gin"
)

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

type PriceHistoryRow struct {
	Date          string  `json:"date"`
	JalaliDate    string  `json:"jalali_date"`
	ClosingPrice  float64 `json:"closing_price"`
	LastPrice     float64 `json:"last_price"`
	HighPrice     float64 `json:"high_price"`
	LowPrice      float64 `json:"low_price"`
	Volume        float64 `json:"volume"`
	TradeValue    float64 `json:"trade_value"`
	ChangePercent float64 `json:"change_percent"`
}

// GetPriceHistory تاریخچه‌ی قیمت یک نماد را برمی‌گرداند.
// پارامتر companyName (نماد یا نام شرکت) و اختیاریاً limit (پیش‌فرض ۳۶۵ روز).
//
// Routing:
//   - LEGACY (default): SQL Server only.
//   - SHADOW: SQL Server served + canonical comparison (never canonical serving).
//   - canary enabled: allowlisted symbols attempt the canonical read and
//     automatically fall back to SQL Server on error/timeout/empty/invalid.
//
// The JSON contract, ordering, units and empty-result behavior are identical for
// all routes. No canonical UUID is ever exposed.
func GetPriceHistory(c *gin.Context) {
	start := time.Now()

	companyName := strings.TrimSpace(c.Query("companyName"))
	if companyName == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "companyName is required"})
		return
	}

	limit := parseIntQuery(c, "limit", 365)
	if limit > 5000 {
		limit = 5000
	}

	companyName = normalizePersian(companyName)

	// Exchange indices are not securities and live in market.index_observations.
	// Serve them through the identical JSON contract so the same price chart
	// renders a stock, a gold fund and an index without special-casing.
	if looksLikeIndex(companyName) {
		if db, err := config.GetPG(); err == nil && db != nil {
			if rows, err := indexHistoryRows(c.Request.Context(), db, companyName, limit); err == nil && len(rows) > 0 {
				c.JSON(http.StatusOK, rows)
				return
			}
		}
	}

	// SQL Server retired: canonical-only, with an explicit error on failure and
	// NO legacy fallback (which would attempt an unreachable SQL Server).
	if config.SQLServerMode() == "offline_expected" {
		sh := integration.Default()
		rows, err := sh.FetchPriceHistoryCanonical(c.Request.Context(), companyName, limit)
		if err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical price history unavailable", "reason": "sqlserver_offline_expected"})
			return
		}
		c.JSON(http.StatusOK, toPriceHistoryRows(rows))
		return
	}

	sh := integration.Default()
	sh.RecordCanaryRequest()
	// Identity eligibility is checked before any canary/percentage routing. An
	// ambiguous or unknown symbol can never be canonical-served, even if it is
	// allowlisted or its hash bucket falls inside a rollout percentage.
	sh.RecordEligibility(companyName)
	route := sh.PriceHistoryRoute(companyName)

	db := config.GetDB()
	defer db.Close()

	if route == integration.RouteCanary {
		sh.RecordCanarySelected()

		res := sh.ResolvePriceHistory(
			c.Request.Context(),
			func(ctx context.Context) ([]integration.MarketInputRow, error) {
				return sh.FetchPriceHistoryCanonical(ctx, companyName, limit)
			},
			func() ([]integration.MarketInputRow, error) {
				legacyRows, err := queryLegacyPriceHistory(db, companyName, limit)
				return toMarketInputs(legacyRows), err
			},
		)

		switch res.Outcome {
		case integration.OutcomeCanonicalServed:
			served := toPriceHistoryRows(res.Rows)

			// Optional controlled verification: compare the canonical result
			// against a legacy read. This is synchronous during the bounded
			// canary phase (documented trade-off in PRICE_HISTORY_CANARY_SPEC.md)
			// and never changes the served response.
			var verifyLegacyMs float64
			if sh.CanaryVerify() {
				vStart := time.Now()
				legacyRows, legacyErr := queryLegacyPriceHistory(db, companyName, limit)
				verifyLegacyMs = msSince(vStart)
				if legacyErr == nil {
					cres := sh.VerifyCanaryPriceHistory(c.Request.Context(), companyName, limit,
						toMarketInputs(legacyRows), 0)
					sh.RecordCanaryComparison(companyName, cres)
				}
			}

			sh.RecordCanarySuccess(integration.CanarySample{
				Symbol:      companyName,
				Route:       "canonical",
				Result:      "served",
				RowCount:    len(served),
				CanonicalMs: res.CanonicalMs,
				LegacyMs:    verifyLegacyMs,
				TotalMs:     msSince(start),
			})
			c.JSON(http.StatusOK, served)
			return

		case integration.OutcomeFallbackServed:
			sh.RecordCanaryFallback(integration.CanarySample{
				Symbol: companyName, Route: "fallback", Result: "legacy",
				RowCount: len(res.Rows), Fallback: true, Error: errString(res.CanonicalErr),
				CanonicalMs: res.CanonicalMs, LegacyMs: res.LegacyMs, TotalMs: msSince(start),
			})
			c.JSON(http.StatusOK, toPriceHistoryRows(res.Rows))
			return

		default: // OutcomeFallbackFailed
			sh.RecordLegacyFallbackError()
			sh.RecordCanaryFallback(integration.CanarySample{
				Symbol: companyName, Route: "fallback", Result: "error",
				Fallback: true, Error: errString(res.CanonicalErr) + "; legacy: " + errString(res.LegacyErr),
				CanonicalMs: res.CanonicalMs, LegacyMs: res.LegacyMs, TotalMs: msSince(start),
			})
			c.JSON(http.StatusInternalServerError, gin.H{"error": errString(res.LegacyErr)})
			return
		}
	}

	// LEGACY or SHADOW: legacy is authoritative.
	legacyStart := time.Now()
	result, err := queryLegacyPriceHistory(db, companyName, limit)
	legacyMs := msSince(legacyStart)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	if route == integration.RouteShadow && sh.Enabled() {
		sh.RecordShadowServed()
		sh.ComparePriceHistory(c.Request.Context(), companyName, limit,
			toMarketInputs(result), time.Duration(legacyMs*float64(time.Millisecond)))
	}
	sh.RecordLegacyServed(integration.CanarySample{
		Symbol: companyName, Route: "legacy", Result: "served",
		RowCount: len(result), LegacyMs: legacyMs, TotalMs: msSince(start),
	})

	c.JSON(http.StatusOK, result)
}

// queryLegacyPriceHistory executes the existing SQL Server read unchanged.
func queryLegacyPriceHistory(db *sql.DB, companyName string, limit int) ([]PriceHistoryRow, error) {
	query := `
		SELECT TOP (@limit)
			CONVERT(NVARCHAR(20), GregorianDate, 23) AS gdate,
			ISNULL(JalaliDate, '') AS jdate,
			ISNULL(ClosingPrice, 0) AS [close],
			ISNULL(LastPrice, 0) AS [last],
			ISNULL(HighPrice, 0) AS [high],
			ISNULL(LowPrice, 0) AS [low],
			ISNULL(Volume, 0) AS [vol],
			ISNULL(TradeValue, 0) AS [tval],
			ISNULL(ClosingChangePercent, 0) AS [chg]
		FROM dbo.MarketPriceHistory
		WHERE CompanyName = @name OR Symbol = @name
		ORDER BY GregorianDate DESC
	`
	rows, err := db.Query(
		query,
		sql.Named("limit", limit),
		sql.Named("name", companyName),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]PriceHistoryRow, 0)
	for rows.Next() {
		var r PriceHistoryRow
		if err := rows.Scan(
			&r.Date, &r.JalaliDate, &r.ClosingPrice, &r.LastPrice,
			&r.HighPrice, &r.LowPrice, &r.Volume, &r.TradeValue,
			&r.ChangePercent,
		); err != nil {
			return nil, err
		}
		result = append(result, r)
	}
	return result, rows.Err()
}

func msSince(t time.Time) float64 {
	return float64(time.Since(t).Microseconds()) / 1000.0
}

// toPriceHistoryRows converts canonical rows to the exact legacy response shape.
func toPriceHistoryRows(rows []integration.MarketInputRow) []PriceHistoryRow {
	out := make([]PriceHistoryRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, PriceHistoryRow{
			Date:          r.Date,
			JalaliDate:    r.JalaliDate,
			ClosingPrice:  r.ClosingPrice,
			LastPrice:     r.LastPrice,
			HighPrice:     r.HighPrice,
			LowPrice:      r.LowPrice,
			Volume:        r.Volume,
			TradeValue:    r.TradeValue,
			ChangePercent: r.ChangePercent,
		})
	}
	return out
}

// toMarketInputs adapts the legacy price rows to the integration comparison
// shape without altering any value.
func toMarketInputs(rows []PriceHistoryRow) []integration.MarketInputRow {
	out := make([]integration.MarketInputRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, integration.MarketInputRow{
			Date:          r.Date,
			JalaliDate:    r.JalaliDate,
			ClosingPrice:  r.ClosingPrice,
			LastPrice:     r.LastPrice,
			HighPrice:     r.HighPrice,
			LowPrice:      r.LowPrice,
			Volume:        r.Volume,
			TradeValue:    r.TradeValue,
			ChangePercent: r.ChangePercent,
		})
	}
	return out
}
