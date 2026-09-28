# اتصال سبد به کارگزاری آگاه

خواندن سبد (تعداد + میانگین خرید) و مانده نقدی هر شخص از پنل معاملات برخط آگاه و
جایگزینی کامل داده‌های آن شخص.

- پنل ورود: `https://online.agah.com/login`
- صفحه پرتفو: `https://online.agah.com/auth/portfolio/asset`
- روش: فقط ورود وب (بدون API رسمی) — **کد امنیتی خودکار حل می‌شود**؛ اگر سایت
  نپذیرد، تصویر کپچا در UI ادمین نمایش داده می‌شود تا همان‌جا وارد شود.

## کپچا و نشست (رفع اشکال قبلی)

- **حل خودکار کپچا**: تصویر کپچای پنل یک data-URL داخل DOM است و با `ddddocr`
  خوانده می‌شود (نصب: `pip install ddddocr`). تا ۲ تلاش خودکار انجام می‌شود.
- **مسیر دستی (fallback)**: اگر OCR نصب نباشد یا کد رد شود، تصویر کپچا از طریق
  `challenge.json` به سرور/UI می‌رسد؛ کد وارد‌شده در UI با POST
  `/api/family/sync-broker/captcha` در `answer.json` نوشته می‌شود و کالکتور
  همان را وارد می‌کند. **دیگر لازم نیست کسی پای سرور کپچا بزند.**
- **جداسازی نشست اشخاص**: پروفایل مرورگر هر شخص جداگانه است
  (`.runtime/chromium-profile-agah/<کلید-نام-کاربری>`). قبلاً یک پروفایل مشترک
  باعث می‌شد سینک نفر دوم بدون صفحه لاگین با حساب نفر اول وارد شود؛ این اصلاح
  شده است.
- **استفاده مجدد از نشست**: چون پروفایل هر شخص ماندگار است، سینک بعدیِ همان
  شخص تا اعتبار نشست کدگزاری **بدون کپچا** انجام می‌شود (`login.mode=session`).
- ورود headless توسط پنل بسته به شبکه ممکن است به `connection-error` برود
  (API پنل `tseonlineapi.agah.com` در برخی مسیرها مرورگر headless را نمی‌پذیرد)؛
  پیش‌فرض headed است ولی چون همه‌چیز خودکار است پنجره را کسی نباید لمس کند.

## اجزا

| بخش | مسیر |
| --- | --- |
| اسکیما | `canonical_postgres_v1_2_1/sql/110_family_broker.sql` |
| اعمال اسکیما | `canonical_postgres_v1_2_1/migration_tools/apply_family_schema.py` |
| رمزنگاری اعتبارنامه | `go-app/config/secrets.go` (AES-256-GCM) |
| کالکتور پایتون | `go-app/py/broker_agah.py` (Playwright + OCR) |
| هندلرها | `go-app/handlers/family_broker_pg.go` |
| UI | تب «کارگزاری آگاه» در `client/src/components/FamilyAssets.tsx` |
| تست آفلاین پارسر/کپچا | `go-app/py/tests/test_broker_agah_offline.py`، `test_broker_captcha_offline.py` |
| تست E2E روی سرور mock | `go-app/py/tests/test_broker_e2e_mock.py` (+ `mock_agah_server.py`) |

## راه‌اندازی

1. کلید رمزنگاری در `go-app/.env`:
   ```
   CDF_SECRET_KEY=<۳۲ بایت base64>
   ```
   تولید: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
2. وابستگی کالکتور:
   ```
   pip install playwright ddddocr
   ```
   اگر کرومیوم playwright نصب نیست، کروم سیستمی استفاده می‌شود (`channel=chrome`).
3. اعمال اسکیما: `python canonical_postgres_v1_2_1/migration_tools/apply_family_schema.py`
4. از تب «کارگزاری آگاه» در صفحه assets، برای هر شخص «تنظیم حساب» را زده و
   نام کاربری/کد ملی و کلمه عبور را ذخیره کنید (رمز رمزنگاری‌شده ذخیره می‌شود).
5. دکمه «سینک از آگاه» (هر شخص) یا «سینک همه از آگاه».

## جریان سینک

1. سرور یک job پس‌زمینه می‌سازد و کالکتور را اجرا می‌کند (پیش‌فرض headed؛
   با `CDF_AGAH_HEADLESS=1` روی سرور headless).
