# تحویل V12.13 — اصلاح ظرفیت no-trim

اجرا: `ranking_research/output/return_v12_13/v12_13_20261019T231848Z/`
وضعیت: `COMPLETE_WITH_VALIDATION_FAILURES`؛ علت ۶۵۶۰ روز position excess در A از شواهد موجود UNKNOWN است و این بازو بدون تغییر ماند.
گزارش: `docs/RETURN_V12_13_FINAL.fa.md`
صفحهٔ موجود: `/ranking/research/v12-1`
CSV کامل ۸۲ مسیر قدیم/اصلاح‌شده: `client/public/research/return-v12-13.csv`
CSV صف/مشارکت/موقعیت: `client/public/research/return-v12-13-queue-fills.csv`, `client/public/research/return-v12-13-symbol-contributions.csv`, `client/public/research/return-v12-13-position-excess.csv`

موتور نسخه‌دار `V12.13-no-trim-capacity-guard-1` فقط guard ظرفیت entrant را اصلاح می‌کند و پارامترهای N/cadence/offset/exit rank را صریح می‌گیرد. خطای legacy با fixture شکست بازتولید شد؛ نتایج و ثبت‌های V12.12 حفظ شده‌اند. از ۸۲ مسیر فقط دو NAV نهایی تغییر کرد؛ شش کنترل legacy زیر یک تومان بازتولید شدند. سود قیمت، هزینه‌ها، معاملات پرشده، صف‌های بدون fill و مشارکت همه نمادها جداگانه ثبت شده‌اند.
در صفحه V12.13 جدول کامل routeها، خلاصهٔ شش خانواده و CSV مقایسه نمایش داده می‌شود. ثبت‌های آینده شروع نشده‌اند و پیش‌فرض غربال ثابت است. شبکه/کدال/DB صفر. build آفلاین PASS؛ مرورگر/دانلود واقعی اجرا نشد.
