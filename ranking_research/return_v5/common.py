import datetime as dt
from pathlib import Path
from ranking_research.return_v3.common import ROOT, SOURCE as V2, read, write, sha
from ranking_research.return_v4.common import V3

V4=ROOT/'ranking_research/output/return_v4/v4_20261016T130610656257Z'

def register():
    out=ROOT/'ranking_research/output/return_v5'/('v5_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    write(out/'registration.json',{'run_id':out.name,'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_files':{str(p):sha(p) for p in [V4/'delivery_manifest.json',V4/'repaired_panel.parquet',V4/'latest_research_ranking.json',V3/'selection_protocol.json',V2/'db_actions.parquet']},
        'initial_toman':100000000,'independent_holdout':False,'real_account_performance':'does_not_exist',
        'quality_rule':'end at last inferred market session with >=50% of local universe having positive volume/value/close and internally valid OHLC; choose before new returns',
        'promotion':{'wealth_ratio':1.10,'majority_complete_blocks':True,'dd_deterioration_max':.05,'combined_stress_advantage':True,'remove_best_block_advantage':True},
        'new_configs_max':6,'cost_per_side':.005,'settlement':'modeled T+2 inferred sessions',
        'economic_scenarios':['documented issuer payment for individual investor, never earlier than announcement','no dividend reinvestment until evaluation end'],
        'budget':{'local_first':True,'new_price_probes_max':8,'economic_catalog_pages_max':120,'economic_documents_max':60,'request_timeout_seconds':20,'concurrency':1,'stop_on_access_or_rate_control':True}})
    write(out/'checkpoint.json',{'phase':'registered','files_plan':{'prices.py':'daily contract, bounded official probes, fixed quality windows',
        'events.py':'source deduplication, documented mechanics using shared Ledger','diagnostics.py':'rank labels, cohort and actual cadence/fill audit',
        'run.py':'resume validation and artifacts','report.py':'same research page, comparison and handoff'},
        'dependencies':'A quality window before C labels/new financial replay; B independent; candidate registry before any new candidate return',
        'estimated_work':'254 cached price series; 3 signals x 3 horizons; reuse completed accounts; at most 6 new candidates only if diagnostics justify; bounded network separate cached phase'})
    return out

def validate(out):
    for p,h in read(out/'registration.json')['source_files'].items():
        if sha(p)!=h:raise ValueError('Source changed: '+p)
    if (out/'code_freeze.json').exists():
        for p,h in read(out/'code_freeze.json').items():
            if sha(ROOT/p)!=h:raise ValueError('Code changed; new run required: '+p)
    if (out/'consumed_sources.json').exists():
        for p,h in read(out/'consumed_sources.json').items():
            if sha(p)!=h:raise ValueError('Consumed source changed: '+p)

def freeze(out):
    files={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for folder in ['return_v5','return_v3'] for p in (ROOT/('ranking_research/'+folder)).glob('*.py')}
    if (out/'code_freeze.json').exists():validate(out)
    else:
        write(out/'code_freeze.json',files)
        from ranking_research.strategy_search.features import V,market_fingerprint
        import pandas as pd
        symbols=pd.read_csv(V2/'new_market_archive/inventory.csv').symbol.tolist()
        assert market_fingerprint(symbols)==read(V2/'data_manifest.json')['market']
        sec=V.load_reference_data()['sec'];ins=dict(zip(sec.symbol,sec.ins_code))
        paths=[V.CACHE/n for n in ['corp_actions_confirmed.parquet','calendar.parquet','securities.parquet']]
        paths += [V.RAW/f'raw_{s}_{ins[s]}.json.gz' for s in symbols]
        paths += list((V2/'new_market_archive').glob('*.gz'))
        paths += [V4/'repaired_panel.parquet',V2/'db_actions.parquet']
        effective=read(V3/'registration.json')['frozen_v2_code']
        paths += [V3/'frozen_v2'/rel for rel in effective]
        for rel,h in effective.items():assert sha(V3/'frozen_v2'/rel)==h
        write(out/'consumed_sources.json',{str(p):sha(p) for p in paths})
        write(out/'effective_shared_code.json',{'archived_loader':str(V3/'frozen_v2'),'code':effective,'V3_code':'code_freeze.json','V5_code':'code_freeze.json'})
