# 07 — Proposed Architecture Decisions (ADR)

> پیشنهادها بر پایه‌ی investigationهای همین پوشه. هیچ implementation/migration انجام نشده است.

---

## ADR-001 — Company identity

**Context:** `CompanyID = md5(name)`؛ شاهد دو CompanyID برای یک InstrumentCode (کسرا)؛ `Symbol` می‌تواند به چند نهاد اشاره کند؛ Codal هیچ identifier شرکت پایدار نمی‌دهد.

**Decision:**
- Internal identity = **UUID** (`companies.id`).
- External identifiers جدا در `securities`:
  - `tsetmc_ins_code` (`InstrumentCode`) — UNIQUE، شناسه‌ی پایدار بازار
  - `codal_symbol` (`Symbol`) — برای اتصال به Codal
  - `isin` (اختیاری، در صورت دسترس)
- `CompanyName` فقط display/lookup است، هرگز کلید.

**Reason:** نام پایدار نیست؛ `InstrumentCode` یکتای بازار و مستقل از نام است.

**Alternatives:** استفاده از `Symbol` به‌عنوان PK (رد: نمادهای فرعی و تصادم کسرا)؛ استفاده از `TracingNo` (رد: شناسه‌ی گزارش است نه شرکت).

**Risks:** mapping داده‌ی قدیمی باید دوگانه‌ی نام/نماد را با `InstrumentCode` ادغام کند؛ ممکن است چند نماد یک شرکت به یک security نگاشت شوند (نیاز به قاعده).

---

## ADR-002 — Financial amount storage

**Context:** همه‌ی مبالغ `float` و به‌صورت **میلیون ریال** (اثبات عددی)؛ EPS ریال/سهم؛ `statements.UnitCode='unknown'`.

**Decision:**
- نوع = **`numeric`** (نه float)، دقت کافی (مثلاً `numeric(24,4)`).
- واحد canonical = **ریال**؛ مقدار خام گزارش + `reported_unit` (`million_rial`/`thousand_rial`/`rial`) و `unit_multiplier` ذخیره شود.
- EPS به‌عنوان `rial_per_share` با `numeric`.

**Reason:** دقت پولی، ریشه‌کن‌کردن heuristics واحد (`NPUnitRatio`/`OpK`)، حفظ شفافیت منبع.

**Alternatives:** نگه‌داشتن میلیون ریال به‌عنوان واحد canonical (رد: بازهم نیاز به تبدیل و ابهام در نسبت‌ها دارد).

**Risks:** تبدیل باید idempotent و مستند باشد؛ داده‌ی تاریخی با واحدهای مخلوط نیاز به backfill محتاطانه دارد.

---

## ADR-003 — Price storage

**Context:** MPH قیمت‌ها به ریال، `BIGINT`؛ StockData/StockPrices موازی.

**Decision:**
- قیمت canonical = **ریال**، نوع **`numeric`**.
- OHLC برای MPH: `high`, `low`, `close/last`, `first`, `yesterday`؛ `volume` (تعداد سهم)، `trade_value` (ریال)، `trade_count`.
- ستون‌های صریح تعدیل: `is_adjusted`, `adjusted_at`.

**Reason:** یکسانی با ADR-002، دقت، و شفافیت تعدیل.

**Alternatives:** تومان (رد: منبع ریال است و تبدیل، منشأ خطا).

**Risks:** واحد بعضی منابع ممکن است تومان باشد (در BRS/TSETMC فعلی ریال تأیید شد؛ سایر منابع باید در ingestion چک شوند).

---

## ADR-004 — Dates

**Context:** تاریخ‌های شمسی به‌صورت string؛ timestampهای naive و مخلوط UTC/local.

**Decision:**
- Business date: **`date` میلادی** canonical + `jalali_text` + `fiscal_year`/`fiscal_month` (int).
- Event timestamp: **`timestamptz` به UTC**.
- تبدیل/اعتبارسنجی جلالی با کتابخانه‌ی معتبر؛ بدون roll-over؛ تاریخ نامعتبر رد شود.

