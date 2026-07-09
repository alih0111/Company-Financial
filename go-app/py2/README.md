# Codal Ingestor

این پروژه گزارش‌های فعالیت ماهانه و صورت سود و زیان کدال را با Playwright می‌خواند و در PostgreSQL ذخیره می‌کند.

## اتصال فعلی

فایل `.env` برای PostgreSQL محلی تنظیم شده است:

- Host: `localhost`
- Port: `5432`
- User: `postgres`
- Database: `postgres`

رمز دارای `@` است و در URL به صورت `%40` نوشته شده است.

## نصب

از داخل پوشه `py`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

اگر `CHROMIUM_BINARY` در `.env` معتبر است نیازی به دانلود Chromium پلی‌رایت نیست. در غیر این صورت آن را خالی کنید و اجرا کنید:

```powershell
playwright install chromium
```

## ایجاد جدول‌ها

جدول‌ها هنگام اولین اجرا خودکار ایجاد می‌شوند. اجرای دستی نیز ممکن است:

```powershell
codal-ingest init-schema
```

## اجرای مستقیم

صورت سود و زیان:

```powershell
codal-ingest scrape profit-loss `
  --company-name "نام شرکت" `
  --base-url "CODAL_LIST_URL" `
  --pages "1,2" `
  --row-limit 20
```

گزارش ماهانه:

```powershell
codal-ingest scrape monthly `
  --company-name "نام شرکت" `
  --base-url "CODAL_LIST_URL" `
  --pages "1,2" `
  --row-limit 20
```

## سازگاری با Go قدیمی

این دو فایل همان آرگومان‌های قبلی را می‌پذیرند:

```powershell
python scraper.py "نام شرکت" 20 "CODAL_LIST_URL" "[1,2]"
python scraper2.py "نام شرکت" 20 "CODAL_LIST_URL" "[1,2]"
```

- `scraper.py`: صورت سود و زیان
- `scraper2.py`: فعالیت ماهانه

خروجی نهایی هر اجرا JSON است. Logها روی stderr نوشته می‌شوند.

## جدول‌های PostgreSQL

- `companies`
- `reports`
- `report_versions`
- `monthly_activities`
- `financial_facts`

گزارش‌های اصلاحی به عنوان نسخه جدید در `report_versions` حفظ می‌شوند و اطلاعات جاری Upsert می‌شود.
