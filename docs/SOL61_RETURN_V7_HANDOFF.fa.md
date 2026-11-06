# تحویل V7

اجرا: `D:\RFA\Company-Financial\ranking_research\output\return_v7\v7_20261016T195745152277Z`

گزارش نهایی: docs/RETURN_V7_FINAL.fa.md. نتیجه: هر سه نامزد نسبت به S2 مشترک و طبیعی در هر دو بلوک کامل ضعیف‌تر؛ هیچ finalist، stress، جامعهٔ طبیعی نامزد یا دورهٔ مستقل اجرا نشد. چهار خانهٔ ماتریس تازه و پنج مسیر تشخیصی، چهار مرجع بازاستفاده، صفر شکست مالی. S2 تولیدی ارتقا نیافت. حساب اقتصادی کامل نامعلوم.

کنترل فقط‌خواندنی (پس از seal آزموده شود):
```
.venv/Scripts/python.exe -B -m ranking_research.return_v7_verify --run D:\RFA\Company-Financial\ranking_research\output\return_v7\v7_20261016T195745152277Z
```
فرمان بالا علاوه بر خروجی داخلی، public assets را هم بررسی می‌کند. فرمان ثبت‌شدهٔ `.venv/Scripts/python.exe -B -m ranking_research.return_v7.run all --run D:\RFA\Company-Financial\ranking_research\output\return_v7\v7_20261016T195745152277Z` پس از seal فقط خروجی داخلی و V6 را verify می‌کند؛ هرگز replay نمی‌کند. برای تحویل کامل از wrapper بالا استفاده کن. تغییر داده/قاعدهٔ مالی نیازمند اجرای جدید است؛ وزن یا افق دیگر را خودکار جست‌وجو نکن. کد ثبت‌شده و کد تحویل آرشیو شده‌اند. V6 همچنان با فرمان handoff خودش فقط‌خواندنی verify می‌شود. dirty git اولیه و تغییرات تاریخچهٔ معاملات کاربر محفوظ‌اند؛ هیچ commit/reset/clean انجام نشد.

کاسپین: از2024-10-22 تا آخرین مشاهده2026-02-25 رشد شاخص۳٫۳۳برابر؛ ارزش فرض سرمایه‌گذاری کامل حدود۳۳۱٫۴میلیون، اما آن فرض ظرفیت را رعایت نمی‌کند. حساب محدود به ظرفیت حدود۱۱۴٫۹۸میلیون و خرید اولیه۶٫۴۴میلیون؛ فروش انتهای اسفند احراز نشد. ابتدا رتبه۱۲، اولین خرید S2 در2025-05-24؛ رتبه، داده، خروج هدف و fill را با هم اشتباه نگیر. وضعیت سه‌برابرشدن نقد واقعی و اقتصاد رویداد را قطعی ننام. winner_summary/coverage و exclusion_census را پیش از نسبت‌دادن همهٔ جاماندن به فروش زودهنگام بخوان.

صف recovery_refined تعداد تصمیم مالی بالقوه را مستقل از بازده اولویت می‌دهد. Darou سود نقدی۱۰۷۰ریالی از سند رسمی تأیید شد؛ استحقاق/وصول باز است. سند رسمی کاسپینِ۲۰۲۶ به May2025 وصل نشد. پورتال رسمی سهامداران timeout شد؛ تکرار نکن. منابع قیمت بعدV6 از قبل مصرف‌شده و فاقد زنجیرهٔ اقتصادی متصل‌اند؛ آن‌ها را holdout دست‌نخورده ننام.

snapshot دستی تاریخیِ بدون معامله:
```
.venv/Scripts/python.exe -B -m ranking_research.return_v7.run snapshot --run D:\RFA\Company-Financial\ranking_research\output\return_v7\v7_20261016T195745152277Z --date 2024-10-30
```
خروجی جدا در return_v7_manual_snapshots؛ یک تاریخ را بازنویسی نمی‌کند. این فرمان آزمون اتصال است و snapshot تازهٔ امروز نیست.

capture آینده، فقط با بستهٔ جدیدِ معتبر و هش‌شده؛ هیچ scheduler فعال نیست:
```
.venv/Scripts/python.exe -B -m ranking_research.return_v7_capture --help
```
پارامترها --run --date --panel --manifest --output. manifest باید panel_sha256، decision_date، price_chain_asof، publication_chain_verified، price_chain_verified، identity_chain_verified، corporate_actions_asof_verified و files با مسیر/هش داشته باشد. همهٔ بدنه‌های مصرف‌شده در sources.sha256 باید در files باشند؛ ساعت انتشار پیش از cutoff بررسی می‌شود. گواهی‌های بسته، ادعای کنترل مستقل خارج از این ابزار نیستند. برای آینده بدون مدرک، ورودی فرضی نساز؛ حساب یا معاملهٔ واقعی اجرا نمی‌شود.

صفحهٔ /ranking/research بخشV7 با شش مرجع/خانه، دو پنجرهٔ کاسپین و۳۷تصمیم دارای علت دارد. دادهٔ return-v7 مستقل از return-v6 و دفتر۴۰۳معاملهٔ S2 است. public return-v7 و provenance با manifest مهر شده‌اند. تغییر صفحهٔ بعدی مجاز است، اما فایل‌های مهرشدهٔ پژوهش را بازنویسی نکن.
