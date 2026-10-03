package handlers

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// Market assets = exchange indices (شاخص‌ها) + gold/commodity funds (نمادهای طلا/کالا).
//
// Indices live in market.index_observations (they are not securities); funds are
// ordinary core.securities rows with security_type in (gold, commodity, etf, fund).
// Both are served through the same price-history contract, so the existing
// PriceChart component renders them without a dedicated chart implementation.

// MarketIndex is the latest known level of one exchange index.
type MarketIndex struct {
	Code            string  `json:"code"`
	Name            string  `json:"name"`
	Value           float64 `json:"value"`
	Change          float64 `json:"change"`
	ChangePercent   float64 `json:"change_percent"`
	Min             float64 `json:"min"`
	Max             float64 `json:"max"`
	TradeDate       string  `json:"trade_date"`
	JalaliDate      string  `json:"jalali_date"`
	MarketValueRial float64 `json:"market_value_rial"`
	TradeValueRial  float64 `json:"trade_value_rial"`
}

// MarketFund is one gold/commodity fund (a real, tradable security).
type MarketFund struct {
	Symbol        string  `json:"symbol"`
	Name          string  `json:"name"`
	Kind          string  `json:"kind"`
	LastPrice     float64 `json:"last_price"`
	ChangePercent float64 `json:"change_percent"`
	TradeDate     string  `json:"trade_date"`
	JalaliDate    string  `json:"jalali_date"`
	Observations  int     `json:"observations"`
}

type marketAssetsResponse struct {
	Indices []MarketIndex `json:"indices"`
	Funds   []MarketFund  `json:"funds"`
	Source  string        `json:"source"`
}

// preferredIndexOrder keeps the headline index first, then the equal-weight one.
var preferredIndexOrder = []string{
	"TEDPIX", "TEDPIX_EW", "TEDPIX_PRICE", "TEDPIX_EW_PRICE",
	"TEDPIX_FREEFLOAT", "MARKET_FIRST", "MARKET_SECOND",
}

func indexRank(code string) int {
	for i, c := range preferredIndexOrder {
		if c == code {
			return i
		}
	}
	return len(preferredIndexOrder)
}

// GetMarketAssets lists indices and gold/commodity funds for the market page.
func GetMarketAssets(c *gin.Context) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "canonical postgres unavailable"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
	defer cancel()

	resp := marketAssetsResponse{Indices: []MarketIndex{}, Funds: []MarketFund{}, Source: "canonical"}

	idxRows, err := db.QueryContext(ctx, `
		SELECT DISTINCT ON (index_code)
		       index_code, index_name, trade_date, COALESCE(jalali_date_text, ''),
		       value, COALESCE(change_value, 0), COALESCE(change_percent, 0),
		       COALESCE(min_value, 0), COALESCE(max_value, 0),
		       COALESCE(market_value_rial, 0), COALESCE(trade_value_rial, 0)
		FROM market.index_observations
		ORDER BY index_code, trade_date DESC`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	for idxRows.Next() {
		var m MarketIndex
		var tradeDate any
		if err := idxRows.Scan(&m.Code, &m.Name, &tradeDate, &m.JalaliDate, &m.Value,
			&m.Change, &m.ChangePercent, &m.Min, &m.Max, &m.MarketValueRial, &m.TradeValueRial); err != nil {
			idxRows.Close()
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		m.TradeDate = pgDateString(tradeDate)
		resp.Indices = append(resp.Indices, m)
	}
	idxRows.Close()
	sort.SliceStable(resp.Indices, func(i, j int) bool {
		ri, rj := indexRank(resp.Indices[i].Code), indexRank(resp.Indices[j].Code)
		if ri != rj {
			return ri < rj
		}
		return resp.Indices[i].Code < resp.Indices[j].Code
	})

	fundRows, err := db.QueryContext(ctx, `
		SELECT s.codal_symbol,
		       COALESCE(NULLIF(BTRIM(s.brs_name), ''), s.codal_symbol),
		       s.security_type,
		       COALESCE(p.closing_price_rial, 0),
		       COALESCE(p.closing_change_percent, 0),
		       p.trade_date,
		       COALESCE(p.jalali_date_text, ''),
		       cnt.n
		FROM core.securities s
		LEFT JOIN LATERAL (
		    SELECT trade_date, closing_price_rial, closing_change_percent, jalali_date_text
		    FROM market.price_observations po
		    WHERE po.security_id = s.id AND po.price_series = 'adjusted'
		    ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
		    LIMIT 1) p ON true
		LEFT JOIN LATERAL (
		    SELECT count(*) AS n FROM market.price_observations po2 WHERE po2.security_id = s.id) cnt ON true
		WHERE s.is_active AND s.security_type IN ('gold', 'commodity', 'etf', 'fund')
		ORDER BY (s.security_type = 'gold') DESC, s.security_type, s.codal_symbol`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	defer fundRows.Close()
	for fundRows.Next() {
		var f MarketFund
		var tradeDate sql.NullString
		if err := fundRows.Scan(&f.Symbol, &f.Name, &f.Kind, &f.LastPrice,
			&f.ChangePercent, &tradeDate, &f.JalaliDate, &f.Observations); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if tradeDate.Valid {
			f.TradeDate = tradeDate.String
		}
		resp.Funds = append(resp.Funds, f)
	}

	c.JSON(http.StatusOK, resp)
}

// indexHistoryRows reads an index series converted to the /api/price-history
// contract, so the client's PriceChart renders indices with no special case.
// Match is by stable code (TEDPIX) or Persian display name (شاخص کل).
func indexHistoryRows(ctx context.Context, db *sql.DB, key string, limit int) ([]PriceHistoryRow, error) {
	key = strings.TrimSpace(key)
	if key == "" {
		return nil, nil
	}
	if limit <= 0 {
		limit = 365
	} else if limit > MaxPriceHistoryLimit {
		limit = MaxPriceHistoryLimit
	}
	rows, err := db.QueryContext(ctx, `
		SELECT trade_date, COALESCE(jalali_date_text, ''), value,
		       COALESCE(max_value, 0), COALESCE(min_value, 0),
		       COALESCE(trade_value_rial, 0), COALESCE(change_percent, 0)
		FROM market.index_observations
		WHERE index_code = $1 OR index_name = $1
		ORDER BY trade_date DESC
		LIMIT $2`, key, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]PriceHistoryRow, 0, priceHistoryPrealloc(limit))
	for rows.Next() {
		var r PriceHistoryRow
		var tradeDate any
		if err := rows.Scan(&tradeDate, &r.JalaliDate, &r.ClosingPrice,
			&r.HighPrice, &r.LowPrice, &r.TradeValue, &r.ChangePercent); err != nil {
			return nil, err
		}
		r.Date = pgDateString(tradeDate)
		// An index level is a single value; OHLC collapses to it (with the day's
		// intraday range preserved as high/low).
		r.LastPrice = r.ClosingPrice
		out = append(out, r)
	}
	return out, rows.Err()
}

func pgDateString(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case time.Time:
		return t.Format("2006-01-02")
	case string:
		return t
	case []byte:
		return string(t)
	default:
		return ""
	}
}

