import numpy as np, blocks as b, common as c, json, time, pickle
B,cols,mask=b.build()
pickle.dump((B,cols,mask),open('cache.pkl','wb'),protocol=4)
W=b.W033
def ev(w,extra=None,days=(15,)):
    s=b.score(B,mask,w,extra,cols); D=b.data_with(s)
    rs=[c.summ(c.run(data=D,sched=c.monthly(d))) for d in days]
    return rs[0] if len(rs)==1 else {k:round(float(np.mean([r[k] for r in rs])),2) for k in rs[0]}
t=time.time(); base=ev(W); print('base',base,time.time()-t)
res={'base':base}
# ablation and scaling
for k in W:
    for f,lab in [(0,'zero'),(0.5,'x0.5'),(1.5,'x1.5'),(2,'x2')]:
        w=dict(W); w[k]=W[k]*f if W[k]>0.05 else (0 if f==0 else 0.1*f)
        res[f'{k} {lab}']=ev(w)
res['equal blocks']=ev({k:1/8 for k in W})
res['mom+risk only']=ev({**{k:0 for k in W},'momentum':.5,'risk':.5})
res['fund only (acc+prof+growth)']=ev({**{k:0 for k in W},'acceleration':.5,'profitability':.3,'growth':.2})
res['033 + valuation .15']=ev({**W,'valuation':.15})
for k,v in res.items(): print(f'{k:30s}',v)
json.dump(res,open('exp1.json','w'),default=float)
