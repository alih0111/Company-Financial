package handlers

import (
	"database/sql"
	"fmt"
	"go-app/config"
	"go-app/models"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// ─────────────────────────────────────────────────────────────────────
// دارایی خانواده — جایگزین اکسل «دارایی - 14050526.xlsx»
// همه endpointها فقط برای ادمین هستند.
// ─────────────────────────────────────────────────────────────────────

// نرخ کارمزد پیش‌فرض مطابق الگوی اکسل (اکثر سهام)؛ نرخ هر دارایی
// در ستون CommissionRate قابل تنظیم است (مثقال و یاقوت متفاوت‌اند).
const familyDefaultCommission = 0.0088

// نرخ کارمزد دارایی‌های خاص مطابق فرمول‌های اکسل
var familyAssetCommissions = map[string]float64{
	"مثقال": 0.001186,
	"یاقوت": 0.0001675,
}

// ضریب ۳٪ بهترین/بدترین حالت فردایی (ستون‌های BC18/BC19)
const familyTomorrowRange = 0.03

var familyDateKeyRe = regexp.MustCompile(`^\d{4}/\d{2}/\d{2}$`)

// ────────────────────────────── DDL ──────────────────────────────

// ensureFamilyTables جداول دارایی خانواده را در صورت نبود می‌سازد (idempotent).
func ensureFamilyTables(db *sql.DB) {
	statements := []string{
		`IF OBJECT_ID(N'dbo.FamilyPeople', N'U') IS NULL
		CREATE TABLE dbo.FamilyPeople (
			PersonID  INT IDENTITY(1,1) PRIMARY KEY,
			Name      NVARCHAR(100) NOT NULL,
			SortOrder INT NOT NULL DEFAULT 0,
			IsActive  BIT NOT NULL DEFAULT 1
		)`,
		`IF OBJECT_ID(N'dbo.FamilyAssets', N'U') IS NULL
		CREATE TABLE dbo.FamilyAssets (
			AssetID        INT IDENTITY(1,1) PRIMARY KEY,
			Name           NVARCHAR(100) NOT NULL,
			Category       NVARCHAR(20) NOT NULL DEFAULT N'stock',
			CommissionRate FLOAT NOT NULL DEFAULT 0.0088,
			SortOrder      INT NOT NULL DEFAULT 0,
			IsActive       BIT NOT NULL DEFAULT 1
		)`,
		// برای جدول‌های ساخته‌شده قبل از افزودن ستون نرخ کارمزد
		`IF COL_LENGTH('dbo.FamilyAssets', 'CommissionRate') IS NULL
		ALTER TABLE dbo.FamilyAssets ADD CommissionRate FLOAT NOT NULL DEFAULT 0.0088`,
		// نماد بازار برای سینک خودکار قیمت از MarketPriceHistory
		`IF COL_LENGTH('dbo.FamilyAssets', 'Symbol') IS NULL
		ALTER TABLE dbo.FamilyAssets ADD Symbol NVARCHAR(50) NULL`,
		`IF OBJECT_ID(N'dbo.FamilyHoldings', N'U') IS NULL
		CREATE TABLE dbo.FamilyHoldings (
			PersonID  INT NOT NULL,
			AssetID   INT NOT NULL,
			Quantity  FLOAT NOT NULL DEFAULT 0,
			CostBasis FLOAT NOT NULL DEFAULT 0,
			CONSTRAINT PK_FamilyHoldings PRIMARY KEY (PersonID, AssetID)
		)`,
		`IF OBJECT_ID(N'dbo.FamilyPrices', N'U') IS NULL
		CREATE TABLE dbo.FamilyPrices (
			DateKey NVARCHAR(10) NOT NULL,
			AssetID INT NOT NULL,
			Price   FLOAT NOT NULL,
			CONSTRAINT PK_FamilyPrices PRIMARY KEY (DateKey, AssetID)
		)`,
		`IF OBJECT_ID(N'dbo.FamilyAccounts', N'U') IS NULL
		CREATE TABLE dbo.FamilyAccounts (
			PersonID    INT PRIMARY KEY,
			CashBalance FLOAT NOT NULL DEFAULT 0
		)`,
		`IF OBJECT_ID(N'dbo.FamilyCashFlows', N'U') IS NULL
		CREATE TABLE dbo.FamilyCashFlows (
			ID        INT IDENTITY(1,1) PRIMARY KEY,
			DateKey   NVARCHAR(10) NOT NULL,
			Amount    FLOAT NOT NULL,
			Direction NVARCHAR(3) NOT NULL, -- in | out
			Note      NVARCHAR(300) NULL
		)`,
		`IF OBJECT_ID(N'dbo.FamilyHistory', N'U') IS NULL
		CREATE TABLE dbo.FamilyHistory (
			DateKey     NVARCHAR(10) PRIMARY KEY,
			TotalValue  FLOAT NOT NULL,
			ChangeValue FLOAT NOT NULL DEFAULT 0,
			ChangePct   FLOAT NOT NULL DEFAULT 0,
			RecordedAt  DATETIME NOT NULL DEFAULT GETDATE()
		)`,
	}
	for _, s := range statements {
		_, _ = db.Exec(s)
	}
}

// ────────────────────────────── ابزارها ──────────────────────────────

// requireFamilyAdmin اگر کاربر ادمین نباشد 403 برمی‌گرداند.
func requireFamilyAdmin(c *gin.Context) bool {
	isAdmin, _ := c.Get("isAdmin")
	if ok, _ := isAdmin.(bool); !ok {
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "admin access required"})
		return false
	}
	return true
}

