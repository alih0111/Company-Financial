# بررسی استحکام FactorMix — پوشهٔ کاری

- `REPORT.fa.md`: آزمون‌های استحکام نسخهٔ ماهانه ۱۵ (هزینه، روز بازبینی، تعداد سهم، طلا).
- `factor_tests/REPORT.fa.md`: آزمون وزن‌ها، اندیکاتورها و walk-forward روی دادهٔ بازسازی‌شده.
- `diagnostics/`: مقایسهٔ دادهٔ منجمد با دادهٔ رویدادی (مرحلهٔ بعد).

## کاری که روی سیستم اصلی باید اجرا شود

این مرحله فقط خواندنی است. به دیتابیس و اینترنت نیاز ندارد و هیچ استراتژی یا حسابی را تغییر نمی‌دهد. فقط روی سیستمی اجرا شود که پوشه‌های دادهٔ پژوهشی را دارد (`ranking_research/output/...`، `fundamental_event_research/...`، `score_v2_research/`).

از ریشهٔ پروژه:

```
python -B robustness_review_20261107/diagnostics/diagnose_frozen_vs_event.py
```

سپس پوشهٔ `robustness_review_20261107/diagnostics/results_diag/` را commit و push کنید. حجمش باید چند مگابایت باشد. اگر خطا داد، فایل `ERROR.txt` در همان پوشه ساخته می‌شود؛ همان را push کنید.
