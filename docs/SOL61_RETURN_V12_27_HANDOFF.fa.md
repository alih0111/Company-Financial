# تحویل اجرای V12.27

گزارش نهایی: `docs/RETURN_V12_27_FINAL.fa.md`  
پوشهٔ نسخه‌دار: `ranking_research/output/return_v12_27/v12_27_20261022_replay_and_attribution_01/`  
صفحهٔ پژوهش: `/ranking/research/v12-1`، بخش V12.27 در انتهای خروجی‌های قبلی.

## بازتولید آفلاین

از ریشهٔ پروژه و محیط Python موجود:

```powershell
.venv\Scripts\python.exe -B -m ranking_research.return_v12_27.run
.venv\Scripts\python.exe -B -m unittest ranking_research.return_v12_27.test_v12_27 -q
.venv\Scripts\python.exe -B -m ranking_research.return_v12_27.run --replay 2021-04-03 --weight valuation_0 --gate G0
```

برای هر تاریخ خارج از snapshot، CLI `DATA_UNAVAILABLE` می‌دهد. اجرای runner فقط گزارش و snapshot مشتق‌شدهٔ رتبه/تصمیم می‌سازد؛ NAV و معاملهٔ جدید نمی‌سازد. بستهٔ خام coverage لازم نیست برای UI بارگذاری شود.

## وضعیت گیت‌ها

- مراحل ۱ تا ۴ و ۶: PASS؛ ۱۴ آزمون، شامل رگرسیون بازسازی سفارش‌های معلق؛ تطبیق ۱۸ نمونه، خطای score حداکثر 2.132e−14، و hash خروجی‌های اصلی در بازتولید دوم یکسان.
- مرحلهٔ ۵: صفحه و build آفلاین PASS؛ مرورگر NOT_RUN برای حفظ صفر درخواست شبکه.
- V12.26: پوشش و G0 controls PASS؛ ۱٬۲۰۰ مسیر کامل، ۲۴۰ مسیر ناقص، ۱۲ پیوسته، ۲٬۴۲۴ ردیف ledger با صفر عدم‌تطبیق.
- network/codal/DB/install: صفر. پیش‌فرض غربال و مصنوعات قبلی ثابت‌اند.

## فایل‌های اصلی

`METHOD_P1.fa.md`، `analysis_contract.locked.json`، `source_inventory.json`، `validation.json`، `delivery_manifest.json`، `convergence_audit.csv`، `capital_path_reconciliation.csv`، `w0_control_reconciliation.csv`، `divergence_decisions.csv`، `changed_monthly_routes.csv`، `capital_start_summary_fa.csv`، `continuous_annual_with_return.csv`، `p1_trades_fa.csv`، `p1_contributions_fa.csv`، `horizon_extrema.csv`، `historical_replay_data.json.gz`، `replay_sample_validation.csv` و `execution_incident_log.csv`.

CSVهای فارسی UTF-8 BOM دارند. NAV انتهایی از سود خالص جداست؛ هزینه دوبار کسر نشده. واحدهای fill شاخص قیمت تعدیل‌شده‌اند، نه تعداد سهم واقعی. مرورگر تعاملی با وضعیت ورود احراز هویت‌شده آزموده نشد؛ هیچ دسترسی یا اتصال خارجی باز نشد.
