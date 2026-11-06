# مأموریت ۰۱B: بستن replay و مقاومت commit حساب کاغذی

در `D:\RFA\Company-Financial` این مأموریت را پیاده‌سازی و با شواهد واقعی تحویل بده. هدف پایان دادن به مأموریت والد ۰۱ است. بازنویسی معماری، مدل رتبه‌بندی، موتور خرید/فروش یا backtest تازه لازم نیست. سه بخش زیر را به‌ترتیب انجام بده؛ تست‌های هر بخش باید پیش از بخش بعد پاس شوند.

ابتدا `git status --short --untracked-files=all` و این فایل‌ها را بخوان:

- `docs/paper_portfolio_delivery/task-01a/review/REVIEW.fa.md`
- `docs/paper_portfolio_delivery/task-01a/review/results.json`
- `docs/PAPER_PORTFOLIO_TASK_01.fa.md` برای پذیرش‌های مأموریت والد.
- کد فعلی `ranking_research/paper_account_store.py`، `ranking_research/future_eval_v12_30/apply_paper_fill.py` و `ranking_research/tests/test_paper_account_atomic.py`.
- قواعد pinned موجود `ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json` فقط برای خواندن.

تغییرات قبلی UI، cycle، Codal و تست‌ها را حفظ کن؛ reset/stash/revert کلی، commit یا push نکن. سورس‌های جدید فعلاً untracked هستند؛ آن‌ها را فایل اضافی و قابل حذف فرض نکن. شواهد قبلی را برای سبزکردن نتیجه بازنویسی نکن.

## بخش اول: دو باقی‌ماندهٔ کوچک ۰۱A

۱. مقایسهٔ تاریخچه را در writer مشترک به نوع JSON حساس کن. تغییر `details.value` رویداد قدیمی از `1` به `true` اکنون در هر دو API ذخیره می‌شود. رویداد قدیمی باید با همان payload حفظ شود؛ ترتیب کلیدهای object اهمیتی ندارد، ولی ترتیب آرایه/رویداد و نوع boolean در برابر number دارد. از مقایسهٔ بازگشتی با نوع صریح یا نمایش canonical معتبر استفاده کن. سیاست `1` در برابر `1.0` را صریح کن؛ محافظه‌کارانه حفظ نوع نمایش عدد مناسب است. تست‌های mutation nested، حذف، reorder و append معتبر همچنان برقرار باشند. مقایسهٔ صرف hash بدون بررسی/تولید معتبر داده راه‌حل کافی نیست.

آزمون لازم: حساب کامل معتبر، تغییر تنها همان payload در `read_modify_write` و جداگانه `write_account_atomic`؛ هر دو باید خطای history rewrite بدهند و bytes ثابت بماند. تغییر فقط ترتیب کلیدهای object نباید رویداد تازه یا خطای مغایرت بسازد. تبدیل دادهٔ ورودی به نوع قدیمی برای پنهان‌کردن تغییر ممنوع است.

۲. در پایان مأموریت، manifest تحویل باید کد محصول، تست‌ها، `.gitignore` در صورت تغییر، و گزارش/شواهد همین مأموریت را با path/size/SHA-256 پوشش دهد. manifest قبلی فقط سه گزارش داشت. خود manifest را برای جلوگیری از خودارجاعی مستثنا کن. برای فایل‌های جدید سورس/تست/گزارش فقط استثنای محدود Git لازم اضافه کن؛ هیچ خروجی، archive یا credential عمومی unignore نشود. از stage کلی و `git add -f .` استفاده نکن.

## بخش دوم: replay عملیاتی fill

محافظ فعلی ابتدای `run_locked` فقط برداشت تکراری را متوقف می‌کند؛ قبل از بررسی ورودی replay خطای عمومی می‌دهد. آن را به رفتار صریح زیر تبدیل کن، با حفظ قفل از پیش از read تا پایان commit و بدون حذف کنترل‌های اعتبار شواهد:

- نخستین fill معتبر فقط یک‌بار نقد، holding، order و رویداد fill را در همان replace ثبت کند.
- اجرای دوبارهٔ همان fill با همان هویت و source hashes، یک no-op موفق با status روشن مثل `FILL_ALREADY_APPLIED` و `fill_applied=false` باشد. exit code صفر، همان fill_event_id و bytes حساب عیناً ثابت بماند؛ timestamp، شمارنده، event یا mark قبلی عوض نشود.
- همان order/fill با payload یا منابع متفاوت، خطای تعارض مشخص مثل `FILL_REPLAY_CONFLICT` بدهد؛ برداشت، اصلاح خودکار holding یا تغییر رویداد قبلی ممنوع است. پیاده‌سازی فرایند correction خارج از این مأموریت است؛ پیام روشن بگوید اصلاح نیازمند رویداد اصلاحی جدا و append-only است.
- ورودی خراب، raw hash ناسازگار، identity اشتباه یا شواهد ضروری مفقود نباید صرفاً به‌علت وجود fill موفق تلقی شود. خطای منبع خراب از replay موفق و تعارض معتبر قابل تفکیک باشد.
- وجود holding بدون fill معتبر و receipt قابل اتکا، همچنان guard مستقل دارد؛ آن را موفقیت replay اعلام نکن. دادهٔ legacy مبهم بدون مهاجرت صریح نباید به‌صورت حدسی تأیید شود.

