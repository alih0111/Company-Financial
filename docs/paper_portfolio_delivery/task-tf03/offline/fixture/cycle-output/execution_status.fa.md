# وضعیت سفارش آزمایشی V12.38

آخرین بررسی UTC: `2026-10-24T21:37:33.264928+00:00`
حساب: `TF03_SYNTHETIC_TEMP` · تصمیم: `paper-decision-3e413c0bb9882c28e361` · سفارش: `paper-order-73610cd727cd6a706a34`
تصمیم اصلی حفظ شده: `2026-10-23T06:00:00+00:00` · وضعیت اجرا: `PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE` · fill ثبت‌شده: خیر

## دو مانع مستقل

1. **هنوز دادهٔ جلسهٔ پس از تصمیم موجود نیست** — آخرین جلسهٔ کامل اعلام‌شده نامعلوم است؛ پس از تاریخ تصمیم 2026-10-23 هنوز جلسهٔ کامل‌شده‌ای در این دریافت دیده نمی‌شود.
2. **دسترسی به منبع معتبر تقویم ناقص است** — تقویم محلی score_v2_research/_cache/calendar.parquet تا 2026-10-03 (7826 ردیف) است و پیش از تصمیم پایان می‌یابد. LastPossibleDeven فقط آخرین روز تکمیل‌شده را می‌دهد؛ GetInstrumentCalendar و GetClosingPriceDailyList فقط مشاهدات همان نماد غاذرند و به‌تنهایی تقویم کامل بازار نیستند. در کد پروژه، مسیر رسمی NSCStart برای فهرست جلسات بازار مستند شده و bearer token می‌خواهد؛ این یک مسیر است و نبود توکن آن را مانع همهٔ مسیرهای معتبر نمی‌کند. در فایل‌های محلی/مسیرهای عمومی رسمیِ بررسی‌شده، تقویم سراسری جدیدتری پیدا نشد.

آخرین جلسهٔ کامل اعلام‌شده نامعلوم است؛ پس از تاریخ تصمیم 2026-10-23 هنوز جلسهٔ کامل‌شده‌ای در این دریافت دیده نمی‌شود.

## مسیرهای تقویم بررسی‌شده

- LastPossibleDeven رسمی: فقط آخرین جلسهٔ کامل‌شده.
- GetInstrumentCalendar و GetClosingPriceDailyList غاذر: تاریخچهٔ یک نماد، نه تقویم کامل بازار.
- فایل تقویم محلی: تا `2026-10-03`؛ پس از تصمیم را نمی‌پوشاند.
- مستند رسمی TSETMC برای NSCStart: فهرست روزهای باز بازار را تعریف می‌کند و نمونهٔ درخواستش bearer token دارد. این یکی از مسیرهاست، نه اثبات اینکه همهٔ مسیرهای رسمی به توکن نیاز دارند.

اگر NSCStart انتخاب شد، در PowerShell این روند را در همان نشست اجرا کنید: `$s=Read-Host 'TSETMC read-only token' -AsSecureString; $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try { $env:TSETMC_READONLY_BEARER_TOKEN=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p); .venv\Scripts\python.exe ranking_research\future_eval_v12_30\acquire_tsetmc_open_sessions.py } finally { Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue; [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p); $s.Dispose() }`. توکن وارد history، فایل، فرانت، گزارش یا Git نمی‌شود؛ اسکریپت آن را چاپ یا ذخیره نمی‌کند.

فرمان واحد بررسی دستی از ریشهٔ پروژه: `powershell -NoProfile -ExecutionPolicy Bypass -File ranking_research\future_eval_v12_30\check_paper_order.ps1`. ورود توکن فقط‌خواندنی در SecureString prompt است. دریافت و بررسی دستی است؛ پایش خودکار فعال نیست.

آشتی نقد/دارایی: 100000 + 0 = 100000 تومان؛ برابر بودن: `True`. دفتر رسمی دست‌نخورده است.

## تقویم عمومی (پروفایل آزمایشی)

- نخستین جلسهٔ پذیرفته‌شدهٔ تقویم عمومی موجود است — نخستین جلسهٔ قابل استفاده 20261024 با 1 جلسهٔ پذیرفته‌شدهٔ پس از تصمیم؛ سبد کاغذی با تقویم عمومی؛ پایان جلسه بر پایهٔ فرض ثبت‌شده، بدون گواه کامل‌بودن تقویم شاهد معاملهٔ نامزد: candidate_data_covers_target_day (پایان آرشیو 20261024).
- سازگاری حساب با این سیاست: `compatible`.
- کیفیت بازمحاسبه‌شده از raw: `CORROBORATED_PUBLIC`؛ تازگی: `FRESH`.
- برچسب نمایش: سبد کاغذی با تقویم عمومی؛ پایان جلسه بر پایهٔ فرض ثبت‌شده، بدون گواه کامل‌بودن تقویم

- مسیر عمومی بدون توکن: دو شاخص بورس تهران + LastPossibleDeven از endpointهای عمومی؛ پایان جلسه فرض ثبت‌شدهٔ سیاست است، نه گواه رسمی.
