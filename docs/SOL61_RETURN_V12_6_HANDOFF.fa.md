# واگذاری V12.6 — سبد A و تطبیق عوامل، آفلاین

## نتیجه

- فرمول‌های V12.5 با قرارداد تاریخی V8 تطبیق دارند؛ فرمول تغییر نکرد و برچسب نوسان/شتاب در صفحه دقیق شد.
- سبد هدف نمونهٔ A از w0 و snapshot ذخیره‌شده استخراج شد: 1. سرود، 2. کاسپین، 3. سپید، 4. شسپا، 5. فگستر، 6. غشوکو، 7. بشهاب، 8. شاملا، 9. خراسان، 10. قاسم، ده وزن ۱۰٪ از ۱۰۰ میلیون تومان. بودجه نظری هر سهم ۱۰ میلیون و وجه نقد صفر؛ هیچ تعداد سهم یا سفارش واقعی محاسبه نشد.
- آخرین قیمت تعدیل‌شدهٔ vendor: 2026-10-12، cache جمع‌آوری‌شده در 2026-10-13T05:20:52.444079+00:00. cutoff بنیادی 2026-10-19T18:24:10.459499+00:00؛ دورهٔ مالی 2026-06-21، سن 120 روز هنگام snapshot. پایان جلسه تأیید نشده است.
- آمادگی: A فقط target preview دارد؛ تصمیم/اجرا false. B/C preview، تصمیم و اجرا false. سیاست بلوک تاریخی تا 2026-02-25 به امروز تعمیم داده نشد.
- قرارداد آیندهٔ نسخهٔ ۱٫۱ تصمیم و اجرا را جدا می‌کند؛ تصمیم آینده ثبت نشده و `REGISTERED_NOT_STARTED` باقی ماند.
- درخواست شبکهٔ بیرونی، کدال و اتصال DB: هر کدام صفر.

## مسیرها

- صفحهٔ موجود: `/ranking/research/v12-1`
- public payload: `client/public/research/return-v12-6.json`
- اجرای آفلاین: `ranking_research/output/return_v12_6/v12_6_20261019T194005988394Z/`
- CSV: `ranking_research/output/return_v12_6/v12_6_20261019T194005988394Z/target_portfolio_A.csv`
- گزارش نهایی: `docs/RETURN_V12_6_FINAL.fa.md`
- کد و تست: `ranking_research/return_v12_6/`

## فرمان بازتولید

از ریشهٔ مخزن در PowerShell:

```powershell
$env:SOL61_RETURN_V12_6_PUBLISH='1'
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_6.build_delivery
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_6.finalize_delivery
.\.venv\Scripts\python.exe -B -m pytest ranking_research/return_v12_6/test_delivery.py ranking_research/return_v12_5/test_refresh.py ranking_research/return_v12_4/test_current_snapshot.py ranking_research/return_v12_3/test_repairs.py -q -k "not test_failure_before_atomic_publish_preserves_previous_snapshot"
cd client
npm run build
```

فرمان build فقط snapshotهای محلی را می‌خواند و V12.5 refresh، prices-only، کدال، شبکه یا DB را اجرا نمی‌کند. build سایت برای مشاهدهٔ واقعی صفحه لازم است؛ مرورگر authenticated و تست viewport در این تحویل اجرا نشده‌اند تا هیچ درخواست HTTP/شبکه‌ای ایجاد نشود. CSV فایل محلی با BOM و ۱۶ ستون است؛ ده نماد/وزن/بودجه با JSON تطبیق داده شد. آزمون sentinel formula-like روی fixture موقت PASS است.

## وضعیت آزمون و محدودیت‌ها

- ۲۲ تست نهایی موفق؛ یک تست قدیمی به‌علت assertion نام کلید manifest deselect شد. همان تست در دور اول عدم‌تغییر hash snapshot را PASS کرده بود و بعد روی کلید `latest_run` fail شد؛ schema نهایی گزارش V12.5 از `latest_published_run` استفاده می‌کند.
- replay عامل، رتبه، سبد و CSV در دو اجرای آفلاین به‌صورت byte-for-byte یکسان تأیید شد.
- عامل‌ها برای ۲۲۷/۲۲۷ ردیف از سری تعدیل‌شده و turn-over منجمد باز‌محاسبه شدند؛ mismatch صفر، بیشینهٔ اختلاف نوسان 8.88e-16 و شتاب صفر.
- تعدیل corporate action مستقل احراز نشده؛ vendor-reported باقی می‌ماند. قیمت خام اجرای امروز، session رسمی و state حساب وجود ندارد.
- B/C به پنل PIT selector و ورودی‌های بعد از دوره تاریخی نیاز دارند؛ نبود آن‌ها A را مسدود نمی‌کند.
- نتایج تاریخی A/B/C توصیفی و غیرمستقل‌اند؛ C فقط بزرگ‌ترین نتیجهٔ گذشتهٔ دیده‌شده است.

هش‌های V12.3 مهرشده بررسی و بدون تغییر ماندند: `{"docs/RETURN_V12_3_COMPLETION.fa.md": "a81c601830a72edd44f0169e55c071adc67dfeb40179a06f5cf31e9ef2f578b8", "docs/RETURN_V12_3_FINAL.fa.md": "259de3eafd4e91fd5963a88e2d43399199a0ac967a60506041418fa125968d41"}`.
