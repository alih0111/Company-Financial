# 03 — معنای واقعی `dbo.miandore2`

> مبنا: trace مستقیم `py/MianSql.py` (تابع `extract_profit_loss_values`, `extract_balance_sheet_values`, `extract_cashflow_values`, `save_profit_loss_to_sql`) و wrapper `py/scraper.py` / `py/codal_processor.py`.
> هر جا قطعی نیست `UNKNOWN` نوشته شده است.

## Writerها

| مسیر | فایل | تابع |
| --- | --- | --- |
| Go `run-script` / `full_run_scripts` (`table="miandore2"`) | `py/scraper.py` → `MianSql.main_scraper(..., "miandore2")` | `scrape_report` → `save_profit_loss_to_sql` |
| Discovery sync (LetterType=6) | `py/sync_codal.py` → `py/codal_processor.py::_process_financial` | `MianSql.scrape_report(..., table_name="miandore2")` |

`MianSql.ensure_table` ستون‌های پایه را می‌سازد و بقیه را به‌صورت idempotent با `ALTER TABLE ... ADD` اضافه می‌کند. پس schema این جدول از داخل همین اسکریپت مدیریت می‌شود.

## دوره‌ها (`Value1/2/3`)

`get_period_columns(table)` تا **سه** ستون دوره‌ی قابل مشاهده را برمی‌گرداند (ستون «شرح» و «درصد تغییر» حذف می‌شوند). از روی کامنت‌های parser:

- `Value1` = **دوره‌ی جاری** (current period)
- `Value2` = **دوره‌ی مقایسه‌ای سال قبلِ همان دوره** (prior-year same period)
- `Value3` = **کل سال مالی قبل** (FYPrev / «سکل سال قبل» در کامنت)

> `Value3` فقط برای ردیف‌های سود خالص / سود عملیاتی / درآمد / جریان نقدی خوانده می‌شود و برای EPS/سرمایه عملاً هم درج می‌شود اما معنای FYPrev قطعی نیست → برای `Num1_Value3/Num2_Value3/Num4_Value3/Product3` **UNKNOWN/کم‌استفاده**.

## ستون‌های per-share و سرمایه (بلوک Num/Product)

منبع ردیف‌ها: `net_eps_row` (سود/زیان خالص هر سهم – ریال)، `capital_row` (سرمایه)، `operating_eps_row` (عملیاتی – ریال).

| ستون | معنی business | statement | واحد | مقیاس | دوره | raw/derived |
| --- | --- | --- | --- | --- | --- | --- |
| `Num1_Value1` | سود (زیان) خالص هر سهم | سود و زیان | ریال/سهم | per-share | جاری | raw |
| `Num2_Value1` | سرمایه | ترازنامه/سود و زیان | **UNKNOWN** (مبلغ) | — | جاری | raw |
| `Num4_Value1` | سود (زیان) عملیاتی هر سهم | سود و زیان | ریال/سهم | per-share | جاری | raw |
| `Product1` | `Num1_Value1 × Num2_Value1` | سود و زیان | **مقیاس مخلوط** (per-share × سرمایه) | — | جاری | **derived** |
| `Num1_Value2` | سود خالص هر سهم | سود و زیان | ریال/سهم | per-share | سال قبل همان دوره | raw |
| `Num2_Value2` | سرمایه | — | **UNKNOWN** | — | سال قبل همان دوره | raw |
| `Num4_Value2` | سود عملیاتی هر سهم | — | ریال/سهم | per-share | سال قبل همان دوره | raw |
| `Product2` | `Num1_Value2 × Num2_Value2` | — | مقیاس مخلوط | — | سال قبل همان دوره | derived |
| `Num1_Value3` | سود خالص هر سهم | — | ریال/سهم | per-share | FYPrev (کم‌استفاده) | raw |
| `Num2_Value3` | سرمایه | — | UNKNOWN | — | FYPrev | raw |
| `Num4_Value3` | سود عملیاتی هر سهم | — | ریال/سهم | — | FYPrev | raw |
| `Product3` | `Num1_Value3 × Num2_Value3` | — | مقیاس مخلوط | — | FYPrev | derived |

> **نکته‌ی کلیدی:** `Product*` = EPS × سرمایه است، یعنی **مقیاس مخلوط** (نه سود خالص ریالی خالص). دلیل وجود guardهای واحد در `vw_AIStockMetrics` همین است.

## ستون‌های مبلغی/سود

