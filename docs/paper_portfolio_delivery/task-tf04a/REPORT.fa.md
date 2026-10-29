# گزارش تکمیل TF-04A — اصلاح تشخیص و تعیین کسری داده

**تشخیص و بستهٔ TF-04A تکمیل شد؛ آمادگی تصمیم حساب همچنان BLOCKED / UNKNOWN است.** این کار صرفاً ابزار تشخیص، آزمون‌ها و برنامهٔ داده را اصلاح کرد. موتور، ranking/panel اصلی، حساب، وضعیت `PREPARATION_UNCONFIRMED`، دفتر رسمی، O00 و scheduler تغییر نکردند؛ هیچ درخواست شبکه‌ای انجام نشد.

## نتیجهٔ جداگانه

| بُعد | نتیجه |
|---|---|
| محاسبات P1/P3 و validator قفل‌شده | PASS برای هر دو snapshot؛ 254 ردیف و تطبیق 254 شناسه/نماد با universe ثابت |
| تاریخ‌های manifest | کنترل تاریخ now timezone-aware و دامنه‌دار است. اختلاف max آرشیو با max ردیف منتخب به‌تنهایی خطا نیست؛ تاریخ metadata ثابت/نامنطبق v12-37 همچنان آشکار و مسدودکننده است. |
| receipt و freshness برای تصمیم تازه | receipt مالی منتخب اثبات نشده؛ freshness/کیفیت public مصوب نیست و UNKNOWN می‌ماند. seal مشاهده فقط وجود bytes را در زمان مشاهده ثابت می‌کند. |
| حساب/تصمیم کاغذی تازه | BLOCKED؛ خروجی ابزار مجوز تصمیم صادر نمی‌کند. |
| آغاز واقعی TF-04B | بستهٔ شروع می‌تواند به علت پوشش اطلاعیهٔ 254 هویت و ranking آماده‌نشده BLOCKED بماند؛ در این مأموریت شروع نشد. |

## مقایسهٔ دو snapshot

| snapshot | SHA-256 فایل ranking | canonical | ارزیابی / شمارش | `share_matches` | تشخیص manifest |
|---|---|---|---|---:|---|
| v12-36 پین‌شده | `629cf6b9a123df4bdaa25751384bd270a84463f04b79d98fe0cf35f1743a6421` | `25fd2cdd20ee50bb4aca0d7baafd4984287da7b63568ba2ba86c93158a2b2224` | 2026-10-21؛ P1=166/254، P3=225/254؛ validator PASS | 245 | آمار آرشیو/hash و تاریخ ارزیابی درست؛ dataset_id متفاوت. دو cutoff در Tehran دو سوی مرز پایان/شروع روزند و فقط 1 میکروثانیه فاصله دارند. |
| v12-37 آخرین cycle بررسی‌شده | `18485acf24389e5de07e56b7258b0306b03f5fb4cdd93976da346065b4571f67` | `651a0dde9cf06f5967090b55f44607df156c82b689430c905ce870647da6a0ef` | 2026-10-24؛ P1=166/254، P3=225/254؛ validator PASS | 253 | metadata extraction به v12-35/2026-10-21 و قیمت تا 2026-10-21 اشاره می‌کند، درحالی‌که ranking/panel تا 2026-10-24 است. |

گزارش قبلیِ دقیق، پیش از به‌روزرسانی در [نسخهٔ تاریخی گزارش](finish-20261025/REPORT.pre-finish.fa.md) حفظ شده است. خروجی نهایی ابزار: [آمادگی v12-36](finish-20261025/evidence/accept-v12-36/readiness.json) و [آمادگی v12-37](finish-20261025/evidence/accept-v12-37/readiness.json)؛ validation و observed seal کنار هرکدام قرار دارد. Seal زمان واقعی اجرا را دارد و ادعای دریافت تاریخی یا نبود اطلاعیهٔ تازه نیست.

## اصلاحات ابزار و آزمون

