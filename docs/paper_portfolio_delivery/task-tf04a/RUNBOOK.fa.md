# راهنمای اجرای تشخیص TF-04A

تمام فرمان‌ها از ریشهٔ `D:/RFA/Company-Financial` اجرا می‌شوند. اجرای ابزار فقط در `--output-dir` تازه می‌نویسد؛ اگر پوشه غیرخالی باشد متوقف می‌شود. برای snapshot دیگر، مسیر ranking و manifest متناظر و مقصد جدید بدهید.

```powershell
.venv/Scripts/python.exe -X utf8 docs/paper_portfolio_delivery/task-tf04a/assess_ranking_readiness.py `
  --snapshot ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/ranking/latest-ranking.json `
  --manifest ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/ranking/manifest.json `
  --output-dir docs/paper_portfolio_delivery/task-tf04a/evidence/my-run-v12-36

.venv/Scripts/python.exe -X utf8 docs/paper_portfolio_delivery/task-tf04a/assess_ranking_readiness.py `
  --snapshot ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/ranking/latest-ranking.json `
  --manifest ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/ranking/manifest.json `
  --output-dir docs/paper_portfolio_delivery/task-tf04a/evidence/my-run-v12-37

$env:PYTHONDONTWRITEBYTECODE='1'
.venv/Scripts/python.exe -X utf8 -m pytest docs/paper_portfolio_delivery/task-tf04a/test_assess_ranking_readiness.py -q `
  --basetemp "$env:TEMP/tf04a-pytest-<unique-run-id>"
```

خروجی `readiness.json` کنترل محاسبه، lineage، receipt، freshness و مجوز دو مسیر را جدا نگه می‌دارد؛ `validation.json` را validator موجود می‌سازد. observation manifest فقط hash bytes در زمان اجرای ابزار است. آن را receipt تاریخی تفسیر نکنید. آزمون‌ها از `tmp_path` pytest استفاده می‌کنند و خروجی harness به پوشهٔ delivery نمی‌نویسند.

## ترتیب لازم برای تصمیم تازه

مدرک تصمیم باید پیش از acquisition تازه ثبت شود؛ acquisition و preview بعدی شواهد اجرای پس از همان تصمیم‌اند. برای اجرای واقعی، `--decision-at` را از timestamp واقعی ثبت‌شده بگیر، نه از timestamp دلخواه یا ساعت خرید fixture. نمونهٔ PowerShell برای ثبت مدرک پایه:

```powershell
$runId = [guid]::NewGuid().ToString('N')
$decisionAt = [DateTimeOffset]::UtcNow.ToString('o')
$decisionPath = "ranking_research/output/paper_cycle/decisions/$runId/decision.json"
New-Item -ItemType Directory -Path (Split-Path $decisionPath) -Force | Out-Null
[ordered]@{ run_id=$runId; decision_at_utc=$decisionAt; basis="fresh decision record before acquisition" } |
  ConvertTo-Json | Set-Content -LiteralPath $decisionPath -Encoding utf8

# در یک اجرای مجاز بعدی، نه در TF-04A:
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_codal_incremental.py $runId
# سپس بسته‌بندی/محاسبهٔ ranking همان run و بررسی manifestهای هم‌run انجام شود.
.venv/Scripts/python.exe -X utf8 docs/paper_portfolio_delivery/task-tf04a/assess_ranking_readiness.py `
  --snapshot <ranking همان run> --manifest <manifest همان run> `
  --output-dir <مقصد ایزوله و تازه> --decision-at $decisionAt
# در آخر preview فقط روی حساب موقت؛ زمان تصمیم در preview با acquisition جابه‌جا نشود.
```

در fixture نیز ترتیب داده چنین است: `decision.json` با زمان fixture ابتدا ثبت می‌شود؛ acquisition fixture پس از آن با receiptهای fixture جداگانه نگه داشته می‌شود؛ سپس assess با `--decision-at` همان زمان تصمیم را می‌سنجد. آزمون `test_assess_reports_hash_bound_market_receipt_after_hypothetical_decision` این ترتیب را از مسیر خود assess می‌آزماید. زمان fixture به ساعت observation واقعی ابزار تزریق نمی‌شود.

نمونهٔ قابل‌اجرای آفلاین با بستهٔ موجود: زمان تصمیم فرضی 18:00Z است و registration بستهٔ بازار همان cycle زمان دریافت 19:02Z را با hash دارد؛ این fixture فقط منطق ترتیب را نشان می‌دهد و مدرک تصمیم تاریخی واقعی نیست.

```powershell
$fixtureDecision = '2026-10-24T18:00:00Z'
[ordered]@{ decision_at_utc=$fixtureDecision; kind='TEST_FIXTURE_ONLY' } |
  ConvertTo-Json | Set-Content -LiteralPath "$env:TEMP/tf04a-decision-fixture.json" -Encoding utf8
.venv/Scripts/python.exe -X utf8 docs/paper_portfolio_delivery/task-tf04a/assess_ranking_readiness.py `
  --snapshot ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/ranking/latest-ranking.json `
  --manifest ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/ranking/manifest.json `
  --output-dir docs/paper_portfolio_delivery/task-tf04a/finish-20261025/evidence/fixture-order `
  --decision-at $fixtureDecision
```

این نمونه زمان capture یا timestamp منبع را تغییر نمی‌دهد؛ ابزار باید market receipt را `AFTER_DECISION` نشان دهد.

اگر روز معاملاتی جدیدی نرسیده یا `NO_NEW_SESSION` حاصل شد، همان نتیجه طبیعی است؛ ساعت سیستم یا ساعت خرید را برای ساختن fill جابه‌جا نکن. TF-04A زمان تصمیم/سفارش یا acquisition ایجاد نمی‌کند. پیش از اجرا، [پلن محدود TF-04B](finish-20261025/TF-04B-PLAN.fa.md) را رعایت کنید؛ سیاست freshness/کیفیت همچنان UNKNOWN است.

پیشنهاد حداقلی TF-04B و گروه‌های داده/هزینهٔ تقریبی در `REPORT.fa.md` است. دریافت live، preview سفارش یا هر نوع فعال‌سازی در TF-04A انجام نشده است.
