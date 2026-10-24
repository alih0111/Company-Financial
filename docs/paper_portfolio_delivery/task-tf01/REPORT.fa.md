# گزارش تحویل TF-01 — جمع‌آورنده و ارزیاب تقویم عمومی بدون توکن

تاریخ: 2026-10-23 · مخزن: `D:/RFA/Company-Financial` · سرشاخه: `9d02afc65576576540cf8ac077b43e9e85fe93a0` (پایان کار بدون تغییر working tree موجود)

دامنهٔ این تحویل **فقط TF-01** است: یک جمع‌آورنده/ارزیاب تقویم مبتنی بر شواهد عمومی، بدون هیچ درخواست احراز هویت‌شده. TF-02 (adapter مشترک) و TF-03 (اجرای آزمایشی) شروع نشده‌اند. این گزارش PASS را فقط برای تکمیل TF-01 ثبت می‌کند؛ نه مجوز اجرای خرید، نه گواه کامل‌بودن تقویم رسمی، نه آمادگی O00.

## ۱. فرمان‌های واقعی اجراشده

| فرمان | نتیجه |
|---|---|
| `.venv\Scripts\python.exe -m pytest ranking_research\tests\test_public_market_calendar.py -v --basetemp=D:\RFA\_tmp_tf01\pytest` | **۱۳ passed, 0 failed** |
| `.venv\Scripts\python.exe -m pytest ranking_research\tests\test_paper_account_atomic.py ranking_research\tests\test_paper_cycle_http.py -q` | **۵۹ passed** (بدون regression) |
| `.venv\Scripts\python.exe ranking_research\future_eval_v12_30\acquire_public_market_calendar.py --window-start 20261022` (اجرای اول) | quality=CONFLICT — نقص دامنهٔ مقایسه؛ رفع شد (بند ۷) |
| همان فرمان (اجرای دوم، نهایی) | `manifest.20261023T182831259743Z.json` · sha256=`a788836f31a38d43a5b56ce2ec608e7dfefe196dfa4bc8b3ff97282e373e576a` · **CORROBORATED_PUBLIC** |
| `... --window-start 20261022 --from-manifest ranking_research\output\public_market_calendar_tf01\manifest.20261023T182831259743Z.json` | `manifest.20261023T182911289428Z.json` · sha256=`c47587a2001dfef2f611f56ba610782b1c00c6be1a631e3e305bfb7fed56ba60` · بازپخش offline، `session_dates_equal=true` |

آزمون‌ها شبکهٔ زنده ندارند؛ همهٔ fixtureها مصنوعی‌اند. هیچ توکنی خوانده، چاپ یا ذخیره نشد (آزمون ۱۲ متغیر `TSETMC_READONLY_BEARER_TOKEN` را حذف و نبود هر درخواست `api.tsetmc.com`/`NSCStart` را اثبات می‌کند).

## ۲. پوشش ۱۳ آزمون (نگاشت به ۱۲ رفتار الزامی پلن)

1. توافق دو شاخص + تکمیل معتبر → مجموعهٔ مرتب یکتا با کیفیت `CORROBORATED_PUBLIC` (آزمون ۱)
2. نبود ردیف نامزد با حضور جلسه در شاخص‌ها → روز بازار حفظ می‌شود (آزمون ۲)
3. نبود ردیف همهٔ منابع → `NO_POSITIVE_EVIDENCE`، نه تعطیلی قطعی (آزمون ۳)
4. تاریخ تنها در یکی از شاخص‌ها یا شاهد معاملهٔ سهم خارج از تقویم → `CONFLICT` بدون پنهان‌کاری؛ تفاوت شروع تاریخچهٔ پیش از پنجره فقط «تفاوت بازه» ثبت می‌شود (آزمون ۴)
5. نامزد فرابورسی با تقویم بورس یا نماد غیرسهام → `MARKET_SCOPE_MISMATCH` / `MARKET_SCOPE_UNCLASSIFIED` (آزمون ۵)
6. آخرهفته با دریافت تازه و آخرین تاریخ یکسان → `NO_NEW_SESSION` بدون جلسهٔ ساختگی (آزمون ۶)
7. watermark عقب‌تر از تاریخ شاخص یا نامعتبر → `COMPLETION_UNVERIFIED` و تاریخ تأییدنشده مجوز اجرا نمی‌گیرد (آزمون ۷)
8. خطای شبکه/پاسخ خالی/HTML با ۲۰۰/JSON نامعتبر/هش raw متفاوت → خطای دقیق، بدون موفقیت کاذب (آزمون ۸)
9. تاریخ نامعتبر/آینده، رکورد تکراری متعارض، شناسهٔ اشتباه، ناهم‌خوانی نام شاخص → رد؛ تکرار کاملاً یکسان dedupe می‌شود (آزمون ۹)
10. تغییر ترتیب ردیف‌ها، rerun و مرز نیمه‌شب تهران (۲۰:۳۰ UTC) → خروجی پایدار (آزمون ۱۰)
11. پنجرهٔ تصمیم خارج از پوشش → `INSUFFICIENT_COVERAGE` با `session_count=null` نه صفر (آزمون ۱۱)
12. بدون متغیر توکن کار می‌کند و هیچ درخواست NSCStart ساخته نمی‌شود (آزمون ۱۲)
13. بازپخش offline از manifest ذخیره‌شده: session/quality/watermark برابر؛ دست‌کاری raw → `RAW_HASH_MISMATCH` (آزمون ۱۳)

