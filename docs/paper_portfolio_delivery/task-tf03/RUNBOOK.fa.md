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

ترتیب زمانی لازم است: ابتدا snapshot رتبه‌بندی واجدشرایط و قواعد را pin کنید و یک مدرک پایهٔ تصمیم بسازید که فقط شناسه/هش ranking و هویت نامزد را ثبت کند؛ این مدرک، market evidence یا شاهد اجرای بعد از تصمیم نیست. تصمیم با ساعت واقعی سیستم ثبت می‌شود. فقط پس از ثبت موفق تصمیم، collector تقویم و candidate evidence تازه اجرا می‌شوند و خروجی همان invocation به preview داده می‌شود. timestamp دریافت را ویرایش یا به قبل/بعد منتقل نکنید.

```powershell
$out = 'docs/paper_portfolio_delivery/task-tf03/runs/<RUN_ID>'
New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
$account = 'docs/paper_portfolio_delivery/task-tf03/draft/public-paper-account.json'
$ranking = '<RANKING_JSON_VALIDATED_AND_PINNED>'
$rules = 'docs/paper_portfolio_delivery/task-tf03/draft/execution_rules_public.json'
$symbol = '<PINNED_SYMBOL>'
$company = '<PINNED_COMPANY_ID>'
# این فایل فقط پایهٔ ثبت تصمیم است؛ ورودی market acquisition محسوب نمی‌شود.
$basis = @{dataset_id='pinned-ranking'; candidate=@{symbol=$symbol; company_id=$company}; sources=@()} | ConvertTo-Json -Depth 6 -Compress
[IO.File]::WriteAllText("$out/decision-basis.json", $basis, [Text.UTF8Encoding]::new($false))
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/register_paper_decision.py `
  --calendar-provider public --account $account --ranking $ranking --rules $rules `
  --evidence "$out/decision-basis.json" --calendar-policy ranking_research/paper_calendar_policy.public-paper-v1.json
# از این نقطه به بعد، هر دو دریافت تازه‌اند و در مسیر مختص همین invocation ذخیره می‌شوند.
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_paper_candidate_evidence.py `
  --account $account --output-dir "$out/candidate"
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_public_market_calendar.py `
  --window-start <DECISION_LOCAL_YYYYMMDD> --candidate-symbol $symbol `
  --output-dir "$out/calendar" --cross-check-lookback-days 60
$candidateManifest = (Get-Content -Raw "$out/candidate/latest-manifest.json" | ConvertFrom-Json).manifest_path
$calendarManifest = '<MANIFEST_PATH_FROM_THIS_CALENDAR_INVOCATION>'
$calendarSha = (Get-FileHash -Algorithm SHA256 $calendarManifest).Hash.ToLowerInvariant()
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/paper_cycle.py `
  --order-review-only --calendar-provider public --account $account --rules $rules `
  --evidence-manifest $candidateManifest --ranking $ranking `
  --calendar-manifest $calendarManifest --calendar-manifest-sha256 $calendarSha `
  --output-dir "$out/status" --public-output-dir "$out/public"
```

اگر پس از تصمیم هنوز جلسهٔ تازه‌ای نیست، `NO_NEW_SESSION` نتیجهٔ عادی است؛ تا جلسه و evidence تازه نرسد، preview را در زمان بعدی با دریافت تازه تکرار کنید. manifest صریح و hash همان invocation در provider عمومی اولویت قطعی دارند؛ `TSETMC_CALENDAR_MANIFEST` فقط برای مسیر legacy بدون manifest صریح و provider برابر `nscstart` خوانده می‌شود. مسیر public توکن/NSCStart را وارد نمی‌کند.

شاخهٔ `order-review-only` مراحل ranker/Codal/O00 و scheduler را اجرا نمی‌کند. preview پیش‌فرض هیچ fillای نمی‌نویسد. Apply فقط با اجرای مجدد همان command و افزودن `--apply-fill` صریح است؛ هر دو اجرا باید به account و evidence/calendar pinشدهٔ همان تصمیم اشاره کنند.

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

Replay دقیق همان fill با همان ورودی‌های pinشده و `--apply-fill` انجام می‌شود؛ receipt و hash ورودی نباید عوض شوند. برای سنجش idempotency روز بعد، clock سیستم/CLI باید واقعاً جلو رفته باشد و ساعت خرید را دوباره به replay تحمیل نکنید؛ receipt اصلی و mark حفظ می‌شوند. برای سفارش جدید، clock گذشته یا manifest قدیمی به کار نبرید. این فرمان‌ها در TF-03 برای حساب واقعی اجرا نشده‌اند.

## شرط بازکردن مانع شروع واقعی

snapshot فعلی `v12_36_statement_type_aware_existing_archives_20261021` در artifact خود `PREPARATION_UNCONFIRMED` می‌گوید و زمان دریافت آرشیو را برای ادعای availability پیش از cutoff اثبات نمی‌کند. این برچسب در `rebuild_latest_supported_v12_37.py` ثبت شده است. قرارداد قفل‌شده `future-evaluation-v12.28-p1-p3-o00-g0` انتخاب P1 rank 1 را تعریف می‌کند، اما این برچسب را به رتبهٔ جاری/آینده یا مجوز آغاز تبدیل نمی‌کند. بنابراین ۱۶۶/۲۵۴ مبنای ساخت آستانهٔ تازه نیست؛ شرط لازم، snapshot نامزد تازه و قابل‌اعتبارسنجی با lineage/زمان دریافت و قرارداد هم‌خوان است، سپس تصمیم جدید با زمان واقعی ثبت می‌شود. وضعیت رسمی/کامل تقویم، O00، PIT فروش، صف و cadence ۶۳ جلسه‌ای از این مسیر نتیجه نمی‌شوند.
