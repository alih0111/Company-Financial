# 03 — Columns

Per-table column definition.


## dbo.CodalReports

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Id | bigint | NOT NULL | YES |  | PK |  |  |
| 2 | CodalReportId | nvarchar(100) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | LetterType | int | NOT NULL |  |  |  |  |  |
| 4 | Ticker | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | CompanyName | nvarchar(300) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 6 | ReportTitle | nvarchar(1000) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 7 | ReportDate | nvarchar(20) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 8 | PublishedAt | datetime2(7) | NULL |  |  |  |  |  |
| 9 | SourceUrl | nvarchar(2000) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 10 | Status | nvarchar(30) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 11 | Attempts | int | NOT NULL |  |  |  | ((0)) |  |
| 12 | DiscoveredAt | datetime2(7) | NOT NULL |  |  |  | (sysutcdatetime()) |  |
| 13 | ProcessedAt | datetime2(7) | NULL |  |  |  |  |  |
| 14 | ErrorMessage | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.CodalSyncState

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | LetterType | int | NOT NULL |  |  | PK |  |  |
| 2 | LastSuccessfulSync | datetime2(7) | NULL |  |  |  |  |  |
| 3 | UpdatedAt | datetime2(7) | NOT NULL |  |  |  | (sysutcdatetime()) |  |

## dbo.FamilyAccounts

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PersonID | int | NOT NULL |  |  | PK |  |  |
| 2 | CashBalance | float(53) | NOT NULL |  |  |  | ((0)) |  |

## dbo.FamilyAssets

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | AssetID | int | NOT NULL | YES |  | PK |  |  |
| 2 | Name | nvarchar(100) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | Category | nvarchar(20) | NOT NULL |  |  |  | (N'stock') | SQL_Latin1_General_CP1_CI_AS |
| 4 | SortOrder | int | NOT NULL |  |  |  | ((0)) |  |
| 5 | IsActive | bit | NOT NULL |  |  |  | ((1)) |  |
| 6 | CommissionRate | float(53) | NOT NULL |  |  |  | ((0.0088)) |  |
| 7 | Symbol | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.FamilyCashFlows

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | int | NOT NULL | YES |  | PK |  |  |
| 2 | DateKey | nvarchar(10) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | Amount | float(53) | NOT NULL |  |  |  |  |  |
| 4 | Direction | nvarchar(3) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | Note | nvarchar(300) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.FamilyHistory

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | DateKey | nvarchar(10) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 2 | TotalValue | float(53) | NOT NULL |  |  |  |  |  |
| 3 | ChangeValue | float(53) | NOT NULL |  |  |  | ((0)) |  |
| 4 | ChangePct | float(53) | NOT NULL |  |  |  | ((0)) |  |
| 5 | RecordedAt | datetime | NOT NULL |  |  |  | (getdate()) |  |

## dbo.FamilyHoldings

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PersonID | int | NOT NULL |  |  | PK |  |  |
| 2 | AssetID | int | NOT NULL |  |  | PK |  |  |
| 3 | Quantity | float(53) | NOT NULL |  |  |  | ((0)) |  |
| 4 | CostBasis | float(53) | NOT NULL |  |  |  | ((0)) |  |

## dbo.FamilyPeople

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PersonID | int | NOT NULL | YES |  | PK |  |  |
| 2 | Name | nvarchar(100) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | SortOrder | int | NOT NULL |  |  |  | ((0)) |  |
| 4 | IsActive | bit | NOT NULL |  |  |  | ((1)) |  |

## dbo.FamilyPrices

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | DateKey | nvarchar(10) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 2 | AssetID | int | NOT NULL |  |  | PK |  |  |
| 3 | Price | float(53) | NOT NULL |  |  |  |  |  |

## dbo.FullPE

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | bigint | NOT NULL | YES |  |  |  |  |
| 2 | CompanyName | nvarchar(150) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | PE | float(53) | NULL |  |  |  |  |  |
| 4 | Price | float(53) | NULL |  |  |  |  |  |
| 5 | LastModified | datetime2(7) | NULL |  |  |  |  |  |

## dbo.mahane

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | int | NOT NULL | YES |  |  |  |  |
| 2 | CompanyID | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | ReportDate | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | Value1 | float(53) | NULL |  |  |  |  |  |
| 6 | Value2 | float(53) | NULL |  |  |  |  |  |
| 7 | Value3 | float(53) | NULL |  |  |  |  |  |
| 8 | Url | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 9 | LastModificationDate | datetime2(7) | NULL |  |  |  |  |  |

