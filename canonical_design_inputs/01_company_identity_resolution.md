# 01 — Canonical Company Identity Resolution

> مرحله: investigation فقط. هیچ DB/schema/کد تغییر نکرد. همه‌ی queryها SELECT بودند.
> داده‌ی خام: `_investigation_facts.json`, `_identity_details.json`, `company_identity_candidates.csv`.
> اسکریپت‌ها: `investigate.py`, `investigate2.py`, `investigate4.py` (read-only).

## منابع بررسی‌شده
`mahane`, `miandore2`, `MarketPriceHistory` (MPH), `TrackedTickers`, `FullPE`, `CodalReports`,
به‌همراه کد `codal_feed.py`, `codal_prefilter.py`, `codal_universe.py`, `brs_prices.py`, `MianSql*.py`, `FullPE.py`, `price.py`.
همچنین یک fetch read-only از Codal feed API و یک گزارش HTML برای بررسی identifier رسمی.

## نتایج عددی (داده‌ی واقعی)

| سنجه | مقدار |
| --- | --- |
| CompanyIDهای یکتا (universe هر سه جدول) | **279** (CSV) |
| CompanyID در `mahane` | 193 |
| CompanyID در `miandore2` | 267 |
| CompanyID در `MarketPriceHistory` | 274 |
| `mahane` ∩ `miandore2` | 184 |
| `miandore2` ∩ MPH | 264 |
| `mahane` ∩ MPH | 190 |
| فقط در `mahane` | 9 |
| فقط در `miandore2` | 83 |
| `Symbol` → چند `CompanyID` | **1** مورد (کسرا) |
| `CompanyID` → چند `Symbol` | **3** مورد (سیمرغ/های وب/جم پیلن) |
| `InstrumentCode` → چند `CompanyID` | **1** مورد (4614779520007780) |
| `CompanyID` → چند `InstrumentCode` | همان ۳ مورد |

## پاسخ به سؤالات

### ۱) چند CompanyID به یک CompanyName؟ → **صفر**
`SELECT CompanyName, COUNT(DISTINCT CompanyID) ... HAVING >1` → خالی (هم raw و هم normalized). چون `CompanyID = md5(name)` قطعی است، هر نام دقیقاً یک ID می‌گیرد.

### ۲) چند CompanyName به یک CompanyID؟ → **همیشه ۱**
`MAX(COUNT(DISTINCT CompanyName)) = 1` در هر دو جدول. پس درون هر جدول نگاشت ۱:۱ است.

### ۳) آیا یک Symbol به چند CompanyID وصل شده؟ → **بله، ۱ مورد**
`کسرا` → دو CompanyID:
- `4ccc9664a47539eaff4b6b34fbfc0931` نام «کاتالیست‌های صنعتی آریا» (۳٬۶۴۳ ردیف، ۲۰۰۴..۲۰۲۶)
- `7e41b7fd7ba1c353199eba22667db254` نام `کسرا` (۱۷ ردیف، ۲۰۲۶/۰۷/۳۰..۰۹/۲۳)

**هر دو `InstrumentCode = 4614779520007780`.** این دقیقاً همان باگ identity است: یک ابزار واحد، دو CompanyID چون یکی با «نام کامل» و دیگری با «نماد» ساخته شده. (مسیر sync کدال نماد را می‌فرستد، مسیر legacy نام را.)

### ۴) آیا یک CompanyID به چند Symbol وصل شده؟ → **بله، ۳ مورد**
- `5d9142…` (سیمرغ): `سیمرغ`, `سیمرغ3`
- `62475be…` (های وب): `های وب`, `های وب3`
- `fa2e326…` (جم پیلن): `جم پیلن`, `جم پیلن2`, `جم پیلن3`
این‌ها نمادهای فرعی (حق تقدم/بازار موازی با پسوند عددی) هستند؛ هرکدام `InstrumentCode` جدا دارند.

### ۵) آیا CompanyName در طول تاریخ تغییر کرده؟
در DB نه — چون اگر تغییر می‌کرد، `CompanyID` جدید ساخته می‌شد و رکورد تکراری به‌وجود می‌آمد. تنها شاهد «تغییر نام عملی»، همان دوگانه‌ی «نماد ↔ نام کامل» (کسرا) است، نه تغییر زمانی در یک ID.

### ۶) آیا Symbol تغییر کرده؟
در سطح یک CompanyID بله (۳ مورد بالا). اصلی‌ترین الگو: نماد پایه + نمادهای فرعی.
بررسی `InstrumentCode → Symbol`: فقط ۱ ابزار که دو CompanyID دارد؛ بقیه ۱:۱.

