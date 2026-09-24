# 14 — Source Usage Map

Search scope: `go-app/`, `go-app/py/`, `go-app/py2/` (`.go`, `.py`, `.sql`, `.json`).
Operation keywords are heuristics derived from the same line (SELECT/INSERT/UPDATE/DELETE/FROM/INTO/JOIN/MERGE/EXEC).

> Caveat: common English words (e.g. `statements`, `Users`, `TrackedTickers`) may produce
> false positives. Review each hit in context.


## CodalReports

References: **4** across **2** files. Op keywords: (none)

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/py/codal_registry.py | 3 | - | جدول ``dbo.CodalReports`` به‌عنوان منبع حقیقت برای «کدام گزارش قبلاً دیده/پردازش |
| go-app/py/codal_registry.py | 26 | - | TABLE = "CodalReports" |
| go-app/py/codal_registry.py | 144 | - | logger.warning("⚠️ Could not read CodalReports (assuming empty): %s", exc) |
| go-app/py/sync_codal.py | 12 | - | dedup با SQL Server (CodalReports) |

## CodalSyncState

References: **2** across **1** files. Op keywords: (none)

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/py/codal_sync_state.py | 12 | - | TABLE = "CodalSyncState" |
| go-app/py/codal_sync_state.py | 16 | - | """جدول CodalSyncState را در صورت نبود می‌سازد (idempotent).""" |

## FamilyAccounts