## dbo.MarketPriceHistory

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | InstrumentCode | varchar(30) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 2 | CompanyID | nvarchar(50) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(200) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | Symbol | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | GregorianDate | date | NOT NULL |  |  | PK |  |  |
| 6 | JalaliDate | char(10) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 7 | HighPrice | bigint | NULL |  |  |  |  |  |
| 8 | LowPrice | bigint | NULL |  |  |  |  |  |
| 9 | ClosingChangePercent | decimal(12,4) | NULL |  |  |  |  |  |
| 10 | ClosingChange | bigint | NULL |  |  |  |  |  |
| 11 | ClosingPrice | bigint | NULL |  |  |  |  |  |
| 12 | LastChangePercent | decimal(12,4) | NULL |  |  |  |  |  |
| 13 | LastChange | bigint | NULL |  |  |  |  |  |
| 14 | LastPrice | bigint | NULL |  |  |  |  |  |
| 15 | FirstPrice | bigint | NULL |  |  |  |  |  |
| 16 | YesterdayPrice | bigint | NULL |  |  |  |  |  |
| 17 | TradeValue | decimal(24,0) | NULL |  |  |  |  |  |
| 18 | Volume | bigint | NULL |  |  |  |  |  |
| 19 | TradeCount | bigint | NULL |  |  |  |  |  |
| 20 | Url | varchar(550) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 21 | CollectedAt | datetime2(7) | NOT NULL |  |  |  | (sysutcdatetime()) |  |
| 22 | BrsName | nvarchar(200) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.miandore

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | int | NOT NULL | YES |  |  |  |  |
| 2 | CompanyID | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | ReportDate | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | Value1 | float(53) | NULL |  |  |  |  |  |
| 6 | Value2 | float(53) | NULL |  |  |  |  |  |
| 7 | Value3 | float(53) | NULL |  |  |  |  |  |
| 8 | Url | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 9 | Sarmaye | bigint | NULL |  |  |  |  |  |

## dbo.miandore2

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | int | NOT NULL | YES |  |  |  |  |
| 2 | CompanyID | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | ReportDate | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | Num1_Value1 | float(53) | NULL |  |  |  |  |  |
| 6 | Num2_Value1 | float(53) | NULL |  |  |  |  |  |
| 7 | Num4_Value1 | float(53) | NULL |  |  |  |  |  |
| 8 | Product1 | float(53) | NULL |  |  |  |  |  |
| 9 | Num1_Value2 | float(53) | NULL |  |  |  |  |  |
| 10 | Num2_Value2 | float(53) | NULL |  |  |  |  |  |
| 11 | Num4_Value2 | float(53) | NULL |  |  |  |  |  |
| 12 | Product2 | float(53) | NULL |  |  |  |  |  |
| 13 | Num1_Value3 | float(53) | NULL |  |  |  |  |  |
| 14 | Num2_Value3 | float(53) | NULL |  |  |  |  |  |
| 15 | Num4_Value3 | float(53) | NULL |  |  |  |  |  |
| 16 | Product3 | float(53) | NULL |  |  |  |  |  |
| 17 | Url | varchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 18 | OperatingProfitNew | float(53) | NULL |  |  |  |  |  |
| 19 | OperatingProfitLastYear | float(53) | NULL |  |  |  |  |  |
| 20 | FinanceCostsNew | float(53) | NULL |  |  |  |  |  |
| 21 | FinanceCostsLastYear | float(53) | NULL |  |  |  |  |  |
| 22 | OtherNonOpNew | float(53) | NULL |  |  |  |  |  |
| 23 | OtherNonOpLastYear | float(53) | NULL |  |  |  |  |  |
| 24 | RevenueNew | float(53) | NULL |  |  |  |  |  |
| 25 | RevenueLastYear | float(53) | NULL |  |  |  |  |  |
| 26 | TotalAssets | float(53) | NULL |  |  |  |  |  |
| 27 | TotalAssetsLY | float(53) | NULL |  |  |  |  |  |
| 28 | CurrentAssets | float(53) | NULL |  |  |  |  |  |
| 29 | CurrentAssetsLY | float(53) | NULL |  |  |  |  |  |
| 30 | TotalLiabilities | float(53) | NULL |  |  |  |  |  |
| 31 | TotalLiabilitiesLY | float(53) | NULL |  |  |  |  |  |
| 32 | CurrentLiabilities | float(53) | NULL |  |  |  |  |  |
| 33 | CurrentLiabilitiesLY | float(53) | NULL |  |  |  |  |  |
| 34 | TotalEquity | float(53) | NULL |  |  |  |  |  |
| 35 | TotalEquityLY | float(53) | NULL |  |  |  |  |  |
| 36 | OperatingCashFlow | float(53) | NULL |  |  |  |  |  |
| 37 | OperatingCashFlowLY | float(53) | NULL |  |  |  |  |  |
| 38 | NetProfitAmountLY | float(53) | NULL |  |  |  |  |  |
| 39 | NetProfitAmountFYPrev | float(53) | NULL |  |  |  |  |  |
| 40 | OperatingProfitFYPrev | float(53) | NULL |  |  |  |  |  |
| 41 | RevenueFYPrev | float(53) | NULL |  |  |  |  |  |
| 42 | OperatingCashFlowFYPrev | float(53) | NULL |  |  |  |  |  |
| 43 | NetProfitAmount | float(53) | NULL |  |  |  |  |  |

