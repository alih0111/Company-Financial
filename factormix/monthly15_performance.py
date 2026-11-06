"""Publish only hash-verified registered monthly results alongside the parent."""
from pathlib import Path
import json
import shutil

import numpy as np
import pandas as pd

from factormix.reproduce_monthly15 import verify

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0'


def attach_monthly15(cases, folder):
    if not VERSION.exists():
        return
    verify(VERSION)
    policy = json.loads((VERSION / 'strategy.locked.json').read_text(encoding='utf8'))
    summary = json.loads((VERSION / 'results/summary.json').read_text(encoding='utf8'))
    record = json.loads((ROOT / 'strategy_registry/monthly15.registration.json').read_text(encoding='utf8'))
    import hashlib
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    archive = Path(record['archive'])
    assert digest(archive) == record['zip_sha256']
    case = next(c for c in cases if c['id'] == 'from-1401')
    nav = pd.read_csv(VERSION / 'results/monthly_jalali_15_nav.csv')
    parent = pd.read_csv(VERSION / 'results/original_quarterly_nav.csv')
    assert nav.session.tolist() == [p['date'] for p in case['path']]
    np.testing.assert_allclose(parent.nav_toman, [p['nav_toman'] for p in case['path']], rtol=0, atol=1)
    values = nav.nav_toman.to_numpy()
    dd = values / np.maximum.accumulate(np.r_[case['initial_toman'],values])[1:] - 1
    row = summary['accounts']['monthly_jalali_15']
    for point, value, drawdown in zip(case['path'], values, dd):
        point['monthly15_toman'] = float(value)
        point['monthly15_drawdown'] = float(drawdown)
    downloads = {}
    for key, source, name in [
        ('nav', VERSION / 'results/monthly_jalali_15_nav.csv', 'from-1401-monthly15-nav.csv'),
        ('trades', VERSION / 'results/monthly_jalali_15_trades.csv', 'from-1401-monthly15-trades.csv'),
        ('decisions', VERSION / 'results/monthly_jalali_15_decisions.csv', 'from-1401-monthly15-decisions.csv'),
        ('report', VERSION / 'REPORT.fa.md', 'from-1401-monthly15-report.fa.md'),
        ('guide', VERSION / 'STRATEGY.fa.md', 'from-1401-monthly15-guide.fa.md'),
        ('policy', VERSION / 'strategy.locked.json', 'from-1401-monthly15-policy.json'),
        ('archive', archive, 'from-1401-monthly15-v1.0.0.zip')]:
        shutil.copyfile(source, folder / name)
        downloads[key] = name
    trades = pd.read_csv(VERSION / 'results/monthly_jalali_15_trades.csv')
    ledger = row['ledger']
    case['monthly15'] = dict(strategy_id=policy['registry_id'], label='FactorMix · ماهانه ۱۵',
        policy_sha256=digest(VERSION / 'strategy.locked.json'), archive_sha256=record['zip_sha256'],
        account=dict(**row['metrics'], fees_toman=row['fees_toman'], slippage_toman=row['slippage_toman'],
            trade_count=row['fills'], buy_count=int((trades.side=='BUY').sum()),
            sell_count=int((trades.side=='SELL').sum()), decision_count=row['decisions'], first_fill=row['first_fill'],
            cash_toman=ledger['terminal_cash_toman'],
            holdings_value_toman=sum(p['market_value_toman'] for p in ledger['positions']), positions=ledger['positions']),
        annual=row['annual'], reviews_scheduled=row['reviews_scheduled'],
        stale_decisions_skipped=row['stale_decisions_skipped'], downloads=downloads,
        same_frozen_inputs_as_parent=True, only_review_calendar_changed=True)
