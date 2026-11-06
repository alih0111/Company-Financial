# تحویل V3

اجرا: `D:\RFA\Company-Financial\ranking_research\output\return_v3\v3_20261016T090423998625Z`

وضعیت: مسیرهای مستقل اجرا و تحویل شدند؛ گواهی اقتصادی و تمدیدD2 به علل ردیفی blockers.csv مشروطند. فرایند مالی پس از پایان فرمان فعال نیست.

کنترل مستقل پیاده‌شده: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run verify --run "D:\RFA\Company-Financial\ranking_research\output\return_v3\v3_20261016T090423998625Z"`

ادامهٔ همان کد و ورودی در صورت قطع اجرای تحویل: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run all --run "D:\RFA\Company-Financial\ranking_research\output\return_v3\v3_20261016T090423998625Z"`

این فرمان مسیرهای سازگار را از payload کامل برمی‌دارد؛ تغییر کد/داده شناسهٔ تازه می‌خواهد. برای دادهٔ جدید ابتدا ثبت واقعی اجرا: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run register`. فرمان موجود به‌طور پیش‌فرض منبعV2 ثابت را مصرف می‌کند؛ parser/ورود خودکارِ بستهٔ اقتصادی جدید ادعا نشده و قبل از اجرای تازه باید پیاده و ثبت شود.

ثبت دستی مشاهدهٔ بدون سفارش برای تاریخ روز تهران: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.ranking --run "D:\RFA\Company-Financial\ranking_research\output\return_v3\v3_20261016T090423998625Z" --observe-date YYYY-MM-DD`. YYYY-MM-DD باید با تاریخ واقعی روز جایگزین شود؛ تاریخ رتبه و زمان مشاهده جدا ثبت می‌شوند.

فرانت: `/ranking/research`؛ فایل سرو‌شده client/public/research/return-v3.json با شناسهٔ صریح همین اجرا پین شده و انتخاب خودکار آخرین پوشه نیست. خروجی تاریخی را امروز معرفی نکن. اسناد V2، کد تولید اصلی، کارگزاری و /ranking جایگزین نشده‌اند.
