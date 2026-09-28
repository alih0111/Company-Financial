package handlers

import (
	"context"
	"database/sql"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"go-app/config"
	"go-app/models"

	"github.com/gin-gonic/gin"
)

// ─────────────────────────────────────────────────────────────────────
// دارایی خانواده — پیاده‌سازی PostgreSQL (namespace: family)
// معادل دقیق هندلرهای SQL Server در فایل family_assets.go.
// کانکشن از pool مشترک config.GetPG() گرفته می‌شود و بسته نمی‌شود.
// ─────────────────────────────────────────────────────────────────────

func familyPGTimeout() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 30*time.Second)
}

// familyPGDB pool مشترک PostgreSQL را برمی‌گرداند؛ در صورت نبود 503 می‌دهد.
func familyPGDB(c *gin.Context) (*sql.DB, bool) {
	db, err := config.GetPG()
	if err != nil || db == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "postgres family unavailable"})
		return nil, false
	}
	return db, true
}

// ────────────────────────────── بارگذاری داده ──────────────────────────────

func loadFamilyAssetsPG(ctx context.Context, db *sql.DB) ([]familyAssetDef, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT asset_id, name, COALESCE(symbol, ''), category, commission_rate, sort_order
		FROM family.assets
		WHERE is_active = true
		ORDER BY sort_order, asset_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []familyAssetDef{}
	for rows.Next() {
		var a familyAssetDef
		if err := rows.Scan(&a.ID, &a.Name, &a.Symbol, &a.Category, &a.CommissionRate, &a.SortOrder); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func loadFamilyPeoplePG(ctx context.Context, db *sql.DB) ([]familyPersonDef, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT person_id, name, sort_order
		FROM family.people
		WHERE is_active = true
		ORDER BY sort_order, person_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []familyPersonDef{}
	for rows.Next() {
		var p familyPersonDef
		if err := rows.Scan(&p.ID, &p.Name, &p.SortOrder); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func loadFamilyHoldingsPG(ctx context.Context, db *sql.DB) ([]familyHoldingRow, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT person_id, asset_id, quantity, cost_basis
		FROM family.holdings`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []familyHoldingRow{}
	for rows.Next() {
		var h familyHoldingRow
		if err := rows.Scan(&h.PersonID, &h.AssetID, &h.Quantity, &h.CostBasis); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

func loadFamilyPricesPG(ctx context.Context, db *sql.DB) (map[int]familyPriceRow, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT DISTINCT ON (asset_id) asset_id, price, date_key
		FROM family.prices
		WHERE price > 0
		ORDER BY asset_id, date_key DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := map[int]familyPriceRow{}
	for rows.Next() {
		var r familyPriceRow
		if err := rows.Scan(&r.AssetID, &r.Price, &r.DateKey); err != nil {
			return nil, err
		}
		out[r.AssetID] = r
	}
	return out, rows.Err()
}

func loadFamilyAccountsPG(ctx context.Context, db *sql.DB) (map[int]float64, error) {
	rows, err := db.QueryContext(ctx, `SELECT person_id, cash_balance FROM family.accounts`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := map[int]float64{}
	for rows.Next() {
		var id int
		var bal float64
		if err := rows.Scan(&id, &bal); err != nil {
			return nil, err
		}
		out[id] = bal
	}
	return out, rows.Err()
}

// ────────────────────────────── GET /family/assets ──────────────────────────────

func getFamilyAssetsPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}
	ctx, cancel := familyPGTimeout()
	defer cancel()

	people, err := loadFamilyPeoplePG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load people: " + err.Error()})
		return
	}
	assets, err := loadFamilyAssetsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load assets: " + err.Error()})
		return
	}
	holdings, err := loadFamilyHoldingsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load holdings: " + err.Error()})
		return
	}
	prices, err := loadFamilyPricesPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load prices: " + err.Error()})
		return
	}
	accounts, err := loadFamilyAccountsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load accounts: " + err.Error()})
		return
	}

	assetName := map[int]string{}
	assetRate := map[int]float64{}
	for _, a := range assets {
		assetName[a.ID] = a.Name
		assetRate[a.ID] = a.CommissionRate
	}

	personHoldings := map[int][]models.FamilyHoldingRow{}
	assetAgg := map[int]*models.FamilyAssetRow{}
	for _, a := range assets {
		assetAgg[a.ID] = &models.FamilyAssetRow{
			AssetID:        a.ID,
			Name:           a.Name,
			Symbol:         a.Symbol,
			Category:       a.Category,
			CommissionRate: a.CommissionRate,
			SortOrder:      a.SortOrder,
		}
		if pr, ok := prices[a.ID]; ok {
			assetAgg[a.ID].LatestPrice = pr.Price
			assetAgg[a.ID].PriceDate = pr.DateKey
		}
	}

	for _, h := range holdings {
		pr, hasPrice := prices[h.AssetID]
		agg := assetAgg[h.AssetID]
		if agg == nil {
			continue
		}

		row := models.FamilyHoldingRow{
			AssetID:   h.AssetID,
			AssetName: assetName[h.AssetID],
			Quantity:  h.Quantity,
			CostBasis: h.CostBasis,
		}
		if hasPrice {
			row.Value = h.Quantity * pr.Price * (1 - assetRate[h.AssetID])
			row.Profit = row.Value - h.CostBasis
			if h.CostBasis != 0 {
				row.ProfitPct = (row.Value / h.CostBasis) - 1
			}
		}

		personHoldings[h.PersonID] = append(personHoldings[h.PersonID], row)

		agg.TotalQuantity += h.Quantity
		agg.TotalCost += h.CostBasis
		agg.TotalValue += row.Value
		agg.TotalProfit += row.Profit
	}

	var holdingsValue, totalCash float64
	personRows := make([]models.FamilyPersonRow, 0, len(people))
	for _, p := range people {
		ph := personHoldings[p.ID]
		if ph == nil {
			ph = []models.FamilyHoldingRow{}
		}

		pr := models.FamilyPersonRow{
			PersonID:    p.ID,
			Name:        p.Name,
			SortOrder:   p.SortOrder,
			CashBalance: accounts[p.ID],
			Holdings:    ph,
		}

		for i := range ph {
			pr.HoldingsValue += ph[i].Value
			pr.TotalCost += ph[i].CostBasis
		}
		for i := range ph {
			if pr.HoldingsValue > 0 {
				pr.Holdings[i].Weight = ph[i].Value / pr.HoldingsValue
			}
		}

		pr.TotalValue = pr.HoldingsValue + pr.CashBalance
		pr.Profit = pr.HoldingsValue - pr.TotalCost
		if pr.TotalCost != 0 {
			pr.ProfitPct = (pr.HoldingsValue / pr.TotalCost) - 1
		}

		holdingsValue += pr.HoldingsValue
		totalCash += pr.CashBalance
		personRows = append(personRows, pr)
	}

	assetRows := make([]models.FamilyAssetRow, 0, len(assets))
	var stocksTotal, goldTotal, dollarTotal float64
	latestDateKey := ""
	for _, a := range assets {
		agg := assetAgg[a.ID]
		if agg.TotalCost != 0 {
			agg.ProfitPct = (agg.TotalValue / agg.TotalCost) - 1
		}
		if holdingsValue > 0 {
			agg.Weight = agg.TotalValue / holdingsValue
		}
		switch a.Category {
		case "gold":
			goldTotal += agg.TotalValue
		case "dollar":
			dollarTotal += agg.TotalValue
		default:
			stocksTotal += agg.TotalValue
		}
		if agg.PriceDate > latestDateKey {
			latestDateKey = agg.PriceDate
		}
		assetRows = append(assetRows, *agg)
	}

	grandTotal := holdingsValue + totalCash
	for i := range personRows {
		if grandTotal > 0 {
			personRows[i].ShareOfTotal = personRows[i].TotalValue / grandTotal
		}
	}

	totalCost := 0.0
	for _, a := range assetRows {
		totalCost += a.TotalCost
	}
	totalProfit := holdingsValue - totalCost
	var totalProfitPct float64
	if totalCost != 0 {
		totalProfitPct = (holdingsValue / totalCost) - 1
	}

	state := models.FamilyState{
		TodayDateKey: todayFamilyDateKey(),
		Assets:       assetRows,
		People:       personRows,
		Summary: models.FamilySummary{
			LatestDateKey:  latestDateKey,
			HoldingsValue:  holdingsValue,
			TotalCash:      totalCash,
			GrandTotal:     grandTotal,
			TotalCost:      totalCost,
			TotalProfit:    totalProfit,
			TotalProfitPct: totalProfitPct,
			BestTomorrow:   grandTotal + familyTomorrowRange*holdingsValue,
			WorstTomorrow:  grandTotal - familyTomorrowRange*holdingsValue,
			StocksTotal:    stocksTotal,
			GoldTotal:      goldTotal,
			DollarTotal:    dollarTotal,
		},
	}

	c.JSON(http.StatusOK, state)
}

// ────────────────────────────── سینک قیمت از بازار ──────────────────────────────

func syncFamilyPricesFromMarketPG(ctx context.Context, db *sql.DB, fullBackfill bool) (updated []familySyncedPrice, missing []string, err error) {
	assets, err := loadFamilyAssetsPG(ctx, db)
	if err != nil {
		return nil, nil, err
	}

	updated = []familySyncedPrice{}
	missing = []string{}
	maxDate := ""

	var floorDate string
	if fullBackfill {
		var minDate sql.NullString
		if err := db.QueryRowContext(ctx, `SELECT MIN(date_key) FROM family.history`).Scan(&minDate); err != nil {
			return nil, nil, err
		}
		if minDate.Valid {
			floorDate = minDate.String
			if _, err := db.ExecContext(ctx, `DELETE FROM family.prices WHERE date_key < $1`, floorDate); err != nil {
				return nil, nil, err
			}
		}
	}

	for _, a := range assets {
		symbol := a.Symbol
		if symbol == "" {
			symbol = a.Name
		}

		type priceRow struct {
			Date  time.Time
			Last  sql.NullFloat64
			Close sql.NullFloat64
		}
		var rows []priceRow

		if fullBackfill {
			rs, err := db.QueryContext(ctx, `
				SELECT po.trade_date, po.last_price_rial, po.closing_price_rial
				FROM market.daily_prices po
				JOIN core.securities s ON s.id = po.security_id
				LEFT JOIN core.companies c ON c.id = s.company_id
				WHERE s.codal_symbol = $1 OR c.display_name = $1
				ORDER BY po.trade_date`, symbol)
			if err != nil {
				return nil, nil, err
			}
			for rs.Next() {
				var r priceRow
				var last, close sql.NullFloat64
				if err := rs.Scan(&r.Date, &last, &close); err != nil {
					rs.Close()
					return nil, nil, err
				}
				r.Last, r.Close = last, close
				rows = append(rows, r)
			}
			rs.Close()
			if err := rs.Err(); err != nil {
				return nil, nil, err
			}
		} else {
			var last, close sql.NullFloat64
			var tradeDate sql.NullTime
			if err := db.QueryRowContext(ctx, `
				SELECT po.last_price_rial, po.closing_price_rial, po.trade_date
				FROM market.daily_prices po
				JOIN core.securities s ON s.id = po.security_id
				LEFT JOIN core.companies c ON c.id = s.company_id
				WHERE s.codal_symbol = $1 OR c.display_name = $1
				ORDER BY po.trade_date DESC, po.observation_id DESC
				LIMIT 1`, symbol).Scan(&last, &close, &tradeDate); err != nil {
				if err == sql.ErrNoRows {
					missing = append(missing, a.Name)
					continue
				}
				return nil, nil, err
			}
			if tradeDate.Valid {
				rows = append(rows, priceRow{Date: tradeDate.Time, Last: last, Close: close})
			}
		}

		if len(rows) == 0 {
			missing = append(missing, a.Name)
			continue
		}

		syncedAny := false
		lastDateKey := ""
		lastPrice := 0.0
		for _, r := range rows {
			price := 0.0
			if r.Last.Valid && r.Last.Float64 > 0 {
				price = r.Last.Float64
			} else if r.Close.Valid && r.Close.Float64 > 0 {
				price = r.Close.Float64
			} else {
				continue
			}

			jy, jm, jd := gregorianToJalali(r.Date.Year(), int(r.Date.Month()), r.Date.Day())
			dateKey := formatFamilyDateKey(jy, jm, jd)
			if floorDate != "" && dateKey < floorDate {
				continue
			}

			if _, err := db.ExecContext(ctx, `
				INSERT INTO family.prices (date_key, asset_id, price)
				VALUES ($1, $2, $3)
				ON CONFLICT (date_key, asset_id) DO UPDATE SET price = EXCLUDED.price`,
				dateKey, a.ID, price); err != nil {
				return nil, nil, err
			}
			syncedAny = true
			lastDateKey = dateKey
			lastPrice = price
			if dateKey > maxDate {
				maxDate = dateKey
			}
		}

		if syncedAny {
			updated = append(updated, familySyncedPrice{
				AssetID: a.ID,
				Name:    a.Name,
				Symbol:  symbol,
				DateKey: lastDateKey,
				Price:   lastPrice,
			})
		} else {
			missing = append(missing, a.Name)
		}
	}

	if maxDate != "" {
		if total, err := computeFamilyTotalPG(ctx, db, maxDate); err == nil {
			_ = upsertFamilyHistoryPG(ctx, db, maxDate, total)
		}
	}

	return updated, missing, nil
}

func syncFamilyPricesPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req struct {
		Backfill bool `json:"backfill"`
	}
	_ = c.ShouldBindJSON(&req)

	ctx, cancel := familyPGTimeout()
	defer cancel()

	updated, missing, err := syncFamilyPricesFromMarketPG(ctx, db, req.Backfill)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "sync: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"updated":  updated,
		"missing":  missing,
		"backfill": req.Backfill,
	})
}

// ────────────────────────────── POST /family/prices ──────────────────────────────

func saveFamilyPricesPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req saveFamilyPricesRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	dateKey := strings.TrimSpace(req.DateKey)
	if !familyDateKeyRe.MatchString(dateKey) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "date_key must be like 1405/05/26"})
		return
	}
	if len(req.Prices) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "prices is empty"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}
	defer tx.Rollback()

	for _, p := range req.Prices {
		if p.Price <= 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "price must be > 0 for asset " + strconv.Itoa(p.AssetID)})
			return
		}
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO family.prices (date_key, asset_id, price)
			VALUES ($1, $2, $3)
			ON CONFLICT (date_key, asset_id) DO UPDATE SET price = EXCLUDED.price`,
			dateKey, p.AssetID, p.Price); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "save price: " + err.Error()})
			return
		}
	}

	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	total, err := computeFamilyTotalPG(ctx, db, dateKey)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "compute total: " + err.Error()})
		return
	}

	if err := upsertFamilyHistoryPG(ctx, db, dateKey, total); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save history: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "saved", "date_key": dateKey, "total_value": total})
}

