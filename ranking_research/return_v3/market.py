"""Compare independently archived official vintages without mutating either."""
import gzip
import hashlib
import json
import numpy as np
import pandas as pd
from .common import SOURCE,ROOT,read,write,sha,checkpoint,done

FIELDS={'o':'priceFirst','h':'priceMax','l':'priceMin','c':'pClosing','vol':'qTotTran5J','tcnt':'zTotTran','tval':'qTotCap'}

def iso(n):
    s=str(n);return f'{s[:4]}-{s[4:6]}-{s[6:8]}'

def markets(out):
    from ranking_research.strategy_search.features import load_market,V
    from ranking_research.top10_six_month.market_adapter import correct_volume
    symbols=pd.read_csv(SOURCE/'new_market_archive/inventory.csv').symbol.tolist()
    old=load_market(symbols)
    original=V.RAW
    try:
        V.RAW=SOURCE/'new_market_archive'
        new=V.MarketData(V.load_reference_data(),symbols=symbols);correct_volume(new)
    finally: V.RAW=original
    # D1 changes source vintage on precisely the dates archived in D0.
    import copy
    revised=copy.deepcopy(old);revised.cal=list(old.cal)
    for sym,r in revised.data.items():
        b=new.data[sym]
        for i,d in enumerate(r['dates']):
            if d not in b['dmap']:continue # explicitly retain old-only observations
            j=b['dmap'][d]
            for k in FIELDS:r[k][i]=b[k][j]
    return old,revised,new

def run(out):
    if done(out,'A'):return
    old,d1,new=markets(out)
    inv=pd.read_csv(SOURCE/'new_market_archive/inventory.csv',dtype={'ins_code':str})
    diagnosis=[];changes=[];calendar={};sources={}
    # Ending and ever-traded cohorts are audit labels, never universe exclusions.
    cohorts={s:set() for s in old.data}
    for label,eid in [('baseline','eval_balanced_control'),('selector','eval_existing_choose')]:
        fills=pd.read_csv(SOURCE/'results'/f'{eid}.fills.csv')
        holds=pd.read_csv(SOURCE/'results'/f'{eid}.holdings.csv.gz')
        for s in fills.symbol.unique():cohorts[s].add(label+'_ever_traded')
        for s in holds[holds.date.eq('2026-04-29')].symbol:cohorts[s].add(label+'_terminal')
    for x in inv.itertuples():
        path=SOURCE/'new_market_archive'/PathName(x.path)
        assert sha(path)==x.archive_sha256
        raw=gzip.decompress(path.read_bytes());assert hashlib.sha256(raw).hexdigest()==x.source_sha256
        records=json.loads(raw)['closingPriceDaily']
        assert all(str(r.get('insCode',x.ins_code))==x.ins_code for r in records)
        sources[str(path)]=x.archive_sha256
        a,b=old.data[x.symbol],new.data[x.symbol]
        apos=[d for i,d in enumerate(a['dates']) if a['vol'][i]>0 and a['tval'][i]>0 and a['c'][i]>0]
        bpos=[d for i,d in enumerate(b['dates']) if b['vol'][i]>0 and b['tval'][i]>0 and b['c'][i]>0]
        missing=[d for d in bpos if '2026-02-25'<d<='2026-04-29' and d not in apos]
        for d in set(a['dates'])&set(b['dates']):
            i,j=a['dmap'][d],b['dmap'][d]
            for k,col in FIELDS.items():
                av,bv=float(a[k][i]),float(b[k][j])
                if not np.isclose(av,bv,rtol=0,atol=0,equal_nan=True):
                    changes.append({'symbol':x.symbol,'security_id':x.security_id,'date':d,'field':col,'old':av,'new':bv,
                        'new_source_hash':x.source_sha256,'consumed_by':'execution/mark/features' if k!='tcnt' else 'audit'})
        for d in bpos:calendar.setdefault(d,set()).add(x.symbol)
        diagnosis.append({'security_id':x.security_id,'symbol':x.symbol,'ins_code':x.ins_code,
            'old_last_trade':max(apos,default=None),'new_last_trade':max(bpos,default=None),
            'old_last_trade_at_evaluation_end':max([d for d in apos if d<='2026-04-29'],default=None),
            'new_last_trade_at_evaluation_end':max([d for d in bpos if d<='2026-04-29'],default=None),
            'first_missing_trade':min(missing,default=None),'positive_trade_count':sum('2026-02-25'<d<='2026-04-29' for d in bpos),
            'positive_trade_count_after_feb25_full_archive':sum(d>'2026-02-25' for d in bpos),
            'official_status_evidence':'not obtained; two official price vintages are not a status notice',
            'cause':'archive_gap' if missing else 'unknown','confidence':'high' if missing else 'insufficient_status_evidence',
            'source_hash':x.source_sha256,'audit_cohort':';'.join(sorted(cohorts[x.symbol]))})
    pd.DataFrame(diagnosis).to_csv(out/'market_gap_diagnosis.csv',index=False)
    pd.DataFrame(changes).to_csv(out/'price_row_revisions.csv',index=False)
    cal=[]
    for d in sorted(set(old.cal)|set(calendar)):
        n=len(calendar.get(d,set()))
        cal.append({'date':d,'positive_trade_securities':n,'archive_row_present':d in old.cal,
            'market_session_inferred':n>0,'official_open_closed_status':'unknown',
            'evidence':'positive volume AND value in official per-security price archive' if n else 'placeholder/absent; cannot establish open or closed',
            'source_manifest':'price_archive_manifest.json','order_validity_certified':False})
    pd.DataFrame(cal).to_csv(out/'calendar_evidence.csv',index=False)
    write(out/'price_archive_manifest.json',{'files':sources,'validated':len(sources),'old_files_overwritten':False})
    write(out/'data_packages.json',{'D0':{'source':str(SOURCE),'contract':'frozen V2'},
        'D1':{'contract':'revise overlapping dates only, retain old-only rows explicitly; identical D0 dates and action sources',
              'changed_cells':len(changes),'changed_rows':len({(r['symbol'],r['date']) for r in changes})},
        'D2':{'status':'blocked_economic_extension','price_endpoint':max(calendar),
              'reason':'new event entitlement, adjustment completeness, security lifecycle and official calendar not certified; no mechanical factor splice'},
        'received_at':'record-specific retrieved_at in V2 inventory; distinct from effective dates',
        'source_price_manifest_sha256':sha(out/'price_archive_manifest.json')})
    checkpoint(out,'A',[out/n for n in ['market_gap_diagnosis.csv','price_row_revisions.csv','calendar_evidence.csv','price_archive_manifest.json','data_packages.json']])
    print('A complete:',len(diagnosis),'securities;',len(changes),'revised cells;',sum(r['positive_trade_count'] for r in diagnosis),'positive trades in gap',flush=True)

def PathName(s):
    # Stored manifests retain their original absolute location; locate copied bytes by exact filename.
    return str(s).replace('\\','/').rsplit('/',1)[-1]
