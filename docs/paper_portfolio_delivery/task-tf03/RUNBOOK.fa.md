# راهنمای شروع مسیر public (برای بازبینی؛ اجرا نشده)

همهٔ فرمان‌های زیر برای آینده‌اند و جز فرمان ساخت پیش‌نویسِ غیرفعال، در این مأموریت اجرا نشده‌اند. مسیر خروجی هر حساب تازه باید جدا از حساب قدیمی باشد. قبل از تصمیم تازه، ranking انتخابی را با قرارداد و validator همان artifact بررسی و هش آن را ثبت کنید. رتبه‌بندی فعلی `PREPARATION_UNCONFIRMED` است؛ پیش‌نویس موجود به همین دلیل `active_decision=null` دارد و برای preview سفارش مجاز نیست.

## ساخت حساب مستقل

```powershell
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/create_public_paper_account.py `
  --ranking <RANKING_JSON_VALIDATED> `
  --output-account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --output-rules docs/paper_portfolio_delivery/task-tf03/draft/execution_rules_public.json `
  --account-id paper-p1-public-<UNIQUE_ID>
```

این دستور فقط حساب خالی با سرمایهٔ قالب مصوب، قواعد کپی‌شده و binding عمومی می‌سازد؛ سفارش یا تصمیم ایجاد نمی‌کند. فایل مقصد باید از قبل وجود نداشته باشد. فایل فعلی در `draft/` غیرفعال است و فقط برای نشان‌دادن وضعیت فعلی ساخته شده است؛ نام/شناسهٔ آن را برای شروع واقعی reuse نکنید.

## تصمیم تازه و preview سفارش

پس از انتخاب ranking واجدشرایط، زمان تصمیم باید زمان واقعی همان اجرا باشد. ابتدا مدرک نامزد و تقویم را در پوشهٔ invocation مستقل دریافت کنید و بعد آن‌ها را به ثبت تصمیم بدهید:

```powershell
$out = 'docs/paper_portfolio_delivery/task-tf03/runs/<RUN_ID>'
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_paper_candidate_evidence.py `
  --account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --output-dir "$out/candidate"
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_public_market_calendar.py `
  --window-start <DECISION_LOCAL_YYYYMMDD> --candidate-symbol <PINNED_SYMBOL> `
  --output-dir "$out/calendar" --cross-check-lookback-days 60
# مسیر manifest تازهٔ candidate را از latest-manifest.json همان acquisition بخوانید.
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/register_paper_decision.py `
  --calendar-provider public --account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --ranking <RANKING_JSON_VALIDATED> --rules docs/paper_portfolio_delivery/task-tf03/draft/execution_rules_public.json `
  --evidence <CANDIDATE_MANIFEST_FROM_THIS_RUN> --calendar-policy ranking_research/paper_calendar_policy.public-paper-v1.json
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/paper_cycle.py `
  --order-review-only --calendar-provider public `
  --account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --rules docs/paper_portfolio_delivery/task-tf03/draft/execution_rules_public.json `
  --evidence-manifest <CANDIDATE_MANIFEST_FROM_THIS_RUN> `
  --calendar-manifest <PUBLIC_CALENDAR_MANIFEST_FROM_THIS_RUN> `
  --calendar-manifest-sha256 <PUBLIC_CALENDAR_MANIFEST_SHA256> `
  --output-dir "$out/status" --public-output-dir "$out/public"
```

شاخهٔ `order-review-only` مراحل ranker/Codal/O00 و scheduler را اجرا نمی‌کند. بدون `--apply-fill` اجرای wrapper preview است و هیچ حسابی فعال نمی‌شود. public profile با manifest/hash صریح به NSCStart یا prompt توکن وارد نمی‌شود. نتیجهٔ `NO_NEW_SESSION` مجوز fill نیست.

## apply، mark و replay (فقط پس از بازبینی و مجوز مرحلهٔ آتی)

درخواست صریح apply فقط با افزودن `--apply-fill` به اجرای `paper_cycle.py` بالا انجام می‌شود. mark باید با منبع قیمت تازهٔ همان نامزد و مسیرهای temp باشد:

```powershell
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/check_paper_account.py `
  --account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --ranking <PINNED_RANKING_JSON> --tsetmc-manifest <FRESH_CANDIDATE_MARKET_MANIFEST> `
  --calendar <LOCAL_SESSION_CALENDAR_PARQUET> --mark-to-market `
  --output-dir <TEMP_STATUS_DIR> --public-output-dir <TEMP_PUBLIC_STATUS_DIR>
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/apply_paper_fill.py `
  --session-calendar-manifest <ORIGINAL_PINNED_PUBLIC_MANIFEST> `
  --calendar-manifest-sha256 <ORIGINAL_PINNED_SHA256> `
  --evidence-manifest <ORIGINAL_PINNED_CANDIDATE_MANIFEST> `
  --calendar-provider public --calendar-policy ranking_research/paper_calendar_policy.public-paper-v1.json `
  --account docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json `
  --rules docs/paper_portfolio_delivery/task-tf03/draft/execution_rules_public.json --apply-fill
```

Replay دقیق همان fill با همان ورودی‌های pinشده و `--apply-fill` انجام می‌شود؛ receipt و hash ورودی نباید عوض شوند. replay ساعت اعتبارسنجی ثبت‌شده در receipt را بازاستفاده می‌کند. برای سفارش جدید، clock گذشته یا manifest قدیمی به کار نبرید. این فرمان‌ها در TF-03 برای حساب واقعی اجرا نشده‌اند.

## شرط بازکردن مانع شروع واقعی

snapshot فعلی `v12_36_statement_type_aware_existing_archives_20261021` در artifact خود `PREPARATION_UNCONFIRMED` می‌گوید و زمان دریافت آرشیو را برای ادعای availability پیش از cutoff اثبات نمی‌کند. این برچسب در `rebuild_latest_supported_v12_37.py` ثبت شده است. قرارداد قفل‌شده `future-evaluation-v12.28-p1-p3-o00-g0` انتخاب P1 rank 1 را تعریف می‌کند، اما این برچسب را به رتبهٔ جاری/آینده یا مجوز آغاز تبدیل نمی‌کند. بنابراین ۱۶۶/۲۵۴ مبنای ساخت آستانهٔ تازه نیست؛ شرط لازم، snapshot نامزد تازه و قابل‌اعتبارسنجی با lineage/زمان دریافت و قرارداد هم‌خوان است، سپس تصمیم جدید با زمان واقعی ثبت می‌شود. وضعیت رسمی/کامل تقویم، O00، PIT فروش، صف و cadence ۶۳ جلسه‌ای از این مسیر نتیجه نمی‌شوند.
