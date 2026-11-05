"""Current V2 preview: verified financial history + current canonical market/shares.

Separate from frozen historical price files. Does not store scores in serving DB.
Never mixes report revisions or uses unverified legacy financial facts.
"""
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
os.environ.setdefault('CDF_PILOT_DB','company_financial_analytics_shadow_v121')
from v2_inputs import CM,H,feature_row
from v2_engine import score_frame
from verified_financial_inputs import eligible_cache_facts


def main():
    out=Path(H.C.read(HERE/'output/formula_v2_running.json')['run_path'])
    policy=H.C.read(out/'protocol.json')
    cutoff=dt.datetime.now(dt.timezone.utc);asof=cutoff.astimezone(ZoneInfo('Asia/Tehran')).date()
    engine=CM.Engine(asof,cutoff);engine.load=lambda:None;engine.superseded=set()
    with CM.pg_pilot_conn() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        def rows(query,params=()):
            cur=db.execute(query,params)
            return [dict(zip([c.name for c in cur.description],row)) for row in cur.fetchall()]
        engine.companies=rows('SELECT id::text AS company_id, display_name, is_active FROM core.companies')
        engine.securities=rows('''SELECT s.id::text AS security_id,s.company_id::text AS company_id,
            s.codal_symbol,s.is_active,s.is_primary,
            (SELECT count(*) FROM market.price_observations p WHERE p.security_id=s.id) AS price_rows
            FROM core.securities s''')
        engine.prices=rows('''WITH daily AS (
            SELECT DISTINCT ON (security_id,trade_date) security_id::text,trade_date,collected_at,
                closing_price_rial,last_price_rial,trade_value_rial
            FROM market.price_observations WHERE price_series='adjusted' AND trade_date<=%s AND collected_at<=%s
            ORDER BY security_id,trade_date,collected_at DESC,id DESC)
            SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY security_id ORDER BY trade_date DESC) AS rn FROM daily) ranked
            WHERE rn<=250 ORDER BY security_id,trade_date DESC''',(asof,cutoff))
        engine.share_structure=rows('''SELECT id,security_id::text,company_id::text,shares_count,market_value_rial,
            eps_rial,as_of_date,source,collected_at FROM core.share_structure WHERE as_of_date<=%s AND collected_at<=%s''',(asof,cutoff))
        engine.tsetmc_current=rows('''SELECT id,security_id::text,shares_count,collected_at,source
            FROM market.tsetmc_current_shares WHERE collected_at<=%s''',(cutoff,))
    monthly=H.C.read(out/'input_monthly.json')
    engine.monthly=[{**r,'period_end_date':dt.date.fromisoformat(r['period_end_date'])} for r in monthly
        if r['period_end_date']<=asof.isoformat() and (not r['published_at'] or dt.datetime.fromisoformat(r['published_at'])<=cutoff)
        and (not r['collected_at'] or dt.datetime.fromisoformat(r['collected_at'])<=cutoff)]
    reports=H.select_asof(H.C.read(out/'input_reports.json'),cutoff)
    versions={};catalogs={};cache_manifest={}
    for r in reports:
        observed=dt.datetime.fromisoformat(r.get('balance_enriched_at') or r.get('recovered_at') or r['observed_at'])
        if observed>cutoff or r['period_end']>asof.isoformat():continue
        versions[(r['company_id'],r['period_end'])]={'published_at':r['published_at'],'observed_at':observed.isoformat(),
            'tracing_no':r['tracing_no'],'title':r['title'],'facts':r['facts'],'source':'verified_archived_report'}
    cache_records=[]
    for path in sorted((H.C.OUT/'facts').glob('*.json')):
        rec=H.C.read(path)
        if rec.get('rules_version')!=3:continue
        cache_manifest[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        cache_records.append(rec)
        if rec['company_id'] not in catalogs:
            selected=H.C.select(H.C.letters_for(rec['symbol'],False,0),cutoff)
            catalogs[rec['company_id']]=selected
        titles={str(letter['TracingNo']):letter['Title'] for _,(_,letter) in catalogs[rec['company_id']]}
        groups={}
        for fact in eligible_cache_facts(rec,asof,cutoff):groups.setdefault(fact['period_end_date'],[]).append(fact)
        for period,facts in groups.items():
            f=facts[0];old=versions.get((rec['company_id'],period))
            if old and dt.datetime.fromisoformat(old['published_at'])>dt.datetime.fromisoformat(f['published_at']):continue
            # One entire report wins; missing metrics never borrow an older revision.
            converted=[{'metric_code':f['metric_code'],'statement_type':f['statement_type'],
                'period_order':f['period_order'],'unit':'rial_per_share' if f['unit']=='rial_per_share' else 'rial',
                'value':f['value']*(1 if f['unit']=='rial_per_share' else 1e6),'basis':'parent'} for f in facts]
            # Two proven extracts of the SAME report are not two revisions.
            # A partial older cache must not erase a newly verified superset.
            # Overlapping values must agree; never union conflicting extracts.
            if old and old['tracing_no']==f['tracing_no'] and dt.datetime.fromisoformat(old['published_at'])==dt.datetime.fromisoformat(f['published_at']):
                identity=lambda x:(x['statement_type'],x['metric_code'],x['period_order'])
                prior={identity(x):x['value'] for x in old['facts']}
                cached={identity(x):x['value'] for x in converted}
                import math
                if any(k in cached and not math.isclose(float(v),float(cached[k]),rel_tol=1e-12,abs_tol=1) for k,v in prior.items()):
                    raise ValueError('same_report_extract_conflict')
                if set(cached)<=set(prior):continue
                if not set(prior)<=set(cached):
                    # Both inputs passed their native/dynamic source checks,
                    # parent/unit admission, exact tracing/publication identity
                    # and overlap agreement above. Retain their distinct source
                    # lineage rather than presenting the union as one extract.
                    combined={identity(x):x for x in old['facts']}
                    combined.update({identity(x):x for x in converted})
                    versions[(rec['company_id'],period)]={**old,'facts':list(combined.values()),
                        'observed_at':max(old['observed_at'],max(g['collected_at'] for g in facts),key=dt.datetime.fromisoformat),
                        'source':'verified_same_report_extract_union',
                        'source_parts':[{'source':old['source'],'tracing_no':old['tracing_no']},
                            {'source':f['source'],'sha256':f['sha256'],'tracing_no':f['tracing_no']}],
                        'union_checks':['same_parent_report','same_publication','normalized_units','overlap_agreement']}
                    continue
            versions[(rec['company_id'],period)]={'published_at':f['published_at'],
                'observed_at':max(g['collected_at'] for g in facts),'tracing_no':f['tracing_no'],
                'title':titles.get(str(f['tracing_no']),''),'facts':converted,'source':'verified_current_cache'}
    # Admit empty catalog markers so a newer known report cannot fall back to old earnings.
    current=H.C.read(out/'input_family.json');metadata={r['company_id']:r for r in current['ranked']+current['unscored']}
    for cid,meta in metadata.items():
        selected=catalogs.setdefault(cid,H.C.select(H.C.letters_for(meta['symbol'],False,0),cutoff))
        for period,(published,letter) in selected:
            if period>asof:continue
            key=(cid,str(period));old=versions.get(key)
            if old is None or published>dt.datetime.fromisoformat(old['published_at']):
                versions[key]={'published_at':published.isoformat(),'observed_at':cutoff.isoformat(),
                    'tracing_no':str(letter['TracingNo']),'title':letter['Title'],'facts':[],'source':'unparsed_known_report_marker'}
    engine.stmt=[];engine.codal_titles=[];lineage=[]
    for (cid,period),record in versions.items():
        if not record['title']:continue
        engine.codal_titles.append({'company_id':cid,'period_end_date':dt.date.fromisoformat(period),'title':record['title']})
        for fact in [*record['facts'],{'metric_code':'_report_marker','statement_type':'income_statement','period_order':1,'unit':'rial','value':0}]:
            engine.stmt.append({'company_id':cid,'statement_type':fact['statement_type'],'period_end_date':dt.date.fromisoformat(period),
                'fiscal_year':None,'fiscal_month':None,'is_restated':False,'version_no':1,
                'collected_at':dt.datetime.fromisoformat(record['observed_at']),
                'metric_code':fact['metric_code'],'period_order':fact['period_order'],'canonical_value':fact['value'],
                'canonical_unit':fact['unit'],'report_id':str(record['tracing_no'])})
        lineage.append({'company_id':cid,'period':period,**{k:v for k,v in record.items() if k!='facts'}})
    metrics=engine.compute();index=engine.report_index();engine.report_index=lambda:index
    prices={}
    for row in engine.prices:prices.setdefault(row['security_id'],[]).append(row)
    features=[]
    for cid,metric in metrics.items():
        if not metric.get('symbol'):continue
        feature=feature_row(engine,cid,metric,policy)
        meta=metadata.get(cid,{})
        history=prices.get(metric['security_id'],[])
        latest=history[0] if history else None
        closes=np.array([float(r['closing_price_rial']) if r['closing_price_rial'] is not None else np.nan for r in history])
        daily=np.diff(closes[:61][::-1])/closes[:61][::-1][:-1]
        mom=float(closes[0]/closes[120]-1) if len(closes)>120 and np.isfinite(closes[[0,120]]).all() and closes[120]>0 else None
        vol=float(np.std(daily,ddof=1)*np.sqrt(252)) if len(daily)>=59 and np.isfinite(daily).all() else None
        age=(asof-latest['trade_date']).days if latest else 9999
        if age>7:feature['market_cap']=None;feature['operating_yield']=None
        feature.update(model_family=meta.get('model_family','unknown'),industry=meta.get('industry'),
            industry_pit_valid=bool(meta.get('industry')),momentum=mom,volatility=vol,
            tradable=bool(latest and latest['trade_date']==asof and latest['trade_value_rial'] and latest['trade_value_rial']>0),
            market_date=str(latest['trade_date']) if latest else None,
            valuation_provenance=json.dumps(metric['_valuation_prov'],default=str),
            industry_observed_at=cutoff.isoformat())
        features.append(feature)
    preview=score_frame(pd.DataFrame(features),policy)
    # Check the economic score independently from the vectorized kernel.
    for row in preview.loc[preview.eligible].to_dict('records'):
        for model,weights in policy['models'].items():
            score=sum(sum(row['s_'+f] for f in policy['blocks'][b])/len(policy['blocks'][b])*w for b,w in weights.items())
            if abs(score-row[model])>1e-9:raise ValueError('current scalar score mismatch')
    for path,sha in cache_manifest.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('current cache changed during preview')
    preview.sort_values(['eligible','BALANCED','symbol'],ascending=[False,False,True]).to_csv(out/'current_live_preview.csv',index=False,encoding='utf-8-sig')
    H.C.write(out/'current_live_lineage.json',lineage)
    H.C.write(out/'current_cache_manifest.json',cache_manifest)
    H.C.write(out/'current_market_snapshot.json',{'cutoff':cutoff.isoformat(),'prices':engine.prices,
        'share_structure':engine.share_structure,'tsetmc_current':engine.tsetmc_current})
    receipt={'as_of':str(asof),'cutoff':cutoff.isoformat(),'rows':len(preview),'eligible':int(preview.eligible.sum()),
        'market_date':str(max(r['trade_date'] for r in engine.prices)),'historical_price_cache_used':False,
        'legacy_financial_facts_used':False,'current_catalog_blocks_stale_revision':True,
        'industry_scope':'current observation only; never injected into historical analysis',
        'production_changed':False,'real_orders':0,'scalar_score_check':'passed'}
    receipt['implementation_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Path(__file__),HERE/'v2_inputs.py',HERE/'v2_engine.py',Path(CM.__file__)]}
    H.C.write(out/'current_live_receipt.json',receipt)
    print(json.dumps(receipt))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8');main()
