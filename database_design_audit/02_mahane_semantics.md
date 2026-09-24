# 02 — معنای واقعی `dbo.mahane`

> مبنا: trace مستقیم writerها. هیچ حدسی زده نشده؛ هر جا قطعی نیست `UNKNOWN` نوشته شده است.
> منبع اصلی: `py/MianSql2.py`، wrapper: `py/scraper2.py`، مسیر جدید: `py/codal_processor.py`، `py/sync_codal.py`.

## Writerها

| مسیر | فایل | تابع |
| --- | --- | --- |
| Go `run-script2` / `full_run_scripts` (`table="mahane"`) | `py/scraper2.py` → `MianSql2.main_scraper2(..., "mahane")` | `save_report_to_sql` |
| Discovery sync (LetterType=58) | `py/sync_codal.py` → `py/codal_processor.py::_process_monthly` | `MianSql2.parse_report_table` + `MianSql2.save_report_to_sql` |

نکته: `MianSql2.ensure_table` فقط ستون‌های `CompanyID, CompanyName, ReportDate, Value1, Value2, Value3, Url` با PK مرکب را می‌سازد. ستون‌های `ID` (IDENTITY) و `LastModificationDate` در `CREATE TABLE` این فایل **نیستند** → writer آن‌ها در سورس پیدا نشد (`UNKNOWN`).

## نگاشت ستون‌ها

| ستون DB | نوع | معنی business | منبع در Codal | واحد | مقیاس | یک‌ماهه/تجمعی | raw/derived |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CompanyID` | `nvarchar(50)` | شناسه‌ی داخلی شرکت = `md5(company_name)` (hex 32 char) | — (ساخت داخلی) | — | — | — | derived |
| `CompanyName` | `nvarchar(50)` | نام/نماد شرکت همان‌طور که به scraper پاس داده شده | — | — | — | — | raw |
| `ReportDate` | `nvarchar(50)` | تاریخ پایان دوره‌ی گزارش (شمسی) | `#ctl00_lblPeriodEndToDate` روی صفحه‌ی گزارش | — | — | — | raw |
| `Value1` | `float` | «تعداد تولید یک‌ماهه» | ستون هدر «تعداد تولید … دوره یک ماهه» در ردیف جمع | **UNKNOWN** (تعداد/مقدار؛ parser واحد تعداد را استخراج نمی‌کند) | — | **یک‌ماهه (non-cumulative)** | raw |
| `Value2` | `float` | «تعداد فروش یک‌ماهه» | ستون هدر «تعداد فروش … دوره یک ماهه» در ردیف جمع | **UNKNOWN** | — | **یک‌ماهه** | raw |
| `Value3` | `float` | «مبلغ فروش یک‌ماهه» یا «درآمد شناسایی‌شده طی دوره یک‌ماهه» | ستون «مبلغ فروش» (محصولی) یا «درآمد … طی دوره» (خدماتی) در ردیف جمع | **UNKNOWN** (MianSql2 واحد ارز را تشخیص نمی‌دهد) | — | **یک‌ماهه** | raw |
| `Url` | `varchar(550)` | آدرس ذخیره‌شده | در مسیر Go = URL لیست/فید (base_url)؛ در مسیر sync = URL خود گزارش | — | — | — | raw (ناسازگار بین دو مسیر) |
| `ID` | `int` IDENTITY | کلید مصنوعی | — | — | — | — | derived (writer در سورس یافت نشد) |
| `LastModificationDate` | `datetime2` | آخرین تغییر گزارش؟ | **UNKNOWN** — هیچ‌جا در سورس نوشته نمی‌شود | — | — | — | **UNKNOWN** |

## منطق استخراج `Value1/2/3` (از `MianSql2.extract_one_month_values`)

1. از هدر چندسطحی جدول، ستون‌هایی که هدرشان با الگوی `دوره\s*(?:یک|1)\s*ماهه` مطابق است انتخاب می‌شوند.
2. ردیف جمع واقعی (`جمع` / `جمع کل` / `مجموع` / regex `جمع( کل)? درآمدهای? عملیاتی`) پیدا می‌شود.
3. دو حالت:
   - **گزارش محصولی:** اگر هر سه ستون «تعداد تولید»، «تعداد فروش»، «مبلغ فروش» باشند → `[production, sales_quantity, sales_amount]` (یعنی همان `Value1, Value2, Value3`).
   - **گزارش خدماتی/درآمدی:** اگر ستون «درآمد» باشد → `[0, 0, one_month_revenue]`.
4. اگر نوع ستون‌های یک‌ماهه پشتیبانی نشود → `[]` و رکورد ذخیره نمی‌شود.

## قطعی‌ها

- `Value1` و `Value2` برای گزارش‌های خدماتی همیشه **صفر** هستند.
- `Value3` **یک‌ماهه** است، نه تجمعی (کلیدواژه‌ی «طی دوره یک‌ماهه»).
- `CompanyID` یک hash داخلی است، نه شناسه‌ی کدال (TracingNo/ISIN/Symbol).

## `UNKNOWN`ها

- **واحد Value1/2/3:** legacy parser واحد ارز را استخراج نمی‌کند (برخلاف `py2.detect_currency_unit`). مقیاس واقعی (ریال/هزار ریال/میلیون ریال) از کد قابل اثبات نیست.
- **مقیاس تعداد Value1/2:** واحد «تعداد/مقدار» (سهم/تن/کیلوگرم/…) استخراج نمی‌شود.
- **نویسنده و معنای `LastModificationDate`:** در سورس یافت نشد.
- **معنی دقیق `Url` در داده‌ی موجود:** بسته به مسیر قدیمی/جدید متفاوت است و در snapshot فعلی DB قابل تفکیک نیست.
