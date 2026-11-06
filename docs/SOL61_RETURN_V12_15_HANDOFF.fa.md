# تحویل V12.15

وضعیت: `COMPLETE_WITH_LIMITATIONS` · شناسه اجرا: `v12_15_20261021_local_matrix_05`

- گزارش: `docs/RETURN_V12_15_FINAL.fa.md`
- صفحهٔ موجود: `/ranking/research/v12-1`؛ جدول کامل ۳۶ مسیر و مقایسهٔ کنترل/انتخاب زمانی در صفحه اضافه شد.
- پوشهٔ نسخه‌دار: `ranking_research/output/return_v12_15/v12_15_20261021_local_matrix_05/`
- جدول کامل نامزدها: `client/public/research/return-v12-15-all_candidates.csv`
- جدول سالانهٔ ۳۶ نامزد و کنترل A: `client/public/research/return-v12-15-all_candidates_annual.csv`
- NAV روزانه، معاملات، تصمیم‌ها و مشارکت نمادها برای همهٔ نامزدها در همان پوشه و public/research منتشر شد.
- benchmark و فرصت‌ها: `market_opportunity.json`؛ زمان رتبه/خرید/فروش پنج برنده در `control_531_winner_timing.json`.
- مسیر انتخاب زمانی: `time_selection.json` و CSVهای choices/NAV/trades/decisions.
- دو کنترل با خطای صفر تومان بازتولید شدند؛ cadenceهای ۱۰/۲۱/۶۳ پوشش کامل موعد داشتند؛ ۳۶/۳۶ ledger و سهم نمادها کمتر از یک تومان خطا داشتند.
- بهترین نتیجهٔ تاریخی: ۱٬۲۳۰٬۰۲۷٬۱۰۸٫۵۸ تومان؛ مسیر انتخاب زمانی: ۱۴۷٬۴۴۴٬۸۴۰٫۸۷ تومان در بازهٔ کوتاه‌تر از ۱۴۰۲/۰۱/۰۵ تا ۱۴۰۴/۱۲/۰۵.
- شبکه=۰، کدال=۰، DB=۰؛ غربال و ثبت آینده ثابت ماندند.
- محدودیت‌ها: cohort ثابت ۲۵۴ نماد؛ نتیجهٔ retrospective؛ نبود شاخص رسمی محلی مستند؛ داده فقط تا ۱۴۰۴/۱۲/۰۵ برای قیمت+score؛ منابع adjusted price و dividend مستقل تأیید نشده‌اند.