// gregorianToJalali تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد jalaali).
func gregorianToJalali(gy, gm, gd int) (jy, jm, jd int) {
	gdm := [...]int{0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334}
	if gy > 1600 {
		jy = 979
		gy -= 1600
	} else {
		jy = 0
		gy -= 621
	}
	gy2 := gy
	if gm > 2 {
		gy2 = gy + 1
	}
	days := 365*gy + (gy2+3)/4 - (gy2+99)/100 + (gy2+399)/400 - 80 + gd + gdm[gm-1]
	jy += 33 * (days / 12053)
	days %= 12053
	jy += 4 * (days / 1461)
	days %= 1461
	if days > 365 {
		jy += (days - 1) / 365
		days = (days - 1) % 365
	}
	if days < 186 {
		jm = 1 + days/31
		jd = 1 + days%31
	} else {
		jm = 7 + (days-186)/30
		jd = 1 + (days-186)%30
	}
	return
}

func formatFamilyDateKey(jy, jm, jd int) string {
	return fmt.Sprintf("%04d/%02d/%02d", jy, jm, jd)
}

// todayFamilyDateKey تاریخ امروز را به شکل '1405/05/26' برمی‌گرداند.
func todayFamilyDateKey() string {
	now := time.Now()
	jy, jm, jd := gregorianToJalali(now.Year(), int(now.Month()), now.Day())
	return formatFamilyDateKey(jy, jm, jd)
}

// ────────────────────────────── بارگذاری داده ──────────────────────────────

type familyAssetDef struct {
	ID             int
	Name           string
	Symbol         string
	Category       string
	CommissionRate float64
	SortOrder      int
}

type familyPersonDef struct {
	ID        int
	Name      string
	SortOrder int
}

type familyHoldingRow struct {
	PersonID  int
	AssetID   int
	Quantity  float64
	CostBasis float64
}

type familyPriceRow struct {
	AssetID int
	Price   float64
	DateKey string
}

