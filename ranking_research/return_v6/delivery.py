import os
import subprocess
import sys
import json
from pathlib import Path
import pandas as pd
from .common import ROOT,V3,V4,V5,read,write,sha,utc,validate,verify_prior

def snapshot(out):
    base=read(V5/'research_snapshot.json')
    c=pd.read_csv(out/'machine_comparison.csv');fits=pd.read_csv(out/'training_cutoffs.csv')
    base.update(research_version='V6',run_id=out.name,performance_run_id=out.name,
        performance_status='S2 حفظ شده است؛ نتیجهٔ نامزدهای V6 پژوهشی است و مجوز معاملهٔ واقعی نیست.',
        freshness_note='بنیاد در مسیر واقعی آزمون از زمان انتشار مجاز استفاده می‌کند؛ تأخیر ماهانه به V5 نسبت داده نشد. گزارش تاریخی تازه‌ای تأیید نشد.',
        v6_details={'model_features':read(out/'model_contract.json')['features'],
            'coefficients':pd.read_csv(out/'model_coefficients.csv').to_dict('records'),
            'trained_blocks':int(fits.status.eq('trained').sum()),'fallback_blocks':int(fits.status.ne('trained').sum()),
            'training_note':'آموزش فقط با برچسب سررسیدشدهٔ پیش از بلوک؛ تاریخ قبلاً دیده شده است.'},
        performance=[])
    names=['S2_publication','S2_common','equal_feature_ranks','ridge_rank','existing_choose']
    for name in names:
        z=c[c.method.eq(name)]
        if not len(z):continue
        r=z.iloc[0]
        base['performance'].append({'method':name,'final_toman':float(r.final_toman),'start':str(r.start),'end':str(r.end),
            'max_drawdown_percent':abs(float(r.max_drawdown))*100,'ledger':'شاخص تعدیل‌شده؛ اقتصاد کامل نامعلوم',
            'book_cash_toman':float(r.book_cash_toman),'economic_final_toman':None})
    base['note']=(base.get('note','')+' نسخهٔ V6 روش پذیرفته‌شده و تاریخ فهرست را حفظ کرده است؛ S2 هم‌جامعه با S2 جامعهٔ طبیعی تفاوت پوشش دارد.')
    assert base['rows']==read(V5/'research_snapshot.json')['rows']
    write(out/'research_snapshot.json',base)
    write(ROOT/'client/public/research/return-v6.json',base)
    write(ROOT/'client/public/research/return-v6.provenance.json',{'run_id':out.name,'ranking_source_run':V5.name,
        'ranking_as_of':base['as_of'],'ranking_sha256':sha(V5/'research_snapshot.json'),
        'artifact_sha256':sha(out/'research_snapshot.json'),'comparison_sha256':sha(out/'machine_comparison.csv'),
        'freshness_claim':'historical published-as-of financial input, not latest publications of entire market',
        'accepted_method_changed':False})

def verify(out):
    validate(out)
    m=read(out/'delivery_manifest.json')
    for p,h in m['files'].items():
        if sha(out/p)!=h:raise ValueError('V6 artifact changed: '+p)
    for p,h in m['external_artifacts'].items():
        if sha(p)!=h:raise ValueError('Published V6 artifact changed: '+p)
    return True

