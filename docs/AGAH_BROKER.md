# اتصال سبد به کارگزاری آگاه

خواندن سبد (تعداد + میانگین خرید) و مانده نقدی هر شخص از پنل معاملات برخط آگاه و
جایگزینی کامل داده‌های آن شخص.

- پنل ورود: `https://online.agah.com/login`
- صفحه پرتفو: `https://online.agah.com/auth/portfolio/asset`
- روش: فقط ورود وب (بدون API رسمی) — ورود دستی کد امنیتی در هر سینک.

## اجزا

| بخش | مسیر |
| --- | --- |
| اسکیما | `canonical_postgres_v1_2_1/sql/110_family_broker.sql` |
| اعمال اسکیما | `canonical_postgres_v1_2_1/migration_tools/apply_family_schema.py` |
| رمزنگاری اعتبارنامه | `go-app/config/secrets.go` (AES-256-GCM) |
| کالکتور پایتون | `go-app/py/broker_agah.py` (Playwright) |
| هندلرها | `go-app/handlers/family_broker_pg.go` |
| UI | تب «کارگزاری آگاه» در `client/src/components/FamilyAssets.tsx` |

## راه‌اندازی

1. کلید رمزنگاری در `go-app/.env`:
   ```
   CDF_SECRET_KEY=<۳۲ بایت base64>
   ```
   تولید: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
2. اعمال اسکیما: `python canonical_postgres_v1_2_1/migration_tools/apply_family_schema.py`
3. از تب «کارگزاری آگاه» در صفحه assets، برای هر شخص «تنظیم حساب» را زده و
   نام کاربری/کد ملی و کلمه عبور را ذخیره کنید (رمز رمزنگاری‌شده ذخیره می‌شود).
4. دکمه «سینک از آگاه» (هر شخص) یا «سینک همه از آگاه».

## جریان سینک

1. سرور یک job پس‌زمینه می‌سازد و کالکتور Playwright را با مرورگر headed اجرا می‌کند.
2. نام کاربری/رمز از قبل پر می‌شود؛ **کد امنیتی را در پنجره مرورگر وارد کنید** و
   وارد شوید (تا ۳۰۰ ثانیه فرصت).
3. پس از ورود، سبد و مانده نقدی خوانده و به‌صورت JSON برگردانده می‌شود.
4. هرگز رمز/توکن لاگ نمی‌شود؛ snapshot خام در `family.broker_snapshots` ذخیره می‌شود.
5. سبد شخص با داده کارگزاری **کامل جایگزین** می‌شود (holdings + مانده حساب).

## API (فقط ادمین)

| متد | مسیر | توضیح |
| --- | --- | --- |
| GET | `/api/family/broker` | فهرست حساب‌های کارگزاری هر شخص |
| PUT | `/api/family/broker` | ذخیره/ویرایش `{person_id, username, password?, is_active?}` |
| DELETE | `/api/family/broker?person_id=` | حذف اتصال |
| POST | `/api/family/sync-broker` | شروع سینک `{person_id}` یا `{all:true}` → `{jobs:[...]}` |
| GET | `/api/family/sync-broker/status?job_id=` | وضعیت job (polling) |

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
در `broker_agah.py` تنظیم می‌شوند.

## نکات

- **واحد پول**: مقادیر عیناً همان‌طور که پنل نمایش می‌دهد وارد می‌شوند؛ در صورت
  اختلاف ریال/تومان باید در `reconcileBrokerHoldingsPG` تبدیل اعمال شود.
- **چند پرتفو در یک حساب**: فعلاً همه دارایی‌ها جمع می‌شوند.
- تطبیق نماد کارگزاری با `family.assets` بر اساس نماد/نام انجام می‌شود و در
  صورت نبود، دارایی جدید ساخته می‌شود.
- اسکرپینگ پنل ممکن است با شرایط استفاده کارگزاری مغایرت داشته باشد؛
  مسئولیت آن با کاربر است.
