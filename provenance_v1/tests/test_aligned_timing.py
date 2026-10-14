import copy
import datetime as dt
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from complete_ranking_coverage import ANA
from aligned_timing import align_returns, FACTORS


def records(start, ret, industry='drug'):
    return {fid: {'status': 'valid', 'raw_value': 999, 'warnings': [],
                  'market': {'last_trade_date': dt.date(2026, 10, 12),
                             'window': {'base_date': start, 'ref_date': dt.date(2026, 4, 13),
                                        'stock_return': ret}}} for fid in FACTORS}


def test_older_security_cannot_distort_shared_benchmark():
    start = dt.date(2026, 2, 25)
    raw = {'a': records(start, .2), 'b': records(start, .4),
           'halted': records(dt.date(2026, 1, 1), 9)}
    meta = {cid: {'industry': 'drug'} for cid in raw}
    policy = align_returns(raw, meta)
    assert abs(raw['a']['momentum_6m_rel']['raw_value'] + .1) < 1e-12
    assert raw['halted']['momentum_6m_rel']['status'] == 'invalid'
    assert policy['momentum_6m_rel']['aligned_members'] == 2
    assert raw['a']['momentum_6m_rel']['market']['window']['actual_start_date'] == start


def test_unknown_gap_and_small_industry_stay_unscored():
    start = dt.date(2026, 4, 12)
    raw = {'a': records(start, .2), 'b': records(start, .4), 'bad': records(start, 99)}
    for rec in raw['bad'].values():
        rec.update(status='invalid', raw_value=None, validation_reason='suspected_unadjusted_gap')
    align_returns(raw, {'a': {'industry': 'one'}, 'b': {'industry': 'two'}, 'bad': {'industry': 'one'}})
    assert raw['a']['relative_strength_6m_sector']['status'] == 'not_applicable'
    assert raw['bad']['momentum_6m_rel']['validation_reason'] == 'suspected_unadjusted_gap'
    assert raw['a']['momentum_6m_rel']['market']['window']['benchmark_n'] == 2


def test_verified_valid_returns_can_rebuild_a_missing_sector_benchmark():
    start = dt.date(2026, 4, 12)
    raw = {'a': records(start, .2), 'b': records(start, .4)}
    for factors in raw.values():
        factors['relative_strength_6m_sector'].update(status='not_applicable', raw_value=None,
            validation_reason='insufficient_sector_benchmark: original population excluded reopening returns')
    align_returns(raw, {'a': {'industry': 'drug'}, 'b': {'industry': 'drug'}})
    assert raw['a']['relative_strength_6m_sector']['status'] == 'valid'
    assert raw['a']['relative_strength_6m_sector']['market']['window']['benchmark_n'] == 2