References: **10** across **2** files. Op keywords: DELETE=1, FROM=4, INSERT=1, INTO=1, MERGE=1, SELECT=3

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 80 | - | `IF OBJECT_ID(N'dbo.FamilyAccounts', N'U') IS NULL |
| go-app/handlers/family_assets.go | 81 | - | CREATE TABLE dbo.FamilyAccounts ( |
| go-app/handlers/family_assets.go | 284 | SELECT/FROM | rows, err := db.Query(`SELECT PersonID, CashBalance FROM dbo.FamilyAccounts`) |
| go-app/handlers/family_assets.go | 780 | SELECT/FROM | (SELECT ISNULL(SUM(CashBalance), 0) FROM dbo.FamilyAccounts) |
| go-app/handlers/family_assets.go | 1051 | MERGE | MERGE dbo.FamilyAccounts AS t |
| go-app/py/family_import.py | 104 | - | IF OBJECT_ID(N'dbo.FamilyAccounts', N'U') IS NULL |
| go-app/py/family_import.py | 105 | - | CREATE TABLE dbo.FamilyAccounts ( |
| go-app/py/family_import.py | 278 | SELECT/FROM | (SELECT ISNULL(SUM(CashBalance), 0) FROM dbo.FamilyAccounts) |
| go-app/py/family_import.py | 333 | DELETE/FROM | cur.execute("DELETE FROM dbo.FamilyAccounts") |
| go-app/py/family_import.py | 336 | INSERT/INTO | "INSERT INTO dbo.FamilyAccounts (PersonID, CashBalance) VALUES (?, ?)", |

## FamilyAssets

References: **20** across **2** files. Op keywords: FROM=2, INSERT=1, INTO=1, JOIN=2, MERGE=1, SELECT=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 50 | - | `IF OBJECT_ID(N'dbo.FamilyAssets', N'U') IS NULL |
| go-app/handlers/family_assets.go | 51 | - | CREATE TABLE dbo.FamilyAssets ( |
| go-app/handlers/family_assets.go | 60 | - | `IF COL_LENGTH('dbo.FamilyAssets', 'CommissionRate') IS NULL |
| go-app/handlers/family_assets.go | 61 | - | ALTER TABLE dbo.FamilyAssets ADD CommissionRate FLOAT NOT NULL DEFAULT 0.0088`, |
| go-app/handlers/family_assets.go | 63 | - | `IF COL_LENGTH('dbo.FamilyAssets', 'Symbol') IS NULL |
| go-app/handlers/family_assets.go | 64 | - | ALTER TABLE dbo.FamilyAssets ADD Symbol NVARCHAR(50) NULL`, |
| go-app/handlers/family_assets.go | 196 | FROM | FROM dbo.FamilyAssets |
| go-app/handlers/family_assets.go | 782 | JOIN | JOIN dbo.FamilyAssets a ON a.AssetID = h.AssetID |
| go-app/handlers/family_assets.go | 1013 | INSERT/INTO | INSERT INTO dbo.FamilyAssets (Name, Category, CommissionRate, SortOrder) |
| go-app/py/family_import.py | 68 | - | IF OBJECT_ID(N'dbo.FamilyAssets', N'U') IS NULL |
| go-app/py/family_import.py | 69 | - | CREATE TABLE dbo.FamilyAssets ( |
| go-app/py/family_import.py | 79 | - | IF OBJECT_ID(N'dbo.FamilyAssets', N'U') IS NOT NULL |
| go-app/py/family_import.py | 80 | - | AND COL_LENGTH('dbo.FamilyAssets', 'CommissionRate') IS NULL |
| go-app/py/family_import.py | 81 | - | ALTER TABLE dbo.FamilyAssets ADD CommissionRate FLOAT NOT NULL DEFAULT 0.0088""", |
| go-app/py/family_import.py | 83 | - | IF OBJECT_ID(N'dbo.FamilyAssets', N'U') IS NOT NULL |
| go-app/py/family_import.py | 84 | - | AND COL_LENGTH('dbo.FamilyAssets', 'Symbol') IS NULL |
| go-app/py/family_import.py | 85 | - | ALTER TABLE dbo.FamilyAssets ADD Symbol NVARCHAR(50) NULL""", |
| go-app/py/family_import.py | 257 | MERGE | MERGE dbo.FamilyAssets AS t |
| go-app/py/family_import.py | 268 | SELECT/FROM | cur.execute("SELECT AssetID FROM dbo.FamilyAssets WHERE Name = ?", name) |
| go-app/py/family_import.py | 280 | JOIN | JOIN dbo.FamilyAssets a ON a.AssetID = h.AssetID |

## FamilyCashFlows

References: **9** across **2** files. Op keywords: DELETE=2, EXEC=1, FROM=3, INSERT=2, INTO=2

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 85 | - | `IF OBJECT_ID(N'dbo.FamilyCashFlows', N'U') IS NULL |
| go-app/handlers/family_assets.go | 86 | - | CREATE TABLE dbo.FamilyCashFlows ( |
| go-app/handlers/family_assets.go | 1091 | FROM | FROM dbo.FamilyCashFlows |
| go-app/handlers/family_assets.go | 1153 | INSERT/INTO | INSERT INTO dbo.FamilyCashFlows (DateKey, Amount, Direction, Note) |
| go-app/handlers/family_assets.go | 1180 | DELETE/FROM/EXEC | if _, err := db.Exec(`DELETE FROM dbo.FamilyCashFlows WHERE ID = @p1`, id); err != nil { |
| go-app/py/family_import.py | 110 | - | IF OBJECT_ID(N'dbo.FamilyCashFlows', N'U') IS NULL |
| go-app/py/family_import.py | 111 | - | CREATE TABLE dbo.FamilyCashFlows ( |
| go-app/py/family_import.py | 372 | DELETE/FROM | cur.execute("DELETE FROM dbo.FamilyCashFlows") |
| go-app/py/family_import.py | 375 | INSERT/INTO | "INSERT INTO dbo.FamilyCashFlows (DateKey, Amount, Direction, Note) VALUES (?, ?, ?, ?)", |

## FamilyHistory

References: **12** across **2** files. Op keywords: FROM=4, MERGE=2, SELECT=3, UPDATE=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 93 | - | `IF OBJECT_ID(N'dbo.FamilyHistory', N'U') IS NULL |
| go-app/handlers/family_assets.go | 94 | - | CREATE TABLE dbo.FamilyHistory ( |
| go-app/handlers/family_assets.go | 530 | SELECT/FROM | SELECT MIN(DateKey) FROM dbo.FamilyHistory`).Scan(&floorDate); err != nil { |
| go-app/handlers/family_assets.go | 703 | - | // تاریخچه (FamilyHistory) ثبت می‌کند — مثل زدن قیمت در ستون C اکسل. |
| go-app/handlers/family_assets.go | 802 | FROM | FROM dbo.FamilyHistory |
| go-app/handlers/family_assets.go | 818 | MERGE | MERGE dbo.FamilyHistory AS t |
| go-app/handlers/family_assets.go | 841 | SELECT/FROM | SELECT COUNT(1) FROM dbo.FamilyHistory WHERE DateKey = @p1`, latest).Scan(&exists); err != nil \|\| exists == 0 { |
| go-app/handlers/family_assets.go | 1238 | SELECT/FROM | histRows, err := db.Query(`SELECT DateKey, TotalValue FROM dbo.FamilyHistory`) |
| go-app/py/family_import.py | 119 | - | IF OBJECT_ID(N'dbo.FamilyHistory', N'U') IS NULL |
| go-app/py/family_import.py | 120 | - | CREATE TABLE dbo.FamilyHistory ( |
| go-app/py/family_import.py | 361 | MERGE | MERGE dbo.FamilyHistory AS t |
| go-app/py/family_import.py | 385 | UPDATE | "UPDATE dbo.FamilyHistory SET TotalValue = ? WHERE DateKey = ?", |

## FamilyHoldings

References: **12** across **2** files. Op keywords: DELETE=3, FROM=6, INSERT=1, INTO=1, MERGE=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 65 | - | `IF OBJECT_ID(N'dbo.FamilyHoldings', N'U') IS NULL |
| go-app/handlers/family_assets.go | 66 | - | CREATE TABLE dbo.FamilyHoldings ( |
| go-app/handlers/family_assets.go | 240 | FROM | FROM dbo.FamilyHoldings`) |
| go-app/handlers/family_assets.go | 781 | FROM | FROM dbo.FamilyHoldings h |
| go-app/handlers/family_assets.go | 882 | DELETE/FROM | DELETE FROM dbo.FamilyHoldings |
| go-app/handlers/family_assets.go | 889 | MERGE | MERGE dbo.FamilyHoldings AS t |
| go-app/handlers/family_assets.go | 923 | DELETE/FROM | DELETE FROM dbo.FamilyHoldings |
| go-app/py/family_import.py | 87 | - | IF OBJECT_ID(N'dbo.FamilyHoldings', N'U') IS NULL |
| go-app/py/family_import.py | 88 | - | CREATE TABLE dbo.FamilyHoldings ( |
| go-app/py/family_import.py | 279 | FROM | FROM dbo.FamilyHoldings h |
| go-app/py/family_import.py | 327 | DELETE/FROM | cur.execute("DELETE FROM dbo.FamilyHoldings") |
| go-app/py/family_import.py | 330 | INSERT/INTO | "INSERT INTO dbo.FamilyHoldings (PersonID, AssetID, Quantity, CostBasis) VALUES (?, ?, ?, ?)", |

## FamilyPeople

References: **8** across **2** files. Op keywords: FROM=2, INSERT=1, INTO=1, MERGE=1, SELECT=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 43 | - | `IF OBJECT_ID(N'dbo.FamilyPeople', N'U') IS NULL |
| go-app/handlers/family_assets.go | 44 | - | CREATE TABLE dbo.FamilyPeople ( |
| go-app/handlers/family_assets.go | 218 | FROM | FROM dbo.FamilyPeople |
| go-app/handlers/family_assets.go | 963 | INSERT/INTO | INSERT INTO dbo.FamilyPeople (Name, SortOrder) |
| go-app/py/family_import.py | 60 | - | IF OBJECT_ID(N'dbo.FamilyPeople', N'U') IS NULL |
| go-app/py/family_import.py | 61 | - | CREATE TABLE dbo.FamilyPeople ( |
| go-app/py/family_import.py | 240 | MERGE | MERGE dbo.FamilyPeople AS t |
| go-app/py/family_import.py | 248 | SELECT/FROM | cur.execute("SELECT PersonID FROM dbo.FamilyPeople WHERE Name = ?", name) |

## FamilyPrices

References: **15** across **2** files. Op keywords: DELETE=1, FROM=7, MERGE=3, SELECT=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 73 | - | `IF OBJECT_ID(N'dbo.FamilyPrices', N'U') IS NULL |
| go-app/handlers/family_assets.go | 74 | - | CREATE TABLE dbo.FamilyPrices ( |
| go-app/handlers/family_assets.go | 260 | FROM | FROM dbo.FamilyPrices p |
| go-app/handlers/family_assets.go | 264 | FROM | FROM dbo.FamilyPrices p2 |
| go-app/handlers/family_assets.go | 509 | - | // (خروجی کالکتور BRS) در FamilyPrices ثبت می‌کند. |
| go-app/handlers/family_assets.go | 535 | DELETE/FROM | DELETE FROM dbo.FamilyPrices WHERE DateKey < @p1`, floorDate); err != nil { |
| go-app/handlers/family_assets.go | 615 | MERGE | MERGE dbo.FamilyPrices AS t |
| go-app/handlers/family_assets.go | 742 | MERGE | MERGE dbo.FamilyPrices AS t |
| go-app/handlers/family_assets.go | 785 | FROM | FROM dbo.FamilyPrices p |
| go-app/handlers/family_assets.go | 834 | SELECT/FROM | SELECT MAX(DateKey) FROM dbo.FamilyPrices`).Scan(&latest) |
| go-app/handlers/family_assets.go | 1264 | FROM | FROM dbo.FamilyPrices |
| go-app/py/family_import.py | 96 | - | IF OBJECT_ID(N'dbo.FamilyPrices', N'U') IS NULL |
| go-app/py/family_import.py | 97 | - | CREATE TABLE dbo.FamilyPrices ( |
| go-app/py/family_import.py | 283 | FROM | FROM dbo.FamilyPrices p |
| go-app/py/family_import.py | 347 | MERGE | MERGE dbo.FamilyPrices AS t |

## FullPE

References: **12** across **6** files. Op keywords: DELETE=1, FROM=5, INSERT=1, INTO=2, SELECT=3

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/company_score.go | 68 | SELECT/FROM | fullPEQuery := `SELECT CompanyName, PE, Price FROM codal.dbo.FullPE WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))` |
| go-app/handlers/company_score.go | 86 | - | c.JSON(http.StatusInternalServerError, gin.H{"error": "fullPE query error: " + err.Error()}) |
| go-app/handlers/score_handler.go | 45 | - | // Query FullPE data |
| go-app/handlers/score_handler.go | 46 | SELECT/FROM | fullPEQuery := "SELECT TOP (1000) ID, CompanyName, PE, Price, LastModified FROM codal.dbo.FullPE" |
| go-app/handlers/score_handler.go | 54 | INTO | // Parse FullPE data into a map |
| go-app/models/models.go | 82 | - | type FullPE struct { |
| go-app/py/codal_universe.py | 54 | - | "fullpe", |
| go-app/py/codal_universe.py | 56 | SELECT/FROM | SELECT DISTINCT CompanyName FROM dbo.FullPE |
| go-app/py/scraperFullPE.py | 3 | FROM | from FullPE import scrape_pe_values |
| go-app/py/scraperFullPE.py | 64 | DELETE/FROM | cursor.execute("DELETE FROM [codal].[dbo].[FullPE]") |
| go-app/py/scraperFullPE.py | 87 | INSERT/INTO | INSERT INTO [codal].[dbo].[FullPE] (CompanyName, PE, Price, LastModified) |
| go-app/sql/vw_AIStockMetrics.sql | 36 | - | --     P/E = قیمت / EPS_TTM است (با جدول FullPE اعتبارسنجی شد؛ میانه‌ی |

## mahane

References: **20** across **13** files. Op keywords: FROM=9, SELECT=6

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/ai_stock_handler.go | 707 | FROM | FROM dbo.mahane |
| go-app/handlers/company_score.go | 66 | SELECT/FROM | salesQuery := `SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))` |
| go-app/handlers/full_run_scripts.go | 26 | - | table := "mahane" |
| go-app/handlers/sales_data2.go | 20 | SELECT/FROM | query := "SELECT CompanyName, CompanyID, ReportDate, Value1, Value2, Value3 FROM mahane " |
| go-app/handlers/sales_data2.go | 85 | SELECT/FROM | query := "SELECT TOP 1 Url FROM mahane WHERE CompanyName LIKE @companyName " |
| go-app/handlers/score_handler.go | 27 | SELECT/FROM | salesQuery := "SELECT CompanyID, CompanyName, ReportDate, Value3 FROM mahane " |
| go-app/py/backtest.py | 7 | - | - mahane (فروش ماهانه) |
| go-app/py/backtest.py | 140 | FROM | FROM dbo.mahane |
| go-app/py/brs_prices.py | 20 | - | جدول‌های codal (mahane / miandore2) فقط CompanyName دارند و نماد |
| go-app/py/brs_prices.py | 451 | - | for table in ("mahane", "miandore2"): |
| go-app/py/bulk_runner.py | 38 | - | #                     inserted_any = main_scraper2_with_driver(driver, company, row_meta, url, page_numbers, "mahane") |
| go-app/py/codal_processor.py | 21 | - | MONTHLY_TABLE = "mahane" |
| go-app/py/codal_universe.py | 17 | - | (بدون اینکه به mahane/miandore2 وابسته باشد). |
| go-app/py/codal_universe.py | 47 | - | "mahane", |
| go-app/py/codal_universe.py | 49 | SELECT/FROM | SELECT DISTINCT CompanyName FROM dbo.mahane |
| go-app/py/scraper2.py | 15 | - | main_scraper2(company, row_meta, base_url, page_numbers, "mahane") |
| go-app/py/sync_codal.py | 18 | - | miandore2          mahane |
| go-app/sql/vw_AIStockMetrics.sql | 76 | - | --     چون Product1 (ریال) و RevenueNew/mahane (هزار ریال) هم‌خانواده‌ی واحد نیستند. |
| go-app/sql/vw_AIStockMetrics.sql | 117 | SELECT/FROM | SELECT CompanyID, CompanyName FROM dbo.mahane WHERE CompanyID IS NOT NULL |
| go-app/sql/vw_AIStockMetrics.sql | 134 | FROM | FROM dbo.mahane |

## miandore

No references found in source.

## miandore2

References: **74** across **19** files. Op keywords: FROM=19, SELECT=12

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/ai_stock_handler.go | 757 | FROM | FROM dbo.miandore2 |
| go-app/handlers/company_score.go | 67 | SELECT/FROM | epsQuery := `SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2 WHERE LTRIM(RTRIM(CompanyName)) LIKE LTRIM(RTRIM(@companyName))` |
| go-app/handlers/full_run_scripts.go | 28 | - | table = "miandore2" |
| go-app/handlers/sales_data.go | 19 | SELECT/FROM | query := "SELECT CompanyName, CompanyID, ReportDate, Product1, Product2, Product3 FROM miandore2" |
| go-app/handlers/sales_data.go | 76 | SELECT/FROM | query := "SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName " |
| go-app/handlers/sales_data.go | 107 | SELECT/FROM | query := "SELECT TOP 1 Url FROM miandore2 WHERE CompanyName LIKE @companyName" |
| go-app/handlers/score_handler.go | 36 | SELECT/FROM | // epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1 FROM miandore2" |
| go-app/handlers/score_handler.go | 37 | SELECT/FROM | epsQuery := "SELECT CompanyID, CompanyName, ReportDate, Product1, OperatingProfitNew, OperatingProfitLastYear, RevenueNew FROM miandore2" |
| go-app/py/_backfill_v32.py | 4 | - | برای هر شرکت، آخرین URL از miandore2 و اجرای py/scraper.py با rowMeta=1، صفحه 1 |
| go-app/py/_backfill_v32.py | 46 | FROM | FROM dbo.miandore2 |
| go-app/py/_backfill_v32.py | 57 | SELECT/FROM | "SELECT COUNT(DISTINCT CompanyName) FROM dbo.miandore2 WHERE TotalEquity IS NOT NULL" |
| go-app/py/backfill_history.py | 63 | SELECT/FROM | SELECT TOP 1 Url FROM dbo.miandore2 |
| go-app/py/backfill_history.py | 76 | FROM | FROM dbo.miandore2 WHERE CompanyName = ? |
| go-app/py/backtest.py | 6 | - | - miandore2 (گزارش‌های فصلی تجمعی از ۱۳۹۸): Product1, EPS, OperatingProfit*, Revenue*, FinanceCosts, OtherNonOp |
| go-app/py/backtest.py | 132 | FROM | FROM dbo.miandore2 |
| go-app/py/backtest_phase2.py | 76 | - | """miandore2 با همه‌ی ستون‌های v3.2 + نگاشت نام→CompanyID""" |
| go-app/py/backtest_phase2.py | 81 | SELECT/FROM | f"SELECT DISTINCT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyName IN ({qmarks})", |
| go-app/py/backtest_phase2.py | 94 | FROM | FROM dbo.miandore2 |
| go-app/py/brs_prices.py | 20 | - | جدول‌های codal (mahane / miandore2) فقط CompanyName دارند و نماد |
| go-app/py/brs_prices.py | 451 | - | for table in ("mahane", "miandore2"): |
| go-app/py/bulk_runner.py | 36 | - | #                     inserted_any = main_scraper_with_driver(driver, company, row_meta, url, page_numbers, "miandore2") |
| go-app/py/codal_processor.py | 20 | - | FINANCIAL_TABLE = "miandore2" |
| go-app/py/codal_universe.py | 5 | - | ``miandore2.CompanyName`` است (همان که ``GetCompanyNames`` و BulkFetch |
| go-app/py/codal_universe.py | 17 | - | (بدون اینکه به mahane/miandore2 وابسته باشد). |
| go-app/py/codal_universe.py | 40 | - | "miandore2", |
| go-app/py/codal_universe.py | 42 | SELECT/FROM | SELECT DISTINCT CompanyName FROM dbo.miandore2 |
| go-app/py/scraper.py | 17 | - | main_scraper(company, row_meta, base_url, page_numbers, "miandore2") |
| go-app/py/scraperFullPE.py | 29 | SELECT/FROM | cursor.execute("SELECT DISTINCT CompanyName FROM codal.dbo.miandore2") |
| go-app/py/scraperFullPE.py | 46 | FROM | FROM [codal].[dbo].[miandore2] |
| go-app/py/sync_codal.py | 18 | - | miandore2          mahane |
| go-app/sql/add_balance_sheet_columns.sql | 2 | - | --  ستون‌های صورت وضعیت مالی (ترازنامه) و صورت جریان‌های نقدی برای miandore2 |
| go-app/sql/add_balance_sheet_columns.sql | 13 | - | IF COL_LENGTH('dbo.miandore2', 'TotalAssets') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 14 | - | ALTER TABLE dbo.miandore2 ADD TotalAssets FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 16 | - | IF COL_LENGTH('dbo.miandore2', 'TotalAssetsLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 17 | - | ALTER TABLE dbo.miandore2 ADD TotalAssetsLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 19 | - | IF COL_LENGTH('dbo.miandore2', 'CurrentAssets') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 20 | - | ALTER TABLE dbo.miandore2 ADD CurrentAssets FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 22 | - | IF COL_LENGTH('dbo.miandore2', 'CurrentAssetsLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 23 | - | ALTER TABLE dbo.miandore2 ADD CurrentAssetsLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 25 | - | IF COL_LENGTH('dbo.miandore2', 'TotalLiabilities') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 26 | - | ALTER TABLE dbo.miandore2 ADD TotalLiabilities FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 28 | - | IF COL_LENGTH('dbo.miandore2', 'TotalLiabilitiesLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 29 | - | ALTER TABLE dbo.miandore2 ADD TotalLiabilitiesLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 31 | - | IF COL_LENGTH('dbo.miandore2', 'CurrentLiabilities') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 32 | - | ALTER TABLE dbo.miandore2 ADD CurrentLiabilities FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 34 | - | IF COL_LENGTH('dbo.miandore2', 'CurrentLiabilitiesLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 35 | - | ALTER TABLE dbo.miandore2 ADD CurrentLiabilitiesLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 37 | - | IF COL_LENGTH('dbo.miandore2', 'TotalEquity') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 38 | - | ALTER TABLE dbo.miandore2 ADD TotalEquity FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 40 | - | IF COL_LENGTH('dbo.miandore2', 'TotalEquityLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 41 | - | ALTER TABLE dbo.miandore2 ADD TotalEquityLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 43 | - | IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlow') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 44 | - | ALTER TABLE dbo.miandore2 ADD OperatingCashFlow FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 46 | - | IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlowLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 47 | - | ALTER TABLE dbo.miandore2 ADD OperatingCashFlowLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 55 | - | IF COL_LENGTH('dbo.miandore2', 'NetProfitAmount') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 56 | - | ALTER TABLE dbo.miandore2 ADD NetProfitAmount FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 58 | - | IF COL_LENGTH('dbo.miandore2', 'NetProfitAmountLY') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 59 | - | ALTER TABLE dbo.miandore2 ADD NetProfitAmountLY FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 61 | - | IF COL_LENGTH('dbo.miandore2', 'NetProfitAmountFYPrev') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 62 | - | ALTER TABLE dbo.miandore2 ADD NetProfitAmountFYPrev FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 64 | - | IF COL_LENGTH('dbo.miandore2', 'OperatingProfitFYPrev') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 65 | - | ALTER TABLE dbo.miandore2 ADD OperatingProfitFYPrev FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 67 | - | IF COL_LENGTH('dbo.miandore2', 'RevenueFYPrev') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 68 | - | ALTER TABLE dbo.miandore2 ADD RevenueFYPrev FLOAT NULL; |
| go-app/sql/add_balance_sheet_columns.sql | 70 | - | IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlowFYPrev') IS NULL |
| go-app/sql/add_balance_sheet_columns.sql | 71 | - | ALTER TABLE dbo.miandore2 ADD OperatingCashFlowFYPrev FLOAT NULL; |
| go-app/sql/add_revenue_columns.sql | 2 | - | --  Migration: افزودن ستون‌های درآمد عملیاتی به جدول miandore2 |
| go-app/sql/add_revenue_columns.sql | 14 | - | IF COL_LENGTH('dbo.miandore2', 'RevenueNew') IS NULL |
| go-app/sql/add_revenue_columns.sql | 16 | - | ALTER TABLE dbo.miandore2 |
| go-app/sql/add_revenue_columns.sql | 21 | - | IF COL_LENGTH('dbo.miandore2', 'RevenueLastYear') IS NULL |
| go-app/sql/add_revenue_columns.sql | 23 | - | ALTER TABLE dbo.miandore2 |
| go-app/sql/vw_AIStockMetrics.sql | 119 | SELECT/FROM | SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyID IS NOT NULL |
| go-app/sql/vw_AIStockMetrics.sql | 215 | FROM | FROM dbo.miandore2 |

## statements

References: **2** across **1** files. Op keywords: (none)

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/family_assets.go | 42 | - | statements := []string{ |
| go-app/handlers/family_assets.go | 102 | - | for _, s := range statements { |

## StockData

References: **1** across **1** files. Op keywords: FROM=1, SELECT=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/stock_analysis.go | 32 | SELECT/FROM | query := `SELECT TradeDate, [Close], Volume FROM dbo.StockData WHERE Ticker = @ticker ORDER BY TradeDate` |

## StockPrices

No references found in source.

## TrackedTickers

References: **4** across **2** files. Op keywords: (none)

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/py/codal_prefilter.py | 127 | - | """universe را از master ticker list (dbo.TrackedTickers.Symbol) می‌خواند.""" |
| go-app/py/codal_universe.py | 28 | - | UNIVERSE_TABLE = "TrackedTickers" |
| go-app/py/codal_universe.py | 64 | - | """جدول TrackedTickers را در صورت نبود می‌سازد (idempotent).""" |
| go-app/py/codal_universe.py | 148 | - | = نمادهای دستیِ موجود در TrackedTickers (اگر جدول باشد) |

## Users

References: **18** across **9** files. Op keywords: EXEC=1, FROM=5, INSERT=1, INTO=1, SELECT=2, UPDATE=3

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/auth.go | 65 | FROM | FROM [codal].[dbo].[Users] |
| go-app/handlers/auth.go | 95 | UPDATE/EXEC | _, _ = db.Exec(`UPDATE [codal].[dbo].[Users] SET [IsOnline] = 1, [Token] = @p2 WHERE [UserName] = @p1`, |
| go-app/handlers/auth.go | 125 | SELECT/FROM | err := db.QueryRow("SELECT COUNT(*) FROM [codal].[dbo].[Users] WHERE [UserName] = @p1", input.Username).Scan(&count) |
| go-app/handlers/auth.go | 136 | SELECT/FROM | err2 := db.QueryRow("SELECT COUNT(*) FROM [codal].[dbo].[Users] WHERE [Email] = @p1", input.Email).Scan(&count2) |
| go-app/handlers/auth.go | 155 | INSERT/INTO | INSERT INTO [codal].[dbo].[Users] ([UserName], [Email], [Password], [IsOnline], [ViewedItems]) |
| go-app/handlers/portfolio.go | 15 | - | // ensurePortfolioColumn ستون [Portfolio] را روی جدول Users می‌سازد اگر وجود ندارد. |
| go-app/handlers/portfolio.go | 19 | - | IF COL_LENGTH('dbo.Users','Portfolio') IS NULL |
| go-app/handlers/portfolio.go | 20 | - | ALTER TABLE [codal].[dbo].[Users] ADD [Portfolio] NVARCHAR(MAX) NULL |
| go-app/handlers/portfolio.go | 31 | FROM | FROM [codal].[dbo].[Users] WITH (UPDLOCK, ROWLOCK) |
| go-app/handlers/portfolio.go | 59 | UPDATE | UPDATE [codal].[dbo].[Users] |
| go-app/handlers/userViewed.go | 56 | FROM | FROM [codal].[dbo].[Users] WITH (UPDLOCK, ROWLOCK) |
| go-app/handlers/userViewed.go | 104 | UPDATE | UPDATE [codal].[dbo].[Users] |
| go-app/main.go | 46 | - | protected.POST("/users/get-items", handlers.AddViewedItem) |
| go-app/models/portfolio.go | 4 | - | // این ساختار به‌صورت JSON داخل ستون [Portfolio] جدول Users ذخیره می‌شود |
| go-app/py/FullPE.py | 32 | - | CHROMIUM_BINARY = r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe" |
| go-app/py/MianSql.py | 38 | - | r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe" |
| go-app/py/MianSql2.py | 34 | - | CHROMIUM_BINARY = r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe" |
| go-app/py/price.py | 41 | - | r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe" |

## MarketPriceHistory

References: **35** across **9** files. Op keywords: FROM=8, SELECT=1

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/ai_stock_handler.go | 826 | FROM | FROM dbo.MarketPriceHistory |
| go-app/handlers/family_assets.go | 62 | - | // نماد بازار برای سینک خودکار قیمت از MarketPriceHistory |
| go-app/handlers/family_assets.go | 499 | - | // familySyncedPrice یک دارایی که قیمتش از MarketPriceHistory خوانده شد. |
| go-app/handlers/family_assets.go | 508 | - | // syncFamilyPricesFromMarket قیمت هر دارایی خانواده را از MarketPriceHistory |
| go-app/handlers/family_assets.go | 557 | FROM | FROM dbo.MarketPriceHistory m |
| go-app/handlers/family_assets.go | 584 | FROM | FROM dbo.MarketPriceHistory m |
| go-app/handlers/family_assets.go | 660 | - | // SyncFamilyPrices قیمت‌های دارایی خانواده را از بازار (MarketPriceHistory) |
| go-app/handlers/price_history.go | 25 | - | // GetPriceHistory تاریخچه‌ی قیمت یک نماد را از MarketPriceHistory برمی‌گرداند. |
| go-app/handlers/price_history.go | 55 | FROM | FROM dbo.MarketPriceHistory |
| go-app/py/backtest.py | 8 | - | - MarketPriceHistory (قیمت روزانه) |
| go-app/py/backtest.py | 149 | FROM | FROM dbo.MarketPriceHistory |
| go-app/py/brs_prices.py | 5 | - | و ذخیره در جدول dbo.MarketPriceHistory. |
| go-app/py/brs_prices.py | 25 | - | 3) تطبیق از روی نمادی که قبلاً در MarketPriceHistory ثبت شده |
| go-app/py/brs_prices.py | 366 | - | def ensure_price_history_table(cursor, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 443 | - | symbol_index: {Symbol: CompanyID}  (از MarketPriceHistory) |
| go-app/py/brs_prices.py | 467 | - | # نگه‌داشتن نام اصلی codal برای ذخیره در MarketPriceHistory |
| go-app/py/brs_prices.py | 480 | - | # نقشه‌ی نماد از MarketPriceHistory (تغذیه‌ی خودکار با گذشت زمان) |
| go-app/py/brs_prices.py | 485 | FROM | FROM dbo.MarketPriceHistory |
| go-app/py/brs_prices.py | 549 | - | # 3) نماد ذخیره‌شده در MarketPriceHistory |
| go-app/py/brs_prices.py | 888 | - | def upsert_rows(cursor, rows, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 919 | - | def resolve_matched_symbols(table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1027 | - | def cmd_daily(table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1102 | - | def fallback_tsetmc_scrape(symbol, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1170 | - | def cmd_backfill_raw(symbol, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1327 | - | def detect_corporate_events(days=14, threshold=-12.0, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1531 | - | def cmd_sync(days=14, threshold=-20.0, use_api=False, table_name="MarketPriceHistory"): |
| go-app/py/brs_prices.py | 1684 | - | def cmd_backfill(limit=None, symbol=None, force=False, table_name="MarketPriceHistory"): |
| go-app/py/codal_universe.py | 11 | - | - ``MarketPriceHistory`` فقط نمادهایی را نگه می‌دارد که به یک شرکت codal |
| go-app/py/codal_universe.py | 35 | SELECT/FROM | SELECT DISTINCT Symbol FROM dbo.MarketPriceHistory |
| go-app/py/family_import.py | 40 | - | # نماد بازار برای سینک خودکار قیمت از MarketPriceHistory. |
| go-app/py/price.py | 886 | - | table_name="MarketPriceHistory", |
| go-app/py/price.py | 1154 | - | table_name="MarketPriceHistory", |
| go-app/py/price.py | 1221 | - | history_table_name="MarketPriceHistory", |
| go-app/py/price.py | 1315 | - | history_table_name="MarketPriceHistory", |
| go-app/sql/vw_AIStockMetrics.sql | 369 | FROM | FROM dbo.MarketPriceHistory |

## vw_AIStockMetrics

References: **14** across **6** files. Op keywords: FROM=6

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/ai_stock_handler.go | 489 | FROM | FROM dbo.vw_AIStockMetrics |
| go-app/handlers/ai_stock_handler.go | 623 | FROM | FROM dbo.vw_AIStockMetrics |
| go-app/handlers/ai_stock_handler.go | 1140 | FROM | FROM dbo.vw_AIStockMetrics |
| go-app/handlers/export.go | 75 | FROM | FROM dbo.vw_AIStockMetrics |
| go-app/handlers/portfolio.go | 66 | - | // fetchLivePrices 最新 قیمت/سیمبل/نام شرکت‌های داخل پوررفولیو را از vw_AIStockMetrics می‌گیرد. |
| go-app/handlers/portfolio.go | 96 | FROM | FROM [codal].[dbo].[vw_AIStockMetrics] |
| go-app/py/_apply_view.py | 15 | - | sql_text = Path("sql/vw_AIStockMetrics.sql").read_text(encoding="utf-8-sig") |
| go-app/py/_apply_view.py | 31 | FROM | FROM dbo.vw_AIStockMetrics |
| go-app/py/backtest.py | 3 | - | بک‌تست فاز ۱ برای اعتبارسنجی QuantScore (نسخه v3.x از vw_AIStockMetrics) |
| go-app/sql/vw_AIStockMetrics.sql | 4 | - | /****** Object:  View [dbo].[vw_AIStockMetrics]    Script Date: 7/24/2026 ******/ |
| go-app/sql/vw_AIStockMetrics.sql | 12 | - | IF OBJECT_ID(N'dbo.vw_AIStockMetrics', N'V') IS NOT NULL |
| go-app/sql/vw_AIStockMetrics.sql | 13 | - | DROP VIEW dbo.vw_AIStockMetrics |
| go-app/sql/vw_AIStockMetrics.sql | 17 | - | CREATE VIEW [dbo].[vw_AIStockMetrics] |
| go-app/sql/vw_AIStockMetrics.sql | 20 | - | --  vw_AIStockMetrics  (v3.0) |

## vw_AIStockMetrics2

No references found in source.

## vw_AIStockMetrics3

No references found in source.

## fn_JalaliKey

References: **10** across **2** files. Op keywords: (none)

| file | line | op | snippet |
| --- | --- | --- | --- |
| go-app/handlers/ai_stock_handler.go | 709 | - | AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL |
| go-app/handlers/ai_stock_handler.go | 710 | - | ORDER BY dbo.fn_JalaliKey(ReportDate) DESC |
| go-app/handlers/ai_stock_handler.go | 759 | - | AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL |
| go-app/handlers/ai_stock_handler.go | 760 | - | ORDER BY dbo.fn_JalaliKey(ReportDate) DESC |
| go-app/sql/vw_AIStockMetrics.sql | 132 | - | dbo.fn_JalaliKey(ReportDate) AS ReportKey, |
| go-app/sql/vw_AIStockMetrics.sql | 136 | - | AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL |
| go-app/sql/vw_AIStockMetrics.sql | 187 | - | dbo.fn_JalaliKey(ReportDate) AS ReportKey, |
| go-app/sql/vw_AIStockMetrics.sql | 188 | - | dbo.fn_JalaliKey(ReportDate) / 10000 AS JYear, |
| go-app/sql/vw_AIStockMetrics.sql | 189 | - | (dbo.fn_JalaliKey(ReportDate) % 10000) / 100 AS JMonth, |
| go-app/sql/vw_AIStockMetrics.sql | 217 | - | AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL |
