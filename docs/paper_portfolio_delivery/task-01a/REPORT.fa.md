# گزارش مأموریت ۰۱A: ذخیره‌سازی حساب کاغذی

## نتیجه

**PASS برای دامنهٔ ۰۱A.** اعتبارسنجی schema، محافظت append-only از تاریخچه، گردکردن mark و قابل‌تحویل بودن فایل‌های سورس اصلاح و آزموده شد. نتیجهٔ مأموریت والد ۰۱ همچنان `PARTIAL` می‌ماند؛ replay عملیاتی fill و crash/concurrent commit کامل متعلق به ۰۱B هستند.

## رفتار قبل و بعد

- **اعتبارسنجی:** قبلاً `int()` و defaultهای صفر و `if accounting` می‌توانستند cash کسری/بدنوع، accounting یا فیلدهای ضروری مفقود و P&L نمایشی غلط را از اعتبارسنج عبور دهند. اکنون schema حداقلی account، holding، event و accounting صریح است. پول Toman باید integer واقعی (bool، float، رشته و NaN/Infinity پذیرفته نمی‌شوند) باشد؛ سهم integer نامنفی است؛ ارزش‌های دارایی و fee نامنفی‌اند؛ P&L صحیح می‌تواند منفی باشد. شرط holdings value، NAV و هر دو تعریف P&L بررسی می‌شوند. خطا قبل از replace رخ می‌دهد و bytes قبلی حفظ می‌شوند.
- **تاریخچه:** قبلاً snapshot رویدادهای قدیمی alias بود و nested mutation می‌توانست مبنای مقایسه را هم عوض کند. اکنون snapshot مستقل گرفته می‌شود؛ حذف، تغییر payload/شناسه و reorder رد می‌شود و فقط append انتهایی مجاز است. خود `write_account_atomic` نیز قفل می‌گیرد، schema و تاریخچهٔ فعلی را می‌سنجد و سپس replace می‌کند؛ entrypointهای موجود قفل را از قبل از read نگه می‌دارند. قفل transaction تو‌در‌تو در همان thread با RLock مدیریت می‌شود و OS lock فقط در لایهٔ بیرونی گرفته می‌شود.
- **گردکردن mark:** قبلاً `int(round(...))` مقدار ۱٬۰۰۵ ریال را ۱۰۰ تومان می‌کرد. اکنون `rial_to_toman` با Decimal و `ROUND_HALF_UP` آن را ۱۰۱ تومان می‌کند. محاسبهٔ پول fill و مسیر قدیمی شبیه‌سازی هم از helper مشترک/Decimal استفاده می‌کنند؛ نرخ fee، lot، تعداد و قواعد 1.2.0 دست‌نخورده‌اند.
- **بسته‌بندی Git:** `.gitignore` اکنون استثناهای محدود برای store، دو سورس لازم، و گزارش/نتیجه/evidence همین task دارد. خروجی‌ها، آرشیوها، credentialها و پوشه‌های عمومی پژوهش unignore نشده‌اند.

## نقشهٔ مسیرهای نویسندهٔ حساب

| Entry point | داده‌ای که تغییر می‌دهد | تابع commit مشترک |
|---|---|---|
| `apply_paper_fill.py` | fill، expiry و observation صریح سفارش | `paper_account_store.write_account_atomic`؛ observation از همین مسیر می‌گذرد |
| `register_paper_decision.py` | تصمیم و سفارش pending | `paper_account_store.write_account_atomic`، زیر `account_write_lock` از پیش از read |
| `check_paper_account.py` | fill قدیمی (متوقف با پیام مهاجرت) و mark | mark از `paper_account_store.write_account_atomic`، زیر قفل کل عملیات |
| `refresh_paper_decision_status.py` | فقط فایل‌های status و گزارش | حساب فقط خوانده می‌شود |
| `paper_cycle.py` | فقط manifest/status چرخه | حساب فقط خوانده می‌شود |
| `check_paper_order.ps1` | فقط خواندن و فراخوانی evaluator | هیچ نوشتن مستقیم؛ `apply_paper_fill.py` نویسنده است |

محافظت مشترک event history در مسیر commit واقعی همهٔ سه writer بالا داخل `write_account_atomic` انجام می‌شود؛ صرفاً wrapper `read_modify_write` نیست.

## آزمون‌ها و نتایج واقعی

فرمان پایه و مجموعهٔ regression:

```powershell
& .venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py -q
```

**۳۷ passed in 3.53s، صفر شکست.** موارد تازه شامل ۱۶ ورودی منفی از fixture معتبر، حفظ bytes/hash پس از رد، nested mutation/deletion/reorder رویداد قدیمی، append مجاز، mark نیم‌تومان و ثبت تصمیم از entrypoint با فایل‌های temp است.

فرمان syntax check:

```powershell
& .venv/Scripts/python.exe -X utf8 -m py_compile ranking_research/paper_account_store.py ranking_research/future_eval_v12_30/apply_paper_fill.py ranking_research/future_eval_v12_30/register_paper_decision.py ranking_research/future_eval_v12_30/check_paper_account.py
```

موفق، exit code صفر. اعتبارسنجی read-only حساب موجود نیز موفق شد: `CURRENT_ACCOUNT_READ_ONLY_VALIDATION=PASS`؛ خود فایل حساب نه نوشته شد و نه migrate.

شاهد عددی مستقل در `evidence/acceptance.json`:

- **TEST_FIXTURE خرید:** ۱۰۰٬۰۰۰ تومان، ۱٬۲۳۴ ریال، ۸۰۶ سهم، gross=۹۹٬۴۶۰، fee=۴۹۷، نقد=۴۳، NAV=۹۹٬۵۰۳، P&L=−۴۹۷.
- **TEST_FIXTURE mark:** یک سهم با ۱٬۰۰۵ ریال، ارزش=۱۰۱، نقد=۹۹٬۸۹۹، NAV=۱۰۰٬۰۰۰، P&L=۰.
- دوازده ورودی خرابِ مجزا reject شدند و SHA-256 bytes پیش/پس در هر مورد یکسان است. snapshot تاریخچهٔ nested هم hash قبل و بعد برابر دارد. pytest همچنین حذف/reorder را رد و append را می‌پذیرد.

## وضعیت Git و فایل‌ها

قبل از کار status شامل تغییرات قبلی UI، چرخه، Codal و تست هدف بود؛ همگی حفظ شدند. تست هدف گسترش یافت. `git check-ignore -q` برای سه منبع جدید و فایل‌های task-01a مقدار false برمی‌گرداند؛ `git status --short --untracked-files=all` آن‌ها را untracked نشان می‌دهد، نه ignored.

فایل‌های افزوده‌شدهٔ سورس (untracked تا زمان انتخاب کاربر برای stage):

- `ranking_research/paper_account_store.py`
- `ranking_research/future_eval_v12_30/register_paper_decision.py`
- `ranking_research/future_eval_v12_30/check_paper_account.py`

تغییرات دیگر همین task: `.gitignore`، `apply_paper_fill.py`، `test_paper_account_atomic.py` و فایل‌های task-01a. `evidence/artifact-manifest.json` مسیر، اندازه و SHA-256 فایل‌های تحویل را فهرست می‌کند.

## محدودیت‌های باقیماندهٔ ۰۱B

Replay اجرایی fill یکسان/متعارض، crash injection قبل/بعد از replace، آزادشدن قفل پس از crash و دو commit واقعی هم‌زمان هنوز در این مرحله PASS نشده‌اند و اینجا اجرا/ادعا نشده‌اند. عملیات فروش و دفتر دوبل هم خارج از دامنه‌اند.

حساب جاری، دفتر رسمی، scheduler، شبکه، قرارداد مدل و قواعد اجرای 1.2.0 تغییر نکردند. `docs/paper_portfolio_delivery/task-01/review/REVIEW.fa.md` و `results.json` و شواهد قبلی بازبینی دست‌نخورده ماندند.
