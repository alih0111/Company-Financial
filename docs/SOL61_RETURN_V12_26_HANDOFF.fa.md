# تحویل اجرای V12.26

گزارش نهایی: `docs/RETURN_V12_26_FINAL.fa.md`  
پوشهٔ نسخه‌دار: `ranking_research/output/return_v12_26/v12_26_20261022_financial_eligibility_audit_01/`

## اجرای آفلاین

در ریشهٔ repository و با بسته‌های موجود، به‌ترتیب اجرا کنید: `python -B -m ranking_research.return_v12_26.run --lock`، `--coverage`، `--controls`، `--run`، `--summarize`. ماتریس را تنها پس از PASS شدن دو گیت اجرا کنید. آزمون regression: `python -B -m unittest ranking_research.return_v12_26.test_coverage_audit -q`.

## وضعیت تحویل

- گیت پوشش: ۴٬۲۵۴ موعد، صفر score مفقود، بیشینهٔ خطای بازسازی 1.4210854715202004e-14.
- G0: ۴۰۴ کنترل، صفر شکست، اختلاف NAV کمتر از یک تومان.
- ماتریس: ۱٬۴۴۰ مسیر ماهانه (۱٬۲۰۰ کامل و ۲۴۰ ناقص) و ۱۲ مسیر پیوسته.
- دفتر مستقل: ۲٬۴۲۴ ردیف، صفر عدم‌تطبیق؛ سالانه ۶۰ ردیف؛ نمونهٔ ماهانه ۸ مسیر.
- ۱۳ آزمون PASS؛ شبکه/کدال/DB/نصب بسته صفر؛ غربال و مصنوعات قبلی حفظ؛ commit انجام نشد.
- شش خطای اولیهٔ validator/runner و رفع آنها در `execution_incident_log.csv` ثبت شده‌اند.

نتایج تاریخی و اکتشافی‌اند و cutoff موتور اثبات زمان انتشار دادهٔ خام نیست. این تحویل پایان دامنهٔ V12.26 است.
