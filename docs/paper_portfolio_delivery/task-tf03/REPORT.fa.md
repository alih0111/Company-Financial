# TF-03 — گزارش تکمیل

نتیجهٔ کل: **PARTIAL**. چرخهٔ آزمایشی آفلاین کامل و PASS است؛ شاخهٔ سفارشِ wrapper در `paper_cycle.main` نیز روی مسیرهای temp اجرا و PASS شد. پیش‌نمایش سفارش واقعی اجرا نشد و آمادگی فعال‌سازی BLOCKED است. حساب اصلی، قواعد اصلی، دفتر رسمی و scheduler دست‌نخورده‌اند.

## چرخهٔ مصنوعی آفلاین — PASS

Harness بازاجراشدنی `run_offline_lifecycle.py` همهٔ entrypointها را با subprocess واقعی اجرا می‌کند و برای Python childها socket connect/create_connection را مسدود می‌کند. دادهٔ تقویم و قیمت کاملاً مصنوعی‌اند؛ هیچ تابع fill، writer یا resolverای mock نشده است. ورودی‌های بی‌ربط ranker، Codal، دریافت تمام ۲۵۴ نماد و NSCStart اصلاً اجرا نشدند.

مسیر سالم: حساب خالی → `register_paper_decision.py --calendar-provider public` با ranking pinشده و clock صریح fixture → preview → apply یک fill → mark روز بعد از `check_paper_account.py --mark-to-market` → replay همان receipt با `--apply-fill` پیش و پس از mark. binding عمومی در همان ثبت تصمیم در چهار سطح account/decision/order/rules ایجاد شد. ساعت UTC و تاریخ تهران از همان instant ساخته شدند. Preview و هر دو replay، hash bytes حساب را ثابت گذاشتند؛ یک fill event ثبت شد، receipt پس از mark ثابت ماند و mark به عقب برنگشت.

محاسبهٔ مستقل از موتور، با `Decimal` و `ROUND_HALF_UP`: ۱۰۰٬۰۰۰ تومان و ۱۲۳۴ ریال → ۸۰۶ سهم، gross=۹۹٬۴۶۰، fee=۴۹۷، نقد=۴۳، NAV=۹۹٬۵۰۳ و P&L=-۴۹۷. Mark روز بعد در ۱۲۴۰ ریال → ارزش دارایی=۹۹٬۹۴۴، NAV=۹۹٬۹۸۷ و P&L=-۱۳؛ receipt خرید ثابت ماند.

شش شاخهٔ preview subprocess نیز حساب را بدون تغییر نگه داشتند: نبود bar جلسهٔ اول با وجود bar روز بعد، انقضا پس از سه جلسه با شواهد کافی، ابهام دیررس، `NO_NEW_SESSION`، کیفیت نامعتبر و provider ناسازگار. در دو مورد آخر، علت دقیق تا exit نهایی حفظ شد؛ شمار جلسهٔ نامعلوم به صفر تبدیل نشد. چهار outcome محصول و چندین سناریوی خطا در suite قبلی هم مجدداً اجرا شدند.

## اتصال cycle/wrapper — PASS محدود

`paper_cycle.main --order-review-only --calendar-provider public`، wrapper واقعی `check_paper_order.ps1`، preview واقعی `apply_paper_fill.py` و refresh status را با همان account/rules/evidence/calendar/hash و مقصدهای temp اجرا کرد. Exit=0، public calendar آماده و حساب قبل/بعد یکسان بود. این شاخه ranker/Codal/O00 را اجرا نمی‌کند و ادعای اجرای کل `paper_cycle.main` نیست. public بدون token و بدون prompt رفت؛ wrapper فقط شاخهٔ NSCStart را در provider برابر `nscstart` وارد می‌کند. Apply در شاخهٔ cycle فقط با `--apply-fill` صریح انتخاب می‌شود.

مسیرهای account/rules ورودی register، apply، mark و refresh اکنون انتخاب‌پذیرند؛ قفل حساب پس از resolve مسیر همان حساب گرفته می‌شود. `paper_cycle.main` شاخهٔ order-only مسیرهای ورودی/خروجی را تا wrapper منتقل می‌کند و فایل lock و گزارش cycle هم در output منتخب ساخته می‌شوند. حالت legacy با مقادیر پیش‌فرض خود حفظ شده است.