## ۳. جدول قابلیت/محدودیت منابع

| منبع (همه عمومی، بدون Authorization) | قابلیت | محدودیت |
|---|---|---|
| `cdn.tsetmc.com/api/Index/GetIndexB2History/32097828799138957` | تاریخچهٔ شاخص کل: ۴٬۳۱۱ تاریخ یکتا، 20081204 تا 20261021 | فقط تاریخ‌های همان شاخص؛ گواه کامل‌بودن جلسات بازار نیست |
| `cdn.tsetmc.com/api/Index/GetIndexB2History/67130298613737946` | تاریخچهٔ شاخص کل (هم‌وزن): ۳٬۰۳۲ تاریخ یکتا از 20140319 | شروع دیرتر؛ پیش از 2014 قابل تطبیق نیست (تفاوت بازه ثبت شد) |
| `cdn.tsetmc.com/api/Index/GetIndexB1LastAll/All/1` | تطبیق هویت هر دو شناسه با نام فارسی (۲/۲ تطبیق) | `dEven=0` در پاسخ؛ فقط برای هویت استفاده شد؛ شمول غیرTSE اثبات نشده |
| `service.tsetmc.com/.../LastPossibleDeven` | پاسخ `20261021;20261021` → watermark تکمیل 20261021 | معنای تک‌تک اجزا مستند رسمی نیست؛ فقط توافق اجزا استفاده شد |
| `cdn.tsetmc.com/api/Instrument/GetInstrumentInfo/{ins}` | هویت نامزد: غاذر، `flow=1`، `flowTitle=بازار بورس`، «بازار دوم (تابلوی فرعی) بورس» | — |
| آرشیو محلی `official_tsetmc_20261022` (cross-check) | ۲۵۴ نماد با هش raw تک‌تک تأییدشده، بدون اتصال به DB | snapshot تا 2026-10-21؛ فقط نمادهای جهانِ فریز ۲۵۴؛ ردیف حجم صفر نه جلسه را اثبات می‌کند نه توقف را |

## ۴. نتیجهٔ ارزیابی زندهٔ نهایی

- **بازار نامزد:** غاذر (کشت‌وصنعت‌پیاذر، insCode `35158826900216508`) از evidence خام InstrumentInfo → بورس تهران (TSE)؛ با پروفایل تقویم TSE هم‌خوان.
- **تطبیق دو شاخص در پنجرهٔ تصمیم (≥ 20261022):** صفر اختلاف. در کل بازه، ۱٬۲۷۹ تاریخ پیش از 2014 فقط در شاخص اصلی است → به‌عنوان «تفاوت شروع تاریخچه» ثبت شد، نه conflict (اصلاح اجرای اول، بند ۷).
- **Cross-check آرشیو سهام (پنجره 20260823 به بعد):** ۲۵۴ نماد، صفر skipped؛ **همهٔ تاریخ‌های معاملهٔ مثبت داخل مجموعهٔ جلسات دو شاخص؛ صفر شاهد خارج از تقویم.**
- **آخرین جلسهٔ مشاهده‌شده:** 20261021 (چهارشنبه). **پوشش:** 20081204 تا 20261021 (حد مشاهده، نه گواه پیوستگی).
- **وضعیت تکمیل:** `COMPLETION_CORROBORATED_THROUGH_WATERMARK` با watermark=20261021 (اجزای LastPossibleDeven موافق‌اند).
- **جلسه پس از تصمیم:** `NO_NEW_SESSION` — انتظاری و مشروع: تصمیم پنجشنبه 2026-10-22 ثبت شده، آخرین جلسهٔ کامل‌شده 2026-10-21 است و جلسهٔ شنبه 2026-10-24 هنوز برگزار نشده. این وضعیت نه شکست پیاده‌سازی است و نه مجوز fill.
- **بازپخش offline:** با همان ورودی و همان ساعت مرجع، session set و کیفیت و watermark عیناً برابر (`session_dates_equal=true`, `quality_equal=true`, `watermark_equal=true`).

## ۵. چه چیزی فرض سیاست است و چه چیزی از raw قابل اثبات

**قابل اثبات از پاسخ‌های خام (هش‌شده):** تاریخ‌های دو شاخص و توافق/اختلاف آن‌ها؛ پاسخ `20261021;20261021`؛ هویت دو شاخص از فهرست شاخص‌ها؛ هویت و بازار غاذر (`flow`/`flowTitle`/`cgrValCotTitle`)؛ تاریخ‌های حجم مثبت ۲۵۴ نماد و داخل‌بودن همه در جلسات؛ زمان دریافت هر منبع.