2. اگر نشست فعال آن شخص در پروفایلش باشد، ورود کلاً رد می‌شود.
3. وگرنه: نام کاربری/رمز + کپچای OCR‌شده پر و «ورود» کلیک می‌شود. اگر ورود
   رد شود، با کپچای تازه دوباره تلاش می‌شود؛ بعد از ۲ شکست OCR، کپچا به UI
   منتشر می‌شود (کادر زرد «ثبت کد» در تب کارگزاری) و تا ۳۰۰ ثانیه منتظر
   می‌ماند. جریان فایل‌ها: `challenge.json` (تصویر data-URL) و `answer.json`
   (`{"code": "..."}`) در `%TEMP%/agah-sync/exchange/<job_id>`.
4. پس از ورود، سبد و مانده نقدی خوانده و به‌صورت JSON برگردانده می‌شود
   (`login.mode` یکی از `auto|manual|session`).
5. هرگز رمز/توکن لاگ نمی‌شود؛ snapshot خام در `family.broker_snapshots` ذخیره می‌شود.
6. سبد شخص با داده کارگزاری **کامل جایگزین** می‌شود (holdings + مانده حساب).
7. برای یک شخص هم‌زمان بیش از یک سینک اجرا نمی‌شود (۴۰۹ از API).

## API (فقط ادمین)

| متد | مسیر | توضیح |
| --- | --- | --- |
| GET | `/api/family/broker` | فهرست حساب‌های کارگزاری هر شخص |
| PUT | `/api/family/broker` | ذخیره/ویرایش `{person_id, username, password?, is_active?}` |
| DELETE | `/api/family/broker?person_id=` | حذف اتصال |
| POST | `/api/family/sync-broker` | شروع سینک `{person_id}` یا `{all:true}` → `{jobs:[...]}` |
| GET | `/api/family/sync-broker/status?job_id=` | وضعیت job (شامل `needs_captcha`/`captcha_image`) |
| POST | `/api/family/sync-broker/captcha` | ارسال کد امنیتی `{job_id, code}` |

## متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
| --- | --- | --- |
| `CDF_AGAH_HEADLESS` | خالی (headed) | `1` = اجرای headless روی سرور |
| `AGAH_DISABLE_OCR` | خالی | `1` = غیرفعال‌کردن OCR و رفتن مستقیم به مسیر دستی |
| `CHROMIUM_BINARY` | خالی | مسیر صریح chrome.exe؛ در نبود آن کروم سیستمی/باندل‌شده |
| `CDF_PYTHON` | `python` | مفسر پایتون کالکتور |

## تست‌ها

```
cd go-app
python -m unittest py.tests.test_broker_agah_offline py.tests.test_broker_captcha_offline   # سریع/آفلاین
python -m unittest py.tests.test_broker_e2e_mock                                            # E2E روی mock (کند)
```

تست E2E کل چرخه (ورود خودکار OCR، استفاده مجدد نشست، کپچای دستی از طریق
exchange، و ردشدن ورود با پروفایل تازه/رمز اشتباه) را روی سرور mock با همان
سلکتورهای پنل واقعی می‌آزماید.

## کشف ساختار پنل (اگر parser ناموفق بود)

اگر job با پیام «ساختار پنل ناشناخته است» برگردد، خروجی خام در مسیر
`captured.dump_dir` ذخیره شده است (فایل‌های `resp_*.json` و `page.html`).
برای نهایی‌کردن parser:
```
$env:CHROMIUM_BINARY="<مسیر chrome.exe>"
'{"username":"...","password":"...","headless":true,"timeout_sec":300}' |
  python go-app/py/broker_agah.py --out result.json --dump-dir dump --timeout 300
```
سپس کلیدهای واقعی پنل در توابع `parse_dom_tables` / `parse_json_payloads`
در `broker_agah.py` تنظیم می‌شود.

## نکات

- **واحد پول**: مقادیر عیناً همان‌طور که پنل نمایش می‌دهد وارد می‌شوند؛ در صورت
  اختلاف ریال/تومان باید در `reconcileBrokerHoldingsPG` تبدیل اعمال شود.
- **چند پرتفو در یک حساب**: فعلاً همه دارایی‌ها جمع می‌شوند.
- تطبیق نماد کارگزاری با `family.assets` بر اساس نماد/نام انجام می‌شود و در
  صورت نبود، دارایی جدید ساخته می‌شود.
- **اولین سینک پس از این تغییر**: پروفایل‌های جدید از نو ساخته می‌شوند؛ اولین
  ورود هر شخص با OCR خودکار انجام می‌شود (اگر نشد، کادر کپچا در UI).
- اسکرپینگ پنل ممکن است با شرایط استفاده کارگزاری مغایرت داشته باشد؛
  مسئولیت آن با کاربر است.
