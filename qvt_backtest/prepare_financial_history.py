"""Inventory already discovered original Codal reports for a later historical
financial replay. Read-only: no downloads, database mutation or backdated facts.
"""
import datetime as dt
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "provenance_v1"), str(ROOT / "canonical_postgres_v1_2_1/analytics_canonical_v1")]
from complete_ranking_coverage import letters_for, select, OUT

ranking = json.loads((ROOT / "qvt_paper/output/current_ranking.json").read_text(encoding="utf8"))
rows = []
universe = [r for r in ranking["ranked"] + ranking["unscored"] if r["model_family"] == "general"]
for stock in universe:
    letters = letters_for(stock["symbol"], False, 0)
    # Keep actual publication timestamps and original report identity. This is
    # a collection inventory, not a claim that all cutoffs have usable facts.
    for period, (_, letter) in select(letters, dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)):
        if str(period) < "2019-01-01": continue
        tracing = str(letter["TracingNo"])
        raw = OUT / "raw" / f"{stock['symbol']}_{tracing}.html"
        rows.append({"company_id": stock["company_id"], "symbol": stock["symbol"],
                     "period_end": str(period), "tracing_no": tracing,
                     "published_original": letter.get("PublishDateTime"), "title": letter["Title"],
                     "decision_url": letter.get("Url"), "excel_url": letter.get("ExcelUrl"),
                     "html_already_cached": raw.exists()})
out = ROOT / "qvt_backtest/output"
pd.DataFrame(rows).to_csv(out / "financial_history_inventory.csv", index=False)
summary = {"general_companies": len(universe), "reports_discovered": len(rows),
           "companies_with_reports": len({r["company_id"] for r in rows}),
           "html_cached": sum(r["html_already_cached"] for r in rows),
           "not_yet_cached": sum(not r["html_already_cached"] for r in rows),
           "note": "Catalog inventory only; parent identity, tables, units, same-report windows and share history still require validation"}
(out / "financial_history_inventory.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps(summary, ensure_ascii=False))
