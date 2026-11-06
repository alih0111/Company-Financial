"""Create a versioned local recovery package; never overwrite an existing version."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil,zipfile,platform,importlib.metadata

ROOT=Path(__file__).resolve().parents[1]
REG=ROOT/'strategy_registry'
VERSION=REG/'RFA-FactorMix-033/v1.0.0'
SEARCH=ROOT/'ranking_research/experiments/feature_model_search_20261106'
REPLAY=ROOT/'ranking_research/experiments/replay_1402_to_now_20261106'
PREV=ROOT/'ranking_research/experiments/final_strategy_review_20261106'
BACKUP=Path.home()/'Documents/RFA-Strategy-Backups'
NAME='RFA-FactorMix-033-v1.0.0-20261106.zip'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    if VERSION.exists():raise RuntimeError('Version already exists. Verify it or create a NEW version; do not overwrite.')
    decision=json.loads((SEARCH/'artifacts/research_decision.json').read_text(encoding='utf8'))
    active=json.loads((REPLAY/'artifacts/active_summary.json').read_text(encoding='utf8'))
    generic=json.loads((REPLAY/'artifacts/complete_summary.json').read_text(encoding='utf8'))
    provenance=[]
    VERSION.mkdir(parents=True)
    def copy(source,target):
        dst=VERSION/target;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dst)
        provenance.append(dict(original_path=str(source.relative_to(ROOT)),archived_path=target,sha256=sha(dst)))
    # A stand-alone simulator plus frozen matrices can reproduce the NAV even
    # after all original experiment directories have been deleted.
    copy(PREV/'engine.py','replay/engine_snapshot.py')
    copy(REG/'restore_replay_template.py','replay/restore_replay.py')
    copy(REPLAY/'artifacts/active_inputs.npz','snapshot_data/active_inputs.npz')
    copy(REPLAY/'artifacts/complete_inputs.npz','snapshot_data/generic_inputs.npz')
    copy(SEARCH/'artifacts/features.npz','snapshot_data/model_features.npz')
    copy(SEARCH/'artifacts/market_inputs.npz','snapshot_data/model_market_inputs.npz')
    copy(SEARCH/'artifacts/score_cache/GROUP_WEIGHT_033.npz','snapshot_data/selected_score.npz')
    for source,label in [(SEARCH,'model_search'),(REPLAY,'full_replay')]:
        for p in sorted(source.glob('*.py')):copy(p,f'source/{label}_{p.name}')
        copy(source/'REPORT.fa.md',f'reports/{label}.fa.md')
        copy(source/'README.md',f'reports/{label}_reproduction.md')
    for name in ['research_decision.json','protocol.locked.json','chosen.before_reused_verification.json',
                 'summary.json','feature_manifest.json','selection_all.csv','stress.csv','monthly_starts.csv',
                 'stability_summary.json','stability_results.csv','tests.junit.xml']:
        copy(SEARCH/'artifacts'/name,'evidence/model_'+name)
    for name in ['active_summary.json','complete_summary.json','available_replay.json','active_calendar.protocol.json',
                 'market_extension.json','active_financial_extension_audit.json','generic_financial_extension_audit.json',
                 'reference_factor_regression.csv','new_reference_adjustments.csv','tests.junit.xml','full_comparison.png']:
        copy(REPLAY/'artifacts'/name,'results/'+name)
    for prefix in ['active_candidate','active_baseline','complete_candidate','complete_baseline']:
        for suffix in ['nav.csv','trades.csv','decisions.csv']:
            name=f'{prefix}_{suffix}';copy(REPLAY/'artifacts'/name,'results/'+name)
    for p in sorted((REPLAY/'artifacts').glob('financial_*.parquet')):copy(p,'source_inputs/'+p.name)
    # Pin the financial inputs too. No environment/config/credential files enter
    # the package, and the bulky raw public price archives are not duplicated.
    source_manifest=json.loads((REPLAY/'artifacts/delivery_manifest.json').read_text(encoding='utf8'))
    for item in source_manifest['input_sources']:
        p=ROOT/item['path'];assert sha(p)==item['sha256']
        copy(p,'source_inputs/'+p.name)
    policy={**decision,'registry_id':'RFA-FactorMix-033-Q40-Buffer8-v1.0.0',
        'registry_version':'1.0.0','registered_client_date':'2026-11-06',
        'registered_at_utc':datetime.now(timezone.utc).isoformat(),'preservation_only_no_activation':True,
        'calendar_policy':{'primary':'observed equity-activity calendar',
            'historical_frozen_prefix_end':'2026-02-24','after_prefix':'exclude dates with no positive-volume/value tradable opening across the frozen 254 names',
            'stock_session_order_expiry':5,'generic_calendar_is_retained_as_control':True},
        'replay':{'requested_start':'2023-03-21','first_available_session':active['start'],
            'market_end':active['latest_available_market_day'],'market_end_jalali':active['latest_market_day_jalali'],
            'initial_toman':active['initial_toman'],'expected_final_toman':active['candidate']['final_toman'],
            'baseline_final_toman':active['baseline']['final_toman'],
            'generic_calendar_final_toman':generic['candidate']['final_toman'],
            'max_drawdown':active['candidate']['max_drawdown'],
            'basis':'historical reconstructed portfolio NAV; NOT actual cash proceeds or prospective proof'},
        'archive_score_file':'snapshot_data/selected_score.npz',
        'no_future_performance_guarantee':True}
    # Do not require a path on the original computer for offline replay.
    policy['original_score_file']=policy.pop('score_file')
    write(VERSION/'strategy.locked.json',policy)
    requirements=[]
    for p in ['numpy','pandas','jdatetime']:
        requirements.append(p+'=='+importlib.metadata.version(p))
    (VERSION/'requirements-replay.txt').write_text('\n'.join(requirements)+'\n',encoding='utf8')
    guide='''# نسخه ثبت شده استراتژی FactorMix 033

نسخه ۱٫۰٫۰ — ثبت در ۶ نوامبر ۲۰۲۶

این بسته نسخهٔ منتخب تحقیقاتی را حفظ می‌کند. ثبت آن به معنی فعال‌سازی معامله یا تأیید بازده آینده نیست. تغییرهای بعدی باید در نسخهٔ تازه ثبت شوند؛ این نسخه بازنویسی نشود.

## قواعد دقیق

مدل همان GROUP_WEIGHT_033 است. وزن هشت بلوک در strategy.locked.json با تمام دقت ثبت شده: شتاب عملکرد، سودآوری، روند قیمت، نوسان و برگشت کوتاه‌مدت، رشد سطح عملکرد، ترازنامه، ارزش‌گذاری و سهم کوچکی از P1 قبلی. نام بلوک‌ها و ترتیب آن‌ها نیز در JSON ثبت است. تعریف ریاضی ورودی‌ها در source/model_search_features.py نگهداری شده است.

هدف پنج سهم با وزن ۲۰٪ است. سهم نگهداری‌شده تا رتبهٔ ۸ حفظ می‌شود؛ پس از خروج، جای خالی از بالاترین رتبه‌ها پر می‌شود. در بازبینی، انحراف بیش از ۵ واحد درصد از وزن هدف باعث بازتنظیم می‌شود. بین بازبینی‌ها سقف تضمین‌شدهٔ وزن نداریم.

بازبینی در نخستین جلسهٔ سهام در یا پس از ۴۰ روز از پایان فصل شمسی است. ورود اولیه صریح ثبت می‌شود. تصمیم بعد از بازار و نخستین معامله در جلسهٔ بعد است. پنج جلسه برای بخش پرنشدهٔ سفارش در نظر گرفته می‌شود. تقویم سهام و دورهٔ تعطیلی در فایل JSON ثبت شده‌اند؛ تقویم عمومی قبلی به عنوان کنترل حفظ شده است.

فرض تاریخی هر طرف: کارمزد ۰٫۵٪، لغزش ۰٫۱٪ و سقف ۵٪ میانهٔ ارزش معاملات قبلی. روز تک‌قیمتی به معنی پرشدن قطعی نیست. شرایط پوشش و تازگی داده و سایر پارامترها در execution_assumptions آمده‌اند.

## نتیجه ثبت شده

شروع با ۱۰۰ میلیون تومان از ابتدای ۱۴۰۲ و پایان در ۱۳ آبان ۱۴۰۵: حدود ۱٬۲۹۰٫۵ میلیون تومان ارزش سبد با تقویم فعالیت سهام، مقابل ۹۶۱ میلیون تومان P1 همسان. کنترل تقویم عمومی برای مدل جدید حدود ۱٬۱۷۹٫۷ میلیون تومان است. هر دو سناریو نگهداری شده‌اند؛ این‌ها فاصلهٔ اطمینان نیستند.

این ارزش دفتری با قیمت آخرین معامله است. در پایان یک خروج پرنشده باقی مانده و شش موقعیت به جای هدف پنج‌تایی دیده می‌شود. دادهٔ مالی بازسازی‌شده، تعدیلات امتداد‌یافتهٔ پژوهشی و فرض سرمایه‌گذاری مجدد سود، عملکرد حساب واقعی یا نقد قابل برداشت را اثبات نمی‌کنند. بخشی از تاریخچه در انتخاب وزن‌ها استفاده شده است.

## بازیابی مستقل

فایل‌های قواعد و کد در Git ثبت می‌شوند؛ ماتریس‌های بزرگ و منابع مالی داخل ZIP پشتیبان هستند. اگر فقط فایل‌های Git موجود باشند، ZIP کامل را از پوشهٔ پشتیبان بازیابی کنید.

نسخهٔ کامل شامل کد مستقل replay/restore_replay.py و دادهٔ snapshot_data/active_inputs.npz است. این مسیر برای بازتولید همان بک‌تست به پوشه‌های آزمایش اصلی، پایگاه داده یا اتصال شبکه نیاز ندارد. Python و بسته‌های requirements-replay.txt لازم‌اند.

از داخل همین پوشه:

```powershell
python replay/restore_replay.py --verify-only
python replay/restore_replay.py --output-dir C:/RFA-Recovered-Replay-v1
```

مسیر خروجی باید تازه و بیرون از این نسخه باشد؛ اسکریپت چیزی را بازنویسی نمی‌کند. تمام فایل‌ها با MANIFEST.sha256.json کنترل می‌شوند و سپس کل مسیر روزانه با نتیجهٔ ذخیره‌شده تطبیق داده می‌شود.

کدهای source/ تصویرِ ارجاعیِ کدهای اصلی‌اند؛ بعضی بازسازی‌های مالیِ کامل به ماژول‌های پروژهٔ اصلی نیاز دارند. بازیابی مستقل فوق، از ماتریس‌های نهاییِ منجمد استفاده می‌کند و این وابستگی را ندارد. این بسته پشتیبان کاملِ همهٔ نرم‌افزارها و آرشیو خام بازار نیست.
'''
    (VERSION/'STRATEGY.fa.md').write_text(guide,encoding='utf8')
    write(VERSION/'PROVENANCE.json',{'files':provenance,'python_version':platform.python_version(),
        'source_project':str(ROOT),'no_credentials_included':True,'mode':'local frozen strategy preservation'})
    files=[dict(path=str(p.relative_to(VERSION)).replace('\\','/'),sha256=sha(p),bytes=p.stat().st_size)
        for p in sorted(VERSION.rglob('*')) if p.is_file() and p.name!='MANIFEST.sha256.json']
    write(VERSION/'MANIFEST.sha256.json',{'registry_id':policy['registry_id'],'files':files})
    archives=REG/'archives';archives.mkdir(exist_ok=True);archive=archives/NAME
    if archive.exists():raise RuntimeError('Archive exists; refusing overwrite')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(VERSION.rglob('*')):
            if p.is_file():z.write(p,'RFA-FactorMix-033-v1.0.0/'+str(p.relative_to(VERSION)).replace('\\','/'))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    digest=sha(archive);sidecar=archive.with_suffix('.zip.sha256')
    sidecar.write_text(digest+'  '+NAME+'\n',encoding='ascii')
    BACKUP.mkdir(parents=True,exist_ok=True);external=BACKUP/NAME
    if external.exists():raise RuntimeError('External backup exists; refusing overwrite')
    shutil.copyfile(archive,external);shutil.copyfile(sidecar,BACKUP/sidecar.name)
    assert sha(external)==digest
    pointer={'registry_id':policy['registry_id'],'version_directory':str(VERSION),'archive':str(archive),
        'backup':str(external),'zip_sha256':digest,'files_in_version':len(files)+1,'archive_bytes':archive.stat().st_size,
        'cloud_uploaded':False,'production_activated':False}
    write(REG/'registration.json',pointer)
    rootguide=f'''# محل ثبت و پشتیبان استراتژی منتخب RFA

نسخهٔ ثبت‌شده: **RFA-FactorMix-033، نسخهٔ ۱٫۰٫۰**، تاریخ ۶ نوامبر ۲۰۲۶.

- [قواعد و راهنمای بازیابی]({(VERSION/'STRATEGY.fa.md').as_posix()})
- [وزن‌ها و پارامترهای دقیق]({(VERSION/'strategy.locked.json').as_posix()})
- [نسخهٔ کامل فشرده داخل پروژه]({archive.as_posix()})
- [کپی پشتیبان خارج از پروژه]({external.as_posix()})

این نسخه همان مدلِ بازپخش حدود ۱٫۲۹ میلیارد تومانی با شروع ۱۰۰ میلیون در ۱۴۰۲ است. کنترل تقویم عمومیِ حدود ۱٫۱۸ میلیارد نیز همراهش حفظ شده است. عددها نتیجهٔ پژوهشی‌اند و فعال‌سازی حساب یا تضمین آینده نیستند.

بسته شامل قواعد، وزن‌ها، تصویر کد، ورودی‌های منجمد، معاملات، مسیر سرمایه، نتایج و اسکریپت بازیابی مستقل است. صحت دو ZIP با SHA-256 تطبیق داده شده است. پشتیبان خارج از پروژه روی همین رایانه قرار دارد؛ بارگذاری ابری انجام نشده است.

برای تغییر، نسخهٔ تازه بسازید؛ فایل‌های نسخهٔ ۱٫۰٫۰ را بازنویسی نکنید. رسید ثبت و اثر انگشت ZIP در strategy_registry/registration.json قرار دارد.
'''
    (ROOT/'STRATEGY-REGISTER.fa.md').write_text(rootguide,encoding='utf8')
    (REG/'README.fa.md').write_text(rootguide,encoding='utf8')
    print(json.dumps(pointer,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
