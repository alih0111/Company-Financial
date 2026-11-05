"""Read-only local archive/DB inventory. Never stores credentials or account data."""
import json
import pandas as pd
from .features import V
from .registry import atomic_write_json
from .features import ROOT, HIST
from .registry import sha_file


def inventory(panel, md, out):
    import psycopg
    queries = {
        'reports': "SELECT count(*) total,count(DISTINCT company_id) companies,min(published_at) first_publication,max(published_at) last_publication,count(*) FILTER(WHERE published_at IS NULL) missing_publication,count(*) FILTER(WHERE supersedes_report_id IS NOT NULL) revisions FROM ingestion.reports",
        'statements': "SELECT count(*) total,count(DISTINCT company_id) companies,min(period_end_date) first_period,max(period_end_date) last_period,count(*) FILTER(WHERE report_version_id IS NOT NULL) linked_versions FROM fundamentals.financial_statements",
        'classification': "SELECT count(*) total,min(valid_from) first_valid,max(valid_from) last_valid,count(*) FILTER(WHERE valid_to IS NOT NULL) closed_intervals FROM core.company_classification",
        'securities': "SELECT count(*) total,count(*) FILTER(WHERE NOT is_active) inactive,count(*) FILTER(WHERE valid_from IS NOT NULL) dated_start,count(*) FILTER(WHERE valid_to IS NOT NULL) dated_end FROM core.securities",
        'actions': "SELECT event_semantics_status,adjustment_evidence_status,count(*) total FROM market.corporate_actions GROUP BY 1,2",
        'old_publications': "SELECT extract(year from published_at) AS publication_year,count(*) total,count(DISTINCT company_id) companies FROM ingestion.reports WHERE published_at<'2022-03-01' GROUP BY 1 ORDER BY 1",
        'old_parsed': "SELECT extract(year from r.published_at) AS publication_year,count(*) statements,count(DISTINCT s.company_id) companies FROM fundamentals.financial_statements s JOIN ingestion.reports r ON r.id=s.report_id WHERE r.published_at<'2022-03-01' GROUP BY 1 ORDER BY 1",
    }
    results = {}
    registration = json.loads((HIST / 'registration.json').read_text(encoding='utf8'))
    input_path = __import__('pathlib').Path(registration['inputs']) / 'input_reports.json'
    verified = pd.DataFrame(json.loads(input_path.read_text(encoding='utf8')))
    verified.groupby(verified.published_at.str[:4]).agg(reports=('company_id','size'), companies=('company_id','nunique')).to_csv(out / 'verified_source_years.csv')
    prior_run = __import__('pathlib').Path(json.loads((ROOT / 'ranking_research/output/top10_six_month_latest.json').read_text(encoding='utf8'))['run_path'])
    coverage = pd.read_csv(prior_run / 'coverage_by_date.csv')
    coverage.to_csv(out / 'prior_snapshot_coverage.csv', index=False)
    pre = coverage[coverage.decision_time.lt('2022-03-01')]
    results['verified_input_probe'] = {'input_sha256': sha_file(input_path), 'input_reports': len(verified),
        'first_verified_publication': str(verified.published_at.min()),
        'pre2022_months_probed': len(pre), 'pre2022_eligible_total': int(pre.eligible.sum()),
        'coverage_file_sha256': sha_file(prior_run / 'coverage_by_date.csv'),
        'conclusion': 'existing source-proof builder has zero baseline-eligible earlier months; DB records are not interchangeable with verified frozen report chains'}
    try:
        with psycopg.connect(V.DSN, connect_timeout=5) as c:
            c.execute('SET TRANSACTION READ ONLY')
            c.execute("SET LOCAL statement_timeout='20000'")
            with c.cursor() as q:
                for name, sql in queries.items():
                    q.execute(sql)
                    results[name] = [dict(zip([d.name for d in q.description], r)) for r in q.fetchall()]
    except Exception as exc:
        results['db_error'] = type(exc).__name__  # connection strings never logged
    price_dates = [{'symbol': s, 'first': r['dates'][0], 'last': r['dates'][-1], 'sessions': len(r['dates'])}
                   for s, r in md.data.items() if len(r['dates'])]
    pd.DataFrame(price_dates).to_csv(out / 'price_archive_inventory.csv', index=False)
    rows = []
    for col in ['momentum_12_1', 'operating_yield', 'operating_improvement', 'cash_multi', 'debt_ratio', 'sales_yoy', 'sources_published_before_cutoff']:
        for day, g in panel.groupby('decision_time'):
            valid = g[col].eq(True) if col == 'sources_published_before_cutoff' else g[col].notna()
            rows.append({'feature': col, 'date': day, 'symbols': int(g.symbol.nunique()),
                         'valid_symbols': int(g.loc[valid, 'symbol'].nunique()),
                         'source': 'frozen local PIT panel + market archive',
                         'access_time': 'source published_at < snapshot cutoff; local collection can be later',
                         'revision': 'consumed source IDs in frozen panel; historical version availability not fully certified',
                         'retrieval_cost': '0; local read', 'testability': '48 observed monthly dates; 3 full evaluation folds'})
    gaps = [
        ('older_financials', 'ingestion.reports + financial_statements', 'partial',
         'Older records exist; period-end alone is not publication evidence. Requires re-running the source-proof snapshot builder and common-range baselines before inclusion.'),
        ('historical_universe', 'core.securities / security_aliases', 'not_certified',
         'No inactive/delisted primary universe proved; listing/delisting effective dates incomplete. Size/direction of strategy bias unknown.'),
        ('historical_industry', 'core.company_classification', 'not_certified',
         'valid_from starts 2026; cannot backdate current industry to 2022.'),
        ('cash_rights_events', 'market.corporate_actions', 'partial',
         'Most events lack confirmed semantics; adjustment confirmation does not prove cash/right investment timing.'),
        ('untouched_evaluation', 'available local history', 'unavailable',
         'All 48 months were already inspected. No retrospective split creates an untouched test.'),
    ]
    for feature, source, status, why in gaps:
        rows.append({'feature': feature, 'date': None, 'symbols': None, 'valid_symbols': None,
                     'source': source, 'access_time': 'see db_inventory.json', 'revision': status,
                     'retrieval_cost': 'local checked; external tariff/access unknown', 'testability': why})
    matrix = pd.DataFrame(rows)
    matrix.to_csv(out / 'data_gap_matrix.csv', index=False)
    atomic_write_json(out / 'db_inventory.json', results)
    return results, matrix
