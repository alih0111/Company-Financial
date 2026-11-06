# گزارش نهایی پژوهش بازده V12

شناسه: `v12_20261018T183000Z` · دادهٔ قیمت تا 2026-02-25 · تصمیم رتبه‌بندی تا 2026-02-24 · جامعهٔ ثابت 254 هویت.

| مسیر | نهایی از ۱۰۰م | بازده خالص | افت بیشینه | هزینه | خرید/فروش |
|---|---:|---:|---:|---:|---:|
| weight_only_24m | 204.65م | 104.65% | 30.82% | 22.64م | 553/431 |
| staged_weight_selected_policy | 278.44م | 178.44% | 39.19% | 17.70م | 122/59 |
| staged_weight_base_policy | 229.64م | 129.64% | 26.26% | 23.64م | 514/430 |
| baseline_exact_current | 228.44م | 128.44% | 30.52% | 23.95م | 565/434 |
| baseline_normalized | 228.44م | 128.44% | 30.52% | 23.95م | 565/434 |

## تفسیر نتیجه

مسیر اصلی `weight_only_24m` به 204.65م رسید؛ کنترل دقیق 228.44م بود، پس تفاوت -23.79م است. در این آزمون، وزن‌تنها بهتر نشد.
با وزن‌های staged یکسان، انتخاب سیاست در شش ماه آخر نسبت به سیاست پایه 48.80م اختلاف داشت (278.44م در برابر 229.64م). مسیرهای staged آزمایش ثانویه‌اند؛ از برتری بیرونی آن‌ها برندهٔ مستقل نمی‌سازیم.
علت قابل‌اندازه‌گیری افت V11 از مسیر وزن منتخب با سیاست پایه (234.14م) به V11 کامل (112.31م) انتخاب/تعامل سیاست‌های N، cadence و بستهٔ خروج/تخصیص است؛ اختلاف 121.83م. فاکتوریل ۸حالته در `v11_policy_ablation.csv` نشان می‌دهد حالت تماماً پایه ۲۳۴٫۱۴م، تماماً منتخب ۱۱۲٫۳۱م و ترکیب سیاست پایهٔ N با cadence و بستهٔ منتخب ۲۸۲٫۸۱م شد. برهم‌کنش‌ها اجازهٔ نسبت‌دادن سهم علّی یکتا به یک پارامتر را نمی‌دهند.

## وزن‌ها و سیاست‌های انتخاب‌شده

| بلوک | وزن‌های غیرصفر | سیاست بیرونی staged |
|---:|---|---|
| 0 | sales_growth_12m 11.8, sales_growth_3m 7.1, revenue_growth 5.9, operating_profit_growth 5.9, net_profit_growth 11.8, operating_margin 4.7, net_margin 4.7, roe 7.1, margin_trend 3.5, interest_coverage 3.5, cash_conversion 2.4, earnings_quality 4.7, pe 12.9, ps 3.5, pb 2.4, sales_stability 1.2, leverage 1.2, current_ratio 2.4, volatility_30d 2.4, price_momentum_30d 1.2 | N=3, cadence=21, exit=1, equal |
| 1 | sales_growth_12m 12.5, sales_growth_3m 7.5, revenue_growth 6.2, operating_profit_growth 6.2, net_profit_growth 12.5, operating_margin 5.0, net_margin 5.0, margin_trend 3.8, interest_coverage 3.8, cash_conversion 2.5, earnings_quality 5.0, pe 13.8, ps 3.8, pb 2.5, sales_stability 1.2, leverage 2.5, current_ratio 2.5, volatility_30d 2.5, price_momentum_30d 1.2 | N=1, cadence=10, exit=1, equal |
| 2 | sales_growth_12m 10.9, sales_growth_3m 13.0, revenue_growth 5.4, operating_profit_growth 5.4, net_profit_growth 10.9, operating_margin 4.3, net_margin 4.3, roe 6.5, margin_trend 3.3, interest_coverage 3.3, cash_conversion 2.2, earnings_quality 4.3, pe 12.0, ps 3.3, pb 2.2, sales_stability 1.1, leverage 2.2, current_ratio 2.2, volatility_30d 2.2, price_momentum_30d 1.1 | N=1, cadence=21, exit=1, equal |
| 3 | sales_growth_12m 13.3, sales_growth_3m 8.0, revenue_growth 6.7, operating_profit_growth 6.7, net_profit_growth 13.3, operating_margin 5.3, net_margin 5.3, roe 8.0, margin_trend 4.0, interest_coverage 4.0, cash_conversion 2.7, earnings_quality 5.3, ps 4.0, pb 2.7, sales_stability 1.3, leverage 2.7, current_ratio 2.7, volatility_30d 2.7, price_momentum_30d 1.3 | N=1, cadence=10, exit=2, equal |
| 4 | sales_growth_12m 13.3, sales_growth_3m 8.0, revenue_growth 6.7, operating_profit_growth 6.7, net_profit_growth 13.3, operating_margin 5.3, net_margin 5.3, roe 8.0, margin_trend 4.0, interest_coverage 4.0, cash_conversion 2.7, earnings_quality 5.3, ps 4.0, pb 2.7, sales_stability 1.3, leverage 2.7, current_ratio 2.7, volatility_30d 2.7, price_momentum_30d 1.3 | N=10, cadence=21, exit=2, equal |
| 5 | sales_growth_12m 13.3, sales_growth_3m 8.0, revenue_growth 6.7, operating_profit_growth 6.7, net_profit_growth 13.3, operating_margin 5.3, net_margin 5.3, roe 8.0, margin_trend 4.0, interest_coverage 4.0, cash_conversion 2.7, earnings_quality 5.3, ps 4.0, pb 2.7, sales_stability 1.3, leverage 2.7, current_ratio 2.7, volatility_30d 2.7, price_momentum_30d 1.3 | N=10, cadence=63, exit=1, equal |

