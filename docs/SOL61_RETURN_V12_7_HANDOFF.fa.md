# تحویل V12.7

اجرای کامل سند V12.7 در `ranking_research/output/return_v12_7/v12_7_20261020T020000Z/` ثبت شده است. گزارش نهایی: `docs/RETURN_V12_7_FINAL.fa.md`.

## نتیجهٔ عملی

- رابطهٔ تاریخی w0 با بازده بعدی مثبت بود: میانگین Spearman برابر ۰٫۰۹۸ در افق ۲۱ و ۰٫۱۶۱ در افق ۶۳ جلسه؛ top10 به‌ترتیب ۳٫۰۹٪ و ۹٫۷۳٪ در برابر ۱٫۲۲٪ و ۴٫۵۶٪ جهان مساوی.
- capture top10 از دهک برتر آینده در افق ۶۳ برابر ۹۷/۱٬۴۷۶ مشاهدهٔ نماد-تاریخ (۶٫۶٪) بود؛ top20 برابر ۲۰۳/۱٬۴۷۶ (۱۳٫۸٪).
- مقایسهٔ تاریخی A/B/C به‌ترتیب پایان ۲۲۸٫۴۳۸م، ۲۵۹٫۷۷۲م و ۳۳۴٫۲۸۸م تومان داشت؛ دفتر مشارکت نماد/بلوک و کارمزد اختلاف C-A را آشتی داد.
- اختلاف تاریخی C و A برابر ۱۰۵٫۸۵۰ میلیون تومان آشتی شد: ۹۹٫۸۰۱ میلیون تفاوت P&L قیمت mark و ۶٫۰۴۹ میلیون صرفه‌جویی هزینه. تغییر سیاست‌های C در هر شش بلوک است؛ C با B در بلوک‌های ۰، ۲ و ۴ فرق دارد.
- آزمون چهار سیاست: A=۲۲۸٫۴۳۸م؛ نگهداری rank20 با cadence10=۲۰۱٫۰۱۴م؛ cadence21 و خروج rank10=۲۰۸٫۳۱۲م؛ cadence21 و خروج rank20=۲۲۳٫۹۳۱م. اثر نگهداری تابع cadence است. افت بیشینه و HHI تمرکز هم به‌صورت توصیفی ثبت شدند.
- دفتر مستقل هر چهار replay با خطای حداکثر `2.98e-7` تومان پاس شد. آزمون تغییر دادهٔ پس از cutoff برای انتخاب‌های B/C، ۱۲/۱۲ PASS است؛ این اثبات کامل PIT ورودی خام نیست.
- پیشنهاد مسیر: تمرکز مرحلهٔ بعد بر زمان‌بندی خرید/نگهداری و سنجش آینده‌نگر ثبت‌شده؛ فعلاً وزن‌ها را جست‌وجو نکنید. آزمون حاضر تاریخی و غیرمستقل است.

## صفحه و محدودیت آمادگی

بخش تشخیص بازده به route موجود `/ranking/research/v12-1` اضافه شد. رتبه/preview A از دادهٔ ذخیره‌شدهٔ V12.6 حفظ شده؛ قیمت واقعی تا 2026-10-12 است و عنوان امروز ندارد. B/C فاقد selector جاری‌اند. برای A هم preview آماده است، اما تصمیم آینده‌نگر یا اجرا ثبت نشده است. ارتباط همهٔ برندگان افق ۶۳ با رتبه و معاملات A/C در `winner_trade_crosswalk.csv` است.

هیچ درخواست شبکه، کدال یا اتصال DB انجام نشد. مرورگر و دانلود واقعی CSV در این اجرا بازآزمایی نشد؛ build آفلاین و مدل داده/CSV آزموده شد.

## آزمون و بازتولید

۲۶ آزمون مرتبط موفق شدند. آزمون `test_failure_before_atomic_publish_preserves_previous_snapshot` با کلید معتبر `latest_published_run` در fixture موقت اجرا شد و pointer و hash snapshot قبلی را حفظ کرد؛ اجرای شکست‌خورده منتشر نشد.

```powershell
$env:RETURN_V12_7_RUN_ID = 'v12_7_<unique-UTC-run-id>'
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_7.run
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_7.finalize
.\.venv\Scripts\python.exe -B -m pytest ranking_research/return_v12_7/test_analysis.py ranking_research/return_v12_6/test_delivery.py ranking_research/return_v12_5/test_refresh.py ranking_research/return_v12_4/test_current_snapshot.py ranking_research/return_v12_3/test_repairs.py -q
cd client
$env:npm_config_offline='true'; npm run build
```

برای اجرای دوباره، یک شناسهٔ UTC یکتا در متغیر بالا قرار دهید؛ خروجی موفق فعلی را بازنویسی نکنید. مدخل‌های تاریخی از manifest اجرای موفق hash شده‌اند. انتساب A/B/C از V12.2/V12.3 مهرشده استفاده شد و دوباره به‌عنوان کشف مستقل ساخته نشد. جزئیات تکرار، limitationها و hashهای payload/page در `delivery_manifest.json` همان پوشه ثبت می‌شوند.