## پیش‌نمایش عمومی واقعی — تفکیک وضعیت

- `live_calendar_acquisition`: **PASS_REPLAYED**. پنج raw زندهٔ ۲۴ اکتبر ۲۰۲۶ و replay آفلاین تأییدشده در `live/public-calendar/` موجودند. در ادامهٔ این مأموریت هیچ endpoint تازه‌ای فراخوانی نشد.
- `live_account_preview`: **BLOCKED / NOT_RUN**. جمع‌آوری تقویم به‌تنهایی preview حساب نیست. ranking موجود برای شروع تازه مناسب/تأییدشده نیست؛ هیچ preview سفارش زنده ادعا نمی‌شود.
- پیش‌نمایش زندهٔ قبلی با مرز `window_start=20261024` فقط `NO_NEW_SESSION` پس از آن مرز را گزارش می‌کرد؛ آخرین جلسهٔ مشاهده‌شده خود ۲۴ اکتبر بود. این مرز، تصمیم حساب نبود.

یک حساب عمومی مستقل در `draft/` ساخته شد؛ سرمایهٔ اولیه همان ۱۰۰٬۰۰۰٬۰۰۰ تومان قالب است، active decision/order ندارد و وضعیتش `INACTIVE_PUBLIC_PAPER_DRAFT` است. ranking پین‌شدهٔ آن `PREPARATION_UNCONFIRMED` است؛ این فایل برای ثبت تصمیم یا preview سفارش استفاده نشد. حساب قدیمی به public تبدیل یا migrate نشد.

مبنای مانع از خود artifact است: ranking با status=`PREPARATION_UNCONFIRMED` صریحاً «رتبهٔ رسمی یا ارزیابی آینده نیست» و lineage زمان دریافت برای ادعای availability پیش از cutoff را اثبات نمی‌کند. قرارداد قفل‌شدهٔ v12.28 قاعدهٔ P1 rank 1 را مشخص می‌کند، اما این artifact را به رتبهٔ جاری/معتبر ارتقا نمی‌دهد. ۱۶۶/۲۵۴ به‌تنهایی آستانهٔ تازه‌ای نمی‌سازد. برای شروع، snapshot نامزد قابل‌اعتبارسنجی با lineage/زمان دریافت هم‌خوان لازم است؛ سپس تصمیم تازه با timestamp واقعی ثبت می‌شود. preview زندهٔ سفارش تا آن زمان BLOCKED می‌ماند.

## آزمون‌ها و شواهد

پس از آخرین تغییر کد، مجموعهٔ کامل ۱۷۰ آزمونی اجرا شد: ۱۷۰ موفق، صفر ناموفق، در ۵۵۲٫۵۸ ثانیه؛ فرمان و نتیجه در `evidence/test-run.json` ثبت شده است. همان مجموعه crash پیش و پس از replace، رقابت دو writer و دو fill هم‌زمان را پوشش می‌دهد. hash شش فایل محافظت‌شده قبل/بعد در `result.json` است. گزارش اولیه و manifest آن با نام یکتا در `history/TF03-PARTIAL-INITIAL-20261025T203000Z/` حفظ شده؛ پوشهٔ review TF-03 و rawهای live تغییر نکردند.

اجرای مجدد harness، hash پیش/پس هفت مقصد بالقوهٔ اصلی (حساب و ranking legacy، قواعد و manifestهای default، status outputها و درخت خروجی paper_cycle) را ثبت کرد؛ همه برابر ماندند. مسیرهای واقعی harness زیر `task-tf03/offline/` هستند. نتیجه در `evidence/write-target-audit.json` است.

Runbook فرمان‌های ساخت حساب مستقل، ثبت تصمیم، preview، apply، mark و replay را دارد؛ فرمان‌های عملیاتی آن در این مأموریت اجرا نشده‌اند. جزئیات artifactها و SHA-256 در `artifact-manifest.json` است.
