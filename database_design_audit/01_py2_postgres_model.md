# 01 — مدل فعلی PostgreSQL در `go-app/py2/`

> این سند فقط مستندسازی است. هیچ چیزی تغییر نکرده است.
> منبع: `py2/src/codal_ingestor/{models,domain,repository,db,config}.py` + `py2/alembic/versions/0001_initial.py`.

## خلاصه‌ی معماری py2

`py2` یک خط لوله‌ی **جدا و موازی** نسبت به خط لوله‌ی SQL Server (`py/`) است:

- **Stack:** Playwright (Chromium) → BeautifulSoup → SQLAlchemy 2.x (Declarative `Mapped`) → PostgreSQL.
- **Migration:** Alembic (`0001_initial`) که با `models.py` هم‌خوان است.
- **Schema auto-create:** علاوه بر Alembic، `db.ensure_schema()` با `Base.metadata.create_all` هم schema را می‌سازد و `config.auto_create_schema` (پیش‌فرض `True`) آن را فعال می‌کند.
- **نقطه‌ی ورود:** `cli.py` (دستور `codal-ingest scrape monthly|profit-loss` و `init-schema`) + لایه‌ی سازگاری `scraper.py`/`scraper2.py` با آرگومان‌های Go قدیمی.
- **اتصال به SQL Server نداند:** طبق `14_source_usage.md`، هیچ ارجاعی به جدول‌های `codal` در `py2` وجود ندارد. کاملاً PostgreSQL.

## جدول `companies`

| ستون | نوع | Null | PK | UNIQUE | توضیح |
| --- | --- | --- | --- | --- | --- |
| `id` | `UUID` (`as_uuid=True`) | NOT NULL | ✅ PK | | پیش‌فرض `uuid.uuid4` |
| `name` | `Text` | NOT NULL | | | نام اصلی شرکت (همان ورودی) |
| `normalized_name` | `Text` | NOT NULL | | ✅ | `normalize_company_name` (lower + normalize) |
| `symbol` | `String(32)` | NULL | | | **هیچ‌جا توسط repository پر نمی‌شود → همیشه NULL** |
| `instrument_code` | `String(64)` | NULL | | ✅ | **هیچ‌جا پر نمی‌شود → همیشه NULL** |
| `is_active` | `Boolean` | NOT NULL (default True) | | | upsert آن را True می‌کند |
| `created_at` | `DateTime(tz)` | NOT NULL (`now()`) | | | |
| `updated_at` | `DateTime(tz)` | NOT NULL (`now()`, onupdate) | | | |

- Relationship: `reports` (۱ به چند).
- **upsert:** بر اساس `normalized_name` (`on_conflict_do_update`، name و is_active بروز می‌شوند).
- **نکته مهم:** با اینکه ستون‌های `symbol` و `instrument_code` طراحی شده‌اند، در کل مسیر ingestion پر نمی‌شوند؛ بنابراین identity شرکت در Postgres فعلی صرفاً از روی `normalized_name` است.

## جدول `reports`

| ستون | نوع | Null | کلید | توضیح |
| --- | --- | --- | --- | --- |
| `id` | `UUID` | NOT NULL | PK | |
| `company_id` | `UUID` | NOT NULL | FK → `companies.id` ON DELETE CASCADE | |
| `report_type` | `String(32)` | NOT NULL | | مقادیر: `monthly_activity` یا `profit_loss` |
| `period_end_jalali` | `String(10)` | NOT NULL | UQ (ترکیبی) | `YYYY/MM/DD` شمسی |
| `period_end_date` | `Date` | NOT NULL | | معادل میلادی (`jalali_to_gregorian`) |
| `current_source_url` | `Text` | NOT NULL | | URL آخرین نسخه |
| `current_content_hash` | `String(64)` | NOT NULL | | sha256 canonical payload |
| `collected_at` | `DateTime(tz)` | NOT NULL (`now()`) | | |
| `updated_at` | `DateTime(tz)` | NOT NULL (`now()`, onupdate) | | |

- **UNIQUE:** `uq_reports_company_type_period (company_id, report_type, period_end_jalali)`.
- **Index:** `ix_reports_company_type_date (company_id, report_type, period_end_date)`.
- **Relationship:** `versions` (۱:N)، `monthly_activity` (۱:۱ اختیاری)، `financial_facts` (۱:N).
- **منطق upsert:** اگر رکورد موجود و `current_content_hash == digest` باشد → `unchanged` (هیچ نسخه‌ی جدیدی ساخته نمی‌شود). وگرنه `reports` آپدیت و یک ردیف جدید در `report_versions` درج می‌شود.

## جدول `report_versions`

| ستون | نوع | Null | کلید | توضیح |
| --- | --- | --- | --- | --- |
| `id` | `BigInteger` (autoincrement) | NOT NULL | PK | |
| `report_id` | `UUID` | NOT NULL | FK → `reports.id` CASCADE | |
| `source_url` | `Text` | NOT NULL | | |
| `content_hash` | `String(64)` | NOT NULL | UQ (ترکیبی) | |
| `raw_payload` | `JSONB` | NOT NULL | | canonical payload کل گزارش |
| `collected_at` | `DateTime(tz)` | NOT NULL (`now()`) | | |

- **UNIQUE:** `uq_report_versions_hash (report_id, content_hash)`.
- **منطق:** تاریخچه‌ی نسخه‌ها (گزارش‌های اصلاحی نسخه‌ی جدید می‌سازند)؛ درج با `on_conflict_do_nothing`.

## جدول `monthly_activities`

