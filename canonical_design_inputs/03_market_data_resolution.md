# 03 — Price Unit & Canonical Market Data Resolution

> investigation فقط (SELECT). مبنا: `_units_price_facts.json`, `_investigation_facts.json`, کد `brs_prices.py`/`price.py`.

## وضعیت کلی جداول

| جدول | rows | شناسه‌ها | بازه‌ی تاریخ | writer | reader | وضعیت |
| --- | --- | --- | --- | --- | --- | --- |
| `MarketPriceHistory` | 705,812 | 277 InstrumentCode / 274 CompanyID / 277 Symbol | 1991-11-20 → 2026-09-24 | `brs_prices.py` (BRS API)، `price.py` (TSETMC) | Go `price_history.go`, `vw`, `family_assets` | **ACTIVE / canonical** |
| `StockData` | 32,958 | 11 Ticker | 2001-03-26 → **2025-05-28** | **هیچ writer در سورس** | Go `stock_analysis.go` | **STALE / نیمه‌متروک** |
| `StockPrices` | 277 | CompanyName | (date به‌صورت nvarchar) | nenhum | nenhum | **LEGACY** |
| `FullPE` | 244 | CompanyName | snapshot | `scraperFullPE.py` | Go, `vw` | snapshot لحظه‌ای |
| `FamilyPrices` | 15,302 | DateKey+AssetID | 1405/07/02 (نمونه) | `family_import.py`, Go | Go `family_assets` | **portfolio valuation cache** |

## واحد قیمت — اثبات
نمونه‌ی MPH (`2026-09-24`): `زدشت` Close=9490، Volume=8,626,371، TradeValue=81,890,724,830.
`TradeValue / Volume = 81,890,724,830 / 8,626,371 ≈ 9493 ≈ ClosingPrice`.
→ **قیمت‌ها و TradeValue به ریال**، Volume به تعداد سهم. کلاس: **INFERABLE_FROM_SOURCE** (HIGH).

## مقایسه‌ی `MarketPriceHistory` با `StockData`

- `StockData` فقط **۱۱ نماد** و آخرین تاریخ **۲۰۲۵-۰۵-۲۸** (حدود ۱۶ ماه قدیمی‌تر از MPH) → عملاً متوقف.
- هم‌پوشانی‌های زمانی (join روی `Symbol=Ticker` و `GregorianDate=TradeDate`): نسبت `MPH.ClosingPrice / StockData.Close` در بازه‌ی **۰.۳۲ تا ۱.۰۱** توزیع شده (نه ×۱۰ و نه ×۱۰۰).
- چون واحد هر دو ریال است، اختلاف از **مبنای قیمت** است، نه ارز:
  - MPH از `Candlestick.php?type=3` = `candle_daily_adjusted` می‌آید و علاوه بر آن `local_adjust_prices` روی رویدادهای شرکتی اعمال می‌کند.
  - `StockData` هیچ writer/مستندات تعدیل ندارد → احتمالاً **unadjusted**.
  - تفاوت فروشنده (vendor) و stale بودن StockData هم دخیل است.
- **نتیجه:** ستون `Open` در `StockData` وجود دارد ولی MPH ندارد (فقط `FirstPrice`/`YesterdayPrice`). اگر Open واقعی لازم باشد، باید از منبع یا فیلد `FirstPrice` با احتیاط استفاده شود. اما `StockData` به‌خاطر پوشش (۱۱ نماد) و قدمت، نمی‌تواند canonical باشد.

## Corporate actions در `brs_prices.py`
1. `detect_corporate_events(days, threshold=-20/-12)`: با `LAG` روی `ClosingPrice` به‌ازای هر `InstrumentCode`، افت‌های بیش از آستانه را «رویداد» می‌داند.
2. `local_adjust_prices`: قیمت‌های قدیمی همان `InstrumentCode` را **محلی** تعدیل می‌کند (بدون API).
3. `cmd_sync --api`: به‌جای تعدیل محلی، از API (Candlestick) دوباره re-fetch می‌کند.

→ **MPH یک بار تعدیل‌شده است** (`candle_daily_adjusted`). اثر روی backtest: چون تعدیل محلی heuristic و بر پایه‌ی آستانه‌ی افت است، ممکن است رویدادهای کوچک (زیر آستانه) تعدیل نشوند و بازدهی‌های تاریخی مصنوعی ایجاد کنند؛ اما دیتاست به‌طور کلی adjusted است، نه خام.

## `FullPE`
- Snapshot لحظه‌ای: `PE` از `div[17]` و `Price` از `div[8]` صفحه‌ی TSETMC؛ هر اجرا کل جدول DELETE و بازنویسی می‌شود.
- `FullPE.Price / MPH.ClosingPrice` برای آخرین روز در نمونه: **۰.۷ تا ۱.۱** → هم‌واحد (ریال)، تفاوت به‌خاطر منبع/زمان.
- ارزیابی گزینه‌ها:
  - **A) raw market snapshot:** ارزش ذاتی پایین؛ snapshot مثبت صفر تاریخ است (تاریخچه ندارد) و با منبع اصلی هم‌پوشان است.
  - **B) اصلاً canonical نباشد و P/E از financial + price محاسبه شود:** **پیشنهاد ما** — چون `vw_AIStockMetrics` همین حالا `PEApprox` را از `TTMEPS` و قیمت محاسبه می‌کند.
  - جمع‌بندی: `FullPE` به‌عنوان جدول canonical نگه داشته **نشود**؛ در صورت نیاز به P/E گزارش‌شده‌ی فروشنده، به‌صورت یک فایل/ستون RAW اختیاری با timestamp حفظ شود. (ADR-005)

## `FamilyPrices`
- محتوای نمونه: `DateKey=1405/07/02`, `Asset.Name=یاقوت/غشان/کپرور/مثقال`, `Category=stock|gold`.
- یعنی قیمت دارایی‌های **پورتفوی خانوادگی** (سهام دستی + طلا) → یک **portfolio valuation cache/history**، نه market data عمومی.
- **نباید با canonical market prices ترکیب شود.** ممکن است در آینده از MPH تغذیه شود، اما entity آن `family_asset_price` است.

## تصمیم canonical market data
- **منبع canonical = `MarketPriceHistory`** (با اثبات: کامل‌ترین پوشش، شناسه‌ی بازار `InstrumentCode`, OHLC نسبی، Volume/TradeValue/TradeCount، adjusted، رویداد شرکتی).
- `StockData` و `StockPrices` → `LEGACY_DO_NOT_MIGRATE` (مگر تصمیم آگاهانه برای برداشتن ستون Open از StockData).
- قیمت‌ها canonical: **ریال**، `numeric` (نه bigint، برای آینده و دقت).
- تعدیل: ستون `is_adjusted boolean` + `adjusted_at timestamp` + جدول `corporate_actions` پیشنهادی، تا تعدیل صریح باشد (نه heuristic پنهان).
- `FullPE` → خارج از دامنه‌ی market price (snapshot اختیاری).
- `FamilyPrices` → دامنه‌ی portfolio، جدا.

## UNKNOWNها
- منبع دقیق و الگوریتم تعدیل `price.py` (TSETMC).
- علت دقیق تفاوت MPH/StockData در سطح هر ردیف (نیاز به cross-check کامل per-date).
- مقدار درست `Open` برای MPH (`FirstPrice` چقدر به Open واقعی نزدیک است).
