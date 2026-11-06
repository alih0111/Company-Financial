# نتیجهٔ V6

اجرا: `D:\RFA\Company-Financial\ranking_research\output\return_v6\v6_20261016T144712827439Z`

S2 حفظ شد؛ نامزدها خودکار به روش پذیرفته‌شده ارتقا نیافتند. اعداد، NAV شاخصی پژوهشی با سرمایهٔ آغاز ۱۰۰ میلیون تومان، هزینهٔ ۰٫۵٪ هر سمت، تقویم استنباطی و همان قرارداد قیمت V5 هستند. بازده اقتصادی کامل نامعلوم است؛ حساب واقعی نداریم.

## یافتهٔ تازه دربارهٔ به‌موقع‌بودن

ردیابی واقعی نشان داد V5 از V4 ← V3 ← V2.events.panel_asof با join عقب‌نگر رویداد انتشار مصرف می‌کند. فایل قدیمی asof_panel تأخیر ماهانه دارد، اما این تأخیر در مسیر واقعی V5 نیست. publication_path_proof.csv تطابق منابع و S2 را سطر به سطر کنترل می‌کند. D0 و D2 ورودی یکسان دارند و خروجی موجود بازاستفاده شده؛ D1 یک خلاف‌واقعِ صریح با تأخیر ماهانه است و افت یا رشد آن اصلاح V5 محسوب نمی‌شود. publication_to_decision_lag.csv نشان می‌دهد کدام اسناد را این خلاف‌واقع نمی‌بیند. بنیاد با زمان انتشار دقیق تا پایان روز تصمیم مجاز است، سفارش از جلسهٔ بعد؛ روزِ بدون ساعت از جلسهٔ بعد مجاز است.

## بازیابی تاریخ و جامعه

صفِ 21 سند دارای انتشار/دورهٔ مشخص بر مبنای سقف تصمیم‌های مسدودشده و اتصال سند ساخته شد؛ این شمار سقف اولویت‌بندی است، نه تضمین رفع همهٔ تصمیم‌ها با یک سند. کاتالوگ و validation محلی V4 بازبینی و مسیر مستقیمِ سند دقیق با checkpoint محدود امتحان شد؛ گزارش تاریخی تازهٔ قابل‌پذیرش صفر بود. ۲۲۵ گزارش افزودهٔ V4 از ژوئیهٔ ۲۰۲۶ به بعدند و وارد دورهٔ اصلی نشدند. شرایط اعتبار شل نشد. پوشش قبل/بعد برای همهٔ موعدهای آموزشی و تصمیم، سطل‌های <=۱۰ / ۱۱..۱۹ / >=۲۰ و علل حذف در historical_coverage_before_after.csv ثبت شده است؛ جامعهٔ محلی ۲۵۴ هویت است، نه کل بازارِ بدون سوگیری بقا.

## مدل محدود

سه ویژگی ثابت: S2 مستقل، سود عملیاتی TTM/دارایی مثبت همان منبع، momentum12_1 موجود. ridge با alpha=۱ و تابع میانگین خطای وزن‌دار + مجموع مربع ضرایب، عرض از مبدأ بدون جریمه. هر ماه وزن برابر؛ حداقل۲۴تاریخ بالغ با۲۰برچسب معتبر، حداکثر۳۶ماه گذشته، سررسید برچسب۶۰جلسه‌ای قبل از cutoff. در 3 بلوک آموزش و در 0 بلوک fallback ازپیش‌ثبت‌شدهٔ S2 هم‌جامعه رخ داد. این تاریخ قبلاً مصرف شده و برچسب‌ها هم‌پوشان‌اند. ضرایب بدون تغییر علامت پسینی در model_coefficients.csv موجودند.

## مقایسهٔ ۱۰۰ میلیون

بازهٔ نمایش 2024-11-02 تا 2026-02-25؛ تصمیم اولیه2024-10-30. NAV کامل مسیرهای تازه، نخستین fill، هزینهٔ پیش از نمایش و سرمایهٔ آغاز جدا ثبت‌اند. دارایی و نقد در مرز بلوک ریست نمی‌شوند. مراجع رشد سود/وزن مساوی cadence ماهانهٔ قبلی دارند و فقط مرجع زمینه‌اند؛ S2/کنترل/مدل همگی دوهفته‌ای با حداکثر۱۰عضو و وزن برابرند. مرجع وزن مساوی همهٔ واجدان می‌تواند بیشتر از۱۰سهم داشته باشد.

|روش|پایانی، میلیون تومان|افت بیشینه|
|---|---:|---:|
|S2_publication|174.8889|20.03٪|
|existing_choose|169.7205|20.43٪|
|profit_growth|173.0624|23.79٪|
|equal_weight_all|148.0097|23.02٪|
|D1_monthly_counterfactual|178.8473|20.74٪|
|S2_common|181.0190|20.07٪|
|equal_feature_ranks|140.1485|24.71٪|
|ridge_rank|153.0935|25.33٪|

machine_comparison.csv گردش، هزینه، نقد، سفارش ناقص و ارزش‌گذاری کهنه را دارد؛ block_performance.csv دو بلوک کامل و انتهای ناقص را جدا می‌کند. S2_common کنترل رتبه روی همان جامعهٔ ویژگی مدل است؛ S2_publication جامعهٔ طبیعی S2 است. اختلاف این دو اثر پوشش است. D0→D1→D2 در data_ablation.csv با هش ورودی و اختلاف NAV آمده و تغییر داده بهبود فرمول نامیده نشده است.

