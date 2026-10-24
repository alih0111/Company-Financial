# TF-03 — گزارش اجرا

وضعیت تحویل: **PARTIAL / آماده‌سازی شروع BLOCKED**. حساب اصلی، scheduler، قواعد pinشده و دفتر رسمی در این تلاش فعال یا تغییر داده نشدند. TF-02B بدون بازبینی مجدد پذیرفته‌شده تلقی شد.

## پیش‌نمایش عمومی زنده

فرمان محدود و بدون توکن:

```text
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_public_market_calendar.py --window-start 20261024 --candidate-symbol غاذر --output-dir docs/paper_portfolio_delivery/task-tf03/live/public-calendar --cross-check-lookback-days 14 --max-cross-symbols 3
```

اجرای زنده موفق بود: پنج endpoint عمومی HTTP 200 دادند، دو تاریخچهٔ شاخص کیفیت `CORROBORATED_PUBLIC` داشتند، تعارضی دیده نشد و تطبیق سهام ۱ نماد واجد شرایط از ۲۵۴ رکورد را بررسی کرد. watermark دو جزء یکسان `20261024` بود، اما completion طبق قرارداد رسمی تأییدنشده است. برای تاریخ تصمیم `20261024` نتیجه `NO_NEW_SESSION` و شمار جلسهٔ پس از تصمیم صفر بود؛ این مجوز fill نیست. manifest و rawهای فشردهٔ تغییرناپذیر در پوشهٔ `live/public-calendar/` هستند؛ fixture مصنوعی با live مخلوط نشده است.

## چرخه و موانع

چرخهٔ آفلاین TF-03 (ثبت تصمیم عمومی در subprocess، resolve، preview بی‌تغییر، fill، mark، replay، سناریوهای کیفیت، crash/concurrency) در این اجرا انجام نشد و PASS نمی‌گیرد. ثبت تصمیم فعلی مسیرهای ثابت دارد و binding چهارسطحی public را هنگام ثبت نمی‌سازد؛ apply نیز مسیر حساب و قواعد ثابت دارد؛ wrapper PowerShell مسیرهای ثابت و انتخاب apply خودکار دارد. اجرای این زنجیره بدون اصلاح و آزمون اتصال، خطر نوشتن خارج از temp دارد. `paper_cycle.main` نیز مراحل دیگر با مقصدهای ثابت اجرا می‌کند، پس انتخاب ایمن اینجا wrapper واقعی اصلاح‌شده نبود.

رتبه‌بندی موجود 166/254 نماد امتیازدار و وضعیت `PREPARATION_UNCONFIRMED` دارد. بنابراین شرط پلن برای snapshot معتبر شروع تازه احراز نشده است. حساب legacy به public تبدیل نشد و حساب draft عمومیِ واجد صلاحیت یا fill واقعی ساخته نشد. هیچ fixture موفقی به‌جای اجرای زنده گزارش نشده است.

## وضعیت‌ها

- `offline_lifecycle`: NOT_RUN
- `cycle_integration`: BLOCKED — اتصال مسیرهای temp/provider/hash کامل نشده
- `live_preview`: PASS محدود — دریافت عمومی و resolve؛ `NO_NEW_SESSION`، بدون fill
- `activation_package`: BLOCKED — رتبه‌بندی فعلی برای شروع تازه معتبر نیست
- `live_account_activated`: `false`

شواهد hash فایل‌های محافظت‌شده و manifest تمام فایل‌های این تحویل در `result.json` و `artifact-manifest.json` ثبت شده‌اند. برای تکمیل TF-03 باید اتصال ایزوله‌شده پیاده‌سازی شود و سپس چرخهٔ آفلاین و suite نهایی طبق پلن اجرا شوند.
