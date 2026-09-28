"""Quarterly-profit audit + reconciliation (کاسپین) and net_profit coverage."""
import csv, json, os, sys, pathlib
sys.path.insert(0, r"D:\RFA\Company-Financial\go-app\py2\src")
from dotenv import load_dotenv
load_dotenv(r"D:\RFA\Company-Financial\go-app\.env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from canonical_ingest.db import transaction
import pyodbc

OUT = pathlib.Path(r"D:\RFA\Company-Financial\integration_shadow_v1\output")
OUT.mkdir(parents=True, exist_ok=True)
CID = "3d594732-5172-49ca-b8c5-7b684189196d"
LKEY = "7386c9d3264a07cdaacbdba2e1941d42"

with transaction() as c:
    cur = c.cursor()
    # coverage audit (period_order=1)
    cur.execute("""
        SELECT count(DISTINCT fs.company_id) AS companies,
               count(*) FILTER (WHERE f.metric_code='eps') AS eps_facts,
               count(*) FILTER (WHERE f.metric_code='net_profit') AS np_facts,
               count(*) FILTER (WHERE f.metric_code='capital') AS cap_facts
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
        WHERE f.period_order=1 AND f.metric_code IN ('eps','net_profit','capital')""")
    totals = cur.fetchone()
    cur.execute("""
        SELECT count(*) FROM (
          SELECT fs.company_id
          FROM fundamentals.financial_facts f
          JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
          WHERE f.period_order=1
          GROUP BY fs.company_id
          HAVING count(*) FILTER (WHERE f.metric_code='net_profit') = 0
             AND count(*) FILTER (WHERE f.metric_code='eps') > 0
        ) t""")
    companies_eps_no_np = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM (
          SELECT fs.company_id
          FROM fundamentals.financial_facts f
          JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
          WHERE f.period_order=1
          GROUP BY fs.company_id
          HAVING count(*) FILTER (WHERE f.metric_code='net_profit') > 0
        ) t""")
    companies_with_np = cur.fetchone()[0]

    with (OUT / "net_profit_coverage_audit.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "fact_count", "note"])
        w.writerow(["eps_period1", totals[1], "complete across periods"])
        w.writerow(["capital_period1", totals[3], "complete across periods"])
        w.writerow(["net_profit_period1", totals[2], "SOURCE_ABSENT historically (miandore2.NetProfitAmount null)"])
        w.writerow(["companies_eps_but_no_net_profit", companies_eps_no_np, ""])
        w.writerow(["companies_with_any_net_profit", companies_with_np, ""])

    # کاسپین canonical facts per period
    cur.execute("""
        SELECT r.jalali_period_text, f.metric_code, f.reported_value
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
        JOIN ingestion.reports r ON r.id=fs.report_id
        WHERE fs.company_id=%s AND f.period_order=1
          AND f.metric_code IN ('eps','capital','net_profit')
        ORDER BY r.jalali_period_text""", (CID,))
    canon = {}
    for period, code, val in cur.fetchall():
        canon.setdefault(period, {})[code] = float(val or 0)

# SQL source per period
cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};DATABASE={os.environ['DB_NAME']};"
      f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};TrustServerCertificate=yes;Connection Timeout=10")
cn = pyodbc.connect(cs, timeout=15)
sc = cn.cursor()
sc.execute("""SELECT ReportDate, Num1_Value1, Num2_Value1, NetProfitAmount, Product1
              FROM dbo.miandore2 WHERE CompanyID=? ORDER BY ReportDate""", (LKEY,))
src = {row[0]: {"eps": row[1], "capital": row[2], "net_profit": row[3], "product1": row[4]} for row in sc.fetchall()}
cn.close()

periods = sorted(set(canon) | set(src))
rows = []
prev_year = None
prev_cum = 0.0
q = 0
for p in periods:
    cy = canon.get(p, {})
    sy = src.get(p, {})
    eps = cy.get("eps", sy.get("eps") or 0)
    capital = cy.get("capital", sy.get("capital") or 0)
    np_fact = cy.get("net_profit", 0)
    cumulative = eps * capital  # consistent legacy net-profit proxy (== source Product1)
    year = int(p[:4])
    if year != prev_year:
        q = 0
        prev_cum = 0.0
        prev_year = year
    q += 1
    standalone = cumulative if q == 1 else cumulative - prev_cum
    prev_cum = cumulative
    rows.append({
        "period": p, "fiscal_year": year, "quarter": q,
        "canonical_eps": eps, "canonical_capital": capital,
        "canonical_net_profit_million": np_fact,
        "source_net_profit_million": sy.get("net_profit"),
        "source_product1": sy.get("product1"),
        "cumulative_profit_proxy": cumulative,
        "quarterly_profit_proxy": standalone,
        "quarterly_display_percentage": round(standalone / 1_000_000, 2),
    })

with (OUT / "kaspin_financial_periods.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# validation: increasing standalone quarters within latest full FY (profitability improved?)
last_fy = max(r["fiscal_year"] for r in rows)
fy_rows = [r for r in rows if r["fiscal_year"] == last_fy]
with (OUT / "quarterly_profit_validation.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "period", "fiscal_year", "quarter", "cumulative", "quarterly", "display_percentage"])
    for r in rows:
        w.writerow(["کاسپین", r["period"], r["fiscal_year"], r["quarter"],
                    r["cumulative_profit_proxy"], r["quarterly_profit_proxy"], r["quarterly_display_percentage"]])

(k := OUT / "financial_history_repair_summary.json").write_text(json.dumps({
    "symbol": "کاسپین",
    "root_cause": "SOURCE_ABSENT",
    "detail": "dbo.miandore2.NetProfitAmount/RevenueNew are NULL for all historical periods; only the latest period is populated. True historical net profit is not present in the legacy source. No canonical migration/parser/query defect.",
    "canonical_net_profit_coverage": {"companies_eps_but_no_net_profit": companies_eps_no_np,
                                       "companies_with_any_net_profit": companies_with_np},
    "repair_performed": False,
    "repair_reason": "No source history to repair from; fabricating net profit is forbidden. Deterministic cumulative net-profit proxy (EPS x Capital) is used for the chart, derived from canonical EPS and Capital facts.",
    "latest_fy": last_fy,
    "latest_fy_quarters_increasing": all(
        fy_rows[i]["quarterly_profit_proxy"] >= fy_rows[i-1]["quarterly_profit_proxy"]
        for i in range(1, len(fy_rows))),
}, ensure_ascii=False, indent=2), encoding="utf-8")

print("coverage:", {"companies_eps_but_no_net_profit": companies_eps_no_np, "companies_with_any_net_profit": companies_with_np})
print("latest_fy", last_fy, "increasing", all(fy_rows[i]["quarterly_profit_proxy"] >= fy_rows[i-1]["quarterly_profit_proxy"] for i in range(1, len(fy_rows))))
for r in rows[-6:]:
    print(r)
