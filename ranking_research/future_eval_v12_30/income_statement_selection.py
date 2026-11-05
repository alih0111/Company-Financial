"""Pure selection helpers for income-statement factor inputs."""

INCOME_METRICS = {"revenue", "operating_profit", "net_profit", "other_non_operating", "finance_cost", "eps"}


def income_statement_view(report_index):
    """Retain only periods that contain at least one income statement item."""
    selected = {
        company_id: {period: cell for period, cell in periods.items() if INCOME_METRICS.intersection(cell)}
        for company_id, periods in report_index.items()
    }
    return {company_id: periods for company_id, periods in selected.items() if periods}


def latest_income_statement_cell(income_index, company_id):
    periods = income_index.get(str(company_id), {})
    latest = max(periods, default=None)
    return latest, periods.get(latest, {})


def locked_engine_factor(candidate):
    """Never replace a missing TTM output with a single-report point ratio."""
    try:
        value = float(candidate)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value
