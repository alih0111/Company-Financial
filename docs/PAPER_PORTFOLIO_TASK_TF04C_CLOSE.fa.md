# TF-04C-CLOSE — تکمیل دو پذیرش باقی‌ماندهٔ آفلاین

ابتدا گزارش `docs/paper_portfolio_delivery/task-tf04c-fix/review/REVIEW.fa.md` و خروجی `review/run-20261026T114903050248Z/verification.json` را بخوان. اصلاح مقایسهٔ کامل نتیجه و پنج mutation پذیرفته شده‌اند. هدف این مأموریت پایان‌دادن به دو گروه باقی‌مانده است؛ تعداد تست یا گزارش هدف نیست.

دامنه فقط adapter، fixture و آزمون‌های مستقیم آن است. شبکه و دریافت زنده، DB، cycle، حساب، scheduler، ranking، public، preview/fill، ledger و admission اجرا نشوند. قرارداد P1/P3 و parserهای موجود تغییر نکنند. captureهای قبلی، reviewها، index و تغییرهای هم‌زمان حفظ شوند. نیاز به هیچ توکن یا ورودی بیرونی برای این مأموریت نیست.

## ۱. ابتدا یک مسیر موفق واقعی بساز و اجرا کن

- fixture کوچک و خودبسنده با هویت، tracing، عنوان/دوره، publication و محتوای سازگار بساز. مصنوعی بودن fixture یا منشأ محلی آن صریح باشد؛ receipt تاریخی یا واقعی برایش اختراع نکن. وابستگی آزمون به پوشهٔ review و temp قبلی حذف شود.
- راه شروع: `prepare_codal_inputs.parse_financial` main بدون datasource را می‌پذیرد و سپس صفحات وابسته را parse می‌کند؛ موفقیت نیازمند facts والد با واحد rial یا rial_per_share است. می‌توان main مصنوعی دارای selector ساخت و یک sheet معتبر محلی با metadata خودش را به آن متصل کرد؛ قواعد parser را تغییر نده. دادهٔ معتبر باید داخل fixture بسته snapshot شود، نه از مسیر متغیر cache خوانده شود.
- در process تازه با acquire واقعی، opener ساختگی و parser واقعی اجرا کن: دو search معتبر، redirect main مالی، حداقل یک sheet لازم با redirect و body متفاوت از main، مالی PARSED_HELD با facts و مقادیر معلوم، فروش PARSED_HELD با مبلغ معلوم، سپس replay برابر کل نتایج. خروجی parser را mock نکن.
- assert دقیق status، facts، basis، واحد و مبلغ بگذار. main receipt/hash/time باید متعلق به main بماند؛ sheet جای آن ننشیند. hash compressed و payload جدا و پیش از مصرف با receipt تطبیق داده شوند؛ محاسبهٔ hash تازه از bytes تغییرکرده جای تطبیق با مقدار pinشده نیست. acquire و replay ورودی یکسان مصرف کنند.
- دستکاری bytes صفحه، چه gzip و چه payload، باید رد شود. مقایسهٔ replay نباید فیلدهای حساس را برای برابرکردن نتایج حذف کند. CLI mismatch همچنان exit غیرصفر بدهد.
- اگر fixture در نخستین اجرای parser رد شد، علت را با همان دادهٔ محلی برطرف کن؛ دو رد parser را موفقیت چرخه معرفی نکن و صرفاً گزارش ناتمام دیگری نساز.

## ۲. outcome توقف و کامل‌بودن receipt را اصلاح کن

- روی acquire و replay واقعی، حالت‌های first-timeout، read-error، 429، CAPTCHA، cooldown دو feed و body بزرگ‌تر از سقف را اجرا کن. همه offline و با opener ساختگی باشند. چهار حالت نخست و oversize فقط یک تلاش؛ cooldown صفر تلاش. manifest در توقف‌های کنترل‌شده حفظ شود.
- نتیجهٔ بازپخش توقف ثبت‌شده باید با همان outcome برابر باشد؛ توقف مشروع با خرابی شواهد یکی نیست. search ناموفق/اجرانشده و no-selection/no-body یک قرارداد مشترک در acquire و replay داشته باشند. challenge را برای census موفق parse نکن. status و دلیل توقف را مقایسه کن؛ تغییرشان باید mismatch بدهد.
- missing body اعلام‌شده در read failure را از حذف body متعلق به پاسخ کامل تفکیک کن. برای پاسخ ناموجود hash یا زمان دریافت نساز. صحت بازپخش outcome و صحت bytes موجود را جدا گزارش کن؛ صفر body نباید ادعای دریافت پاسخ موفق ایجاد کند.
- در oversize وضعیت BODY_TRUNCATED حفظ شود؛ prefix ذخیره‌شده hash خودش را داشته باشد، اما complete_body_count صفر و نتیجه فاقد ادعای پاسخ کامل باشد. شمار attempt، response، complete body و truncated body معنی روشن داشته باشند.
- خطای کنترل‌شدهٔ آماده‌سازی صفحه/metadata/parser نیز نباید receiptهای قبلی را با نساختن manifest از بین ببرد؛ finalization را محدود به همین نیاز اصلاح کن، framework تازه نساز.

## آزمون و تحویل

- شبکه در process والد و subprocess فرزند مسدود باشد. ۱۸ آزمون موجود و regressionهای مستقیم بالا پس از آخرین تغییر اجرا شوند؛ suite حسابداری/۱۸۵تایی تکرار نشود. basetemp کوتاه و یکتا انتخاب کن تا خطای طول مسیر ویندوز نتیجه را مخدوش نکند.
- گزارش مختصر، فرمان و exit واقعی، شاهد موفق مالی/فروش با مقادیر معلوم و replay کامل، جدول حالت‌های توقف و mutationها، baseline پیش/پس مسیرهای مشترک، و manifest کوچک تحویل بده. pytest-temp و rawهای تکراری حجیم در manifest نریز.
- سورس و تست و fixture دقیقاً آزموده‌شده snapshot شوند و hash همهٔ ارجاعات با آن‌ها برابر باشد. فایل‌های نسخهٔ قبلی را بازنویسی نکن. نبود نسخهٔ محتوایی سورس live قدیمی با snapshot امروز رفع نمی‌شود.
- فقط با عبور هر دو گروه، PASS برای اصلاح آفلاین اعلام کن. این PASS مجوز آمادگی تصمیم یا موفقیت live مالی نیست؛ readiness BLOCKED و admission صفر می‌مانند. پس از تحویل برای بازبینی متوقف شو.
