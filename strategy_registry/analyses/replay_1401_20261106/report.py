"""Persian report and exportable chart for the frozen 1401-start replay."""
from pathlib import Path
import hashlib,json
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;OUT=HERE/'artifacts'


def million(value):return f'{value/1e6:,.1f}'
def pct(value):return f'{value*100:,.1f}٪'


def main():
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    candidate=summary['accounts']['candidate'];baseline=summary['accounts']['baseline']
    cm=candidate['metrics'];bm=baseline['metrics'];positions=candidate['ledger']['positions']
    xml=ET.parse(OUT/'tests.junit.xml').getroot()
    suites=list(xml.iter('testsuite'))
    assert sum(int(t.get('failures','0'))+int(t.get('errors','0')) for t in suites)==0
    tests=sum(int(t.get('tests','0')) for t in suites)
    fig,(a,b)=plt.subplots(2,1,figsize=(11.4,7.4),sharex=True,gridspec_kw={'height_ratios':[2.4,1]})
    for label,title,color in [('candidate','FactorMix-033 (frozen v1.0.0)','#07836c'),('baseline','P1 BASE: same dates and execution','#657c9b')]:
        nav=pd.read_csv(OUT/f'{label}_nav.csv');x=pd.to_datetime(nav.session);v=nav.nav_toman.to_numpy()/1e6
        a.plot(x,v,label=title,color=color,lw=1.9)
        b.plot(x,(v/np.maximum.accumulate(np.r_[100,v])[1:]-1)*100,color=color,lw=1.3)
        a.annotate(f'{v[-1]:,.1f}m',xy=(x.iloc[-1],v[-1]),xytext=(-8,10),textcoords='offset points',ha='right',color=color,weight='bold')
    a.set_title('1401 start: 100 million toman to latest available close',loc='left',weight='bold',fontsize=14,pad=14)
    a.set_ylabel('Portfolio value (million toman)');b.set_ylabel('Drawdown (%)')
    a.legend(frameon=False,loc='upper left',fontsize=9)
    for ax in [a,b]:
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.18)
    b.xaxis.set_major_locator(mdates.MonthLocator(interval=6));b.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.text(.08,.027,'2022-03-26 to 2026-11-04. Retrospective reconstruction; simulated fills and adjusted index units. Not live or unseen performance.',fontsize=8,color='#555')
    fig.tight_layout(rect=[0,.05,1,1]);fig.savefig(OUT/'comparison.png',dpi=170,facecolor='white');plt.close(fig)
    annual='\n'.join(f"| {'تا ۱۳ آبان ۱۴۰۵' if r['year']==1405 else r['year']} | {million(r['final_toman'])} | {pct(r['return_fraction'])} |" for r in candidate['annual'])
    holding='\n'.join(f"| {r['symbol']} | {million(r['market_value_toman'])} | {pct(r['weight'])} | {r['price_date']} | {'خروج اجرا نشده' if r['action']=='EXIT_UNFILLED' else 'در سبد هدف'} |" for r in positions)
    first='، '.join(candidate['first_decision']['target'].split(';'))
    text=f'''# بازپخش FactorMix-033 از ابتدای ۱۴۰۱

**۱۰۰ میلیون تومان از ۶ فروردین ۱۴۰۱ تا ۱۳ آبان ۱۴۰۵، در این شبیه‌سازی به {cm['final_toman']:,.0f} تومان رسیده است؛ حدود ۲٫۵۴۷ میلیارد تومان.** مدل P1 با همان بازه، سرمایه، داده و فرض‌های اجرا به {bm['final_toman']:,.0f} تومان، حدود ۱٫۵۴۰ میلیارد تومان، رسیده است.

این آزمون صرفاً شروع حساب را عقب می‌برد. وزن‌ها، قواعد سبد و موتور بایگانی‌شدهٔ نسخهٔ ۱٫۰٫۰ تغییر نکرده‌اند و بهینه‌سازی یا انتخاب نسخهٔ جدید انجام نشده است. مبلغ‌ها اسمی‌اند و به تورم یا نرخ ارز تعدیل نشده‌اند.

## تاریخ و سرمایهٔ شروع

درخواست از ابتدای ۱۴۰۱ است؛ اولین جلسهٔ موجود ۶ فروردین ۱۴۰۱ (۲۰۲۲-۰۳-۲۶) و اولین خرید ۷ فروردین (۲۰۲۲-۰۳-۲۷) است. حساب در آغاز دقیقاً ۱۰۰ میلیون تومان نقد و صفر دارایی دارد. سابقهٔ قیمت و عوامل پیش از شروع برای ساخت ویژگی‌ها استفاده می‌شود؛ معامله یا سرمایهٔ قبلی به حساب منتقل نمی‌شود.

آخرین دادهٔ موجود ۱۳ آبان ۱۴۰۵ (۲۰۲۶-۱۱-۰۴) است، نه تاریخ ۱۵ آبانِ درخواست. برای روزهای فاقد داده، معامله یا بازده ساخته نشده است. هدف اولین تصمیم: {first}.

## نتیجه و مقایسه

| شاخص | FactorMix-033 | P1 مبنا |
|---|---:|---:|
| ارزش نهایی میلیون تومان | {million(cm['final_toman'])} | {million(bm['final_toman'])} |
| سود خالص میلیون تومان | {million(cm['final_toman']-summary['initial_toman'])} | {million(bm['final_toman']-summary['initial_toman'])} |
| بازده کل | {pct(cm['total_return'])} | {pct(bm['total_return'])} |
| بازده مرکب سالانهٔ تاریخی | {pct(cm['cagr'])} | {pct(bm['cagr'])} |
| بیشترین افت از سقف قبلی | {pct(abs(cm['max_drawdown']))} | {pct(abs(bm['max_drawdown']))} |
| تعداد اجراهای خرید و فروش | {candidate['fills']} | {baseline['fills']} |
| تعداد تصمیم‌ها | {candidate['decisions']} | {baseline['decisions']} |

مبنای P1 از تنظیم ثابت BASE خودش استفاده می‌کند؛ بافر نگهداری و باند بازتنظیم FactorMix به آن تحمیل نشده‌اند. داده، روز شروع و پایان، سرمایه و محدودیت‌های اجرا مشترک‌اند. اختلاف ثروت پایان حدود {million(summary['final_difference_toman'])} میلیون تومان است. این مقایسه به‌تنهایی اثر امتیاز را از اثر قواعد متفاوت سبد جدا نمی‌کند.

## مسیر سالانهٔ همان حساب پیوسته

همهٔ مبلغ‌های جدول میلیون تومان‌اند؛ سرمایه در ابتدای سال‌ها مجدداً ۱۰۰ میلیون نمی‌شود.

| دوره | ارزش پایان | بازده همان دوره |
|---|---:|---:|
{annual}

سال ۱۴۰۴ با آخرین قیمت موجود در اسفند و سال ۱۴۰۵ از اولین فعالیت مشاهده‌شدهٔ سهام پس از تعطیلی تا ۱۳ آبان گزارش شده است. روزهای فاقد فعالیت با تقویم مشاهده‌شدهٔ سهام همان نسخهٔ قفل‌شده رسیدگی می‌شوند.

مسیر سال ۱۴۰۲ در این حساب با آزمونی که تازه در ۱۴۰۲ شروع می‌شود یکسان نیست: موجودی و سابقهٔ نگهداری از ۱۴۰۱ ادامه دارد، بافر رتبه و محدودیت ظرفیت نیز به وضعیت حساب وابسته‌اند. نتیجهٔ آزمون مستقلِ شروع ۱۴۰۲، یعنی حدود ۱٫۲۹۰ میلیارد تومان، قبل از اجرای این آزمون عیناً بازتولید شد و بازنویسی نشده است.

## هزینه و اجرای مدل

کارمزد هر طرف ۰٫۵٪، لغزش هر طرف ۰٫۱٪، ظرفیت روزانه حداکثر ۵٪ میانهٔ ارزش معاملات قبلی و مهلت سفارش پنج جلسه است. روز تک‌قیمت طبق همان قاعدهٔ ثبت‌شده برای اجرا پذیرفته نمی‌شود. در حساب جدید جمع کارمزد {million(candidate['fees_toman'])} میلیون و اثر لغزش {million(candidate['slippage_toman'])} میلیون تومان است؛ این هزینه‌ها قبلاً از نتیجه کم شده‌اند و نباید دوباره کسر شوند.

تعداد هدف پنج سهم است؛ به‌دلیل خروج‌های کامل‌نشده، بیشترین تعداد موقعیت موجود در طول مسیر {candidate['maximum_position_count']} و در پایان {len(positions)} بوده است. پنج سهم سقف سخت تعداد موقعیت‌های اجراشده نیست.

## ترکیب پایان و قابلیت نقدکردن

| نماد | ارزش میلیون تومان | وزن واقعی پایان | تاریخ آخرین قیمت میلادی | وضعیت |
|---|---:|---:|---|---|
{holding}

نقد پایان مدل {candidate['ledger']['terminal_cash_toman']:,.0f} تومان است. خروج شمواد اجرا نشده و قیمت آن هشت روز پیش از پایان داده است؛ حدود {million(next(r['market_value_toman'] for r in positions if r['symbol']=='شمواد'))} میلیون تومان از ارزش پایان به این موقعیت مربوط است. ارزش نهایی، NAV بر پایهٔ قیمت‌های ثبت‌شده است و فروش فوری کل سبد با همین مبلغ را اثبات نمی‌کند. تعدادها واحد شاخصی تعدیل‌شده‌اند، نه تعداد سهم واقعی کارگزاری.

## کنترل صحت و محدودیت اعتماد

چک‌سام {summary['archive_files_verified']} فایل بایگانی پیش و پس از اجرا بررسی شد. موتور از خود بستهٔ ثبت‌شده بارگذاری شد. کل مسیر روزانهٔ آزمون قبلی ۱۴۰۲ بازتولید شد. برای هر دو حساب، دفتر مستقلِ نقد و واحد، NAV هر روز، تقدم تصمیم بر اجرا، محدودیت ظرفیت، کارمزد، سود بسته و باز و زنجیرهٔ بازده سالانه تطبیق داده شد. {tests} تست مستقلِ فایل‌های خروجی موفق بوده است.

این بازپخش شاهد مستقلِ آیندهٔ دیده‌نشده نیست: بخشی از همین تاریخچه برای انتخاب مدل استفاده شده است؛ زمان دریافت واقعی تمام گزارش‌های تاریخی اثبات نشده؛ جهان ۲۵۴ نمادی ثابت خطر سوگیری بقا دارد؛ حسابداری واحد شاخص و سرمایه‌گذاری فوری سود نقدی جای حسابداری واقعی اقدامات شرکتی نیست؛ و دادهٔ روزانه صف واقعی را اثبات نمی‌کند. این نتیجه مجوز اتکای قطعی با پول واقعی نیست.

هیچ فایل نسخهٔ منجمد، حساب پیگیری، رتبه‌بندی صفحه یا معاملهٔ واقعی در این اجرا تغییر نکرده است. این نتیجه در پوشهٔ تحلیل مستقل نگهداری می‌شود و جایگزین حساب شروع ۱۴۰۲ نیست.

## خروجی‌ها

- `artifacts/summary.json`: نتیجه، سالانه، ترکیب پایان و کنترل حساب‌ها.
- `artifacts/protocol.json`: تاریخ‌ها، سرمایه، قواعد و اثر انگشت ورودی و موتور پیش از اجرا.
- `artifacts/candidate_nav.csv` و `baseline_nav.csv`: کل مسیر روزانه.
- `artifacts/candidate_trades.csv` و `baseline_trades.csv`: تمام اجراها.
- `artifacts/candidate_ledger.csv` و `baseline_ledger.csv`: دفتر نقد و بهای تمام‌شده.
- `artifacts/candidate_decisions.csv` و `baseline_decisions.csv`: هدف تصمیم‌ها.
- `artifacts/comparison.png`: نمودار سرمایه و افت.
- `artifacts/tests.junit.xml`: نتیجهٔ تست‌ها.
'''
    (HERE/'REPORT.fa.md').write_text(text,encoding='utf8')
    manifest=[]
    for path in sorted(HERE.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and '.pytest_cache' not in path.parts and path.name!='delivery_manifest.json':
            manifest.append(dict(path=path.relative_to(HERE).as_posix(),bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (OUT/'delivery_manifest.json').write_text(json.dumps(dict(files=manifest),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(report='REPORT.fa.md',tests=tests,files=len(manifest))))


if __name__=='__main__':main()
