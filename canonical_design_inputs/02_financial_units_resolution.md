# 02 — Financial Unit / Scale Resolution

> فقط investigation. هیچ داده‌ای تغییر نکرد. مبنا: parserها + داده‌ی واقعی SQL Server (`_units_price_facts.json`, `_investigation_facts.json`).
> کلاس‌ها: **KNOWN** | **INFERABLE_FROM_SOURCE** | **HEURISTIC_ONLY** | **UNKNOWN**

## Monthly activity (`mahane`)

| ستون | معنی | واحد | کلاس |
| --- | --- | --- | --- |
| `Value1` | تعداد تولید یک‌ماهه | quantity (عدد/تن/…) — parser استخراج نمی‌کند | **UNKNOWN** |
| `Value2` | تعداد فروش یک‌ماهه | quantity — استخراج نمی‌کند | **UNKNOWN** |
| `Value3` | مبلغ فروش/درآمد یک‌ماهه | **میلیون ریال** | **INFERABLE_FROM_SOURCE** (HIGH) |

یافته‌های داده:
- `Value1<>0` در ۹٬۳۰۲ ردیف، `Value2<>0` در ۹٬۳۰۲، `Value3<>0` در ۱۲٬۰۵۳.
- نمونه: `خراسان 1405/02/31` → V1=22,554,921 / V2=23,093,328 / V3=11,845,690 (مقدار فیزیکی بزرگ و مبلغ ماهانه).
- مقایسه‌ی مقیاس با `miandore2.RevenueNew` همان شرکت‌ها هم‌مرتبه است → `Value3` میلیون ریال.

**منبع واحد در کدال:** هدر گزارش‌های کدال معمولاً «(مبلغ به میلیون ریال)» را دارد؛ `py2.detect_currency_unit` همین را می‌خواند
(`million_rial` / `thousand_rial` / `rial`). **parser قدیمی `MianSql2.py` این هدر را نمی‌خواند** → واحد از دست می‌رود.
یعنی واحد **قابل استخراج از منبع** است، نه صرفاً heuristic.

## Financial statements (`miandore2`)

### EPS (per-share) — KNOWN
`Num1_Value*` (سود خالص هر سهم) و `Num4_Value*` (سود عملیاتی هر سهم) از ردیف‌هایی می‌آیند که عنوانشان «… هر سهم - ریال» است → **ریال بر سهم**. (`py2` هم `unit_code='rial_per_share'` می‌گذارد.)

### مقادیر مبلغی — INFERABLE_FROM_SOURCE (HIGH)
اثبات عددی که واحد = **میلیون ریال** است:

```
shares           = NetProfitAmount(million) × 1e6 / EPS(rial)
Capital(rial)    = shares × 1000        (ارزش اسمی = 1000 ریال)
Capital_stored   = Capital(rial) / 1e6  = Capital به میلیون ریال
⇒ Product1 = EPS × Capital_stored = NetProfitAmount(million) × 1000
```

شاهد تجربی: توزیع `LOG10(NetProfitAmount / Product1)`:
`bucket -3.0 → 360 ردیف`، `-2.0 → 6`، `-6.0 → 1` → یعنی برای ~۹۸٪ رکوردها `Product1 ≈ 1000 × NetProfitAmount`. ✅

جدول cross-check (۱۲ شرکت از صنایع مختلف، آخرین گزارش):

| شرکت | تاریخ | EPS(ریال/سهم) | Capital | Product1 | NetProfitAmount | RevenueNew | TotalAssets | log10(NP/P1) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| آردینه | 1405/03/31 | 1493 | 2,000,000 | 2.986e9 | 2,986,850 | 6,235,493 | 19,147,792 | -3.0 |
| ارفع | 1405/03/31 | 1216 | 32,000,000 | 3.8912e10 | 38,899,526 | 140,547,858 | 286,834,358 | -3.0 |
| اروند | 1405/03/31 | 505 | 12,000,000 | 6.06e9 | 6,063,966 | 43,998,765 | 328,922,592 | -3.0 |
| اسیاتک | 1405/03/31 | 486 | 11,500,000 | 5.589e9 | 5,584,765 | 10,360,028 | 80,746,195 | -3.0 |
| افق | 1405/03/31 | 1339 | 30,000,000 | 4.017e10 | 40,175,980 | 872,495,896 | 927,626,685 | -3.0 |
| انرژی | 1405/03/31 | 224 | 4,050,000 | 9.072e8 | 908,342 | 989,395 | 7,777,978 | -2.999 |
| بترانس | 1405/04/31 | 119 | 1,200,000 | 1.428e8 | 142,882 | 216,011 | 2,762,476 | -3.0 |
| بجهرم | 1405/03/31 | 102 | 36,545,332 | 3.7276e9 | 3,718,949 | 7,228,876 | 65,919,690 | -3.001 |
| آریا | 1405/03/31 | 350 | 34,378,800 | 1.2033e10 | (NULL) | (NULL) | (NULL) | — |