func loadFamilyAssets(db *sql.DB) ([]familyAssetDef, error) {
	rows, err := db.Query(`
		SELECT AssetID, Name, ISNULL(Symbol, N''), Category, CommissionRate, SortOrder
		FROM dbo.FamilyAssets
		WHERE IsActive = 1
		ORDER BY SortOrder, AssetID`)
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

func loadFamilyPeople(db *sql.DB) ([]familyPersonDef, error) {
	rows, err := db.Query(`
		SELECT PersonID, Name, SortOrder
		FROM dbo.FamilyPeople
		WHERE IsActive = 1
		ORDER BY SortOrder, PersonID`)
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

func loadFamilyHoldings(db *sql.DB) ([]familyHoldingRow, error) {
	rows, err := db.Query(`
		SELECT PersonID, AssetID, Quantity, CostBasis
		FROM dbo.FamilyHoldings`)
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

func loadFamilyPrices(db *sql.DB) (map[int]familyPriceRow, error) {
	rows, err := db.Query(`
		SELECT p.AssetID, p.Price, p.DateKey
		FROM dbo.FamilyPrices p
		WHERE p.Price > 0
		  AND p.DateKey = (
		      SELECT MAX(p2.DateKey)
		      FROM dbo.FamilyPrices p2
		      WHERE p2.AssetID = p.AssetID AND p2.Price > 0
		  )`)
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

func loadFamilyAccounts(db *sql.DB) (map[int]float64, error) {
	rows, err := db.Query(`SELECT PersonID, CashBalance FROM dbo.FamilyAccounts`)
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

// GetFamilyAssets کل وضعیت دارایی‌ها را با محاسبات برمی‌گرداند (مثل Sheet1).
func GetFamilyAssets(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	people, err := loadFamilyPeople(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load people: " + err.Error()})
		return
	}
	assets, err := loadFamilyAssets(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load assets: " + err.Error()})
		return
	}
	holdings, err := loadFamilyHoldings(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load holdings: " + err.Error()})
		return
	}
	prices, err := loadFamilyPrices(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load prices: " + err.Error()})
		return
	}
	accounts, err := loadFamilyAccounts(db)
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

	// دارایی‌های هر شخص + جمع‌های هر دارایی بین همه اشخاص
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

	// وزن هر دارایی و خلاصه اشخاص
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

// ────────────────────────────── سینک خودکار قیمت از بازار ──────────────────────────────

// familySyncedPrice یک دارایی که قیمتش از MarketPriceHistory خوانده شد.
type familySyncedPrice struct {
	AssetID int     `json:"asset_id"`
	Name    string  `json:"name"`
	Symbol  string  `json:"symbol"`
	DateKey string  `json:"date_key"`
	Price   float64 `json:"price"`
}

// syncFamilyPricesFromMarket قیمت هر دارایی خانواده را از MarketPriceHistory
// (خروجی کالکتور BRS) در FamilyPrices ثبت می‌کند.
//   fullBackfill=false → فقط آخرین قیمت هر نماد (حالت روزانه)
//   fullBackfill=true  → کل تاریخچه نماد (برای بازسازی چارت سبد اشخاص)
//
// مثل اکسل «آخرین قیمت» ملاک است (fallback: قیمت پایانی).
// دارایی بدون نماد بازار گزارش می‌شود تا دستی وارد شود.
func syncFamilyPricesFromMarket(db *sql.DB, fullBackfill bool) (updated []familySyncedPrice, missing []string, err error) {
	assets, err := loadFamilyAssets(db)
	if err != nil {
		return nil, nil, err
	}

	updated = []familySyncedPrice{}
	missing = []string{}
	maxDate := ""

	// در backfill کامل، فقط تاریخ‌های داخل بازه‌ی تاریخچه واقعی (اکسل)
	// منتقل می‌شود؛ بازسازی قدیمی‌تر از آن با دارایی‌های امروز بی‌معنی است.
	var floorDate string
	if fullBackfill {
		if err := db.QueryRow(`
			SELECT MIN(DateKey) FROM dbo.FamilyHistory`).Scan(&floorDate); err != nil {
			return nil, nil, err
		}
		if floorDate != "" {
			if _, err := db.Exec(`
				DELETE FROM dbo.FamilyPrices WHERE DateKey < @p1`, floorDate); err != nil {
				return nil, nil, err
			}
		}
	}

	for _, a := range assets {
		symbol := a.Symbol
		if symbol == "" {
			symbol = a.Name // دارایی‌هایی که نامشان همان نماد بازار است
		}

		type priceRow struct {
			DateKey string
			Last    sql.NullFloat64
			Close   sql.NullFloat64
		}
		var rows []priceRow

		if fullBackfill {
			rs, err := db.Query(`
				SELECT m.JalaliDate, m.LastPrice, m.ClosingPrice
				FROM dbo.MarketPriceHistory m
				WHERE m.Symbol = @p1
				ORDER BY m.GregorianDate`, symbol)
			if err != nil {
				return nil, nil, err
			}
			for rs.Next() {
				var r priceRow
				var last, close sql.NullFloat64
				if err := rs.Scan(&r.DateKey, &last, &close); err != nil {
					rs.Close()
					return nil, nil, err
				}
				r.Last, r.Close = last, close
				if familyDateKeyRe.MatchString(r.DateKey) && (floorDate == "" || r.DateKey >= floorDate) {
					rows = append(rows, r)
				}
			}
			rs.Close()
			if err := rs.Err(); err != nil {
				return nil, nil, err
			}
		} else {
			var last, close sql.NullFloat64
			var dateKey sql.NullString
			if err := db.QueryRow(`
				SELECT TOP 1 m.LastPrice, m.ClosingPrice, m.JalaliDate
				FROM dbo.MarketPriceHistory m
				WHERE m.Symbol = @p1
				ORDER BY m.GregorianDate DESC`, symbol).Scan(&last, &close, &dateKey); err != nil {
				if err == sql.ErrNoRows {
					missing = append(missing, a.Name)
					continue
				}
				return nil, nil, err
			}
			if dateKey.Valid && familyDateKeyRe.MatchString(dateKey.String) {
				rows = append(rows, priceRow{DateKey: dateKey.String, Last: last, Close: close})
			}
		}

		if len(rows) == 0 {
			missing = append(missing, a.Name)
			continue
		}

		syncedAny := false
		for _, r := range rows {
			price := 0.0
			if r.Last.Valid && r.Last.Float64 > 0 {
				price = r.Last.Float64
			} else if r.Close.Valid && r.Close.Float64 > 0 {
				price = r.Close.Float64
			} else {
				continue
			}

			if _, err := db.Exec(`
				MERGE dbo.FamilyPrices AS t
				USING (SELECT @p1 AS DateKey, @p2 AS AssetID) AS s
				ON t.DateKey = s.DateKey AND t.AssetID = s.AssetID
				WHEN MATCHED THEN UPDATE SET Price = @p3
				WHEN NOT MATCHED THEN INSERT (DateKey, AssetID, Price) VALUES (@p1, @p2, @p3);`,
				r.DateKey, a.ID, price); err != nil {
				return nil, nil, err
			}
			syncedAny = true
			if r.DateKey > maxDate {
				maxDate = r.DateKey
			}
		}

		if syncedAny {
			last := rows[len(rows)-1]
			price := 0.0
			if last.Last.Valid && last.Last.Float64 > 0 {
				price = last.Last.Float64
			} else if last.Close.Valid && last.Close.Float64 > 0 {
				price = last.Close.Float64
			}
			updated = append(updated, familySyncedPrice{
				AssetID: a.ID,
				Name:    a.Name,
				Symbol:  symbol,
				DateKey: last.DateKey,
				Price:   price,
			})
		} else {
			missing = append(missing, a.Name)
		}
	}

	// ثبت جمع کل در تاریخچه فقط برای جدیدترین تاریخ سینک‌شده؛
	// تاریخچه واقعی روزهای گذشته (اکسل) دست‌نخورده می‌ماند.
	if maxDate != "" {
		if total, err := computeFamilyTotal(db, maxDate); err == nil {
			_ = upsertFamilyHistory(db, maxDate, total)
		}
	}

	return updated, missing, nil
}

// SyncFamilyPrices قیمت‌های دارایی خانواده را از بازار (MarketPriceHistory)
// به‌روز می‌کند — همان کاری که Daily Prices بعداً خودکار انجام می‌دهد.
// با {"backfill": true} کل تاریخچه هر نماد منتقل می‌شود (یک‌باره، برای چارت اشخاص).
func SyncFamilyPrices(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	var req struct {
		Backfill bool `json:"backfill"`
	}
	_ = c.ShouldBindJSON(&req)

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	updated, missing, err := syncFamilyPricesFromMarket(db, req.Backfill)
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

type familyPriceInput struct {
	AssetID int     `json:"asset_id"`
	Price   float64 `json:"price"`
}

type saveFamilyPricesRequest struct {
	DateKey string              `json:"date_key"`
	Prices  []familyPriceInput `json:"prices"`
}

// SaveFamilyPrices قیمت‌های یک تاریخ را ذخیره می‌کند و جمع کل را در
// تاریخچه (FamilyHistory) ثبت می‌کند — مثل زدن قیمت در ستون C اکسل.
func SaveFamilyPrices(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

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

	tx, err := db.Begin()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "transaction error"})
		return
	}
	defer tx.Rollback()

	for _, p := range req.Prices {
		if p.Price <= 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("price must be > 0 for asset %d", p.AssetID)})
			return
		}
		if _, err := tx.Exec(`
			MERGE dbo.FamilyPrices AS t
			USING (SELECT @p1 AS DateKey, @p2 AS AssetID) AS s
			ON t.DateKey = s.DateKey AND t.AssetID = s.AssetID
			WHEN MATCHED THEN UPDATE SET Price = @p3
			WHEN NOT MATCHED THEN INSERT (DateKey, AssetID, Price) VALUES (@p1, @p2, @p3);`,
			dateKey, p.AssetID, p.Price); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "save price: " + err.Error()})
			return
		}
	}

	if err := tx.Commit(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "commit error"})
		return
	}

	total, err := computeFamilyTotal(db, dateKey)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "compute total: " + err.Error()})
		return
	}

	if err := upsertFamilyHistory(db, dateKey, total); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save history: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "saved", "date_key": dateKey, "total_value": total})
}

