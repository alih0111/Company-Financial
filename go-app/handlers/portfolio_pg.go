package handlers

import (
	"context"
	"database/sql"
	"net/http"
	"strings"
	"time"

	"go-app/config"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

// PostgreSQL-backed portfolio using the canonical portfolio namespace
// (portfolios / assets / positions). SQL Server is not touched.

func portfolioTimeout() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 6*time.Second)
}

func userIDByUsername(ctx context.Context, db *sql.DB, username string) (string, bool, error) {
	var id string
	err := db.QueryRowContext(ctx, `SELECT id::text FROM auth.users WHERE username = $1`, strings.TrimSpace(username)).Scan(&id)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return id, true, nil
}

func defaultPortfolioID(ctx context.Context, db *sql.DB, userID string) (string, bool, error) {
	var id string
	err := db.QueryRowContext(ctx, `SELECT id::text FROM portfolio.portfolios WHERE user_id = $1 AND name = 'default' LIMIT 1`, userID).Scan(&id)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return id, true, nil
}

// resolveSecurityByLegacyCompany returns a canonical security id for a legacy
// company key (security mapping first, then the company's primary security).
func resolveSecurityByLegacyCompany(ctx context.Context, db *sql.DB, legacyKey string) (string, bool, error) {
	var id string
	err := db.QueryRowContext(ctx, `
		SELECT target_uuid::text FROM core.legacy_entity_map
		WHERE entity_type = 'security' AND legacy_key = $1 LIMIT 1`, legacyKey).Scan(&id)
	if err == nil {
		return id, true, nil
	}
	if err != sql.ErrNoRows {
		return "", false, err
	}
	err = db.QueryRowContext(ctx, `
		SELECT COALESCE(sec.id::text, '') FROM core.legacy_entity_map lem
		JOIN core.securities sec ON sec.company_id = lem.target_uuid AND sec.is_primary
		WHERE lem.entity_type = 'company' AND lem.legacy_key = $1 LIMIT 1`, legacyKey).Scan(&id)
	if err == sql.ErrNoRows || id == "" {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return id, true, nil
}

func legacyCompanyBySecurity(ctx context.Context, db *sql.DB, securityID string) string {
	var key string
	_ = db.QueryRowContext(ctx, `
		SELECT legacy_key FROM core.legacy_entity_map
		WHERE entity_type = 'security' AND target_uuid = $1::uuid LIMIT 1`, securityID).Scan(&key)
	return key
}

func getPortfolioPG(c *gin.Context) {
	username := c.GetString("username")
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres portfolio unavailable"})
		return
	}
	ctx, cancel := portfolioTimeout()
	defer cancel()

	uid, ok, err := userIDByUsername(ctx, db, username)
	if err != nil || !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	pid, ok, err := defaultPortfolioID(ctx, db, uid)
	if err != nil || !ok {
		c.JSON(http.StatusOK, models.PortfolioSummary{Holdings: []models.PortfolioHoldingEnriched{}})
		return
	}

	rows, err := db.QueryContext(ctx, `
		SELECT COALESCE(pa.security_id::text, ''), COALESCE(pa.symbol, ''), COALESCE(pa.name, ''),
		       pos.quantity, COALESCE(pos.avg_cost_rial, 0),
		       COALESCE(lp.price, 0)
		FROM portfolio.positions pos
		JOIN portfolio.assets pa ON pa.id = pos.asset_id
		LEFT JOIN LATERAL (
			SELECT po.closing_price_rial AS price
			FROM market.price_observations po
			WHERE pa.security_id IS NOT NULL AND po.security_id = pa.security_id AND po.price_series = 'adjusted'
			ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC LIMIT 1
		) lp ON true
		WHERE pos.portfolio_id = $1`, pid)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "portfolio query error"})
		return
	}
	defer rows.Close()

	enriched := []models.PortfolioHoldingEnriched{}
	var totalMarketValue, totalCost float64
	for rows.Next() {
		var secID, symbol, name string
		var qty, cost, live float64
		if err := rows.Scan(&secID, &symbol, &name, &qty, &cost, &live); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "portfolio scan error"})
			return
		}
		h := models.PortfolioHolding{CompanyID: legacyCompanyBySecurity(ctx, db, secID), Symbol: symbol, CompanyName: name, Quantity: qty, BuyPrice: cost}
		e := models.PortfolioHoldingEnriched{PortfolioHolding: h}
		if live > 0 {
			e.LatestPrice = live
			e.HasLivePrice = true
		}
		e.CostBasis = qty * cost
		if e.HasLivePrice {
			e.MarketValue = qty * live
		}
		e.Gain = e.MarketValue - e.CostBasis
		if e.CostBasis != 0 {
			e.GainPct = e.Gain / e.CostBasis * 100
		}
		totalMarketValue += e.MarketValue
		totalCost += e.CostBasis
		enriched = append(enriched, e)
	}
	for i := range enriched {
		if totalMarketValue > 0 {
			enriched[i].Weight = round(enriched[i].MarketValue/totalMarketValue*100, 2)
		}
	}
	totalGain := totalMarketValue - totalCost
	var gainPct float64
	if totalCost != 0 {
		gainPct = totalGain / totalCost * 100
	}
	c.JSON(http.StatusOK, models.PortfolioSummary{
		TotalCost: round(totalCost, 2), TotalCostRaw: totalCost,
		TotalMarketValue: round(totalMarketValue, 2), TotalGain: round(totalGain, 2),
		TotalGainPct: round(gainPct, 2), HoldingsCount: len(enriched), Holdings: enriched,
	})
}

