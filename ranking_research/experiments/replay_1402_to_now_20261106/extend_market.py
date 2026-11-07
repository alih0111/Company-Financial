"""Local-only research extension of the existing mechanical adjustment rule.

No DB/cache replacement. Corporate-action economics and actual cash/share
accounting are NOT inferred from a reference-price reset.
"""
from pathlib import Path
from datetime import datetime,timezone
import gzip,hashlib,json,sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PREV=HERE.parent/'final_strategy_review_20261106';OUT=HERE/'artifacts'
sys.path[:0]=[str(ROOT),str(ROOT/'score_v2_research'),str(PREV)]
import v2lib as V
from repair_marks import last_trade_arrays

LATEST=ROOT/'ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261105T190004086286Z-161d8f98/extraction_manifest.json'


def raw_gaps(records):
    out=[]
    for a,b in zip(records,records[1:]):
        before=float(a.get('pClosing') or 0);after=float(b.get('priceYesterday') or 0)
        if before<=0 or after<=0 or abs(before-after)<=1e-6:continue
        d=str(b['dEven']);day=f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        out.append(dict(date=day,factor=after/before,before=before,after=after))
    return out


def prepare_market():
    OUT.mkdir(exist_ok=True)
    meta=json.loads(LATEST.read_text(encoding='utf8'))
    pack=ROOT/meta['market_package']['path']
    manifest=json.loads((pack/'manifest.json').read_text(encoding='utf8'))
    identity=pd.read_csv(ROOT/'ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv',dtype=str)
    bysymbol={r['symbol']:r for r in manifest['records']}
    ref=V.load_reference_data();md=V.MarketData(ref,symbols=sorted(identity.symbol))
    frozen=dict(np.load(PREV/'artifacts_v2/inputs.npz',allow_pickle=False))
    events=ref['events'];new_events=[];raw_by_symbol={};raw_proof=[];new_days=set();prefix_checks=[]
    for s in frozen['syms']:
        item=bysymbol[str(s)];source=item['sources']['daily'];path=ROOT/source['raw_path']
        with gzip.open(path,'rb') as f:body=f.read()
        assert hashlib.sha256(body).hexdigest()==source['raw_sha256']
        fresh=json.loads(body)['closingPriceDaily']
        rec=md.data[str(s)]
        oldpath=ROOT/'historical_codal_backfill/output/raw_closing_universe'/f"raw_{s}_{rec['ins']}.json.gz"
        with gzip.open(oldpath,'rt',encoding='utf8') as f:old=json.load(f)['closingPriceDaily']
        # Preserve the previously used raw series through its certified cutoff.
        oldmap={int(r['dEven']):r for r in old if int(r['dEven'])<=20260930}
        oldmap.update({int(r['dEven']):r for r in fresh if 20260930<int(r['dEven'])<=20261106})
        rows=sorted(oldmap.values(),key=lambda r:r['dEven']);raw_by_symbol[str(s)]=rows
        sid=md.sym2sid[str(s)];known=events[events.security_id.eq(sid)]
        observed={e['date']:e['factor'] for e in raw_gaps(rows)}
        for day,factor in zip(known.action_date,known.factor):
            day=str(day)
            if '2023-03-21'<=day<='2026-09-30':
                prefix_checks.append(dict(symbol=str(s),date=day,expected=float(factor),observed=observed.get(day),
                                          passed=bool(day in observed and abs(float(factor)-observed[day])<=5.1e-9)))
        suffix=[{**e,'factor':round(e['factor'],8)} for e in raw_gaps(rows) if e['date']>'2026-09-30']
        if any(not np.isfinite(e['factor']) or e['factor']<=0 for e in suffix):raise RuntimeError('Invalid reference-price factor')
        new_events.extend([dict(symbol=str(s),security_id=sid,**e) for e in suffix])
        ev=[(str(d),float(f)) for d,f in zip(known.action_date,known.factor)] + [(e['date'],e['factor']) for e in suffix]
        dates=[]
        for r in rows:
            d=str(r['dEven']);day=f'{d[:4]}-{d[4:6]}-{d[6:8]}';dates.append(day)
            if day>'2026-09-30' and (r.get('qTotTran5J') or 0)>0 and (r.get('qTotCap') or 0)>0:new_days.add(day)
        factors=np.ones(len(rows))
        for day,factor in ev:factors[np.array(dates)<day]*=factor
        rec.update(dates=dates,dmap={d:i for i,d in enumerate(dates)},dset=set(dates),cf=factors,
            c=np.array([float(r.get('pClosing') or 0) for r in rows]),
            o=np.array([float(r.get('priceFirst') or 0) for r in rows]),
            h=np.array([float(r.get('priceMax') or 0) for r in rows]),
            l=np.array([float(r.get('priceMin') or 0) for r in rows]),
            vol=np.array([float(r.get('qTotTran5J') or 0) for r in rows]),
            tcnt=np.array([float(r.get('zTotTran') or 0) for r in rows]),
            tval=np.array([float(r.get('qTotCap') or 0) for r in rows]))
        import datetime as dt
        md.events[sid]=[(dt.date.fromisoformat(d),f) for d,f in ev]
        raw_proof.append(dict(symbol=str(s),path=str(path.relative_to(ROOT)),raw_sha256=source['raw_sha256'],retrieved_at=source['retrieved_at_utc']))
    pd.DataFrame(prefix_checks).to_csv(OUT/'reference_factor_regression.csv',index=False,encoding='utf-8-sig')
    # Existing DB factors are stored to 8 decimal places. Two prior confirmed
    # actions have no longer-observable reset in the retained raw history;
    # preserve their already-used factors rather than silently deleting them.
    missing=[x for x in prefix_checks if x['observed'] is None]
    mismatched=[x for x in prefix_checks if x['observed'] is not None and not x['passed']]
    print(json.dumps({'factor_checks':len(prefix_checks),'numeric_mismatches':len(mismatched),'prior_unobservable_resets_retained':missing},ensure_ascii=False),flush=True)
    assert prefix_checks and not mismatched,'Reference-price factors conflict beyond 8-decimal storage precision'
    cal=np.r_[frozen['cal'],np.array(sorted(new_days))]
    assert len(cal)==len(set(cal))
    md.cal=cal.tolist();S=len(frozen['syms']);T=len(cal)
    data={k:(np.concatenate([v,np.repeat(v[-1:],T-len(v),axis=0)]) if v.ndim and v.shape[0]==len(frozen['cal']) else v.copy()) for k,v in frozen.items()}
    data['cal']=cal
    for j,s in enumerate(frozen['syms']):
        rec=md.data[str(s)];suffix=[e for e in new_events if e['symbol']==s]
        scale=float(np.prod([e['factor'] for e in suffix]))
        # As later reference events scale all earlier prices equally, old NAV
        # must remain invariant. Preserve all old ADV, bars and mark ages.
        data['close'][:len(frozen['cal']),j]=frozen['close'][:,j]*scale
        data['opening'][:len(frozen['cal']),j]=frozen['opening'][:,j]*scale
        rows=raw_by_symbol[str(s)];future=cal[len(frozen['cal']):]
        close,age=last_trade_arrays(rows,cal,[(str(d),float(f)) for d,f in md.events[rec['sid']]])
        data['close'][len(frozen['cal']):,j]=close[len(frozen['cal']):]
        data['mark_age'][len(frozen['cal']):,j]=age[len(frozen['cal']):]
        adv=pd.Series(rec['tval']/10,index=rec['dates']).where(lambda x:x>0).rolling(20,min_periods=10).median().shift(1)
        for i in range(len(frozen['cal']),T):
            k=rec['dmap'].get(str(cal[i]));data['opening'][i,j]=np.nan;data['locked'][i,j]=False;data['adv'][i,j]=0
            if k is not None:
                data['adv'][i,j]=float(adv.iloc[k]) if np.isfinite(adv.iloc[k]) else 0
                if rec['vol'][k]>0 and rec['tval'][k]>0 and rec['o'][k]>0:
                    data['opening'][i,j]=rec['o'][k]*rec['cf'][k]
                    data['locked'][i,j]=rec['h'][k]==rec['l'][k]
        c=pd.Series(data['close'][:,j]).where(lambda x:x>0)
        for h in [63,126]:data[f'mom{h}'][:,j]=c.pct_change(h,fill_method=None)
        data['volatility'][:,j]=c.pct_change(fill_method=None).rolling(63,min_periods=40).std()*np.sqrt(252)
        data['trend'][:,j]=c/c.rolling(126,min_periods=100).mean()-1
    manifest_out={'research_generated_at':datetime.now(timezone.utc).isoformat(),'last_market_date':str(cal[-1]),
        'old_certified_end':'2026-09-30','new_reference_events':new_events,'old_factor_regression_checks':len(prefix_checks),
        'all_rederivable_factors_match_8decimal_precision':not mismatched,
        'prior_unobservable_resets_retained':missing,'source_raw_files':raw_proof,
        'interpretation':'research-only extension of unchanged tsetmc_gap_rule_v1 reference-price ratios; not cash/dividend/rights economics or live certification',
        'database_written':False,'original_cache_changed':False,'latest_financial_manifest':str(LATEST.relative_to(ROOT))}
    (OUT/'market_extension.json').write_text(json.dumps(manifest_out,ensure_ascii=False,indent=2),encoding='utf8')
    pd.DataFrame(new_events).to_csv(OUT/'new_reference_adjustments.csv',index=False,encoding='utf-8-sig')
    np.savez_compressed(OUT/'extended_market.npz',**data)
    print(json.dumps({k:v for k,v in manifest_out.items() if k not in ['source_raw_files','new_reference_events']},ensure_ascii=False),flush=True)
    return data,md,meta


if __name__=='__main__':prepare_market()