func computeFamilyTotalPG(ctx context.Context, db *sql.DB, dateKey string) (float64, error) {
	var holdingsValue, totalCash float64
	err := db.QueryRowContext(ctx, `
		SELECT
			COALESCE(SUM(h.quantity * pr.price * (1 - a.commission_rate)), 0),
			(SELECT COALESCE(SUM(cash_balance), 0) FROM family.accounts)
		FROM family.holdings h
		JOIN family.assets a ON a.asset_id = h.asset_id
		LEFT JOIN LATERAL (
			SELECT p.price
			FROM family.prices p
			WHERE p.asset_id = h.asset_id AND p.date_key <= $1 AND p.price > 0
			ORDER BY p.date_key DESC
			LIMIT 1
		) pr ON true`,
		dateKey).Scan(&holdingsValue, &totalCash)
	if err != nil {
		return 0, err
	}
	return holdingsValue + totalCash, nil
}

func upsertFamilyHistoryPG(ctx context.Context, db *sql.DB, dateKey string, total float64) error {
	var prev sql.NullFloat64
	if err := db.QueryRowContext(ctx, `
		SELECT total_value
		FROM family.history
		WHERE date_key < $1
		ORDER BY date_key DESC
		LIMIT 1`, dateKey).Scan(&prev); err != nil && err != sql.ErrNoRows {
		return err
	}

	change := 0.0
	changePct := 0.0
	if prev.Valid {
		change = total - prev.Float64
		if prev.Float64 != 0 {
			changePct = change / prev.Float64
		}
	}

	_, err := db.ExecContext(ctx, `
		INSERT INTO family.history (date_key, total_value, change_value, change_pct)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (date_key) DO UPDATE SET
			total_value = EXCLUDED.total_value,
			change_value = EXCLUDED.change_value,
			change_pct = EXCLUDED.change_pct,
			recorded_at = now()`,
		dateKey, total, change, changePct)
	return err
}

