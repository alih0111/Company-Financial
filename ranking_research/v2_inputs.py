"""Verified report snapshots, using the canonical financial and score functions.

Publication-history reconstruction is explicit: observation timestamps are never
rewritten to pretend these archives were collected in the past. Legacy monthly
rows without publication timestamps remain an explicitly disclosed proxy.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'qvt_backtest'),str(ROOT/'provenance_v1'),str(ROOT/'canonical_postgres_v1_2_1/analytics_canonical_v1')]
import compute_metrics as CM
import collect_financial_history as H
from fiscal_calendar import annual_month_of,build_fiscal_calendar,prev_annual_cell
from report_chain_ttm import resolve_ttm
from reconstructed_replay import cutoff_for,resolve_shares


def finite(value):
    return value is not None and math.isfinite(float(value))


def rtt(report,durations,annual,key,metric):
    if key not in durations or (annual is None and prev_annual_cell(durations,*key) is None):
        return None,'unproven_fiscal_window'
    value,provenance=resolve_ttm(report,metric,*key,annual_month=annual,
        is_annual=durations[key]==12,prev_annual_cell=prev_annual_cell(durations,*key))
    return value,provenance


def feature_row(engine,cid,metric,policy):
    """Same point-in-time factor derivation for live and reconstructed snapshots."""
    rep=engine.report_index().get(cid,{})
    if not hasattr(engine,'feature_calendar'):
        rows=[(r['company_id'],r['title'],*CM.fiscal_ym(r['period_end_date'])) for r in engine.codal_titles]
        engine.feature_calendar=build_fiscal_calendar(rows)
    durations_all,calendar=engine.feature_calendar
    durations={key:val for (company,key),val in durations_all.items() if company==cid}
    annual,_,_=annual_month_of(calendar,cid)
    latest=max(rep,key=lambda k:k[0]*12+k[1]) if rep else None
    def get(metric_name,key=latest):
        return rtt(rep,durations,annual,key,metric_name)[0] if key else None
    keys=sorted((k for k in rep if durations.get(k) in (3,6,9,12)),key=lambda k:k[0]*12+k[1],reverse=True)[:policy['history_windows']]
    gaps=[(rep[a]['_period']-rep[b]['_period']).days for a,b in zip(keys,keys[1:])]
    histories=[{f:get(f,k) for f in ('operating_cash_flow','net_profit','operating_profit','revenue')} for k in keys]
    good=[x for x in histories if all(finite(v) for v in x.values()) and x['revenue']>0]
    net_sum=sum(x['net_profit'] for x in good)
    cash_multi=sum(x['operating_cash_flow'] for x in good)/net_sum if len(good)==policy['history_windows'] and net_sum>0 else None
    margins=[x['operating_profit']/x['revenue'] for x in good]
    stability=1-float(np.std(margins))/policy['stability_margin_std_scale'] if len(good)==policy['history_windows'] else None
    cell=rep.get(latest,{})
    own=lambda f:cell.get(f,{}).get(1)
    assets,equity=own('total_assets'),own('total_equity')
    op=get('operating_profit');revenue=get('revenue')
    previous=(latest[0]-1,latest[1]) if latest else None
    prior_rev=get('revenue',previous);prior_op=get('operating_profit',previous)
    status='missing_comparable'
    sales=None
    if finite(revenue) and finite(prior_rev) and prior_rev>0:
        status='low_base' if prior_rev<policy['minimum_growth_base_fraction']*max(revenue,0) else 'comparable'
        if status=='comparable':sales=revenue/prior_rev-1
    # Scale profit improvement by past revenue, including a transition out of
    # losses without constructing an infinite percentage-profit growth.
    improvement=(op-prior_op)/prior_rev if all(finite(x) for x in (op,prior_op,prior_rev)) and prior_rev>0 else None
    period=cell.get('_period')
    denom=own('current_liabilities');ca=own('current_assets')
    ratio=ca/denom if finite(ca) and finite(denom) and denom>0 else None
    liabilities=own('total_liabilities')
    debt=liabilities/assets if finite(liabilities) and finite(assets) and assets>0 else None
    cap=metric.get('market_cap')
    finance=get('finance_cost')
    interest=op/-finance if finite(op) and finite(finance) and finance<0 else None
    return {'company_id':cid,'symbol':metric['symbol'],'as_of':str(engine.as_of),
        'cash_multi':cash_multi,'operating_roa':op/assets if finite(op) and finite(assets) and assets>0 else None,
        'margin_stability':stability,'operating_yield':op/cap if finite(op) and finite(cap) and cap>0 else None,
        'sales_yoy':sales,'operating_improvement':improvement,'sales_growth_status':status,
        'debt_ratio':debt,'current_ratio':ratio,'history_windows':len(good),
        'maximum_history_gap_days':max(gaps,default=9999),
        'financial_period_end':str(period) if period else None,
        'financial_age_days':(engine.as_of-period).days if period else 9999,
        'net_profit_ttm':get('net_profit'),'operating_profit_ttm':op,'total_assets':assets,'total_equity':equity,
        'market_cap':cap,'interest_coverage_ttm':interest,
        'used_older_income_report':bool(keys and keys[0]!=latest),
        'source_valid':True,'quarter_keys':json.dumps(keys),'history_values':json.dumps(histories,allow_nan=False),
        'growth_state':'turnaround' if finite(prior_op) and prior_op<=0 and finite(op) and op>0 else 'normal'}


class ArchiveSnapshots:
    def __init__(self,reports,monthly,identities,market,share_intervals):
        self.reports=reports;self.monthly=monthly;self.identities=identities;self.market=market
        self.intervals={};self.parsed_cache={};self.raw_manifest={}
        for row in share_intervals:self.intervals.setdefault(row['codal_symbol'],[]).append(row)

    def parsed(self,record):
        key=record['company_id'],record['tracing_no']
        if key in self.parsed_cache:return self.parsed_cache[key]
        if record.get('parser_version','').startswith('codal-dynamic-source-'):
            from dynamic_financial import verified_parsed,own_facts
            parsed=verified_parsed(record)
            if own_facts(parsed)!=record['facts']:raise ValueError('archive facts differ from source')
            from qvt_backtest.evidence_paths import resolve_evidence_path
            path=resolve_evidence_path(record['dynamic_manifest_path'])
            self.raw_manifest[str(path)]=H.hashlib.sha256(path.read_bytes()).hexdigest()
            manifest=H.C.read(path)
            for page in manifest['pages']:self.raw_manifest[page['path']]=page['sha256']
            if manifest.get('native_export'):self.raw_manifest[manifest['native_export']['path']]=manifest['native_export']['sha256']
        else:
            html,path=H.C.report_html(record['symbol'],{'TracingNo':record['tracing_no']},False,0)
            parsed=H.P.parse_report(html,parent_only=True) if html else {'statements':{},'period_headers':{}}
            if html:
                # read-only report_html returns a source label, not always a path.
                if Path(str(path)).is_file():self.raw_manifest[str(Path(path).resolve())]=H.hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.parsed_cache[key]=parsed
        return parsed

    def snapshot(self,date,cutoff=None,require_observed=False):
        cutoff=cutoff or cutoff_for(date)
        selected=H.select_asof(self.reports,cutoff)
        if require_observed:
            selected=[r for r in selected if dt.datetime.fromisoformat(r.get('balance_enriched_at') or r.get('recovered_at') or r['observed_at'])<=cutoff]
        groups={}
        for rec in selected:
            if rec['period_end']<=date:groups.setdefault(rec['company_id'],[]).append(rec)
        eng=CM.Engine(dt.date.fromisoformat(date),cutoff,market_pit='trade_date')
        eng.load=lambda:None;eng.superseded=set();eng.share_structure=[]
        eng.companies=[{'company_id':cid,'display_name':identity['symbol'],'is_active':True} for cid,identity in self.identities.items()]
        eng.securities=[{'company_id':cid,'security_id':row['security_id'],'codal_symbol':row['symbol'],'is_active':True,'is_primary':True,'price_rows':1} for cid,row in self.identities.items()]
        eng.codal_titles=[];eng.stmt=[]
        for cid,group in groups.items():
            latest=max(group,key=lambda r:r['period_end'])
            for rec in group:
                period=dt.date.fromisoformat(rec['period_end'])
                eng.codal_titles.append({'company_id':cid,'period_end_date':period,'title':rec['title']})
                facts=list(rec['facts'])
                # Empty newest reports must block reuse of an older complete one.
                facts.append({'metric_code':'_report_marker','statement_type':'income_statement','value':0,'unit':'rial','period_order':1})
                if rec is latest:
                    parsed=self.parsed(rec)
                    for statement,bucket in parsed['statements'].items():
                        headers=parsed['period_headers'].get(statement,[])
                        if not headers or H.F.jalali_to_gregorian(*headers[0])!=period:continue
                        for metric,values in bucket.items():
                            for order,value in values.items():
                                if order>1:
                                    facts.append({'metric_code':metric,'statement_type':statement,'value':value*(1 if metric in H.P.PER_SHARE else 1e6),
                                                  'unit':'rial_per_share' if metric in H.P.PER_SHARE else 'rial','period_order':order})
                for fact in facts:
                    if fact.get('basis','parent')!='parent' or fact['unit'] not in ('rial','rial_per_share'):raise ValueError('unverified financial basis/unit')
                    eng.stmt.append({'company_id':cid,'statement_type':fact['statement_type'],'period_end_date':period,
                        'fiscal_year':None,'fiscal_month':None,'version_no':1,'is_restated':False,
                        'collected_at':dt.datetime.fromisoformat(rec['observed_at']),
                        'metric_code':fact['metric_code'],'period_order':fact['period_order'],'canonical_value':fact['value'],
                        'canonical_unit':fact['unit'],'report_id':rec['tracing_no']})
        eng.monthly=[]
        for row in self.monthly:
            if row['period_end_date']>date:continue
            published=row['published_at']
            if published and dt.datetime.fromisoformat(published)>=cutoff:continue
            if not published and row['source']!='legacy_sqlserver':continue
            if require_observed and row['collected_at'] and dt.datetime.fromisoformat(row['collected_at'])>cutoff:continue
            eng.monthly.append({**row,'period_end_date':dt.date.fromisoformat(row['period_end_date'])})
        eng.prices=[]
        traded={};timing={}
        for cid,row in self.identities.items():
            sym=row['symbol'];rec=self.market.data.get(sym)
            if rec is None:continue
            end=self.market.idx_at(sym,date)
            if end<0:continue
            causal=self.market.asof_factors(sym,date)
            close=rec['c'][:end+1]*causal[:end+1]
            valid=[i for i in range(end+1) if np.isfinite(rec['vol'][i]) and rec['vol'][i]>0 and np.isfinite(close[i]) and close[i]>0]
            if not valid:continue
            last=valid[-1];price_date=rec['dates'][last]
            for i in valid[-30:]:
                eng.prices.append({'security_id':row['security_id'],'trade_date':dt.date.fromisoformat(rec['dates'][i]),
                    'closing_price_rial':float(close[i]),'last_price_rial':float(close[i]),
                    'trade_value_rial':float(rec['tval'][i]) if np.isfinite(rec['tval'][i]) else None,'collected_at':None})
            iv=resolve_shares(self.intervals,sym,cid,row['security_id'],date,price_date)
            traded[cid]=(price_date,float(rec['c'][last]),iv)
            observed=close[max(0,end-60):end+1]
            returns=np.diff(observed)/observed[:-1]
            timing[cid]={'momentum':float(close[end]/close[end-120]-1) if end>=120 and close[end-120]>0 else None,
                'volatility':float(np.std(returns,ddof=1)*np.sqrt(252)) if len(returns)>=59 and np.isfinite(returns).all() else None,
                'tradable':last==end and price_date==date}
        eng.prices.sort(key=lambda row:row['trade_date'],reverse=True)
        metrics=eng.compute()
        index=eng.report_index();eng.report_index=lambda:index
        for cid,metric in metrics.items():
            price_date,price,iv=traded.get(cid,(None,None,None))
            fresh=price_date and (eng.as_of-dt.date.fromisoformat(price_date)).days<=7
            cap=price*iv['shares_outstanding'] if fresh and iv else None
            metric['market_cap']=cap
            metric['shares_outstanding']=iv['shares_outstanding'] if iv else None
            metric['latest_price']=price
            idx=eng.report_index().get(cid,{})
            latest=max(idx,key=lambda k:k[0]*12+k[1]) if idx else None
            eq=idx.get(latest,{}).get('total_equity',{}).get(1)
            for field,den in [('pe',metric['net_profit_ttm']),('ps',metric['revenue_ttm']),('pb',eq)]:
                metric[field]=cap/den if finite(cap) and finite(den) and den>0 else None
            metric['_valuation_prov']={'valuation_mode':'publication_reconstructed','price_date':price_date,'share_evidence':iv.get('evidence') if iv else None,
                'share_knowledge_from':iv.get('knowledge_from') if iv else None,'historical_first_seen_claim':False}
        eng.rank_and_score()
        # Avoid rebuilding the same verified report index for every factor row.
        eng.snapshot_source_reports={cid:[{'tracing_no':r['tracing_no'],'period_end':r['period_end'],'published_at':r['published_at'],'observed_at':r['observed_at']} for r in group] for cid,group in groups.items()}
        return eng,metrics,timing
