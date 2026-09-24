# Canonical Design Inputs — جمع‌بندی

> این پوشه حاصل مرحله‌ی حل ابهام‌های معماری است: **investigation + read-only queries + documentation**.
> هیچ جدول/schema/داده‌ای در SQL Server یا PostgreSQL تغییر نکرد، هیچ parser/Go handler تغییر نکرد، و هیچ migration اجرا نشد.

## فایل‌ها و ابزارها

| فایل | موضوع |
| --- | --- |
| `01_company_identity_resolution.md` | حل ابهام identity شرکت |
| `02_financial_units_resolution.md` | حل ابهام واحد/مقیاس مالی |
| `03_market_data_resolution.md` | منبع canonical بازار و واحد قیمت |
| `04_date_time_policy.md` | policy تاریخ/زمان |
| `05_view_drift.md` | drift نسخه‌ی view (v3.6 repo vs v3.7 DB) |
| `06_py2_reuse_decision.md` | تصمیم KEEP/EXTEND/REFACTOR/REPLACE |
| `07_architecture_decisions.md` | ADR-001..008 |
| `company_identity_candidates.csv` | ۲۷۹ ردیف نگاشت identity |
| `sql/vw_AIStockMetrics_production.sql` | snapshot view فعلی DB |
| `_investigation_facts.json`, `_units_price_facts.json`, `_identity_details.json`, `_view.diff` | داده‌ی خام investigation |
| `investigate.py`, `investigate2.py`, `investigate3.py`, `investigate4.py` | اسکریپت‌های read-only (فقط SELECT) |

## یافته‌های کلیدی

- **Identity:** `CompanyID = md5(name)`؛ در هر جدول ۱:۱ با نام، اما مسیر نماد vs نام کامل دو ID می‌سازد (شاهد: `کسرا` با یک `InstrumentCode` و دو `CompanyID`). `InstrumentCode` (insCode تسه‌مکو) پایدارترین external identifier است. Codal هیچ identifier شرکت پایدار در feed/HTML نمی‌دهد.
- **Units:** همه‌ی مبالغ `miandore2`/`mahane.Value3` = **میلیون ریال** (اثبات عددی: `LOG10(NP/Product1) ≈ -3` در ۹۸٪ رکوردها)؛ EPS = ریال/سهم؛ `Product1` مقیاس مخلوط. واحد در HTML کدال موجود است ولی parser قدیمی نمی‌خواند.
- **Market:** `MarketPriceHistory` canonical است؛ قیمت‌ها به **ریال**؛ adjusted (`candle_daily_adjusted` + تعدیل محلی). `StockData` (۱۱ نماد، stale تا ۲۰۲۵-۰۵) و `StockPrices` legacy. `FullPE` snapshot اختیاری. `FamilyPrices` دامنه‌ی portfolio.
- **Dates:** همه‌ی timestampها naive و مخلوط UTC/local؛ تاریخ‌های شمسی string. `1405/06/31` معتبر و معادل `2026-09-22` است؛ هیچ roll-over نباید انجام شود.
- **View drift:** repo v3.6 ⊂ production v3.7 (+140/−40 خط)؛ v3.7 `OpAmt`/`OpK`/`SR_TTM*` و `ScoreVersion='v3.7'` را اضافه کرده.

## توصیه‌های کلیدی (خلاصه ADRها)
1. identity داخلی UUID + `securities` با `tsetmc_ins_code`/`codal_symbol` (ADR-001).
2. `numeric` برای پول با واحد canonical ریال + `reported_unit` (ADR-002).
3. قیمت ریال `numeric` + تعدیل صریح (ADR-003).
4. business date میلادی `date` + jalali metadata؛ event `timestamptz` UTC (ADR-004).
5. `MarketPriceHistory` canonical؛ بقیه legacy/جدا (ADR-005).
6. `financial_facts` generic با `statement_type` (ADR-006).
7. لایه‌ی RAW → NORMALIZED (ADR-007).
8. derived metrics فقط در analytics (ADR-008).

---

# CANONICAL POSTGRESQL DESIGN READINESS

## READY

اطلاعات معماری لازم برای طراحی schema تمیز PostgreSQL **کافی است**. سه ابهام اصلی (identity، واحد، تاریخ) با شواهد داده‌ای حل شدند و منبع داده‌ی هر دامنه مشخص شد.

### دامنه‌هایی که طراحی schema بعدی باید پوشش دهد

1. **Identity / Securities**
   - `companies` (UUID PK، display_name، normalized_name)
   - `securities`/`instruments` (company_id FK، `tsetmc_ins_code` UNIQUE، `codal_symbol`، `brs_name`، `security_type`، `is_active`)

2. **Report registry / ingestion**
   - `reports` (registry گزارش‌ها، از `CodalReports` + `reports` py2)
   - `report_versions` (نسخه‌بندی/اصلاحیه)
   - `codal_sync_state` (watermark)
   - `tracked_tickers`/universe

3. **RAW layer**
   - `raw_reports` / `raw_report_payloads` (HTML/JSON خام، source_url، content_hash)

4. **Normalized financial facts**
   - `financial_facts` (statement_type, period, metric_code, value, unit) برای سود و زیان، ترازنامه، جریان نقدی، جامع، حقوق
   - `monthly_activities` (تولید/فروش/مبلغ/داخلی/صادراتی + واحد)

5. **Market data**
   - `market_prices` (شرکت/ابزار، تاریخ میلادی، OHLC نسبی، volume، trade_value، trade_count، is_adjusted)
   - `corporate_actions` (پیشنهادی، برای تعدیل صریح)

6. **Portfolio / Family**
   - `family_people`, `family_assets`, `family_accounts`, `family_holdings`, `family_prices`, `family_cash_flows`, `family_history`

7. **Users / Auth**
   - `users` (+ جدا/`jsonb` برای `portfolio`/`viewed_items`)

8. **Analytics (derived)**
   - materialized view/service برای TTM/growth/margins/P-E/ROE/QuantScore با `score_version` (از v3.7 به بعد) و بدون heuristics واحد.

### شرایط/فرض‌های همراه (خارج از blocker طراحی)
- `statements`, `StockData`, `StockPrices`, `LastModificationDate` **writer ناشناس** دارند → به‌عنوان `REVIEW`/legacy در دامنه‌ی طراحی قرار نگیرند (مگر برعکسش اثبات شود).
- واحد فیزیکی مقادیر `mahane.Value1/Value2` هنوز در source ثبت نمی‌شود → ستون `quantity` + `quantity_unit` با مقدار `unknown`/`reported_unit` در نظر گرفته شود.
- تهیه‌ی ISIN از Codal تضمین‌شده نیست → `codal_symbol` + `tsetmc_ins_code` به‌عنوان شناسه‌های اصلی کافی است.
- داده‌ی تاریخی به‌خاطر اختلاط UTC/local و نبود FK، هنگام migration نیاز به پاک‌سازی/نگاشت دارد (کاری در مرحله‌ی migration، نه blocker طراحی).