همه‌ی ستون‌های مبلغی (`Capital`, `NetProfitAmount`, `RevenueNew`, `OperatingProfitNew`, `FinanceCostsNew`,
`TotalAssets`, `TotalLiabilities`, `TotalEquity`, `OperatingCashFlow`, و `Num2`) → **میلیون ریال**.

### Product1 — derived با مقیاس مخلوط
`Product1 = Num1_Value1 × Num2_Value1`. از نظر dimension: «ریال/سهم × میلیون‌ریال» = بی‌معنا؛ عددی که می‌دهد
≈ ۱۰۰۰ × سود خالص (میلیون ریال) فقط وقتی ارزش اسمی ۱۰۰۰ ریال باشد. این منبع اصلی نیاز به `NPUnitRatio` در `vw_AIStockMetrics` است.

## EPS / سرمایه / علت اختلاف ×1000
- **EPS:** ذاتاً per-share (ریال/سهم). — KNOWN
- **`Num2` (سرمایه):** میلیون ریال. — INFERABLE
- **`Product1`:** `EPS × Capital` → مقیاس مخلوط؛ عددی ~۱۰۰۰× سود خالص. — derived
- **علت ×1000:** چون `Capital` میلیون ریال ولی `EPS` ریال است و ارزش اسمی ۱۰۰۰ ریال → `EPS×Capital = NP×1e3`.

## `statements` table
- `UnitCode` برای **همه‌ی** ۵٬۹۲۰ ردیف = `'unknown'`.
- `StatementType` ∈ {`balance_sheet`, `cash_flow`, `comprehensive_income`, `equity_changes`}.
- `PeriodHeader` شامل «حسابرسی شده/نشده» و «تجدید ارائه شده به تاریخ …» است.
- `MetricCode` الگوی `balance_sheet.m_<hash>.1` دارد؛ `RowTitle` عنوان خط فارسی است.
- فقط برای **۱ شرکت (`کالا`)** داده دارد → pilot/external؛ writer ناشناس.
- کلاس واحد: **UNKNOWN** (ستون واحد دارد ولی پر نشده).

## آیا واحد در خود گزارش Codal موجود است؟
- **بله** — در هدر جدول به‌صورت «میلیون ریال/هزار ریال/ریال». تأیید از طریق `py2.detect_currency_unit`.
- parserهای قدیمی (`MianSql.py`, `MianSql2.py`) آن را نادیده می‌گیرند → واحد باید در ingestion استخراج و نرمال شود.

## خلاصه‌ی classification

| Metric | Class |
| --- | --- |
| `mahane.Value3`, `miandore2` monetary (Capital/NP/Revenue/OP/Finance/Assets/Equity/CF) | **INFERABLE_FROM_SOURCE** (million rial) |
| `miandore2` EPS fields (`Num1_*`, `Num4_*`) | **KNOWN** (rial/share) |
| `miandore2.Product*` | derived mixed-scale (نه یک واحد) |
| `mahane.Value1/Value2` (quantities) | **UNKNOWN** (unit not captured) |
| `statements.*` | **UNKNOWN** (`UnitCode='unknown'`) |
| `MarketPriceHistory` price/Volume/TradeValue | KNOWN/INFERABLE = rial (بخش ۰۳) |

## نتیجه برای طراحی
واحد به‌صورت یک ستون `unit`/`scale` در ingestion قابل استخراج است؛ در Postgres باید هر مقدار مبلغی با یک واحد canonical (پیشنهاد: **ریال**، `numeric`) و یک ستون `reported_unit` ذخیره شود. با این کار `NPUnitRatio`/`OpK`/`Product1` از analytics حذف می‌شوند.