// computeFamilyTotal جمع کل (دارایی‌ها با قیمت‌های <= تاریخ + مانده حساب‌ها) را
// برای یک تاریخ محاسبه می‌کند.
func computeFamilyTotal(db *sql.DB, dateKey string) (float64, error) {
	// آخرین تاریخ تاریخچه قبل از این تاریخ، برای محاسبه تغییر
	var holdingsValue, totalCash float64
	err := db.QueryRow(`
		SELECT
			ISNULL(SUM(h.Quantity * pr.Price * (1 - a.CommissionRate)), 0),
			(SELECT ISNULL(SUM(CashBalance), 0) FROM dbo.FamilyAccounts)
		FROM dbo.FamilyHoldings h
		JOIN dbo.FamilyAssets a ON a.AssetID = h.AssetID
		OUTER APPLY (
			SELECT TOP 1 p.Price
			FROM dbo.FamilyPrices p
			WHERE p.AssetID = h.AssetID AND p.DateKey <= @p1 AND p.Price > 0
			ORDER BY p.DateKey DESC
		) pr`,
		dateKey).Scan(&holdingsValue, &totalCash)
	if err != nil {
		return 0, err
	}
	return holdingsValue + totalCash, nil
}

// upsertFamilyHistory ردیف تاریخچه یک تاریخ را می‌سازد/به‌روز می‌کند.
// تغییر نسبت به آخرین تاریخ قبل از آن محاسبه می‌شود.
func upsertFamilyHistory(db *sql.DB, dateKey string, total float64) error {
	var prev sql.NullFloat64
	if err := db.QueryRow(`
		SELECT TOP 1 TotalValue
		FROM dbo.FamilyHistory
		WHERE DateKey < @p1
		ORDER BY DateKey DESC`, dateKey).Scan(&prev); err != nil && err != sql.ErrNoRows {
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

	_, err := db.Exec(`
		MERGE dbo.FamilyHistory AS t
		USING (SELECT @p1 AS DateKey) AS s
		ON t.DateKey = s.DateKey
		WHEN MATCHED THEN UPDATE SET
			TotalValue = @p2, ChangeValue = @p3, ChangePct = @p4, RecordedAt = GETDATE()
		WHEN NOT MATCHED THEN INSERT (DateKey, TotalValue, ChangeValue, ChangePct)
			VALUES (@p1, @p2, @p3, @p4);`,
		dateKey, total, change, changePct)
	return err
}

// refreshLatestFamilyHistory اگر برای آخرین تاریخ قیمت‌دار ردیف تاریخچه وجود دارد،
// آن را با محاسبه مجدد به‌روز می‌کند (بعد از تغییر تعداد/بهای/مانده).
func refreshLatestFamilyHistory(db *sql.DB) {
	var latest string
	err := db.QueryRow(`
		SELECT MAX(DateKey) FROM dbo.FamilyPrices`).Scan(&latest)
	if err != nil || latest == "" {
		return
	}

	var exists int
	if err := db.QueryRow(`
		SELECT COUNT(1) FROM dbo.FamilyHistory WHERE DateKey = @p1`, latest).Scan(&exists); err != nil || exists == 0 {
		return
	}

	if total, err := computeFamilyTotal(db, latest); err == nil {
		_ = upsertFamilyHistory(db, latest, total)
	}
}

// ────────────────────────────── PUT /family/holdings ──────────────────────────────

type upsertFamilyHoldingRequest struct {
	PersonID  int     `json:"person_id"`
	AssetID   int     `json:"asset_id"`
	Quantity  float64 `json:"quantity"`
	CostBasis float64 `json:"cost_basis"`
}

// UpsertFamilyHolding تعداد و بهای تمام شده یک دارایی در سبد یک شخص را
// ذخیره می‌کند (تعداد صفر = حذف).
func UpsertFamilyHolding(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	var req upsertFamilyHoldingRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.Quantity < 0 || req.CostBasis < 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "quantity and cost_basis must be >= 0"})
		return
	}

	if req.Quantity == 0 {
		if _, err := db.Exec(`
			DELETE FROM dbo.FamilyHoldings
			WHERE PersonID = @p1 AND AssetID = @p2`, req.PersonID, req.AssetID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
			return
		}
	} else {
		if _, err := db.Exec(`
			MERGE dbo.FamilyHoldings AS t
			USING (SELECT @p1 AS PersonID, @p2 AS AssetID) AS s
			ON t.PersonID = s.PersonID AND t.AssetID = s.AssetID
			WHEN MATCHED THEN UPDATE SET Quantity = @p3, CostBasis = @p4
			WHEN NOT MATCHED THEN INSERT (PersonID, AssetID, Quantity, CostBasis)
				VALUES (@p1, @p2, @p3, @p4);`,
			req.PersonID, req.AssetID, req.Quantity, req.CostBasis); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "save: " + err.Error()})
			return
		}
	}

	refreshLatestFamilyHistory(db)
	c.JSON(http.StatusOK, gin.H{"message": "saved"})
}

