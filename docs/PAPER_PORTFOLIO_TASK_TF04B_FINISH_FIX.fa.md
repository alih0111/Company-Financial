# TF-04B-FINISH-FIX — سه اصلاح باقی‌مانده، آفلاین

ابتدا `docs/paper_portfolio_delivery/task-tf04b-finish/review/REVIEW.fa.md` و سه شاهد مستقل آن را بخوان. هدف بستن همان پذیرش‌های TF-04B-FINISH است؛ محصول یا مأموریت تازه نساز. تا اصلاح و آزمون هدفمند ادامه بده؛ برای مراحل مجاز میانی متوقف نشو.

## محدوده

شبکه/token، DB، cycle عملیاتی، scheduler، حساب اصلی، preview/fill، دفتر رسمی و انتشار public اجرا نشوند. P1/P3، قرارداد قفل‌شده، universe، معیار admission و freshness policy تغییر نکنند. تمام candidateها تا شاهد واقعی admission held بمانند؛ موفقیت parse مجوز ارتقای readiness نیست.

محصول را فقط در بخش‌های caller/builder/assessor و harness مرتبط اصلاح کن. تحویل در یک run جدید زیر `docs/paper_portfolio_delivery/task-tf04b-finish-fix/` باشد؛ تحویل‌ها و reviewهای قبلی را بازنویسی نکن. به تغییرهای هم‌زمان و index دست نزن؛ reset/stage/commit/پاک‌سازی لازم نیست. موفقیت 33+11 parser و 254 هویت را از صفر بازطراحی نکن.

## ۱. context واحد caller، از fallback تا validation

- تاریخ مؤثر، MARKET_PACK، DATASET_ID و مسیرها را یک‌بار در هر شاخه انتخاب کن. factor preparation، main، shadow و validation از همان context استفاده کنند؛ تاریخ بازار ناقص یا None دوباره در عبارت validation مصرف نشود.
- موارد واقعی را تست کن: بازار کامل؛ نبود تاریخ؛ وجود تاریخ ولی بازار ناقص/failed؛ shadow. صرف ساخت دستی env در harness شاهد اتصال caller نیست. می‌توان helper خالص انتخاب context استخراج کرد و مسیرهای اصلی را به آن وصل کرد، یا orchestration را با stageهای stubشده آزمود. cycle واقعی اجرا نشود.
- بدون override ویژهٔ V1237_DATASET_ID، extraction/ranking/validator باید شناسهٔ یکسان مربوط به v12-37 داشته باشند. helper v12-35 وقتی مستقل استفاده می‌شود پیش‌فرض تاریخی خودش را حفظ کند؛ با تنظیم global دائمی آن را به v12-37 تبدیل نکن.
- یک اجرای wrapper واقعی `build_latest_supported_v12_37.py` روی ورودی pinned با مقصدهای temp و بازار ایزوله، بدون DATASET_ID ویژهٔ harness، ثبت کن. metadata consistency، validator و same-input باید پاس باشند. اجرای `_impl.py` به‌تنهایی شاهد wrapper نیست.
- محافظ overwrite ایزوله را نگه دار. public اصلی در هر تست با temp جایگزین شود. env مؤثر را ثبت و V1237های ناخواستهٔ محیط را حذف کن. حالت offline دادهٔ بازار اصلی را بازنویسی نکند.

پذیرش: regression خطای None.replace و تاریخ ناسازگار fallback؛ آزمون env شاخه‌ها؛ یک wrapper واقعی موفق؛ dataset یکسان در سه سطح؛ پیش‌فرض v12-35 با import/read-only test؛ حفظ sentinel مقصد ایزوله.

## ۲. معنی cutoff را از مصرف‌کنندهٔ واقعی بگیر

