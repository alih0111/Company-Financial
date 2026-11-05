"""Reporting-only delivery and independent integrity checks; no portfolio search."""
import datetime as dt
import html
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from .common import ROOT,SOURCE,read,write,sha,code,done

def mdtable(d,columns):
    def fmt(v):
        if pd.isna(v):return 'نامعلوم'
        return f'{v:,.4f}' if isinstance(v,(float,np.floating)) else str(v)
    return '| '+' | '.join(columns)+' |\n| '+' | '.join(['---']*len(columns))+' |\n'+''.join('| '+' | '.join(fmt(r[c]) for c in columns)+' |\n' for r in d.to_dict('records'))

def comparison(out):
    d=pd.read_csv(out/'same_period_100m_comparison.csv');extra=[];effects=[]
    for name in ['balanced_control','existing_choose','S2_P0','S2_P3','S1_P3']:
        eid='eval_'+name if name in ('balanced_control','existing_choose') else 'eval_fixed_'+name
        old=read(SOURCE/'results'/f'{eid}.json')['summary']
        new=d[d.method.eq(name)&d.data_package.eq('D1')].iloc[0]
        extra.append({**old,'method':name,'data_package':'D0','accounting_status':'adjusted_index_proxy_not_economic_wealth'})
        effects.append({'method':name,'D0_final_toman':old['final_toman'],'D1_final_toman':new.final_toman,
            'price_revision_effect_toman':new.final_toman-old['final_toman'],'start':old['start'],'end':old['end']})
    augmented=pd.concat([d[d.data_package.eq('D1')],pd.DataFrame(extra)],ignore_index=True)
    augmented.to_csv(out/'same_period_all_source_controls.csv',index=False)
    pd.DataFrame(effects).to_csv(out/'price_revision_effect_all_methods.csv',index=False)
    return augmented

