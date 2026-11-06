# ممیزی ورودی بازده V2

اجرا: `D:\RFA\Company-Financial\ranking_research\output\return_v2\v2_20261015T185724180015Z`. ۲۴ نمونه با seed ثابت؛ ۱۲ برندهٔ قدیمی و ۱۲ کنترل میانی/منفی.

قیمت۱۰۰۰ با حجم/ارزش و OHLC صفر پیش از اولین معامله، قیمت قابل‌سرمایه‌گذاری نیست. قاعدهٔ جدید فقط مشاهدات معامله‌شدهٔ موجود در تاریخ endpoint را می‌پذیرد؛ نماد یا بازده بزرگ حذف نشده است. بازده69.45 نسبت است و حدود6945٪؛ این نمونه‌ها با مخرج پیش‌معامله معتبر نیستند.

| symbol | sample | decision_time | left_raw_price_rial | first_observed_trade | legacy_adjusted_return | validated_adjusted_return | status |
|---|---|---|---|---|---|---|---|
| غمایه | original_top12 | 2023-03-29 | 1,000.0000 | 2023-07-12 | 69.4523 | nan | invalid_pretrade_endpoint |
| آردینه | original_top12 | 2024-01-31 | 1,000.0000 | 2024-02-14 | 65.0594 | nan | invalid_pretrade_endpoint |
| دزاگرس | original_top12 | 2024-11-30 | 1,000.0000 | 2024-12-23 | 39.6500 | nan | invalid_pretrade_endpoint |
| عالیس | original_top12 | 2023-03-29 | 1,000.0000 | 2023-05-27 | 28.8469 | nan | invalid_pretrade_endpoint |
| بیوتیک | original_top12 | 2023-09-30 | 1,000.0000 | 2024-02-07 | 24.7500 | nan | invalid_pretrade_endpoint |
| ددانا | original_top12 | 2022-03-30 | 1,000.0000 | 2022-05-16 | 22.7500 | nan | invalid_pretrade_endpoint |
| کربن | original_top12 | 2024-06-30 | 1,000.0000 | 2024-12-04 | 18.5500 | nan | invalid_pretrade_endpoint |
| زفجر | original_top12 | 2023-04-30 | 1,000.0000 | 2023-05-20 | 18.4790 | nan | invalid_pretrade_endpoint |
| سآبیک | original_top12 | 2022-03-30 | 1,000.0000 | 2022-05-18 | 11.2985 | nan | invalid_pretrade_endpoint |
| کماسه | original_top12 | 2022-10-31 | 2,551.0000 | 2001-03-26 | 3.8883 | 3.8883 | valid_traded_endpoints_economic_uncertainty |
| شمس | original_top12 | 2024-11-30 | 1,000.0000 | 2025-01-22 | 3.7351 | nan | invalid_pretrade_endpoint |
| سپیدار | original_top12 | 2022-12-31 | 24,350.0000 | 2021-01-06 | 3.1609 | 3.1609 | valid_traded_endpoints_economic_uncertainty |
| بوعلی | middle_control | 2023-03-29 | 54,890.0000 | 2020-12-09 | 0.0479 | 0.0479 | valid_traded_endpoints_economic_uncertainty |
| کسرا | middle_control | 2022-07-31 | 6,610.0000 | 2004-07-03 | -0.0726 | -0.0726 | valid_traded_endpoints_economic_uncertainty |
| حفاری | middle_control | 2024-03-30 | 7,580.0000 | 2009-07-22 | 0.1147 | 0.1147 | valid_traded_endpoints_economic_uncertainty |
| شبصیر | middle_control | 2025-05-31 | 13,680.0000 | 2018-11-06 | -0.0760 | -0.0760 | valid_traded_endpoints_economic_uncertainty |
| سفانو | middle_control | 2024-12-31 | 30,440.0000 | 2009-10-21 | 0.1192 | 0.1192 | valid_traded_endpoints_economic_uncertainty |
| نوری | middle_control | 2023-11-29 | 147,580.0000 | 2019-07-13 | 0.2403 | 0.2403 | valid_traded_endpoints_economic_uncertainty |
| غشصفا | negative_control | 2024-02-28 | 14,130.0000 | 2003-06-15 | -0.2200 | -0.2200 | valid_traded_endpoints_economic_uncertainty |
| توریل | negative_control | 2025-01-29 | 6,200.0000 | 2012-04-24 | -0.4831 | -0.4831 | valid_traded_endpoints_economic_uncertainty |
| کرازی | negative_control | 2023-10-31 | 1,576.0000 | 2005-05-14 | -0.0805 | -0.0805 | valid_traded_endpoints_economic_uncertainty |
| سنیر | negative_control | 2024-02-28 | 59,320.0000 | 2007-11-27 | -0.3338 | -0.3338 | valid_traded_endpoints_economic_uncertainty |
| فبیرا | negative_control | 2025-01-29 | 1,623.0000 | 2013-11-30 | -0.1442 | -0.1442 | valid_traded_endpoints_economic_uncertainty |
| فولاد | negative_control | 2025-05-31 | 3,839.0000 | 2007-03-11 | -0.0844 | -0.0844 | valid_traded_endpoints_economic_uncertainty |

