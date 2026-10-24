# TF-02B — گزارش نهایی

تاریخ: ۲۰۲۶-۱۰-۲۴. نتیجه: **PASS در محدودهٔ TF-02B**. این نتیجه فقط سه گروه پذیرش همین مأموریت را پوشش می‌دهد. TF-03 و فعال‌سازی حساب واقعی انجام نشده‌اند. گزارش PARTIAL قبلی با فایل‌های همراه در `historical/TF02B-PARTIAL-20261024T2210Z/` حفظ شده است. اسناد بازبینی دست‌نخورده‌اند.

## ۱. قرارداد انتخاب provider

اعتبارسنجی provider پیش از شاخه‌های public و nscstart در apply، refresh و acquisition اجرا می‌شود. اعتبارسنجی binding چهار سطح را بررسی می‌کند؛ مقدار ناقص یا نامعتبر legacy تلقی نمی‌شود. نگاشت `public` به `public-index` صریح است. برای public/public و legacy/nscstart کنترل‌های موفق apply اجرا شدند؛ public/nscstart، provider حذف‌شده/پیش‌فرض، preview، observation و legacy/public همگی با `CALENDAR_POLICY_MISMATCH` و بدون تغییر حساب رد شدند. status و مرحلهٔ acquisition چرخه همان علت را گزارش می‌کنند؛ چرخه پیش از credential یا stage متوقف می‌شود. بازپخش روز بعد و مسیر سالم legacy در suite موجود باقی ماندند.

## ۲. hash قواعد pinشده

هر مصرف‌کننده قواعد را یک‌بار به bytes می‌خواند، SHA-256 همان bytes را با pin تصمیم تطبیق می‌دهد و از همان snapshot برای parse/binding استفاده می‌کند. قواعد ناخوانا/گمشده علت کنترل‌شده و readiness=false می‌دهند. برای whitespace و تغییر معنایی بدون pin تازه، fill/status/acquisition همگی `PINNED_EXECUTION_RULES_HASH_MISMATCH` می‌دهند. fixture قواعد تغییرکرده با pin تازهٔ temp در هر سه مسیر کنترل سالم است. آزمون چرخه همچنین فایل روی دیسک را در حین stage عوض می‌کند و نشان می‌دهد مصرف از snapshot معتبر آغازین استفاده می‌کند. هیچ pin حسابی خودکار اصلاح نمی‌شود.

## ۳. تعلق خروجی acquisition به invocation

هر اجرا مقصد تازه و یکتا دارد. خروجی فقط پس از کنترل hash pointer/manifest، برابری run_id آن دو و قرارگرفتن مسیر resolveشدهٔ manifest در مقصد همان invocation مصرف می‌شود. stage جعلی سالم raw، manifest و pointer را حین اجرا در مقصد می‌سازد. پنج حالت معیوب (بدون خروجی، مسیر بیرون مقصد، اختلاف run_id، اختلاف hash، و شکست stage با pointer قدیمی) همگی رد شدند. دو اجرای سالم متوالی manifestهای خود را مصرف کردند و فایل اجرای اول حفظ شد. این‌ها آزمون مستقیم `acquire_order_calendar` هستند، نه اجرای کامل `paper_cycle.main`.

## آزمون نهایی

فرمان کامل و خروجی پس از آخرین تغییر کد و regression:

```text
.venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_public_market_calendar.py ranking_research/tests/test_paper_calendar_interface.py ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py ranking_research/tests/test_paper_calendar_tf02a_regressions.py ranking_research/tests/test_paper_calendar_tf02b_regressions.py -q --basetemp D:/RFA/Company-Financial/.pytest_tmp_tf02b_deliver
168 passed, 0 failed in 453.99s
```

۱۴۹ آزمون موجود و ۱۹ regression یکتای TF-02B اجرا شدند؛ تفکیک یکتا بر اساس فایل در `result.json` آمده است. شواهد خروجی entrypointها، حالت‌های رد و hash حساب‌های temp در `evidence/evidence.json` ثبت شده‌اند. hash شش فایل محافظت‌شده با baseline پیشین برابر است و پس از اجرا نیز برابر ماند. شبکه و توکن استفاده نشدند؛ حساب واقعی فقط hash شد.

## فایل‌های تحویل

`artifact-manifest.json` اندازه و SHA-256 فایل‌های کد، تست، گزارش، نتیجه، شواهد و snapshot تاریخی PARTIAL را فهرست می‌کند؛ خود manifest را hash نمی‌کند.
