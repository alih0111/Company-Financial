import numpy as np, blocks as b, common as c, pickle
B,cols,mask=pickle.load(open('cache.pkl','rb'))
cands=pickle.load(open('wf_1.pkl','rb'))+pickle.load(open('wf_2.pkl','rb'))
cal=c.run()['cal']
def tranche(w,ex=None):
    D=b.data_with(b.score(B,mask,w,ex,cols)); return np.mean([c.run(data=D,sched=c.monthly(d))['nav'] for d in (5,15,25)],0)
refs={'033':tranche(b.W033),'equal':tranche({k:1/8 for k in b.W033})}
V=np.array([x[0] for x in cands]); N=np.array([x[1] for x in cands],float)
def seg(nav,a,z):
    i=np.searchsorted(cal,a); j=np.searchsorted(cal,z+'~'); base=nav[i-1] if i else 1e8; return nav[j-1]/base
def ddw(nav,a,z):
    i=np.searchsorted(cal,a); j=np.searchsorted(cal,z+'~'); x=nav[:j]; return float(np.min(x/np.maximum.accumulate(x)-1))
years=[('2023-01-01','2023-12-31'),('2024-01-01','2024-12-31'),('2025-01-01','2025-12-31'),('2026-01-01','2026-11-04')]
print(f'{len(cands)} random weight sets, tranche days 5/15/25')
chain={'wf_best':1,'wf_top20avg':1,'033':1,'equal':1,'median_random':1}
for a,z in years:
    tr=np.array([np.log(seg(n,'2022-03-21',str(int(a[:4])-1)+'-12-31')) for n in N])
    dd=np.array([ddw(n,'2022-03-21',str(int(a[:4])-1)+'-12-31') for n in N])
    sc=tr+0.5*dd
    oos=np.array([seg(n,a,z) for n in N])
    best=np.argmax(sc); top=np.argsort(-sc)[:20]
    r={'wf_best':oos[best],'wf_top20avg':oos[top].mean(),'033':seg(refs['033'],a,z),'equal':seg(refs['equal'],a,z),'median_random':np.median(oos)}
    for k in chain: chain[k]*=r[k]
    pct033=np.mean(oos<r['033'])*100
    print(a[:4],' '.join(f'{k}={v:.2f}' for k,v in r.items()),f'| 033 beats {pct033:.0f}% of random | rank-corr train->test {np.corrcoef(np.argsort(np.argsort(sc)),np.argsort(np.argsort(oos)))[0,1]:.2f}')
print('chain 2023-2026:',{k:round(v,2) for k,v in chain.items()})
full=np.array([n[-1]/1e8 for n in N]); print('full-period random weights: p5 %.1f med %.1f p95 %.1f max %.1f; 033 %.1f equal %.1f'%(*np.percentile(full,[5,50,95]),full.max(),refs['033'][-1]/1e8,refs['equal'][-1]/1e8))
K=list(b.W033)+['mom_12_1']
# which weights correlate with full-period result
for j,k in enumerate(K): print(f'  {k:14s} corr with log full return {np.corrcoef(V[:,j],np.log(full))[0,1]:+.2f}')
top=np.argsort(-full)[:50]; print('top50 avg weights',{k:round(float(V[top,j].mean()),2) for j,k in enumerate(K)})
pickle.dump(dict(V=V,full=full),open('wf_summary.pkl','wb'))
