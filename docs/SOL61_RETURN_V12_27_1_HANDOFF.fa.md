# تحویل اصلاح‌شدهٔ V12.27.1

تاریخ اجرا: ۱۴۰۵/۰۷/۳۰ (2026-10-22). گزارش نهایی: `docs/RETURN_V12_27_1_FINAL.fa.md`. پوشه: `ranking_research/output/return_v12_27/v12_27_1_20261022_delivery_corrections_01/`. صفحهٔ موجود: `/ranking/research/v12-1`، بخش V12.27.1. گزارش، handoff، manifest و مصنوعات مهرشدهٔ V12.27 دست‌نخورده‌اند.

## تغییرات و نتایج

- جدول آغازین گزارش از دادهٔ ذخیره‌شده بازسازی شد؛ نماد، تاریخ تصمیم و تاریخ fill جدا هستند.
- ۱۷ آزمون اجرا شد و همگی PASS شدند (۱۴ Python و ۳ CSV). اختلاف قبلی گزارش (۱۳) با handoff (۱۴) با شمارش اجرای واقعی حل شد.
- سرمایهٔ پایان، سود خالص و کارمزد در کارت‌های مسیر رابط جدا نمایش داده می‌شوند. CSV فارسی BOM دارد؛ متن فرمول‌مانند با apostrophe محافظت می‌شود و عدد منفی دست‌نخورده می‌ماند.
- نتیجهٔ G0/G1/G50 و آشتی همگرایی تغییر نکرد: G1 در 2021-07-05 و G50 در 2021-10-16 به وضعیت پایدار رسیدند و تا پایان ماندند. باقی‌مانده‌های آشتی به‌ترتیب کمتر از یک میکروتومان و صفر ثبت شده‌اند. این حسابداری مسیر است، نه اثر علّی مستقل.
- سفارش معلق از آخرین تصمیم ذخیره‌شده و fillهای بعدی بازسازی شده است؛ اگر fill شده از pending حذف می‌شود و اگر fill نشده بماند. V12.26 دفتر روزانهٔ مستقل سفارش ندارد، پس این بخش استنباط از دفترهاست.

## آزمون و محدودیت

- آزمون‌های اجراشده: ۱۷/۱۷ PASS (۱۴ Python + ۳ CSV). شامل ۱۸ نمونهٔ بازپخش، بازسازی امتیاز ۸٬۸۰۰ ردیف با بیشینهٔ خطای `2.132e-14`، آشتی ۳۵ fill/مشارکت/کارمزد، افق ناقص، CSV فارسی و بازسازی سفارش.
- Build: PASS با بسته‌های موجود. هشدار `caniuse-lite` قدیمی و chunk بزرگ‌تر از ۵۰۰KB ثبت شد؛ بسته‌ای نصب یا ارتقا نیافت.
- مرورگر: `NOT_RUN`؛ فایل اجرایی Chromium برای Playwright موجود نبود؛ نصب مرورگر طبق قید انجام نشد و هیچ صفحه‌ای باز نشد. رفتار عرض ۳۹۰/۱۴۴۰، دانلود واقعی CSV و کنسول مرورگر از این رو تأیید نشده‌اند.
- شبکه/کدال/DB/نصب: صفر. هیچ NAV یا معاملهٔ تازه تولید نشد.

## بازتولید آفلاین

از ریشهٔ مخزن در PowerShell، با محیط موجود:

```powershell
.venv\Scripts\python.exe -B -m ranking_research.return_v12_27.run
.venv\Scripts\python.exe -B -m unittest ranking_research.return_v12_27.test_v12_27 -q
.venv\Scripts\python.exe -B -m ranking_research.return_v12_27.deliver_v12_27_1
cd client
npm run build -- --emptyOutDir=false
```

CLI بازپخش دقیق: `.venv\Scripts\python.exe -B -m ranking_research.return_v12_27.run --replay 2021-04-03 --weight valuation_0 --gate G0`. تاریخ غایب باید `DATA_UNAVAILABLE` باشد.

## فایل‌های کلیدی

`METHOD_P1.fa.md`، `analysis_contract.locked.json`، `source_inventory.json`، `validation.json`، `delivery_manifest.json`، `convergence_audit.csv`، `capital_path_reconciliation.csv`، `w0_control_reconciliation.csv`، `divergence_decisions.csv`، `changed_monthly_routes.csv`، `continuous_annual_with_return.csv`، `p1_trades_fa.csv`، `p1_contributions_fa.csv`، `historical_replay_data.json.gz`، `replay_sample_validation.csv` و `execution_incident_log.csv`. مسیر پایهٔ فایل‌های منتشرشده در manifest به‌صراحت `client/public/research/` است؛ `client/dist/research/` کپی buildشدهٔ همان فایل‌هاست.
