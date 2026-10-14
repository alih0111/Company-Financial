import datetime as dt
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verified_reopenings import corroborate_gap, timing_with_proofs
import score_v2_t_raw as TR

def examples():
    a = {'pClosing': 100, 'pDrCotVal': 100, 'priceMax': 101, 'priceMin': 99,
         'qTotTran5J': 10, 'zTotTran': 5, 'qTotCap': 1000}
    b = {**a, 'pClosing': 130, 'pDrCotVal': 130, 'priceMax': 131, 'priceMin': 129, 'priceYesterday': 100}
    quiet = [{'qTotTran5J': 0, 'zTotTran': 0, 'qTotCap': 0}]
    bars = ({'close': 100, 'high': 101, 'low': 99, 'volume': 10},
            {'close': 130, 'high': 131, 'low': 129, 'volume': 10})
    return a, b, quiet, bars

def test_reference_reset_or_trading_inside_gap_cannot_be_excused():
    a, b, quiet, bars = examples()
    assert corroborate_gap(a, b, quiet, *bars)
    assert not corroborate_gap(a, {**b, 'priceYesterday': 50}, quiet, *bars)
    assert not corroborate_gap(a, b, [{'qTotTran5J': 1, 'zTotTran': 1, 'qTotCap': 100}], *bars)
    assert not corroborate_gap(a, b, [], *bars)

def test_exception_is_security_specific_and_default_guard_is_restored():
    asof = dt.date(2026, 10, 13)
    a, b = dt.date(2026, 4, 12), dt.date(2026, 5, 20)
    rows = [{'date': a, 'close': 10000, 'tv': 1000, 'collected_at': None},
            {'date': b, 'close': 13000, 'tv': 1000, 'collected_at': None},
            {'date': dt.date(2026, 10, 12), 'close': 13000, 'tv': 1000, 'collected_at': None}]
    histories = {'proven': rows, 'unknown': [dict(r) for r in rows]}
    pilot = SimpleNamespace(build_histories=lambda *args: (histories, {}))
    engine = SimpleNamespace(as_of=asof)
    original_facts, original_warnings = TR._security_facts, TR._gap_warnings
    proofs = {'proven': {(a, b): {'adjusted_return': 0.3}}}
    with timing_with_proofs(engine, pilot, proofs):
        good = TR._security_facts(histories['proven'], asof)
        other = TR._security_facts(histories['unknown'], asof)
        assert not TR._gap_warnings({'momentum_6m_rel': good.chains['momentum_6m_rel']})
        assert TR._gap_warnings({'momentum_6m_rel': other.chains['momentum_6m_rel']})
    assert TR._security_facts is original_facts
    assert TR._gap_warnings is original_warnings
    assert TR._gap_warnings({'momentum_6m_rel': original_facts(rows, asof).chains['momentum_6m_rel']})
