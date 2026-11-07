import sys,json,numpy as np,pandas as pd,jdatetime
from bisect import bisect_left
from dataclasses import replace
import os,zipfile,tempfile
ROOT=os.environ.get('RFA_ROOT') or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..'))
ZIP=os.path.join(ROOT,'client/public/strategies/factormix-033/performance/from-1401-monthly15-v1.0.0.zip')
_T=os.path.join(tempfile.gettempdir(),'fm_m15_review')
if not os.path.isdir(os.path.join(_T,'RFA-FactorMix-033-M15-v1.0.0')): zipfile.ZipFile(ZIP).extractall(_T)
V=os.path.join(_T,'RFA-FactorMix-033-M15-v1.0.0')
sys.path.insert(0,V+'/replay')
import engine_snapshot as e
D=dict(np.load(V+'/snapshot_data/active_inputs.npz'));D['p1']=D['candidate_score']
POL=json.load(open(V+'/strategy.locked.json'))
CFG=e.Config(**POL['portfolio']);EX=e.Execution(**POL['execution_assumptions'])
ORIG=e.calendar_schedule
def monthly(day):
    def f(cal,config,start,end):
        ids={start}
        first=jdatetime.date.fromgregorian(date=pd.Timestamp(cal[start]).date())
        last=jdatetime.date.fromgregorian(date=pd.Timestamp(cal[end-1]).date())
        for y in range(first.year,last.year+1):
            for m in range(1,13):
                nom=jdatetime.date(y,m,day).togregorian().isoformat()
                if nom<cal[start]: continue
                k=bisect_left(cal,nom)
                if start<=k<end: ids.add(k)
        return ids
    return f
def run(cfg=CFG,ex=EX,sched=None,data=D,start='2022-03-21',end='2026-11-04'):
    e.calendar_schedule=sched or monthly(15)
    try: return e.simulate(data,cfg,ex,start=start,end=end,capital=1e8)
    finally: e.calendar_schedule=ORIG
WIN=[('full','2022-03-21','2026-11-04'),('sel','2022-03-21','2024-12-31'),('ver','2025-01-01','2026-02-24'),('new','2026-02-25','2026-11-04')]
def summ(r):
    out={}
    cal,nav=r['cal'],r['nav']
    for lab,a,b in WIN:
        i=np.searchsorted(cal,a);j=np.searchsorted(cal,b+'~')
        base=nav[i-1] if i else 1e8; seg=np.r_[base,nav[i:j]]
        out[lab]=round(seg[-1]/seg[0],2)
    ext=np.r_[1e8,nav]; out['maxDD%']=round(100*float(np.min(ext/np.maximum.accumulate(ext)-1)),1)
    out['trades']=r['n_trades']; out['expired']=r['expired_orders']
    return out
