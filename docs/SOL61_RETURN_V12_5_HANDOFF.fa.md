# واگذاری V12.5 — رتبهٔ آفلاین و ارزیابی روش

## وضعیت تحویل

- **درخواست تازه به کدال: صفر.** checkpoint ناقص V12.4 دست‌نخورده ماند. هیچ ابزار/پراکسی/مرورگر/collector جایگزین برای کدال به کار نرفت.
- رتبهٔ V12.5 روی صفحهٔ موجود `/ranking/research/v12-1` منتشر شد: ۲۲۷ از ۲۵۰ هویت؛ ۲۳ حذف دقیقاً با دلیل `no_verified_financial_snapshot`.
- پوشش سه عامل فروش بدون تغییر ماند: ۸۳، ۹۵ و ۹۱ از ۲۲۷. نوسان ۳۰روزه از ۰ به ۲۲۷ و شتاب ۳۰روزه از ۰ به ۲۱۵ رسید.
- اطلاعات بنیادی از ورودی V12.4 با cutoff `2026-10-19T18:24:10.459499Z` است. cache تعدیل‌شدهٔ BRS نوع ۳ تا ۱۲ اکتبر ۲۰۲۶ و گردآوری ۱۳ اکتبر است؛ پایان جلسه تأیید نشده.
- A/B/C در همان صفحه نمایش داده می‌شوند؛ C بزرگ‌ترین نتیجهٔ تاریخی را داشت، اما نتیجه مستقل نیست. سبد جاری هر سه unavailable است. هیچ سفارش ساخته نشد.
- آینده‌نگری با قرارداد ثابت ذخیره شد، ولی شروع نشده؛ زمان‌بندی/اجرای دائمی وجود ندارد.

## فایل‌ها و مسیر صفحه

- گزارش: `docs/RETURN_V12_5_FINAL.fa.md`
- گزارش واگذاری: همین فایل
- کد refresh و آزمون‌ها: `ranking_research/return_v12_5/`
- صفحهٔ موجود: `/ranking/research/v12-1`، ورودی منتشرشده `client/public/research/return-v12-5.json`
- اجرای منتشرشده: `ranking_research/output/return_v12_5/v12_5_20261019T191900240558Z/`
- replay دقیق، بدون انتشار: `ranking_research/output/return_v12_5/v12_5_20261019T191955859839Z/`
- evidence و manifest تحویل: `ranking_research/output/return_v12_5/delivery/` و `ranking_research/output/return_v12_5/delivery_manifest.json`

## بازتولید

از ریشهٔ مخزن در PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_5.refresh
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_5.refresh --replay v12_5_20261019T191900240558Z
.\.venv\Scripts\python.exe -B -m pytest ranking_research/return_v12_5/test_refresh.py ranking_research/return_v12_4/test_current_snapshot.py ranking_research/return_v12_3/test_repairs.py -q
cd client
npm run build
```

اجرای اول فقط offline است: درخواست شبکه، کدال و DB باید صفر بماند. `--replay` شناسهٔ اجرای هدف می‌گیرد و خروجی را منتشر نمی‌کند. حالت اختیاری `--prices-only` برای BRS در کد وجود دارد، اما در این کار اجرا نشده است.

## قفل‌ها، ورودی‌ها و محدودیت‌ها

- Cache هر قیمت با هویت دقیق، symbol منبع، hash payload، نتیجهٔ اعتبارسنجی منبع، hash collector/adapter و نسخهٔ parser ثبت می‌شود. ۲۲۷ cache در اجرای موفق hit شدند؛ هیچ parse دوباره‌ای نبود.
- وزن، پیش‌فرض، قواعد missing، percentile، جریمه و DQ تغییر نکرده‌اند؛ وزن نقدشوندگی صفر است. رتبهٔ جدید از دو عامل قیمت آمده، نه از گسترش جامعه.
- آزمون‌های مرتبط ۱۳/۱۳ موفق: فرمول قیمت/حداقل مشاهده، مسدودسازی fake transport و redirect کدال، hash خراب، ورودی خراب، حفظ snapshot قبلی در شکست پیش از انتشار، رد writer دوم، و پنجره‌های ماهانه/ماه گمشده/مخرج صفر.
- replay دقیق تأیید شد. مرورگر در harness کنترل‌شده آزموده شد: جست‌وجوی کاسپین، انتخاب وزن staged، جزئیات عوامل، عرض ۳۹۰/۱۴۴۰ و فایل CSV واقعی با BOM/UTF-8/۱۱ ستون و یک ردیف خوانده شدند.
- hash snapshot و کد منبع در manifest هر run ثبت شده‌اند. hash دو گزارش مهرشدهٔ V12.3 با مقدار قبلی یکی است.
- هنوز آخرین گزارش همهٔ شرکت‌ها، تاریخ انتشار/`tracing_no`، پایان جلسه، مخرج بازار، ۲۳ snapshot مالی، ۱۲ تاریخچهٔ شتاب ناکافی و تست مستقل event adjustment نداریم. کل بازده اقتصادی شامل dividend/حق‌تقدم نیست.
- ارزیابی A/B/C صرفاً توصیفی از دورهٔ دیده‌شده تا `2026-02-25` است؛ holdout آینده ندارد. آزمون کامل session-authenticated برنامه و تست زنده با sentinel formula-like اجرا نشد.

قرارداد آینده در `ranking_research/output/return_v12_5/future_evaluation_contract.json` است. اولین تصمیم بعد از timestamp قرارداد و فقط با ورودی واقعاً کامل می‌تواند شروع باشد؛ تا آن زمان خروجی جاری «سبد در دسترس نیست» می‌ماند.