**فرض سیاست (ثبت‌شده در `manifest.policy`، قابل تغییر با ورودی، مبنای نتیجه‌گیری نیست):** نگاشت `flowTitle→بازار` (بازار بورس=TSE، بازار فرابورس=IFB)؛ پیشوندهای «بازار اول/دوم» به‌عنوان تابلوی سهام عادی؛ پنجرهٔ cross-check با lookback پیش‌فرض ۶۰ روز؛ قاعدهٔ «توافق دو جزء watermark»؛ پنجشنبه/جمعه فقط هشدار و هرگز تولید جلسه؛ رد تاریخ‌های پس از روز محلی تهران؛ و `completeness_certified=false`: دو شاخص از یک تأمین‌کننده مستقل نیستند و توافقشان گواه نمی‌شود که هیچ جلسه‌ای از همهٔ منابع مشترک جا نیفتاده است.

## ۶. سه پرچم تحویل (هش قبل = هش بعد)

| پرچم | مقدار | شاهد |
|---|---|---|
| `existing_account_modified` | **false** | `client/public/research/v12-36/paper-portfolio.json` → `7c6fa7f17f51fc93c8d3d439acfa52fbbbcc0b400653f585383f5201f0bb21b3` (قبل = بعد) |
| `official_ledger_modified` | **false** | `execution_rules_v1_2_0.json` → `ab31c9275fcdc96f787b91de1c8ec314cf32fedb5b6249aa17911bad90ec5646` و `future_evaluation_contract.locked.json` → `8b08cace7b64ee135ac862b6b9afd02242ba91cec24f8d6134b1d9b6c623c1c8` (قبل = بعد) |
| `model_contract_changed` | **false** | قرارداد قفل‌شدهٔ `future-evaluation-v12.28-p1-p3-o00-g0` با همان هش `8b08cace...` دست‌نخورده؛ هیچ artifact رتبه‌بندی تغییری نکرد |

فایل حساب فقط **خوانده** شد (برای نماد نامزد)؛ نوشتنی صورت نگرفت. DB، scheduler، دفتر رسمی و شواهد پلن (`docs/paper_portfolio_delivery/token-free-plan/evidence/`) دست‌نخورده‌اند.

## ۷. رویداد اجرای اول (شفافیت)

اجرای زندهٔ اول (`manifest.20261023T182304705548Z.json`) `quality=CONFLICT` با ۱٬۲۷۹ conflict داد، چون مقایسهٔ دو شاخص روی **کل تاریخچه** انجام می‌شد و شروع دیرترِ شاخص هم‌وزن (2014) به‌عنوان اختلاف تفسیر می‌شد. اصلاح: مقایسه مطابق سیاست ۳ پلن به «پنجرهٔ تصمیم تا آخرین روز تکمیل‌شده» محدود و تفاوت‌های پیش از پنجره به‌صورت «تفاوت بازه» ثبت شدند؛ پنجرهٔ cross-check سهام نیز به lookback ۶۰روزهٔ صریح تبدیل شد. هر دو manifest نگه داشته شدند و آزمون ۴ این رفتار را قفل کرده است. خروجی live و fixture هرگز مخلوط نشدند.

## ۸. فایل‌های تحویل (اندازه/SHA-256 در `result.json`)

- سورس: `ranking_research/future_eval_v12_30/acquire_public_market_calendar.py` — جمع‌آورنده (۵ GET عمومی با retry محدود، raw تغییرناپذیر با نام یکتا) + ارزیاب خالص (بدون I/O در import) + حالت offline با تأیید هش.
- آزمون: `ranking_research/tests/test_public_market_calendar.py` — ۱۳ آزمون fixture محور.
- Evidence: کپی دو manifest (زنده و بازپخش offline) در `evidence/`؛ rawهای gzip در `ranking_research/output/public_market_calendar_tf01/raw/` (پنج فایل برای هر اجرا؛ هش بر مبنای بایت‌های **غیرفشرده**).
- `result.json` — فهرست کامل فایل‌ها با اندازه و SHA-256، خلاصهٔ اجراها و سه پرچم.

## ۹. توقف

TF-01 اینجا متوقف می‌شود. adapter مشترک (TF-02)، اتصال به مصرف‌کنندگان (`apply_paper_fill`/`refresh_paper_decision_status`/`build_codal_factor_inputs`/`paper_cycle`)، پذیرش در حساب عملیاتی و بازنویسی مسیر فروش، همه به بازبینی این تحویل و تصمیم صریح موکول شده‌اند. فایل خروجی این ماژول عمداً `nscstart_compatible=false` دارد و source آن در `apply_paper_fill` پذیرفته نمی‌شود — اتصال، کار TF-02 است.
