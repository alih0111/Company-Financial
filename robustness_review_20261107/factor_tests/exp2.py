import numpy as np, blocks as b, common as c, json, pickle
B,cols,mask=pickle.load(open('cache.pkl','rb'))
W=b.W033; DAYS=(5,15,25)
def ev(w,extra=None,days=DAYS):
    s=b.score(B,mask,w,extra,cols); D=b.data_with(s)
    rs=[c.summ(c.run(data=D,sched=c.monthly(d))) for d in days]
    return {k:round(float(np.mean([r[k] for r in rs])),2) for k in rs[0]}
res={'base 033 (avg days 5/15/25)':ev(W),'base day15':ev(W,days=(15,))}
feats=['rsi14','dist_ma50','macd_hist','adv_ratio_20_120','mom_252','mom_21','near_high_252','mom_12_1','log_adv20','size_small','earnings_yield','sales_growth_3m','sales_growth_change30','roe','data_quality','vol_21','avg_trade_value_30d']
for f in feats:
    for a in [.1,.25]:
        res[f'+{f} {a}']=ev(W,{f:a})
    res[f'-{f} .1']=ev(W,{f:-.1})
for k,v in res.items(): print(f'{k:32s}',v)
json.dump(res,open('exp2.json','w'),default=float)