func refreshLatestFamilyHistoryPG(ctx context.Context, db *sql.DB) {
	var latest sql.NullString
	if err := db.QueryRowContext(ctx, `SELECT MAX(date_key) FROM family.prices`).Scan(&latest); err != nil || !latest.Valid {
		return
	}

	var exists int
	if err := db.QueryRowContext(ctx, `
		SELECT COUNT(1) FROM family.history WHERE date_key = $1`, latest.String).Scan(&exists); err != nil || exists == 0 {
		return
	}

	if total, err := computeFamilyTotalPG(ctx, db, latest.String); err == nil {
		_ = upsertFamilyHistoryPG(ctx, db, latest.String, total)
	}
}

// ────────────────────────────── PUT /family/holdings ──────────────────────────────

func upsertFamilyHoldingPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req upsertFamilyHoldingRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.Quantity < 0 || req.CostBasis < 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "quantity and cost_basis must be >= 0"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	if req.Quantity == 0 {
		if _, err := db.ExecContext(ctx, `
			DELETE FROM family.holdings
			WHERE person_id = $1 AND asset_id = $2`, req.PersonID, req.AssetID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
			return
		}
	} else {
		if _, err := db.ExecContext(ctx, `
			INSERT INTO family.holdings (person_id, asset_id, quantity, cost_basis)
			VALUES ($1, $2, $3, $4)
			ON CONFLICT (person_id, asset_id) DO UPDATE SET
				quantity = EXCLUDED.quantity, cost_basis = EXCLUDED.cost_basis`,
			req.PersonID, req.AssetID, req.Quantity, req.CostBasis); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "save: " + err.Error()})
			return
		}
	}

	refreshLatestFamilyHistoryPG(ctx, db)
	c.JSON(http.StatusOK, gin.H{"message": "saved"})
}

func deleteFamilyHoldingPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	personID, _ := strconv.Atoi(c.Query("person_id"))
	assetID, _ := strconv.Atoi(c.Query("asset_id"))
	if personID <= 0 || assetID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id and asset_id are required"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	if _, err := db.ExecContext(ctx, `
		DELETE FROM family.holdings
		WHERE person_id = $1 AND asset_id = $2`, personID, assetID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
		return
	}

	refreshLatestFamilyHistoryPG(ctx, db)
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// ────────────────────────────── POST /family/people و /family/assets ──────────────────────────────

func createFamilyPersonPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req createFamilyPersonRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	name := strings.TrimSpace(normalizePersian(req.Name))
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "name is required"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	var id int
	if err := db.QueryRowContext(ctx, `
		INSERT INTO family.people (name, sort_order)
		VALUES ($1, $2)
		RETURNING person_id`, name, req.SortOrder).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "person_id": id})
}

func createFamilyAssetPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req createFamilyAssetRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	name := strings.TrimSpace(normalizePersian(req.Name))
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "name is required"})
		return
	}

	switch req.Category {
	case "stock", "gold", "dollar", "other":
	default:
		req.Category = "stock"
	}

	rate, found := familyAssetCommissions[name]
	if !found {
		rate = familyDefaultCommission
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	var id int
	if err := db.QueryRowContext(ctx, `
		INSERT INTO family.assets (name, category, commission_rate, sort_order)
		VALUES ($1, $2, $3, $4)
		RETURNING asset_id`, name, req.Category, rate, req.SortOrder).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "asset_id": id})
}

// ────────────────────────────── PUT /family/account ──────────────────────────────

func updateFamilyAccountPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req updateFamilyAccountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.PersonID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id is required"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	if _, err := db.ExecContext(ctx, `
		INSERT INTO family.accounts (person_id, cash_balance)
		VALUES ($1, $2)
		ON CONFLICT (person_id) DO UPDATE SET cash_balance = EXCLUDED.cash_balance`,
		req.PersonID, req.CashBalance); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save: " + err.Error()})
		return
	}

	refreshLatestFamilyHistoryPG(ctx, db)
	c.JSON(http.StatusOK, gin.H{"message": "saved"})
}

// ────────────────────────────── جریان‌های نقدی ──────────────────────────────

func getFamilyCashFlowsPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	limit := 200
	if v, err := strconv.Atoi(c.DefaultQuery("limit", "200")); err == nil && v > 0 && v <= 2000 {
		limit = v
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	rows, err := db.QueryContext(ctx, `
		SELECT id, date_key, amount, direction, COALESCE(note, '')
		FROM family.cash_flows
		ORDER BY date_key DESC, id DESC
		LIMIT $1`, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query: " + err.Error()})
		return
	}
	defer rows.Close()

	out := []models.FamilyCashFlow{}
	for rows.Next() {
		var f models.FamilyCashFlow
		if err := rows.Scan(&f.ID, &f.DateKey, &f.Amount, &f.Direction, &f.Note); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan: " + err.Error()})
			return
		}
		out = append(out, f)
	}
	if err := rows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, out)
}

func addFamilyCashFlowPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	var req addFamilyCashFlowRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	dateKey := strings.TrimSpace(req.DateKey)
	if !familyDateKeyRe.MatchString(dateKey) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "date_key must be like 1405/05/26"})
		return
	}
	if req.Amount <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "amount must be > 0"})
		return
	}
	direction := strings.ToLower(strings.TrimSpace(req.Direction))
	if direction == "+" {
		direction = "in"
	} else if direction == "-" {
		direction = "out"
	}
	if direction != "in" && direction != "out" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "direction must be 'in' or 'out'"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	var id int
	if err := db.QueryRowContext(ctx, `
		INSERT INTO family.cash_flows (date_key, amount, direction, note)
		VALUES ($1, $2, $3, $4)
		RETURNING id`,
		dateKey, req.Amount, direction, strings.TrimSpace(normalizePersian(req.Note))).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "id": id})
}

func deleteFamilyCashFlowPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil || id <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	if _, err := db.ExecContext(ctx, `DELETE FROM family.cash_flows WHERE id = $1`, id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// ────────────────────────────── GET /family/history ──────────────────────────────

func getFamilyHistoryPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	assets, err := loadFamilyAssetsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load assets: " + err.Error()})
		return
	}
	holdings, err := loadFamilyHoldingsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load holdings: " + err.Error()})
		return
	}
	accounts, err := loadFamilyAccountsPG(ctx, db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load accounts: " + err.Error()})
		return
	}

	totalByDate := map[string]float64{}
	histRows, err := db.QueryContext(ctx, `SELECT date_key, total_value FROM family.history`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query history: " + err.Error()})
		return
	}
	for histRows.Next() {
		var dk string
		var v float64
		if err := histRows.Scan(&dk, &v); err != nil {
			histRows.Close()
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan history: " + err.Error()})
			return
		}
		totalByDate[dk] = v
	}
	histRows.Close()
	if err := histRows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	assetPrices := map[int][]familyPricePoint{}
	priceRows, err := db.QueryContext(ctx, `
		SELECT asset_id, date_key, price
		FROM family.prices
		WHERE price > 0
		ORDER BY date_key`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query prices: " + err.Error()})
		return
	}
	for priceRows.Next() {
		var id int
		var pt familyPricePoint
		if err := priceRows.Scan(&id, &pt.DateKey, &pt.Price); err != nil {
			priceRows.Close()
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan prices: " + err.Error()})
			return
		}
		assetPrices[id] = append(assetPrices[id], pt)
	}
	priceRows.Close()
	if err := priceRows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	dateSet := map[string]bool{}
	for dk := range totalByDate {
		dateSet[dk] = true
	}
	dates := make([]string, 0, len(dateSet))
	for dk := range dateSet {
		dates = append(dates, dk)
	}
	sort.Strings(dates)

	rateOf := map[int]float64{}
	for _, a := range assets {
		rateOf[a.ID] = a.CommissionRate
	}
	cashByPerson := map[string]float64{}
	for pid, bal := range accounts {
		cashByPerson[strconv.Itoa(pid)] = bal
	}

	out := make([]models.FamilyHistoryRow, 0, len(dates))
	for _, dk := range dates {
		people := map[string]float64{}
		for pid := range cashByPerson {
			people[pid] = 0
		}
		for _, h := range holdings {
			pts := assetPrices[h.AssetID]
			if len(pts) == 0 {
				continue
			}
			price, _ := priceAtOrEarliest(pts, dk)
			pid := strconv.Itoa(h.PersonID)
			people[pid] += h.Quantity * price * (1 - rateOf[h.AssetID])
		}
		for pid, cash := range cashByPerson {
			people[pid] += cash
		}

		total, hasTotal := totalByDate[dk]
		if !hasTotal {
			for _, v := range people {
				total += v
			}
		}

		out = append(out, models.FamilyHistoryRow{
			DateKey:  dk,
			Total:    total,
			HasTotal: hasTotal,
			People:   people,
		})
	}

	c.JSON(http.StatusOK, out)
}