| ستون | معنی business | statement | ردیف منبع (Title) | واحد | مقیاس | دوره | raw/derived |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `OperatingProfitNew` | سود (زیان) عملیاتی | سود و زیان | «سود (زیان) عملیاتی» (بدون هر سهم/قبل از مالیات/غیرعملیاتی) | **UNKNOWN** | — | جاری | raw |
| `OperatingProfitLastYear` | سود (زیان) عملیاتی | سود و زیان | همان ردیف | UNKNOWN | — | سال قبل همان دوره | raw |
| `FinanceCostsNew` | هزینه(های) مالی | سود و زیان | «هزینه مالی» | UNKNOWN | — | جاری | raw |
| `FinanceCostsLastYear` | هزینه(های) مالی | — | همان | UNKNOWN | — | سال قبل | raw |
| `OtherNonOpNew` | سایر درآمدها و هزینه‌های غیرعملیاتی (+ سود فروش دارایی زیستی مولد) | سود و زیان | «سایر درآمدها و هزینه‌های غیرعملیاتی» + «سود (زیان) فروش دارایی زیستی مولد» | UNKNOWN | — | جاری | **raw + derived (جمع)** |
| `OtherNonOpLastYear` | همان | — | همان | UNKNOWN | — | سال قبل | raw + derived |
| `RevenueNew` | درآمدهای عملیاتی | سود و زیان | «درآمدهای عملیاتی» | UNKNOWN | — | جاری | raw |
| `RevenueLastYear` | درآمدهای عملیاتی | — | همان | UNKNOWN | — | سال قبل | raw |
| `NetProfitAmount` | سود (زیان) خالص (مبلغی) | سود و زیان | «سود (زیان) خالص» (بدون هر سهم/عملیات/جامع/پایه) | UNKNOWN | — | جاری | raw |
| `NetProfitAmountLY` | سود خالص | — | همان | UNKNOWN | — | سال قبل همان دوره | raw |
| `NetProfitAmountFYPrev` | سود خالص | — | همان | UNKNOWN | — | پایان سال مالی قبل | raw |
| `OperatingProfitFYPrev` | سود عملیاتی | — | «سود (زیان) عملیاتی» | UNKNOWN | — | پایان سال قبل | raw |
| `RevenueFYPrev` | درآمد عملیاتی | — | «درآمدهای عملیاتی» | UNKNOWN | — | پایان سال قبل | raw |

## ستون‌های ترازنامه (`extract_balance_sheet_values`)

منبع: صفحه‌ی «صورت وضعیت مالی» از همان گزارش (selectbox)، ستون اول = **پایان دوره‌ی جاری**، ستون دوم = **پایان دوره/سال قبل**.

| ستون | معنی | ردیف منبع | واحد | current/compare |
| --- | --- | --- | --- | --- |
| `TotalAssets` / `TotalAssetsLY` | جمع دارایی‌ها | «جمع دارایی‌ها» | UNKNOWN | current / prior |
| `CurrentAssets` / `CurrentAssetsLY` | جمع دارایی جاری | contains «جمع دارایی جاری» | UNKNOWN | current / prior |
| `TotalLiabilities` / `TotalLiabilitiesLY` | جمع بدهی‌ها | «جمع بدهی‌ها» | UNKNOWN | current / prior |
| `CurrentLiabilities` / `CurrentLiabilitiesLY` | جمع بدهی جاری | contains «جمع بدهی جاری» | UNKNOWN | current / prior |
| `TotalEquity` / `TotalEquityLY` | جمع حقوق مالکانه | contains «جمع حقوق مالکانه» | UNKNOWN | current / prior |

## ستون‌های جریان نقدی (`extract_cashflow_values`)

منبع: «صورت جریان‌های نقدی»، ردیف «خالص جریان‌های نقدی عملیاتی». کامنت parser: **تجمعی از ابتدای سال** (مثل سود).

| ستون | معنی | دوره | raw/derived |
| --- | --- | --- | --- |
| `OperatingCashFlow` | خالص جریان نقدی عملیاتی | جاری | raw |
| `OperatingCashFlowLY` | همان | سال قبل همان دوره | raw |
| `OperatingCashFlowFYPrev` | همان | پایان سال قبل | raw |

## نکات مهم

1. **مخلوط چند صورت مالی در یک جدول:** `miandore2` هم‌زمان سود و زیان (per-share + مبلغی)، ترازنامه، و جریان نقدی را در یک ردیف کلی می‌ریزد. `statement type` در ستون‌ها کد نشده است.
2. **بدون کشف واحد:** `MianSql.py` برخلاف `py2` تابع `detect_currency_unit` ندارد (بررسی شد؛ تنها py2 آن را دارد). پس واحد مقادیر مبلغی **UNKNOWN** است.
3. **`Product*` مقیاس مخلوط:** `EPS × سرمایه`؛ تنها ستون «مبلغی واقعی» برای سود، `NetProfitAmount` است.
4. **آپدیت جزئی:** اگر رکورد موجود باشد، فقط ستون‌های مبلغی/ترازنامه‌ای با `COALESCE(col, ?)` پر می‌شوند (یعنی قدیمی‌ترها بازنویسی نمی‌شوند) و `Num*/Product*` هرگز به‌روزرسانی نمی‌شوند.

## `UNKNOWN`ها

- واحد/مقیاس همه‌ی مبالغ (`capital`, `OperatingProfitNew`, `RevenueNew`, `NetProfitAmount`, ترازنامه، جریان نقدی) — parser استخراج نمی‌کند.
- معنای قطعی `Value3` برای `Num1_Value3/Num2_Value3/Num4_Value3/Product3` (کامنت فقط «سکل سال قبل» دارد).
