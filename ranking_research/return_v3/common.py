import datetime as dt
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'ranking_research/output/return_v2/v2_20261016T080341078036Z'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def read(p): return json.loads(Path(p).read_text(encoding='utf8'))

def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf8')
    tmp.replace(p)

def code():
    return {str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted((ROOT/'ranking_research/return_v3').glob('*.py')) if p.name!='report.py'}

def register():
    out=ROOT/'ranking_research/output/return_v3'/('v3_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True);(out/'results').mkdir()
    frozen=read(SOURCE/'search_freeze.json')['effective_code']
    for rel,digest in frozen.items():
        src=SOURCE/'search_registered_code'/rel
        assert sha(src)==digest,rel
        dst=out/'frozen_v2'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    files=['decision_panel.parquet','pit_feature_events.parquet','pit_report_versions.parquet',
        'db_reports.parquet','db_statements.parquet','db_securities.parquet','db_actions.parquet',
        'known_report_gap_events.parquet','selection_protocol.json','evaluation_comparison.csv',
        'formula_vs_coverage_summary.csv','source_gap_queue.csv','data_manifest.json','delivery_manifest.json',
        'verification.json','event_sources_manifest.json','native_source_validation.csv','search_freeze.json']
    source_hashes={str(SOURCE/n):sha(SOURCE/n) for n in files}
    write(out/'registration.json',{'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source':str(SOURCE),'source_files':source_hashes,'frozen_v2_code':frozen,
        'mission':'A price diagnosis, B economic ledger, C source reconciliation, D fixed replay, E bounded hypotheses, research ranking',
        'old_start':'2024-11-02','old_end':'2026-04-29','initial_rial':1000000000,
        'new_hypotheses_max':12,'retrospective':True,'real_orders':0,
        'calendar':'official where evidenced, otherwise explicit inferred sensitivity',
        'report_changes_do_not_invalidate_financial_cache':True})
    return out

def snapshot(out):
    """Execute archived V2 bytes; preserve original __file__ for repository data paths."""
    frozen=read(out/'registration.json')['frozen_v2_code']
    class Loader(importlib.abc.Loader):
        def __init__(self,rel): self.rel=rel
        def create_module(self,spec): return None
        def exec_module(self,module):
            path=out/'frozen_v2'/self.rel
            assert sha(path)==frozen[self.rel]
            module.__file__=str(ROOT/self.rel)
            exec(compile(path.read_bytes(),module.__file__,'exec'),module.__dict__)
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            rel=fullname.replace('.','/')+'.py'
            if rel in frozen:
                return importlib.util.spec_from_loader(fullname,Loader(rel),origin=str(out/'frozen_v2'/rel))
    import sys
    sys.meta_path.insert(0,Finder())

def checkpoint(out,stage,files,**details):
    write(out/('stage_'+stage+'.json'),{'complete':True,'files':{str(Path(p).relative_to(out)):sha(p) for p in files},**details})

def done(out,stage):
    p=out/('stage_'+stage+'.json')
    if not p.exists(): return False
    for name,digest in read(p)['files'].items(): assert sha(out/name)==digest,'checkpoint changed '+name
    return True

def seal_code(out):
    p=out/'financial_code_freeze.json'
    current=code()
    if p.exists(): assert read(p)==current,'financial code changed; new run required'
    else:
        write(p,current)
        for rel in current:
            dst=out/'registered_v3'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst)
