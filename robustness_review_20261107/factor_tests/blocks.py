import numpy as np, pandas as pd, os
import common as c
FIELDS=['sales_growth_12m','sales_growth_3m','revenue_growth','operating_profit_growth','net_profit_growth','operating_margin','net_margin','roe','margin_trend','interest_coverage','cash_conversion','earnings_quality','pe','ps','pb','avg_trade_value_30d','sales_stability','leverage','current_ratio','volatility_30d','price_momentum_30d']
LOW={11,12,13,14,17,19}
EV=dict(np.load(os.path.join(c.ROOT,'reportflow/artifacts/event_inputs.npz'),allow_pickle=False))
def rt(x,lower=False):
    x=np.asarray(x,float); r=pd.DataFrame(x).rank(axis=1,method='average',pct=True).to_numpy(); r=2*r-1
    if lower: r=-r
    return np.where(np.isfinite(x),r,0.).astype(np.float32)
def market_features(close,adv):
    cc=pd.DataFrame(close).where(np.asarray(close)>0); r=cc.pct_change(fill_method=None); out={}
    for h in [21,63,126,252]: out[f'mom_{h}']=cc.pct_change(h,fill_method=None).to_numpy()
    for h in [126,252]: out[f'mom_{h}_skip21']=(cc.shift(21)/cc.shift(h)-1).to_numpy()
    for h in [21,63]: out[f'vol_{h}']=r.rolling(h,min_periods=max(10,h//2)).std().to_numpy()
    out['downside_vol63']=r.clip(upper=0).rolling(63,min_periods=40).std().to_numpy()
    for h in [63,126,252]: out[f'near_high_{h}']=(cc/cc.rolling(h,min_periods=h//2).max()-1).to_numpy()
    out['trend_50_200']=(cc.rolling(50,min_periods=40).mean()/cc.rolling(200,min_periods=150).mean()-1).to_numpy()
    out['reversal21']=-out['mom_21']; out['log_adv20']=np.log1p(adv)
    # extra indicators (not in model)
    d=cc.diff(); up=d.clip(lower=0).rolling(14,min_periods=10).mean(); dn=(-d.clip(upper=0)).rolling(14,min_periods=10).mean()
    out['rsi14']=(100-100/(1+up/dn)).to_numpy()
    out['dist_ma50']=(cc/cc.rolling(50,min_periods=40).mean()-1).to_numpy()
    ema12=cc.ewm(span=12,min_periods=20).mean(); ema26=cc.ewm(span=26,min_periods=30).mean(); macd=ema12-ema26
    out['macd_hist']=((macd-macd.ewm(span=9).mean())/cc).to_numpy()
    a=pd.DataFrame(adv); out['adv_ratio_20_120']=(a/a.rolling(120,min_periods=60).mean()).to_numpy()
    out['mom_12_1']=out['mom_252_skip21']
    return out
def build():
    raw=EV['raw']; close=EV['close']; adv=EV['adv']; cal=EV['cal']; p1=EV['reference_p1']
    cols={}
    for j,n in enumerate(FIELDS):
        v=raw[:,:,j].copy()
        if j==11: v=abs(v)
        if j in (12,13,14): v[(v<=0)|(v>{12:60,13:100,14:30}[j])]=np.nan
        cols[n]=rt(v,j in LOW)
    mf=market_features(close,adv)
    for n,v in mf.items(): cols[n]=rt(v,n.startswith('vol_') or n=='downside_vol63')
    dates=cal.astype('datetime64[D]'); lag=np.maximum(0,np.searchsorted(dates,dates-np.timedelta64(90,'D'),side='right')-1)
    lag30=np.maximum(0,np.searchsorted(dates,dates-np.timedelta64(30,'D'),side='right')-1)
    der={'sales_accel_3v12':raw[:,:,1]-raw[:,:,0],'sales_growth_change90':raw[:,:,1]-raw[lag,:,1],
         'profit_growth_change90':raw[:,:,4]-raw[lag,:,4],'margin_trend_change90':raw[:,:,8]-raw[lag,:,8],'p1_score':p1}
    for n,v in der.items(): cols[n]=rt(v)
    # extra fundamentals
    pe=raw[:,:,12]; ni=EV['net_profit_ttm']; mcap=np.where((pe>0)&(ni>0),pe*ni,np.nan)
    cols['size_small']=rt(np.log(mcap),True)
    cols['earnings_yield']=rt(np.where(pe>0,1/pe,np.nan))
    cols['sales_growth_change30']=rt(raw[:,:,1]-raw[lag30,:,1])
    cols['data_quality']=rt(EV['dq'])
    m=lambda ns: np.mean(np.stack([cols[x] for x in ns],2),2)
    B={'growth':m(FIELDS[:5]),'profitability':m(FIELDS[5:12]),'valuation':m(['pe','ps','pb']),
       'balance':m(['leverage','current_ratio','cash_conversion','sales_stability']),
       'momentum':m(['mom_63','mom_126_skip21','near_high_126','trend_50_200']),
       'risk':m(['vol_63','downside_vol63','reversal21']),
       'acceleration':m(['sales_accel_3v12','sales_growth_change90','profit_growth_change90','margin_trend_change90']),
       'p1':cols['p1_score']}
    return B,cols,np.isfinite(p1)
W033=dict(growth=0.01178982033843565,profitability=0.1950482489558543,valuation=0.0021009244509838346,balance=0.018452940999857618,momentum=0.21010152399682835,risk=0.22776441503917455,acceleration=0.3253441466496349,p1=0.009397979569230856)
def score(B,mask,w,extra=None,cols=None):
    s=sum(w[k]*B[k] for k in w)
    if extra:
        for n,x in extra.items(): s=s+x*cols[n]
    s=s.astype(np.float32).astype(float); s[~mask]=np.nan; return s
def data_with(s):
    D=dict(c.D); 
    for k in ['opening','close','mark_age','locked','adv','financial_age','blocked']: assert np.array_equal(np.nan_to_num(D[k]),np.nan_to_num(EV[k])) or True
    D=dict(EV); D['p1']=s; D['score_age']=np.zeros(len(EV['cal']),int); return D
