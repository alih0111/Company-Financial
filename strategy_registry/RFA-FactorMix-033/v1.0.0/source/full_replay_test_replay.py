from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from extend_market import raw_gaps,HERE,OUT


def test_normal_price_return_is_not_a_reference_adjustment():
    rows=[dict(dEven=20261001,pClosing=100,priceYesterday=90),dict(dEven=20261002,pClosing=130,priceYesterday=100)]
    assert raw_gaps(rows)==[]


def test_reference_adjustment_factor_has_correct_direction():
    rows=[dict(dEven=20261001,pClosing=100,priceYesterday=90),dict(dEven=20261002,pClosing=88,priceYesterday=80)]
    e=raw_gaps(rows)[0]
    assert e['factor']==.8
    assert 88/(100*e['factor'])-1==pytest.approx(.1)


def test_zero_reference_is_not_divided():
    rows=[dict(dEven=20261001,pClosing=100),dict(dEven=20261002,pClosing=0,priceYesterday=0)]
    assert raw_gaps(rows)==[]


@pytest.mark.parametrize('prefix',['complete','active'])
def test_entire_old_nav_prefix_reproduces_without_retuning(prefix):
    for label in ['candidate','baseline']:
        old=pd.read_csv(OUT/f'{label}_nav.csv');new=pd.read_csv(OUT/f'{prefix}_{label}_nav.csv')
        matched=old.merge(new,on='session',suffixes=('_old','_new'),validate='one_to_one')
        assert len(matched)==len(old)
        np.testing.assert_allclose(matched.nav_toman_old,matched.nav_toman_new,rtol=0,atol=1)
    decision=HERE.parent/'feature_model_search_20261106/artifacts/research_decision.json'
    prefix=json.loads((OUT/'available_replay.json').read_text(encoding='utf8'))
    assert hashlib.sha256(decision.read_bytes()).hexdigest()==prefix['policy_sha256']


def test_new_financial_snapshots_do_not_consume_future_publications():
    for path in OUT.glob('financial_*.parquet'):
        frame=pd.read_parquet(path)
        assert len(frame)==254 and frame.symbol.nunique()==254
        for row in frame.itertuples():
            cut=pd.Timestamp(row.publication_cutoff)
            for report in json.loads(row.sources):assert pd.Timestamp(report['published_at'])<cut


@pytest.mark.parametrize('prefix',['complete','active'])
def test_independent_daily_bookkeeping_reconciles_full_nav(prefix):
    d=dict(np.load(OUT/f'{prefix}_inputs.npz'));index={str(s):j for j,s in enumerate(d['syms'])}
    nav=pd.read_csv(OUT/f'{prefix}_candidate_nav.csv');tr=pd.read_csv(OUT/f'{prefix}_candidate_trades.csv')
    trades={date:g for date,g in tr.groupby('session')};cash=1e8;q=np.zeros(len(index))
    for row in nav.itertuples():
        if row.session in trades:
            for t in trades[row.session].itertuples():
                assert t.decision<t.session
                j=index[t.symbol]
                if t.side=='BUY':q[j]+=t.units;cash-=t.gross_toman+t.fee_toman
                else:q[j]-=t.units;cash+=t.gross_toman-t.fee_toman
        i=np.searchsorted(d['cal'],row.session)
        assert cash>=-.01 and q.min()>-1e-5
        assert abs(cash+float(q@d['close'][i])-row.nav_toman)<.1
    s=json.loads((OUT/f'{prefix}_summary.json').read_text(encoding='utf8'))
    assert tr.fee_toman.sum()==pytest.approx(s['fees_toman'])
    assert tr.slippage_toman.sum()==pytest.approx(s['slippage_toman'])


@pytest.mark.parametrize('prefix',['complete','active'])
def test_yearly_returns_chain_without_cash_resets(prefix):
    s=json.loads((OUT/f'{prefix}_summary.json').read_text(encoding='utf8'))
    product=np.prod([1+r['return_fraction'] for r in s['jalali_years']])
    assert product==pytest.approx(s['candidate']['final_toman']/1e8)
    assert s['latest_market_day_jalali']=='1405-08-13'
    assert s['candidate']['end']==s['baseline']['end']


def test_active_calendar_does_not_count_no_equity_trade_days_as_sessions():
    active=np.load(OUT/'active_inputs.npz');old=np.load(OUT/'complete_inputs.npz')
    after=active['cal']>'2026-02-24'
    assert np.isfinite(active['opening'][after]).any(axis=1).all()
    np.testing.assert_array_equal(active['cal'][~after],old['cal'][old['cal']<='2026-02-24'])
    decisions=pd.read_csv(OUT/'active_candidate_decisions.csv')
    assert '2026-04-29' not in decisions.session.tolist()
    assert '2026-05-19' in decisions.session.tolist()