## dbo.statements

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | bigint | NOT NULL | YES |  | PK |  |  |
| 2 | CompanyID | nvarchar(50) | NOT NULL |  |  | UQ |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(150) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | ReportDate | nvarchar(50) | NOT NULL |  |  | UQ |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | StatementType | nvarchar(40) | NOT NULL |  |  | UQ |  | SQL_Latin1_General_CP1_CI_AS |
| 6 | MetricCode | nvarchar(160) | NOT NULL |  |  | UQ |  | SQL_Latin1_General_CP1_CI_AS |
| 7 | RowTitle | nvarchar(500) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 8 | PeriodOrder | int | NOT NULL |  |  | UQ |  |  |
| 9 | PeriodHeader | nvarchar(500) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 10 | Value | float(53) | NULL |  |  |  |  |  |
| 11 | UnitCode | nvarchar(32) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 12 | Url | varchar(550) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 13 | CollectedAt | datetime2(7) | NOT NULL |  |  |  | (sysdatetime()) |  |

## dbo.StockData

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Ticker | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 2 | TradeDate | date | NOT NULL |  |  | PK |  |  |
| 3 | Open | float(53) | NULL |  |  |  |  |  |
| 4 | High | float(53) | NULL |  |  |  |  |  |
| 5 | Low | float(53) | NULL |  |  |  |  |  |
| 6 | Close | float(53) | NULL |  |  |  |  |  |
| 7 | Volume | int | NULL |  |  |  |  |  |
| 8 | OpenInterest | float(53) | NULL |  |  |  |  |  |
| 9 | OpenInt1 | int | NULL |  |  |  |  |  |
| 10 | OpenInt2 | float(53) | NULL |  |  |  |  |  |
| 11 | Url | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.StockPrices

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | bigint | NOT NULL | YES |  |  |  |  |
| 2 | date | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | CompanyName | nvarchar(250) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | count | int | NULL |  |  |  |  |  |
| 5 | volume | bigint | NULL |  |  |  |  |  |
| 6 | value | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 7 | yesterday_price | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 8 | open | float(53) | NULL |  |  |  |  |  |
| 9 | close | float(53) | NULL |  |  |  |  |  |
| 10 | diffrent | float(53) | NULL |  |  |  |  |  |
| 11 | diffrent_percentage | float(53) | NULL |  |  |  |  |  |
| 12 | mean_price | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 13 | mean_diffrent | float(53) | NULL |  |  |  |  |  |
| 14 | mean_diffrent_percentage | float(53) | NULL |  |  |  |  |  |
| 15 | low | float(53) | NULL |  |  |  |  |  |
| 16 | high | float(53) | NULL |  |  |  |  |  |
| 17 | en_date | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 18 | url | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |

## dbo.TrackedTickers

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Symbol | nvarchar(50) | NOT NULL |  |  | PK |  | SQL_Latin1_General_CP1_CI_AS |
| 2 | Source | nvarchar(50) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | IsActive | bit | NOT NULL |  |  |  | ((1)) |  |
| 4 | CreatedAt | datetime2(7) | NOT NULL |  |  |  | (sysutcdatetime()) |  |

## dbo.Users

| # | column | type | nullability | identity | computed | key | default/expr | collation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ID | bigint | NOT NULL | YES |  |  |  |  |
| 2 | UserName | nvarchar(550) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 3 | Email | nvarchar(450) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 4 | Password | nvarchar(950) | NOT NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 5 | ViewedItems | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 6 | IsOnline | bit | NULL |  |  |  |  |  |
| 7 | Token | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
| 8 | IsAdmin | bit | NULL |  |  |  | ((0)) |  |
| 9 | Portfolio | nvarchar(max) | NULL |  |  |  |  | SQL_Latin1_General_CP1_CI_AS |
