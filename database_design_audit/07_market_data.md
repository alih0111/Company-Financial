# 07 — Market Data Audit

> مقایسه‌ی `MarketPriceHistory`, `StockData`, `StockPrices`, `FullPE`, `FamilyPrices`.
> مبنا: trace کد. موارد نامعلوم `UNKNOWN`.

## جدول مقایسه

| ویژگی | `MarketPriceHistory` | `StockData` | `StockPrices` | `FullPE` | `FamilyPrices` |
| --- | --- | --- | --- | --- | --- |
| **Writer** | `py/brs_prices.py` (BRS API) و `py/price.py` (TSETMC) | **هیچ writer در سورس یافت نشد** | **هیچ writer یافت نشد** | `py/scraperFullPE.py` (DELETE کل + INSERT) | `py/family_import.py` + Go `family_assets.go` |
| **Reader** | Go `price_history.go`, `vw_AIStockMetrics`, `family_assets.go` | Go `stock_analysis.go` | **هیچ reader یافت نشد** | Go `company_score.go`, `score_handler.go`, `vw` | Go `family_assets.go` |
| **Data source** | BRS API (`Api.BrsApi.ir/Tsetmc`) + TSETMC (old.tsetmc.com) | UNKNOWN | UNKNOWN | TSETMC `Loader.aspx?ParTree=15131F` | قیمت دستی/ثبت‌شده کاربر |
| **Identifiers** | `InstrumentCode` + `GregorianDate` (PK)، `Symbol`, `CompanyID`, `CompanyName`, `BrsName` | `Ticker` + `TradeDate` (PK) | `CompanyName` + `date` (PK) | `CompanyName` (PK) + `ID` identity | `DateKey` + `AssetID` (PK) |
| **Coverage** | tsetmc روزانه (snapshot) + تاریخچه‌ی تعدیل‌شده | 32,958 ردیف | 277 ردیف | ~244 شرکت (snapshot) | 15,302 ردیف |
| **Price unit** | `BIGINT` خام — **UNKNOWN** | `float` — UNKNOWN | `float` — UNKNOWN | `float` — UNKNOWN | `float` — UNKNOWN |
| **Adjusted?** | بله (BRS `Candlestick.php?type=3` = `candle_daily_adjusted`) + adjust محلی رویدادهای شرکتی | UNKNOWN | UNKNOWN | — (نسبت) | — |
| **OHLC** | High/Low/Closing(Last)/First/Yesterday (بدون Open صریح؛ `FirstPrice` تقریبی) | Open/High/Low/Close | open/close/low/high | — | — |
| **Volume** | `Volume BIGINT` | `Volume int` | `volume bigint` | — | — |
| **Trade value** | `TradeValue DECIMAL(24,0)` | ندارد (فقط Volume) | `value nvarchar(50)` | — | — |
| **Corporate action** | `detect_corporate_events` (افت > -۱۲٪/-۲۰٪) → `local_adjust_prices` یا API re-fetch | UNKNOWN | UNKNOWN | — | — |
| **Status** | **ACTIVE / canonical candidate** | SUSPECT (نیمه‌متروک، فقط یک endpoint) | **LEGACY** | ACTIVE (snapshot نسبت P/E) | ACTIVE (دامنه‌ی خانواده) |
| **Row count** | 705,812 | 32,958 | 277 | 244 | 15,302 |

## آیا `MarketPriceHistory` می‌تواند canonical باشد؟

- **بله، به‌عنوان canonical market price:** کامل‌ترین جدول است (OHLC نسبی، Volume، TradeValue، TradeCount، تعدیل، رویداد شرکتی، `InstrumentCode`+`Symbol`+`CompanyID`).
- **اما یک شکاف مهم:** `StockData` ستون **`Open`** دارد و `MarketPriceHistory` ستون `Open` صریح ندارد (فقط `FirstPrice`/`YesterdayPrice`). پس اگر مصرف‌کننده‌ای به Open واقعی نیاز دارد، `MarketPriceHistory` ممکن است کافی نباشد.
- همچنین `StockData` با `Ticker` کلید شده (نماد معاملاتی) در حالی که `MarketPriceHistory` با `InstrumentCode` (شناسه BRS) کلید شده → نگاشت بین دو دامنه لازم است.
- `StockData` هیچ writer در سورس ندارد → منبع و به‌روزرسانی آن `UNKNOWN` است؛ احتمال توقف ingestion آن بالاست.

## تعدیل و رویدادهای شرکتی (فقط `MarketPriceHistory`)

- منبع BRS: `Candlestick.php?type=3` صریحاً `candle_daily_adjusted` است.
- `detect_corporate_events`: با `LAG` روی `ClosingPrice` (per `InstrumentCode`) افت‌های > آستانه را رویداد می‌داند.
- `local_adjust_prices`: قیمت‌های قدیمی را محلی تعدیل می‌کند (بدون API) — heuristic.
- `cmd_sync --api`: re-backfill از API.

## `FullPE`

- Snapshot لحظه‌ای (نه time-series). هر اجرا کل جدول را `DELETE` و بازنویسی می‌کند.
- `PE` از `divs[17]` و `Price` از `divs[8]` صفحه‌ی TSETMC.
- اگر `PE == 0` بود → `PE = price / eps` که `eps` از `miandore2.Num1_Value1` (آخرین ReportDate) گرفته می‌شود.
- **اتصال DB:** `scraperFullPE.save_to_db` از `localhost` + `Trusted_Connection=yes` استفاده می‌کند (نه `.env`) → ریسک محیطی.

## `UNKNOWN`ها

- نویسنده و منبع `StockData` و `StockPrices`.
- واحد قیمت‌ها (`BIGINT`/`float`) در همه‌ی جداول.
- آیا `price.py` قیمت‌ها را تعدیل می‌کند یا نه.
- منبع و به‌روزرسانی `StockData.Ticker`.
