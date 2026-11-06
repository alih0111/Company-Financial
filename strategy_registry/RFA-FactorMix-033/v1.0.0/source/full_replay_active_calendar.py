"""Equity-activity calendar correction, declared without return-based tuning."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
import json,sys
import numpy as np
import pandas as pd
import jdatetime
import full_replay as f
from engine import Config,Execution,simulate,save_run,calendar_schedule

HERE=f.HERE;OUT=f.OUT


def main():
    declaration={'declared_at_utc':datetime.now(timezone.utc).isoformat(),
        'rule':'preserve all frozen dates through 2026-02-24; thereafter count an equity session only when at least one of the 254 names has a positive-volume/value opening',
        'reason':'generic calendar includes dates during the spring 1405 equity closure, incorrectly expiring orders and anchoring quarterly reviews',
        'return_based_calendar_tuning':False,'weights_and_order_life_unchanged':True,
        'calendar_is_observed_equity_activity_proxy_not_exchange_certification':True}
    (OUT/'active_calendar.protocol.json').write_text(json.dumps(declaration,indent=2),encoding='utf8')
    original=dict(np.load(OUT/'complete_inputs.npz',allow_pickle=False));T=len(original['cal'])
    keep=(original['cal']<='2026-02-24')|np.isfinite(original['opening']).any(axis=1)
    # Load only the local market object; normalized original inputs stay intact.
    _,md,meta=f.prepare_market()
    data={k:(v[keep].copy() if v.ndim and v.shape[0]==T else v.copy()) for k,v in original.items() if k!='candidate_score'}
    md.cal=data['cal'].tolist();cal=md.cal
    policy=json.loads((f.SEARCH/'artifacts/research_decision.json').read_text(encoding='utf8'))
    cfg=Config(**policy['portfolio']);e=Execution(**policy['execution_assumptions'])
    schedule=calendar_schedule(cal,cfg,int(np.searchsorted(cal,'2023-03-21')),len(cal))
    ix=[i for i in sorted(schedule) if cal[i]>'2026-02-24'];needed={cal[i] for i in ix}
    for i in ix:
        k=np.searchsorted(data['cal'].astype('datetime64[D]'),np.datetime64(cal[i])-np.timedelta64(90,'D'),side='right')-1
        if cal[k]>'2026-02-24':needed.add(cal[k])
    print('EQUITY CALENDAR',int((~keep).sum()),'inactive rows excluded; snapshots',sorted(needed),flush=True)
    # Separate snapshot audit names preserve the first calculation's provenance.
    generic_audit=OUT/'generic_financial_extension_audit.json'
    if not generic_audit.exists():
        generic_audit.write_bytes((OUT/'financial_extension_audit.json').read_bytes())
    frame=f.append_financial(data,md,meta,sorted(needed))
    audit=json.loads((OUT/'financial_extension_audit.json').read_text(encoding='utf8'))
    (OUT/'active_financial_extension_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    values=f.build_extended_scores(data,frame,policy)
    np.savez_compressed(OUT/'active_inputs.npz',**data,candidate_score=values)
    runs={}
    for label,d,c in [('candidate',{**data,'p1':values},cfg),('baseline',data,Config('BASE'))]:
        r=simulate(d,c,e,start='2023-03-21',end=cal[-1],detail=True);runs[label]=r;save_run(OUT/f'active_{label}',r)
        old=pd.read_csv(OUT/f'{label}_nav.csv')
        dates=np.searchsorted(r['cal'],old.session.to_numpy())
        np.testing.assert_allclose(r['nav'][dates],old.nav_toman.to_numpy(),rtol=0,atol=1)
    r=runs['candidate'];periods=[]
    years=np.array([jdatetime.date.fromgregorian(date=pd.Timestamp(str(d)).date()).year for d in r['cal']])
    for y in sorted(set(years)):
        ids=np.flatnonzero(years==y);a,b=int(ids[0]),int(ids[-1]);initial=r['nav'][a-1] if a else 1e8
        periods.append(dict(year=int(y),start=str(r['cal'][a]),end=str(r['cal'][b]),initial_toman=float(initial),
                            final_toman=float(r['nav'][b]),return_fraction=float(r['nav'][b]/initial-1)))
    comparisons=[]
    for day in ['2026-02-24','2026-09-30',cal[-1]]:
        i=np.searchsorted(r['cal'],day,side='right')-1
        comparisons.append(dict(date=str(r['cal'][i]),candidate_toman=float(r['nav'][i]),baseline_toman=float(runs['baseline']['nav'][i])))
    result={'initial_toman':100000000,'start':str(r['cal'][0]),'latest_available_market_day':cal[-1],
        'latest_market_day_jalali':str(jdatetime.date.fromgregorian(date=pd.Timestamp(cal[-1]).date())),
        'candidate':r['metrics'],'baseline':runs['baseline']['metrics'],'same_date_comparison':comparisons,
        'jalali_years':periods,'fees_toman':r['cost_toman'],'slippage_toman':r['slippage_toman'],
        'trades':r['n_trades'],'rebalances':len(r['decisions']),'last_positions':r['terminal_positions'],
        'inactive_calendar_rows_excluded':int((~keep).sum()),'excluded_dates':original['cal'][~keep].tolist(),
        'new_financial_snapshots':sorted(needed),'historical_prefix_reproduced':True,
        'frozen_weights_and_policy_unchanged':True,'research_adjustment_extension':True,'historical_receipt_proven':False,
        'execution':asdict(e),'production_changed':False}
    (OUT/'active_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
