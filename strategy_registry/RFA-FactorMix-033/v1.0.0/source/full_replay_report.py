"""Persian full-period report, comparable endpoints and a checked chart."""
from pathlib import Path
import hashlib,json,sys
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import jdatetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE=Path(__file__).resolve().parent;OUT=HERE/'artifacts';ROOT=HERE.parents[2]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(name):return json.loads((OUT/name).read_text(encoding='utf8'))
def million(v):return f'{v/1e6:,.1f}'
def pct(v):return f'{v*100:.1f}٪'


def main():
    s=read('active_summary.json');generic=read('complete_summary.json');market=read('market_extension.json');fin=read('active_financial_extension_audit.json')
    junit=ET.parse(OUT/'tests.junit.xml').getroot()
    assert sum(int(x.attrib.get('errors',0))+int(x.attrib.get('failures',0)) for x in junit.iter('testsuite'))==0
    tests=sum(int(x.attrib.get('tests',0)) for x in junit.iter('testsuite'))
    fig,(a,b)=plt.subplots(2,1,figsize=(11,7.4),sharex=True,gridspec_kw={'height_ratios':[2.2,1]})
    for label,title,color in [('candidate','New strategy (frozen factor mix)','#148779'),('baseline','P1 baseline, same data and execution','#315b9d')]:
        d=pd.read_csv(OUT/f'active_{label}_nav.csv');x=pd.to_datetime(d.session);v=d.nav_toman.to_numpy()/1e6
        a.plot(x,v,color=color,lw=1.8,label=title)
        b.plot(x,(v/np.maximum.accumulate(np.r_[100,v])[1:]-1)*100,color=color,lw=1.4)
        a.annotate(f'{v[-1]:,.0f}m',xy=(x.iloc[-1],v[-1]),xytext=(-8,9),textcoords='offset points',ha='right',color=color,weight='bold')
    a.set_title('1402 start: 100m toman to latest available close',loc='left',fontsize=15,weight='bold',pad=14)
    a.set_ylabel('Portfolio value (million toman)');b.set_ylabel('Drawdown (%)')
    for z in [a,b]:
        z.grid(axis='y',alpha=.18);z.spines[['top','right']].set_visible(False)
        z.axvline(pd.Timestamp('2026-02-24'),color='#999999',ls=':',lw=1)
    a.legend(frameon=False,loc='upper left',fontsize=9)
    b.xaxis.set_major_locator(mdates.MonthLocator(interval=6));b.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.text(.08,.025,'2023-03-25 to 2026-11-04. Publication-reconstructed data; research adjustment extension after September. Simulated fills, not live performance.',fontsize=8.2,color='#555555')
    fig.tight_layout(rect=[0,.05,1,1]);fig.savefig(OUT/'full_comparison.png',dpi=170,facecolor='white');plt.close(fig)
    yearrows='\n'.join(f"| {'تا ۱۳ آبان ۱۴۰۵' if r['year']==1405 else r['year']} | {million(r['final_toman'])} | {pct(r['return_fraction'])} |" for r in s['jalali_years'])
    commonrows=[]
    for r in s['same_date_comparison']:
        day=str(jdatetime.date.fromgregorian(date=pd.Timestamp(r['date']).date()))
        commonrows.append(f"| {day} | {million(r['candidate_toman'])} | {million(r['baseline_toman'])} |")
    c=s['candidate'];base=s['baseline'];delta=c['final_toman']-base['final_toman']
    from_date='۵ فروردین ۱۴۰۲';to_date='۱۳ آبان ۱۴۰۵'
    text=f'''# بازپخش استراتژی جدید از ابتدای ۱۴۰۲ تا آخرین روز موجود

با سرمایهٔ اولیهٔ ۱۰۰ میلیون تومان، ارزش سبد استراتژی جدید تا {to_date}، آخرین روز قیمت موجود در آرشیو، به حدود **{million(c['final_toman'])} میلیون تومان** رسیده است؛ یعنی حدود **۱٫۲۹ میلیارد تومان**. مبنای P1 با همان ورودی و فرض‌های اجرا به {million(base['final_toman'])} میلیون تومان رسیده است. وزن‌ها و قواعد مدل تغییر نکردند و هیچ بهینه‌سازی مجددی انجام نشد.

تاریخ امروزِ درخواست ۱۵ آبان ۱۴۰۵ است؛ آخرین قیمت موجود مربوط به ۱۳ آبان است. برای روزهای فاقد قیمت، بازده یا معامله ساخته نشده است. نخستین جلسهٔ موجود برای شروع {from_date} و نخستین خرید ۶ فروردین ۱۴۰۲ است. تاریخچهٔ قبل از شروع فقط برای محاسبهٔ ویژگی‌ها استفاده شد؛ سرمایه‌گذاری قبل از شروع صورت نگرفت.

## مقایسه در تاریخ پایان یکسان

همهٔ ارقام جدول، میلیون تومان و با شروع ۱۰۰ میلیون تومان در ابتدای ۱۴۰۲ هستند.

| تاریخ پایان شمسی | مدل جدید | P1 مبنا با فرض‌های مشترک |
|---|---:|---:|
{chr(10).join(commonrows)}

عدد ۴۱۷٫۵ میلیون مربوط به ۵ اسفند ۱۴۰۴ بود. عدد ۸۵۹٫۴ میلیونِ سند قدیمی تا ۸ مهر ۱۴۰۵ ادامه داشت؛ مقایسهٔ مستقیم آن دو درست نیست. در همین تاریخ ۸ مهر، مدل جدید در بازپخش تکمیل‌شده {million(s['same_date_comparison'][1]['candidate_toman'])} میلیون و مبنای همسان {million(s['same_date_comparison'][1]['baseline_toman'])} میلیون تومان دارد.

مبنای جدید عین خروجی ۸۵۹٫۴ میلیونی سند نیست: ورود اولیه و تقویم تصحیح شده‌اند، لغزش و ظرفیت حجم و عدم پرشدن لحاظ شده‌اند و ورودی مالی تاریخ‌های بعد از اسفند بازسازی شده است. عدد سند با فرض‌ها و رتبه‌های قدیمی حفظ شده و بازنویسی نشده است.

## حساسیت مهم به تقویم بازار سهام

اجرای اول با تقویم عمومیِ قبلی، ارزش نهایی {million(generic['candidate']['final_toman'])} میلیون تومان داد. کنترل نمودار نشان داد ۴۸ ردیف بعد از پایان پنل قدیمی، هیچ قیمت بازِ دارای معامله برای کل ۲۵۴ سهم ندارند؛ عمدهٔ آن‌ها در بهار ۱۴۰۵ هستند. شمارش این روزها، بازبینی فصلی و انقضای سفارش را در دوره‌ای که سهام معامله ندارد جلو می‌برد.

قاعدهٔ اصلاح پیش از اجرای کنترل ثبت شد: بخش قدیمی تا ۵ اسفند بدون تغییر بماند؛ پس از آن، روز فاقد معامله در کل این جهان سهامی، جلسهٔ سهام شمرده نشود. این تقویم از فعالیت مشاهده‌شده ساخته شده و ادعای گواهی تقویم رسمی بورس نیست. در نتیجه، بازبینی بهار به جای ۲۹ آوریل، در ۱۹ مه، برابر ۲۹ اردیبهشت، انجام می‌شود. دوره‌های قیمت و مهلت پنج‌جلسه‌ای نیز روی همین جلسات سهام شمارش می‌شوند. وزن، تعداد سهم، روز چهل، هزینه و مهلت سفارش به قصد بهترکردن بازده تغییر نکرده‌اند.

عدد اصلی گزارش، اجرای اصلاح‌شدهٔ سهام یعنی {million(c['final_toman'])} میلیون تومان است. عدد {million(generic['candidate']['final_toman'])} میلیونِ تقویم عمومی نیز به عنوان کنترل حفظ شده است؛ این دو عدد سناریوی متفاوت‌اند و فاصلهٔ اطمینان آماری نیستند. مبنای P1 در این اصلاح همان {million(base['final_toman'])} میلیون باقی مانده است.

## مسیر سالانه سرمایه

| دوره | ارزش پایان دوره میلیون تومان | بازده همان دوره |
|---|---:|---:|
{yearrows}

یک حساب پیوسته استفاده شده است؛ در ابتدای هر سال سرمایه دوباره ۱۰۰ میلیون نشده و سودهای قبلی در سبد باقی مانده‌اند.

## خلاصه عملکرد و اجرا

| شاخص | مدل جدید | P1 مبنا |
|---|---:|---:|
| بازده کل | {pct(c['total_return'])} | {pct(base['total_return'])} |
| بازده مرکب سالانهٔ تاریخی | {pct(c['cagr'])} | {pct(base['cagr'])} |
| بیشترین افت | {pct(abs(c['max_drawdown']))} | {pct(abs(base['max_drawdown']))} |
| ارزش نهایی میلیون تومان | {million(c['final_toman'])} | {million(base['final_toman'])} |

مدل جدید حدود {million(delta)} میلیون تومان ثروت پایانی بیشتر ساخته است؛ معادل {(c['final_toman']/base['final_toman']-1)*100:.1f}٪ ثروت بیشتر از مبنای مشترک. این اختلاف توصیف همین بازپخش است و تضمین آینده نیست.

کارمزد ۰٫۵٪ و لغزش قیمت ۰٫۱٪ برای هر طرف، سقف روزانهٔ ۵٪ میانهٔ ارزش معاملات قبلی، رد فرض پرشدن روز تک‌قیمتی، پرشدن جزئی و انقضای پنج‌جلسه‌ای سفارش اعمال شدند. جمع کارمزدهای کسرشده حدود {million(s['fees_toman'])} میلیون و لغزش حدود {million(s['slippage_toman'])} میلیون تومان است. {s['trades']} معاملهٔ پرشده و {s['rebalances']} تصمیم بازبینی ثبت شد. ارزش نهایی با قیمت پایانی محاسبه شده، نه با فرض فروش فوری و نقدشوندهٔ کل سبد.

در پایان، با وجود هدف پنج‌سهمی، شش موقعیت باقی است: خروج شمواد هنوز پر نشده و با آخرین معاملهٔ ۲۷ اکتبر، هشت روز پیش از پایان، ارزش‌گذاری شده است. این موقعیت حدود ۲۵۹٫۹ میلیون تومان از ارزش سبد را تشکیل می‌دهد. بنابراین ۱٫۲۹ میلیارد، ارزش دفتری سبد بر اساس آخرین قیمت‌ها است و نقد قابل برداشتِ تضمین‌شده نیست.

## تکمیل داده بدون تغییر مدل

بخش قبلی تا ۵ اسفند ۱۴۰۴ عیناً حفظ شد؛ نه فقط ارزش پایان، بلکه کل مسیر روزانه با حداکثر یک تومان اختلاف بازتولید شد. آرشیو رسمی بازارِ سنجاق‌شده تا ۱۳ آبان، برای هر نماد از نظر هویت و اثر انگشت پاسخ خام کنترل شد.

پس از ۸ مهر، زنجیرهٔ تعدیل در همین پوشه و صرفاً برای تحقیق با همان نسبت «قیمت مرجع روز بعد به قیمت پایانی قبل» گسترش یافت. {len(market['new_reference_events'])} تغییر مرجع جدید در جهان نمادها ثبت شد. از {market['old_factor_regression_checks']} ضریب قبلی، ۱۱۴۵ ضریب قابل بازسازی تا دقت ذخیره‌سازی هشت رقم اعشار تطبیق داشتند. دو ضریب قبلی که بازنشانی مرجع آن‌ها در نسخهٔ فعلی خام دیده نمی‌شود، بدون تغییر از کش قبلی حفظ شدند؛ حذف یا جعل نشدند. این امتداد، گواهی جدید رسمی یا بازسازی اقتصادی سود نقدی و حق‌تقدم نیست.

برای ادامهٔ مدل، {len(s['new_financial_snapshots'])} snapshot مورد نیاز در تاریخ‌های چرخش و نقاط مبنای تغییرات ۹۰روزه ساخته شد: {', '.join(s['new_financial_snapshots'])}. هر کدام همهٔ ۲۵۴ هویت ثابت را دارند. گزارش‌ها با تاریخ انتشارِ قبل از cutoff انتخاب شدند؛ دادهٔ مالی «جدول مالک فعلی» به تاریخ‌های گذشته منتقل نشد. مقایسه‌های دارای زمان دسترسیِ صریحِ بعد از cutoff وارد آن snapshot نشدند. انتخاب دورهٔ صورت سود و زیان برای دادهٔ جدید از آداپتور فعلی V12.37 استفاده می‌کند و بخش تاریخی قبلی دست نخورده است. ورودی‌های ماهانه نیز با نسخه‌ها و اصلاحیه‌های همان زنجیره بازپخش شدند.

بنابراین رتبه‌های اسفند برای تمام ماه‌های بعد ثابت نگه داشته نشده‌اند و گزارش‌های آبان به فروردین نسبت داده نشده‌اند. در عین حال، زمان دریافت واقعی همهٔ داده‌های تاریخی اثبات‌شده نیست؛ این همچنان بازسازی بر اساس انتشار است، نه سابقهٔ واقعی اجرای سیستم در آن تاریخ.

## حدود برداشت از نتیجه

پارامترهای مدل پس از مشاهدهٔ بخشی از همین تاریخچه انتخاب شده‌اند. این نمودار فرض می‌کند همین قواعد منتخب در تمام دوره برقرار بوده‌اند؛ عملکرد مستقل آینده را ثابت نمی‌کند. واحدهای شاخص تعدیل‌شده و سرمایه‌گذاری مجدد فوریِ سود، جانشین حسابداری تعداد سهم واقعی، زمان پرداخت سود و اقدامات شرکتی نیستند. دادهٔ روزانه نیز اولویت صف را نشان نمی‌دهد. تمام ارقام اسمیِ تومان‌اند و به تورم یا نرخ ارز تعدیل نشده‌اند.

عدد اصلی پاسخ، حدود ۱٫۲۹ میلیارد تومان است و باید همراه با همین فرض‌های پژوهشی خوانده شود. هیچ وزن عملیاتی، حساب کاغذی موجود یا سفارش واقعی تغییر نکرد.

## فایل‌های بررسی

- [خلاصهٔ کامل با تقویم سهام]({(OUT/'active_summary.json').as_posix()})
- [کنترل با تقویم عمومی قبلی]({(OUT/'complete_summary.json').as_posix()})
- [مسیر روزانهٔ مدل جدید]({(OUT/'active_candidate_nav.csv').as_posix()})
- [فهرست تمام معاملات]({(OUT/'active_candidate_trades.csv').as_posix()})
- [تاریخ و رتبه‌های تصمیم‌ها]({(OUT/'active_candidate_decisions.csv').as_posix()})
- [ممیزی امتداد قیمت و تعدیلات]({(OUT/'market_extension.json').as_posix()})
- [ممیزی بازسازی مالی]({(OUT/'active_financial_extension_audit.json').as_posix()})
- [نمودار مقایسه]({(OUT/'full_comparison.png').as_posix()})

{tests} آزمون این اجرا، بازتولید روزانهٔ بخش قبلی، ثابت‌ماندن سیاست، عدم مصرف انتشار آینده، جهت ضریب تعدیل، حسابداری مستقل روزانه، هزینه‌ها و زنجیرهٔ بازده سال‌ها را کنترل کردند و گذشتند.
'''
    (HERE/'REPORT.fa.md').write_text(text,encoding='utf8')
    source_paths=[ROOT/market['latest_financial_manifest'],ROOT/fin['reports_path'],ROOT/fin['monthly_path'],
        ROOT/json.loads((ROOT/market['latest_financial_manifest']).read_text(encoding='utf8'))['financial']['comparatives_path']]
    evidence={'input_sources':[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in source_paths],
        'model_policy_sha256':read('available_replay.json')['policy_sha256'],'tests_passed':tests,
        'requested_end':'2026-11-06','actual_market_end':s['latest_available_market_day'],
        'files':[dict(path=str(p.relative_to(HERE)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(HERE.rglob('*'))
            if p.is_file() and p.suffix in ['.py','.md','.json','.csv','.parquet','.npz','.png','.xml'] and '__pycache__' not in p.parts and p.name!='delivery_manifest.json']}
    (OUT/'delivery_manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'final_toman':c['final_toman'],'baseline_toman':base['final_toman'],
        'end':s['latest_market_day_jalali'],'tests':tests,'report':str(HERE/'REPORT.fa.md')},indent=2))


if __name__=='__main__':main()
