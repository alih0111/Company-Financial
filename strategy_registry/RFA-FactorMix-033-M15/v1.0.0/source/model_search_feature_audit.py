"""Descriptive feature ICs on training labels only; never used to reselect."""
import numpy as np
import pandas as pd
from features import OUT


def main():
    f=dict(np.load(OUT/'features.npz'));d=dict(np.load(OUT/'market_inputs.npz'))
    cut=int(np.searchsorted(d['cal'],'2024-12-31',side='right')-1)
    records=[]
    for h in [63,126]:
        rows=f['sample_rows'];ends=f[f'label_end{h}'];rows=rows[(ends[rows]>=0)&(ends[rows]<=cut)]
        for i in rows:
            y=f[f'y{h}'][i];ok=np.isfinite(y)&f['allowed'][i]
            if ok.sum()<30:continue
            z=f['X'][i,ok].astype(float);z-=z.mean(axis=0)
            r=pd.Series(y[ok]).rank().to_numpy();r-=r.mean()
            den=np.sqrt((z*z).sum(axis=0)*(r*r).sum())
            ic=np.divide(z.T@r,den,out=np.full(z.shape[1],np.nan),where=den>1e-12)
            for name,value in zip(f['names'],ic):
                if np.isfinite(value):records.append(dict(horizon=h,date=str(d['cal'][i]),feature=str(name),ic=float(value)))
    t=pd.DataFrame(records)
    t.to_csv(OUT/'feature_ic_training_by_date.csv',index=False,encoding='utf-8-sig')
    s=t.groupby(['horizon','feature']).ic.agg(['mean','median','std','count']).reset_index().sort_values(['horizon','mean'],ascending=[True,False])
    s.to_csv(OUT/'feature_ic_training_summary.csv',index=False,encoding='utf-8-sig')
    print('TRAINING_ONLY_FEATURE_AUDIT',len(records),'records;',len(s),'feature/horizon summaries')
    print(s.groupby('horizon').head(6).to_string(index=False))


if __name__=='__main__':main()
