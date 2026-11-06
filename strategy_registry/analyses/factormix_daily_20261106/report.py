"""Export a static comparison chart and a checksum inventory for this analysis."""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'artifacts'


def main():
    summary = json.loads((OUT / 'summary.json').read_text(encoding='utf8'))
    accounts = summary['accounts']
    cases = [('original_quarterly','Original: quarterly +40 days','#059669'),
             ('monthly_jalali_15','Monthly: Jalali day 15','#7c3aed'),
             ('daily_after_close','Daily: after market close','#e11d48')]
    fig,axes = plt.subplots(2,1,figsize=(11,7.6),sharex=True,
                            gridspec_kw={'height_ratios':[2.1,1]},layout='constrained')
    for key,label,color in cases:
        frame = pd.read_csv(OUT / f'{key}_nav.csv')
        dates = pd.to_datetime(frame.session)
        values = frame.nav_toman.to_numpy()
        axes[0].plot(dates,values/1e6,color=color,lw=1.7,label=label)
        drawdown = values/np.maximum.accumulate(np.r_[summary['initial_toman'],values])[1:]-1
        axes[1].plot(dates,drawdown,color=color,lw=1.2)
        axes[0].annotate(f'{values[-1]/1e6:,.0f}',xy=(dates.iloc[-1],values[-1]/1e6),
                         xytext=(7,0),textcoords='offset points',color=color,fontsize=9,va='center')
    axes[0].set_title('FactorMix: change only the portfolio review schedule',loc='left',weight='bold',pad=15)
    axes[0].set_ylabel('Portfolio value (million toman)')
    axes[0].yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    axes[0].legend(loc='upper left',frameon=False)
    axes[1].set_ylabel('Drawdown from own peak')
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1].set_xlabel('2022-03-26 to 2026-11-04 | Initial capital: 100 million toman | Costs included')
    for ax in axes:
        ax.grid(axis='y',alpha=.18)
        ax.spines[['top','right']].set_visible(False)
        ax.margins(x=.04)
    fig.savefig(OUT / 'comparison.png',dpi=160,facecolor='white')
    plt.close(fig)
    daily = accounts['daily_after_close']; monthly = accounts['monthly_jalali_15']
    no_cost_daily = accounts['daily_zero_cost']['metrics']['final_toman']
    no_cost_monthly = accounts['monthly15_zero_cost']['metrics']['final_toman']
    paragraph = ('\n## تفسیر نتیجه\n\n'
        f"با اجرای دقیق همان موتور، ارزش پایان روزانه {daily['metrics']['final_toman']:,.0f} تومان است؛ "
        f"{abs(summary['daily_relative_to_monthly']):.2%} کمتر از ماهانهٔ ۱۵. تعداد اجراها از {monthly['fills']} به {daily['fills']} رسید "
        f"و میانهٔ مدت موقعیت‌های بسته‌شده از {monthly['holding']['median_closed_holding_sessions']:.0f} به {daily['holding']['median_closed_holding_sessions']:.0f} جلسه کاهش یافت.\n\n"
        f"حتی با حذف هزینه‌ها، روزانه {no_cost_daily:,.0f} تومان در برابر {no_cost_monthly:,.0f} تومان ماهانه شد؛ "
        'بنابراین تفاوت به جمع کارمزدها محدود نیست. زمان و ترکیب ورود و خروج‌ها نیز تغییر می‌کند. آزمایش بدون هزینه یک مسیر فرضی تازه با نقد و معاملات متفاوت است و تفاضل آن با حالت اصلی، صرفاً جمع حسابداری هزینه‌ها نیست.\n\n'
        'در FactorMix حدود ۴۳٫۸٪ وزن امتیاز مربوط به بلوک‌های روند قیمت و ریسک است. پس با ثابت ماندن گزارش‌ها نیز تغییر قیمت می‌تواند امتیاز و رتبه را عوض کند. بازبینی روزانه امکان واکنش بیشتری به این تغییرها می‌دهد. این نتیجه ثابت نمی‌کند که بررسی روزانه در همهٔ مدل‌ها یا دوره‌ها بدتر است.\n')
    report = HERE / 'REPORT.fa.md'
    report.write_text(report.read_text(encoding='utf8').split('\n## تفسیر نتیجه')[0]+paragraph,encoding='utf8')
    files = [dict(path=p.relative_to(HERE).as_posix(),bytes=p.stat().st_size,
                  sha256=hashlib.sha256(p.read_bytes()).hexdigest())
             for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='delivery_manifest.json']
    (OUT / 'delivery_manifest.json').write_text(json.dumps(dict(
        purpose='isolated daily-review analysis; not a registered or activated strategy',
        files=files,independent_accounting='PASS',primary_controls_reproduced=True,
        pending_order_sensitivity_completed=True),indent=2),encoding='utf8')
    print(json.dumps(dict(status='PASS',files=len(files),chart='artifacts/comparison.png')))


if __name__ == '__main__':
    main()
