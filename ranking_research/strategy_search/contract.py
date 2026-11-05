"""Feature and access-time contract. Fails loudly on any future information."""
import json
import numpy as np
import pandas as pd

FORBIDDEN_PREFIXES = ('ret_', 'forward_', 'outcome', 'future_', 'label_')
REQUIRED = ('decision_time', 'company_id', 'symbol')
SCORE_REQUIRED = ('eligible', 'score')


class ContractError(ValueError):
    pass


def check_panel(frame):
    """Structural checks on a point-in-time feature panel."""
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ContractError('missing_required_columns: ' + ','.join(missing))
    future = [c for c in frame.columns if str(c).startswith(FORBIDDEN_PREFIXES)]
    if future:
        raise ContractError('future_outcome_columns_present: ' + ','.join(future))
    if frame.duplicated(['decision_time', 'company_id']).any():
        raise ContractError('duplicate_company_decision')
    return True


def check_score_frame(frame):
    """A frame handed to the engine must carry eligibility and a finite score
    where eligible (corrective 2.3: notna alone does not reject infinities)."""
    missing = [c for c in SCORE_REQUIRED if c not in frame.columns]
    if missing:
        raise ContractError('missing_score_columns: ' + ','.join(missing))
    if len(frame):
        elig = frame.eligible.fillna(False).astype(bool)
        bad = frame[elig & frame.score.isna()]
        if len(bad):
            raise ContractError(f'eligible_rows_without_score: {len(bad)}')
        scores = pd.to_numeric(frame.score, errors='coerce')
        nonfinite = frame[elig & ~np.isfinite(scores.astype(float))]
        if len(nonfinite):
            raise ContractError(f'eligible_rows_with_nonfinite_score: {len(nonfinite)}')
    return True


def check_publication(frame):
    """Every used report must be published strictly before the decision cutoff.

    Rows whose sources are unknown are allowed only when they are explicitly
    ineligible; a row cannot be eligible with `publication_valid` False.
    """
    if 'eligible' not in frame.columns:
        return True
    if 'publication_valid' in frame:
        bad = frame[frame.eligible & ~frame.publication_valid.fillna(False)]
        if len(bad):
            raise ContractError(f'eligible_row_with_unverified_publication: {len(bad)}')
    if 'source_valid' in frame:
        bad = frame[frame.eligible & ~frame.source_valid.fillna(False)]
        if len(bad):
            raise ContractError(f'eligible_row_with_invalid_source: {len(bad)}')
    if 'publication_cutoff' in frame:
        for row in frame.itertuples():
            if not getattr(row, 'eligible'):
                continue
            pub = getattr(row, 'publication_cutoff', None)
            if pub is None:
                raise ContractError(f'eligible_row_without_publication_cutoff: {row.company_id}')
            if pd.Timestamp(pub) > pd.Timestamp(row.decision_time):
                raise ContractError(f'publication_after_decision: {row.company_id} {row.decision_time}')
    return True


def check_growth_handling(frame):
    """A percentage growth from a near-zero or negative base is not normal growth."""
    if 'eligible' not in frame.columns:
        return True
    if {'growth_state', 'prior_net_profit_ttm'} <= set(frame.columns):
        eps = 1e6
        mask = frame.eligible & frame.growth_state.eq('normal') & frame.prior_net_profit_ttm.lt(eps)
        if mask.any():
            raise ContractError(f'normal_growth_with_sub_resolution_base: {int(mask.sum())}')
    return True


def check_labels_mature(labels, training_cutoff, horizon_months):
    """No label may be consumed before its outcome window has completed.

    Correct condition (corrective 2.6): the label's ACTUAL end time must be <=
    the training cutoff. The actual end is the later of (decision + horizon,
    realized exit mark); horizon is added ONLY to the decision date, never also
    to the sample/as-of date (which silently accepted immature labels).
    """
    if labels is None or len(labels) == 0:
        return True
    cutoff = pd.Timestamp(training_cutoff)
    if 'actual_label_end_time' in labels.columns:
        end = pd.to_datetime(labels.actual_label_end_time, errors='coerce')
        immature = labels[end.isna() | (end > cutoff)]
    elif 'horizon_end' in labels.columns:
        end = pd.to_datetime(labels.horizon_end, errors='coerce')
        immature = labels[end.isna() | (end > cutoff)]
    else:
        end = (pd.to_datetime(labels.decision_time, errors='coerce')
               + pd.DateOffset(months=horizon_months))
        immature = labels[end.isna() | (end > cutoff)]
    if len(immature):
        raise ContractError(f'immature_labels_used: {len(immature)}')
    return True


def summarize(frame):
    return {
        'rows': int(len(frame)),
        'months': int(frame.decision_time.nunique()),
        'symbols': int(frame.symbol.nunique()),
        'eligible_rows': int(frame.eligible.sum()) if 'eligible' in frame else None,
        'first_month': str(frame.decision_time.min())[:7],
        'last_month': str(frame.decision_time.max())[:7],
        'families': (frame.historical_family.value_counts().to_dict()
                     if 'historical_family' in frame else None),
    }