def final(out):
    if (out/'delivery_manifest.json').exists():return verify(out)
    for stage in ['A','C','MONTHLY','D','E','STRESS','B']:assert done(out,stage),stage
    assert read(out/'financial_code_freeze.json')==code()
    from .ranking import emit
    ranking=emit(out);comp=comparison(out);gates=pd.read_csv(out/'acceptance.csv')
    selected=read(out/'research_decision.json');protocol=read(out/'selection_protocol.json')
    status=pd.read_csv(out/'configuration_status.csv');gap=pd.read_csv(out/'market_gap_diagnosis.csv')
    revisions=pd.read_csv(out/'price_row_revisions.csv');queue=pd.read_csv(out/'source_queue_reconciled.csv')
    terminal=pd.read_csv(out/'terminal_valuation.csv')
    old=comp[comp.data_package.eq('D1') & ~comp.method.eq('old_choices_counterfactual')].copy()
    new=read(out/'results/new_selector.json')['summary']
    old=pd.concat([old,pd.DataFrame([{**new,'method':'new_selector','data_package':'D1'}])],ignore_index=True)
    old['book_final_million_toman']=old.final_toman/1e6;old['net_return_percent']=100*(old.final_toman/1e8-1)
    old['max_drawdown_percent']=old.max_drawdown*100
    old.to_csv(out/'machine_comparison.csv',index=False)
    ablation=[]
    for name in ['balanced_control','existing_choose']:
        row=comp[comp.method.eq(name)&comp.data_package.eq('D0')].iloc[0]
        changed=comp[comp.method.eq(name)&comp.data_package.eq('D1')].iloc[0]
        for stage,val,reason in [
            ('D0_frozen_V2',row.final_toman,'inherited fixed source, not a new run'),
            ('D1_provider_revision',changed.final_toman,'same dates/actions/formula; selector reselected from past'),
            ('same_period_fundamental_coverage',changed.final_toman,'no new financial-statement version admitted; three monthly bodies do not change S2'),
            ('official_calendar',None,'blocked: complete dated official calendar/order validity unproved; inferred evidence kept separately'),
            ('economic_ledger',None,'partial modeled raw-share components; unresolved entitlements prevent total wealth attribution')]:
            ablation.append({'method':name,'stage':stage,'comparable_book_final_toman':val,'status':'measured' if val is not None else 'conditional_unknown','reason':reason})
    pd.DataFrame(ablation).to_csv(out/'ablation_comparison.csv',index=False)
    blockers=[
        {'blocker':'economic_entitlement_settlement','effect':'economic NAV, liquid cash and full return cannot be certified',
         'needed':'dated dividend entitlement/confirmed receipts; funding/bonus tradability; rights conversion notices for economic_event_coverage.csv',
         'action':'provide original dated Codal/CSDI/issuer records with report identifiers; rerun with a new explicit V3 run ID'},
        {'blocker':'official_market_calendar_and_status','effect':'global closure vs security halt cause stays unknown; session/TTL stress is modeled',
         'needed':'dated official exchange open/closed calendar and instrument halt/reopen notices',
         'action':'archive original notices; historical API probes returned404, not a proof that evidence does not exist'},
        {'blocker':'D2_event_and_lifecycle_completeness','effect':'price tail through Oct14 not admitted as an economically valid performance extension',
         'needed':'new adjustment/economic source records, historical identity/lifecycle and eligible publication inventory',
         'action':'admit a versioned complete bundle in a new run; do not splice price tail into old factors'},
        {'blocker':'monthly_sales_six_versions','effect':'F5 both policies not_tested',
         'needed':'same-scope six dated monthly amounts (last3 and same3 prior year), complete sources and units',
         'action':'three successfully parsed original V4 amounts are retained in monthly_sources.json; complete chains before another registered trial'},
        {'blocker':'current_financial_publication_completeness','effect':'ranking is dated historical output, no today claim',
         'needed':'current dated original financial versions and a complete latest-publication inventory',
         'action':'reconcile source_queue_reconciled.csv; metadata feed ending Oct7 cannot certify Oct14 completeness'}]
    pd.DataFrame(blockers).to_csv(out/'blockers.csv',index=False)
    # Per-period and per-symbol trace files already contain actual fills, reasons and quantities.
    trace=[]
    for eid in ['D1_eval_balanced_control','D1_eval_existing_choose','new_selector']:
        o=pd.read_csv(out/'results'/f'{eid}.orders.csv')
        for reason,count in o.groupby(['side','last_reason']).size().items():
            trace.append({'method':eid,'side':reason[0],'reason':reason[1],'orders':int(count)})
    pd.DataFrame(trace).to_csv(out/'order_exit_reasons.csv',index=False)
    from ranking_research.strategy_search.registry import read_jsonl
    records,_=read_jsonl(out/'experiments.jsonl');complete=[r for r in records if r['status']=='complete']
    count={'registered_main_variants':12,'tested_main_variants':int(status.status.eq('tested').sum()),
        'not_tested_main_variants':int(status.status.eq('not_tested').sum()),'successful_index_portfolio_executions':len(complete),
        'failed_index_attempts':sum(r['status']=='failed' for r in records),'raw_share_diagnostics':len(terminal),
        'twenty_inferred_session_exit_diagnostics':len(terminal),'independent_holdout':False}
    write(out/'execution_counts.json',count)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,5))
    for eid,label in [('D1_eval_balanced_control','balanced'),('D1_eval_existing_choose','V2 selector'),('new_selector','V3 selector')]:
        nav=pd.read_csv(out/'results'/f'{eid}.nav.csv');ax.plot(pd.to_datetime(nav.date),nav.nav_rial/1e7,label=label)
    ax.set_ylabel('Book value, million toman');ax.grid(alpha=.2);ax.legend();fig.tight_layout();fig.savefig(out/'evaluation_paths.png',dpi=160);plt.close(fig)
    report=(f'# نتیجهٔ پژوهش V3 و صفحهٔ رتبه‌بندی S2\n\n'
        f'نتیجه: **{selected["result"]}**. تغییر روش بدون احراز دو مرجع و دفتر اقتصادی ارتقا نمی‌یابد. '
        'این چرخه گذشته‌نگر است و آزمون مستقلِ ندیده ندارد.\n\n'
        'سرمایهٔ اولیه۱۰۰میلیون تومان؛ بازهٔ دقیق2024-11-02 تا2026-04-29. اعداد زیر ارزش دفتری شاخص تعدیل‌شده‌اند، نه وجه قابل‌برداشت. واحد محاسبات ریال و واحد نمایش تومان است.\n\n'
        +mdtable(old,['method','start','end','book_final_million_toman','net_return_percent','max_drawdown_percent'])+
        '\nاصلاح نسخهٔ ارائه‌دهنده و بازانتخاب زمانی، مزیت قبلی را به‌زور تغییر نداده‌اند. انتخابگر قبلی روی دادهٔ اصلاح‌شده از گذشته بازانتخاب شد؛ '
        f'انتخاب‌ها: `{protocol["old_selector_choices"]}`. پخش انتخاب‌های منجمد، counterfactual جداست. '
        'دو انتخابگر یکسان V2 با برابری مسیر و دو هش در old_selector_identity.json فقط یک شاهد شمرده شده‌اند.\n\n'
        '## قیمت و پوشش منابع\n\n'
        f'{len(gap)} هویت ورقه، {len(revisions)} اختلاف ستون مصرف‌شده در {len(revisions[["symbol","date"]].drop_duplicates())} ردیف ثبت شد. '
        f'تعداد معاملهٔ مثبت پس از۲۵فوریه تا۲۹آوریل در دریافت جدید: {int(gap.positive_trade_count.sum())}. '
        'توافق دو نسخهٔ رسمی قیمت، مدرک اطلاعیهٔ توقف نیست؛ علت در market_gap_diagnosis.csv نامعلوم حفظ شده است. '
        'آرشیو قدیمی تغییر نکرد. D1 فقط هم‌پوشانی را اصلاح می‌کند و ردیفِ فقط‌قدیمی را با قرارداد صریح نگه می‌دارد. '
        'D2 به علت نبود زنجیرهٔ کامل رویداد، هویت و تقویم وارد بازده نشده؛ انتهای دلخواه برای افزایش بلوک‌ها انتخاب نشده است. '
        'بازهٔ مشترکِ کاملاً تأییدشده از نظر اقتصادی به دست نیامد. ادامهٔ تاریخی قیمت، tail تشخیصی است، نه holdout.\n\n'
        f'صف فعلی: `{queue.status.value_counts().to_dict()}`. ۴۲۰۱ اتصال موجودِ دقیق شرکت/دوره/انتشار، وضعیت قدیمی صف را روشن کرد. '
        '۷۲۹۷ نسخهٔ صورت مالی قبلی، با سه بدنهٔ فروش ماهانهٔ تازه یکی شمرده نشده‌اند. سه بدنه با شناسه، دوره، زمان انتشار، ستون دقیق یک‌ماهه و واحد میلیون ریال تطبیق یافتند؛ '
        'سری شش‌نسخه‌ای کافی برای S5 نداریم. مقدار تجمعی به‌جای فروش ماهانه مصرف نشد. '
        'دو probe اولیه به مسیر نادرست404 دادند. مسیر اصلاح‌شدهٔ MarketData/GetInstrumentState پاسخ۲۰۰ داد، ولی تاریخ و InsCode صفر و عنوان وضعیت تهی داشت؛ '
        'این پاسخ برای نسبت‌دادن وضعیت به ورقه/روز معتبر نیست. بدنه و هش هر دو تلاش در official_status_route_check محفوظ است؛ '
        'فقدان اطلاعیه یا علت توقف از این پاسخ‌ها استنتاج نشده است.\n\n'
        '## شبکهٔ محدود و انتخاب زمانی\n\n'
        +mdtable(status,['configuration','status','usable_dates','reason'])+
        '\nF2 از نسخه‌های دقیقِ همان منابع، فصل قبل، هم‌فصل سال قبل و میانگین دارایی همان فصل بازسازی شد؛ '
        'ابتدا بازتولید S2 فصل جاری لازم است. وقفهٔ دو تصمیم به‌جای دو فصل استفاده نشد. '
        'F0 تاF5 فقطP0/P3؛ وزن اضافه، سیاست تازه یا جایگزین برای فرضیهٔ فاقد پوشش ساخته نشد. '
        'طبیعی و اشتراکِ جداگانهٔ F0 با هر تغییر، با رتبه‌بندی مجدد، در variant_comparison.csv هستند. '
        'S0، S2، رشد سود ساده، مومنتوم و هم‌وزن کل جامعه با هزینه/اجرای مشترک حفظ شدند. '
        'آموزش۲۴/انتخاب۶/ارزیابی۶ماه، سه بلوک کامل و یک حساب پیوسته با حمل موقعیت و سفارش اجرا شد. '
        'انتخاب ثابتِ برندهٔ کل تاریخ از انتخابگر زمانی مستقل گزارش شده است؛ نتیجهٔ بیرونی برای افزودن وزن به همین آزمایش استفاده نشد.\n\n'
        +mdtable(gates,['reference','relative_wealth','wins','blocks','without_best_log_advantage','extra_drawdown','combined_advantage_toman','book_research_gate_passed'])+
        '\nهزینهٔ دوبرابر، تأخیر۲جلسه، ظرفیت نصف، ترکیب و۵۰۰میلیون دوباره شبیه‌سازی شدند؛ سرمایه۵برابر با ضرب خروجی ساخته نشد. '
        'تنش می‌تواند تصادفاً سود بیشتری بسازد؛ فایل fills/orders و order_exit_reasons.csv تفاوت اجرا را حفظ می‌کنند. '
        'حساسیت منفعتِ ضرایب نامعلوم جداست و حسابداری سود/حق‌تقدم را اثبات نمی‌کند. '
        'با سه بلوک و آزمون‌های متعدد فاصلهٔ اطمینان مستقل یا بهترین روش ممکن ادعا نمی‌شود. '
        'مرجع محدودیت انتخاب: [Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).\n\n'
        '## دفتر سهم خام و خروج\n\n'
        +mdtable(terminal,['method','known_modeled_component_toman','certified_final_toman','modeled_settled_cash_toman','sale_receivables_toman','unmeasured_events','economic_certified'])+
        '\nاجزای جدولِ سهم خام با شاخص تعدیل‌شده جمع یا تفریق نمی‌شوند. محاسبهٔ سهم واقعی بر تصمیم‌های ثبت‌شده و اندازه‌گذاریِ جزء معلوم انجام شده؛ '
        'با نبود شروط استحقاق/تسویه، ثروت اقتصادی کل و بازده اقتصادی/سالانه نامعلوم‌اند. سود نقدی مجهول صفر نشده، '
        'حق‌تقدم پول بیرونی یا نقد منفی ایجاد نمی‌کند و سهم جایزه قبل از تاریخ مستند قابل‌معامله نمی‌شود. '
        'هویت روزانهٔ جزء معلوم کنترل شده؛ هویت حسابداری به‌تنهایی کفایت سند را ثابت نمی‌کند. کارمزد۰٫۵٪ هرطرف و تسویهT+2 بر تقویم استنباطی سناریو هستند. '
        'وجوه قابل‌برداشت واقعی نامعلوم و از نقد مدل‌شده جداست. پایان اصلی فروش اجباری ندارد. '
        'liquidation_scenario.csv سناریوی جداگانه۲۰جلسهٔ استنباطی پس از پایان، فروش ظرفیت‌محدود، وجه وصول‌شده، مطالبه و باقی‌مانده را نشان می‌دهد؛ '
        'تعداد سهم ممکن است به رویداد نامعلوم وابسته باشد و نتیجه بازده۲۹آوریل یا تضمین نقدشوندگی نیست. '
        'تقویم رسمیِ کامل و اعتبار سفارش مسدودند؛ اثر مستقل تقویم و دفتر در ablation_comparison.csv نامعلوم ثبت شده است.\n\n'
        '## رتبه‌بندی قابل‌مشاهده\n\n'
        f'صفحهٔ فرانت: `/ranking/research`، منو «رتبه‌بندی پژوهشی S2». تاریخ فهرست **{ranking.get("as_of","نامعلوم")}**؛ '
        f'{len(ranking["rows"])} نماد از {ranking.get("eligible_count",0)} نامزد واجدشرایط. '
        'این خروجی امروز نیست؛ دریافت قیمت۱۴اکتبر به‌تنهایی تازگی بنیاد آن روز را احراز نمی‌کند. '
        'همان تابع امتیازدهی F0/S2 بک‌تست مصرف شده؛ امتیاز درصد سود موردانتظار یا احتمال موفقیت نیست. '
        'نام، دو دلیل، تاریخ و وضعیت کفایت در صفحه و ویژگی‌ها/منشأ کامل در ranking_audit.json هستند. '
        'رتبه‌بندی اصلی خودکار عوض نشده؛ صفحهٔ جدید مستقل و دارای همان محافظ ورود است. '
        'ثبت دستی مشاهدهٔ آتی پیاده شده، زمان‌بندی/کارگزاری/سفارش زنده وجود ندارد.\n\n'
        f'شمار اجراها: `{count}`. آزمون‌های اجراشده در test_evidence.json ثبت‌اند؛ تست قدیمیِ اجرا‌نشده پاس تازه معرفی نشده است. '
        'موانع و اقدام دقیق در blockers.csv؛ run و ورودی‌ها/کد و payloadها هش دارند.\n\n'
        f'![مسیر ارزش دفتری]({out.as_posix()}/evaluation_paths.png)\n\nاجرای صریح: `{out}`.\n')
    report_path=ROOT/'docs/RETURN_V3_FINAL.fa.md';report_path.write_text(report,encoding='utf8')
    (out/'RETURN_V3_FINAL.fa.md').write_text(report,encoding='utf8')
    handoff=(f'# تحویل V3\n\nاجرا: `{out}`\n\nوضعیت: مسیرهای مستقل اجرا و تحویل شدند؛ گواهی اقتصادی و تمدیدD2 به علل ردیفی blockers.csv مشروطند. '
        'فرایند مالی پس از پایان فرمان فعال نیست.\n\n'
        f'کنترل مستقل پیاده‌شده: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run verify --run "{out}"`\n\n'
        f'ادامهٔ همان کد و ورودی در صورت قطع اجرای تحویل: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run all --run "{out}"`\n\n'
        'این فرمان مسیرهای سازگار را از payload کامل برمی‌دارد؛ تغییر کد/داده شناسهٔ تازه می‌خواهد. '
        'برای دادهٔ جدید ابتدا ثبت واقعی اجرا: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.run register`. '
        'فرمان موجود به‌طور پیش‌فرض منبعV2 ثابت را مصرف می‌کند؛ parser/ورود خودکارِ بستهٔ اقتصادی جدید ادعا نشده و قبل از اجرای تازه باید پیاده و ثبت شود.\n\n'
        f'ثبت دستی مشاهدهٔ بدون سفارش برای تاریخ روز تهران: `.venv/Scripts/python.exe -B -m ranking_research.return_v3.ranking --run "{out}" --observe-date YYYY-MM-DD`. '
        'YYYY-MM-DD باید با تاریخ واقعی روز جایگزین شود؛ تاریخ رتبه و زمان مشاهده جدا ثبت می‌شوند.\n\n'
        'فرانت: `/ranking/research`؛ فایل سرو‌شده client/public/research/return-v3.json با شناسهٔ صریح همین اجرا پین شده و انتخاب خودکار آخرین پوشه نیست. '
        'خروجی تاریخی را امروز معرفی نکن. اسناد V2، کد تولید اصلی، کارگزاری و /ranking جایگزین نشده‌اند.\n')
    handoff_path=ROOT/'docs/SOL61_RETURN_V3_HANDOFF.fa.md';handoff_path.write_text(handoff,encoding='utf8')
    static=ROOT/'client/public/research/return-v3.json';static.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(out/'latest_research_ranking.json',static)
    write(out/'frontend_publication.json',{'pinned_run':out.name,'route':'/ranking/research','source':str(out/'latest_research_ranking.json'),
        'source_sha256':sha(out/'latest_research_ranking.json'),'destination':str(static),'destination_sha256':sha(static),
        'primary_ranking_replaced':False})
    excluded={'delivery_manifest.json','verification.json'}
    files={str(p.relative_to(out)).replace('\\','/'):sha(p) for p in out.rglob('*') if p.is_file() and p.name not in excluded and not p.name.startswith('verification_independent_')}
    write(out/'delivery_manifest.json',{'run_id':out.name,'files':files,'reports':{str(report_path):sha(report_path),str(handoff_path):sha(handoff_path)},
        'financial_code':code(),'portfolio_executions':len(complete),'source':str(SOURCE),'economic_certification':False})
    receipt=verify(out,initial=True);write(out/'verification.json',receipt)
    print('FINAL',receipt,flush=True)
    return receipt

