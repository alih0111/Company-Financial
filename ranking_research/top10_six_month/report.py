import pandas as pd
from .common import read, checkpoint


def report(out):
    a = read(out / 'acceptance.json'); coverage = pd.read_csv(out / 'coverage_by_date.csv')
    text = ['# نتیجهٔ پژوهش سبد ده‌سهمی', '',
            '**این اجرا پژوهشی است و رتبه‌بندیِ برتر یا آمادهٔ معامله تأیید نشده است.**', '',
            'روش: شش ترکیب چهارعامل ارزندگی، کیفیت، رشد اسمی سود و روند قیمت؛ بازبینی یک، سه و شش ماه. انتخاب با ۲۴ ماه غربال و ۱۲ ماه انتخاب، سپس بلوک شش‌ماههٔ بعدی.', '',
            f"تقویم بررسی، شامل ماه‌های فاقد داده: {coverage.decision_time.min()} تا {coverage.decision_time.max()}. کمترین/بیشترین تعداد واجد شرایط: {coverage.eligible.min()}/{coverage.eligible.max()}. تعداد کل در فایل پوشش، شمار ورودی‌های مالیِ بازسازی‌شده است و شمار کل بازار نیست.", '',
            'جامعه فقط شناسه‌های آرشیوشده است؛ پوشش کل بازار، حذف‌شده‌ها و سابقهٔ پذیرش تأیید نشده. نوع شرکت فقط با مدرک تاریخی انتخاب شده؛ نسخه از پیش بدون سقف صنعت ثبت شده است.', '',
            '**معنای ارقام:** شبیه‌سازی شاخص قیمت تعدیل‌شده با هزینهٔ فرضی نیم درصد در هر سمت؛ واحدهای صحیح شاخص، سهم واقعی قابل‌تحویل نیستند. سود نقدی قابل دریافت، حق‌تقدم و صف تأیید نشده‌اند. ارقام، نتیجهٔ یک حساب نقدی قابل سرمایه‌گذاری نیستند.', '']
    if (out / 'comparison.csv').exists():
        frame = pd.read_csv(out / 'comparison.csv')
        primary = frame[frame.name.eq('walk_forward')].iloc[0]
        text += [f"سرمایهٔ اولیه: ۱۰۰٬۰۰۰٬۰۰۰ تومان. بازهٔ آزمون: {primary.start} تا {primary.end}. سرمایهٔ پایان در شبیه‌سازی قیمت تعدیل‌شده: **{primary.final_toman:,.0f} تومان**؛ بازده خالص سناریو {primary.net_return:.1%}؛ بیشترین افت {primary.max_drawdown:.1%}.", '',
                 '| روش | سرمایهٔ پایان سناریو (تومان) | بازده | افت |', '|---|---:|---:|---:|']
        for row in frame[frame.name.isin(['walk_forward', 'balanced_1m', 'balanced_3m', 'balanced_6m', 'equal_weight_1m', 'walk_forward_stress'])].itertuples():
            text.append(f'| {row.name} | {row.final_toman:,.0f} | {row.net_return:.1%} | {row.max_drawdown:.1%} |')
        text += ['', f"تعداد بلوک‌های کامل: {a['test_blocks']}. صدک نتیجه در ۲۰۰ سبد تصادفی: {a['primary_random_percentile']:.1f}.", '',
                 'مقایسه‌های ثابت کل تاریخ فقط تشخیصی‌اند؛ بهترین آن‌ها از ابتدای تاریخ معلوم نبوده است. پنج جابه‌جایی شروع در comparison.csv ثبت شده و مستقل نیستند.', '',
                 '## شروطی که پاس نشده‌اند', ''] + [f'- `{s}`' for s in a['failed_checks']]
    text += ['', '## تصمیم و ادامهٔ کار', '',
             'نسخهٔ فعال /ranking تغییر نکرده است. این اجرای پژوهشی مجوز خرید ده سهم اول یا اتصال کارگزاری نیست.', '',
             'برای تکمیلِ ارزیابی: سابقهٔ معتبر پذیرش/حذف نماد، رویدادهای نقدی و حق‌تقدم با تاریخ قابل دریافت، دادهٔ صف/دامنهٔ مجاز و امکان تسویهٔ پایان پنجره لازم است. کمبود این منابع با تنظیم وزن حل نمی‌شود. وضعیت هر شرط در acceptance.json و داده‌های هر معامله در دفترها قابل بررسی است.', '',
             'تمام تاریخ موجود قبلاً بررسی شده است؛ این آزمایش بازسازی زمانی پژوهشی است و آزمون دست‌نخورده محسوب نمی‌شود.', '']
    if (out / 'volume_mapping_audit.json').exists():
        volume = read(out / 'volume_mapping_audit.json')
        text += ['## کنترل حجم معاملات', '',
                 f"حجم تعداد سهم از qTotTran5J و تعداد دفعات معامله از zTotTran خوانده شد. در {volume['ohlc_value_identity_observations']:,} مشاهده، سازگاری ارزش/حجم با بازهٔ قیمت {volume['correct_volume_price_bounds_fraction']:.1%} بود. اجرای قبلی با حجمِ اشتباه باطل و حفظ شده است؛ نتیجهٔ این اجرا با نگاشت اصلاح‌شده محاسبه شده است.", '']
    if (out / 'legacy_comparison.csv').exists():
        text += ['## مقایسه با فرمول‌های قبلی', '',
                 'در legacy_comparison.csv فرمول CASH_QV و زیرمجموعهٔ ۷۶ امتیازی QVT، با پوشش واقعی خود و جامعهٔ مشترکِ مبتنی بر ورودی، در هر سه فاصله دوباره محاسبه شده‌اند. این زیرمجموعه، کل مدل زندهٔ QVT نیست. غربال قدیمی به‌علت فقدان تاریخ انتشار معتبرِ بخشی از ماهانه‌ها، قابل مقایسهٔ معتبر اعلام نشده است.', '']
    (out / 'report.fa.md').write_text('\n'.join(text), encoding='utf8')
    # Standalone shareable chart; no front-end production change before acceptance.
    if (out / 'daily_nav.csv').exists():
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for name in ['walk_forward', 'balanced_1m', 'equal_weight_1m']:
            path = out / 'daily_nav.csv' if name == 'walk_forward' else out / 'comparisons' / f'{name}_daily.csv'
            data = pd.read_csv(path); x = pd.to_datetime(data.date); nav = data.nav_rial / 10
            axes[0].plot(x, nav / 1e6, label=name)
            axes[1].plot(x, 100 * (nav / nav.cummax() - 1), label=name)
        axes[0].set_ylabel('Million toman (adjusted-price proxy)'); axes[1].set_ylabel('Drawdown %')
        axes[0].legend(); axes[0].set_title('Research only - execution and corporate cashflows uncertified')
        fig.tight_layout(); fig.savefig(out / 'wealth_drawdown.png', dpi=150); plt.close(fig)
    checkpoint(out, 'report')
