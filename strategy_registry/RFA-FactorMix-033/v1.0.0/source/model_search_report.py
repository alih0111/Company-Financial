"""Deliver the wider-search findings without overstating reused evidence."""
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import json,hashlib,platform,sys
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from features import HERE,OUT,PREV,sha
sys.path.insert(0,str(PREV))
from engine import Execution
from run_research import dump


def read(name):return json.loads((OUT/name).read_text(encoding='utf8'))
def pct(x):return f'{x*100:.1f}٪'
def money(x):return f'{x/1e6:,.1f}'
def link(name,label):return f'[{label}]({(OUT/name).as_posix()})'


def chart():
    fig,(a,b)=plt.subplots(2,1,figsize=(10.5,7),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for label,title,color in [('candidate','New factor mix + rank buffer','#168c79'),('baseline','Original P1 top 5','#315b9d')]:
        d=pd.read_csv(OUT/f'verify_{label}_nav.csv');x=pd.to_datetime(d.session);v=d.nav_toman.to_numpy()/1e6
        a.plot(x,v,label=title,color=color,lw=2)
        b.plot(x,(v/np.maximum.accumulate(np.r_[100,v])[1:]-1)*100,color=color,lw=1.7)
    a.set_title('Expanded feature search: reused retrospective verification',loc='left',fontsize=14,weight='bold',pad=15)
    a.set_ylabel('Value (million toman)');b.set_ylabel('Drawdown (%)')
    a.legend(frameon=False,loc='upper left')
    for z in [a,b]:
        z.grid(axis='y',alpha=.18);z.spines[['right','top']].set_visible(False)
    b.xaxis.set_major_locator(mdates.MonthLocator(interval=2));b.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.text(.09,.025,'2025-01-01 to 2026-02-24. Initial 100m toman. Modeled fees, slippage and capacity. Not prospective or live performance.',fontsize=8.5,color='#555555')
    fig.tight_layout(rect=[0,.05,1,1]);fig.savefig(OUT/'comparison.png',dpi=170,facecolor='white');plt.close(fig)


def main():
    s=read('summary.json');st=read('stability_summary.json');feat=read('feature_manifest.json')
    proto=read('protocol.locked.json');fits=read('fit_audits.json')
    for name,h in proto['source_hashes'].items():
        p=OUT/name if (OUT/name).exists() else HERE/name
        assert sha(p)==h,(name,'changed after registration')
    assert all(a['max_label_end'] is None or a['max_label_end']<=a['fit_cutoff'] for a in fits)
    t=ET.parse(OUT/'tests.junit.xml').getroot()
    assert sum(int(x.attrib.get('failures',0))+int(x.attrib.get('errors',0)) for x in t.iter('testsuite'))==0
    test_count=sum(int(x.attrib.get('tests',0)) for x in t.iter('testsuite'))
    vs={r['label']:r for r in s['verification']};c=vs['candidate'];b=vs['baseline']
    empirical=all(s['gates'][n] for n in ['verification_return','verification_drawdown','cost_stress','delay_stress'])
    status='PROMISING_CHALLENGER_FOR_PARALLEL_PAPER_COMPARISON' if empirical else 'RETAIN_BASELINE_NO_SUPPORTED_REPLACEMENT'
    names=['growth','profitability','valuation','balance','momentum','risk','acceleration','p1']
    weights=dict(zip(names,s['winner']['selected_model'].get('weights',[])))
    decision={'policy_id':'RFA-FactorMix-033-Q40-Buffer8-Research-20261106','status':status,
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'production_activated':False,
        'is_current_page_P1_score':False,'source_model':s['winner']['selected_model'],
        'block_weights':weights,'portfolio':s['winner']['selected_policy'],
        'human_rules':{'target_names':5,'target_equal_weight':.2,'exit_when_rank_exceeds':8,
            'hold_survivors_inside_exit_buffer':True,'weight_rebalance_band_absolute':.05,
            'calendar':'actual Jalali quarter end +40 calendar days; explicit initial entry',
            'decision':'after close; earliest fill following session',
            'missing_slots':'cash','unfilled_orders':'explicit; modeled expiry after 5 sessions'},
        'execution_assumptions':asdict(Execution()),'nominal_initial_capital_toman':100000000,
        'verification_reused':True,'all_statistical_promotion_gates_pass':s['all_gates_pass'],
        'not_proven_superior_for_future_real_money':True,
        'next_use':'separate prospective paper contract/account alongside unchanged P1 baseline; neither created by this research run',
        'historical_scope':'existing reconstructed 254-name universe; historical receipt time unproven; fractional adjusted units and assumed dividend reinvestment',
        'protocol_sha256':sha(OUT/'protocol.locked.json'),'selection_sha256':sha(OUT/'selection_all.csv'),
        'score_file':str(OUT/'score_cache'/f"{s['winner']['selected_model']['id']}.npz"),
        'summary_sha256':sha(OUT/'summary.json')}
    dump(OUT/'research_decision.json',decision)
    labels={'growth':'رشد سطح عملکرد','profitability':'سودآوری و کیفیت سود','valuation':'ارزش‌گذاری',
            'balance':'ترازنامه و ثبات','momentum':'مومنتوم و روند قیمت','risk':'نوسان کمتر و برگشت کوتاه‌مدت',
            'acceleration':'شتاب تغییر فروش، سود و حاشیه','p1':'امتیاز P1 قبلی'}
    wtable='\n'.join(f'| {labels[n]} | {weights[n]*100:.2f}٪ |' for n in sorted(weights,key=weights.get,reverse=True))
    stress=pd.read_csv(OUT/'stress.csv');stable=pd.read_csv(OUT/'stability_results.csv')
    stress_rows=[]
    titles={'fee1pct_slip03pct':'کارمزد ۱٪ و لغزش ۰٫۳٪ در هر طرف','delay3sessions':'اجرای ۳ جلسه دیرتر',
            'capacity1pct':'سقف ۱٪ ارزش معاملات','order_life10':'مهلت سفارش ۱۰ جلسه','fresh_price1':'حداکثر سن قیمت یک روز'}
    for case,title in titles.items():
        x=stress[stress['case'].eq(case)].set_index('label')
        stress_rows.append(f"| {title} | {pct(x.loc['candidate','total_return'])} | {pct(x.loc['baseline','total_return'])} |")
    stable_table=[]
    for case,title in [('offset_35','چرخش روز ۳۵'),('offset_45','چرخش روز ۴۵'),('rounded_weights_5pct','گردکردن وزن‌ها به مضرب ۵٪'),
                       ('capital_1e+09','سرمایهٔ یک میلیارد تومان'),('capital_1e+10','سرمایهٔ ده میلیارد تومان')]:
        x=stable[stable['case'].eq(case)].iloc[0]
        stable_table.append(f"| {title} | {pct(x.total_return)} | {pct(abs(x.max_drawdown))} |")
    ci=s['paired_bootstrap']['ci95_relative_wealth']
    full=[]
    for label in ['candidate','baseline']:
        x=pd.read_csv(OUT/f'full_{label}_nav.csv');v=x.nav_toman.to_numpy()
        full.append((money(v[-1]),pct(v[-1]/1e8-1)))
    fallback=sum(x['fallback'] for x in fits)
    text=f'''# نتیجه جست‌وجوی گسترده ویژگی و مدل برای RFA

۶ نوامبر ۲۰۲۶

با گسترش آزمون از قواعد سبد به خودِ مدل رتبه‌بندی، یک نامزد با بازده تاریخی بهتر پیدا شد. نامزد منتخب در دورهٔ بازبینی ۲۰۲۵ تا ۲۴ فوریهٔ ۲۰۲۶، بازده {pct(c['total_return'])} در برابر {pct(b['total_return'])} مبنا داشت و افت کمتری ثبت کرد. نتیجهٔ این دور، انتخاب آن برای مقایسهٔ کاغذیِ آینده در کنار مبنا است. برتری برای آینده و پول واقعی هنوز اثبات نشده است. این مدل جدید روی صفحه یا حساب عملیاتی اعمال نشده است.

## تفاوت با بررسی قبلی

بررسی قبلی عمدتاً موتور ثابت P1 را نگه می‌داشت و تعداد سهم، تقویم و قواعد سبد را تغییر می‌داد. این دور شامل حذف عامل، تغییر وزن، ساخت مشتق‌های مالی و قیمت و آموزش مدل پیش‌بینی رتبهٔ بازده است. بنابراین نتیجهٔ قبلی به معنی نبود هر نوع استراتژی بهتر نبود.

۲۱۲ تعریف مدل با ۱۴ سیاست سبد ترکیب شدند و {s['selection_portfolio_runs']:,} اجرای انتخاب به دست آمد: یک مرجع P1، ۲۷ حذف یا تغییر وزن عوامل منبع، ۱۴۸ مدل بلوکی و ترکیب وزن، و ۳۶ مدل یادگیرنده. نامزد منتخب از خانوادهٔ ترکیب عوامل بود، نه پیچیده‌ترین مدل درختی. ۲۲۲ اجرای حساسیت اضافی هم پس از انتخاب انجام شد و انتخاب را تغییر نداد.

## نتیجه با سرمایه تازه و هزینه اجرا

بازهٔ مشترک از ۱ ژانویهٔ ۲۰۲۵ تا ۲۴ فوریهٔ ۲۰۲۶، با سرمایهٔ اولیهٔ ۱۰۰ میلیون تومان است. همهٔ اعداد بازپخش تاریخی و اسمی به تومان‌اند؛ تورم و تغییر نرخ ارز تعدیل نشده‌اند.

| شاخص | مدل جدید | P1 مبنا |
|---|---:|---:|
| ارزش نهایی میلیون تومان | {money(c['final_toman'])} | {money(b['final_toman'])} |
| بازده کل دوره | {pct(c['total_return'])} | {pct(b['total_return'])} |
| بیشترین افت | {pct(abs(c['max_drawdown']))} | {pct(abs(b['max_drawdown']))} |
| تعداد معاملات پرشدهٔ شبیه‌سازی‌شده | {c['n_trades']} | {b['n_trades']} |

اختلاف بازده حدود {(c['total_return']-b['total_return'])*100:.1f} واحد درصد است؛ نسبت ثروت نهایی حدود {s['paired_bootstrap']['observed_relative_wealth']:.3f} برابر مبناست. این اعداد مربوط به حدود ۱۴ ماه هستند و پیش‌بینی سود سالانه نیستند.

در ۲۴ شروع ماهانهٔ مختلف در سال‌های ۲۰۲۳ و ۲۰۲۴، تا پایان مشترک فوریهٔ ۲۰۲۶، نامزد منتخب در {s['monthly_start_wins']} مورد بازده بیشتری داشت. این مسیرها هم‌پوشانی دارند و ۲۴ شاهد مستقل محسوب نمی‌شوند.

در بازپخش کل مسیر ۱ ژانویهٔ ۲۰۲۲ تا ۲۴ فوریهٔ ۲۰۲۶، ارزش نهایی نامزد {full[0][0]} و مبنا {full[1][0]} میلیون تومان است. بخش بزرگی از این مسیر در انتخاب دخالت داشته؛ این اعداد فقط توصیف تاریخی‌اند و شاهد تازهٔ تأیید نیستند.

## مدل منتخب و قواعد آن

امتیاز جدید ترکیب وزن‌دارِ رتبه‌های مقطعی هشت بلوک زیر است. مقادیر هر عامل فقط از اطلاعات تا تاریخ تصمیم ساخته می‌شوند؛ دادهٔ ناموجود مقدار خنثی می‌گیرد. این امتیاز، درصد سود پیش‌بینی‌شده نیست و با ستون P1 فعلی صفحه یکسان نیست.

| بلوک | وزن دقیق گزارش‌شده تا دو رقم اعشار |
|---|---:|
{wtable}

بلوک شتاب، اختلاف رشد فروش سه‌ماهه و دوازده‌ماهه و تغییرات ۹۰روزهٔ رشد فروش، رشد سود و روند حاشیه را ترکیب می‌کند. این «شتاب» است، نه غافلگیری نسبت به پیش‌بینی تحلیل‌گران. بلوک روند از مومنتوم ۶۳جلسه‌ای، مومنتوم ۱۲۶جلسه‌ای با حذف ماه اخیر، فاصله از سقف و نسبت میانگین‌های ۵۰ و ۲۰۰ جلسه ساخته می‌شود. بلوک ریسک، نوسان، نوسان نزولی و برگشت کوتاه‌مدت قیمت را ترکیب می‌کند. تعریف دقیق همهٔ بلوک‌ها در کد و فهرست ویژگی‌ها موجود است.

قواعد سبد منتخب:

۱. در شروع، پنج نماد بالای رتبه‌بندی جدید با بودجهٔ مساوی هدف قرار می‌گیرند. نمادهای فاقد شرایط تازگی یا پوشش داده وارد نمی‌شوند و کسری سبد نقد می‌ماند.

۲. بازبینی در اولین جلسهٔ بازار در یا پس از ۴۰ روز از پایان فصل شمسی انجام می‌شود. تصمیم بعد از بسته‌شدن بازار و نخستین اجرای مجاز در جلسهٔ بعد است.

۳. سهم نگهداری‌شده تا وقتی رتبه‌اش ۸ یا بهتر است حفظ می‌شود. پس از خروج، جای خالی از بالاترین رتبه‌های موجود پر می‌شود. این بافر، فروش و خرید ناشی از جابه‌جایی کوچک رتبه را کم می‌کند.

۴. هدف وزن هر نماد ۲۰٪ است، ولی در بازبینی فقط انحراف بیش از ۵ واحد درصد موجب هم‌وزن‌سازی می‌شود. این یک باند بازتنظیم در روز بازبینی است و سقف تضمین‌شدهٔ وزن در فاصلهٔ دو بازبینی نیست.

۵. کارمزد پایه ۰٫۵٪ و لغزش ۰٫۱٪ هر طرف، سقف مشارکت ۵٪ میانهٔ ارزش معاملات قبلی و مهلت پنج‌جلسه‌ای سفارش، همان فرض‌های شبیه‌ساز قبلی‌اند. رکورد تک‌قیمتی به عنوان پرشدن سفارش فرض نمی‌شود. این‌ها تقریب اجرای روزانه‌اند، نه مدرک صف یا تعرفهٔ واقعی کارگزار.

## هزینه و حساسیت

| سناریو | بازده نامزد | بازده مبنا |
|---|---:|---:|
{chr(10).join(stress_rows)}

در ۱۰۰ تغییر ضربی وزن با پراکندگی لگاریتمی ۰٫۱۰، {st['perturbations']['0.1']['wins']} حالت از مبنا بهتر ماند. در پراکندگی ۰٫۲۵، {st['perturbations']['0.25']['wins']} حالت بهتر بود. این یعنی نتیجه به رقم‌های بسیار دقیق وزن‌ها محدود نیست، اما تمام این آزمون‌ها روی همان تاریخچه‌اند و تأیید مستقل نیستند.

| آزمون تشخیصی پس از انتخاب | بازده نامزد | بیشترین افت |
|---|---:|---:|
{chr(10).join(stable_table)}

گردکردن وزن‌ها و تغییر روز چرخش صرفاً تشخیصی است و برای بازانتخاب برنده استفاده نشد. حذف بلوک مومنتوم یا شتاب، بازده دوره را به حدود ۲۷٪ کاهش داد؛ حذف بعضی بلوک‌های کم‌وزن، سبد این دوره را تغییر نداد. حذف سودآوری در همین دوره نتیجهٔ بهتری داشت، اما به دلیل مشاهدهٔ پس از نتیجه، آن نسخه جایگزین نامزد قفل‌شده نشد.

برتری در سرمایهٔ حدود یک میلیارد هم در این شبیه‌سازی حفظ شد. در ده میلیارد تومان، محدودیت حجم نتیجه را برعکس می‌کند: بازده نامزد حدود ۶٫۱٪ و مبنا حدود ۱۰٫۸٪ است. بنابراین نتیجه به اندازهٔ سرمایه وابسته است. حذف سهم سودساز اصلی نیز می‌تواند بخشی از برتری را از بین ببرد؛ سبد پنج‌سهمی همچنان متمرکز است.

## آموزش زمانی و معنای آماری نتیجه

بانک ورودی شامل ۴۴ عامل و مشتق و ۲۱ علامت فقدان داده است. مدل‌های Ridge، Elastic Net و درخت‌های تقویتی با افق ۶۳ و ۱۲۶ جلسه، هر ژانویه و ژوئیه بازآموزی شدند. هر برچسب فقط زمانی مجاز بود که کل بازده آیندهٔ آن تا روز آموزش محقق شده باشد. برای {s['fit_audit_records']} ثبت بازهٔ آموزش، این شرط کنترل شد. در {fallback} بازهٔ آغازین، نمونهٔ کافی نبود و طبق قاعدهٔ ازپیش‌ثبت‌شده از P1 استفاده شد؛ این موارد در لاگ جدا آمده‌اند.

انتخاب مدل و سیاست با داده‌های تا پایان ۲۰۲۴، چهار پنجرهٔ نیم‌سالهٔ ۲۰۲۳ و ۲۰۲۴، بازده نسبی، پایداری و محدودیت افت انجام شد. نامزد پیش از محاسبهٔ نتیجهٔ این دور برای بازهٔ ۲۰۲۵ تا فوریهٔ ۲۰۲۶ در فایل ثبت شد. اما همان بازه در مراحل قبلی پروژه دیده شده بود؛ بنابراین عبارت «دادهٔ آیندهٔ دست‌نخورده» دربارهٔ آن درست نیست.

بازنمونه‌گیری بلوکی ۳۰۰۰باره، فاصلهٔ ۹۵٪ نسبت ثروت نامزد به مبنا را تقریباً بین {ci[0]:.2f} و {ci[1]:.2f} قرار داد. این فاصله ۱ را در بر می‌گیرد. پس بازده و افت مشاهده‌شده بهترند، اما برتری آماری قطعی تأیید نمی‌شود. این فاصله نیز مشروط به سیاست منتخب است و اثر کل جست‌وجوی چند هزار حالت یا مواجههٔ قبلی با تاریخچه را حذف نمی‌کند.

دادهٔ مالی همچنان بازسازی تاریخی است و زمان دریافت واقعی در گذشته اثبات نشده؛ جهان ۲۵۴ نمادی ثابت است و خطر سوگیری بقا دارد؛ حسابداری واحد شاخص تعدیل‌شده، سرمایه‌گذاری فوری سود نقدی را فرض می‌کند؛ و دادهٔ روزانه اولویت صف را اثبات نمی‌کند. هیچ افزایش تعداد آزمون روی همین تاریخچه این محدودیت‌ها را برطرف نمی‌کند.

## تصمیم این دور

این دور، نامزد بهتری از نظر بازده تاریخی و افت پیدا کرد؛ بنابراین نسخهٔ قدیمی را نباید «بهترین استراتژی ممکن» نامید. انتخاب تحقیقاتی من، نگه‌داشتن مدل جدید با وزن‌ها و قواعد قفل‌شده برای مقایسهٔ کاغذیِ آینده، در کنار P1 ثابت به عنوان کنترل است. نتیجهٔ آن مقایسه باید از snapshotهای واقعاً زمان‌دار و پرشدن یا پرنشدن ثبت‌شدهٔ سفارش به دست آید. هنوز ادعای نسخهٔ نهاییِ اثبات‌شده برای سرمایهٔ واقعی نداریم.

هیچ صفحه، وزن عملیاتی، قرارداد حساب یا سفارش واقعی تغییر نکرده است. قرارداد حساب موجود P1/O00 نیز متعلق به سیاست متفاوت است و برای این مدل نباید بی‌صدا استفاده شود.

## شواهد و بازتولید

- {link('research_decision.json','نسخه و تصمیم تحقیقاتی قفل‌شده')}
- {link('selection_all.csv','تمام ۲۹۶۸ نتیجهٔ انتخاب')}
- {link('chosen.before_reused_verification.json','ثبت انتخاب قبل از بازبینی نتیجهٔ این دور')}
- {link('feature_inventory.csv','فهرست ۶۵ ورودی')}
- {link('feature_ic_training_summary.csv','ارتباط تک‌عامل‌ها با بازده در دادهٔ آموزشی')}
- {link('fit_audits.json','بازه‌های آموزش و آخرین برچسب مجاز')}
- {link('stress.csv','آزمون هزینه و اجرا')}
- {link('stability_results.csv','آزمون وزن، سرمایه و حذف عامل یا سهم')}
- {link('monthly_starts.csv','مقایسهٔ تاریخ‌های شروع')}
- {link('comparison.png','نمودار مقایسهٔ نامزد و مبنا')}

{test_count} آزمون جدید برای علیت ویژگی‌های قیمت، تبدیل رتبه، حذف برچسب محقق‌نشده، منطق قیمت ورود و تفکیک ورودی‌ها گذشت. راهنمای بازتولید در README همین پوشه است. منبع روش‌شناسی برای سوگیری انتخاب و آزمون‌های متعدد: [Bailey و López de Prado](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
'''
    (HERE/'REPORT.fa.md').write_text(text,encoding='utf8')
    chart()
    packages={}
    for name in ['numpy','pandas','scipy','sklearn']:
        mod=__import__(name);packages[name]=mod.__version__
    inventory={'created_at_utc':datetime.now(timezone.utc).isoformat(),'python_version':platform.python_version(),
        'packages':packages,'status':status,'new_tests_passed':test_count,
        'files':[dict(path=str(p.relative_to(HERE)),sha256=sha(p),bytes=p.stat().st_size)
            for p in sorted(HERE.rglob('*')) if p.is_file() and p.suffix in ['.py','.md','.json','.npz','.csv','.xml','.png']
            and '__pycache__' not in p.parts and p.name!='delivery_manifest.json']}
    dump(OUT/'delivery_manifest.json',inventory)
    print(json.dumps({'report':str(HERE/'REPORT.fa.md'),'decision':str(OUT/'research_decision.json'),
                      'status':status,'files':len(inventory['files']),'new_tests':test_count},indent=2))


if __name__=='__main__':main()