func upsertHoldingPG(c *gin.Context, req UpsertHoldingRequest) {
	username := c.GetString("username")
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres portfolio unavailable"})
		return
	}
	ctx, cancel := portfolioTimeout()
	defer cancel()

	companyID := strings.TrimSpace(req.CompanyID)
	if companyID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "company_id is required"})
		return
	}
	if req.Quantity <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "quantity must be greater than 0"})
		return
	}
	uid, ok, err := userIDByUsername(ctx, db, username)
	if err != nil || !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	pid, ok, err := defaultPortfolioID(ctx, db, uid)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "portfolio lookup error"})
		return
	}
	if !ok {
		if err := db.QueryRowContext(ctx, `INSERT INTO portfolio.portfolios (id, user_id, name, portfolio_type, base_currency, is_active, created_at, updated_at)
			VALUES (gen_random_uuid(), $1, 'default', 'personal', 'IRR', true, now(), now()) RETURNING id::text`, uid).Scan(&pid); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "portfolio create error"})
			return
		}
	}

	secID, found, err := resolveSecurityByLegacyCompany(ctx, db, companyID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "identity resolution error"})
		return
	}
	var assetID string
	if found {
		err = db.QueryRowContext(ctx, `SELECT id::text FROM portfolio.assets WHERE security_id = $1`, secID).Scan(&assetID)
		if err == sql.ErrNoRows {
			name := req.CompanyName
			if strings.TrimSpace(name) == "" {
				name = req.Symbol
			}
			if strings.TrimSpace(name) == "" {
				name = "asset"
			}
			if err := db.QueryRowContext(ctx, `INSERT INTO portfolio.assets (id, security_id, asset_type, name, symbol, pricing_source, is_active, created_at, updated_at)
				VALUES (gen_random_uuid(), $1, 'stock', $2, $3, 'market', true, now(), now()) RETURNING id::text`,
				secID, name, req.Symbol).Scan(&assetID); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "asset create error"})
				return
			}
		} else if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "asset lookup error"})
			return
		}
	} else {
		name := req.CompanyName
		if strings.TrimSpace(name) == "" {
			name = req.Symbol
		}
		if strings.TrimSpace(name) == "" {
			name = "asset"
		}
		if err := db.QueryRowContext(ctx, `INSERT INTO portfolio.assets (id, security_id, asset_type, name, symbol, pricing_source, is_active, created_at, updated_at)
			VALUES (gen_random_uuid(), NULL, 'other', $1, $2, 'manual', true, now(), now()) RETURNING id::text`,
			name, req.Symbol).Scan(&assetID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "asset create error"})
			return
		}
	}

	if _, err := db.ExecContext(ctx, `INSERT INTO portfolio.positions (portfolio_id, asset_id, quantity, avg_cost_rial, cost_basis_rial, as_of_at, computed_from_tx_count)
		VALUES ($1, $2, $3, $4, $5, now(), 0)
		ON CONFLICT (portfolio_id, asset_id) DO UPDATE SET quantity=EXCLUDED.quantity,
			avg_cost_rial=EXCLUDED.avg_cost_rial, cost_basis_rial=EXCLUDED.cost_basis_rial, as_of_at=now()`,
		pid, assetID, req.Quantity, req.BuyPrice, req.Quantity*req.BuyPrice); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "position save error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "holding saved", "canonical": true})
}

func deleteHoldingPG(c *gin.Context, companyID string) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres portfolio unavailable"})
		return
	}
	ctx, cancel := portfolioTimeout()
	defer cancel()
	uid, ok, err := userIDByUsername(ctx, db, c.GetString("username"))
	if err != nil || !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	pid, ok, err := defaultPortfolioID(ctx, db, uid)
	if err != nil || !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "portfolio not found"})
		return
	}
	secID, found, err := resolveSecurityByLegacyCompany(ctx, db, strings.TrimSpace(companyID))
	if err != nil || !found {
		c.JSON(http.StatusNotFound, gin.H{"error": "holding not found"})
		return
	}
	res, err := db.ExecContext(ctx, `DELETE FROM portfolio.positions WHERE portfolio_id=$1 AND asset_id IN (SELECT id FROM portfolio.assets WHERE security_id=$2)`, pid, secID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete error"})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": "holding not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "holding deleted", "canonical": true})
}