// DeleteFamilyHolding یک دارایی را از سبد یک شخص حذف می‌کند.
func DeleteFamilyHolding(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	personID, _ := strconv.Atoi(c.Query("person_id"))
	assetID, _ := strconv.Atoi(c.Query("asset_id"))
	if personID <= 0 || assetID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id and asset_id are required"})
		return
	}

	if _, err := db.Exec(`
		DELETE FROM dbo.FamilyHoldings
		WHERE PersonID = @p1 AND AssetID = @p2`, personID, assetID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
		return
	}

	refreshLatestFamilyHistory(db)
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// ────────────────────────────── POST /family/people و /family/assets ──────────────────────────────

type createFamilyPersonRequest struct {
	Name      string `json:"name"`
	SortOrder int    `json:"sort_order"`
}

// CreateFamilyPerson شخص جدید اضافه می‌کند.
func CreateFamilyPerson(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

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

	var id int
	if err := db.QueryRow(`
		INSERT INTO dbo.FamilyPeople (Name, SortOrder)
		OUTPUT INSERTED.PersonID
		VALUES (@p1, @p2)`, name, req.SortOrder).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "person_id": id})
}

type createFamilyAssetRequest struct {
	Name      string `json:"name"`
	Category  string `json:"category"`
	SortOrder int    `json:"sort_order"`
}