برای تشخیص، یک receipt/fingerprint ساخت‌یافتهٔ کوچک و نسخه‌دار در **اولین commit همان fill** ثبت کن؛ دفتر یا فایل authoritative دوم نساز. شامل account/order/decision identity موجود، جلسهٔ designated، قواعد pinned، هویت سهم، پارامترهای fill و hash منابع لازمِ تقویم و candidate باشد. هویت replay از path محلی، زمان اجرای دوباره یا ترتیب کلیدهای JSON ساخته نشود. معنای «همان source hashes» و مجموعهٔ دقیق hashها را بنویس و تست کن. retrieval time و lineage همچنان اعتبارسنجی شوند. manifest صرفاً با بازآرایی کلید/انتقال path نباید اثر اقتصادی جدید ایجاد کند؛ raw hash معتبر همچنان باید بررسی شود.

پس از mark، نقد/قیمت/ارزش فعلی را مبنای محاسبهٔ دوبارهٔ خرید قدیمی قرار نده؛ receipt اطلاعات اجرای اولیه و نقد قبل از fill را نگه دارد تا replay به وضعیت امروز وابسته نباشد. از parse متن فارسی/free-text رویداد برای بازیابی مبلغ اصلی استفاده نکن. حساب واقعی هنوز fill ندارد و برای این تغییر نیازی به نوشتن یا مهاجرت آن نیست.

حداقل تست‌های entrypoint روی فایل‌های موقت:

1. اولین خرید واقعی fixture از `main`، سپس دو replay یکسان: دقیقاً یک fill event، یک برداشت و bytes ثابت در replayها.
2. تغییر قیمت raw و به‌روزرسانی صحیح hashها با همان سفارش: تعارض صریح و حساب ثابت. یک تغییر منبع دیگر مثل تقویم نیز پوشش داده شود.
3. raw دستکاری‌شده با hash قبلی یا ورودی ناقص: رد اعتبارسنجی، بدون نوشتن.
4. replay همان fill بعد از mark معتبر جدید: موفق و حسابِ بعد از mark byte-identical بماند.
5. guard حساب دارای holding بدون receipt معتبر و حالت order/fill ناسازگار؛ عدم برداشت و عدم موفقیت جعلی.

fixture پایه خرید: سرمایه ۱۰۰۰۰۰ تومان، close=۱۲۳۴ ریال، ۸۰۶ سهم، gross=۹۹۴۶۰، fee=۴۹۷، cash=۴۳، NAV=۹۹۵۰۳، P&L=−۴۹۷. مثال mark جدا: یک سهم، close=۱۰۰۵ ریال، cash=۹۹۸۹۹، cost=۱۰۰، fee=۱؛ value=۱۰۱، NAV=۱۰۰۰۰۰ و P&L=۰.

## بخش سوم: crash و concurrency با فرایند واقعی

از subprocess و handshake قابل اعتماد با timeout محدود استفاده کن. صرف mock کردن استثنا یا sleep تصادفی برای ادعای مقاومت در برابر مرگ فرایند کافی نیست. حساب‌ها، rawها، manifestها و تمام خروجی‌ها فقط در temporary directory باشند. اگر برای تزریق خطا hook لازم است ترجیحاً در harness فرزند monkeypatch کن؛ گزینهٔ خطرناک عمومی CLI/متغیر محیطی برای crash در محصول نساز.

آزمون‌ها باید مسیر writer واقعی را طی کنند:

- مرگ فرایند حین نوشتن temp پیش از تکمیل، و جداگانه پس از flush/fsync و پیش از replace: فایل اصلی bytes نسخهٔ قدیم و JSON معتبر بماند؛ tmp نیمه‌کاره authoritative نشود.
- مرگ بلافاصله پس از replace، پیش از اعلام موفقیت: فایل اصلی bytes نسخهٔ جدید کامل، schema/accounting معتبر و فقط یک رویداد جدید داشته باشد. در سناریوی fill، اجرای مجدد باید no-op موفق باشد و برداشت دوم نسازد.
- پس از هر crash، فرایند تازه بتواند همان حساب را زیر قفل باز کند و عملیات معتبر بعدی انجام دهد؛ فایل temp باقی‌مانده مانع commit یا موجب بازیابی دادهٔ قدیمی نشود. Windows mutex واقعاً پس از مرگ فرایند آزاد/abandoned قابل تصاحب باشد. حساب هرگز حذف و از روی tmp نامعتبر بازسازی نشود.
- دو فرایند روی **یک مسیر حساب موقت**، read-modify-write واقعی انجام دهند. اولی از پیش از read قفل را نگه دارد؛ دومی یا منتظر می‌ماند یا نتیجهٔ روشن LOCKED می‌گیرد و پس از پایان اولی با خواندن تازه retry می‌کند. پس از دو موفقیت، هر دو append مستقل و هر تغییر وضعیت مورد انتظار موجود باشند؛ هیچ lost update پذیرفته نیست. اگر سیاست fail-fast است، تعداد تلاش، نتیجهٔ LOCKED و retry صریح ثبت شوند.
- دو تلاش fill هم‌زمان برای همان سفارش: بعد از retry مجاز، دقیقاً یک fill/برداشت و یک replay موفق؛ بدون overwrite تغییرات یا duplicate event.

