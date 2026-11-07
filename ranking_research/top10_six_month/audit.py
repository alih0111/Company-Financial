"""Independent checks of retained sources, timestamps, selections and cash."""
import json
import numpy as np
import pandas as pd
from .common import sha, read, write, checkpoint
from .factors import score


def audit(out):
    manifest = read(out / 'manifest.json'); checks = {}
    changed = [p for p, digest in manifest.items() if sha(p) != digest]
    checks['all_source_hashes_match'] = not changed
    checks['protocol_matches_registration'] = sha(out / 'protocol.json') == read(out / 'registration.json')['protocol_sha256']
    volume = read(out / 'volume_mapping_audit.json')
    checks['share_volume_not_transaction_count'] = volume['volume_field'] == 'qTotTran5J' and volume['correct_volume_price_bounds_fraction'] > .8
    f = pd.read_parquet(out / 'features_point_in_time.parquet')
    checks['no_outcomes_in_features'] = not any(c.startswith(('ret_', 'forward_', 'future_', 'outcome')) for c in f.columns)
    checks['unique_company_decision'] = not f.duplicated(['decision_time', 'company_id']).any()
    checks['no_current_family_or_industry'] = not {'model_family', 'industry'} & set(f.columns)
    checks['all_report_publications_before_cutoff'] = all(
        pd.Timestamp(rec['published_at']) < pd.Timestamp(row.publication_cutoff)
        for row in f.itertuples() for rec in json.loads(row.sources))
    stored = pd.read_parquet(out / 'scores.parquet'); rebuilt = score(f, read(out / 'protocol.json'))
    checks['scores_reproduce_without_outcomes'] = all(np.allclose(stored[m], rebuilt[m], equal_nan=True) for m in read(out / 'protocol.json')['weights'])
    if (out / 'daily_nav.csv').exists():
        fills = pd.read_csv(out / 'fills.csv'); cash = pd.read_csv(out / 'cash_ledger.csv')
        holdings = pd.read_csv(out / 'holdings.csv'); nav = pd.read_csv(out / 'daily_nav.csv')
        selections = pd.read_csv(out / 'selections.csv')
        checks['fills_strictly_after_decision'] = bool(fills.date.gt(fills.decision_time).all())
        checks['cash_never_negative'] = bool(nav.cash_rial.ge(-1e-5).all() and cash.cash_after_rial.ge(-1e-5).all())
        checks['cash_change_equals_fills'] = bool(np.allclose(cash.cash_change_rial,
              np.where(fills.side.eq('buy'), -fills.gross_rial, fills.gross_rial) - fills.fee_rial))
        initial = read(out / 'protocol.json')['initial_toman'] * 10
        checks['cash_conserved'] = bool(np.allclose(initial + cash.cash_change_rial.cumsum(), cash.cash_after_rial))
        values = holdings.groupby('date').value_rial.sum().reindex(nav.date, fill_value=0).to_numpy()
        checks['daily_nav_equals_cash_plus_positions'] = bool(np.allclose(nav.nav_rial, nav.cash_rial + values))
        # Reconstruct quantities independently from fills, including unsuccessful sales.
        quantities = {}; valid = True; by_date = {d: g for d, g in fills.groupby('date')}
        held_by_day = {d: g for d, g in holdings.groupby('date')}
        for day in nav.date:
            group = held_by_day.get(day, holdings.iloc[:0])
            for row in by_date.get(day, fills.iloc[:0]).itertuples():
                quantities[row.symbol] = quantities.get(row.symbol, 0) + (1 if row.side == 'buy' else -1) * row.index_units
            expected = {s: q for s, q in quantities.items() if q}
            actual = dict(zip(group.symbol, group.index_units))
            valid &= expected == actual
        checks['positions_reconcile_to_fills'] = bool(valid)
        reproduced = True
        for (date, model), group in selections.groupby(['decision_time', 'model']):
            candidate = stored[stored.decision_time.eq(date) & stored.eligible].sort_values([model, 'company_id'], ascending=[False, True]).head(10)
            reproduced &= candidate.company_id.tolist() == group.sort_values('rank').company_id.tolist()
        checks['top_ten_reproduce'] = bool(reproduced)
        trials = pd.read_csv(out / 'selection_trials.csv')
        checks['selection_windows_before_test'] = bool(trials.window_end_exclusive.le(trials.test_month).all())
        checks['no_dividend_double_count'] = not (out / 'dividend_cash_ledger.csv').exists()
    passed = all(bool(v) for v in checks.values())
    write(out / 'audit.json', {'status': 'passed' if passed else 'failed', 'checks': checks,
          'changed_paths': changed, 'source_files': len(manifest), 'economic_certification': False,
          'note': 'Passing arithmetic/source audit does not certify trading feasibility or ranking superiority.'})
    checkpoint(out, 'audit', 'complete' if passed else 'failed')
    if not passed: raise ValueError('independent_audit_failed: ' + ','.join(k for k, v in checks.items() if not v))
