# TF-02B — گزارش تحویل (PARTIAL)

تاریخ: ۲۰۲۶-۱۰-۲۴

## تغییرات انجام‌شده

- اعتبارسنجی provider پیش از اجرای مسیر تقویم در مصرف‌کنندگان افزوده شد. قرارداد `public-paper-v1` با نگاشت صریح به `public-index` سنجیده می‌شود؛ حساب legacy بی‌binding در انتخاب public رد می‌شود و binding ناقص/متناقض خطا می‌دهد.
- SHA-256 بایت‌های واقعی فایل قواعد با `active_decision.execution_rules.sha256` در کنترل مشترک بررسی می‌شود.
- acquisition عمومی چرخه مقصد یکتای خودش را می‌سازد و manifest بیرون آن یا pointer با شناسهٔ ناسازگار را رد می‌کند. fixtureهای مسیر acquisition نیز artifact را حین stage و در مقصد همان invocation می‌سازند.

## آزمون‌های اجراشده

- suite تحویل TF-02A پس از تغییر کد: **۱۴۹ passed، صفر شکست** در ۳۵۸٫۰۵ ثانیه.
- سه regression مربوط به fixture سالم acquisition: **۳ passed، صفر شکست**.
- شبکه استفاده نشد؛ حساب واقعی و فایل‌های محافظت‌شده فقط hash شدند. hash شش فایل محافظت‌شده با baseline تحویل TF-02A برابر ماند. جزئیات در `result.json` و `evidence/evidence.json` است.

## موارد باز

این تحویل PARTIAL است: آزمون مستقل چهار ترکیب account/provider از `apply.main`، ماتریس تغییر بایت قواعد در سه entrypoint، و fault matrix کامل acquisition (از جمله اجرای متوالی) هنوز اجرا/ثبت نشده‌اند. بنابراین ادعای PASS برای TF-02B داده نمی‌شود.

TF-03 آغاز نشده است.
