import common as c, numpy as np, json, pandas as pd
import os
B=json.load(open(os.path.join(c.ROOT,'client/public/strategies/factormix-033/performance/benchmarks.json')))
def ser(k): return pd.Series({r['date']:r['closing_price'] for r in B['series'][k]['rows']})
r=c.run(); nav=pd.Series(r['nav'],index=r['cal'])
g=ser('mesghal_toman'); ix=ser('index_toman')
df=pd.DataFrame({'s':nav,'g':g,'i':ix}).sort_index().ffill().loc[nav.index[0]:]
df=df.dropna()
ret=df.pct_change().fillna(0)
out={}
for w in [1,.8,.7,.6,.5,0]:
    # monthly rebalance (by gregorian month)
    v=1.0; ws=np.array([w,1-w]); hold=ws*v; m=None; path=[]
    for d,row in ret.iterrows():
        hold=hold*(1+np.array([row.s,row.g])); v=hold.sum(); path.append(v)
        if d[:7]!=m: hold=ws*v; m=d[:7]
    p=pd.Series(path,index=ret.index)
    dd=(p/p.cummax()-1).min()
    def seg(a,b):
        q=p.loc[:b]; q0=p.loc[:a].iloc[-2] if len(p.loc[:a])>1 else p.iloc[0]
        return round(q.iloc[-1]/q0,2)
    out[f'{int(w*100)}/{int(100-w*100)}']=dict(full=round(p.iloc[-1],2),maxDD=round(100*dd,1),ver=seg('2025-01-01','2026-02-24'),new=seg('2026-02-25','2026-11-04'))
for k,v in out.items(): print(k,v)
# rolling 12m (252 sessions) win rate vs gold and index
s=df.s;W=240
rs=(s/s.shift(W)); rg=(df.g/df.g.shift(W)); ri=(df.i/df.i.shift(W))
m=rs.notna()&rg.notna()
print('rolling~1y: beat gold %.0f%%, beat index %.0f%%, worst 1y strat %.2f'%(100*(rs[m]>rg[m]).mean(),100*(rs[m]>ri[m]).mean(),rs[m].min()))
print('corr daily strat vs gold %.2f, vs index %.2f'%(ret.s.corr(ret.g),ret.s.corr(ret.i)))
json.dump(out,open('blend.json','w'))
