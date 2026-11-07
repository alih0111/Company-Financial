import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','factor_tests'))
import numpy as np, common as c, blocks as b, time
import os; P=np.load(os.path.join(c.ROOT,'robustness_review_20261107/diagnostics/results_diag/panel_blocks.npz')); Bp=P['blocks'].astype(float); T=Bp.shape[0]
W=np.array(list(b.W033.values())); fr=c.D['candidate_score'].astype(float); mask=np.isfinite(fr)
END='2026-02-24'
def pad(s):
    o=np.full(fr.shape,np.nan); o[:T]=s; o[~mask]=np.nan; return o
cal=c.run(end=END)['cal']
def nav(s):
    D={**c.D,'p1':s,'score_age':np.zeros(len(s),int)}
    return np.mean([c.run(data=D,sched=c.monthly(d),end=END)['nav'] for d in (5,15,25)],0)
def seg(n,a,z):
    i=np.searchsorted(cal,a); j=np.searchsorted(cal,z+'~'); return n[j-1]/(n[i-1] if i else 1e8)
def dd(n,z):
    j=np.searchsorted(cal,z+'~'); x=np.r_[1e8,n[:j]]; return np.min(x/np.maximum.accumulate(x)-1)
rng=np.random.default_rng(11); V=[];N=[]; t=time.time()
while time.time()-t<140:
    v=rng.dirichlet(np.ones(8)*0.7); V.append(v); N.append(nav(pad(Bp@v)))
V=np.array(V); N=np.array(N)
ref={'033':nav(pad(Bp@W)),'equal':nav(pad(Bp.mean(2))),'frozen':nav(fr)}
print(len(V),'random weight sets on panel blocks')
tr=np.array([np.log(seg(n,'2022-03-21','2024-12-31'))+.5*dd(n,'2024-12-31') for n in N])
te=np.array([seg(n,'2025-01-01',END) for n in N])
print('train->test rank corr %.2f'%np.corrcoef(np.argsort(np.argsort(tr)),np.argsort(np.argsort(te)))[0,1])
top=np.argsort(-tr)
for k,v in ref.items():
    t1=np.log(seg(v,'2022-03-21','2024-12-31'))+.5*dd(v,'2024-12-31'); t2=seg(v,'2025-01-01',END)
    print(f'{k:7s} train-score pct {np.mean(tr<t1)*100:3.0f}%  test {t2:.2f} (beats {np.mean(te<t2)*100:3.0f}% of random)  to2024 {seg(v,"2022-03-21","2024-12-31"):.2f}')
print('best-train test %.2f | top20 avg test %.2f | median random test %.2f | p10-p90 %.2f-%.2f'%(te[top[0]],te[top[:20]].mean(),np.median(te),*np.percentile(te,[10,90])))
for yr in ['2023','2024','2025']:
    a=f'{yr}-01-01'; z=f'{yr}-12-31' if yr!='2025' else END
    trs=np.array([np.log(seg(n,'2022-03-21',f'{int(yr)-1}-12-31'))+.5*dd(n,f'{int(yr)-1}-12-31') for n in N]); tes=np.array([seg(n,a,z) for n in N])
    print(yr,'wf best %.2f top20 %.2f median %.2f | 033 %.2f equal %.2f'%(tes[np.argmax(trs)],tes[np.argsort(-trs)[:20]].mean(),np.median(tes),seg(ref['033'],a,z),seg(ref['equal'],a,z)))
names=list(P['block_names']); f=np.array([n[-1] for n in N])
print({k:round(float(np.corrcoef(V[:,j],np.log(f))[0,1]),2) for j,k in enumerate(names)})