- `H.select_asof` انتشار برابر cutoff را رد می‌کند. assessor اکنون آن را می‌پذیرد. روی مرز دقیق، 1µs پیش و 1µs پس، نتیجهٔ selector واقعی و بررسی panel باید هم‌معنا باشد.
- معادل‌کردن end-of-day و next-midnight بدون مشخص بودن عملگر هر دامنه مجاز نیست. cutoffهای financial selection، lineage، sales و نمایش snapshot را با نام دامنه/عملگر توضیح بده. اگر دو نمایش واقعاً قرارداد متفاوت دارند، اختلاف را گزارش کن؛ قرارداد قفل‌شده یا selector را برای پاس شدن assessor تغییر نده. tolerance وسط روز بازنگردد.
- fixture واقعی assess با receipt invalid، naive و آینده بساز؛ declaration/hashهای دیگر درست باشند تا آزمون دقیقاً زمان را بسنجد. ساعت اجرای واقعی را جعل نکن؛ تاریخ آینده را نسبت به ساعت ثبت‌شدهٔ آزمون بساز. provenance و قابل‌استفاده‌بودن برای تصمیم دو خروجی مجزا باشند. آزمون after-decision موجود را حفظ کن.

پذیرش: fixture سه‌مرزی از selector واقعی، real panel/assess، و سه حالت زمان؛ خروجی helper به‌تنهایی کافی نیست. اگر تطبیق واقعی یک ناسازگاری قدیمی metadata را آشکار کرد، شفاف ثبت شود؛ نتیجهٔ عددی صحیح را با lineage صحیح یکی نکن.

## ۳. ممیزی وابستگی‌ها و شواهد جاری

- baseline محافظت قبل از اولین پردازش بگیر. علاوه بر شش مقصد موجود، rules/قراردادهای مصرفی، ledgerهای رسمی مرتبط و reviewهای قبلی را با مسیر دقیق پوشش بده. نبود مسیر را صریح ثبت کن؛ bytes اصلی را تغییر نده و برای تکمیل شاهد گذشته timestamp نساز.
- manifest ورودی را از وابستگی واقعی بساز؛ حداقل comparative_lineage.json و owner_features.csv که در extraction source_sha256 هستند و قبلاً pin نشده‌اند افزوده شوند. پیش/پس actual consumption ثبت شود. raw مالی/فروش و cache snapshotهای موجود را حفظ کن؛ هیچ دانلودی لازم نیست.
- همهٔ financial_pages خوانده‌شده، حتی اگر parse رد شود، پیش از فراخوانی parser وارد input manifest شوند. regression رد parser پس از خواندن صفحه باید آن صفحه را همچنان در ممیزی نشان دهد.
- شواهد جدید parser مالی/فروش یک منبع حقیقت داشته باشند. output قدیمی با «parser نداریم» و نام compressed برای digest payload را در run تازه تولید نکن یا صریحاً legacy diagnostic جدا معرفی کن؛ تاریخچه را تغییر نده.
- نمونهٔ مستقل یک مالی و یک فروش را با آدرس سلول/ستون در datasource خام، دوره، unit و تبدیل عدد ثبت کن؛ assert صرفاً خروجی خود parser کافی نیست. نیازی به parser عمومی جدید نیست.
- شمارش تست‌ها و وضعیت‌ها از خروجی واقعی استخراج شوند؛ `package_finish.py` اکنون 23 را hardcode می‌کند. manifest فایل‌های کوچک لازم را پوشش دهد؛ زیرmanifestهای ranking را صرف نام manifest.json از پوشش حذف نکن. rawها با مسیر+hash کافی‌اند؛ tempهای pytest و کل تاریخچه را بسته‌بندی نکن.

## تحویل و پایان

23 آزمون فعلی + regressionهای مستقیم اصلاح‌ها کافی است؛ suite کامل 185تایی پیش‌شرط نیست. یک بار پس از آخرین تغییر اجرا و stdout/stderr/فرمان ثبت شود. موارد parser، caller، cutoff، input audit، calculation و readiness وضعیت جدا داشته باشند. README/REPORT کوتاه، result، شواهد و manifest نهایی ارائه کن.

508 جفت discovery برنامه باقی بمانند؛ اجرا نشوند و تعداد درخواست نامیده نشوند. body gap ناشی از parser/metadata را با نبود receipt یا census قاطی نکن. سه publication mismatch با تغییر metadata یا دورزدن کنترل رفع نشوند.

PASS محدود زمانی مجاز است که سه یافته بسته شوند. readiness می‌تواند همچنان BLOCKED/UNKNOWN بماند و این به‌خودی‌خود مانع PASS اصلاح نیست. اگر پذیرشی شاهد ندارد، همان را PARTIAL بنویس؛ نه اینکه با تعداد تست یا هش فایل جایگزینش کنی. پس از تحویل برای بازبینی برگرد.
