import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[2]
PUBLIC=ROOT/'client/public/strategies/factormix-033/performance'


def test_published_1401_path_and_downloads_match_the_verified_analysis():
    report=json.loads((PUBLIC/'performance.json').read_text(encoding='utf8'))
    case=next(c for c in report['cases'] if c['start_year']==1401)
    source=ROOT/'strategy_registry/analyses/replay_1401_20261106/artifacts'
    summary=json.loads((source/'summary.json').read_text(encoding='utf8'))
    for label in ['candidate','baseline']:
        nav=pd.read_csv(source/f'{label}_nav.csv')
        key='nav_toman' if label=='candidate' else 'baseline_toman'
        np.testing.assert_allclose([p[key] for p in case['path']],nav.nav_toman,rtol=0,atol=1)
        assert (PUBLIC/case['downloads'][f'{label}_nav']).read_bytes()==(source/f'{label}_nav.csv').read_bytes()
        assert case['accounts'][label]['final_toman']==pytest.approx(summary['accounts'][label]['metrics']['final_toman'],abs=1)
        assert case['accounts'][label]['trade_count']==summary['accounts'][label]['fills']


def test_both_trials_have_fresh_capital_and_independent_annual_chains():
    report=json.loads((PUBLIC/'performance.json').read_text(encoding='utf8'))
    assert report['default_case']=='from-1401'
    assert len(report['cases'])==2
    for case in report['cases']:
        assert case['path'][0]['nav_toman']==case['path'][0]['baseline_toman']==case['initial_toman']==100_000_000
        for label,field in [('candidate','return_fraction'),('baseline','baseline_return_fraction')]:
            product=np.prod([1+y[field] for y in case['annual']])*case['initial_toman']
            assert product==pytest.approx(case['accounts'][label]['final_toman'],abs=1)
        assert all(case['id'] in name for name in case['downloads'].values())
        assert all((PUBLIC/name).is_file() for name in case['downloads'].values())


def test_performance_payload_contains_no_internal_filesystem_paths_or_secrets():
    raw=(PUBLIC/'performance.json').read_text(encoding='utf8')
    for marker in ['D:/','D:\\','C:/','C:\\','postgresql://','password=']:
        assert marker not in raw


def test_monthly_overlay_is_exact_registered_account_with_unchanged_parent():
    report=json.loads((PUBLIC/'performance.json').read_text(encoding='utf8'))
    case=report['cases'][0]
    registered=ROOT/'strategy_registry/RFA-FactorMix-033-M15/v1.0.0'
    nav=pd.read_csv(registered/'results/monthly_jalali_15_nav.csv')
    parent=pd.read_csv(registered/'results/original_quarterly_nav.csv')
    assert nav.session.tolist()==[p['date'] for p in case['path']]
    np.testing.assert_allclose(nav.nav_toman,[p['monthly15_toman'] for p in case['path']],rtol=0,atol=1)
    np.testing.assert_allclose(parent.nav_toman,[p['nav_toman'] for p in case['path']],rtol=0,atol=1)
    monthly=case['monthly15']
    assert monthly['account']['trade_count']==343
    assert monthly['account']['final_toman']==pytest.approx(2_943_482_563.3857675,abs=1)
    assert monthly['account']['decision_count']+monthly['stale_decisions_skipped']==monthly['reviews_scheduled']
    for name in monthly['downloads'].values():
        assert (PUBLIC/name).is_file()
