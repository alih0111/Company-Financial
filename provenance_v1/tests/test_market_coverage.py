import datetime as dt
from pathlib import Path
import sys
import hashlib
import json
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from complete_market_coverage import validate
import complete_market_coverage as market

def payload():
    return {'l18': 'نماد', 'type': 3, 'candle_daily_adjusted': [
        {'date': '1405-07-20', 'open': 110, 'high': 120, 'low': 100, 'close': 115, 'volume': 10}]}

def test_adjusted_source_identity_and_type_are_required():
    item = payload()
    assert validate(item, 'نماد', dt.date(2026, 10, 13))[0]['date'] == '2026-10-12'
    with pytest.raises(ValueError):
        validate(item, 'نماد دیگر', dt.date(2026, 10, 13))
    with pytest.raises(ValueError):
        validate({**item, 'type': 2}, 'نماد', dt.date(2026, 10, 13))

def test_bad_or_conflicting_candles_cannot_enter_history():
    item = payload()
    candle = item['candle_daily_adjusted'][0]
    with pytest.raises(ValueError):
        validate({**item, 'candle_daily_adjusted': [{**candle, 'close': 150}]}, 'نماد', dt.date(2026, 10, 13))
    with pytest.raises(ValueError):
        validate({**item, 'candle_daily_adjusted': [candle, {**candle, 'close': 114}]}, 'نماد', dt.date(2026, 10, 13))

def test_overlay_preserves_observed_turnover_and_real_collection_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(market, 'MARKET', tmp_path)
    item = payload()
    collected = dt.datetime(2026, 10, 13, 5, tzinfo=dt.timezone.utc)
    rec = {'company_id': 'company', 'symbol': 'نماد', 'source': 'brs_candlestick_type3',
           'collected_at': collected.isoformat(), 'payload': item,
           'payload_sha256': hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    (tmp_path / 'company.json').write_text(json.dumps(rec), encoding='utf-8')
    engine = SimpleNamespace(as_of=dt.date(2026, 10, 13), cutoff=collected - dt.timedelta(seconds=1),
        securities=[{'company_id': 'company', 'security_id': 'security', 'codal_symbol': 'نماد',
                     'is_active': True, 'is_primary': True, 'price_rows': 1}],
        prices=[{'security_id': 'security', 'trade_date': dt.date(2026, 10, 12),
                 'collected_at': collected - dt.timedelta(days=1), 'closing_price_rial': 110,
                 'trade_value_rial': 200}])
    assert market.overlay(engine)['companies'] == 0
    engine.cutoff = collected
    assert market.overlay(engine)['companies'] == 1
    assert engine.prices[0]['closing_price_rial'] == 115
    assert engine.prices[0]['trade_value_rial'] == 200

def test_missing_open_requires_independent_official_corroboration():
    item = payload()
    item['candle_daily_adjusted'][0]['open'] = 0
    with pytest.raises(ValueError):
        validate(item, 'نماد', dt.date(2026, 10, 13))
    official = {'2026-10-12': {'priceFirst': 0, 'pDrCotVal': 115, 'priceMax': 120, 'priceMin': 100}}
    days = validate(item, 'نماد', dt.date(2026, 10, 13), official)
    assert days[0]['open'] == 0
    assert days[0]['open_missing_confirmed'] is True
    official['2026-10-12']['priceMax'] = 200
    with pytest.raises(ValueError):
        validate(item, 'نماد', dt.date(2026, 10, 13), official)