### ۷) آیا InstrumentCode بهترین external identifier بازار است؟ → **بله (قوی‌ترین گزینه‌ی موجود)**
- مقدار آن = `item.get("id") or item.get("isin") or item.get("l18")` از BRS، عددی بزرگ (مثل `9956888831468521`) که با کنوانسیون «insCode» تسه‌مکو/TSETMC هم‌خوان است.
- برای ۲۷۴ شرکت، تقریباً همه دقیقاً ۱ InstrumentCode دارند (`icount=1`).
- یک‌به‌یک با نماد بازار است و به CompanyName وابسته نیست.
- ریسک: ۳ شرکت با نمادهای فرعی چند InstrumentCode دارند؛ برای هر «ابزار معاملاتی» یکتا است، نه لزوماً برای هر «شرکت». پس باید در سطح **security/instrument** نگه داشته شود، نه فقط company.

### ۸) آیا Codal شناسه‌ی publisher/company پایدار دارد؟ → **در feed: خیر**
فیلدهای واقعی پاسخ API (`search.codal.ir/api/search/v2/q`) عبارت‌اند از:
`SuperVision, TracingNo, Symbol, CompanyName, UnderSupervision, Title, LetterCode, SentDateTime, PublishDateTime, HasHtml, IsEstimate, Url, HasExcel, HasPdf, HasXbrl, HasAttachment, AttachmentUrl, PdfUrl, ExcelUrl, XbrlUrl, TedanUrl`.
هیچ `CompanyId`, `PublisherCode`, `ISIN` یا `CompanyCode` وجود ندارد. تنها شناسه‌های یکتا: `TracingNo` (گزارش) و `LetterSerial` (نامه، داخل URLها، base64).
fetch یک صفحه‌ی گزارش (`Decision.aspx`) هم در HTML سمت سرور هیچ `isin`/`CompanyId` نشان نداد (محتوا Angular و ناهمگام است).
→ **هیچ identifier رسمی شرکت در خروجی فعلی Codal قابل استخراج نیست** (احتمالاً در فایل XBRL هست ولی `HasXbrl=False` برای نمونه و دسترسی تأیید نشده → `UNKNOWN`).

### ۹) آیا `CodalReportId` به identifier شرکت وصل است؟ → **خیر**
`CodalReportId = TracingNo` = شناسه‌ی هر **گزارش**، نه شرکت. دو گزارش از یک شرکت، دو `TracingNo` دارند. اتصال به شرکت فقط از طریق `Symbol`/`CompanyName` است.

## نگاشت مفهومی فعلی (نمونه از CSV)
ستون‌های CSV: `current_company_id, company_name, symbol, instrument_code, brs_name, codal_ticker, has_monthly, has_financial, has_price, confidence, issues`.

| current_company_id | company_name | symbol | instrument_code | confidence | issues |
| --- | --- | --- | --- | --- | --- |
| `002c39…` | نان | نان | 8000351713789858 | HIGH | — |
| `5d9142…` | سیمرغ | سیمرغ | … | MEDIUM | multi_symbol(2) |
| `4ccc96…` / `7e41b7…` | آریا/کسرا | کسرا | 4614779520007780 | LOW | symbol collision, same instrument |
| `09029850…` | خبهن | (ندارد) | (ندارد) | LOW | no_symbol; no_financial; no_price |

توزیع confidence: **HIGH=268, MEDIUM=6, LOW=5**. توزیع issues: بدون مشکل=180، `no_monthly`=81، `no_financial`=7.

## چه چیزی identity را خراب می‌کند
1. `CompanyID = md5(name)` → وابسته به رشته؛ نماد vs نام کامل دو ID می‌سازد (شاهد: کسرا).
2. `Symbol` تنها کلید اتصال به Codal است و می‌تواند به چنده نهاد اشاره کند.
3. نمادهای فرعی (`...2/3`) باعث چند Symbol/InstrumentCode برای یک شرکت می‌شوند.
4. جدول `TrackedTickers` نماد-محور است (منبع seed: MPH 273، mahane 6، miandore2 3) و به CompanyID وصل نیست.
5. `FullPE` و بخشی از Go با `CompanyName` join می‌کنند.
6. `CodalReports` فقط `Ticker`(نماد) و `CompanyName` دارد، بدون شناسه‌ی شرکت.

## پیشنهاد Canonical Identity (برای ADR-001)
اسم شرکت **نباید** کلید باشد. الگوی پیشنهادی:

```
companies: id UUID PK  (internal, immutable)
  + display_name text
  + normalized_name text (unique, فقط برای lookup/جلوگیری از تکرار)

securities / instruments: id UUID PK
  + company_id UUID FK
  + isin / tsetmc_ins_code (InstrumentCode) UNIQUE   ← external identifier بازار
  + codal_symbol (Symbol)   UNIQUE-ish
  + brs_name text
  + security_type (base / right / ...) + is_active
```

- **External identifiers:** `tsetmc_ins_code` (InstrumentCode از BRS) به‌عنوان شناسه‌ی پایدار بازار؛ `codal_symbol` برای اتصال به Codal؛ `ISIN` در صورت دسترس بودن.
- **Codal publisher id:** در دسترس نیست؛ به‌جایش اتصال از طریق `codal_symbol`.
- اتصال داده‌ی فعلی: مهاجرت `CompanyID → companies.id` باید دوگانه‌ی نماد/نام را (مثل کسرا) با `InstrumentCode` یکسان ادغام کند.
