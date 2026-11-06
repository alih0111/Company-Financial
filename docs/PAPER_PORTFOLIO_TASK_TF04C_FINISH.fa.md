# TF-04C-FINISH — بستن مسیر واقعی acquire و ادامهٔ همان پایلوت

ابتدا `docs/paper_portfolio_delivery/task-tf04c-pilot/review/REVIEW.fa.md` و `review/run-20261026T072401401128Z/verification.json` را بخوان. مأموریت محدود است: اصلاح adapter، اثبات آفلاین مسیر کامل، سپس یک اجرای عمومی محدود برای همان غاذر. تشخیص تازهٔ گسترده، framework تازه یا بازسازی بازار/wrapper لازم نیست.

## مرزها

- capture قبلی، rawها، manifest-initial/final، review و index را بازنویسی نکن. تغییرهای هم‌زمان دیگر حفظ شوند.
- مقصد جدید و یکتا زیر بستهٔ پایلوت؛ cache/resume جاری فقط خواندنی. هیچ DB، cycle، ranking، public، حساب، scheduler، preview/fill، ledger یا admission اجرا نشود. P1/P3 و universe ثابت بمانند.
- پس از موفقیت پذیرش‌های آفلاین، یک invocation تازه با حداکثر **12 HTTP واقعی** برای یک هویت و دو feed مجاز است؛ redirects و تمام صفحات جزء همین سقف. retry خودکار صفر، concurrency یک. از سقف برای اجرای دور دوم استفاده نکن.

## ۱. مسیر موفق و مسیر توقف را در خود acquire درست کن

- import parser/dependencyها را در process تازه درست راه‌اندازی کن؛ وابستگی به import قبلی آزمون دیگر نداشته باش. خطای import محلی urllib را نیز حذف کن. parserهای قفل‌شده و کنترل publication را شل نکن.
- metadata مالی از search اکنون publication بدون timezone دارد. متن منبع را حفظ کن و مطابق تبدیل زمان منبع در collector موجود، زمان آگاه از timezone را به parser بده؛ از timezone سیستم برای تفسیر datetime naive استفاده نشود. receipt واقعی UTC مفهوم جداگانه است.
- توقف 429/challenge/timeout/budget یا خطای خواندن پاسخ باید manifest جزئی و علت صریح بسازد؛ feedهای اجرا‌نشده را اجرا‌نشده بنویس. پس از stop، transport دوباره صدا نخورد. خطای parser نیز outcome ردشده است، نه حذف receiptها. body ناقص را کامل اعلام نکن.
- تلاش‌های بدون پاسخ hash/body موفق ندارند؛ برای receipt پاسخ‌ها و تعداد تلاش‌ها وضعیت جدا بده. از `all([])` برای اثبات receipt موفق استفاده نکن.

## ۲. redirect عمومی محدود و receipt کامل

- headerهای موردنیاز Date، Content-Type، Content-Encoding، Location و Retry-After را در receipt ذخیره کن؛ پاسخ قبلیِ فاقد header را با header حدسی ترمیم نکن.
- redirect خودکار library خاموش بماند؛ hopها دستی از همان BudgetTransport بگذرند. برای report فقط HTTPS، همان hostname رسمی درخواست اولیه و مسیر `/Reports/` مجاز است؛ Location نسبی با URL فعلی resolve شود. شناسهٔ LetterSerial پس از decode باید همان گزارش باشد. مقصد خارج از این حدود، login/challenge، loop یا Location نامعتبر موجب توقف مستند شود.
- حداکثر دو hop برای هر زنجیره؛ هر hop یک درخواست از سقف مشترک 12. URL اولیه، هر پاسخ/Location و URL نهایی به هم متصل بمانند. صفحهٔ 302 به parser نرود؛ فقط body نهایی معتبر مصرف شود. header به معنای موفقیت مقصد نیست.
- منبع URL search/report همان مسیر عمومی موجود است؛ فقط لینک درست‌نما کافی نیست و مقصد باید قبل از ارسال اعتبارسنجی شود. CAPTCHA/429 را دور نزن؛ cooldown ثبت‌شده رعایت و با دریافت آن‌ها متوقف شو.

