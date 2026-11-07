"""Correct repeated no-trade records; preserve original artifacts unchanged."""
from pathlib import Path
from datetime import datetime,timezone
import gzip,hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]


def last_trade_arrays(records,cal,events):
    r=sorted(records,key=lambda r:r['dEven'])
    dates=np.array([f"{str(x['dEven'])[:4]}-{str(x['dEven'])[4:6]}-{str(x['dEven'])[6:8]}" for x in r])
    good=np.array([(x.get('zTotTran') or 0)>0 and (x.get('qTotCap') or 0)>0 and
                   (x.get('pClosing') or 0)>0 for x in r])
    gd=dates[good]
    prices=np.array([float(x['pClosing']) for x,g in zip(r,good) if g])
    factor=np.ones(len(gd))
    for d,f in events:
        if not np.isfinite(f) or f<=0:raise ValueError('invalid confirmed corporate-action factor')
        factor[gd<d]*=f
    ix=np.searchsorted(gd,cal,side='right')-1
    valid=ix>=0
    close=np.zeros(len(cal));age=np.full(len(cal),9999,dtype=np.int32)
    close[valid]=prices[ix[valid]]*factor[ix[valid]]
    age[valid]=(cal[valid].astype('datetime64[D]')-gd[ix[valid]].astype('datetime64[D]')).astype(int)
    return close,age


def main():
    src=HERE/'artifacts';out=HERE/'artifacts_v2';out.mkdir(exist_ok=True)
    data=dict(np.load(src/'inputs.npz',allow_pickle=False))
    original=data['close'].copy();original_age=data['mark_age'].copy()
    manifest=json.loads((src/'input_manifest.json').read_text(encoding='utf8'))
    refs=ROOT/'score_v2_research/_cache'
    securities=pd.read_parquet(refs/'securities.parquet')
    actions=pd.read_parquet(refs/'corp_actions_confirmed.parquet')
    sidmap=dict(zip(securities.symbol,securities.security_id))
    for j,s in enumerate(data['syms']):
        spec=next(x for x in manifest['market_archives'] if Path(x['path']).name.startswith('raw_'+s+'_'))
        with gzip.open(ROOT/spec['path'],'rt',encoding='utf8') as f:r=json.load(f)['closingPriceDaily']
        ev=actions[actions.security_id.eq(sidmap[s])]
        events=[(str(d),float(f)) for d,f in zip(ev.action_date,ev.factor)]
        close,age=last_trade_arrays(r,data['cal'],events)
        data['close'][:,j]=close;data['mark_age'][:,j]=age
        c=pd.Series(close).where(close>0)
        data['mom63'][:,j]=c.pct_change(63,fill_method=None)
        data['mom126'][:,j]=c.pct_change(126,fill_method=None)
        data['volatility'][:,j]=c.pct_change(fill_method=None).rolling(63,min_periods=40).std()*np.sqrt(252)
        data['trend'][:,j]=c/c.rolling(126,min_periods=100).mean()-1
    correction={'repaired_at_utc':datetime.now(timezone.utc).isoformat(),
        'prior_verification_was_seen':True,'configuration_registry_and_selection_rule_unchanged':True,
        'reason':'Only positive-volume and positive-value records establish fresh executable closing marks. Repeated no-trade rows must not reset price freshness or update marks.',
        'changed_price_cells':int(np.sum(~np.isclose(original,data['close'],equal_nan=True))),
        'changed_mark_age_cells':int(np.sum(original_age!=data['mark_age'])),
        'previous_inputs_sha256':hashlib.sha256((src/'inputs.npz').read_bytes()).hexdigest()}
    manifest['data_revision_note']=correction
    np.savez_compressed(out/'inputs.npz',**data)
    (out/'input_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'normalization_correction.json').write_text(json.dumps(correction,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(correction,indent=2))


if __name__=='__main__':main()
