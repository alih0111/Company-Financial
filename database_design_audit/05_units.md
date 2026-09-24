# 05 — Unit Audit

> مبنا: parserها و `vw_AIStockMetrics`. هیچ حدسی زده نشده؛ واحدهای نامعلوم `UNKNOWN`.

## خلاصه‌ی واحدها در هر خط لوله

| دامنه | خط لوله | کشف واحد؟ | واحدهای شناخته‌شده در کد |
| --- | --- | --- | --- |
| `mahane` (فعالیت ماهانه) | `py/MianSql2.py` | **خیر** | فقط تعداد/مبلغ خام؛ واحد `UNKNOWN` |
| `miandore2` (سود و زیان/ترازنامه/جریان) | `py/MianSql.py` | **خیر** | per-share به‌صورت ضمنی «ریال/سهم»؛ مبالغ `UNKNOWN` |
| `monthly_activities` (Postgres) | `py2/parsers/monthly.py` | **بله** | `million_rial`, `thousand_rial`, `rial`, `unknown` |
| `financial_facts` (Postgres) | `py2/parsers/profit_loss.py` | **بله** | `rial_per_share` + `detect_currency_unit` برای مبالغ |
| قیمت بازار | `py/brs_prices.py`, `py/price.py` | خیر (عدد خام) | `UNKNOWN` (BRS/TSETMC معمولاً ریال) |

`detect_currency_unit` (فقط در `py2`): «میلیون ریال» → `million_rial`، «هزار ریال» → `thousand_rial`، «ریال» → `rial`؛ در غیر این صورت `unknown` که به `million_rial` نگاشت می‌شود.

## واحدهای per-share

- در `miandore2`: `Num1_*` (EPS خالص) و `Num4_*` (EPS عملیاتی) از ردیف‌هایی می‌آیند که عنوانشان «... هر سهم – ریال» است → **ریال بر سهم**.
- در `py2.financial_facts`: `metric_code`های `net_eps` و `operating_eps` با `unit_code = rial_per_share`.

## ارتباط واحد میان شاخص‌ها (منبع پیچیدگی view)

| ستون | واحد واقعی | توضیح |
| --- | --- | --- |
| `EPS` (`Num1_Value1`) | ریال/سهم | per-share |
| `Product1` | **مقیاس مخلوط** | `EPS × سرمایه` → نه مبلغ ریالی خالص |
| `NetProfitAmount` | مبلغ (واحد `U` نامعلوم، احتمالاً میلیون ریال) | سود خالص مبلغی |
| `OperatingProfitNew` | **نامعلوم / per-share یا مبلغ** | بسته به گزارش؛ view آن را تشخیص می‌دهد |
| `RevenueNew` | مبلغ (واحد `U`) | درآمد عملیاتی |
| `mahane.Value3` | مبلغ (واحد `U` نامعلوم) | فروش/درآمد یک‌ماهه |

### heuristicهای واحد (workaround)

1. **`detect_currency_unit` (py2):** فقط سه حالت میلیون/هزار/ریال؛ موارد نامعلوم به `million_rial` **حدس** زده می‌شوند.
2. **`vw_AIStockMetrics` — `OpK` / `OpAbs` / `OpAmt`:** تشخیص می‌دهد آیا سود عملیاتی per-share است یا مبلغی، با مقایسه‌ی magnitude:
   - `ABS(OpRaw) < 0.001 * ABS(NetProfitAmount)` و `< 0.001 * ABS(Revenue)` → per-share، ضریب `NetProfitAmount / EPS`.
   - در غیر این‌صورت `OpK = 1.0`.
   - `OpAmt = OpRaw * OpK` (هم‌واحد با Revenue/FinanceCosts/OtherNonOp/NetProfitAmount) با گارد «حداکثر ۳ برابر درآمد».
3. **`NPUnitRatio`:** ضریب توان-۱۰ بین `NetProfitAmount` (مبلغ) و `Product1` (per-share) که با `LOG10` و رُند کردن به نزدیک‌ترین توان ۱۰ محاسبه می‌شود (فقط اگر اختلاف < 0.1 مرتبه باشد، وگرنه 1.0).
4. **`TTMEPS`:** `SR_TTMNetProfit × LatestEPSReport / NetProfitAmount` یا `TTMNetProfit × LatestEPSReport / NetProfitCum` (بازگرداندن TTM مبلغی به مقیاس EPS).
5. **گاردهای ±۲۰۰٪ / ±۳۰۰٪:** روی نسبت‌های حاشیه‌ای (OperatingMargin/NetMargin/InterestCoverage/ROE) برای رد مقادیر ناشی از ناسازگاری واحد.

## unit normalization در `vw_AIStockMetrics` — کدام workaroundها فقط برای جبران schema/داده‌ی خام‌اند؟

- **`OpK`/`OpAbs`/`OpAmt` و `NPUnitRatio`:** کاملاً برای جبران دو چیز:
  (الف) `Product1 = EPS × سرمایه` با مقیاس مخلوط،
  (ب) نبود ستون واحد در `miandore2`/`mahane`.
  اگر ingestion واحد را استخراج و مقیاس را عادی‌سازی می‌کرد، این‌ها حذف می‌شدند.
- **`TTMEPS` با ضرب/تقسیم به EPS:** برای جبران نبود EPS مبلغی خالص و اختلاف مقیاس.
- **گاردهای نسبت:** برای جبران نوسان واحد و داده‌ی ناقص.
- **`OpAmt` (v3.7):** صریحاً برای رفع خطای ~۱۰۰۰ برابری در `InterestCoverage` و `NonOperatingPct` که ناشی از مخلوط واحد بود اضافه شده.

## نتیجه

واحدها در لایه‌ی SQL Server **استخراج نمی‌شوند**؛ همه‌ی heuristics به `vw_AIStockMetrics` منتقل شده‌اند. خط لوله‌ی `py2` کشف واحد را انجام می‌دهد ولی چون جدول جدا (Postgres) است، به `vw_AIStockMetrics` تغذیه نمی‌کند.

## `UNKNOWN`ها

- واحد واقعی `Value3` (`mahane`) و همه‌ی مبالغ `miandore2`.
- آیا `NetProfitAmount`/`RevenueNew` واقعاً «میلیون ریال» هستند (بر پایه‌ی فرض `U` در کامنت‌های view) یا واحد دیگری.
- واحد `BIGINT` قیمت‌ها در `MarketPriceHistory`.
