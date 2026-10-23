# گزارش مأموریت ۰۱B: replay و مقاومت commit

## نتیجه

**PASS برای مأموریت والد ۰۱** بر پایهٔ آزمون‌های این تحویل و دامنهٔ مشخص‌شده. هیچ تغییر حساب جاری، دفتر رسمی، قرارداد مدل، قواعد اقتصادی ۱.۲.۰ یا O00 انجام نشد. همهٔ حساب‌ها، manifestها و rawهای آزمون در temporary directory ساخته شدند.

## رفتار و پیاده‌سازی

### تاریخچهٔ append-only با نوع JSON

writer مشترک اکنون مقایسهٔ بازگشتی نوع‌حساس دارد: `true` با `1` برابر نیست و `1` با `1.0` نیز برابر نیست. ترتیب کلیدهای object نادیده گرفته می‌شود؛ ترتیب آرایه و event حفظ می‌شود. هر دو API یعنی `read_modify_write` و `write_account_atomic` تغییر نوع/محتوا، حذف و جابه‌جایی event قدیمی را پیش از replace رد می‌کنند. append معتبر مجاز است. سیاست عدد صحیح/اعشاری محافظه‌کارانه و صریح است.

### fill و receipt نسخه‌دار

fill نخستین بار با همان replace حساب، یک `fill_receipt` نسخهٔ ۱ در سفارش ثبت می‌کند. receipt شامل account/order/decision ID، جلسهٔ تعیین‌شده، hash بایت‌های قواعد pinned، insCode و هویت نماد/شرکت، shares/close/gross/fee و cash پیش از fill است. مجموعهٔ `source_sha256` دقیقاً شامل این‌هاست:

- `calendar_raw`: SHA-256 بایت‌های decompressed شدهٔ raw تقویم رسمی؛
- `candidate_daily`، `candidate_share_changes` و `last_possible_session`: SHA-256 بایت‌های decompressed شدهٔ هر raw متناظر.

فشرده‌سازی gzip، مسیر فایل، نام/مسیر manifest، زمان اجرای مجدد و ترتیب کلیدهای JSON manifest در هویت اقتصادی وارد نمی‌شوند. در عین حال هر raw دوباره از روی gzip خوانده و hash اعلام‌شده‌اش بررسی می‌شود؛ retrieval time، تطبیق manifest با raw تقویم و هویت candidate/insCode همچنان پیش‌شرط‌اند. قواعد pinned با hash واقعی فایل سنجیده می‌شوند.

محاسبهٔ replay از `cash_before_toman` داخل receipt انجام می‌شود، نه cash فعلی پس از fill/mark. پس از اعتبارسنجی همهٔ منابع، همان receipt و وضعیت داخلی منطبق، status برابر `FILL_ALREADY_APPLIED` با exit code صفر و `fill_applied=false` می‌دهد؛ bytes، timestamp، mark، شمارنده، event، نقد و holding تغییر نمی‌کنند. منبع معتبرِ متفاوت، `FILL_REPLAY_CONFLICT` می‌دهد و اصلاح را به event اصلاحی append-only جداگانه ارجاع می‌دهد. raw خراب/hash نامعتبر خطای منبع می‌دهد؛ order/fill/holding ناقص یا نامنطبق موفقیت replay محسوب نمی‌شود. holding legacy بدون receipt معتبر رد می‌شود.

### Crash، قفل و preview

تست subprocess writer واقعی را در سه نقطه قطع می‌کند: وسط نوشتن temp، پس از flush/fsync و درست پیش از replace، و بلافاصله پس از replace و پیش از بازگشت موفق. دو حالت اول bytes و JSON معتبر قدیم را حفظ کردند؛ حالت سوم JSON کامل جدید را نگه داشت. پس از هر قطع، transaction تازه زیر همان قفل commit کرد و temp رهاشده مانع کار نشد. یک crash واقعی entrypoint fill پس از replace نیز با replay موفق و bytes کاملاً ثابت بازیابی شد.

در رقابت دو فرایند RMW روی یک مسیر حساب، فرایند اول قفل را پیش از read گرفت. فرایند دوم نتیجهٔ روشن `PAPER_ACCOUNT_LOCKED` گرفت، پس از پایان اول retry کرد و هر دو event ماندند. دو fill هم‌زمان همان سفارش نیز پس از lock/retry به یک debit، یک holding و یک fill event رسیدند و تلاش دوم replay موفق شد. تست قدیمی قفل نیز اصلاح شد تا parent و child هر دو از همان حساب موقت استفاده کنند و به جای sleep از handshake timeout‌دار بهره ببرند.

هر چهار مسیر preview از entrypoint (واجد fill، فاقد bar، expiry و late ambiguity) status مورد انتظار دادند و hash/bytes، cash، holding، سفارش و event را تغییر ندادند. `--observe-order-state` همچنان opt-in است؛ observation، expiry و late ambiguity صریح از shared writer عبور می‌کنند و اجرای تکراری event دوم نمی‌سازد.

