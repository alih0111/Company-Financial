"""Post-selection diagnostics, not another selection or independent validation."""
from dataclasses import replace
from datetime import datetime,timezone
import json,sys
import numpy as np
import pandas as pd
from features import OUT,PREV
sys.path.insert(0,str(PREV))
from engine import Config,Execution,simulate
from run_research import dump


def main():
    s=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    spec=s['winner']['selected_model'];cfg=Config(**s['winner']['selected_policy']);e=Execution()
    data=dict(np.load(OUT/'market_inputs.npz'));features=dict(np.load(OUT/'features.npz'))
    value=np.load(OUT/'score_cache'/f"{spec['id']}.npz")['score']
    baseline=next(r['final_toman'] for r in s['verification'] if r['label']=='baseline')
    declaration={'declared_at_utc':datetime.now(timezone.utc).isoformat(),
        'status':'POST_SELECTION_DIAGNOSTICS_NO_RESELECTION','verification_already_seen':True,
        'weight_perturbations':'100 each of multiplicative log-normal sigma .10/.25, seed 20261107',
        'other_checks':['drop each feature block','round weights to multiples of .05',
            'offset 35/40/45','capital 1b and 10b toman','max price age 0/1/3 days',
            'remove top three profitable traded symbols individually; hindsight diagnostic only'],
        'cannot_change_selected_weights_or_policy':True}
    dump(OUT/'stability.protocol.json',declaration)
    rows=[]
    def run(case,score,policy=cfg,execution=e,capital=1e8):
        r=simulate({**data,'p1':score},policy,execution,start='2025-01-01',end='2026-02-24',capital=capital)
        rows.append(dict(case=case,capital=capital,**r['metrics'],n_trades=r['n_trades']))
        return r
    if spec['kind']=='blocks':
        rng=np.random.default_rng(20261107);w=np.array(spec['weights'])
        def score(weight):
            v=features['blocks']@weight;v[~features['allowed']]=np.nan
            return v
        for sigma in [.1,.25]:
            for k in range(100):
                z=w*np.exp(rng.normal(0,sigma,len(w)));z/=z.sum()
                run(f'perturb_{sigma:g}_{k:03}',score(z))
        for j,name in enumerate(features['block_names']):
            z=w.copy();z[j]=0;z/=z.sum();run('drop_block_'+str(name),score(z))
        rounded=np.round(w/.05)*.05;rounded/=rounded.sum()
        run('rounded_weights_5pct',score(rounded))
        dump(OUT/'rounded_weights_diagnostic.json',{'not_selected':True,'weights':rounded.tolist()})
    for offset in [35,40,45]:run(f'offset_{offset}',value,replace(cfg,offset=offset))
    for cap in [1e9,1e10]:
        run(f'capital_{cap:g}',value,capital=cap)
        r=simulate(data,Config('BASE'),e,start='2025-01-01',end='2026-02-24',capital=cap)
        rows.append(dict(case=f'baseline_capital_{cap:g}',capital=cap,**r['metrics'],n_trades=r['n_trades']))
    for age in [0,1,3]:run(f'price_age_{age}',value,execution=replace(e,max_mark_age=age))
    # Determine contributors by cash-flow attribution, not price change alone.
    r=simulate({**data,'p1':value},cfg,e,start='2025-01-01',end='2026-02-24',detail=True)
    pnl={}
    for t in r['trades']:
        pnl.setdefault(t['symbol'],0.)
        pnl[t['symbol']]+=(-t['gross_toman']-t['fee_toman']) if t['side']=='BUY' else (t['gross_toman']-t['fee_toman'])
    for sym,v in r['terminal_positions'].items():pnl[sym]=pnl.get(sym,0)+v
    assert abs(sum(pnl.values())-(r['nav'][-1]-1e8))<.1
    pd.DataFrame([dict(symbol=k,pnl_toman=v) for k,v in pnl.items()]).sort_values('pnl_toman',ascending=False).to_csv(OUT/'candidate_attribution.csv',index=False,encoding='utf-8-sig')
    for sym in sorted(pnl,key=pnl.get,reverse=True)[:3]:
        z=value.copy();z[:,data['syms']==sym]=np.nan;run('hindsight_drop_'+sym,z)
    table=pd.DataFrame(rows);table.to_csv(OUT/'stability_results.csv',index=False,encoding='utf-8-sig')
    summary={}
    for sigma in [.1,.25]:
        z=table[table['case'].str.startswith(f'perturb_{sigma:g}_')]
        if len(z):summary[str(sigma)]={'cases':len(z),'wins':int((z.final_toman>baseline).sum()),
            'return_p05':float(z.total_return.quantile(.05)),'return_median':float(z.total_return.median()),
            'return_p95':float(z.total_return.quantile(.95))}
    dump(OUT/'stability_summary.json',{'post_selection_only':True,'simulations':len(rows),'perturbations':summary,
                                      'selected_model_unchanged':True})
    print(json.dumps({'simulations':len(rows),'perturbations':summary},indent=2))


if __name__=='__main__':main()
