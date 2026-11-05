import datetime as dt
from pathlib import Path
from ranking_research.return_v3.common import ROOT, SOURCE as V2, read, write, sha

V3 = ROOT/'ranking_research/output/return_v3/v3_20261016T090423998625Z'

def register():
    out=ROOT/'ranking_research/output/return_v4'/('v4_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True);(out/'results').mkdir()
    files=[*V3.glob('*.csv'),*V3.glob('*.json'),V3/'D1_panel.parquet',
           V2/'known_report_gap_events.parquet',V2/'pit_report_versions.parquet',V2/'db_securities.parquet']
    write(out/'registration.json',{'run_id':out.name,'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_v3':str(V3),'source_files':{str(p):sha(p) for p in files},
        'initial_toman':100000000,'new_hypotheses':0,'real_orders':0,
        'resource_budget':{'local_cache_first':True,'max_network_requests':12,'timeout_seconds':20,'request_spacing_seconds':1.5},
        'retrospective':True,'independent_holdout':False})
    write(out/'experiment_registry.json',{'registered_before_results':True,'fresh_combinations':0,
        'reason':'repair available original report chains first; economic certification unresolved; no defensible new formula search',
        'formula':'unchanged shared V2 S2','controls':['balanced','S2_monthly','S2_biweekly','old_temporal_selector','profit_growth','equal_weight_all'],
        'promotion_gate':{'wealth_vs_repaired_old_selector':1.10,'majority_blocks':True,'extra_dd_max':.05,'remove_best_positive':True,'combined_stress_positive':True},
        'monthly_sales':'not_tested; incomplete six-version chains','promotion':'none'})
    return out

def freeze(out):
    files={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'ranking_research/return_v4').glob('*.py')}
    p=out/'code_freeze.json'
    if p.exists():assert read(p)==files,'V4 code changed: new run required'
    else:
        write(p,files)
        for rel in files:
            q=out/'registered_code'/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((ROOT/rel).read_bytes())

def verify_source(out):
    for p,h in read(out/'registration.json')['source_files'].items():assert sha(p)==h,'original source changed: '+p
