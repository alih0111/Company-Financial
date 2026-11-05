import datetime as dt
import pandas as pd
from .common import ROOT,V2,V3,V4,read,write,sha,validate

def run(out):
    comparison=pd.read_csv(out/'machine_comparison.csv')
    if (out/'candidate_comparison.csv').exists():
        comparison=pd.concat([comparison[~comparison.method.str.startswith('S2_buffer15')],pd.read_csv(out/'candidate_comparison.csv')],ignore_index=True)
        comparison.to_csv(out/'machine_comparison.csv',index=False)
    w=read(out/'evaluation_windows.json');end=w['primary_quality_end'];audit=read(out/'effective_policy_audit.json')
    primary=comparison[comparison.scope.eq('primary_quality')]
    gate=read(out/'candidate_gate.json') if (out/'candidate_gate.json').exists() else {'candidates':[]}
    diag=pd.read_csv(out/'signal_diagnostics.csv');grouped=diag.groupby(['signal','horizon_sessions']).agg(mean_rank_ic=('rank_ic','mean'),median_valid_labels=('valid_labels','median'),dates=('date','count'),mature_dates=('rank_ic','count'))
    grouped.to_csv(out/'signal_diagnostics_summary.csv')
    b=read(out/'economic_sources/checkpoint.json');events=pd.read_csv(out/'canonical_events.csv');impact=pd.read_csv(out/'unresolved_event_impact.csv')
    blocks=[]
    for r in impact.to_dict('records'):
        blocks.append({'type':'event_economics','symbol':r['symbol'],'date':r['date'],'document':r['original_event_id'],
            'work_done':'deduplicated database action; cached original capital/AGM bodies reviewed; 26 exact issuer catalog requests timed out',
            'status':'unresolved','next_action':'obtain original issuer decision and matching market entitlement/tradability notice for this canonical event'})
    blocks.extend([{'type':'price_gap_cause','symbol':'local universe 254','date':'2026-02-28..2026-05-18','document':'price_contract_audit.csv',
        'work_done':'daily 254-instrument audit + eight fresh official endpoint histories; zero-positive gap and later resumption observed',
        'status':'unknown cause; no extension admitted','next_action':'obtain dated official market/session status notice covering this gap'},
        {'type':'industry_attribution','symbol':'local universe','date':'historical','document':'archived sector crosswalk absent',
        'work_done':'symbol PnL and concentration calculated without present-day classification backfill','status':'unavailable',
        'next_action':'supply archived instrument-to-industry classification with effective dates'},
        {'type':'capital_fixture_tradability','symbol':'دارو','date':'2025-08-21','document':'codal1396415',
        'work_done':'source ratio parsed; 1892 blocked shares per hypothetical 100-share eligible same-class holder; no premature tradability',
        'status':'conditional mechanics only','next_action':'obtain market notice confirming new-share entitlement and tradability date'}])
    pd.DataFrame(blocks).to_csv(out/'blockers.csv',index=False)
    if not (out/'change_attribution.csv').exists():
        pd.DataFrame(columns=['before_method','after_method','portfolio_management_effect_toman','data_effect_toman','formula_effect_toman','economic_accounting_effect_toman']).to_csv(out/'change_attribution.csv',index=False)
    attrib=pd.read_csv(out/'change_attribution.csv');attrib=attrib[attrib.before_method.ne('V4_old_selector')]
    attrib=pd.concat([attrib,pd.DataFrame([{'before_method':'V4_old_selector','after_method':'V5_same_selector_quality_window',
        'start':'2024-11-02','end':end,'before_toman':169720521.28278625,'after_toman':float(primary[primary.method.eq('existing_choose')].iloc[0].final_toman),
        'data_effect_toman':0,'formula_effect_toman':0,'portfolio_management_effect_toman':0,'economic_accounting_effect_toman':None,
        'contract':'same unchanged holdings/account; shorter time endpoint removes stale tail, not forced sale; unknown economic difference is null'}])],ignore_index=True)
    attrib.to_csv(out/'change_attribution.csv',index=False)
    # Pin UI to this run, preserve latest snapshot date rather than silently displaying older coverage.
    snapshot=read(V4/'latest_research_ranking.json');snapshot.update(research_version='V5',run_id=out.name,
        validity_label='رتبه‌بندی پژوهشی S2؛ مقایسهٔ بازده شاخصی، دفتر اقتصادی کامل هنوز نامعلوم',
        performance_status='برندهٔ معتبر تازه مشخص نشده؛ روش S2 حفظ شده است.',
        performance_note='۱۰۰ میلیون تومان اولیه؛ هزینهٔ فرضی هر سمت ۰٫۵٪؛ تقویم استنباطی. NAV شاخصی پول قابل برداشت یا نقد آمادهٔ خرید نیست. عملکرد واقعی حساب وجود ندارد.',
        performance=[{'method':r['method'],'final_toman':r['final_toman'],'start':r['start'],'end':r['end'],
            'max_drawdown_percent':abs(r['max_drawdown'])*100,'book_cash_toman':r['book_cash_toman'],'ledger':'شاخص تعدیل‌شده',
            'economic_final_toman':None,'stale_price_weight':r['stale_price_weight']} for r in primary.to_dict('records')],
        metadata_completeness='اطلاعات گزارش‌ها با منابع منجمد V4 و ۲۲۵ نسخهٔ بازیابی‌شده تطبیق شده؛ جامعیت همهٔ اطلاعیه‌های تازه احراز نشده است.',
        economic_example='آزمون مستند پکویر: برای دارندهٔ فرضی ۱۰۰ سهم، ۵۸٬۰۰۰ ریال طلب سود ثبت شد؛ در سناریوی برنامهٔ ناشر در آخر بازهٔ پرداخت به نقد تبدیل می‌شود، و در سناریوی عدم استفادهٔ مجدد طلب باقی می‌ماند. این آزمون، بازده کل راهبرد نیست.',
        performance_run_id=out.name)
    # UI rows and all scores remain exactly the same shared S2 artifact.
    assert snapshot['rows']==read(V4/'latest_research_ranking.json')['rows']
    write(out/'research_snapshot.json',snapshot)
    write(ROOT/'client/public/research/return-v5.json',snapshot)
    write(ROOT/'client/public/research/return-v5.provenance.json',{'run_id':out.name,'artifact':str(out/'research_snapshot.json'),
        'artifact_sha256':sha(out/'research_snapshot.json'),'comparison_sha256':sha(out/'machine_comparison.csv'),
        'source_ranking_sha256':sha(V4/'latest_research_ranking.json'),'source_manifest_sha256':sha(V4/'delivery_manifest.json')})
    names={'existing_choose':'انتخابگر قبلی','balanced':'balanced','S2_monthly':'S2 ماهانه','S2_biweekly':'S2 دوهفته‌ای','profit_growth':'رشد سود','equal_weight_all':'وزن مساوی همهٔ واجدان شروط'}
    table='|روش|سرمایهٔ پایانی، میلیون تومان|افت بیشینه|\n|---|---:|---:|\n'+'\n'.join(f"|{names.get(r['method'],r['method'])}|{r['final_toman']/1e6:.4f}|{abs(r['max_drawdown'])*100:.2f}٪|" for r in primary.to_dict('records'))
    hashes=audit['identical_pair'];same=', '.join(k for k,v in hashes.items() if v['identical'])
    note=f'''# تشخیص V5 — یک صفحه

بازهٔ اصلی: 2024-11-02 تا {end}؛ گذشتهٔ مصرف‌شده، نه آزمون مستقل. افق‌های۲۰/۶۰/۱۲۰ فقط تشخیصی‌اند و برچسب‌های هم‌پوشان مستقل حساب نشده‌اند. خروجی `signal_diagnostics_summary.csv` میانگین توصیفی هم‌بستگی و تعداد برچسب‌های معتبر دارد؛ بدون p-value یا انتخاب بهترین افق.

در جفت S0/F0، هش‌های یکسان: {same}. کوچک‌شدن جامعه می‌تواند ترتیب متفاوت امتیاز را به وزن‌های مساوی یکسان تبدیل کند؛ شواهد تصمیم/سفارش/fill ثبت شده‌اند. در مقایسهٔ رشد سود، اثر رتبه در جامعهٔ مشترک از اختلاف جامعه جدا گزارش شده و اختلاف مسیرها تجزیهٔ جمع‌پذیر علّی نامیده نشده است.

برچسب P0/monthly خلاصه از policy پایهٔ outer() می‌آید؛ تقویم واقعی از policy_schedule می‌آید. همهٔ تطابق‌ها در effective_policy_audit.json ثبت‌اند؛ این نقص گزارش از روی شمارش به خطای مالی تعبیر نشده است. مرجع وزن مساوی می‌تواند بیش از۱۰ سهم داشته باشد.

مسئلهٔ قابل اصلاح محدود: بررسی گردش S2 و مرز۱۰..۱۵، بدون تغییر امتیاز. تداوم فصل و کیفیت نقد قبلاً در V3 آزمایش شده‌اند؛ تکرار بی‌دلیل نشده‌اند. طبقه‌بندی تاریخی صنایع در ورودی ثابت موجود نیست؛ سهم هر نماد، حذف تشخیصی بزرگ‌ترین سهم و بهترین بلوک محاسبه شده‌اند. حذف‌ها جامعهٔ معاملاتی جدید نمی‌سازند.
'''
    (out/'DIAGNOSTICS.fa.md').write_text(note,'utf8')
    status='؛ '.join(f"{g['method']}: {g['status']}، نسبت ثروت {g['wealth_ratio']:.4f}" for g in gate['candidates']) or 'فرض تشخیصی برای آزمایش تازه برقرار نشد.'
    report=f'''# نتیجهٔ V5

اجرای صریح: `{out}`

سه قرارداد جدا شد: بازده شاخص تعدیل‌شده؛ بازده اقتصادی شبیه‌سازی‌شده با مطالبات/نقد؛ عملکرد واقعی حساب که اکنون وجود ندارد. رسید شخصی شرط بک‌تست فرضی نیست. هیچ روش تولیدی ارتقا نیافت.

## ۱۰۰ میلیون تومان

بازهٔ اصلی {primary.iloc[0]['start']} تا {end}. اعداد جدول صرفاً NAV شاخصی پس از هزینهٔ فرضی۰٫۵٪ هر سمت، ظرفیت و تقویم استنباطی‌اند؛ نقد قابل‌برداشت نیستند. حساب‌ها میان بلوک‌ها پیوسته‌اند. انتهای آوریل برای تطبیق V4 در machine_comparison.csv جدا حفظ شده است.

{table}

دو بلوک کامل شش‌ماهه تا اکتبر۲۰۲۵ و انتهای ناقص نوامبر۲۰۲۵ تا فوریه۲۰۲۶ جدا شدند. پروتکل مرجع۲۴/۶/۶ و انتخاب‌های مبتنی بر گذشته حفظ شد. این تاریخ پیش‌تر دیده شده و holdout تازه نیست. CAGR محور نتیجه نیست.

## کیفیت قیمت

در آرشیو، بعد از2026-02-25 تا2026-05-18 معاملهٔ مثبت وجود ندارد و از2026-05-19 دوباره مشاهده می‌شود؛ این ممیزی دربارهٔ علت تعطیلی/توقف/نقص منبع حکم نمی‌دهد. هشت دریافت تازهٔ endpoint رسمی با هویت ابزار کنترل شد؛ دریافت دوبارهٔ همان منبع شاهد مستقل وضعیت بازار نیست. بازهٔ اصلی با تقاطع قاعدهٔ کیفیت و بازهٔ قبلاً پذیرفته‌شده پایان یافت. دادهٔ انتهایی به عامل تعدیل قدیمی وصله نشد و فروش فرضی در قیمت کهنه انجام نشد. draft نخست که آخرین ردیف کل آرشیو را به‌اشتباه انتهای اصلی گرفته بود، پیش از تکمیل تشخیص/بازده نامزد رد و با دلیل در window_rule_clarification ثبت شد.

## دفتر اقتصادی واقعاً اجراشده

۳۸ ردیف مواجهه به {impact.original_event_id.nunique()} شناسهٔ مستقل داده‌ای نگاشت شد؛ این‌ها لزوماً همین تعداد رویداد اقتصادی نیستند. گروه‌های پیشنهادی بدون سند ادغام قطعی نشدند. اسناد محلی با hash و تاریخ ثبت‌اند.

اصل AGM پکویر DPS۵۸۰ریال و پیوست رسمی برنامهٔ پرداخت با مشاهدهٔ تصویر کامل خوانده شد. در fixture دارندهٔ فرضی۱۰۰سهم، طلب۵۸هزارریال است؛ در سناریوی ناشر در آخرین روز بازهٔ اعلام‌شده ۱۴۰۵/۰۵/۲۵..۳۱، نقد افزایش می‌یابد، در سناریوی عدم استفادهٔ مجدد طلب می‌ماند؛ NAV مکانیکی با جابه‌جایی طلب به نقد عوض نمی‌شود. خرید زودهنگام با این طلب مجاز نیست. تعداد سهم/قیمت fixture فرضی و صریح است، نه بازده نمایندهٔ راهبرد.

در اصل ثبت افزایش سرمایهٔ دارو، سرمایه۲٫۶به۵۱٫۸میلیون واحد میلیون‌ریالی از محل سودانباشته و تجدیدارزیابی آمده؛ نسبت از مبلغ‌های هم‌واحد به‌دست آمد، نه شکاف قیمت. برای دارندهٔ فرضی۱۰۰سهم هم‌کلاس،۱۸۹۲سهم کامل مسدود ثبت شد؛ کسری و تاریخ معامله‌پذیری مجهول‌اند و پول یا سهم قابل‌معامله جعل نشد. آزمون وجه حق‌تقدم از موتور مشترک با موجودی محدود انجام شد؛ نمونهٔ کامل مستند حق‌تقدم برای کل راهبرد هنوز فراهم نیست.

دفتر کل اقتصادی راهبرد همچنان نامعلوم است، چون رویدادها/استحقاق‌های مادی حل نشده‌اند؛ اختلاف شاخص و raw به‌عنوان اثر سود نقدی جمع‌پذیر معرفی نشد. {b['catalog_pages']} درخواست دقیق کاتالوگ برای۲۶نماد timeout شد؛ retry بی‌پایان یا دورزدن کنترل انجام نشد. دریافت مستقیم پیوست رسمی موجود موفق بود. خطای منبع نیاز به رمز یا رسید شخصی کاربر ندارد.

## آیا رتبه‌بندی بهتر شد؟

{status}

جزئیات IC، گروه‌ها، شمار نمونه/سررسید و مرز رتبه در signal_diagnostics.csv و یادداشت DIAGNOSTICS.fa.md آمده است. اثر جامعه، رتبه و cadence جدا بررسی شد. سیاست‌های واقعی از تقویم تصمیم استخراج شد؛ متادیتای خلاصهٔ P0 برای مسیر زمان‌متغیر گمراه‌کننده بود، نه شاهد اجرای ماهانهٔ کل مسیر. هش وزن/امتیاز/تصمیم/سفارش/fill جفت S0/F0 مقایسه شد. نبود طبقه‌بندی صنایع تاریخی مانع جداست.

تداوم فصل و کیفیت نقد قبلاً آزمایش شده‌اند؛ فرمول تازه‌ای با همان داده تکرار نشد. buffer۱۵ فقط با فرض تشخیصی و ثبت پیش از بازده، در دو cadence موجود آزموده می‌شود؛ هیچ ترکیب برندهٔ پسینی ساخته نشد. قاعدهٔ۱۰٪ نسبت ثروت، اکثریت بلوک‌ها، افت حداکثر۵واحددرصد و تنش/حذف بهترین بلوک در registry است. آزمایش۵۰۰میلیون بدون نامزد معتبر انجام نشد.

## صفحه و ادامه

`http://localhost:3000/ranking/research` همان صفحهٔ موجود است؛ snapshot۱۴اکتبر و۱۰۱از۲۵۴ پنهانی به تاریخ دیگری عوض نشد. دادهٔ UI به `{out.name}` پین شده، حداکثر۱۰نماد و بخش «اگر۱۰۰میلیون سرمایه داشتیم» دارد. برندهٔ معتبر تازه مشخص نیست و S2 حفظ شد. جامعیت آخرین اطلاعیه‌های همهٔ نمادها احراز نشده؛ metadata با منابع منجمد و نسخه‌های بازیابی‌شده کنترل شده است.

مانع‌ها در blockers.csv برای هر نماد/تاریخ/سند با یک قدم بعدی ثبت‌اند. کاربر نیازی به ارائهٔ گردش حساب ندارد؛ ادامهٔ دفتر کامل به اسناد اصلی استحقاق/معامله‌پذیری و وضعیت رسمی بازار نیاز دارد. نتیجهٔ موجود برای مقایسهٔ پژوهشی است.

مراجع روش‌شناسی: [GIPS، تفکیک تعهد و نقد](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)؛ ادعای انطباق با GIPS نداریم. [Bailey و همکاران، خطر بیش‌برازش بک‌تست](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)؛ تکرار تاریخ آزمون مستقل نمی‌سازد. این منابع قانون استحقاق ایران را تعیین نمی‌کنند.
'''
    (out/'RETURN_V5_FINAL.fa.md').write_text(report,'utf8');(ROOT/'docs/RETURN_V5_FINAL.fa.md').write_text(report,'utf8')
    handoff=f'''# تحویل V5

اجرای صریح: `{out}`

فرمان ادامه: `.venv/Scripts/python.exe -B -m ranking_research.return_v5.run all --run "{out}"`

فرمان کنترل: همان فرمان با `verify`. کد/داده ناسازگار رد می‌شود؛ مرحلهٔ کامل و manifestدار بازاجرای مالی نمی‌شود. بعد از تغییر منطق اجرا تازه لازم است. V2..V4 را تغییر نده.

تعهد نقدی از وصول سناریویی و حساب واقعی جدا است؛ درخواست رسید شخصی برای بک‌تست ممنوع است. documented_fixtures.json و payment_schedule_transcription.json شواهد اجراشده‌اند، نه بازده کل راهبرد. canonical_events/exposure_event_mapping و unresolved_event_impact را برای ادامه بخوان.

کیفیت: بازهٔ اصلی تا{end}؛ آوریل فقط تطبیق V4. مشاهدهٔ معامله ازمه به‌تنهایی تمدید شاخص/اقتصاد نیست. source timeoutها cache‌شده‌اند؛ بدون تغییر شرایط دوباره۲۶درخواست را تکرار نکن. درخواست جدید باید سند/مسئلهٔ مشخص داشته باشد.

صفحهٔ موجود از return-v5.json با run_id صریح می‌آید؛ تولیدی دست‌نخورده است. نتیجهٔ نامزدها در candidate_gate.json است. آزمون‌ها و build در test_evidence.json ثبت می‌شوند. پس از اتمام هیچ کار مالی خودکار در پس‌زمینه ادعا نمی‌شود.
'''
    (out/'SOL61_RETURN_V5_HANDOFF.fa.md').write_text(handoff,'utf8');(ROOT/'docs/SOL61_RETURN_V5_HANDOFF.fa.md').write_text(handoff,'utf8')

def seal(out):
    validate(out)
    write(out/'delivery_manifest.json',{'run_id':out.name,'sealed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'files':{str(p.relative_to(out)).replace('\\','/'):sha(p) for p in out.rglob('*') if p.is_file() and p.name not in ['delivery_manifest.json','verification.json']}})
    verify(out)

def verify(out):
    validate(out)
    for p,h in read(out/'delivery_manifest.json')['files'].items():
        if sha(out/p)!=h:raise ValueError('Artifact changed: '+p)
    write(out/'verification.json',{'passed':True,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'run_id':out.name,
        'full_economic_strategy_nav_known':False,'actual_account':'does_not_exist','sources_and_code_unchanged':True})
