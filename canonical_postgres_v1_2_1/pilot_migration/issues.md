# Pilot Issues

هیچ issue با severity HIGH رخ نداد. موارد زیر به‌عنوان محدودیت/مشاهده ثبت می‌شوند.

| # | severity | area | مشاهده | root cause | اثر | اقدام پیشنهادی |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LOW | financial | ۱ fact از ۲۱۱۰ با اختلاف `~3e-7` بین مقدار تبدیل‌شده و canonical | `canonical_value numeric(30,6)` در برابر منبع `FLOAT(53)` گرد می‌کند | ناچیز (زیر ۱ میکرو ریال) | یا پذیرش tolerance 1e-6 (مستند) یا افزایش مقیاس (مثلاً `numeric(38,12)`) در نسخه‌ی بعد |
| 2 | LOW (by design) | scope | `--all` (full migration) پیاده‌سازی نشده | ابزار عمداً فقط sample-file می‌پذیرد | none | افزودن full mode فقط با `--all --i-understand-full-migration` در مرحله‌ی prod |
| 3 | LOW (by design) | provenance | `raw.report_payloads` خالی است | RAW payload واقعی برای داده‌ی legacy موجود نیست | provenance فقط در سطح report_version/parse_run | ثبت limitation (همین‌جا)؛ در صورت استخراج از کدال پر می‌شود |
| 4 | LOW (by design) | registry | بیشتر mahane/miandore2 به report سنتزی `source='legacy_sqlserver'` وصل‌اند، نه به CodalReports | نگاشت دوره‌ی legacy به TracingNo کدال موجود نیست | دو مسیر report (codal و legacy) هم‌پوشان نیستند | cross-link در مرحله‌ی parity/prod migration |
| 5 | INFO | valuation | FullPE migrate نشد | طبق design v1.2.1 canonical نیست | none | P/E در analytics از price+fundamentals محاسبه می‌شود |
| 6 | INFO | scope | Users/Family/portfolio/auth/StockData/StockPrices/miandore/statements migrate نشدند | خارج از دامنه‌ی این pilot (item 22) | none | مرحله‌ی بعد |

## Validations با نتیجه‌ی صفر (بدون issue)
- identity: duplicate ins=0، kastra convergence=1، name-only identity=0
- row counts: همه‌ی اختلاف‌ها = 0 (شامل price dedup)
- monthly: 594/594 مطابق
- financial: 2110/2110 در tolerance (۱ ردیف گردشده)
- market: 160/160 نمونه دقیق
- date: 27189/27189
- unit: canonical != rial/rial_per_share = 0
- orphan/duplicate: همه 0
- idempotency: بدون تغییر
- rollback: PASS