کنترل متوازن و کیفیت P3 دقیقاً با اختلاف کمتر از۰٫۰۱ تومان بازتولید شدند. اثر ویژگی و PnL واقعی هر نماد در anomaly_portfolio_impact.csv است. شناسه/alias تاریخی و تسویهٔ نقدی/حق‌تقدم کامل نیست؛ ضریب تعدیل را سهم/وجه نقد فرض نکردیم. بازده اقتصادی مستقل در نبود سند نامعلوم باقی ماند. تمام رکوردهای رویداد و زنجیرهٔ ضریب ذخیره شده‌اند.


## تکمیل ممیزی قرارداد قیمت معامله‌شده — ۲۰۲۶/۱۰/۱۶

ردیف روزانهٔ بدون معامله نباید تاریخ قیمت تازه بسازد. ممیزی نخستِ چهار سناریوی رویدادهای نامعلوم به‌اشتباه ضرایب آن سناریو را با ضرایب عادی مقایسه کرده بود؛ ارقام بزرگ آن مقایسه معتبر نیستند. ممیزی جایگزین، ضرایب را یکسان می‌گیرد؛ اختلاف‌های زیر تغییر فرضی NAV روی تعداد واحد ثابتِ مسیر قبلی‌اند، نه اثر نهایی بازاجرای راهبرد.

| experiment_id | maximum_daily_nav_mark_difference_toman | terminal_nav_mark_difference_toman |
|---|---|---|
| stress_two_of_three_unknown_events_raw_price_assumption | 29,824,505.3687 | 8,007,312.1914 |
| stress_existing_choose_unknown_events_raw_price_assumption | 29,824,505.3687 | 8,007,312.1914 |
| stress_nested_holding_unknown_events_raw_price_assumption | 5,307,382.2446 | 0.0000 |
| stress_balanced_control_unknown_events_raw_price_assumption | 3,557,799.3328 | 311,288.6420 |
| equal_weight_all | 1,303,927.5491 | -0.0180 |

همهٔ مسیرها با قرارداد معاملهٔ واقعی بازاجرا شدند؛ اثر نهایی با بازتوازن و هزینه در mark_correction_effect.csv است. ممیزی مستقلِ 141 مسیر اصلاح‌شده تطبیق ارزش و تاریخ معامله را تأیید کرد؛ چهار مسیر legacy عمداً قرارداد قدیمی دارند. قیمت بیش از۷روز کهنه از سن و کران علامت‌گذاری حذف نشده است؛ شواهد: `ranking_research\output\return_v2\v2_20261016T080341078036Z\execution_quality_v2`. دفتر نقد/حق‌تقدم و فروش در بازار بسته همچنان تأیید نشده‌اند.
