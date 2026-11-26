"""Verify the official versions behind FactorMix's adjustment and share inputs."""
from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
import json
import math


def official_rows(files, source, instrument, endpoint, field, as_of, *, allow_same_date=False):
    from factormix.ranking_evidence import EvidenceError, exchange_day, local_day

    if not source:
        raise EvidenceError(field + '_receipt_missing')
    if source.get('url') != f'https://cdn.tsetmc.com/api/{endpoint}/{instrument}':
        raise EvidenceError(field + '_source_identity_mismatch', True)
    try:
        body, received = files.receipt(source, path='raw_path', digest='raw_sha256')
        if received > as_of:
            raise EvidenceError(field + '_received_after_decision', True)
        rows = json.loads(body)[field]
        if not isinstance(rows, list):
            raise ValueError('array required')
        indexed = defaultdict(list)
        for row in rows:
            effective = exchange_day(row['dEven'])
            if (str(row['insCode']) != str(instrument) or not effective or
                    effective in indexed and not allow_same_date or effective > local_day(received)):
                raise ValueError('invalid row identity, date or version')
            indexed[effective].append(row)
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise EvidenceError(field + '_payload_invalid', True) from exc
    return indexed, received


def positive_integer(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value != int(value):
        raise ValueError('positive integer expected')
    return int(value)


def verify_adjustments(files, source, instrument, bars, model, first, through, as_of):
    from factormix.ranking_evidence import EvidenceError, day

    rows, received = official_rows(files, source, instrument, 'ClosingPrice/GetPriceAdjustList', 'priceAdjust', as_of,
                                   allow_same_date=True)
    dates = sorted(bars)
    derived = {}
    try:
        for declared, versions in rows.items():
            pos = bisect_right(dates, declared)
            if pos == len(dates) or not first < dates[pos] <= through:
                continue
            effective = dates[pos]
            if not pos or effective in derived:
                raise ValueError('ambiguous adjustment boundary')
            previous, following = bars[dates[pos - 1]], bars[effective]
            before = positive_integer(previous['pClosing'])
            after = positive_integer(following['priceYesterday'])
            edges = {(positive_integer(row['pClosingNotAdjusted']), positive_integer(row['pClosing']))
                     for row in versions}
            edges = {(a, b) for a, b in edges if a != b}
            current = before
            visited = {before}
            while edges:
                successors = [edge for edge in edges if edge[0] == current]
                if len(successors) != 1:
                    break
                edge = successors[0]
                edges.remove(edge)
                current = edge[1]
                if current in visited:
                    raise ValueError('cyclic same-date adjustment versions')
                visited.add(current)
            if edges or current != after:
                raise ValueError('adjustment version differs from daily reference reset')
            if before != after:
                derived[effective] = (declared, Fraction(after, before))
    except (KeyError, ValueError, TypeError) as exc:
        raise EvidenceError('adjustment_values_or_effective_date_mismatch', True) from exc
    expected = {day(d): f for d, f in model}
    if len(expected) != len(model) or set(expected) != set(derived):
        raise EvidenceError('adjustment_model_event_set_mismatch', True)
    if any(not math.isclose(expected[d], float(pair[1]), rel_tol=0, abs_tol=5.1e-9)
           for d, pair in derived.items()):
        raise EvidenceError('adjustment_model_factor_mismatch', True)
    return received, [dict(source_date=declared.isoformat(), effective_date=effective.isoformat(),
                           numerator=ratio.numerator, denominator=ratio.denominator)
                      for effective, (declared, ratio) in sorted(derived.items())]


def verify_share_interval(files, source, instrument, identity, interval, mark, cutoff, as_of):
    from factormix.ranking_evidence import EvidenceError, day

    rows, received = official_rows(files, source, instrument, 'Instrument/GetInstrumentShareChange',
                                   'instrumentShareChange', as_of)
    try:
        changes = {d: (positive_integer(r[0]['numberOfShareOld']), positive_integer(r[0]['numberOfShareNew']))
                   for d, r in rows.items()}
        changes = {d: pair for d, pair in changes.items() if pair[0] != pair[1]}
        first, end = day(interval['valid_from']), day(interval.get('valid_to'))
        if any(str(interval[k]) != str(identity[k]) for k in ('company_id', 'security_id')):
            raise ValueError('model interval identity mismatch')
        anchor = max((d for d in changes if d <= mark), default=None)
        if anchor is None:
            raise EvidenceError('share_interval_source_anchor_missing')
        next_event = min((d for d in changes if d > anchor), default=None)
        if any(changes[a][1] != changes[b][0] for a, b in zip(sorted(changes), sorted(changes)[1:])
               if a >= anchor and b <= cutoff):
            raise ValueError('share version chain is discontinuous')
        if (not first or first > mark or mark > cutoff or (end is not None and cutoff >= end)
                or next_event is not None and next_event <= cutoff
                or end is not None and end != next_event
                or positive_integer(interval['shares_outstanding']) != changes[anchor][1]):
            raise ValueError('model interval differs from official share change')
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise EvidenceError('share_interval_model_version_mismatch', True) from exc
    return received, dict(valid_from=first.isoformat(), source_effective_date=anchor.isoformat(),
                          verified_from=max(first, anchor).isoformat(), verified_through=cutoff.isoformat(),
                          shares_outstanding=changes[anchor][1])