def verify(out,initial=False):
    from ranking_research.strategy_search.registry import read_jsonl,artifacts_match
    manifest=read(out/'delivery_manifest.json')
    for name,digest in manifest['files'].items():assert sha(out/name)==digest,'changed artifact '+name
    for name,digest in manifest['reports'].items():assert sha(name)==digest,'changed report '+name
    assert read(out/'financial_code_freeze.json')==code(),'financial code differs'
    for name,digest in read(out/'registration.json')['source_files'].items():assert sha(name)==digest,'prior V2 source changed '+name
    for name,digest in read(out/'price_archive_manifest.json')['files'].items():assert sha(name)==digest
    records,_=read_jsonl(out/'experiments.jsonl');complete=[r for r in records if r['status']=='complete']
    for r in complete:
        assert artifacts_match(r['artifacts']),r['experiment_id']
        fills=pd.read_csv(r['artifacts']['fills']['path'])
        assert (fills.date>fills.decision_time).all(),'same-session fill'
    econ=pd.read_csv(out/'ledger_reconciliation.csv');assert econ.identity_residual_rial.abs().max()<.01
    assert econ.cash_rial.min()>=-.01
    for name in ['financial_code_freeze.json','D1_panel.parquet']:
        assert name in manifest['files']
    # Every inherited financial module was executed from copied archived bytes.
    for rel,digest in read(out/'registration.json')['frozen_v2_code'].items():assert sha(out/'frozen_v2'/rel)==digest
    from ranking_research.strategy_search.features import market_fingerprint
    symbols=pd.read_csv(SOURCE/'new_market_archive/inventory.csv').symbol.tolist()
    assert market_fingerprint(symbols)==read(SOURCE/'data_manifest.json')['market'],'D0 market archive/reference content changed'
    prior=read(out/'previous_quarter_sources.json')
    from ranking_research.strategy_search.features import HIST
    reports=Path(read(HIST/'registration.json')['inputs'])/'input_reports.json'
    assert sha(reports)==prior['input_reports_sha256'],'source financial version inputs changed'
    pub=read(out/'frontend_publication.json')
    if sha(pub['destination'])!=pub['source_sha256']:
        # UI wording has a separate immutable derivation, never a portfolio/cache mutation.
        provenance=read(ROOT/'client/public/research/return-v3.provenance.json')
        assert provenance['source_ranking_sha256']==pub['source_sha256']
        assert provenance['source_audit_sha256']==sha(out/'ranking_audit.json')
        assert sha(provenance['presentation_path'])==provenance['presentation_sha256']==sha(pub['destination'])
        source=read(out/'latest_research_ranking.json');presented=read(pub['destination'])
        assert source.keys()<=presented.keys()
        for key in source:
            if key not in ('rows','note'):assert source[key]==presented[key],key
        assert len(source['rows'])==len(presented['rows'])
        audit={r['symbol']:r['s2_raw'] for r in read(out/'ranking_audit.json')['rows']}
        for old,new in zip(source['rows'],presented['rows']):
            for key in old:
                if key!='reason1':assert old[key]==new[key],key
            value=audit[old['symbol']]
            expected='افزایش سود عملیاتی فصل نسبت به هم‌فصل سال قبل' if value>0 else 'کاهش سود عملیاتی فصل نسبت به هم‌فصل سال قبل' if value<0 else 'سود عملیاتی فصل برابر با هم‌فصل سال قبل'
            assert new['reason1']==expected
    result={'passed':True,'run_id':out.name,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'completed_index_experiments':len(complete),'source_V2_files_unchanged':True,'same_session_fill_count':0,
        'economic_ledger_identity_passed':True,'economic_certified':False,'manifest_sha256':sha(out/'delivery_manifest.json'),
        'verification_code_sha256':sha(Path(__file__)),'original_market_and_financial_inputs_unchanged':True}
    if not initial:
        write(out/('verification_independent_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'),result)
    return result
