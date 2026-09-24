# Analytics Parity Issues

| # | severity | area | issue | classification | impact |
| --- | --- | --- | --- | --- | --- |
| 1 | HIGH | QuantScore | بازتولید کامل ۱۹ فاکتور v3.7 (rank/percentile/tie/NULL) انجام نشد؛ فقط زیرمجموعه‌ای reproduce شد | `LOGIC_DIFFERENCE` | QuantScore parity = 0% |
| 2 | HIGH | population | مرجع v3.7 = 276 ردیف؛ canonical shadow = 273; intersection = 273 | `POPULATION_DIFFERENCE` | rank/percentile قطعاً یکسان نیست |
| 3 | MEDIUM | TTMNetProfit | compat از `net_profit` canonical استفاده می‌کند؛ v3.7 از NetProfitAmount + NPUnitRatio + Product1 fallback | `LEGACY_UNIT_HEURISTIC` / canonical correction | parity پایین (16 exact از 273) |
| 4 | MEDIUM | SalesLast12M/Prev12M | windowing v3.7 (انتخاب بازه‌ی ۱۲ماهه‌ی تقویمی و فیلتر eligibility) با «۱۲ رکورد آخر» compat فرق دارد | `LOGIC_DIFFERENCE` | 83 exact |
| 5 | LOW | margins/ROE | اختلاف‌های اندک در margins/ROE عمدتاً از تعریف TTM و گردکردن | `FLOAT_PRECISION`/`ROUNDING` | بخش زیادی within tolerance |
| 6 | LOW | PEApprox | P/E compat از TTM EPS محاسبه‌شده؛ v3.7 از مسیر FullPE/EPS متفاوت | `LOGIC_DIFFERENCE` | 28 exact |

## UNKNOWN mismatches
هیچ mismatch با classification `UNKNOWN` ثبت نشد؛ همه deterministically به یکی از کلاس‌های بالا نگاشت شدند. با این حال چون `LOGIC_DIFFERENCE`/`POPULATION_DIFFERENCE` باقی است، gate نمی‌تواند PASS باشد.

## Gate impact
- canonical inputs: **PASS** (`FULL_UNIVERSE_INPUTS_PASS`)
- analytics parity: **FAIL** (full factor/QuantScore reproduction incomplete)