مطمئن شو parent و child هر دو همان ACCOUNT موقت را استفاده می‌کنند؛ تست قدیمی قفل در parent از default واقعی استفاده می‌کرد و فقط به‌دلیل mutex سراسری رد می‌شد. آن تست را به مسیر صحیح موقت محدود کن و assertion اصل قفل را حفظ کن. نیازی به تغییر طراحی قفل سراسری به قفل per-account در این مأموریت نیست.

در تمام subprocessها timeout و cleanup مشخص داشته باش. تزریق مرگ فقط PID فرزند خود تست را هدف بگیرد. آزمون crash فرایند تضمین قطع برق/خرابی دیسک نیست؛ در گزارش بیش از شاهد ادعا نکن. اگر خطای replace عادی را هم آزمودی، از crash ناگهانی جدا گزارش کن.

## رگرسیون و محدودیت‌ها

- چهار preview مستقل (واجد fill، فاقد bar، expiry، late ambiguity) از entrypoint باید بدون flagهای تغییر، bytes حساب را ثابت نگه دارند. به exit code اکتفا نکن؛ status درست و عدم تغییر event/order/cash/holdings را هم assert کن.
- observation صریح، expiry و late ambiguity صریح باید هنوز از writer محافظت‌شده بگذرند؛ تکرار ورودی یکسان رویداد تکراری نسازد. در preview تاریخچه را ننویس.
- ثبت تصمیم و mark از entrypointهای فعلی، اعتبارسنجی strict و نمونه‌های عددی باقی بمانند. مسیر legacy fill همچنان با پیام مهاجرت متوقف بماند.
- تست‌های لازم را در pytest نگه دار؛ به یک گزارش دستی یا probe با exit صفر اکتفا نکن. fixtureهای malformed guard قدیمی را در صورت نیاز معتبر و به رفتار جدید سازگار کن، اما صرفاً حذف/skip نکن.
- baseline: `& .venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py -q`، به‌اضافهٔ فایل‌های تست جدید و syntax check فایل‌های touched. تعداد/فرمان واقعی را گزارش کن؛ از قبل تعداد هدف تعیین نکن.
- شبکه و scheduler اجرا نشوند؛ حساب جاری، دفتر رسمی، قرارداد مدل، P1/P3، وزن‌ها، قواعد اقتصادی 1.2.0 و O00 تغییر نکنند. از default مسیرهای ACCOUNT/RUN/PUBLIC واقعی در تست استفاده نکن. صرفاً hash/read-only validation فایل محافظت‌شده مجاز است.
- مأموریت ۲، چرخهٔ فروش/خرید بعدی، رفع تقویم یا Codal و اصلاح UI را شروع نکن. ایراد ساعت موتور آینده خارج از دامنه است.

## تحویل قابل بازبینی

در `docs/paper_portfolio_delivery/task-01b/` بنویس:

- `REPORT.fa.md`: رفتار replay/تعارض، تعریف receipt و fingerprint، نقشهٔ writerها، نقاط دقیق crash، سیاست retry، فرمان‌ها و نتیجه‌ها، محدودیت‌ها و فایل‌های تغییرکردهٔ این مأموریت جدا از dirt قبلی.
- `result.json`: task_id=01b، status، parent_task_01_status، changed_files، tests و acceptance_results با مسیر شاهد. سه پرچم existing_account_modified، official_ledger_modified و model_contract_changed باید واقعاً false باشند.
- evidence برای replay، crash و concurrency با exit code فرزندان، نقطهٔ قطع/handshake، hash پیش/پس، cash/holding/event_count و نتیجهٔ recovery؛ همه TEST_FIXTURE و بدون اطلاعات حساس.
- manifest نهایی سورس/تست/گزارش با path/size/SHA-256، پس از آخرین تغییر و نه پیش از آن؛ فایل‌های untracked لازم و وضعیت ignore را مشخص کن.

status=PASS برای والد فقط وقتی همهٔ پذیرش‌های مأموریت ۰۱، شامل باقی‌ماندهٔ نوع رویداد، replay، crash/concurrency و چهار preview با شاهد کامل پاس شده‌اند. در صورت مانع واقعی، PARTIAL و مورد دقیق را گزارش کن؛ «تست اجرا نشد» را PASS حساب نکن. پس از تحویل، برای بازبینی صبر کن و مأموریت ۲ را خودکار شروع نکن.