| ستون | نوع | Null | کلید | توضیح |
| --- | --- | --- | --- | --- |
| `report_id` | `UUID` | NOT NULL | PK و FK → `reports.id` CASCADE | ۱:۱ با report |
| `production_quantity` | `Numeric(30,4)` | NULL | | تعداد تولید (فقط محصولی) |
| `sales_quantity` | `Numeric(30,4)` | NULL | | تعداد فروش (فقط محصولی) |
| `sales_amount` | `Numeric(30,4)` | NULL | | مبلغ فروش/درآمد یک‌ماهه |
| `domestic_sales_amount` | `Numeric(30,4)` | NULL | | جمع فروش داخلی |
| `export_sales_amount` | `Numeric(30,4)` | NULL | | جمع فروش صادراتی |
| `currency_unit` | `String(16)` | NOT NULL (default `unknown`) | | از `detect_currency_unit` |
| `quantity_unit` | `String(32)` | NOT NULL (default `reported_unit`) | | همیشه `reported_unit` |

- **توجه ساختاری:** این جدول **totals** یک دوره‌ی یک‌ماهه را نگه می‌دارد؛ معادل ستون‌های `Value1/2/3` در `mahane` است ولی نام‌گذاری‌شده و واحد آن استخراج می‌شود.
- upsert: `on_conflict_do_update` روی `report_id`.

## جدول `financial_facts`

| ستون | نوع | Null | کلید | توضیح |
| --- | --- | --- | --- | --- |
| `id` | `BigInteger` (autoincrement) | NOT NULL | PK | |
| `report_id` | `UUID` | NOT NULL | FK → `reports.id` CASCADE | |
| `period_order` | `SmallInteger` | NOT NULL | UQ (ترکیبی) | ۱..۳ (ستون‌های دوره) |
| `period_header` | `Text` | NOT NULL | | هدر خام دوره |
| `metric_code` | `String(64)` | NOT NULL | UQ (ترکیبی) | `net_eps`, `capital`, `operating_eps`, `operating_profit`, `net_profit` |
| `value` | `Numeric(30,4)` | NULL | | |
| `unit_code` | `String(32)` | NOT NULL | | `rial_per_share` یا واحد مبلغی گزارش |

- **UNIQUE:** `uq_financial_fact_metric (report_id, period_order, metric_code)`.
- **Index:** `ix_financial_facts_report_metric (report_id, metric_code)`.
- upsert: قبل از درج، همه‌ی factهای قبلی همان report حذف می‌شوند (`delete` + `add_all`).

## منطق دامنه (`domain.py`)

- `normalize_text`: ارقام فارسی/عربی → ASCII، حذف نویسه‌های نامرئی، یکسان‌سازی `ي/ك`، فشرده‌سازی فاصله.
- `normalize_label`: علاوه بر بالا، حذف نقطه‌گذاری/براکت و lowercase (برای تطبیق عنوان ردیف‌ها).
- `normalize_company_name`: `normalize_text(...).lower()` + خطا در صورت خالی بودن.
- `normalize_jalali_date` / `jalali_to_gregorian`: با `jdatetime`.
- `to_decimal`: پاکسازی اعداد متنی (کاما، ارقام فارسی، پرانتز منفی).
- `content_hash`: sha256 از JSON مرتب‌شده.

## منطق parserها (خلاصه‌ی معنایی)

- **`monthly.py` parser:** جدول `table.rayanDynamicStatement` را پیدا می‌کند، ستون‌های «دوره یک ماهه» را می‌شناسد، ردیف جمع (`جمع`/`جمع کل`/`جمع درآمدهای عملیاتی`) را می‌خواند و بر اساس وجود «مبلغ فروش» (محصولی) یا «درآمد» (خدماتی) مقادیر را برمی‌دارد. واحد ارز با `detect_currency_unit` (میلیون/هزار/ریال) تشخیص داده می‌شود؛ در صورت unknown پیش‌فرض `million_rial`.
- **`profit_loss.py` parser:** جدول صورت سود و زیان را با نشانه‌ها شناسایی می‌کند، تا ۳ ستون دوره می‌گیرد، و ۵ متریک (`net_eps`, `capital`, `operating_eps`, `operating_profit`, `net_profit`) را برای هر دوره ذخیره می‌کند. `detect_currency_unit` برای مبالغ و `rial_per_share` برای هر سهم.

## شکاف‌های مدل py2 نسبت به SQL Server فعلی

py2 فعلاً فقط دو دامنه را پوشش می‌دهد (**فعالیت ماهانه** و **سود و زیان**). این‌ها در py2 وجود ندارند:

- قیمت بازار (MarketPriceHistory / StockData / StockPrices)
- نسبت P/E (FullPE)
- کاربران/احراز هویت/portfolio (Users)
- دارایی خانواده (Family*)
- موتور امتیازدهی (vw_AIStockMetrics) و AI handler
- universe نمادها (TrackedTickers) و registry کدال (CodalReports/CodalSyncState)

همچنین **هیچ‌کدام** از ستون‌های ترازنامه/جریان نقدی موجود در `miandore2` (مثل `TotalAssets`, `OperatingCashFlow`) در مدل py2 معادل ندارند.

## جمع‌بندی وضعیت

py2 یک **پایه‌ی مدل‌سازی تمیز و نرمال‌شده** است (UUID، FK واقعی، UNIQUE، JSONB، Numeric، تاریخ میلادی، کشف واحد) اما دامنه‌ی آن کامل نیست و به خط لوله‌ی SQL Server وصل نیست.
