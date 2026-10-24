"""Create a separate, empty public-calendar paper-account draft without migration."""
from __future__ import annotations
import argparse, copy, datetime as dt, hashlib, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
try:
    from ranking_research import paper_account_store
except ImportError:
    sys.path.insert(0,str(ROOT)); from ranking_research import paper_account_store

def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template',type=Path,default=ROOT/'client/public/research/v12-36/paper-portfolio.json')
    p.add_argument('--ranking',type=Path,required=True)
    p.add_argument('--rules',type=Path,default=ROOT/'ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json')
    p.add_argument('--policy',type=Path,default=ROOT/'ranking_research/paper_calendar_policy.public-paper-v1.json')
    p.add_argument('--output-account',type=Path,required=True)
    p.add_argument('--output-rules',type=Path,required=True)
    p.add_argument('--account-id',required=True)
    p.add_argument('--fixture',action='store_true',help='Marks a synthetic draft; cannot be used as an operational account.')
    a=p.parse_args()
    dest=a.output_account.resolve(); rules_out=a.output_rules.resolve()
    if dest.exists() or rules_out.exists(): raise SystemExit('DRAFT_DESTINATION_EXISTS; refusing overwrite')
    template=json.loads(a.template.read_text(encoding='utf-8'))
    ranking=json.loads(a.ranking.read_text(encoding='utf-8'))
    rules=json.loads(a.rules.read_text(encoding='utf-8'))
    policy=json.loads(a.policy.read_text(encoding='utf-8'))
    digest=ranking.get('artifact_sha256')
    candidate_rows=[r for r in ranking.get('rows',[]) if r.get('methods',{}).get('P1',{}).get('rank')==1]
    if not isinstance(digest,str) or len(digest)!=64 or len(candidate_rows)!=1:
        raise SystemExit('RANKING_SNAPSHOT_NOT_PINNABLE; expected artifact SHA and unique P1 rank 1')
    row=candidate_rows[0]; candidate={'company_id':row['company_id'],'symbol':row['symbol'],'rank':1,
        'score':row['methods']['P1'].get('score'),'coverage':row['methods']['P1'].get('financial_factor_coverage')}
    binding={'id':policy['policy_id'],'sha256':sha(a.policy),'provider':policy['provider'],'version':policy['version']}
    rules=copy.deepcopy(rules); rules['calendar_policy']=binding
    rules_out.parent.mkdir(parents=True,exist_ok=True)
    rules_out.write_text(json.dumps(rules,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    instant=dt.datetime.now(dt.timezone.utc)
    tehran=instant.astimezone(dt.timezone(dt.timedelta(hours=3,minutes=30)))
    account=copy.deepcopy(template)
    account.update({'account_id':a.account_id,'created_at_utc':instant.isoformat(),'created_at_tehran':tehran.isoformat(),
        'decision_at_utc':instant.isoformat(),'initial_capital_toman':template['initial_capital_toman'],
        'cash_toman':template['initial_capital_toman'],'holdings':[],'event_log':[],
        'ranking':{'dataset_id':ranking.get('dataset_id'),'evaluation_date':ranking.get('evaluation_date'),
            'status':ranking.get('status'),'artifact_sha256':digest,'top_candidate':candidate},
        'accounting':{'holdings_value_toman':0,'total_value_toman':template['initial_capital_toman'],'profit_loss_toman':0},
        'calendar_policy':binding,'active_decision':None,'paper_order':None,
        'order_created':False,'execution_recorded':False,'real_order_submitted':False,
        'status':'INACTIVE_PUBLIC_PAPER_DRAFT','candidate_status':'پیش‌نویس غیرفعال؛ هنوز تصمیم یا سفارش ندارد',
        'official_future_evaluation_ledger_linked':False,'official_ledger_event_count_changed':False})
    account['assumptions_version']=rules['rule_id']
    account['event_log']=[{'event_id':'public-draft-created-'+hashlib.sha256(a.account_id.encode()).hexdigest()[:16],
        'type':'PUBLIC_PAPER_DRAFT_CREATED','at_utc':instant.isoformat(),'reason':'ایجاد حساب جدا و غیرفعال؛ بدون مهاجرت یا تصمیم خرید.',
        'details':f"ranking_sha256={digest}; ranking_status={ranking.get('status')}; fixture={a.fixture}; public policy={policy['policy_id']} sha256={binding['sha256']}."}]
    dest.parent.mkdir(parents=True,exist_ok=True)
    paper_account_store.validate_account(account)
    with paper_account_store.account_write_lock(dest):
        if dest.exists(): raise SystemExit('DRAFT_DESTINATION_EXISTS; refusing overwrite')
        paper_account_store.write_account_atomic(dest,account)
    print(json.dumps({'account':str(dest),'account_sha256':sha(dest),'rules':str(rules_out),
        'rules_sha256':sha(rules_out),'ranking_status':ranking.get('status'),'candidate':candidate,
        'active_decision':False,'live_account_activated':False,'fixture':a.fixture},ensure_ascii=False))
    return 0

if __name__=='__main__': raise SystemExit(main())
