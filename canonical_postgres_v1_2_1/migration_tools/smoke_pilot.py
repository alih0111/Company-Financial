"""Minimal schema smoke test on the pilot DB (all rolled back)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from common import pg_pilot_conn

U = lambda: str(uuid.uuid4())


def main() -> int:
    c = pg_pilot_conn()
    try:
        with c.cursor() as cur:
            cid, sid = U(), U()
            cur.execute("INSERT INTO core.companies (id, display_name, normalized_name) VALUES (%s,'smoke','smoke')", (cid,))
            cur.execute("INSERT INTO core.securities (id, company_id, tsetmc_ins_code, security_type) VALUES (%s,%s,999999999,'stock')", (sid, cid))
            rid = U()
            cur.execute("INSERT INTO ingestion.reports (id, company_id, source, source_report_id, processing_status) VALUES (%s,%s,'smoke','S1','completed')", (rid, cid))
            rv = U()
            cur.execute("INSERT INTO ingestion.report_versions (id, report_id, version_no, content_hash) VALUES (%s,%s,1,%s)", (rv, rid, U()))
            pr = U()
            cur.execute("INSERT INTO ingestion.parse_runs (id, report_version_id, parser_name, parser_version, status, finished_at) VALUES (%s,%s,'smoke','v1','completed',now())", (pr, rv))
            cur.execute("""INSERT INTO fundamentals.monthly_activities
                (company_id, report_id, report_version_id, parse_run_id, period_end_date, sales_amount_rial, reported_sales_amount, reported_currency_unit, reported_unit_multiplier)
                VALUES (%s,%s,%s,%s,'2026-06-21',1000000,1,'million_rial',1000000)""", (cid, rid, rv, pr))
            fsid = U()
            cur.execute("""INSERT INTO fundamentals.financial_statements
                (id, company_id, report_id, report_version_id, parse_run_id, statement_type, period_end_date) VALUES (%s,%s,%s,%s,%s,'income_statement','2026-06-21')""", (fsid, cid, rid, rv, pr))
            cur.execute("INSERT INTO fundamentals.metric_definitions (metric_code, statement_type, canonical_name) VALUES ('revenue','income_statement','revenue') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO fundamentals.financial_facts (statement_id, metric_code, period_order, canonical_value, canonical_unit) VALUES (%s,'revenue',1,1000000,'rial')", (fsid,))
            cur.execute("""INSERT INTO market.price_observations
                (security_id, trade_date, closing_price_rial, observation_hash) VALUES (%s,'2026-06-21',12345,%s)""", (sid, U()))
            # portfolio reversal smoke
            pid, aid, asset = U(), U(), U()
            cur.execute("INSERT INTO portfolio.portfolios (id, name, portfolio_type) VALUES (%s,'smoke','paper')", (pid,))
            cur.execute("INSERT INTO portfolio.accounts (id, portfolio_id, account_type) VALUES (%s,%s,'cash')", (aid, pid))
            cur.execute("INSERT INTO portfolio.assets (id, asset_type, name) VALUES (%s,'stock','smoke-asset')", (asset,))
            buy = U()
            cur.execute("""INSERT INTO portfolio.transactions (id, portfolio_id, account_id, asset_id, transaction_type, effective_date, trade_date, quantity_delta, cash_delta_rial)
                           VALUES (%s,%s,%s,%s,'buy','2026-06-21','2026-06-21',10,-1000)""", (buy, pid, aid, asset))
            cur.execute("""INSERT INTO portfolio.transactions (portfolio_id, account_id, transaction_type, effective_date, reverses_tx_id)
                           VALUES (%s,%s,'reversal','2026-06-22',%s)""", (pid, aid, buy))
            cur.execute("SELECT COALESCE(SUM(quantity_delta),0) FROM portfolio.effective_transactions WHERE portfolio_id=%s", (pid,))
            qty = cur.fetchone()[0]
            assert qty == 0, f"reversal smoke failed: {qty}"
        c.rollback()
        print("SMOKE: PASS (all changes rolled back)")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
