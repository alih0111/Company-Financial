import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','factor_tests'))
import numpy as np, common as c, blocks as b, pickle
import os; P=np.load(os.path.join(c.ROOT,'robustness_review_20261107/diagnostics/results_diag/panel_blocks.npz')); Bp=P['blocks'].astype(float); T=Bp.shape[0]
names=list(P['block_names']); W=np.array(list(b.W033.values()))
fr=c.D['candidate_score'].astype(float); mask=np.isfinite(fr)
Be,cols,emask=b.build(); Be=np.stack([Be[k] for k in names],2)[:T]
def pad(s):
    out=np.full(fr.shape,np.nan); out[:T]=s; out[~mask]=np.nan; return out
END='2026-02-24'
def tr(s,days=(5,15,25)):
    D={**c.D,'p1':s,'score_age':np.zeros(len(s),int)}
    navs=[c.run(data=D,sched=c.monthly(d),end=END)['nav'] for d in days]; n=np.mean(navs,0)
    cal=c.run(data=D,end=END)['cal']; i=np.searchsorted(cal,'2025-01-01')
    ext=np.r_[1e8,n]; dd=np.min(ext/np.maximum.accumulate(ext)-1)
    return f'full {n[-1]/1e8:5.1f}  to2024 {n[i-1]/1e8:4.2f}  2025-Feb26 {n[-1]/n[i-1]:4.2f}  DD {100*dd:5.1f}%'
def lag(x,k):
    y=np.full_like(x,np.nan); 
    if k: y[k:]=x[:-k]
    else: y=x.copy()
    return y
print('to 2026-02-24, tranche 5/15/25')
print('frozen candidate      ',tr(fr))
print('panel 033 rebuilt     ',tr(pad(Bp@W)))
print('panel equal           ',tr(pad(Bp.mean(2))))
print('event 033             ',tr(pad(Be@W)))
print('event equal           ',tr(pad(Be.mean(2))))
fund=[0,1,2,3,6]; mkt=[4,5]
for k in [3,10]:
    Lf=Bp.copy(); Lf[:,:,fund]=lag(Bp[:,:,fund],k)
    Lm=Bp.copy(); Lm[:,:,mkt]=lag(Bp[:,:,mkt],k)
    print(f'panel033 lag{k} fund-only',tr(pad(np.nan_to_num(Lf)@W)))
    print(f'panel033 lag{k} mkt-only ',tr(pad(np.nan_to_num(Lm)@W)))
    print(f'panel033 lag{k} all      ',tr(pad(lag(Bp@W,k))))
# swap blocks: panel fundamentals + event? replace growth/accel by event versions
for lab,idx in [('growth',[0]),('accel',[6]),('growth+accel',[0,6]),('profit',[1]),('all fund',fund)]:
    X=Bp.copy(); X[:,:,idx]=Be[:,:,idx]; print(f'panel w/ event {lab:12s}',tr(pad(X@W)))