**Reason:** محاسبات و range queries درست؛ نمایش جلالی در لایه‌ی UI.

**Alternatives:** ذخیره‌ی جلالی به‌عنوان canonical `date` (رد: تقویم/کبیسه و join با میلادی سخت می‌شود).

**Risks:** `PublishedAt` فعلی در واقع زمان تهران است؛ مهاجرت باید +3:30 را به UTC تبدیل کند.

---

## ADR-005 — Market data

**Context:** سه منبع هم‌پوشان + FullPE + FamilyPrices.

**Decision:**
- Canonical = **`market_prices` از `MarketPriceHistory`** (ریال، adjusted صریح، شناسه‌ی `InstrumentCode`).
- `StockData`/`StockPrices` = **LEGACY_DO_NOT_MIGRATE** (مگر برداشتن هدفمند ستون `Open`).
- `FullPE`: canonical نباشد؛ P/E در لایه‌ی analytics از financial+price محاسبه شود (در صورت نیاز، snapshot فروشنده به‌صورت RAW با timestamp).
- `FamilyPrices` = دامنه‌ی **portfolio**، جدا از market.

**Reason:** MPH کامل‌ترین و پایدارترین است؛ کاهش جدول‌های موازی.

**Alternatives:** StockData canonical (رد: فقط ۱۱ نماد، stale تا 2025-05).

**Risks:** نیاز به ستون Open در MPH (فعلاً `FirstPrice` تقریبی) در صورت نیاز consumer.

---

## ADR-006 — Financial facts

**Context:** `miandore2` wide با چند صورت مالی؛ `py2.financial_facts` generic اما فقط ۵ متریک.

**Decision:**
- مدل **generic facts**: `financial_facts(report_id, statement_type, period_order, period_header, metric_code, row_title, value, unit_code)`.
- گسترش به `statement_type`: income, balance_sheet, cash_flow, comprehensive_income, equity_changes.
- `monthly_activities` wide بماند.

**Reason:** انعطاف برای همه‌ی صورت‌ها و خطوط؛ سازگار با الگوی موجود `statements`/py2.

**Alternatives:** نگه‌داشتن wide (رد: برای ترازنامه/جریان نقدی انفجار ستون و کدشکن).

**Risks:** نیاز به `metric_code` پایدار و نگاشت رسمی با عناوین کدال.

---

## ADR-007 — Raw vs Normalized layers

**Context:** parserهای فعلی هم raw و هم normalized را در یک مسیر می‌ریزند و داده‌ی خام کدال حفظ نمی‌شود.

**Decision:** معماری **دو لایه**:
- **RAW:** `raw_reports` / `raw_report_versions` (payload خام HTML/JSON، source_url، content_hash، collected_at).
- **NORMALIZED:** `reports`, `financial_facts`, `monthly_activities`, `market_prices`, ... تولیدشده از RAW توسط parser.

**Reason:** حفظ قابلیت بازپردازش (reparse) بدون دوباره‌کشیدن از کدال؛ امکان تکامل parser؛ audit کامل.

**Alternatives:** فقط normalized (رد: از دست رفتن متن اصلی و وابستگی به شبکه).

**Risks:** حجم ذخیره‌سازی؛ نیاز به سیاست retention و hashing.

---

## ADR-008 — Derived metrics

**Context:** TTM/growth/margins/P-E/ROE/QuantScore داخل `vw_AIStockMetrics` محاسبه می‌شوند.

**Decision:** derived metrics در **analytics layer** (view/materialized view یا سرویس) باشند، نه در جداول raw مالی.
- raw/normalized فقط داده‌ی واقعی گزارش‌شده.
- derived به‌صورت materialized view قابل بازسازی از normalized (با `score_version`).

**Reason:** تست‌پذیری، بازسازی، جلوگیری از ناسازگاری و تکرار منطق.

**Alternatives:** ذخیره‌ی derived در جداول (رد: stale شدن و ناسازگاری).

**Risks:** کارایی؛ نیاز به refresh/materialization و versioning نسخه‌ی score.
