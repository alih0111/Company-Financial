# تحویل V4

اجرای صریح: `D:\RFA\Company-Financial\ranking_research\output\return_v4\v4_20261016T130610656257Z`

کار قابل‌انجام: بازیابی۲۲۵نسخهٔ اصلی از کش، بازسازی با موتور مشترک، حسابرسی پوشش،۱۳مسیر کنترل و صفحهٔ موجود تحویل شد؛ گواهی بازده اقتصادی و دادهٔ کامل بازار مسدود و صریح باقی است. هیچ فرایند خودکار مالی پس از پایان فرمان فعال نیست.

کنترل: `.venv/Scripts/python.exe -B -m ranking_research.return_v4.run verify --run "D:\RFA\Company-Financial\ranking_research\output\return_v4\v4_20261016T130610656257Z"`

ادامهٔ checkpointهای همین اجرا: `.venv/Scripts/python.exe -B -m ranking_research.return_v4.run all --run "D:\RFA\Company-Financial\ranking_research\output\return_v4\v4_20261016T130610656257Z"`. کد/منبع تغییرکرده اجرای تازه می‌خواهد. فرمان verify فقط کنترل می‌کند؛ all روی خروجی تکمیل‌شده، آزمایش‌ها را تکرار نمی‌کند. برای ثبت اجرای تازه با همان قرارداد: `.venv/Scripts/python.exe -B -m ranking_research.return_v4.run register`.

صفحه: `/ranking/research` با client/public/research/return-v4.json پین‌شده به این اجرا؛ انتخاب خودکار جدیدترین پوشه ندارد. انتشار پژوهشی انجام شده، روش تولیدی ارتقا ندارد.

قدم بعدی: ابتدا blockers.csv با نماد/تاریخ/شناسه رویداد و report_source_validation.csv را بخوان. سند اصلی حق‌تقدم/استحقاق/معامله‌پذیری و رسید سرمایه‌گذار لازم است. از فرضیهٔ dividend_per_share_hypothesis مبلغ سود قطعی نساز. دادهٔ تکمیل‌شده باید در اجرای تازه و با آزمون‌های مربوط وارد شود؛ old_selector فقط با گذشته دوباره انتخاب شود. بازه‌های قبلاً دیده‌شده holdout نیستند.

در صورت قطع مرحلهٔ گزارش، فرمان واقعی اصلاح گزارش بدون بازاجرای مالی: `.venv/Scripts/python.exe -B -m ranking_research.tests.finalize_return_v4_delivery --run "D:\RFA\Company-Financial\ranking_research\output\return_v4\v4_20261016T130610656257Z"`. نسخهٔ مالی اولیه منجمد مانده و اصلاح کاهش تاریخِ خالی جدا ثبت شده است.
