# تحویل پژوهش V11

## وضعیت

V11 با شناسهٔ `v11_20261018T120000Z` کامل و قابل‌بازتولید است. V10 را اجرا یا بازنویسی نکردیم؛ مهر V8/V9/V10 ابتدا و انتها سالم ماند. پاسخ اقتصادی فعلی روشن است: پس از اصلاح انتخاب‌گر، نتیجهٔ قدیمی V10 از ۲۰۵٫۴۷ به ۱۵۶٫۵۵ میلیون تومان رسید؛ جست‌وجوی مشترک V11 روی P3 به ۱۱۲٫۳۱ میلیون رسید و از کنترل فعلی ۲۲۸٫۴۴ میلیون عقب ماند. V11 پیش‌فرض نیست.

## فرمان‌های بازتولید

از ریشهٔ `D:/RFA/Company-Financial`:

```powershell
.venv/Scripts/python.exe -B -m ranking_research.return_v11.audit
.venv/Scripts/python.exe -B -m ranking_research.return_v11.tests
.venv/Scripts/python.exe -B -m ranking_research.return_v11.prepare
.venv/Scripts/python.exe -B -m ranking_research.return_v11.repair
.venv/Scripts/python.exe -B -m ranking_research.return_v11.search
.venv/Scripts/python.exe -B -m ranking_research.return_v11.panel_ablation
.venv/Scripts/python.exe -B -m ranking_research.return_v11.diagnostics
.venv/Scripts/python.exe -B -m ranking_research.return_v11.validate
.venv/Scripts/python.exe -B -m ranking_research.return_v11.finalize
```

`prepare` پنل‌های P0 تا P3 را می‌سازد. برای تغییر علمی، run id تازه با `RETURN_V11_RUN_ID` انتخاب شود؛ ادامهٔ همان run فقط با hash یکسان ورودی، candidate registry و پنجره‌ها مجاز است. `search` نتیجهٔ هر بلوک را checkpoint می‌کند و در resume شناسه‌های کامل را رد می‌کند. `finalize` جست‌وجو یا replay را اجرا نمی‌کند؛ فقط ثبت و hash تحویل را می‌سازد. ساخت رابط: `cd client; npm run build`.

## فایل‌های اصلی خروجی

در `ranking_research/output/return_v11/v11_20261018T120000Z/`:

- ممیزی و fixture: `audit_findings.fa.md`, `audit_fixture_state_reset.json`
- ثبت و قرارداد: `pre_registration.json`, `input_manifest.json`, `feature_contract.json`, `candidate_registry.json`, `candidate_coverage.csv`
- پنل‌ها: `panel_P0.parquet` تا `panel_P3.parquet`, `coverage_by_factor_year.csv`, `missing_reasons.csv`
- ترمیم انتخاب‌گر V10: `v10_selection_repair_comparison.csv`, `v10_selection_repair_validation.csv`, `selection_repair_models.json`
- جست‌وجو: `selection_results/`, `selected_models.json`, `weights_by_block.csv`
- مسیرها و معاملات: `comparison.csv`, `equity.csv`, `trades.csv`, `orders.csv`, `panel_ablation.csv`
- تشخیص: `winner_capture.csv`, `winner_capture_summary.json`, `kaspian_case.csv`, `ps_diagnostics.csv`, `ranking_snapshot.json`
- آزمون و مهر: `test_evidence.json`, `delivery_manifest.json`

صفحهٔ پژوهش، snapshot تاریخی را از `client/public/research/return-v11.json` می‌خواند. اتصال رابط از route برنامه انجام شده و فایل‌های client مهرشدهٔ V10 بدون تغییر مانده‌اند.

## یافته‌های باقی‌مانده

نتیجهٔ V11 ضعیف است، نه ناموفق از نظر صحت. N=1 و وزن ۱۰۰٪ روی رشد فروش سه‌ماهه یا ROE در چند بلوک انتخاب شد؛ دادهٔ مفقود و جست‌وجوی هزاران config می‌تواند علت باشد. winner capture نشان می‌دهد رتبهٔ دهک برتر بهتر نشد و V11 تقریباً هیچ‌یک را انتخاب نکرد. قدم بعدی مناسب، بررسی source coverage و کیفیت سیگنال در همان جامعه و سپس ثبت آزمونی کوچک‌تر است؛ گسترش جست‌وجو برای پنهان‌کردن افت بازده توجیه ندارد.

بازهٔ ۲۰۲۳ تا ۲۰۲۶ holdout مستقل نیست. بازده‌ها شامل تمام سود نقدی و حق‌تقدم اثبات‌شده نیستند، هزینهٔ ظرفیت/اثر بازار ندارند و قیمت اجرای مدل بر فرض full fill روی open معتبر است. هیچ سفارش زنده‌ای ارسال نشده است.
