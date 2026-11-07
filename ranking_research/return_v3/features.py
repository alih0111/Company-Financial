"""Source-versioned previous independent-quarter S2, never lagged decision rows."""
import functools
import json
import re
import numpy as np
import pandas as pd
from .common import SOURCE,ROOT,read,write,sha

def augment(out,d):
    target=out/'variant_panel.parquet'
    if target.exists():return pd.read_parquet(target)
    from ranking_research.strategy_search.features import HIST
    from ranking_research.return_v2.events import independent
    from fiscal_calendar import normalize_digits,parse_title
    from pathlib import Path
    path=Path(read(HIST/'registration.json')['inputs'])/'input_reports.json'
    records=read(path);index={str(r['tracing_no']):r for r in records}
    validated=set(pd.read_parquet(SOURCE/'pit_report_versions.parquet').report_id.astype(str))
    @functools.lru_cache(None)
    def state(raw):
        rep={};durations={};proof={}
        for s in json.loads(raw):
            trace=str(s['tracing_no']);r=index.get(trace)
            if not r or trace not in validated:continue
            assert pd.Timestamp(r['published_at'])==pd.Timestamp(s['published_at'])
            title=normalize_digits(r['title']);part=title.split('منتهی به',1)[-1]
            m=re.search(r'(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})',part)
            if not m:continue
            key=(int(m[1]),int(m[2]));values={}
            for f in r['facts']:
                if f.get('basis')=='parent' and f.get('unit')=='rial' and f.get('period_order',1)==1:
                    values[f['metric_code']]={1:float(f['value'])}
            # Later source version replaces only that same fiscal period.
            if key not in proof or pd.Timestamp(r['published_at'])>pd.Timestamp(proof[key]['published_at']):
                rep[key]=values;durations[key]=parse_title(title)[1];proof[key]=s
        return rep,durations,proof
    def quarter(rep,durations,key):
        old=(key[0]-1,key[1]);a=rep.get(key,{}).get('total_assets',{}).get(1);b=rep.get(old,{}).get('total_assets',{}).get(1)
        mean=(a+b)/2 if a and b and a>0 and b>0 else None
        current=independent(rep,durations,key,'operating_profit');prior=independent(rep,durations,old,'operating_profit')
        if durations.get(key)!=durations.get(old):return None
        return (current-prior)/mean if mean and current is not None and prior is not None else None
    z=d.copy();previous=[];proofs=[];matched=0
    for r in z.itertuples():
        value=np.nan;proof=None
        if pd.notna(r.s2_raw) and isinstance(r.sources,str) and isinstance(r.quarter_keys,str):
            keys=json.loads(r.quarter_keys)
            if keys:
                key=tuple(keys[0]);rep,durations,sources=state(r.sources)
                check=quarter(rep,durations,key)
                if check is not None and np.isclose(check,r.s2_raw,rtol=1e-9,atol=1e-12):
                    matched+=1;linear=key[0]*12+key[1]-4;prior=(linear//12,linear%12+1)
                    result=quarter(rep,durations,prior)
                    if result is not None:
                        value=result;proof=json.dumps({'prior_quarter_key':prior,'sources':list(sources.values()),
                            'current_S2_reproduced':True},ensure_ascii=False)
        previous.append(value);proofs.append(proof)
    z['previous_quarter_s2_raw']=previous;z['previous_quarter_s2_proof']=proofs
    z.to_parquet(target,index=False)
    write(out/'previous_quarter_sources.json',{'input_reports_sha256':sha(path),'variant_panel_sha256':sha(target),
        'current_quarter_reproduced_rows':matched,'previous_quarter_available_rows':int(z.previous_quarter_s2_raw.notna().sum()),
        'method':'independent cumulative subtraction and mean positive assets from same selected source versions; current S2 must reproduce',
        'no_lagged_decision_substitute':True})
    return z