- مقایسهٔ max انتشارِ کل `input_reports` با max ردیف‌های منتخب حذف شد. اکنون hash و آمار آرشیو با فایل واقعی سنجیده می‌شود و lineage منتخب جداگانه نسبت به cutoff بررسی می‌گردد. برابری offsetهای زمانی معادل لحاظ می‌شود؛ دو نمایش cutoff در v12-36 که 1µs در مرز دو روز Tehran فاصله دارند false failure نمی‌شود؛ metadata واقعاً نامنطبق v12-37 و انتشار منتخب پس از cutoff رد می‌شود.
- منبع metadata ثابت ثبت شده است: v12-37 implementation از builder v12-35 استفاده می‌کند؛ [کد v12-37](../../../ranking_research/future_eval_v12_30/build_latest_supported_v12_37_impl.py) و [نوشتن metadata ثابت در v12-35](../../../ranking_research/future_eval_v12_30/build_latest_supported_v12_35.py) نشان می‌دهند `dataset_id`, `evaluation_date`, cutoff و بخشی از source dates ثابت نوشته می‌شوند. اصلاح این رفتار، تغییر مشخصِ یک اجرای محصول آینده است و در TF-04A انجام نشد.
- برای غاذر، هر دو panel گزارش منتخب P1 را با `tracing_no=1569119`، دورهٔ 2026-06-21، انتشار 2026-07-16 و SHA `c73966dabfb7c9faf7cefb862938666c20417766081245bada7cd9b922d56667` به همان فایل raw در `provenance_v1/output/exp_2k13_codal/raw/غاذر_1569119.html` متصل می‌کنند؛ hash فایل با lineage تطبیق دارد. نوع سند در lineage ثبت نشده و `observed_at` زمان مشاهدهٔ محلی است، نه receipt منبع.
- تفاوت max منتخب v12-36 توضیح دارد اما body آن کامل اثبات نشده: ردیف `تپمپی`/`1608939` در `financial_lineage` با source=`verified_current_cache` و انتشار 2026-10-11 آمده است. ورودی cache فعلی metadata این گزارش را دارد، اما فقط `invalid_response_evidence` از CAPTCHA و بدون `body_evidence` دارد. بنابراین max منتخب از cache-lineage می‌آید، نه از max آرشیو 2026-10-04؛ محتوای گزارش و receipt تاریخی آن همچنان UNKNOWN است. جزئیات و hashها در [lineage نمونه‌ها](finish-20261025/evidence/selected-report-lineage.json) هستند.
- max منتخب v12-37 نیز به‌طور محدود ردیابی شد: ردیف `تاصیکو`/`1601930`, period 2026-08-22, published_at `2026-09-21T23:50:46+03:30` (`20:20:46Z`) با بیشینهٔ timezone-aware ردیف‌ها برابر است. رکورد metadata در `input_reports.json` با `history_basis=reconstructed_publication_history`, source URL و digest ثبت‌شده وجود دارد؛ اما در cache فعلی و raw همان cycle body مربوط پیدا نشد و receipt/body-hash اتصال‌پذیر نداریم. پس اختلاف max آرشیو (2026-10-04) و max منتخب (2026-09-21) به‌تنهایی خرابی نیست، ولی provenance محتوای این عامل خاص UNKNOWN می‌ماند.
- ابزار تعداد/یکتایی را از تطبیق `(company_id, symbol)` با universe منجمد جدا کرده است. پس از اجرای موفق validator، ranking تغییر‌یافته در تطبیق هویت PASS نمی‌گیرد؛ با validator ردشده، وضعیت NOT_VERIFIED است. قانون پوشش به‌صورت reference از نتیجهٔ تأیید آن جدا شده و در validator اجرا‌نشده/ناموفق PASS صادر نمی‌کند.
- خروجی واقعی ابزار زمان مشاهدهٔ UTC، syntax/timezone timestamp، منشأ receipt، ترتیب نسبت به observation و ــ اگر داده شود ــ تصمیم فرضی را جدا ثبت می‌کند. `financial_lineage.received_at` بدون زنجیرهٔ receipt hash-bound پذیرفته نمی‌شود؛ به‌ویژه alias احتمالی `observed_at` receipt معتبر تلقی نمی‌شود. timestamp بازار به hash فایل `registration.json` و manifest بستهٔ بازار وصل شده است. نبود ساعت تصمیم صریحاً `NOT_CHECKED_NO_DECISION_TIME` می‌دهد.
- پنل دستکاری‌شده از خود مسیر assess/validator آزمایش شد؛ calculation معتبر گزارش نشد و هویت/قانون در وضعیت تأییدنشده ماند. خروجی مقصد غیرخالی نیز همچنان رد می‌شود.
- regressionهای هدفمند TF-04A در اجرای focused **14 passed** شدند. اجرای پذیرش نهایی، هفت فایل suite قبلی به‌اضافهٔ این regressionها، **185 passed، 0 failed در 551.61s** شد؛ command کامل و basetemp یکتا در [test-run](finish-20261025/evidence/test-run.json) است. دامنهٔ crash/concurrency همان آزمون‌های قبلی است: writer اتمیک در write/pre-replace/post-replace؛ recovery از child fill واقعی پس از replace و جلوگیری از debit دوباره؛ دو writer هم‌زمان در read-modify-write و دو fill CLI هم‌زمان. تزریق crash به wrapper انجام نشده است.