def finish(out):
    snapshot(out)
    env={**os.environ,'RETURN_V6_RUN':str(out),'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    commands=[('python_tests',[sys.executable,'-B','-m','unittest','ranking_research.tests.test_return_v6','-v'],ROOT),
        ('frontend_states',['node','scripts/verify-research-v6.mjs',str(out)],ROOT/'client'),
        ('production_build',['npm.cmd','run','build'],ROOT/'client')]
    evidence={'checked_at':utc(),'checks':{},'V5_read_only_verified':verify_prior()}
    for name,cmd,cwd in commands:
        log=out/(name+'.log')
        with log.open('w',encoding='utf8') as stream:
            r=subprocess.run(cmd,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT)
        evidence['checks'][name]={'passed':r.returncode==0,'returncode':r.returncode,'command':cmd,'log_sha256':sha(log)}
        write(out/'test_evidence.json',evidence)
        print(name,'passed' if r.returncode==0 else 'FAILED',flush=True)
        if r.returncode:raise RuntimeError('Check failed: '+name+'; see '+str(log))
    contracts=[read(p) for p in (out/'results').glob('*.contract.json')]
    counts={status:sum(c['status']==status for c in contracts) for status in ['complete','failed','running']}
    reused=pd.read_csv(out/'reused_paths.csv');fits=pd.read_csv(out/'training_cutoffs.csv');c=pd.read_csv(out/'machine_comparison.csv')
    evidence.update(passed=True,new_financial_paths=counts['complete'],failed_financial_paths=counts['failed'],
        reused_financial_paths=len(reused),running_financial_paths=counts['running'],
        branch_stress_contract_test='real shared engine, October30-November30 2024, explicit protocol and doubled costs; counted separately from full-period financial paths',
        not_run={'stress':read(out/'candidate_gate.json')['stress'],'capital500m':read(out/'candidate_gate.json')['capital500m']})
    write(out/'test_evidence.json',evidence)
    queue=pd.read_csv(out/'recovery_queue.csv');events=pd.read_csv(out/'economic_event_progress.csv')
    blockers=[{'type':'historical_report','id':r.report_id,'symbol':r.symbol,'reason':r.reason,'next_action':r.source_url} for r in queue.head(30).itertuples()]
    blockers += [{'type':'economic_event','id':r.event_id,'symbol':r.symbol,'reason':r.after,'next_action':r.missing_exact_evidence} for r in events.itertuples()]
    blockers += [{'type':'historical_industries','id':'local254','symbol':'','reason':'archived dated industry crosswalk absent','next_action':'obtain dated historical industry membership'},
        {'type':'market_gap','id':'2026-02-28..2026-05-18','symbol':'','reason':'cause unknown; endpoint not extended','next_action':'dated official market/session notice and complete adjustment/asset chain'}]
    pd.DataFrame(blockers).to_csv(out/'blockers.csv',index=False)
    comp='|روش|پایانی، میلیون تومان|افت بیشینه|\n|---|---:|---:|\n'+'\n'.join(f"|{r.method}|{r.final_toman/1e6:.4f}|{abs(r.max_drawdown)*100:.2f}٪|" for r in c.itertuples())
    gates=read(out/'candidate_gate.json');gate_text=json.dumps(gates,ensure_ascii=False,indent=2)
    report=f'''# نتیجهٔ V6

اجرا: `{out}`

S2 حفظ شد؛ نامزدها خودکار به روش پذیرفته‌شده ارتقا نیافتند. اعداد، NAV شاخصی پژوهشی با سرمایهٔ آغاز ۱۰۰ میلیون تومان، هزینهٔ ۰٫۵٪ هر سمت، تقویم استنباطی و همان قرارداد قیمت V5 هستند. بازده اقتصادی کامل نامعلوم است؛ حساب واقعی نداریم.

## یافتهٔ تازه دربارهٔ به‌موقع‌بودن

ردیابی واقعی نشان داد V5 از V4 ← V3 ← V2.events.panel_asof با join عقب‌نگر رویداد انتشار مصرف می‌کند. فایل قدیمی asof_panel تأخیر ماهانه دارد، اما این تأخیر در مسیر واقعی V5 نیست. publication_path_proof.csv تطابق منابع و S2 را سطر به سطر کنترل می‌کند. D0 و D2 ورودی یکسان دارند و خروجی موجود بازاستفاده شده؛ D1 یک خلاف‌واقعِ صریح با تأخیر ماهانه است و افت یا رشد آن اصلاح V5 محسوب نمی‌شود. publication_to_decision_lag.csv نشان می‌دهد کدام اسناد را این خلاف‌واقع نمی‌بیند. بنیاد با زمان انتشار دقیق تا پایان روز تصمیم مجاز است، سفارش از جلسهٔ بعد؛ روزِ بدون ساعت از جلسهٔ بعد مجاز است.

## بازیابی تاریخ و جامعه

صفِ {len(queue)} سند دارای انتشار/دورهٔ مشخص بر مبنای سقف تصمیم‌های مسدودشده و اتصال سند ساخته شد؛ این شمار سقف اولویت‌بندی است، نه تضمین رفع همهٔ تصمیم‌ها با یک سند. کاتالوگ و validation محلی V4 بازبینی و مسیر مستقیمِ سند دقیق با checkpoint محدود امتحان شد؛ گزارش تاریخی تازهٔ قابل‌پذیرش صفر بود. ۲۲۵ گزارش افزودهٔ V4 از ژوئیهٔ ۲۰۲۶ به بعدند و وارد دورهٔ اصلی نشدند. شرایط اعتبار شل نشد. پوشش قبل/بعد برای همهٔ موعدهای آموزشی و تصمیم، سطل‌های <=۱۰ / ۱۱..۱۹ / >=۲۰ و علل حذف در historical_coverage_before_after.csv ثبت شده است؛ جامعهٔ محلی ۲۵۴ هویت است، نه کل بازارِ بدون سوگیری بقا.

## مدل محدود

سه ویژگی ثابت: S2 مستقل، سود عملیاتی TTM/دارایی مثبت همان منبع، momentum12_1 موجود. ridge با alpha=۱ و تابع میانگین خطای وزن‌دار + مجموع مربع ضرایب، عرض از مبدأ بدون جریمه. هر ماه وزن برابر؛ حداقل۲۴تاریخ بالغ با۲۰برچسب معتبر، حداکثر۳۶ماه گذشته، سررسید برچسب۶۰جلسه‌ای قبل از cutoff. در {int(fits.status.eq('trained').sum())} بلوک آموزش و در {int(fits.status.ne('trained').sum())} بلوک fallback ازپیش‌ثبت‌شدهٔ S2 هم‌جامعه رخ داد. این تاریخ قبلاً مصرف شده و برچسب‌ها هم‌پوشان‌اند. ضرایب بدون تغییر علامت پسینی در model_coefficients.csv موجودند.

## مقایسهٔ ۱۰۰ میلیون

بازهٔ نمایش 2024-11-02 تا 2026-02-25؛ تصمیم اولیه2024-10-30. NAV کامل مسیرهای تازه، نخستین fill، هزینهٔ پیش از نمایش و سرمایهٔ آغاز جدا ثبت‌اند. دارایی و نقد در مرز بلوک ریست نمی‌شوند. مراجع رشد سود/وزن مساوی cadence ماهانهٔ قبلی دارند و فقط مرجع زمینه‌اند؛ S2/کنترل/مدل همگی دوهفته‌ای با حداکثر۱۰عضو و وزن برابرند. مرجع وزن مساوی همهٔ واجدان می‌تواند بیشتر از۱۰سهم داشته باشد.

{comp}

machine_comparison.csv گردش، هزینه، نقد، سفارش ناقص و ارزش‌گذاری کهنه را دارد؛ block_performance.csv دو بلوک کامل و انتهای ناقص را جدا می‌کند. S2_common کنترل رتبه روی همان جامعهٔ ویژگی مدل است؛ S2_publication جامعهٔ طبیعی S2 است. اختلاف این دو اثر پوشش است. D0→D1→D2 در data_ablation.csv با هش ورودی و اختلاف NAV آمده و تغییر داده بهبود فرمول نامیده نشده است.

## دروازه و محدودیت نتیجه

```json
{gate_text}
```

دروازهٔ پژوهشی با برتری نسبت به S2 هم‌داده/هم‌cadence، اکثریت بلوک‌های کامل و حد۵واحددرصد افت ثبت شد؛ برای نامزد نهایی مقایسهٔ جامعهٔ طبیعی نیز الزامی شد. تنها دو بلوک کامل داریم و شواهد ضعیف است. تشخیص تمرکز از PnL نماد و حذف بهترین بلوک محاسبه شده، بدون حذف برنده از جامعهٔ معامله. آستانهٔ عمده۱٫۱۰با انتخابگر مستقل از بهبود کوچک است؛ قاعدهٔ V5 عوض نشد. روی این داده وزن‌گردانی بیشتر انجام نمی‌دهیم.

## اقتصاد مرتبط با موجودی مرجع

سه خوشه بر اساس ارزش موجودی خام شبیه‌سازی‌شدهٔ انتخابگر و دسترسی سند انتخاب و بدنه‌های اصلی محلی خوانده شد. economic_selected_exposures.csv تاریخ و تعداد واقعیِ موجودی مدل را نگه می‌دارد. اسناد ثبت افزایش سرمایه به‌تنهایی اثبات اتصال دقیق ex-date، دارندهٔ واجد حق و معامله‌پذیری نیستند؛ هیچ اثر نقد یا سهم مجهول صفر نشد و fixture فرضی تازه جایگزین نشد. economic_event_progress.csv شناسه‌ها و سند دقیق مفقود را مشخص می‌کند. دریافت کاتالوگ ناموفق۲۶نماد تکرار نشد. بازده اقتصادی کل همچنان نامعلوم است.

## کنترل و تحویل

{counts['complete']} مسیر مالی تمام‌دورهٔ تازه، {len(reused)} مسیر مرجع بازاستفاده‌شده، {counts['failed']} مسیر مالی شکست‌خورده؛ آزمون کوچک شاخهٔ تنش انتخابگر جدا از مسیرهای تمام‌دوره اجرا شد. آزمون‌های پایتون، رندر واقعی کامپوننت در سه حالت و build در test_evidence.json ثبت‌اند. صفحهٔ /ranking/research همان صفحه است؛ فهرست S2 و تاریخ۱۴اکتبر/۱۰۱از۲۵۴ حفظ شده و به امروز نسبت داده نمی‌شود. فایل جدید V6 از V5 مستقل است. هیچ کار مالی پس از پایان فرمان در پس‌زمینه ادعا نمی‌شود.
'''
    (out/'RETURN_V6_FINAL.fa.md').write_text(report,encoding='utf8');(ROOT/'docs/RETURN_V6_FINAL.fa.md').write_text(report,encoding='utf8')
    handoff=f'''# تحویل V6

اجرا: `{out}`

گزارش: docs/RETURN_V6_FINAL.fa.md. کنترل فقط‌خواندنیِ آزموده‌شده: `.venv/Scripts/python.exe -B -m ranking_research.return_v6.run verify --run "{out}"`.

فرمان resume: همان فرمان با all؛ پس از seal فقط verify می‌کند و مالی را تکرار نمی‌کند. تغییر کد/داده به اجرای جدید نیاز دارد. V2..V5 دست‌نخورده‌اند؛ dirty git کاربر حفظ شود. V5 از قبل بنیاد مبتنی بر انتشار داشت؛ D1 خلاف‌واقع ماهانه است. D0/D2 و انتخابگر به علت ورودی یکسان بازاستفاده شدند. فرضیه/وزن تازه بدون هدف تازه اضافه نکن. candidate_gate.json، training_cutoffs.csv، data_ablation.csv و test_evidence.json را ابتدا بخوان. اقتصاد کامل نامعلوم، حساب واقعی نداریم. مرحلهٔ بعد نیازمند شواهد تاریخی/استحقاق مشخص است، نه تکرار وزن‌ها. پس از پایان کار پردازش مالی خودکار فعال ادعا نشود.
'''
    (out/'HANDOFF.fa.md').write_text(handoff,encoding='utf8');(ROOT/'docs/SOL61_RETURN_V6_HANDOFF.fa.md').write_text(handoff,encoding='utf8')
    write(out/'delivery_manifest.json',{'sealed_at':utc(),'files':{str(p.relative_to(out)).replace('\\','/'):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'},
        'external_artifacts':{str(ROOT/p):sha(ROOT/p) for p in ['client/public/research/return-v6.json','client/public/research/return-v6.provenance.json']}})
    verify(out)
