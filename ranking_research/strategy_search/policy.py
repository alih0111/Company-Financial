"""Portfolio policies. Wave 1 fixes one policy; wave 2 options are documented but
are not executed until wave 1 is delivered.

The fixed wave-1 policy is deliberately identical to the frozen predecessor:
equal weight, top 10, monthly rebalance, 0.5% cost per side, capacity 1% of the
trailing median traded value, execution at the next session open. This keeps the
signal comparison on one shared execution rule instead of mixing definitions.
"""

FIXED_WAVE1 = {
    'name': 'ew_top10_monthly',
    'top_n': 10,
    'weight': 'equal',
    'cadence_months': 1,
    'cost_per_side': 0.005,
    'delay_sessions': 0,
    'initial_toman': 100_000_000,
    'enforce_member_limit': True,
}

# Declared but NOT run in this stage. Each will be registered before its wave.
WAVE2_OPTIONS = {
    'cadence': [1, 0.5, 3, 0.25],          # monthly, biweekly, quarterly, weekly
    'entry_rank': [10],
    'exit_rank_buffer': [15, 20],
    'weight': ['equal', 'inverse_vol_capped'],
    'top_n': [5, 10, 15],
    'holding': ['calendar', 'hold_until_rank_weakens'],
    'market_filter': ['none', 'trailing_index_filter_keeps_cash'],
}


def schedule_for(scores, policy, start_month='2022-03', end_month='2026-03'):
    """Monthly schedule mapping each decision date to (model, target count)."""
    from ranking_research.top10_six_month.walk_forward import make_schedule
    cadence = max(1, int(round(1 / policy['cadence_months']))) if policy['cadence_months'] < 1 else policy['cadence_months']
    return make_schedule(scores, start_month, end_month, 'score', cadence)