## نقشهٔ writerها

| مسیر | وضعیت در این تحویل |
|---|---|
| `apply_paper_fill.py` | fill/replay و observation/expiry صریح زیر قفل سراسری؛ commit از `paper_account_store.write_account_atomic` |
| `register_paper_decision.py` | ثبت تصمیم و سفارش زیر قفل و shared writer؛ regression قبلی همچنان در مجموعه اجرا شد |
| `check_paper_account.py` | mark-to-market زیر قفل و shared writer؛ mark نمونه و replay بعد از mark آزموده شد |
| مسیر legacy در `check_paper_account.py` | fill منسوخ با پیام مهاجرت متوقف می‌ماند |
| `refresh_paper_decision_status.py` و `paper_cycle.py` | حساب را فقط می‌خوانند؛ نویسندهٔ حساب نیستند |

## خروجی و آزمون‌های واقعی

فرمان پایه:

```powershell
& .venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py -q
```

نتیجهٔ اجرای نهایی: **59 passed in 7.74s، 0 failed**. این تعداد شامل regressionهای نوع JSON، چهار preview، observation صریح، replay تکراری/تعارض قیمت و تقویم، raw دستکاری‌شده، جابه‌جایی/بازآرایی manifest، order/fill ناسازگار، mark، ثبت تصمیم، crash و رقابت واقعی subprocess است.

```powershell
& .venv/Scripts/python.exe -X utf8 -m py_compile ranking_research/paper_account_store.py ranking_research/future_eval_v12_30/apply_paper_fill.py ranking_research/future_eval_v12_30/register_paper_decision.py ranking_research/future_eval_v12_30/check_paper_account.py
```

Syntax check موفق بود. `git diff --check` نیز موفق بود؛ فقط هشدارهای معمول line-ending برای فایل‌های دارای تغییر محلی گزارش شد.

خرید عددی مستقل (محاسبه از ورودی‌های اقتصادی، نه فراخوانی helper برای expected): سرمایه ۱۰۰٬۰۰۰ تومان، close برابر ۱٬۲۳۴ ریال، ۸۰۶ سهم، gross برابر ۹۹٬۴۶۰، fee با نرخ ۰.۵٪ برابر ۴۹۷، نقد ۴۳، NAV برابر ۹۹٬۵۰۳ و P&L برابر ۴۹۷- تومان. مثال mark قبلی ۱٬۰۰۵ ریال نیز در regression حفظ است: ارزش یک سهم ۱۰۱ تومان.

در `evidence/acceptance.json`، سناریوهای synthetic با label برابر `TEST_FIXTURE` ثبت شده‌اند؛ برای هر preview و replay، hash پیش/پس و exit/status آمده است. جدول crash و concurrency، exit فرزند، نقطهٔ قطع، hash، نقد/holding/event و recovery/retry را نگه می‌دارد. `collect_evidence.py` همین شواهد را تنها در temporary directory بازتولید می‌کند و manifest نهایی را می‌سازد.

## فایل‌های این مأموریت و dirt قبلی

فایل‌های تغییرکرده/افزوده‌شده در ۰۱B: `.gitignore`، `ranking_research/paper_account_store.py`، `ranking_research/future_eval_v12_30/apply_paper_fill.py`، `ranking_research/tests/test_paper_account_atomic.py` و فایل‌های `docs/paper_portfolio_delivery/task-01b/`. استثناهای ignore فقط همین گزارش/نتیجه و evidence لازم این task را آشکار می‌کنند؛ پوشهٔ خروجی، archive یا credential باز نشده است. manifest شامل فایل‌های محصول و تست این حوزه، `.gitignore` و گزارش/evidence است؛ خود manifest برای جلوگیری از self-reference مستثناست.

تغییرات موجود UI، cycle، Codal و سایر dirtهای پیشین دست‌نخورده حفظ شدند. فایل‌های review و شواهد task-01a بازنویسی نشدند. `client/public/research/v12-36/paper-portfolio.json` صرفاً hash/read-only شد و hash آن با شاهد ۰۱A برابر ماند؛ hash قواعد pinned ۱.۲.۰ و قرارداد مدل نیز با مقادیر ثبت‌شده در بازبینی قبلی برابر بود.

## محدودیت‌ها

تزریق `os._exit` مقاومت در برابر مرگ فرایند را در نقاط ثبت‌شده می‌سنجد؛ تضمین قطع برق، خرابی کنترلر یا ازبین‌رفتن write cache نیست. lock فعلی Windows mutex سراسری حساب است و سیاست contention در Windows fail-fast است؛ caller مجاز می‌تواند پس از پایان مالک lock دوباره تلاش کند. مسیر اصلاح fill، فروش، دفتر دوبل و چرخهٔ بعدی خارج از این مأموریت باقی می‌مانند.
