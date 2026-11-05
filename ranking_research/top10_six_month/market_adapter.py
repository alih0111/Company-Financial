"""Correct legacy TSETMC field names locally, without modifying old studies."""
import numpy as np


def correct_volume(md):
    checked = 0; bounded = 0; count_would_be_bounded = 0
    for rec in md.data.values():
        if rec.get('_volume_contract') != 'qTotTran5J':
            # Legacy v2lib reads qTotTran5J into tcnt and zTotTran into vol.
            rec['vol'], rec['tcnt'] = rec['tcnt'].copy(), rec['vol'].copy()
            rec['_volume_contract'] = 'qTotTran5J'
        good = (rec['vol'] > 0) & (rec['tcnt'] > 0) & (rec['tval'] > 0) & np.isfinite(rec['l']) & np.isfinite(rec['h']) & (rec['l'] > 0) & (rec['h'] >= rec['l'])
        avg = rec['tval'][good] / rec['vol'][good]
        wrong = rec['tval'][good] / rec['tcnt'][good]
        lo = rec['l'][good] * .99 - 1; hi = rec['h'][good] * 1.01 + 1
        checked += int(good.sum()); bounded += int(((avg >= lo) & (avg <= hi)).sum())
        count_would_be_bounded += int(((wrong >= lo) & (wrong <= hi)).sum())
    if checked and bounded / checked < .8:
        raise ValueError('volume_value_price_identity_failed')
    return {'volume_field': 'qTotTran5J', 'transaction_count_field': 'zTotTran',
            'turnover_field': 'qTotCap', 'ohlc_value_identity_observations': checked,
            'correct_volume_price_bounds_fraction': bounded / checked if checked else None,
            'transaction_count_as_volume_price_bounds_fraction': count_would_be_bounded / checked if checked else None,
            'legacy_shared_library_modified': False}
