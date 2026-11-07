"""One fixed ridge objective, equal date weights, purged source/label clocks."""
import numpy as np
import pandas as pd

def rank_center(d, columns):
    return d.groupby('decision_time')[columns].rank(method='average',pct=True)-.5

def mature_training(d, cutoff):
    lo=(pd.Timestamp(cutoff)-pd.DateOffset(months=36)).date().isoformat()
    z=d[d.decision_time.ge(lo)&d.decision_time.lt(cutoff)&d.label_end.lt(cutoff)&d.label.notna()].copy()
    if len(z):
        assert z.label_end.max()<cutoff
        assert pd.to_datetime(z.source_max,utc=True).max()<pd.Timestamp(cutoff,tz='Asia/Tehran')
    counts=z.groupby('decision_time').size()
    return z[z.decision_time.isin(counts[counts.ge(20)].index)].copy()

def ridge(d, columns):
    """min sum_i w_i (y_i-intercept-X_i beta)^2 + 1.0 ||beta||^2."""
    assert d.decision_time.nunique()>=24
    x=rank_center(d,columns).to_numpy(float)
    y=d.groupby('decision_time').label.rank(method='average',pct=True).to_numpy()-.5
    counts=d.groupby('decision_time').decision_time.transform('size').to_numpy(float)
    w=1/(d.decision_time.nunique()*counts)
    design=np.column_stack([np.ones(len(x)),x])
    penalty=np.diag([0.]+[1.]*len(columns))
    beta=np.linalg.solve(design.T@(w[:,None]*design)+penalty,design.T@(w*y))
    return beta, {'rows':len(d),'dates':d.decision_time.nunique(),'sum_weights':float(w.sum()),
                  'effective_sample_unit':'date; overlapping forward labels remain dependent'}

def available_session(publication, calendar):
    """Exact timestamp: decision at local day end; day-only: next session."""
    p=pd.Timestamp(publication)
    if p.tzinfo is None:
        if len(str(publication))!=10:raise ValueError('timestamp without timezone')
        return next((s for s in calendar if s>str(publication)),None)
    day=p.tz_convert('Asia/Tehran').date().isoformat()
    return next((s for s in calendar if s>=day),None)
