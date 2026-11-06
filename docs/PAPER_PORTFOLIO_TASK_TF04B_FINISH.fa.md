# TF-04B-FINISH — بستن نواقص بازیابی محلی و سازگاری builder

محل کار `D:/RFA/Company-Financial` است. ابتدا `docs/paper_portfolio_delivery/task-tf04b-local/review/REVIEW.fa.md` و شواهد سه probe را بخوان. هدف تکمیل همان مأموریت محلی است؛ محصول جدید، آموزش مدل، دریافت زنده یا فعال‌سازی نیست. تا پایان اصلاح و آزمون هدفمند ادامه بده و برای تأیید کارهای مجاز میانی متوقف نشو.

## حدود و مقصد

هیچ شبکه/token، DB، scheduler، cycle عملیاتی، حساب اصلی، preview/fill، ledger یا انتشار public انجام نشود. مدل‌ها، وزن‌ها، قراردادهای قفل‌شده، universe و معیار admission تغییر نکنند. وضعیت آمادگی و PREPARATION_UNCONFIRMED با تکیه بر parse موفق بالا نرود. index و تغییرهای هم‌زمان حفظ شوند؛ هیچ reset/stage/commit/پاک‌سازی runهای میانی لازم نیست.

تحویل جدید زیر `docs/paper_portfolio_delivery/task-tf04b-finish/` با run یکتا باشد؛ reviewها و تحویل قبلی byte-exact بمانند. تغییر محدود run_local، ابزار assess، دو builder و اتصال caller در صورت ضرورت مجاز است؛ تغییر caller فقط همراه آزمون آفلاین. محتوای مشترک را به حالت قدیمی reset نکن، فقط diff متعلق به اصلاح را اعمال کن.

## ۱. ابتدا دادهٔ موجود را با parser موجود واقعاً مصرف کن

بازبینی با `prepare_codal_inputs.parse_financial` و `parse_sales` روی همان داده‌ها، ۳۳ مالی و ۱۱ فروش را parse کرد؛ ۳۸ مالی بدون facts parent و ۳ مورد publication mismatch رد شدند. این اعداد oracle اجباری یا مجوز admission نیستند؛ هر اختلاف با ورودی pinned توضیح داده شود.

- parser مناسب HTML پویا را با parser جدول قدیمی اشتباه نگیر. از توابع موجود استفاده کن؛ acquisition، اجرای JavaScript یا دورزدن کنترل هویت/واحد/زمان مجاز نیست.
- cache را قبل از خواندن به snapshot محلی با hash تبدیل کن. تمام rawهای اصلی و financial_pages مورد مصرف را از همان snapshot enumerate و پیش/پس hash کن. از همان bytes مهرشده parse کن؛ cache اصلی و rawهای تاریخی را بازنویسی نکن.
- برای هر گزارش خروجی قابل ماشین‌خواندن بده: tracing، company، symbol، دوره، زمان انتشار، basis و unit، raw/payload digest و دامنهٔ digest، parser/version، facts یا علت رد. نبود شاهد با mismatch یکی نشود؛ `not archived` را به `identity verified` تبدیل نکن.
- `parsed`، `reusable candidate` و `admissible for locked ranking` وضعیت‌های جدا داشته باشند. مشاهدهٔ واقعی اکنون را فقط local observation بنام؛ آن را source receipt تاریخی جا نزن. سه publication mismatch را با دورزدن کنترل یا تغییر فراداده رفع نکن؛ علت دقیق/نیاز واقعی را ثبت کن.
- حداقل یک خروجی مالی و یک فروشِ موفق را به سلول یا دادهٔ خام مربوط، دوره و واحد وصل کن و عدد مستقل قابل بررسی بده. نمونهٔ غاذر قدیمی را نگه دار؛ صرف محاسبهٔ رشد نمونه را مساوی عامل TTM مصرفی scorer ننام.
- یک bundle مجزای candidate از facts واقعاً parsed بساز. از admission موجود در حالت آفلاین/مقصد temp استفاده کن اگر بدون side effect ممکن است؛ در غیر این صورت علت held را با کنترل مشخص کد ثبت کن. تنها در صورت پذیرش واقعی قرارداد، ranking candidate جدا ساخته شود؛ برای دادهٔ held هیچ افزایش coverage یا تغییر رتبه ادعا نشود.

پذیرش: روی همان داده‌ها parser درست اجرا شده، خروجی و موارد رد بازتولیدپذیرند؛ حداقل تست اتصال parser پویا با raw موجود، فروش موفق، identity/period/unit mismatch و عدم admission خودکار وجود دارد. تستِ صرفاً کپی کردن عدد ۳۳ یا ۱۱ کافی نیست.

## ۲. سازگاری caller را بدون اجرای عملیاتی برگردان

`build_latest_supported_v12_37_impl` اکنون PUBLIC_DIR را اجبار می‌کند ولی caller عادی و shadow در paper_cycle آن را نمی‌دهند. probe بازبینی wrapper واقعی را با این env اجرا کرد و exit1 گرفت.