// looksLikeIndex cheaply rejects ordinary symbols so the hot price-history path
// pays no extra query for stocks. Indices are named «شاخص …» or use their
// stable uppercase code (TEDPIX, TEDPIX_EW, …).
func looksLikeIndex(name string) bool {
	name = strings.TrimSpace(name)
	if strings.HasPrefix(name, "شاخص") {
		return true
	}
	if name == "" || name[0] < 'A' || name[0] > 'Z' {
		return false
	}
	for _, r := range name {
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' {
			continue
		}
		return false
	}
	return true
}

// MarketCollectRequest drives the market-assets collector (py/market_assets.py).
type MarketCollectRequest struct {
	Mode   string `json:"mode"`   // "daily" | "backfill" | "ensure"
	Symbol string `json:"symbol"` // backfill: a single registry symbol
	Limit  int    `json:"limit"`  // backfill: max symbols (free BRS quota ~10/day)
	All    bool   `json:"all"`    // backfill: ignore already-covered funds
}

// RunMarketAssetsCollector refreshes indices and gold/commodity fund prices.
// Admin-only; logs stream to the server console like the other collectors.
func RunMarketAssetsCollector(c *gin.Context) {
	if !c.GetBool("isAdmin") {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin only"})
		return
	}

	var req MarketCollectRequest
	_ = c.ShouldBindJSON(&req)
	mode := req.Mode
	if mode != "daily" && mode != "backfill" && mode != "ensure" {
		mode = "daily"
	}

	args := []string{"py/market_assets.py", mode}
	if mode == "backfill" {
		if req.Symbol != "" {
			args = append(args, "--symbol", req.Symbol)
		}
		if req.Limit > 0 {
			args = append(args, "--limit", strconv.Itoa(req.Limit))
		}
		if req.All {
			args = append(args, "--all")
		}
	}

	pythonExe := os.Getenv("CDF_PYTHON")
	if pythonExe == "" {
		pythonExe = "python"
	}
	cmd := exec.Command(pythonExe, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stdout pipe: " + err.Error()})
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stderr pipe: " + err.Error()})
		return
	}
	log.Printf("🔍 market assets collector args: %v", args)
	if err := cmd.Start(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "start failed: " + err.Error()})
		return
	}
	go streamLogs(stdout)
	go streamLogs(stderr)
	if err := cmd.Wait(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "collector failed: " + err.Error(), "mode": mode})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "market assets collector executed", "mode": mode})
}

