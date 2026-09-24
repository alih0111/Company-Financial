# 04 — Company Identity Audit

> مبنا: trace کد. هیچ حدسی زده نشده؛ موارد نامطمئن `UNKNOWN`.

## identifierها

| identifier | محل | تعریف دقیق |
| --- | --- | --- |
| `CompanyID` | `mahane`, `miandore2`, `MarketPriceHistory`, family? | در `MianSql.py:60`, `MianSql2.py:47`, `codal_processor.py:26`, `FullPE.py:39`, `price.py:56`: `md5(company_name.encode("utf-8")).hexdigest()`. در `brs_prices.py` هم `md5(normalize_persian(name))` (بدون hash اگر داخل API بیاید). |
| `CompanyName` | `mahane`, `miandore2`, `MarketPriceHistory`, `FullPE` | نام/نماد همان‌طور که از Codal یا UI آمده؛ در `MarketPriceHistory` نام اصلی codal است. |
| `Symbol` | `MarketPriceHistory.Symbol`, `TrackedTickers.Symbol` | نماد کدال (`CodalReport.ticker` = فیلد `Symbol` از API کدال) / نماد BRS (`l18`). |
| `Ticker` | `CodalReports.Ticker`, `StockData.Ticker` | در `CodalReports` = `Symbol` کدال؛ در `StockData` نماد معاملاتی (نویسنده `UNKNOWN`). |
| `InstrumentCode` | `MarketPriceHistory.InstrumentCode` | `item.get("id") or item.get("isin") or item.get("l18")` از BRS (`brs_prices.py:745`) — یعنی شناسه‌ی BRS/ISIN، نه کدال. |
| `BrsName` | `MarketPriceHistory.BrsName` | نام منبع BRS (`l30`). |

## پاسخ به سؤالات

### ۱) `CompanyID` چگونه ساخته می‌شود؟ آیا stable است؟ کدال است یا hash؟
- `md5(company_name)`؛ یک **hash داخلی** است، نه `TracingNo`/`ISIN`/`Symbol` کدال.
- **stable نیست مطلقاً:** به رشته‌ی `company_name` وابسته است. مسیرها رشته‌های متفاوت می‌فرستند:
  - Go UI → `full_run_scripts.go`/`run_script.go`: نام انتخابی کاربر.
  - Discovery sync → `sync_codal.py:265`: `report.ticker or report.company_name` (معمولاً **نماد**).
- نتیجه: یک شرکت واحد می‌تواند **دو `CompanyID` متفاوت** بگیرد (md5 نام کامل vs md5 نماد) → رکوردهای تکراری/یتیم. **HIGH RISK**.
- `brs_prices.load_name_maps` تلاش می‌کند با `name_index` (از `mahane`/`miandore2`) این ناسازگاری را تطبیق دهد، اما اگر شرکت در این جداول نباشد `CompanyID` جدید ساخته می‌شود (`backfill-raw`).

### ۲) `Symbol` چگونه به `CompanyID` وصل می‌شود؟
- مستقیم وصل نیست؛ در `MarketPriceHistory` هر دو ذخیره می‌شوند (`Symbol`, `CompanyID`). `brs_prices.symbol_index` از همین جدول ساخته می‌شود تا در sync بعدی نماد → CompanyID نگاشت شود.

### ۳) `InstrumentCode` چگونه به `Symbol` وصل می‌شود؟
- در `MarketPriceHistory` هر ردیف هم `InstrumentCode` (شناسه‌ی BRS) و هم `Symbol` (نماد کدال) را دارد؛ PK روی `(InstrumentCode, GregorianDate)` است.

### ۴) `BrsName` چگونه match می‌شود؟
- `resolve_company_id(l18, l30, ...)` ترتیب:
  1. override فایل `py/symbol_override.json` (id یا نام)
  2. تطبیق نام دقیق (`name_index`)
  3. `symbol-equals-name` (نماد = نام codal، مثل «خودرو»)
  4. `stored-symbol` (نماد ذخیره‌شده در `MarketPriceHistory`)
  5. `containment` (یکی در دیگری باشد، با شرط حداقل ۲ توکن)
  6. fuzzy Jaccard با آستانه‌ی **0.75**
- اگر هیچ‌کدام → `None` و در backfill یک رکورد `CompanyID = md5(name)` ساخته می‌شود.

### ۵) کجاها join روی `CompanyName` انجام شده؟
- `company_score.go` و `score_handler.go`: `fullPEMap` روی `CompanyName` ساخته و `peData := fullPEMap[name]` (join در Go، نه SQL).
- `price_history.go:56`: `WHERE CompanyName = @name OR Symbol = @name`.
- `scraperFullPE.py:29,47`: `SELECT ... FROM miandore2 WHERE CompanyName = ?`.
- `codal_universe.py`: `SELECT DISTINCT CompanyName` به‌عنوان منبع universe.
- در مقابل، `vw_AIStockMetrics` و `ai_stock_handler.go` عمدتاً روی `CompanyID` کار می‌کنند.

### ۶) fuzzy matching کجاست؟
- فقط در `brs_prices.py` (`tokens_for_match`, `jaccard`, containment).

### ۷) چه چیزی می‌تواند identity را خراب کند؟
- `CompanyID = md5(name)` با نام‌های متفاوت برای یک شرکت → تکراری شدن.
- عدم تطبیق BRS↔Codal به‌خاطر تفاوت نام (`BrsName` vs `CompanyName`) → `CompanyID` اشتباه/جدید.
- fuzzy/containment می‌تواند شرکت‌های با توکن مشترک را جابه‌جا کند (مثلاً «پارس …»)؛ آستانه 0.75 ریسک را کم می‌کند ولی حذف نمی‌کند.
- join روی `CompanyName` در Go (FullPE) در برابر `CompanyID` در view → ناسازگاری کلید بین سرویس‌ها.
- `TrackedTickers` نماد محور است (Symbol)، ولی داده‌ی اصلی `CompanyID` محور → نگاشت نماد↔شناسه یک لایه‌ی جداگانه و ناقص است.

## نگاشت نمادین

```
Codal report  ──(TracingNo)──> CodalReports.CodalReportId
      │
      └── Symbol (ticker) ──> TrackedTickers.Symbol
      │
      └── CompanyName/ticker ──md5()──> CompanyID (mahane/miandore2)
                                  │
BRS AllSymbols (l18, l30, isin) ──resolve_company_id──> CompanyID
                                  │
                        MarketPriceHistory (InstrumentCode, Symbol, CompanyID, BrsName)
```

## `UNKNOWN`ها
- اینکه در داده‌ی فعلی، رکوردهای `mahane`/`miandore2` با `CompanyID=md5(نام کامل)` یا `md5(نماد)` نوشته شده‌اند، بدون query روی DB و مقایسه با لیست نمادها قطعی نیست.
