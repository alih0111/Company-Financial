"""Publish two separately funded, verified replay periods for the performance UI."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import jdatetime
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'strategy_registry/RFA-FactorMix-033/v1.0.0'
ANALYSIS=ROOT/'strategy_registry/analyses/replay_1401_20261106'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annual_rows(nav,baseline,capital):
    years=np.array([jdatetime.date.fromgregorian(date=pd.Timestamp(d).date()).year for d in nav.session])
    rows=[]
    for year in sorted(set(years)):
        ids=np.flatnonzero(years==year);a,b=int(ids[0]),int(ids[-1])
        initial=capital if a==0 else float(nav.nav_toman.iloc[a-1])
        base_initial=capital if a==0 else float(baseline.nav_toman.iloc[a-1])
        final=float(nav.nav_toman.iloc[b]);base_final=float(baseline.nav_toman.iloc[b])
        rows.append(dict(year=int(year),start=str(nav.session.iloc[a]),end=str(nav.session.iloc[b]),
            initial_toman=initial,final_toman=final,return_fraction=final/initial-1,
            baseline_initial_toman=base_initial,baseline_final_toman=base_final,
            baseline_return_fraction=base_final/base_initial-1))
    return rows


def account(nav,trades,decisions,capital,engine,positions):
    metrics=engine.metrics(nav.session.to_numpy(),nav.nav_toman.to_numpy(),capital)
    holdings=sum(float(p['market_value_toman']) for p in positions)
    cash=max(0.,float(nav.cash_toman.iloc[-1]))
    assert abs(cash+holdings-metrics['final_toman'])<1
    return dict(**metrics,fees_toman=float(trades.fee_toman.sum()),slippage_toman=float(trades.slippage_toman.sum()),
        trade_count=len(trades),buy_count=int((trades.side=='BUY').sum()),sell_count=int((trades.side=='SELL').sum()),
        decision_count=len(decisions),first_fill=str(trades.session.iloc[0]),cash_toman=cash,
        holdings_value_toman=holdings,positions=positions)


def make_case(case_id,year,source,prefix,capital,engine,positions,download_dir):
    nav=pd.read_csv(source/f'{prefix}candidate_nav.csv')
    baseline=pd.read_csv(source/f'{prefix}baseline_nav.csv')
    assert nav.session.tolist()==baseline.session.tolist()
    assert nav.session.is_monotonic_increasing and nav.session.is_unique
    assert nav.nav_toman.iloc[0]==baseline.nav_toman.iloc[0]==capital
    assert nav.cash_toman.iloc[0]==baseline.cash_toman.iloc[0]==capital
    assert np.isfinite(nav[['nav_toman','cash_toman']].to_numpy()).all()
    assert np.isfinite(baseline[['nav_toman','cash_toman']].to_numpy()).all()
    accounts={}
    downloads={}
    for label,frame in [('candidate',nav),('baseline',baseline)]:
        trades=pd.read_csv(source/f'{prefix}{label}_trades.csv')
        decisions=pd.read_csv(source/f'{prefix}{label}_decisions.csv')
        accounts[label]=account(frame,trades,decisions,capital,engine,positions[label])
        for kind in ['nav','trades','decisions']:
            filename=f'{case_id}-{label}-{kind}.csv'
            shutil.copyfile(source/f'{prefix}{label}_{kind}.csv',download_dir/filename)
            downloads[f'{label}_{kind}']=filename
    annual=annual_rows(nav,baseline,capital)
    filename=f'{case_id}-annual.csv'
    pd.DataFrame(annual).to_csv(download_dir/filename,index=False,encoding='utf-8-sig')
    downloads['annual']=filename
    drawdown=nav.nav_toman.to_numpy()/np.maximum.accumulate(np.r_[capital,nav.nav_toman])[1:]-1
    base_dd=baseline.nav_toman.to_numpy()/np.maximum.accumulate(np.r_[capital,baseline.nav_toman])[1:]-1
    path=[dict(date=str(d),nav_toman=float(n),baseline_toman=float(b),cash_toman=max(0.,float(c)),
               drawdown=float(dd),baseline_drawdown=float(bd),n_positions=int(np_),baseline_positions=int(bp))
          for d,n,b,c,dd,bd,np_,bp in zip(nav.session,nav.nav_toman,baseline.nav_toman,nav.cash_toman,
                                        drawdown,base_dd,nav.n_positions,baseline.n_positions)]
    for label,field in [('candidate','final_toman'),('baseline','baseline_final_toman')]:
        fractions=[r['return_fraction' if label=='candidate' else 'baseline_return_fraction'] for r in annual]
        assert abs(np.prod([1+x for x in fractions])*capital-accounts[label]['final_toman'])<1
        assert abs(annual[-1][field]-accounts[label]['final_toman'])<1
    return dict(id=case_id,start_year=year,start=str(nav.session.iloc[0]),as_of=str(nav.session.iloc[-1]),
                initial_toman=capital,accounts=accounts,annual=annual,path=path,downloads=downloads)


def publish_performance(history,public,atomic_json):
    # Source analysis has its own immutable delivery manifest. Do not trust a loose
    # summary or silently replace the 1402 trial with a slice of the 1401 trial.
    manifest=json.loads((ANALYSIS/'artifacts/delivery_manifest.json').read_text(encoding='utf8'))
    for item in manifest['files']:
        file=ANALYSIS/item['path']
        if not file.is_file() or digest(file)!=item['sha256']:
            raise RuntimeError('1401 replay delivery checksum failed: '+item['path'])
    protocol=json.loads((ANALYSIS/'artifacts/protocol.json').read_text(encoding='utf8'))
    if protocol['policy_sha256']!=history['policy_sha256'] or protocol['input_sha256']!=digest(ARCHIVE/'snapshot_data/active_inputs.npz'):
        raise RuntimeError('Performance periods use different frozen strategy inputs')
    # Import the frozen engine only for its descriptive metric calculation.
    import importlib.util,sys
    spec=importlib.util.spec_from_file_location('factormix_performance_metrics',ARCHIVE/'replay/engine_snapshot.py')
    engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    extended=json.loads((ANALYSIS/'artifacts/summary.json').read_text(encoding='utf8'))
    previous=json.loads((ARCHIVE/'results/active_summary.json').read_text(encoding='utf8'))
    folder=public/'performance';folder.mkdir(parents=True,exist_ok=True)
    old_positions={label:[dict(symbol=s,market_value_toman=v) for s,v in (
        previous['last_positions'] if label=='candidate' else {}
    ).items()] for label in ['candidate','baseline']}
    # Baseline terminal values are reconstructed from its own fills and marks.
    inputs=np.load(ARCHIVE/'snapshot_data/active_inputs.npz',allow_pickle=False)
    names=inputs['syms'].tolist();base_q=np.zeros(len(names));index={s:j for j,s in enumerate(names)}
    for t in pd.read_csv(ARCHIVE/'results/active_baseline_trades.csv').to_dict('records'):
        base_q[index[t['symbol']]]+=t['units']*(1 if t['side']=='BUY' else -1)
    old_positions['baseline']=[dict(symbol=names[j],market_value_toman=float(base_q[j]*inputs['close'][-1,j]))
                               for j in np.flatnonzero(base_q>1e-10)]
    # Prefer the already verified richer 1402 position records for price-age notes.
    old_positions['candidate']=history['holdings']
    cases=[make_case('from-1401',1401,ANALYSIS/'artifacts','',extended['initial_toman'],engine,
                     {label:extended['accounts'][label]['ledger']['positions'] for label in ['candidate','baseline']},folder),
           make_case('from-1402',1402,ARCHIVE/'results','active_',history['initial_toman'],engine,old_positions,folder)]
    for case,reference in [(cases[0],extended['accounts']),(cases[1],previous)]:
        for label in ['candidate','baseline']:
            metrics=reference[label]['metrics'] if 'metrics' in reference[label] else reference[label]
            for field in ['final_toman','total_return','max_drawdown']:
                tolerance=1 if field=='final_toman' else 1e-10
                assert abs(case['accounts'][label][field]-metrics[field])<tolerance,(case['id'],label,field)
        # A portable human-readable download, independent of project filesystem paths.
        filename=case['id']+'-report.fa.md';a=case['accounts']['candidate'];b=case['accounts']['baseline']
        (folder/filename).write_text(f"# عملکرد تاریخی FactorMix-033، شروع {case['start_year']}\n\n"
            f"بازهٔ میلادی: {case['start']} تا {case['as_of']}؛ سرمایهٔ آغازین {case['initial_toman']:,.0f} تومان.\n\n"
            f"پایان مدل جدید: {a['final_toman']:,.0f} تومان؛ پایان P1: {b['final_toman']:,.0f} تومان.\n\n"
            f"بیشترین افت مدل جدید: {abs(a['max_drawdown'])*100:.2f}٪. کارمزد و لغزش در بازده منظور شده‌اند.\n\n"
            "هر بازه حساب مستقلی با ۱۰۰ میلیون تومان آغازین است. وزن‌ها و قواعد نسخهٔ ۱٫۰٫۰ ثابت‌اند.\n\n"
            "این بازپخش تاریخی با واحد شاخصی تعدیل‌شده است؛ بخشی از همین تاریخچه در انتخاب مدل استفاده شده است. "
            "زمان دریافت تاریخی همهٔ گزارش‌ها و اجرای واقعی صف اثبات نشده‌اند. NAV، نقد قابل برداشت فوری نیست.\n",
            encoding='utf8')
        case['downloads']['report']=filename
        chart_source=ANALYSIS/'artifacts/comparison.png' if case['start_year']==1401 else ARCHIVE/'results/full_comparison.png'
        chart_name=case['id']+'-chart.png';shutil.copyfile(chart_source,folder/chart_name);case['downloads']['chart']=chart_name
    from factormix.monthly15_performance import attach_monthly15
    attach_monthly15(cases,folder)
    payload=dict(schema_version=1,strategy_id=history['strategy_id'],policy_sha256=history['policy_sha256'],
        mode='historical_replay',default_case='from-1401',cases=cases,
        integrity=dict(archive_verified_files=history['integrity']['verified_files'],
            extended_delivery_manifest_sha256=digest(ANALYSIS/'artifacts/delivery_manifest.json'),
            separate_initial_capital_verified=True,annual_and_daily_metrics_reconciled=True))
    atomic_json(folder/'performance.json',payload)
    from factormix.benchmark_history import publish_cached_benchmarks
    publish_cached_benchmarks(folder)
    return payload