## کسری دادهٔ همان cycle و قابلیت استفادهٔ مجدد

دامنه فقط cycle با شناسهٔ `paper-cycle-20261024T190004112005Z-d1278aa0` است. [جدول کسری/هم‌پوشانی](finish-20261025/evidence/cycle-data-gaps.json) capture manifest، identity checks، SHA/زمان cache فعلی و SHA rawهای cycle را جدا ثبت می‌کند. cacheها در manifest چرخه با hash پین نشده‌اند؛ پس hash فعلی را به‌جای hash تاریخی عرضه نکرده‌ام.

| feed | شاهد ثبت‌شدهٔ همان run | cache و هم‌پوشانی شناسه‌ها | اقدام مجاز بعدی |
|---|---|---|---|
| مالی، LetterType=6 | run=`partial`؛ توقف `codal_captcha_page` در مرحلهٔ body با HTTP 200؛ 258 صفحهٔ قبلی اما صفر صفحهٔ تازه، صفر هویت تازه بررسی‌شده و 254 هویت در این run unchecked؛ pagination ناقص. | cache فعلی 826 شناسه دارد؛ 73 دارای body evidence: 57 شناسه با raw bodyهای همین cycle و 16 شناسهٔ دیگر که capture آن‌ها را reuse کرد. 810 مورد «ناقص/نامعتبر» برابر 269 فاقد body و 541 پاسخ quarantine‌شده در شمارش مرحله‌ای capture است، نه جمعیت‌های مستقل. 70 retry به شناسه‌های دارای خطای body مربوط است؛ شمار 541 پاسخ نامعتبر با 484 شناسهٔ یکتا یکسان نیست. | 57 raw ثبت‌شده را با hash و parser محلی replay کن؛ 16 body cache معتبر را با کنترل hash دوباره مصرف کن. body مفقود/نامعتبر فقط پس از فهرست‌کردن tracing_noهای لازم، جداگانه درخواست شود. CAPTCHA متوقف‌کننده است. |
| فروش، LetterType=58 | `partial` و `HTTP_429_READ_ONLY_RETRY_EXHAUSTED`; دو تلاش در سقف retry موجود، صفر صفحهٔ تازه، 254 هویت unchecked و pagination ناقص. | cache فعلی 64 شناسه: 11 body معتبر قابل reuse و 53 نامعتبر؛ هم‌پوشانی rawهای cycle صفر است، که با صفر body تازه سازگار است. `missing=0` در شمارش capture به معنای معتبر بودن 53 بدنه نیست. | 11 body معتبر را replay کن؛ metadata/بدنهٔ 53 مورد quarantine را به‌عنوان محتوای معتبر مصرف نکن. پس از زمان مجاز retry و یک نوبت محدود، در 429 توقف کن. |

