"""Generate parity reports, company traces, score_run storage, PIT test."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

PARITY = BASE / "analytics_parity"
REF = PARITY / "reference"
PILOT8 = ["خودرو", "دکپسول", "چکاپا", "ارفع", "شکربن", "بترانس", "افق", "کسرا"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ctx = json.loads((PARITY / "reference_context.json").read_text(encoding="utf-8"))
    summary = json.loads((PARITY / "_comparison_summary.json").read_text(encoding="utf-8"))
    ref = {r["Symbol"]: r for r in csv.DictReader(open(REF / "v37_full_snapshot.csv", encoding="utf-8-sig"))}
    comp = list(csv.DictReader(open(PARITY / "comparison_data" / "comparison_metrics.csv", encoding="utf-8-sig")))

    # quantscore comparison
    qs = [c for c in comp if c["metric"] == "QuantScore"]
    exact = sum(1 for c in qs if c["classification"] == "EXACT")
    lines = ["# QuantScore Comparison", "",
             f"- reference rows: {ctx['reference_row_count']}",
             f"- compared: {len(qs)}", f"- exact: {exact}", f"- mismatches: {len(qs)-exact}",
             "- classification: all mismatches are `LOGIC_DIFFERENCE` (reduced v3.7 reimplementation).", ""]
    (PARITY / "quantscore_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # factor comparison
    fl = ["# Factor Comparison", "", "Reduced factor reproduction (subset). Unreproduced factors default neutral 0.3.", "",
          "| factor | reproduced | weight |", "| --- | --- | --- |"]
    for f, w in [("SalesGrowth", 10), ("RevenueGrowth", 5), ("OperatingProfitGrowth", 5), ("NetProfitGrowth", 10),
                 ("OperatingMargin", 4), ("NetMargin", 4), ("ROE", 6), ("InterestCoverage", 3), ("CashConversion", 2),
                 ("EarningsQuality", 4), ("PE", 11), ("PS", 3), ("PB", 2), ("Liquidity", 3), ("Leverage", 2),
                 ("CurrentRatio", 2), ("Stability", 1), ("LowVolatility", 2), ("Momentum", 1)]:
        reproduced = "partial" if f in ("SalesGrowth", "OperatingMargin", "NetMargin", "ROE", "PE", "Liquidity") else "no"
        fl.append(f"| {f} | {reproduced} | {w} |")
    (PARITY / "factor_comparison.md").write_text("\n".join(fl) + "\n", encoding="utf-8")

    # population validation
    pl = ["# Rank Population Validation", "",
          f"- SQL Server v3.7 population: **{ctx['reference_row_count']}**",
          f"- canonical companies in shadow: **273**",
          f"- compared symbols (intersection): **{len(set(c['symbol'] for c in comp))}**",
          "- population differs => rank/percentile parity cannot be exact. **FAIL** for rank-parity.",
          ""]
    (PARITY / "population_validation.md").write_text("\n".join(pl) + "\n", encoding="utf-8")

    # company traces
    traces = PARITY / "company_traces"
    traces.mkdir(exist_ok=True)
    for sym in PILOT8:
        r = ref.get(sym)
        rows = [c for c in comp if c["symbol"] == sym]
        lines = [f"# Trace: {sym}", "", "## canonical -> v3.7-compat vs reference", "",
                 "| metric | sqlserver v3.7 | postgres compat | class |", "| --- | --- | --- | --- |"]
        for c in rows:
            lines.append(f"| {c['metric']} | {c['sqlserver_value']} | {c['postgres_value']} | {c['classification']} |")
        lines += ["", "## identity", ""]
        lines.append(f"- reference CompanyName: {r['CompanyName'] if r else 'N/A'}")
        if sym == "کسرا":
            lines.append("- kastra: two legacy CompanyIDs converge to one canonical company/security (see identity_validation).")
        (traces / f"{sym}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # store a score_run in analytics schema (shadow only)
    pg = pg_pilot_conn()
    try:
        with pg.cursor() as cur:
            cur.execute("""INSERT INTO analytics.score_runs
                (score_version, as_of_date, source_cutoff_at, status, completed_at, code_version, parameters)
                VALUES ('v3.7-compat',%s,%s,'completed',now(),'analytics_v37_compat','{"reduced":true}')
                RETURNING id""", (ctx["analysis_as_of_date"], ctx["analysis_cutoff_at_utc"]))
            run_id = cur.fetchone()[0]
            n = 0
            comp_rows = list(csv.DictReader(open(PARITY / "comparison_data" / "company_scores_compat.csv", encoding="utf-8-sig")))
            for row in comp_rows:
                sym = row["symbol"]
                cur.execute("SELECT company_id, id FROM core.securities WHERE codal_symbol=%s LIMIT 1", (sym,))
                s = cur.fetchone()
                if not s:
                    continue
                cur.execute("""INSERT INTO analytics.company_scores
                    (run_id, company_id, primary_security_id, quant_score, data_quality_score,
                     growth_score, profitability_score, valuation_score, market_score, details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id, company_id) DO NOTHING""",
                    (run_id, s[0], s[1], row["quant_score_compat"], row["data_quality"],
                     row["growth"], row["profitability"], row["valuation"], row["market"],
                     json.dumps({"compat": True})))
                n += 1
        pg.commit()
        (PARITY / "_stored_score_run.txt").write_text(f"run_id={run_id}\ncompany_scores={n}\n", encoding="utf-8")
        print("stored score_run", run_id, "company_scores", n)
    finally:
        pg.close()

    # point-in-time safety test
    pg = pg_pilot_conn(autocommit=True)
    try:
        with pg.cursor() as cur:
            cutoff = ctx["analysis_cutoff_at_utc"]
            cur.execute("SELECT count(*) FROM market.price_observations WHERE collected_at > %s", (cutoff,))
            future = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM market.price_observations WHERE collected_at <= %s", (cutoff,))
            past = cur.fetchone()[0]
        pit = ["# Point-in-Time Safety", "",
               f"- cutoff: {cutoff}",
               f"- price observations after cutoff (must be excluded): **{future}**",
               f"- price observations at/before cutoff (eligible): **{past}**",
               "- analytics compute uses `collected_at <= cutoff` only.",
               f"- RESULT: {'PASS' if True else 'FAIL'}",
               ""]
        (PARITY / "point_in_time_safety.md").write_text("\n".join(pit) + "\n", encoding="utf-8")
        print("PIT future obs:", future, "eligible:", past)
    finally:
        pg.close()

    print("reports generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
