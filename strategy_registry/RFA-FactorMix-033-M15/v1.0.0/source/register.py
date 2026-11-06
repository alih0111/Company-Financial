"""Freeze the user-requested M15 variation separately; refuse overwrites."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import zipfile

from factormix.reproduce_monthly15 import reproduce

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / 'strategy_registry/RFA-FactorMix-033/v1.0.0'
SOURCE = ROOT / 'strategy_registry/analyses/factormix_monthly15_20261106'
VERSION = ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0'
STRATEGY_ID = 'RFA-FactorMix-033-M15-Buffer8-v1.0.0'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def main():
    if VERSION.exists():
        raise RuntimeError('Registered version already exists; never overwrite it')
    parent_manifest = json.loads((PARENT / 'MANIFEST.sha256.json').read_text(encoding='utf8'))
    for row in parent_manifest['files']:
        assert sha(PARENT / row['path']) == row['sha256']
    summary = json.loads((SOURCE / 'artifacts/summary.json').read_text(encoding='utf8'))
    protocol = json.loads((SOURCE / 'artifacts/protocol.json').read_text(encoding='utf8'))
    assert protocol['input_sha256'] == sha(PARENT / 'snapshot_data/active_inputs.npz')
    assert protocol['policy_sha256'] == sha(PARENT / 'strategy.locked.json')
    assert summary['original_daily_nav_reproduced'] and summary['registered_strategy_unchanged']
    for folder in ['replay', 'snapshot_data', 'results', 'source']:
        (VERSION / folder).mkdir(parents=True)
    parent = json.loads((PARENT / 'strategy.locked.json').read_text(encoding='utf8'))
    policy = dict(registry_id=STRATEGY_ID, registry_version='1.0.0', display_name='FactorMix-033 · ماهانه ۱۵',
        registered_client_date='2026-11-06', registered_at_utc=datetime.now(timezone.utc).isoformat(),
        parent_strategy_id=parent['registry_id'], parent_policy_sha256=sha(PARENT / 'strategy.locked.json'),
        source_model=parent['source_model'], block_weights=parent['block_weights'],
        portfolio={**parent['portfolio'], 'id':'n5_m15_band', 'schedule':'jalali_monthly_15'},
        human_rules={**parent['human_rules'], 'calendar':'Jalali day 15; first stock session on/after it; explicit initial entry'},
        execution_assumptions=parent['execution_assumptions'], calendar_policy=parent['calendar_policy'],
        replay=dict(requested_start=protocol['requested_start'], end=protocol['end'], initial_toman=100_000_000,
                    expected_final_toman=summary['accounts']['monthly_jalali_15']['metrics']['final_toman']),
        status='REGISTERED_HISTORICAL_VARIANT_WITH_MANUAL_PLANNER', broker_execution_enabled=False,
        live_automatic_rebalancing_enabled=False, historical_scores='same frozen candidate_score as parent',
        live_scores='same locked FactorMix factors recomputed from collected sources; not a claim of identical historical receipt coverage',
        limitations=summary['limitations'], no_future_performance_guarantee=True)
    write(VERSION / 'strategy.locked.json', policy)
    shutil.copyfile(PARENT / 'strategy.locked.json', VERSION / 'parent.strategy.locked.json')
    shutil.copyfile(PARENT / 'replay/engine_snapshot.py', VERSION / 'replay/engine_snapshot.py')
    shutil.copyfile(ROOT / 'factormix/reproduce_monthly15.py', VERSION / 'replay/reproduce.py')
    shutil.copyfile(ROOT / 'strategy_registry/analyses/replay_1401_20261106/run.py', VERSION / 'replay/audit.py')
    shutil.copyfile(PARENT / 'snapshot_data/active_inputs.npz', VERSION / 'snapshot_data/active_inputs.npz')
    for path in (PARENT / 'source').glob('model_search_*.py'):
        shutil.copyfile(path, VERSION / 'source' / path.name)
    shutil.copyfile(SOURCE / 'run.py', VERSION / 'source/analysis_run.py')
    shutil.copyfile(Path(__file__), VERSION / 'source/register.py')
    for path in (SOURCE / 'artifacts').iterdir():
        if path.is_file():
            shutil.copyfile(path, VERSION / 'results' / path.name)
    shutil.copyfile(SOURCE / 'REPORT.fa.md', VERSION / 'REPORT.fa.md')
    for name in ['monthlyBasketPlan.js', 'monthlyBasketPlan.d.ts', 'MonthlyFactorMixPlanner.tsx']:
        shutil.copyfile(ROOT / 'client/src/components' / name, VERSION / 'source' / name)
    guide = '''# FactorMix-033، بازبینی پانزدهم هر ماه

نسخهٔ مستقل ۱٫۰٫۰؛ وزن‌های هشت عامل و قواعد سبد از FactorMix اصلی حفظ شده‌اند.
تغییر اصلی: بازبینی پس از پایان روز ۱۵ شمسی، یا اولین جلسهٔ سهام بعد از آن.
اجرای تغییرها از جلسهٔ بعد؛ ورود اولیه مانند مقایسهٔ اصلی صریح است.
پنج سهم با وزن هدف ۲۰٪؛ دارندگان واجد شرایط تا رتبهٔ ۸ حفظ می‌شوند.
جای خالی از بهترین رتبه‌های باقی‌مانده پر می‌شود. انحراف بیش از ۵ واحد درصد
باعث تنظیم وزن می‌شود. دادهٔ نامعتبر یا قدیمی می‌تواند نماد را خارج کند.
اگر کمتر از پنج سهم واجد شرایط باشد، سهم جای خالی نقد می‌ماند.
کارمزد ۰٫۵٪ و لغزش ۰٫۱٪ هر سمت، مهلت سفارش پنج جلسه و سقف حجم مانند اصل است.

## استفاده از سایت

۱. در طول ماه گزارش‌های جدید مالی، فروش و اصلاحیه‌ها را جمع کنید؛ پایان موفق جمع‌آوری را بررسی کنید.
۲. روز ۱۵، یا اولین جلسهٔ سهام بعد، بعد از پایان بازار، گزارش‌ها و قیمت‌های سهام را به‌روز کنید.
۳. در سبد استراتژی، «به‌روزرسانی امتیازها» را بزنید و منتظر پایان محاسبه بمانید.
۴. در «بررسی سبد ماهانه»، ارزش روز تمام سهم‌های همین سبد و نقد را وارد کنید؛ برای شروع فقط نقد را وارد کنید.
۵. «بررسی سبد ماهانه» را بزنید. پیشنهاد بر مبنای دارایی واردشده و همین امتیازهاست.
۶. از جلسهٔ بعد، پیشنهادهای لازم را با قیمت و امکان اجرای موجود بررسی و در کارگزاری اعمال کنید.
پس از اجرا، در بررسی بعدی موجودی واقعی را وارد کنید؛ سفارش انجام‌نشده را خرید/فروش انجام‌شده حساب نکنید.
دکمه‌ها سفارش کارگزاری ارسال نمی‌کنند و حساب تاریخی یا حساب کاغذی قبلی را تغییر نمی‌دهند.
ارقام پیشنهاد، اختلاف مبلغ هدف پیش از هزینه‌اند؛ فروش‌های اجرا نشده نقد خرید نیستند.
بررسی خارج از موعد فقط پیش‌نمایش است و نوبت ماهانه را جابه‌جا نمی‌کند.

## بازتولید مستقل

از داخل این پوشه: `python -B replay/reproduce.py`.
نیازمند numpy، pandas و jdatetime است؛ پایگاه داده و اینترنت لازم نیست.
MANIFEST.sha256.json همهٔ فایل‌ها را قفل می‌کند. بازپخش هر دو مسیر و نقد و
تمام خریدوفروش‌ها با خروجی ثبت‌شده تطبیق داده می‌شوند. هیچ خروجی روی حساب‌ها نوشته نمی‌شود.
این بسته برای بازپخش عددی مستقل است؛ منابع خام مالی/قیمتی اولیه همگی تکرار نشده‌اند.
تعریف عامل‌ها در source و شناسه و هش نسخهٔ والد در قرارداد نگهداری شده‌اند.
این نسخه بازنویسی نشود؛ تغییر بعدی نسخهٔ تازه می‌خواهد.
'''
    (VERSION / 'STRATEGY.fa.md').write_text(guide, encoding='utf8')
    (VERSION / 'requirements-replay.txt').write_text('\n'.join(
        f'{name}=={importlib.metadata.version(name)}' for name in ['numpy','pandas','jdatetime'])+'\n', encoding='utf8')
    files = [dict(path=p.relative_to(VERSION).as_posix(), sha256=sha(p), bytes=p.stat().st_size)
             for p in sorted(VERSION.rglob('*')) if p.is_file()]
    write(VERSION / 'MANIFEST.sha256.json', dict(strategy_id=STRATEGY_ID, files=files))
    verification = reproduce(VERSION)
    name = 'RFA-FactorMix-033-M15-v1.0.0-20261106.zip'
    archive = ROOT / 'strategy_registry/archives' / name
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(VERSION.rglob('*')):
            if p.is_file():
                z.write(p, 'RFA-FactorMix-033-M15-v1.0.0/' + p.relative_to(VERSION).as_posix())
    backup = Path.home() / 'Documents/RFA-Strategy-Backups' / name
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise RuntimeError('Backup already exists; will not overwrite')
    shutil.copyfile(archive, backup)
    assert sha(backup) == sha(archive)
    for row in parent_manifest['files']:
        assert sha(PARENT / row['path']) == row['sha256']
    record = dict(registry_id=STRATEGY_ID, version_directory=str(VERSION), archive=str(archive),
        backup=str(backup), zip_sha256=sha(archive), files_in_version=len(files)+1,
        archive_bytes=archive.stat().st_size, parent_unchanged=True,
        standalone_replay=verification, production_broker_execution=False, manual_planner_enabled=True)
    write(ROOT / 'strategy_registry/monthly15.registration.json', record)
    print(json.dumps(record))


if __name__ == '__main__':
    main()