// CreateFamilyAsset دارایی جدید (سهام/طلا/دلار) اضافه می‌کند.
func CreateFamilyAsset(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

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

	rate, ok := familyAssetCommissions[name]
	if !ok {
		rate = familyDefaultCommission
	}

	var id int
	if err := db.QueryRow(`
		INSERT INTO dbo.FamilyAssets (Name, Category, CommissionRate, SortOrder)
		OUTPUT INSERTED.AssetID
		VALUES (@p1, @p2, @p3, @p4)`, name, req.Category, rate, req.SortOrder).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "asset_id": id})
}

// ────────────────────────────── PUT /family/account ──────────────────────────────

type updateFamilyAccountRequest struct {
	PersonID    int     `json:"person_id"`
	CashBalance float64 `json:"cash_balance"`
}

// UpdateFamilyAccount مانده حساب یک شخص را ثبت می‌کند.
func UpdateFamilyAccount(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	var req updateFamilyAccountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.PersonID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id is required"})
		return
	}

	if _, err := db.Exec(`
		MERGE dbo.FamilyAccounts AS t
		USING (SELECT @p1 AS PersonID) AS s
		ON t.PersonID = s.PersonID
		WHEN MATCHED THEN UPDATE SET CashBalance = @p2
		WHEN NOT MATCHED THEN INSERT (PersonID, CashBalance) VALUES (@p1, @p2);`,
		req.PersonID, req.CashBalance); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save: " + err.Error()})
		return
	}

	refreshLatestFamilyHistory(db)
	c.JSON(http.StatusOK, gin.H{"message": "saved"})
}

