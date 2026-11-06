# واگذاری V12.4

## وضعیت جاری

- صفحهٔ موجود `/ranking/research/v12-1` از `client/public/research/return-v12-4.json` استفاده می‌کند؛ ۲۲۷ نماد رتبه گرفته‌اند از ۲۵۰ هویت دقیق؛ ۲۳ مورد به دلیل نبود snapshot مالی تأییدشده کنار گذاشته شدند.
- Snapshot `ranking_research/output/return_v12_4/current_20261019T182410459499Z`، cutoff `2026-10-19T18:24:10.459499Z`، قیمت تا 2026-10-19؛ پایان جلسه تأیید نشده.
- پوشش فروش ۱۲ماهه ۸۳/۲۲۷، فروش ۳ماهه ۹۵/۲۲۷، ثبات ۹۱/۲۲۷، نوسان ۰/۲۲۷، شتاب ۰/۲۲۷. دادهٔ فروش امروز فقط رتبهٔ جاری را پشتیبانی می‌کند؛ published_at تهی است و PIT تاریخی نیست.
- روش‌های A/B/C روی تاریخچهٔ دیده‌شده اجرا شدند؛ مستقل نیستند. هیچ default انتخاب نشد.
- کدال بنا به دستور کاربر متوقف شد: ۵۹ موفق، ۶ خطا و ۴۳۵ درخواست از ۵۰۰ انجام‌نشده. فایل checkpoint در `ranking_research/output/return_v12_4/codal_catalog_20261019T182052Z/` است.

## فرمان‌ها

```powershell
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_4.refresh
```

```powershell
$env:CDF_PILOT_DB='v12_4_offline_replay_must_not_connect'
.\.venv\Scripts\python.exe -B -m ranking_research.return_v12_4.current_snapshot --replay ranking_research/output/return_v12_4/current_20261019T182410459499Z
```

## فایل‌ها و ادامهٔ کار

- گزارش: `docs/RETURN_V12_4_FINAL.fa.md`
- قرارداد: `ranking_research/output/return_v12_4/contract_20261019T182410459499Z.json`
- manifest: `ranking_research/output/return_v12_4/delivery_manifest.json`
- audit استفاده و نتایج روش: `ranking_research/output/return_v12_4/evaluation_20261019T180728Z/`
- ابتدا با اجازهٔ بعدی/دستور کاربر اجرای کدال را از checkpoint تکمیل کنید؛ failed از no-report جدا بماند.
- سپس published_at/tracing_no ماهانه را ثبت کنید، زنجیرهٔ adjustment را اثبات کنید، آزمون‌های مرورگر و CSV را با دسترسی معتبر انجام دهید و failure injection/هم‌زمانی را بیازمایید.
- PIT و سابقهٔ مصرف کامل لازم است تا آزمون مستقل آینده ممکن شود.

هیچ سفارش واقعی ارسال نشده و وزن نقدشوندگی صفر مانده است.