یک 200 ممکن است صفحهٔ CAPTCHA یا بدنهٔ خطا باشد؛ status code به‌تنهایی اعتبار body نیست. `archive_reuse` شمارنده‌های مراحل مختلف‌اند و نباید کورکورانه جمع شوند. فهرست IDها در raw/cache برای مالی، 57 شناسهٔ مشترک بین raw همین cycle و body evidence فعلی، به‌علاوهٔ 16 body evidence خارج از raw همین cycle را نشان می‌دهد؛ cache فروش 11 body معتبر دارد و raw تازه ندارد. هیچ‌یک از این موارد به تنهایی جامعیت عدم انتشار برای کل universe را ثابت نمی‌کند.

پوشش تازهٔ هر 254 هویت هنوز برای ادعای ranking تازه لازم است: دادهٔ متفاوت هر شرکت می‌تواند رتبه را عوض کند و قواعد جاری بر کل universe ثابت اجرا می‌شوند. بااین‌حال تعداد درخواست را نمی‌توان 508+508 «حداقل لازم» نامید: صفحات `Total`، watermark هر شناسه، bodyهای معتبر قابل reuse و pagination تعداد واقعی را تعیین می‌کنند. تازه‌کردن غاذر به تنهایی ادعای ranking تازهٔ بازار نیست.

## پلن محدود TF-04B

1. یک cycle نو با مقصد ایزوله بساز؛ manifest نهایی را از همان dataset/evaluation/cutoff، panel SHA و ranking snapshot تولید کن. منشأ ثابت metadata در builder v12-35 را در یک تغییر محصول مجزا اصلاح کن؛ ranking تاریخی را دستکاری نکن.
2. پیش از شبکه، hash و اعتبار 57 body مالیِ raw cycle، 16 body مالی دیگرِ موجود، و 11 body فروش معتبر را بررسی و با `tracing_no` به reports منتخب/عامل‌های مصرفی وصل کن. rawهای `1608939` که CAPTCHA هستند و bodyهای فروش quarantine‌شده وارد محاسبه نشوند.
3. سپس فقط watermarkهای بدون پوشش کافی را بررسی کن. endpoint Codal موجود `search.codal.ir/api/search/v2/q` را با LetterType 6 و 58، نماد/شناسهٔ frozen، `from_date` watermark منهای 7 روز (بدون watermark: پنجرهٔ 365 روزهٔ collector) و صفحه‌بندی طبق `Total` به‌کار ببر. اگر هدف، نبود گزارش جدید برای کل universe است، بررسی نمادهای باقی‌مانده لازم است؛ تعداد صفحات از پاسخ واقعی می‌آید. collector توقف CAPTCHA/429 و retry محدودِ موجود را حفظ کند.
4. بازار را فقط برای freshness تصمیم جدید ارزیابی کن: بستهٔ روزانه و share-change موجود در TSETMC طبق identity و تاریخ مؤثر بررسی شود؛ اگر دادهٔ جاری لازم بود، endpointهای موجود daily و share changes برای identityهای فاقد مدرک درخواست شوند. raw و manifest hash-bound بمانند؛ تاریخچهٔ کامل را بی‌دلیل بازدریافت نکن.
5. بعد از هر feed، نتیجه را با body validation، صفحه‌بندی، هویت‌های checked/unchecked و کیفیت/اقدامات شرکتی جمع‌بندی کن. آستانهٔ freshness/کیفیت مصوب نیست؛ پیشنهاد بررسی به مالک: age قیمت و مالی، پوشش اعلان‌ها و کیفیت تعدیل را جداگانه تصویب کند. هیچ حدی در scorer/قرارداد/این ابزار اضافه نشود.

جزئیات endpoint، سقف تلاش و شرایط توقف در [پلن اجرایی TF-04B](finish-20261025/TF-04B-PLAN.fa.md) آمده است. این پلن اجرا نشده؛ هیچ live fetch، preview، fill یا فعال‌سازی انجام نشد.

## حفاظت و فایل‌های تحویل

hash پیش/پس همان مسیرهای محافظت‌شده در [ممیزی نهایی](finish-20261025/evidence/protected-path-hashes.json) ثبت شده است. تغییرات هم‌زمان UI، ingestion و `.gitignore` حفظ شده‌اند. [manifest نهایی فایل‌ها](finish-20261025/manifest.json) اندازه و SHA همهٔ سورس/آزمون/گزارش/شواهد این تکمیل را دارد و hash خودش را فهرست نمی‌کند.