// ────────────────────────────── جریان‌های نقدی ──────────────────────────────

type addFamilyCashFlowRequest struct {
	DateKey   string  `json:"date_key"`
	Amount    float64 `json:"amount"`
	Direction string  `json:"direction"` // in | out
	Note      string  `json:"note"`
}

// GetFamilyCashFlows لیست آورده/برداشت‌ها را برمی‌گرداند (جدیدترین اول).
func GetFamilyCashFlows(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	limit := 200
	if v, err := strconv.Atoi(c.DefaultQuery("limit", "200")); err == nil && v > 0 && v <= 2000 {
		limit = v
	}

	rows, err := db.Query(`
		SELECT TOP (@p1) ID, DateKey, Amount, Direction, ISNULL(Note, N'')
		FROM dbo.FamilyCashFlows
		ORDER BY DateKey DESC, ID DESC`, limit)
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

// AddFamilyCashFlow یک آورده (+) یا برداشت (−) ثبت می‌کند.
func AddFamilyCashFlow(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

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

	var id int
	if err := db.QueryRow(`
		INSERT INTO dbo.FamilyCashFlows (DateKey, Amount, Direction, Note)
		OUTPUT INSERTED.ID
		VALUES (@p1, @p2, @p3, @p4)`,
		dateKey, req.Amount, direction, strings.TrimSpace(normalizePersian(req.Note))).Scan(&id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "created", "id": id})
}

// DeleteFamilyCashFlow یک جریان نقدی را حذف می‌کند.
func DeleteFamilyCashFlow(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	id, err := strconv.Atoi(c.Param("id"))
	if err != nil || id <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}

	if _, err := db.Exec(`DELETE FROM dbo.FamilyCashFlows WHERE ID = @p1`, id); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// ────────────────────────────── GET /family/history ──────────────────────────────

// familyPricePoint یک قیمت تاریخی یک دارایی.
type familyPricePoint struct {
	DateKey string
	Price   float64
}

// priceAtOrEarliest آخرین قیمت <= تاریخ را برمی‌گرداند؛ اگر تاریخ قبل از
// اولین قیمت موجود باشد، اولین قیمت (تقریب) استفاده می‌شود تا سهم‌هایی که
// تاریخچه‌شان دیرتر شروع شده به صفر جمع نشوند.
func priceAtOrEarliest(pts []familyPricePoint, dateKey string) (float64, bool) {
	i := sort.Search(len(pts), func(i int) bool { return pts[i].DateKey > dateKey })
	if i == 0 {
		return pts[0].Price, true // تاریخ قبل از اولین قیمت → اولین قیمت
	}
	return pts[i-1].Price, true
}

// GetFamilyHistory تاریخچه جمع کل (واقعی) + ارزش بازسازی‌شده هر شخص را
// برای چارت برمی‌گرداند. سری هر شخص = دارایی‌های امروز × قیمت تاریخی +
// مانده فعلی حساب؛ به همین دلیل جمع اشخاص در گذشته ممکن است با جمع کل
// واقعی (ترکیب سبد آن زمان) تفاوت داشته باشد — has_total این را تفکیک می‌کند.
func GetFamilyHistory(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}

	db := config.GetDB()
	defer db.Close()
	ensureFamilyTables(db)

	assets, err := loadFamilyAssets(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load assets: " + err.Error()})
		return
	}
	holdings, err := loadFamilyHoldings(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load holdings: " + err.Error()})
		return
	}
	accounts, err := loadFamilyAccounts(db)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "load accounts: " + err.Error()})
		return
	}

	// تاریخچه واقعی جمع کل
	totalByDate := map[string]float64{}
	histRows, err := db.Query(`SELECT DateKey, TotalValue FROM dbo.FamilyHistory`)
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

	// همه قیمت‌های تاریخی هر دارایی (مرتب بر اساس تاریخ)
	assetPrices := map[int][]familyPricePoint{}
	dateSet := map[string]bool{}
	priceRows, err := db.Query(`
		SELECT AssetID, DateKey, Price
		FROM dbo.FamilyPrices
		WHERE Price > 0
		ORDER BY DateKey`)
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
		dateSet[pt.DateKey] = true
	}
	priceRows.Close()
	if err := priceRows.Err(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

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
