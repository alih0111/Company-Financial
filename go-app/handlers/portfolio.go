package handlers

import (
	"database/sql"
	"encoding/json"
	"go-app/config"
	"go-app/models"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

// ensurePortfolioColumn ستون [Portfolio] را روی جدول Users می‌سازد اگر وجود ندارد.
// الگوی مشابه ensure_table در اسکریپر پایتون. این متد idempotent است.
func ensurePortfolioColumn(db *sql.DB) {
	_, _ = db.Exec(`
		IF COL_LENGTH('dbo.Users','Portfolio') IS NULL
		ALTER TABLE [codal].[dbo].[Users] ADD [Portfolio] NVARCHAR(MAX) NULL
	`)
}

// loadPortfolio پورتفولیوی ذخیره‌شده‌ی کاربر را به‌صورت slice برمی‌گرداند.
// اگر ستون NULL یا خالی باشد، slice خالی برمی‌گردد.
func loadPortfolio(tx *sql.Tx, username string) ([]models.PortfolioHolding, error) {
	var raw sql.NullString

	err := tx.QueryRow(`
		SELECT [Portfolio]
		FROM [codal].[dbo].[Users] WITH (UPDLOCK, ROWLOCK)
		WHERE [UserName] = @p1
	`, username).Scan(&raw)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	holdings := []models.PortfolioHolding{}
	if raw.Valid && strings.TrimSpace(raw.String) != "" {
		if err := json.Unmarshal([]byte(raw.String), &holdings); err != nil {
			holdings = []models.PortfolioHolding{}
		}
	}
	return holdings, nil
}

// savePortfolio پورتفولیو را در ردیف کاربر ذخیره می‌کند.
func savePortfolio(tx *sql.Tx, username string, holdings []models.PortfolioHolding) error {
	b, err := json.Marshal(holdings)
	if err != nil {
		return err
	}

	_, err = tx.Exec(`
		UPDATE [codal].[dbo].[Users]
		SET [Portfolio] = @p1
		WHERE [UserName] = @p2
	`, string(b), username)
	return err
}

// fetchLivePrices 最新 قیمت/سیمبل/نام شرکت‌های داخل پوررفولیو را از vw_AIStockMetrics می‌گیرد.
type livePriceRow struct {
	CompanyID   string
	Symbol      sql.NullString
	CompanyName  sql.NullString
	LatestPrice  sql.NullFloat64
	QuantScore   sql.NullFloat64
}

func fetchLivePrices(db *sql.DB, companyIDs []string) (map[string]livePriceRow, error) {
	out := map[string]livePriceRow{}

	if len(companyIDs) == 0 {
		return out, nil
	}

	placeholders := make([]string, len(companyIDs))
	args := make([]interface{}, len(companyIDs))
	for i, id := range companyIDs {
		placeholders[i] = "@p" + strconv.Itoa(i+1)
		args[i] = id
	}

	query := `
		SELECT
			CompanyID,
			ISNULL(Symbol, '')      AS Symbol,
			CompanyName,
			LatestPrice,
			QuantScore
		FROM [codal].[dbo].[vw_AIStockMetrics]
		WHERE CompanyID IN (` + strings.Join(placeholders, ",") + `)`

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var r livePriceRow
		if err := rows.Scan(&r.CompanyID, &r.Symbol, &r.CompanyName, &r.LatestPrice, &r.QuantScore); err != nil {
			return nil, err
		}
		out[r.CompanyID] = r
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

// GetPortfolio لیست دارایی‌های کاربر را با قیمت زنده و محاسبات برمی‌گرداند.
func GetPortfolio(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	ensurePortfolioColumn(db)

	username := c.GetString("username")
	if username == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}

	tx, err := db.Begin()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}

	holdings, err := loadPortfolio(tx, username)
	if err != nil {
		tx.Rollback()
		c.JSON(http.StatusInternalServerError, gin.H{"error": "select error: " + err.Error()})
		return
	}
	if holdings == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}
	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	// استخراج company_idها برای گرفتن قیمت زنده.
	ids := make([]string, 0, len(holdings))
	for _, h := range holdings {
		if strings.TrimSpace(h.CompanyID) != "" {
			ids = append(ids, h.CompanyID)
		}
	}

	live, err := fetchLivePrices(db, ids)
	if err != nil {
		// اگه ویو در دسترس نبود، بدون قیمت زنده ادامه می‌دهیم.
		live = map[string]livePriceRow{}
	}

	// محاسبه‌ی مقدار بازار کل برای وزن‌دهی.
	var totalMarketValue float64
	enriched := make([]models.PortfolioHoldingEnriched, 0, len(holdings))

	for _, h := range holdings {
		e := models.PortfolioHoldingEnriched{PortfolioHolding: h}

		if lp, ok := live[h.CompanyID]; ok {
			if lp.Symbol.Valid && lp.Symbol.String != "" {
				e.Symbol = lp.Symbol.String
			}
			if lp.CompanyName.Valid && lp.CompanyName.String != "" {
				e.CompanyName = lp.CompanyName.String
			}
			if lp.LatestPrice.Valid && lp.LatestPrice.Float64 > 0 {
				e.LatestPrice = lp.LatestPrice.Float64
				e.HasLivePrice = true
			}
		}

		e.CostBasis = h.Quantity * h.BuyPrice
		if e.HasLivePrice {
			e.MarketValue = h.Quantity * e.LatestPrice
		}
		e.Gain = e.MarketValue - e.CostBasis
		if e.CostBasis != 0 {
			e.GainPct = (e.Gain / e.CostBasis) * 100.0
		}

		totalMarketValue += e.MarketValue
		enriched = append(enriched, e)
	}

	// محاسبه‌ی وزن و خلاصه.
	var totalCost float64
	for i := range enriched {
		var weight float64
		if totalMarketValue > 0 {
			weight = (enriched[i].MarketValue / totalMarketValue) * 100.0
		}
		enriched[i].Weight = round(weight, 2)
		totalCost += enriched[i].CostBasis
	}

	totalGain := totalMarketValue - totalCost
	var totalGainPct float64
	if totalCost != 0 {
		totalGainPct = (totalGain / totalCost) * 100.0
	}

	summary := models.PortfolioSummary{
		TotalCost:        round(totalCost, 2),
		TotalCostRaw:     totalCost,
		TotalMarketValue: round(totalMarketValue, 2),
		TotalGain:        round(totalGain, 2),
		TotalGainPct:     round(totalGainPct, 2),
		HoldingsCount:    len(enriched),
		Holdings:         enriched,
	}

	c.JSON(http.StatusOK, summary)
}