تعداد نامزدهای وزن 93 (حد ثبت‌شده ۹۳)، ۵۵۸ ارزیابی weight-only و ۵۵۸ ارزیابی وزن ۱۸ماهه انجام شد؛ ۱۰۸ سیاست شش‌ماهه همگی موفق بودند. خطای ارزیابی صفر است. رجیستری فقط پایه، تغییر تک‌عامل در (0, 0.5, 1.5, 2) و تغییر چهار گروه را داشت.

## رتبه‌بندی، missing و موقعیت‌ها

تحلیل برندگان فقط روی شبکهٔ مشترک هر ۲۱ جلسه و افق‌های ۶۳/۱۲۶ جلسه است؛ برچسب ناقص حذف شد. خروجی `winner_capture_summary.csv` precision@10 و precision@N را جدا می‌دهد. این برچسب‌های آینده فقط تشخیصی‌اند. همبستگی‌های عامل در `factor_diagnostics.csv` به تفکیک observed/missing هستند و در انتخاب دخالت نکردند.
پوشش هر عامل/جلسه و مقدار خام در `factor_coverage.csv` ثبت شد؛ ۱۲ نمونهٔ seed=20261018 از ledger رویداد محلی (۶ observed و ۶ missing) در `missing_source_audit.csv` ردیابی شد. این نمونه‌گیری منبع محلی را نشان می‌دهد، نه اینکه هر missing را به فقدان واقعی اطلاعات نسبت دهد. سیاست defaults، clipping، penalty و DQ ثابت ماند.
در گزارش V11 شمار ۱۳ برای N=10 از سه ماندهٔ شناور زیر یک تومان می‌آمد؛ پس از حذف dust، شمار اقتصادی ۱۰ است. `n` تعداد هدف انتخاب است، نه سقف سخت روی ماندهٔ عددی.
نمادهای با بیشترین سهم مثبت بازار در مسیر وزن‌تنها: سصوفی, ساربیل, ساروم, سپیدار, دارو. سهم‌ها از دفتر روزانه و موجودی انتقال‌یافته محاسبه شده‌اند؛ جدول کامل در `symbol_attribution.csv`.

## کنترل و محدودیت

اعتبارسنجی: PASS؛ تطبیق ۱۲ نمونهٔ دفتر کند، بازسازی NAV روزانه، هزینه، انتساب تصمیم/اجرا، پیوستگی attribution و هش V8–V11 در `validation_results.json`. مهرها: {"v8": 0, "v9": 0, "v10": 0, "v11": 0} اختلاف.
پایهٔ سرمایه ۱۰۰م، کارمزد هر سمت ۰٫۵٪، اجرای جلسهٔ بعد در اولین open معتبر، full fill بدون اثر بازار، بدون اهرم/short. قیمت تعدیل‌شده اثبات‌کنندهٔ total return شامل تمام سود نقدی و حق‌تقدم نیست. افت سرمایه و تمرکز فقط گزارش شدند. بازهٔ داده بارها دیده شده و holdout مستقل نیست؛ هیچ غربال پیش‌فرض یا رتبه‌بندی زنده تغییر نکرد.
جست‌وجو محدود و از پیش ثبت‌شده بود؛ معیار پس از دیدن نتایج عوض نشد. کاسپین هدف یا شرط موفقیت نبود. سفارش واقعی ارسال نشد. کامپوننت V12 و snapshot آماده‌اند؛ mount رابط به‌علت مهر `App.tsx` در V11 انجام نشد.
جزئیات و فایل‌های بازتولید: `ranking_research/output/return_v12/v12_20261018T183000Z/`.
