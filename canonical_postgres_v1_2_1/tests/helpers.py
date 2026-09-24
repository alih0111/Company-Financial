"""Row builders and assertion helpers for the v1.2.1 integrity tests."""

from __future__ import annotations

import uuid
from contextlib import contextmanager


def uid() -> str:
    return str(uuid.uuid4())


def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())


def one(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


@contextmanager
def expect_error(conn, contains: str):
    """Execute inside a savepoint; assert a DB error mentioning `contains`."""
    raised = None
    try:
        with conn.transaction():  # savepoint when a transaction is active
            yield conn
    except Exception as exc:  # noqa: BLE001
        raised = exc
    assert raised is not None, f"expected DB error containing {contains!r}, but none was raised"
    msg = str(raised)
    assert contains.lower() in msg.lower(), (
        f"expected error containing {contains!r}, got: {msg}"
    )


# ---- core ----
def company(conn, name, normalized=None):
    cid = uid()
    q(conn, """INSERT INTO core.companies (id, display_name, normalized_name)
               VALUES (%s,%s,%s)""", (cid, name, normalized or name.lower()))
    return cid


def security(conn, company_id, ins=None, symbol=None, is_primary=False, valid_from=None, valid_to=None):
    sid = uid()
    q(conn, """INSERT INTO core.securities
               (id, company_id, tsetmc_ins_code, codal_symbol, security_type, is_primary, valid_from, valid_to)
               VALUES (%s,%s,%s,%s,'stock',%s,%s,%s)""",
      (sid, company_id, ins, symbol, is_primary, valid_from, valid_to))
    return sid


# ---- ingestion ----
def report(conn, company_id, source_report_id, security_id=None, supersedes=None,
           status="discovered", report_type="monthly"):
    rid = uid()
    q(conn, """INSERT INTO ingestion.reports
               (id, company_id, security_id, source, source_report_id, report_type,
                processing_status, supersedes_report_id)
               VALUES (%s,%s,%s,'codal',%s,%s,%s,%s)""",
      (rid, company_id, security_id, source_report_id, report_type, status, supersedes))
    return rid


def report_version(conn, report_id, version_no=1, content_hash=None, when="2026-01-01T10:00:00Z"):
    rv = uid()
    q(conn, """INSERT INTO ingestion.report_versions
               (id, report_id, version_no, content_hash, collected_at)
               VALUES (%s,%s,%s,%s,%s)""",
      (rv, report_id, version_no, content_hash or uid(), when))
    return rv


def parse_run(conn, report_version_id, parser_name="miansql", parser_version="v1",
              status="completed", finished=True):
    pr = uid()
    fin = "2026-01-01T11:00:00Z" if (finished or status != "running") else None
    q(conn, """INSERT INTO ingestion.parse_runs
               (id, report_version_id, parser_name, parser_version, status, finished_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
      (pr, report_version_id, parser_name, parser_version, status, fin))
    return pr


def metric(conn, code, statement_type="income_statement"):
    q(conn, """INSERT INTO fundamentals.metric_definitions
               (metric_code, statement_type, canonical_name)
               VALUES (%s,%s,%s) ON CONFLICT (metric_code) DO NOTHING""",
      (code, statement_type, code))


# ---- fundamentals ----
def monthly_activity(conn, company_id, report_id, report_version_id, parse_run_id,
                     period_end="2026-06-21", security_id=None, sales=1000):
    mid = uid()
    q(conn, """INSERT INTO fundamentals.monthly_activities
               (id, company_id, security_id, report_id, report_version_id, parse_run_id,
                period_end_date, sales_amount_rial, reported_sales_amount,
                reported_currency_unit, reported_unit_multiplier)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'million_rial',1000000)""",
      (mid, company_id, security_id, report_id, report_version_id, parse_run_id,
       period_end, sales, sales))
    return mid


def financial_statement(conn, company_id, report_id, report_version_id, parse_run_id,
                        statement_type="income_statement", period_end="2026-06-21"):
    fsid = uid()
    q(conn, """INSERT INTO fundamentals.financial_statements
               (id, company_id, report_id, report_version_id, parse_run_id,
                statement_type, period_end_date, reported_currency_unit)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'million_rial')""",
      (fsid, company_id, report_id, report_version_id, parse_run_id, statement_type, period_end))
    return fsid


def financial_fact(conn, statement_id, metric_code, period_order=1, value=100):
    q(conn, """INSERT INTO fundamentals.financial_facts
               (statement_id, metric_code, period_order, reported_value, canonical_value)
               VALUES (%s,%s,%s,%s,%s)""",
      (statement_id, metric_code, period_order, value, value * 1000000))
    return one(conn, "SELECT max(id) FROM fundamentals.financial_facts")[0]


# ---- market ----
def price_observation(conn, security_id, trade_date, closing, collected_at,
                      price_series="adjusted", adjustment_version="v1", obs_hash=None,
                      source="brs"):
    q(conn, """INSERT INTO market.price_observations
               (security_id, trade_date, price_series, closing_price_rial,
                is_adjusted, adjustment_version, source, collected_at, observation_hash)
               VALUES (%s,%s,%s,%s,true,%s,%s,%s,%s)""",
      (security_id, trade_date, price_series, closing, adjustment_version, source,
       collected_at, obs_hash or uid()))


# ---- portfolio ----
def portfolio(conn, name="p", ptype="paper"):
    pid = uid()
    q(conn, """INSERT INTO portfolio.portfolios (id, name, portfolio_type)
               VALUES (%s,%s,%s)""", (pid, name, ptype))
    return pid


def participant(conn, portfolio_id, name="pa"):
    paid = uid()
    q(conn, """INSERT INTO portfolio.participants (id, portfolio_id, name)
               VALUES (%s,%s,%s)""", (paid, portfolio_id, name))
    return paid


def account(conn, portfolio_id, participant_id=None, atype="cash"):
    aid = uid()
    q(conn, """INSERT INTO portfolio.accounts (id, portfolio_id, participant_id, account_type)
               VALUES (%s,%s,%s,%s)""", (aid, portfolio_id, participant_id, atype))
    return aid


def asset(conn, name="asset", security_id=None, asset_type="stock"):
    aid = uid()
    q(conn, """INSERT INTO portfolio.assets (id, security_id, asset_type, name)
               VALUES (%s,%s,%s,%s)""", (aid, security_id, asset_type, name))
    return aid


def txn(conn, portfolio_id, account_id, ttype, quantity_delta=0, cash_delta=0,
        effective_date="2026-06-21", trade_date=None, asset_id=None, participant_id=None,
        cost_basis=None, reverses=None, tx_id=None):
    tid = tx_id or uid()
    q(conn, """INSERT INTO portfolio.transactions
               (id, portfolio_id, account_id, participant_id, asset_id, transaction_type,
                effective_date, trade_date, quantity_delta, cash_delta_rial, cost_basis_rial,
                reverses_tx_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      (tid, portfolio_id, account_id, participant_id, asset_id, ttype,
       effective_date, trade_date, quantity_delta, cash_delta, cost_basis, reverses))
    return tid