// UpsertHoldingRequest بدنه‌ی درخواست add/update.
type UpsertHoldingRequest struct {
	CompanyID   string  `json:"company_id"`
	Symbol      string  `json:"symbol"`
	CompanyName string  `json:"company_name"`
	Quantity    float64 `json:"quantity"`
	BuyPrice    float64 `json:"buy_price"`
	BuyDate     string  `json:"buy_date"`
	Note        string  `json:"note"`
}

// UpsertHolding یک دارایی را اضافه یا به‌روز می‌کند.
// اگر company_id موجود باشد، ردیف جایگزین می‌شود (upsert).
func UpsertHolding(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	ensurePortfolioColumn(db)

	username := c.GetString("username")
	if username == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}

	var req UpsertHoldingRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	companyID := strings.TrimSpace(req.CompanyID)
	if companyID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "company_id is required"})
		return
	}
	if req.Quantity <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "quantity must be greater than 0"})
		return
	}
	if req.BuyPrice <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "buy_price must be greater than 0"})
		return
	}

	holding := models.PortfolioHolding{
		CompanyID:   companyID,
		Symbol:      strings.TrimSpace(req.Symbol),
		CompanyName: strings.TrimSpace(normalizePersian(req.CompanyName)),
		Quantity:    req.Quantity,
		BuyPrice:    req.BuyPrice,
		BuyDate:     strings.TrimSpace(req.BuyDate),
		Note:        strings.TrimSpace(req.Note),
	}

	tx, err := db.Begin()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}
	defer tx.Rollback()

	holdings, err := loadPortfolio(tx, username)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "select error: " + err.Error()})
		return
	}
	if holdings == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}

	// upsert بر اساس company_id
	found := false
	for i, h := range holdings {
		if h.CompanyID == companyID {
			holdings[i] = holding
			found = true
			break
		}
	}
	if !found {
		holdings = append(holdings, holding)
	}

	if err := savePortfolio(tx, username, holdings); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save error: " + err.Error()})
		return
	}

	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "saved", "holding": holding})
}

// DeleteHolding یک دارایی را بر اساس company_id حذف می‌کند.
func DeleteHolding(c *gin.Context) {
	db := config.GetDB()
	defer db.Close()

	ensurePortfolioColumn(db)

	username := c.GetString("username")
	if username == "" {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
		return
	}

	companyID := strings.TrimSpace(c.Param("company_id"))
	if companyID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "company_id is required"})
		return
	}

	tx, err := db.Begin()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}
	defer tx.Rollback()

	holdings, err := loadPortfolio(tx, username)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "select error: " + err.Error()})
		return
	}
	if holdings == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "user not found"})
		return
	}

	filtered := holdings[:0]
	removed := false
	for _, h := range holdings {
		if h.CompanyID == companyID {
			removed = true
			continue
		}
		filtered = append(filtered, h)
	}
	if !removed {
		c.JSON(http.StatusNotFound, gin.H{"error": "holding not found"})
		return
	}

	if err := savePortfolio(tx, username, filtered); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save error: " + err.Error()})
		return
	}

	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}