- قرارداد حالت ایزوله را صریح کن و override خروجی را تا wrapper/builder/ranking/public-isolated منتقل کن. شرط محافظت از مقصد ایزوله را حفظ کن؛ راه‌حل، خاموش کردن کلی محافظ یا نوشتن در public اصلی نیست.
- caller اصلی و shadow باید با همان قرارداد هماهنگ باشند. سازگاری فراخوانی قبلی را حفظ کن یا migration محدود و کامل caller را پیاده کن؛ حالت نیمه‌مهاجرت‌داده‌شده تحویل نده. public اصلی در تست‌ها با temp جایگزین شود؛ هرگز برای اثبات سازگاری cycle واقعی را اجرا نکن.
- تغییر پیش‌فرض v12-35 به تاریخ ۲۴ اکتبر و نام `v12_37_local_reuse` برای تمام callerها درست نیست. نسخه/تاریخ/dataset را از context همان builder بگیر، رفتار تاریخی unrelated را حفظ کن؛ برای run ایزوله تنظیم صریح بده.
- `evaluation_price_latest` از قیمت‌های واقعاً منتخب حاصل شود و با تاریخ درخواست اشتباه نشود. metadata آرشیو و selected panel مستقل بماند. فیلدهای تاریخی HTTP429/request_count را بدون مرجع invocation به دریافت run آفلاین نسبت نده.

پذیرش: یک اجرای واقعی آفلاین موفق wrapper روی ورودی pinned و مقصد temp؛ آزمون اتصال env برای مسیر اصلی و shadow؛ رد overwrite در حالت ایزوله؛ کنترل تاریخ/dataset v12-35 بدون اجرای مقصد پیش‌فرض؛ validator قفل‌شده و مقایسهٔ same-input عامل‌ها/رتبه‌ها. مسیرهای default/public و source package پیش/پس ثابت بمانند.

## ۳. شواهد، دامنهٔ hash و مرز زمان را کامل کن

- ۶۶ ورودی قبلی، ۱۶ raw مالی خارج cycle و ۱۱ فروش را پوشش نداده بود. manifest ورودی‌ها از وابستگی واقعی parser و builder ساخته شود: rawهای ارجاع‌شده، financial_pages، cache snapshot، ورودی‌های مالی/فروش، share/market و قراردادهای مصرفی. از پوشش کامل با فهرست ناقص ادعا نکن.
- digestهای stored/compressed، decompressed payload و normalized text جدا و با نام صحیح ثبت شوند؛ `body.sha256` را `declared_compressed_sha256` ننام اگر قراردادش payload است. مخلوط شدن یا نبود declaration نباید PASS شود.
- baseline تازهٔ واقعی پیش از run بساز. public v12-37 پیش از TF-04B با baseline قدیمی تفاوت داشته؛ آن را reset نکن و تغییر پیشین را به این مأموریت نسبت نده. حساب، rules، قراردادها، ledger/default outputs و reviewها را در ممیزی پوشش بده.
- پذیرش‌های باقی‌ماندهٔ real-assess زمان invalid، naive، future و after-decision را با fixture کوچک تکمیل کن؛ provenance با ترتیب زمانی دو فیلد مستقل باشد، timestamp آینده به‌عنوان قابل‌مصرف برای تصمیم امروز پذیرفته نشود. ساعت CLI واقعی بماند.
- tolerance عمومی 1µs در cutoff کافی نیست: `<` یا `<=` را از selectorهای واقعی هر دامنه دنبال کن، روی مرز دقیق، پیش و پس از آن fixture بده و نتیجه را با assess مقایسه کن. هیچ تغییر در قرارداد قفل‌شده برای آسان شدن تست نده. فقط اگر قرارداد inclusive/exclusive معادل بودن را اثبات می‌کند تبدیل نمایش زمان انجام شود؛ اختلاف وسط روز نباید معادل تلقی شود.

## ۴. تحویل کوتاه و کسری قابل اقدام

REPORT و result با وضعیت جدا: hash بازار، parsing/reuse، admission، metadata/isolation/caller compatibility، calculation و readiness. موفقیت‌های فعلی hash بازار/محاسبه را دوباره از صفر نساز؛ regressionهای مرتبط و آزمون‌های ۱۸تایی تشخیص را اجرا کن. برای shared caller فقط تست‌های مرتبط با علت مشخص اضافه کن؛ suite کامل ۱۸۵تایی پیش‌شرط مصنوعی نشود.

`network-gap-plan.json` به دو بخش تفکیک شود:

1. discovery/جامعیت اطلاعیه‌ها: ۵۰۸ جفت identity/feed ممکن است همچنان pending باشند؛ این تعداد را تعداد HTTP request ننام، تعداد صفحات وابسته به پاسخ است. watermark/window از baseline معلوم باشد و currentness تازه ادعا نشود.
2. body/sheet gap: فقط گزارش/برگ واقعاً مفقود یا غیرقابل اعتبارسنجی، با شناسه، علت رد parser، raw موجود، endpoint موجود در کد و دلیل ناکافی بودن reuse. ۳۳+۱۱ parse موفق را به‌عنوان «بدنه نیازمند دریافت دوباره چون parser نداریم» فهرست نکن. علت held مربوط به receipt یا کامل‌بودن اطلاعیه با نیاز به دانلود body فرق دارد.

هیچ‌کدام اجرا نشوند. محدودیت CAPTCHA/429 و retry موجود رعایت شود. شبکه مرحلهٔ بعد است.

شواهد شامل فرمان‌های واقعی، stdout/stderr، facts/candidate bundle، نتیجهٔ admission/held، validator، diff same-input، before/after hash و manifest مختصر نهایی باشند. raw ثابت را با مسیر+hash ارجاع بده؛ فقط cache متغیر لازم را snapshot کن. pytest temp، runهای تاریخی و کل بازار را بی‌دلیل چندباره داخل manifest کپی نکن. فقط run مرجع روشن باشد؛ پاک‌سازی برای PASS لازم نیست.

معیار پایان این مأموریت: یافته‌های مشخص بازبینی بسته و چرخهٔ بازیابی محلی بازتولیدپذیر باشد؛ آماده نبودن تصمیم به‌دلیل acquisition/policy مستقل، مانع PASS محدود این اصلاح نیست. پس از تحویل برای بازبینی برگرد.
