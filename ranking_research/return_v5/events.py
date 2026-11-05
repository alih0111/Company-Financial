"""Canonical source evidence and executed, source-linked accounting fixtures."""
import re
from pathlib import Path
import pandas as pd
from bs4 import BeautifulSoup
import jdatetime
from .common import ROOT,V2,V3,V4,read,write,sha
from .ledger import SimulatedLedger

def ascii_digits(s):return str(s).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
def greg(s):
    y,m,d=map(int,ascii_digits(s).split('/'));return jdatetime.date(y,m,d).togregorian().isoformat()

def dividend_terms(text):
    t=ascii_digits(text)
    m=re.search(r'DividendPerShare\s+سود نقدی هر سهم\s*\(ریال\)\s*([\d,٬]+)',t)
    if not m:return None
    dates=re.findall(r'مورخ\s*(1[34]\d{2}/\d{2}/\d{2})',t)
    return {'cash_per_share_rial':int(m.group(1).replace(',','').replace('٬','')),
        'meeting_date':greg(dates[0]) if dates else None,'unit':'rial per share','field':'DividendPerShare'}

def run(out):
    exposures=pd.read_csv(V3/'economic_event_coverage.csv');exposures=exposures[exposures.method.isin(['balanced_control','existing_choose'])]
    actions=pd.read_parquet(V2/'db_actions.parquet').set_index('id');canonical=[];mapping=[]
    for eventid,g in exposures.groupby('event_id',sort=False):
        a=actions.loc[eventid];sym=g.iloc[0].symbol;day=g.iloc[0].date
        candidate='candidate_'+sym+'_'+day[:7] # a grouping hint, never assertion of common economic event
        canonical.append({'canonical_id':'unresolved_'+eventid,'original_event_id':eventid,'symbol':sym,'effective_date':day,
            'candidate_group':candidate,'status':'inferred' if a.event_semantics_status=='INFERRED' else 'unresolved',
            'observed_action_type':a.action_type,'economic_kind':None,'document':a.source_reference,
            'reason':'database factor/share or gap evidence is not a documented entitlement; confirmed factor does not confirm economics',
            'source':a.source,'source_metadata':str(a.metadata)})
        mapping.extend({'method':r.method,'original_event_id':eventid,'canonical_id':'unresolved_'+eventid,'symbol':sym,'date':day} for r in g.itertuples())
    # Local original documents first. Avoid importing the historical DB-writing acquisition modules.
    local=[]
    for p in (ROOT/'historical_codal_backfill/output/lt28_bodies').glob('*.html'):
        sym=p.stem.rsplit('_',1)[0]
        if sym not in set(exposures.symbol):continue
        text=BeautifulSoup(p.read_text('utf8'),'html.parser').get_text(' ',strip=True)
        local.append({'symbol':sym,'tracing_no':p.stem.rsplit('_',1)[1],'path':str(p),'sha256':sha(p),
            'contains_registration': 'ثبت رسیده' in text,'document_type':'original capital registration body'})
    pd.DataFrame(local).to_csv(out/'local_event_document_inventory.csv',index=False)
    # Known exact original AGM body: units and field independently parsed from body, not price gap.
    old=V4/'official_economic_sources/attempts.csv';manifest=pd.read_csv(old)
    rec=manifest[manifest['key'].astype(str).eq('1511063')].iloc[0];p=ROOT/rec['path'];assert sha(p)==rec.sha256
    text=BeautifulSoup(p.read_text('utf8'),'html.parser').get_text(' ',strip=True);term=dividend_terms(text)
    assert term['cash_per_share_rial']==580 and term['meeting_date']=='2026-04-20'
    schedule=read(out/'economic_sources/payment_1511298.json')
    schedule_path=ROOT/schedule['path'];assert sha(schedule_path)==schedule['sha256'] and schedule['starts_pdf']
    write(out/'payment_schedule_transcription.json',{'source':str(schedule_path),'source_sha256':sha(schedule_path),'page':1,
        'verified_by':'rendered original scanned PDF; visually read page in full',
        'DPS_rial':580,'AGM_jalali':'1405/01/31','fiscal_end_jalali':'1404/09/30',
        'payment_window_jalali':['1405/05/25','1405/05/31'],'payment_window':[greg('1405/05/25'),greg('1405/05/31')],
        'group':'all entitled shareholders who completed Sejam registration','payment_channel':'CSDI to Sejam registered bank account',
        'modeled_receipt_policy':'last day of documented window for hypothetical registered individual; not proof of receipt, not a return bound',
        'publication':'2026-04-21T13:27:09+03:30'})
    dividend={'id':'codal_1511063','kind':'dividend','symbol':'پکویر','document_verified':True,'entitlement_date':term['meeting_date'],
        'published_at':'2026-04-21T13:11:33+03:30','cash_per_share_rial':term['cash_per_share_rial'],
        'issuer_scheduled_date':greg('1405/05/31'),'schedule_published_at':'2026-04-21T13:27:09+03:30','investor_group':'individual_registered',
        'source':str(p),'source_sha256':sha(p),'url':rec.url,
        'entitlement_rule_status':'conditional fixture: registered holder at AGM; full policy entitlement reconciliation not established',
        'not_strategy_return':True}
    # Capital ratio from two equal-unit documented capital amounts, not a presumed nominal price or gap.
    capitalpath=ROOT/'historical_codal_backfill/output/lt28_bodies/دارو_1396415.html'
    capitaltext=ascii_digits(BeautifulSoup(capitalpath.read_text('utf8'),'html.parser').get_text(' ',strip=True))
    assert re.search(r'از مبلغ\s*2,600,000\s*میلیون ریال',capitaltext)
    assert '51,800,000' in capitaltext and '1400306' in capitaltext and '47799694' in capitaltext
    bonus={'id':'codal_1396415','kind':'bonus','symbol':'دارو','document_verified':True,
        'entitlement_date':greg('1404/05/05'),'published_at':'2025-08-25T10:09:48+03:30',
        'registration_date':greg('1404/05/30'),'bonus_ratio':(51800000-2600000)/2600000,'tradable_date':None,
        'capital_before_million_rial':2600000,'capital_after_million_rial':51800000,
        'retained_million_rial':1400306,'revaluation_million_rial':47799694,
        'source':str(capitalpath),'source_sha256':sha(capitalpath),
        'url':read(ROOT/'historical_codal_backfill/output/darou_capital_chain.json')['unique_events'][-1]['url'],
        'same_class_ratio_assumption':True,'entitlement_rule_status':'conditional same-class, unchanged holder fixture; eligibility/ex-date/tradability unresolved',
        'fractional_quantity_policy':'floor; remainder unvalued, never invented cash','not_strategy_return':True}
    write(out/'documented_fixtures.json',{'dividend':dividend,'capital':bonus,
        'scope':'real document economics + explicitly hypothetical 100-share eligible holder; mechanical unit test, NOT a representative strategy return',
        'manual_calculation':{'dividend_rial':100*580,'bonus_whole_shares':1892,'fractional_bonus_unvalued':100*bonus['bonus_ratio']-1892},
        'unresolved':'market ex-date, exact policy eligible-holder reconstruction and new-share tradability; payment scenario uses documented last window day'})
    ledgerrows=[];scenarios=[]
    for scenario in ['issuer_schedule','no_reinvestment']:
        l=SimulatedLedger(100000,scenario);l.shares={'پکویر':100};l.remember(dividend['entitlement_date'])
        l.event(dividend,'2026-04-21');l.settle('2026-04-29')
        c=l.components({'پکویر':10000})
        assert c['cash_rial']==100000 and c['dividend_receivables_rial']==58000 and c['known_component_rial']==1158000
        ledgerrows.append({'fixture':'documented_dividend','scenario':scenario,'date':'2026-04-29',**c,
            'eligible_shares':100,'documented_dps_rial':580,'source_id':dividend['id'],'not_strategy_return':True})
        l.settle(dividend['issuer_scheduled_date']);received=58000 if scenario=='issuer_schedule' else 0
        assert l.cash==100000+received and l.components({'پکویر':10000})['known_component_rial']==1158000
        ledgerrows.append({'fixture':'documented_dividend_at_scheduled_receipt','scenario':scenario,'date':dividend['issuer_scheduled_date'],
            **l.components({'پکویر':10000}),'eligible_shares':100,'documented_dps_rial':580,'source_id':dividend['id'],'not_strategy_return':True})
        scenarios.append({'scenario':scenario,'fixture':'documented_dividend','accrued_rial':58000,'reinvestable_received_rial':received,
            'modeled_receipt_date':dividend['issuer_scheduled_date'] if received else None,
            'schedule_status':'documented issuer window, hypothetical registered individual','complete_strategy_nav':None,'actual_receipt_required':False})
        l=SimulatedLedger(100000,scenario);l.shares={'دارو':100};l.remember(bonus['entitlement_date'])
        l.event(bonus,'2025-08-25');l.settle('2025-09-01');c=l.components({'دارو':10000})
        assert c['blocked_share_quantity']==1892 and l.shares['دارو']==100 and c['full_nav_rial'] is None
        ledgerrows.append({'fixture':'documented_capital_conditional_holder','scenario':scenario,'date':'2025-09-01',**c,
            'eligible_shares':100,'source_id':bonus['id'],'not_strategy_return':True})
    pd.DataFrame(ledgerrows).to_csv(out/'economic_ledger.csv',index=False)
    pd.DataFrame(scenarios).to_csv(out/'economic_scenarios.csv',index=False)
    for e,kind in [(dividend,'dividend'),(bonus,'capital_increase')]:
        canonical.append({'canonical_id':e['id'],'original_event_id':None,'symbol':e['symbol'],'effective_date':e['entitlement_date'],
            'status':'confirmed_terms_conditional_entitlement','economic_kind':kind,'document':e['source'],
            'reason':e['entitlement_rule_status'],'source_sha256':e['source_sha256']})
    pd.DataFrame(canonical).to_csv(out/'canonical_events.csv',index=False)
    pd.DataFrame(mapping).to_csv(out/'exposure_event_mapping.csv',index=False)
    impact=[]
    for r in mapping:
        h=pd.read_csv(V3/('economic_'+r['method']+'_holdings.csv.gz'))
        z=h[h.symbol.eq(r['symbol'])&h.date.le(r['date'])]
        qty=z.sort_values('date').iloc[-1].share_quantity if len(z) else None
        impact.append({**r,'modeled_prior_raw_shares':qty,'economic_amount_unknown':True,'impact_toman':None,
            'reason':'unresolved event amount/identity; no fabricated bounds or zero','next_action':'obtain exact issuer decision and market entitlement/tradability notice for this event'})
    pd.DataFrame(impact).to_csv(out/'unresolved_event_impact.csv',index=False)
    write(out/'claim_contract.json',{'adjusted_index':'normalized adjusted-index proxy, not cash wealth',
        'economic_simulated':'raw shares + documents + receivables + modeled settlement and receipt assumptions; complete account NAV unknown while material terms unknown',
        'actual_account':'does_not_exist','personal_receipt_required_for_backtest':False,
        'dividend_claims_are_not_buying_cash':True,'receipt_scenarios_registered_before_returns':True,
        'unknown_amount':'null, not zero, no invented interval','rounding':'integer shares floor; leftover cash retained; fractional new-share claim unresolved',
        'double_counting':'raw prices only for economic ledger; adjusted factors never added to shares or cash',
        'mechanics_then_policy':'fixtures executed; full policy replay not identified until material event terms, entitlement and chronology established',
        'economic_strategy_result':'unknown; documented subset is not representative portfolio performance'})
