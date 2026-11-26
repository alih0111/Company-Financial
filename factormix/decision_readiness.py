"""Fail-closed, side-effect-free readiness primitives for future execution paths.

This module does not authorize submission. Callers must supply provenance for
every input that can affect the decision, including the selection universe.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo


class Gate(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    UNKNOWN = 'UNKNOWN'


TEHRAN = ZoneInfo('Asia/Tehran')


@dataclass(frozen=True)
class Observation:
    symbol: str
    factor: str
    published_at: datetime | None
    first_seen_at: datetime | None
    received_at: datetime | None
    effective_at: datetime | None
    max_age: timedelta
    identity_verified: bool | None
    complete: bool | None
    evidence_gaps: tuple[str, ...] = ()


def assess_data(required, observations, decision_at):
    """Assess (symbol, factor) requirements; unrelated observations are ignored.

    A caller must include every candidate whose omission could alter a rank.
    Timestamps are timezone-aware; later revisions cannot rewrite earlier decisions.
    """
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError('decision_at must be timezone-aware')
    indexed = {}
    for row in observations:
        indexed.setdefault((row.symbol, row.factor), []).append(row)
    required = set(required)
    reasons = []
    for key in sorted(required):
        rows = indexed.get(key, [])
        if len(rows) != 1:
            reasons.append({'input': key, 'state': Gate.UNKNOWN.value, 'reason': 'missing_or_ambiguous'})
            continue
        row = rows[0]
        timestamps = (row.published_at, row.first_seen_at, row.received_at, row.effective_at)
        if row.identity_verified is False or row.complete is False:
            reason, state = 'identity_or_input_invalid', Gate.FAIL
        elif any(t is not None and t.utcoffset() is not None and t > decision_at for t in timestamps):
            reason, state = 'not_yet_available', Gate.FAIL
        elif any(t is None or t.utcoffset() is None for t in timestamps):
            reason, state = 'timestamp_unknown', Gate.UNKNOWN
        elif row.identity_verified is not True or row.complete is not True or row.evidence_gaps:
            reason, state = 'identity_or_completeness_unknown', Gate.UNKNOWN
        elif row.max_age < timedelta(0):
            reason, state = 'invalid_max_age', Gate.FAIL
        elif row.first_seen_at < row.published_at or row.received_at < row.first_seen_at:
            reason, state = 'inconsistent_provenance', Gate.FAIL
        elif decision_at - row.effective_at > row.max_age:
            reason, state = 'stale', Gate.FAIL
        else:
            continue
        detail = {'input': key, 'state': state.value, 'reason': reason}
        if row.evidence_gaps:
            detail['evidence_gaps'] = list(row.evidence_gaps)
        reasons.append(detail)
    if not required:
        reasons.append({'input': None, 'state': Gate.UNKNOWN.value, 'reason': 'requirements_unknown'})
    state = Gate.FAIL if any(r['state'] == Gate.FAIL for r in reasons) else Gate.UNKNOWN if reasons else Gate.PASS
    return {'state': state.value, 'reasons': reasons}


def money_to_rial(value: Decimal, unit: str) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or unit not in ('IRR', 'TOMAN'):
        raise ValueError('explicit finite Decimal and supported unit required')
    numerator, denominator = value.as_integer_ratio()
    rial, remainder = divmod(numerator * (10 if unit == 'TOMAN' else 1), denominator)
    if remainder:
        raise ValueError('fractional rial requires an explicit rounding policy')
    return rial


def ranking_deadline(row, max_age):
    if row.get('effective_date'):
        # Valid through the last allowed Tehran date. No publication or model
        # timestamp is inferred from this deadline.
        expires = date.fromisoformat(row['effective_date']) + timedelta(days=max_age)
        return datetime.combine(expires, time.max, TEHRAN)
    return datetime.fromisoformat(row['effective_at']) + timedelta(days=max_age)


def assess_source_ranking(required, evidence, limits, decision_at):
    indexed = {}
    for row in evidence:
        indexed.setdefault((row.get('symbol'), row.get('factor')), []).append(row)
    reasons = []
    for key in sorted(set(required)):
        rows = indexed.get(key, [])
        if len(rows) != 1:
            reasons.append(dict(input=key, state='UNKNOWN', reason='missing_or_ambiguous'))
            continue
        row = rows[0]
        gaps = row.get('evidence_gaps', [])
        reason, state = None, Gate.UNKNOWN
        try:
            received = datetime.fromisoformat(row['received_at']) if row.get('received_at') else None
            effective = date.fromisoformat(row['effective_date']) if row.get('effective_date') else None
            if row.get('complete') is False or row.get('identity_verified') is False:
                reason, state = 'identity_or_input_invalid', Gate.FAIL
            elif (received and received.utcoffset() is None) or (received and received > decision_at) or (
                    effective and effective > decision_at.astimezone(TEHRAN).date()):
                reason, state = 'not_yet_available', Gate.FAIL
            elif received is None or effective is None:
                reason = 'source_availability_unknown'
            elif row.get('identity_verified') is not True or row.get('complete') is not True or gaps:
                reason = 'source_window_unverified'
            elif decision_at > ranking_deadline(row, limits[key[1]]):
                reason, state = 'stale', Gate.FAIL
        except (ValueError, TypeError, KeyError):
            reason, state = 'invalid_source_time', Gate.FAIL
        if reason:
            reasons.append(dict(input=key, state=state.value, reason=reason, evidence_gaps=gaps))
    if not required:
        reasons.append(dict(input=None, state='UNKNOWN', reason='requirements_unknown'))
    state = Gate.FAIL if any(r['state'] == 'FAIL' for r in reasons) else Gate.UNKNOWN if reasons else Gate.PASS
    return {'state': state.value, 'reasons': reasons}


def assess_ranking(ranking, universe, execution, decision_at):
    """Validate evidence supplied by the ranking producer for the entire rank universe."""
    limits = {'eod': execution['max_mark_age'], 'financial': execution['max_financial_age'],
              'sales': execution['max_financial_age']}
    required = [(symbol, factor) for symbol in universe for factor in limits]
    if decision_at.utcoffset() is None:
        raise ValueError('decision_at must be timezone-aware')
    if ranking.get('evidence_version') == 2:
        data = assess_source_ranking(required, ranking.get('input_evidence', []), limits, decision_at)
    else:
        rows = []
        for row in ranking.get('input_evidence', []):
            factor = row.get('factor')
            if factor not in limits:
                continue
            try:
                timestamps = [datetime.fromisoformat(value) if value else None for value in (
                    row.get('published_at'), row.get('first_seen_at'), row.get('received_at'), row.get('effective_at'))]
            except (TypeError, ValueError):
                timestamps = [None] * 4
            rows.append(Observation(row.get('symbol'), factor, *timestamps,
                                    timedelta(days=limits[factor]), row.get('identity_verified'), row.get('complete'),
                                    tuple(row.get('evidence_gaps', ()))))
        data = assess_data(required, rows, decision_at)
    try:
        computed = datetime.fromisoformat(ranking['computed_at_utc'])
        if computed.utcoffset() is None or computed > decision_at:
            raise ValueError('invalid ranking timestamp')
    except (KeyError, TypeError, ValueError):
        data['state'] = Gate.FAIL.value
        data['reasons'].append({'input': None, 'state': Gate.FAIL.value, 'reason': 'invalid_ranking_timestamp'})
    return data


def readiness(*, service, data, strategy, broker, mode):
    if mode not in ('paper', 'live'):
        raise ValueError('unknown execution mode')
    values = {'service': service, 'data': data, 'strategy': strategy, 'broker': broker}
    if any(value not in tuple(x.value for x in Gate) for value in values.values()):
        raise ValueError('invalid gate value')
    required = ('service', 'data', 'strategy') + (('broker',) if mode == 'live' else ())
    # This primitive is deliberately incapable of authorizing actual submission.
    return {'mode': mode, **values, 'decision_ready': all(values[k] == Gate.PASS for k in required),
            'trading_allowed': False, 'submission_reason': 'execution_gate_not_implemented'}
