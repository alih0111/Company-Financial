"""Causal, self-financing research simulator in adjusted index units.

Only the experiment directory is writable. Daily-bar fills remain proxies,
not evidence of actual queue priority or actual-share dividend accounting.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from bisect import bisect_left
import numpy as np
import pandas as pd
import jdatetime


@dataclass(frozen=True)
class Config:
    id: str
    family: str = 'core'
    n: int = 5
    method: str = 'p1'
    schedule: str = 'quarter'
    offset: int = 40
    buffer: float = 1.0
    rebalance: str = 'equal'
    momentum: int = 63
    pool: int = 15
    blend: float = .25
    regime: bool = False
    weighting: str = 'equal'


@dataclass(frozen=True)
class Execution:
    fee: float = .005
    slippage: float = .001
    capacity: float | None = .05
    skip_one_price: bool = True
    delay: int = 1
    order_life: int = 5
    max_signal_age: int = 45
    max_mark_age: int = 10
    max_financial_age: int = 550


def configurations():
    result = []
    for n in [3,5,7,10]:
        for offset in [25,35,40,45,55]:
            for rb in ['equal','band']:
                for buf in [1.0,1.6]:
                    result.append(Config(f'C_n{n}_d{offset}_{rb}_b{buf:g}',n=n,offset=offset,rebalance=rb,buffer=buf))
    for n in [5,7]:
        for offset in [35,40,45]:
            for mom in [63,126]:
                for pool in [15,30]:
                    for rb in ['equal','band']:
                        result.append(Config(f'M_n{n}_d{offset}_m{mom}_p{pool}_{rb}',family='momentum',
                                             n=n,offset=offset,momentum=mom,pool=pool,rebalance=rb,buffer=1.6))
    for n in [5,7]:
        for cadence in ['monthly','sessions63']:
            for mom in [63,126]:
                for alpha in [.25,.5]:
                    result.append(Config(f'B_n{n}_{cadence}_m{mom}_a{alpha:g}',family='blend',n=n,
                                         schedule=cadence,momentum=mom,blend=alpha,buffer=1.6,rebalance='band'))
    for n in [5,7]:
        for family in ['core','momentum']:
            result.append(Config(f'R_{family}_n{n}',family=family,n=n,regime=True,buffer=1.6,rebalance='band'))
            result.append(Config(f'V_{family}_n{n}',family=family,n=n,weighting='inverse_vol',buffer=1.6,rebalance='band'))
    for n in [5,7]:
        for off in [35,40,45]:
            result.append(Config(f'P3_n{n}_d{off}',method='p3',n=n,offset=off))
    result += [Config('BASE',n=5),Config('EW254',family='equal_universe',n=254),
               Config('MOM_ONLY',family='momentum',n=10,pool=254),
               Config('TOP1_CONTROL',n=1,schedule='monthly')]
    assert len(set(c.id for c in result)) == len(result)
    return result


def calendar_schedule(cal, config, start, end):
    """Initial decision is explicit; a prior quarter cannot disappear from start."""
    ids = {start}
    if config.schedule == 'sessions63':
        ids |= set(range(start,end,63))
    elif config.schedule == 'monthly':
        for i in range(start+1,end):
            if cal[i][:7] != cal[i-1][:7]:
                ids.add(i-1)
    else:
        for year in range(1399,1407):
            for month,day in [(3,31),(6,31),(9,30)]:
                qe = jdatetime.date(year,month,day).togregorian()
                k = bisect_left(cal,(qe+timedelta(days=config.offset)).isoformat())
                if start <= k < end:
                    ids.add(k)
            qe = jdatetime.date(year+1,1,1).togregorian()-timedelta(days=1)
            k = bisect_left(cal,(qe+timedelta(days=config.offset)).isoformat())
            if start <= k < end:
                ids.add(k)
    return ids


def order_for(data,i,cfg,execution):
    score = data[cfg.method][i].copy()
    eligible = np.isfinite(score) & (data['close'][i] > 0)
    eligible &= data['mark_age'][i] <= execution.max_mark_age
    eligible &= data['financial_age'][i] <= execution.max_financial_age
    if cfg.family == 'equal_universe':
        eligible = (data['close'][i]>0) & (data['mark_age'][i]<=execution.max_mark_age)
        score = np.ones(len(score))
    ix = np.flatnonzero(eligible)
    tie = data['symbol_index']
    fundamental = ix[np.lexsort((tie[ix],-score[ix]))]
    if cfg.family == 'momentum':
        pool = fundamental[:cfg.pool]
        momentum = data[f'mom{cfg.momentum}'][i,pool]
        pool = pool[np.isfinite(momentum) & (momentum>0)]
        return pool[np.lexsort((tie[pool],-data[f'mom{cfg.momentum}'][i,pool]))]
    if cfg.family == 'blend':
        m = data[f'mom{cfg.momentum}'][i]
        ix = ix[np.isfinite(m[ix])]
        if len(ix) == 0:
            return ix
        f = pd.Series(score[ix]).rank(pct=True).to_numpy()
        t = pd.Series(m[ix]).rank(pct=True).to_numpy()
        mix = (1-cfg.blend)*f+cfg.blend*t
        return ix[np.lexsort((tie[ix],-mix))]
    return fundamental


def target_for(data,i,cfg,execution,q,nav):
    order = order_for(data,i,cfg,execution)
    ranks = {int(j):r for r,j in enumerate(order,1)}
    keep = [int(j) for j in order if q[j]>1e-12 and ranks[int(j)]<=int(np.ceil(cfg.n*cfg.buffer))]
    selected = keep[:cfg.n]
    for j in order:
        if len(selected)>=cfg.n:
            break
        if int(j) not in selected:
            selected.append(int(j))
    target = np.zeros(len(q))
    equity = 1.0
    if cfg.regime:
        valid = np.isfinite(data['trend'][i]) & (data['mark_age'][i]<=execution.max_mark_age)
        breadth = float(np.mean(data['trend'][i,valid]>0)) if valid.any() else 0
        equity = 1.0 if breadth>=.4 else .5
    if selected:
        w = np.ones(len(selected))
        if cfg.weighting == 'inverse_vol':
            v = data['volatility'][i,selected]
            w = 1/np.where(np.isfinite(v),np.maximum(v,.15),.5)
            w /= w.sum()
            # Bounded relative to equal weight; no hidden concentration optimization.
            w = np.clip(w,.5/len(w),1.5/len(w))
        w /= w.sum()
        # When fewer than n pass, leave the missing slots in cash.
        target[selected] = w*equity*min(1,len(selected)/cfg.n)
    if cfg.rebalance == 'replace':
        survivors = [j for j in selected if q[j]>1e-12]
        entrants = [j for j in selected if q[j]<=1e-12]
        curw = q*data['close'][i]/nav
        target[survivors] = curw[survivors]
        if entrants:
            target[entrants] = max(0,equity-target[survivors].sum())/len(entrants)
    current = q*data['close'][i]/nav
    pending = ((q>1e-12)&(target==0)) | (target>0)
    if cfg.rebalance == 'band':
        pending &= ((q<=1e-12)|(target==0)|(np.abs(current-target)>.05))
    return target,pending,selected


def simulate(data,cfg,execution=Execution(),start='2021-04-03',end='2026-02-24',
             capital=100_000_000.0,detail=False,choice_schedule=None):
    cal = data['cal'].tolist()
    a,b = bisect_left(cal,start),bisect_left(cal,end+'~')
    if a>=b:
        raise ValueError('empty evaluation window')
    schedule = calendar_schedule(cal,cfg,a,b)
    q = np.zeros(len(data['syms']))
    cash = float(capital)
    navs=[];cashs=[];counts=[];trades=[];decisions=[];holdings=[]
    pending = np.zeros(len(q),bool);target=np.zeros(len(q))
    eligible_i=b;expires=b;decision_day='';cost=0.;slipcost=0.;gross_turnover=0.;ntrades=0
    expired=0;blocked_days=0;stale_decisions=0;last_cfg=cfg
    for i in range(a,b):
        op = data['opening'][i]
        if pending.any() and i>=eligible_i:
            if i>expires:
                expired += int(pending.sum())
                pending[:] = False
            else:
                good = np.isfinite(op)&(op>0)
                if execution.skip_one_price:
                    good &= ~data['locked'][i]
                active = pending&good
                blocked_days += int(np.sum(pending&~good))
                # Never use today's close to size an order at today's opening.
                marks=data['close'][max(i-1,0)].copy()
                marks[good] = op[good]
                wealth=cash+float(q@marks)
                desired=target*wealth
                need=desired-q*marks
                cap=np.full(len(q),np.inf) if execution.capacity is None else execution.capacity*data['adv'][i]
                filled=np.zeros(len(q),bool)
                for j in np.flatnonzero(active & (need < -1)):
                    base=min(-need[j],q[j]*op[j],cap[j])
                    if base<=1:
                        continue
                    u=base/op[j];gross=base*(1-execution.slippage);fee=gross*execution.fee
                    q[j]-=u;cash+=gross-fee;cost+=fee;slipcost+=base-gross;gross_turnover+=base;ntrades+=1
                    filled[j]=base>=-need[j]-1 or q[j]<1e-10
                    if detail:trades.append(dict(session=cal[i],decision=decision_day,symbol=str(data['syms'][j]),side='SELL',
                        gross_toman=gross,fee_toman=fee,slippage_toman=base-gross,units=u,index_price=op[j],adv_toman=float(data['adv'][i,j])))
                buy_ids=np.flatnonzero(active & (need > 1))
                base_need=np.minimum(np.maximum(need[buy_ids],0),cap[buy_ids])
                required=float(base_need.sum())*(1+execution.slippage)*(1+execution.fee)
                fraction=min(1,cash/required) if required>0 else 0
                for j,base in zip(buy_ids,base_need*fraction):
                    if base<=1:
                        continue
                    u=base/op[j];gross=base*(1+execution.slippage);fee=gross*execution.fee
                    q[j]+=u;cash-=gross+fee;cost+=fee;slipcost+=gross-base;gross_turnover+=base;ntrades+=1
                    # Fee-driven pro-rata shortage completes; capacity or unfunded
                    # orders remain pending while exits are still outstanding.
                    filled[j]=(base_need[np.searchsorted(buy_ids,j)]>=need[j]-1 and
                               (fraction>=1-1e-9 or not np.any(active&(need<-1)&~filled)))
                    if detail:trades.append(dict(session=cal[i],decision=decision_day,symbol=str(data['syms'][j]),side='BUY',
                        gross_toman=gross,fee_toman=fee,slippage_toman=gross-base,units=u,index_price=op[j],adv_toman=float(data['adv'][i,j])))
                filled |= active & (np.abs(need)<=1)
                pending[filled]=False
        nav=cash+float(q@data['close'][i])
        if cash < -1e-4 or (q < -1e-7).any() or not np.isfinite(nav) or nav<=0:
            raise AssertionError((cal[i],cash,nav))
        navs.append(nav);cashs.append(cash);counts.append(int((q>1e-10).sum()))
        if detail:
            holdings.append(q*data['close'][i])
        if choice_schedule is not None and cal[i] in choice_schedule:
            cfg=choice_schedule[cal[i]]
            schedule = calendar_schedule(cal,cfg,i,b)
            schedule.add(i)
        if i in schedule:
            if data['score_age'][i]>execution.max_signal_age:
                stale_decisions+=1
                continue
            target,pending,selected=target_for(data,i,cfg,execution,q,nav)
            eligible_i=i+execution.delay
            expires=eligible_i+execution.order_life-1
            decision_day=cal[i]
            if detail:decisions.append(dict(session=cal[i],config=cfg.id,signal_date=str(data['signal_dates'][i]),
                                           signal_age=int(data['score_age'][i]),nav_toman=nav,
                                           target=';'.join(str(data['syms'][j]) for j in selected),
                                           weights=';'.join(f'{target[j]:.8f}' for j in selected)))
    navs=np.array(navs)
    result={'cal':np.array(cal[a:b]),'nav':navs,'cash':np.array(cashs),'positions':np.array(counts),
            'metrics':metrics(np.array(cal[a:b]),navs,capital), 'trades':trades,'decisions':decisions,
            'cost_toman':cost,'slippage_toman':slipcost,'gross_turnover_toman':gross_turnover,
            'n_trades':ntrades,'expired_orders':expired,'blocked_order_days':blocked_days,
            'stale_decisions_skipped':stale_decisions,'terminal_cash':cash,
            'terminal_positions':{str(data['syms'][j]):float(q[j]*data['close'][b-1,j]) for j in np.flatnonzero(q>1e-10)}}
    if detail:
        result['holding_values']=np.stack(holdings)
    return result


def metrics(cal,nav,capital=None):
    initial=float(nav[0] if capital is None else capital)
    extended=np.r_[initial,nav]
    years=(pd.Timestamp(str(cal[-1]))-pd.Timestamp(str(cal[0]))).days/365.25
    dd=float(np.min(extended/np.maximum.accumulate(extended)-1))
    returns=extended[1:]/extended[:-1]-1
    sd=float(returns.std(ddof=1)) if len(returns)>1 else 0
    return dict(start=str(cal[0]),end=str(cal[-1]),final_toman=float(nav[-1]),
                total_return=float(nav[-1]/initial-1),cagr=float((nav[-1]/initial)**(1/years)-1) if years else 0,
                max_drawdown=dd,sharpe_zero_rf=float(returns.mean()/sd*np.sqrt(252)) if sd else 0,
                annual_volatility=sd*np.sqrt(252))


def window_metrics(run,start,end):
    cal=run['cal'];a=np.searchsorted(cal,start);b=np.searchsorted(cal,end+'~')
    initial=run['nav'][a-1] if a else 100_000_000.
    return metrics(cal[a:b],run['nav'][a:b],initial)


def save_run(path,run):
    pd.DataFrame(dict(session=run['cal'],nav_toman=run['nav'],cash_toman=run['cash'],n_positions=run['positions'])).to_csv(str(path)+'_nav.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(run['trades']).to_csv(str(path)+'_trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(run['decisions']).to_csv(str(path)+'_decisions.csv',index=False,encoding='utf-8-sig')