## دروازه و محدودیت نتیجه

```json
{
  "candidates": [
    {
      "method": "equal_feature_ranks",
      "same_cohort_research_pass": false,
      "natural_total_research_pass": false,
      "research_pass": false,
      "wealth_ratio_same_cohort_S2": 0.7742198337040554,
      "wealth_ratio_natural_S2": 0.8013575641881938,
      "wealth_ratio_same_conditions_selector": 0.8257606591241753,
      "wealth_ratio_frozen_V5_selector": 0.8257606591241753,
      "complete_blocks": 2,
      "common_block_wins": 0,
      "natural_block_wins": 0,
      "extra_drawdown_same_cohort": 0.046466733280911,
      "remove_best_block_wealth": 0.9772233736064594,
      "reference_same_removed_block_wealth": 1.082791049591178,
      "largest_contributor_pnl_toman": 14028346.665447995,
      "largest_contributor_to_advantage": -0.3432388579715656,
      "data_quality_pass": true,
      "status": "no_qualified_winner",
      "independent_evidence": false,
      "stress_pass": null,
      "major_improvement_pass": false
    },
    {
      "method": "ridge_rank",
      "same_cohort_research_pass": false,
      "natural_total_research_pass": false,
      "research_pass": false,
      "wealth_ratio_same_cohort_S2": 0.845731358640263,
      "wealth_ratio_natural_S2": 0.8753756904871487,
      "wealth_ratio_same_conditions_selector": 0.9020327996656821,
      "wealth_ratio_frozen_V5_selector": 0.9020327996656821,
      "complete_blocks": 2,
      "common_block_wins": 1,
      "natural_block_wins": 1,
      "extra_drawdown_same_cohort": 0.05262071853080219,
      "remove_best_block_wealth": 0.9757605736824475,
      "reference_same_removed_block_wealth": 1.082791049591178,
      "largest_contributor_pnl_toman": 12893235.429020956,
      "largest_contributor_to_advantage": -0.46170013925930686,
      "data_quality_pass": true,
      "status": "no_qualified_winner",
      "independent_evidence": false,
      "stress_pass": null,
      "major_improvement_pass": false
    }
  ],
  "promotion": "none; S2 preserved; no economic/real-account validation",
  "stress": "not_tested; no research-qualified finalist",
  "capital500m": "not_tested; no stress-passing finalist",
  "data_recovered": false,
  "selector_reselection": "same data => locked V3 choices reused, no redundant financial paths",
  "limitations": [
    "consumed history",
    "two complete blocks",
    "overlapping training labels",
    "local 254 identities; not survivor-free market"
  ]
}
```

دروازهٔ پژوهشی با برتری نسبت به S2 هم‌داده/هم‌cadence، اکثریت بلوک‌های کامل و حد۵واحددرصد افت ثبت شد؛ برای نامزد نهایی مقایسهٔ جامعهٔ طبیعی نیز الزامی شد. تنها دو بلوک کامل داریم و شواهد ضعیف است. تشخیص تمرکز از PnL نماد و حذف بهترین بلوک محاسبه شده، بدون حذف برنده از جامعهٔ معامله. آستانهٔ عمده۱٫۱۰با انتخابگر مستقل از بهبود کوچک است؛ قاعدهٔ V5 عوض نشد. روی این داده وزن‌گردانی بیشتر انجام نمی‌دهیم.

## اقتصاد مرتبط با موجودی مرجع

سه خوشه بر اساس ارزش موجودی خام شبیه‌سازی‌شدهٔ انتخابگر و دسترسی سند انتخاب و بدنه‌های اصلی محلی خوانده شد. economic_selected_exposures.csv تاریخ و تعداد واقعیِ موجودی مدل را نگه می‌دارد. اسناد ثبت افزایش سرمایه به‌تنهایی اثبات اتصال دقیق ex-date، دارندهٔ واجد حق و معامله‌پذیری نیستند؛ هیچ اثر نقد یا سهم مجهول صفر نشد و fixture فرضی تازه جایگزین نشد. economic_event_progress.csv شناسه‌ها و سند دقیق مفقود را مشخص می‌کند. دریافت کاتالوگ ناموفق۲۶نماد تکرار نشد. بازده اقتصادی کل همچنان نامعلوم است.

## کنترل و تحویل

4 مسیر مالی تمام‌دورهٔ تازه، 4 مسیر مرجع بازاستفاده‌شده، 0 مسیر مالی شکست‌خورده؛ آزمون کوچک شاخهٔ تنش انتخابگر جدا از مسیرهای تمام‌دوره اجرا شد. آزمون‌های پایتون، رندر واقعی کامپوننت در سه حالت و build در test_evidence.json ثبت‌اند. صفحهٔ /ranking/research همان صفحه است؛ فهرست S2 و تاریخ۱۴اکتبر/۱۰۱از۲۵۴ حفظ شده و به امروز نسبت داده نمی‌شود. فایل جدید V6 از V5 مستقل است. هیچ کار مالی پس از پایان فرمان در پس‌زمینه ادعا نمی‌شود.
