import datetime as dt
import hashlib
import json
from pathlib import Path
from ranking_research.return_v5.common import ROOT, V2, V3, V4, read, write, sha

V5 = ROOT/'ranking_research/output/return_v5/v5_20261016T132527480952Z'
START, DISPLAY_START, END = '2024-10-30', '2024-11-02', '2026-02-25'

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()

def code_files():
    return {str(p.relative_to(ROOT)).replace('\\','/'):sha(p)
            for p in sorted((ROOT/'ranking_research/return_v6').glob('*.py'))}

def verify_prior():
    from ranking_research.return_v5.common import validate
    validate(V5)
    m=read(V5/'delivery_manifest.json')
    for p,h in m['files'].items():
        if sha(V5/p)!=h: raise ValueError('V5 artifact changed: '+p)
    return len(m['files'])

def register():
    out=ROOT/'ranking_research/output/return_v6'/('v6_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    paths=[V5/n for n in ['delivery_manifest.json','experiment_registry.json','machine_comparison.csv','DIAGNOSTICS.fa.md','blockers.csv']]
    paths += [V4/'repaired_panel.parquet',V4/'additional_reports.json',V3/'selection_protocol.json',V2/'pit_feature_events.parquet',V2/'pit_report_versions.parquet',V2/'known_report_gap_events.parquet']
    write(out/'run_manifest.json',{'run_id':out.name,'created_at':utc(),'sources':{str(p):sha(p) for p in paths},
        'code':code_files(),'V5_verified_artifacts':verify_prior(),'initial_toman':100000000,
        'decision_start':START,'display_start':DISPLAY_START,'end':END,'independent_holdout':False,
        'economic_strategy_nav_known':False,'actual_account':False,'production_changed':False,
        'cache':'content-hashed per stage and financial frame; incompatible resume rejected',
        'execution':'python -B -m ranking_research.return_v6.run all --run "'+str(out)+'"'})
    write(out/'experiment_registry.json',{'registered_at':utc(),'before_new_returns':True,
        'primary_configurations':['S2_publication','equal_feature_ranks','ridge_rank'],
        'maximum_primary_configurations':3,'cadence':'biweekly','top_n':10,'weight':'equal','buffer':False,
        'data_ablation':['D0_V5_actual','D1_recovered_monthly_counterfactual','D2_recovered_publication'],
        'D1_warning':'if V5 already publication-aware, D1 is explicit counterfactual and not the V5 baseline',
        'research_gate':{'wealth_vs_same_data_S2':'>1','complete_block_majority':True,'extra_dd_max':.05,'quality_failure':False},
        'major_gate':{'wealth_vs_same_conditions_selector':1.1,'also_show_frozen_V5_ratio':True},
        'finalist_rule':'largest research-qualified terminal wealth, deterministic method id tie break',
        'stress':['double_cost','delay2','capacity_half','combined'],'capital500m':'only finalist passing all stresses',
        'recovery_priority':'affected decision counts, exact local source linkage, retrieval cost; never forward returns',
        'financial_network_budget':6,'economic_network_budget':12,'stop_on_access_barrier':True})
    return out

def validate(out):
    m=read(out/'run_manifest.json')
    for p,h in m['sources'].items():
        if sha(p)!=h: raise ValueError('Source changed: '+p)
    if code_files()!=m['code']:raise ValueError('V6 code changed; register new run')
    verify_prior()

def frame_hash(f):
    z=f.sort_values(['decision_time','company_id']).reset_index(drop=True)
    return hashlib.sha256(z.to_json(orient='records',double_precision=15).encode()).hexdigest()
