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

برای تصمیم بعدی، ابتدا acquisition واقعی و مناسب آن تصمیم را اجرا و manifest تازه/سازگار را بررسی کنید؛ سپس زمان تصمیم واقعی را ثبت کنید؛ پس از آن preview روی حساب موقت را اجرا کنید. اگر روز معاملاتی تازه‌ای نرسیده یا `NO_NEW_SESSION` حاصل شد، همان نتیجه را طبیعی ثبت کنید و ساعت ساختاریافته را برای شبیه‌سازی خرید عوض نکنید. TF-04A زمان تصمیم یا سفارش ایجاد نمی‌کند.

پیشنهاد حداقلی TF-04B و گروه‌های داده/هزینهٔ تقریبی در `REPORT.fa.md` است. دریافت live، preview سفارش یا هر نوع فعال‌سازی در TF-04A انجام نشده است.
