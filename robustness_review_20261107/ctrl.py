import common as c, numpy as np, json
rng=np.random.default_rng(7)
base=c.D['candidate_score'].astype(float)
st={}
for d in [1,15,22]:
    r=c.run(sched=c.monthly(d)); st[d]=(r['stale_decisions_skipped'],r['blocked_order_days'])
print('stale/blocked',st)
def sims(kind,k=300):
    out=[]
    for s in range(k):
        D=dict(c.D)
        noise=rng.random(base.shape)
        if kind=='random': sc=np.where(np.isfinite(base),noise,np.nan)
        else:  # random among top-15 per day: rank-based
            r=np.argsort(np.argsort(-np.nan_to_num(base,nan=-9),axis=1),axis=1)
            sc=np.where(np.isfinite(base)&(r<15),1+noise,np.where(np.isfinite(base),noise*0.5,np.nan))
        D['p1']=sc
        out.append(c.summ(c.run(data=D)))
    f=np.array([o['full'] for o in out]); dd=np.array([o['maxDD%'] for o in out])
    return dict(p5=np.percentile(f,5),med=np.median(f),p95=np.percentile(f,95),share_ge_base=float(np.mean(f>=29.49)),dd_med=np.median(dd), new_med=np.median([o['new'] for o in out]))
res={k:sims(k) for k in ['random','top15random']}
print(json.dumps(res,indent=1,default=float))
json.dump(res,open('ctrl.json','w'),default=float)