# ---- analytics ----
def score_run(conn, score_version="v3.7", as_of="2026-06-21", cutoff="2026-06-20T00:00:00Z",
              status="running", completed=False):
    rid = uid()
    comp = "2026-06-21T00:00:00Z" if (completed or status != "running") else None
    q(conn, """INSERT INTO analytics.score_runs
               (id, score_version, as_of_date, source_cutoff_at, status, completed_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
      (rid, score_version, as_of, cutoff, status, comp))
    return rid


def company_score(conn, run_id, company_id, primary_security_id=None):
    q(conn, """INSERT INTO analytics.company_scores (run_id, company_id, primary_security_id)
               VALUES (%s,%s,%s)""", (run_id, company_id, primary_security_id))
    return one(conn, "SELECT max(id) FROM analytics.company_scores")[0]


def factor_score(conn, run_id, company_id, factor_code="SalesGrowth12MRank"):
    q(conn, """INSERT INTO analytics.factor_scores (run_id, company_id, factor_code)
               VALUES (%s,%s,%s)""", (run_id, company_id, factor_code))
    return one(conn, "SELECT max(id) FROM analytics.factor_scores")[0]


def metric_snapshot(conn, company_id, metric_code="ttm_net_profit", as_of="2026-06-21",
                    cutoff="2026-06-20T00:00:00Z", primary_security_id=None):
    q(conn, """INSERT INTO analytics.metric_snapshots
               (as_of_date, company_id, primary_security_id, metric_code,
                calculation_version, source_cutoff_at)
               VALUES (%s,%s,%s,%s,'v3.7',%s)""",
      (as_of, company_id, primary_security_id, metric_code, cutoff))
    return one(conn, "SELECT max(id) FROM analytics.metric_snapshots")[0]
