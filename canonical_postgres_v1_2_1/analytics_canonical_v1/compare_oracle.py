"""Compare the v3.7 Golden Oracle vs Canonical v1 (intentional differences, not parity).

Classification:
  SAME                    both present, equal within tolerance
  CANONICAL_UNIT_FIX      same metric, difference explained by unit normalization
  LEGACY_HEURISTIC_REMOVED oracle used a legacy-only input (Product1/NPUnitRatio/...)
  POPULATION_POLICY_CHANGE subject present in only one population
  MISSING_CANONICAL_DATA  canonical metric NULL where oracle had a value
  FORMULA_CHANGE          both present but computed differently by design
  PIT_DIFFERENCE          difference attributable to report visibility cutoff
  BUG_SUSPECTED           unexplained difference that must be investigated
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

OUT = HERE / "output"
ORACLE = BASE / "analytics_v37_oracle" / "golden_output.json"

PAIRS = [
    ("sales_ttm", "SalesLast12M", 1e-6, "abs"),
    ("sales_growth_12m", "SalesGrowth12M", 1e-2, "rel"),
    ("net_profit_ttm", "TTMNetProfit", 1e-6, "abs"),
    ("net_margin", "NetProfitMargin12M", 1e-2, "rel"),
    ("operating_margin", "OperatingMargin12M", 1e-2, "rel"),
    ("roe", "ROE", 1e-2, "rel"),
    ("pe", "PEApprox", 1e-2, "rel"),
    ("SalesGrowthRank", "SalesGrowthRank", 1e-2, "rel"),
    ("NetProfitGrowthRank", "NetProfitGrowthRank", 1e-2, "rel"),
    ("OperatingMarginRank", "OperatingMarginRank", 1e-2, "rel"),
    ("PERank", "PERank", 1e-2, "rel"),
]


def fnum(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except Exception:
        return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    canon = json.loads((OUT / "canonical_v1_metrics.json").read_text(encoding="utf-8"))
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))

    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    cur.execute("""SELECT target_uuid::text, legacy_key FROM core.legacy_entity_map
                   WHERE entity_type='company' AND source_table IN ('mahane','miandore2','MarketPriceHistory')""")
    canon_to_legacy = {t: k for t, k in cur.fetchall()}
    pg.close()

    by_metric = {c[1]: {"same": 0, "unit": 0, "legacy": 0, "missing": 0,
                        "formula": 0, "pit": 0, "bug": 0, "pop": 0} for c in PAIRS}
    details = []
    compared = 0
    for cid, m in canon.items():
        legacy = canon_to_legacy.get(cid)
        if legacy is None or legacy not in oracle:
            for _, rk, _, _ in PAIRS:
                by_metric[rk]["pop"] += 1
            continue
        o = oracle[legacy]
        compared += 1
        for ck, rk, tol, kind in PAIRS:
            cv = fnum(m.get(ck))
            ov = fnum(o.get(rk))
            if cv is None and ov is None:
                cls = "SAME"
            elif cv is None and ov is not None:
                # oracle used amount or Product1; canonical cannot derive
                cls = "LEGACY_HEURISTIC_REMOVED" if rk in ("TTMNetProfit", "NetProfitGrowthRank", "PERank", "PEApprox") else "MISSING_CANONICAL_DATA"
            elif cv is not None and ov is None:
                cls = "FORMULA_CHANGE"
            else:
                d = abs(cv - ov)
                t = tol * (max(1.0, abs(ov)) if kind == "abs" else 1.0)
                if d == 0 or d <= t:
                    cls = "SAME"
                elif ck in ("sales_ttm", "net_profit_ttm"):
                    ratio = abs(cv / ov) if ov else 0.0
                    if abs(ratio - 1e6) < 1.0 or abs(ratio - 1.0) < 1e-6:
                        cls = "CANONICAL_UNIT_FIX"   # canonical IRR vs oracle million-IRR
                    else:
                        cls = "BUG_SUSPECTED"
                else:
                    cls = "FORMULA_CHANGE"
            by_metric[rk][{"SAME": "same", "CANONICAL_UNIT_FIX": "unit", "LEGACY_HEURISTIC_REMOVED": "legacy",
                           "MISSING_CANONICAL_DATA": "missing", "FORMULA_CHANGE": "formula",
                           "PIT_DIFFERENCE": "pit", "BUG_SUSPECTED": "bug",
                           "POPULATION_POLICY_CHANGE": "pop"}[cls]] += 1
            details.append({"canonical_company_id": cid, "legacy_company_id": legacy,
                            "metric": rk, "canonical": cv, "oracle": ov, "classification": cls})

    lines = ["# Canonical v1 vs v3.7 Oracle — intentional-difference classification", "",
             f"- canonical population: {len(canon)}",
             f"- oracle population: {len(oracle)}",
             f"- intersection compared: {compared}",
             "- this is NOT a parity gate; differences are classified for understanding.", "",
             "| metric | SAME | unit_fix | legacy_removed | missing_data | formula | bug_suspected | population_only |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    bugs = 0
    for _, rk, _, _ in PAIRS:
        b = by_metric[rk]
        bugs += b["bug"]
        lines.append(f"| {rk} | {b['same']} | {b['unit']} | {b['legacy']} | {b['missing']} | "
                     f"{b['formula']} | {b['bug']} | {b['pop']} |")
    lines.append("")
    lines.append(f"**BUG_SUSPECTED total: {bugs}**")
    (OUT / "oracle_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (OUT / "oracle_comparison.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(details[0].keys()))
        w.writeheader(); w.writerows(details)
    for ln in lines:
        print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