## ۳. census را از body و parser جدا کن

- census search به خطای body وابسته نباشد؛ اما موفقیت HTTP/count به‌تنهایی هم کافی نیست. هویت تمام ردیف‌ها، پنجره، صفحه‌ها، Total ثابت و tracing_noهای یکتا بررسی شوند. ردیف غیرمرتبط یا duplicate با شمارش ظاهراً درست، complete ایجاد نکند.
- Total=0 با پاسخ و صفحهٔ معتبر را از پاسخ ناموجود جدا کن. پنجره و حدود ادعای census را صریح حفظ کن؛ از پنجرهٔ افزایشی، پوشش همهٔ تاریخ یا correction chain کامل نتیجه نگیر.
- فیلدهای search/body/parser و نتیجهٔ نهایی از کد تولید شوند؛ پس از capture، manifest را دستی برای تغییر وضعیت‌ها ویرایش نکن. تحلیل تکمیلی می‌تواند فایل جدا با hash منبع باشد.
- replay همان ورودی‌ها و receiptهای ثبت‌شده را مصرف کند، شبکه ممنوع باشد و outcome موفق، رد parser یا نقص صفحات را دقیقاً مقایسه کند. ردشده‌ها نیز جزء مقایسه‌اند؛ None جای اثبات تطابق نیست.

## ۴. پذیرش‌های آفلاین پیش از live

از همان probeهای بازبین شروع کن؛ فقط تست helper کافی نیست. acquire واقعی با opener ساختگی یا entrypoint واقعی در process تازه اجرا شود و اتصال شبکهٔ واقعی در تست‌ها مسدود باشد:

1. search معتبر → redirect مجاز → body مالی/فروش و صفحات لازم → parser موجود → held → replay برابر. fixture body و metadata هم‌خوان باشند؛ receipt ساختگیِ آزمون را live معرفی نکن.
2. اولین search برابر 429 و یک failure هنگام خواندن پاسخ: بدون درخواست بعدی، manifest جزئی معتبر و شاهد موجود حفظ شود. challenge و رسیدن به budget نیز توقف کنترل‌شده داشته باشند.
3. Location/Retry-After در manifest بمانند؛ loop، مقصد نامجاز و پایان budget پیش از hop بعدی درخواست اضافی نسازند.
4. نماد نامرتبط، duplicate و Total ناسازگار complete نشوند؛ Total=0 معتبر و شکست body پس از search سالم درست تفکیک شوند.

شمار تست هدف نیست. شش تست موجود و regressionهای مستقیم بالا پس از آخرین تغییر کافی‌اند؛ suite حسابداری/185تایی لازم نیست.

## ۵. اجرای محدود و تحویل

پس از پاس آزمون‌ها، dry-run و همان invocation جدید 12درخواستی را انجام بده؛ برای مراحل میانی مجاز متوقف نشو. header حذف‌شدهٔ اجرای قبلی را از body آن جعل نکن؛ دریافت جدید receipt جدید دارد. capture جدید را آفلاین replay کن. اگر دادهٔ معتبر نرسید، علت واقعی و تعداد درخواست‌ها را ثبت کن؛ با گسترش universe یا retry بیشتر دنبال PASS نرو.

گزارش کوتاه، result با وضعیت‌های مستقل implementation/live/receipt/search/parser/replay/readiness، فرمان‌های واقعی، baseline کوچک پیش/پس، و manifest شامل کد و شواهد همان run بده. سورس اجرایی هنگام live را hash و نگهداری کن؛ اگر بعداً تغییر لازم شد، نسخهٔ اولیه و تفاوت معلوم باشند. شواهد قبلی فقط ارجاع path+hash، بدون کپی بازار یا pytest temp.

admission صفر و آمادگی BLOCKED بماند؛ رفع نیاز سیاست freshness و اقدام شرکتی خارج از این مأموریت است. پس از یک اجرای محدود و تحویل برای بازبینی متوقف شو. هیچ PASS برای بخش اجرا‌نشده اعلام نکن.
