"""UI SCORE HISTORICAL PIT REBUILD v2 (task 6/7) — research-only.

Runs the EXACT frozen production Engine (compute_metrics.py, canonical-v1-dev, VAL_DIRECT,
production weights/DQ/penalties/caps/ranks — untouched) for each frozen historical signal
date, with ONE change only: historical information eligibility.

  V1 (existing panel): legacy rows visible iff period_end <= as_of  (proxy — leaks)
  V2 (this rebuild):   every input report visible iff its PROVEN visible_from <= cutoff,
                       where visible_from = real DB published_at (codal rows) or the
                       LATEST recovered Codal publication of that (company, period)
                       (conservative latest-version rule; unprovable rows are INVISIBLE
                       and the EXISTING DQ missing-data behavior applies).

Market data: trade_date <= as_of (frozen historical proxy, unchanged).
Shares: core.share_intervals with knowledge_from <= cutoff (unchanged, provable).

NO returns, NO ICs in this artifact. NO formula change. cutoff convention = the original
validated one: 23:59:59 UTC on the signal date (ui_score_historical_v1.py EOD).
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import os
os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
sys.path.insert(0, r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\analytics_canonical_v1")
sys.path.insert(0, r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\migration_tools")

import psycopg  # noqa: E402
import pandas as pd  # noqa: E402
from common import pg_pilot_conn  # noqa: E402
from compute_metrics import Engine, VAL_DIRECT  # noqa: E402

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "ui_score_research"
OUT = HERE / "ui_score_historical_pit_v2"
OUT.mkdir(exist_ok=True)
SIG = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals.csv")
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
VERSION = "ui_score_historical_pit_v2"
EOD = lambda y, m, d: dt.datetime(y, m, d, 23, 59, 59, tzinfo=dt.timezone.utc)
WEIGHTS = {
    "growth": {"SalesGrowthRank": 10, "SalesGrowth3MRank": 6, "RevenueGrowthRank": 5,
               "OperatingProfitGrowthRank": 5, "NetProfitGrowthRank": 10},
    "profitability": {"OperatingMarginRank": 4, "NetMarginRank": 4, "ROERank": 6,
                      "MarginTrendRank": 3, "InterestCoverageRank": 3,
                      "CashConversionRank": 2, "EarningsQualityRank": 4},
    "valuation": {"PERank": 11, "PSRank": 3, "PBRank": 2},
    "market": {"LiquidityRank": 3, "LeverageRank": 2, "CurrentRatioRank": 2,
               "StabilityRank": 1, "LowVolatilityRank": 2, "MomentumRank": 1},
}
RAW_FIELDS = ["sales_growth_12m", "sales_growth_3m", "revenue_growth", "operating_profit_growth",
              "net_profit_growth", "eps_growth", "operating_margin", "net_margin", "roe",
              "margin_trend", "interest_coverage", "cash_conversion", "earnings_quality",
              "pe", "ps", "pb", "avg_trade_value_30d", "debt_ratio", "current_ratio",
              "sales_stability", "volatility_30d", "price_momentum_30d", "latest_price",
              "market_cap", "shares_outstanding", "net_profit_ttm", "revenue_ttm"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_intervals():
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT s.codal_symbol, s.id::text, si.valid_from, si.valid_to,
                              si.shares_outstanding, si.knowledge_from, si.status
                       FROM core.share_intervals si JOIN core.securities s ON s.id=si.security_id""")
        iv = {}
        for sym, sid, vf, vt, sh, kf, st in cur.fetchall():
            iv.setdefault(sym, []).append({"security_id": sid, "valid_from": vf, "valid_to": vt,
                                           "shares": float(sh) if sh is not None else None,
                                           "knowledge_from": kf, "status": st})
        return iv


def eligible_shares(ivs, d, cutoff):
    for i in ivs or []:
        if i["status"] != "KNOWN" or i["shares"] is None:
            continue
        if i["valid_from"] and d < i["valid_from"]:
            continue
        if i["valid_to"] and d >= i["valid_to"]:
            continue
        if i["knowledge_from"] is None or i["knowledge_from"] > cutoff:
            continue
        return i
    return None


class PITEngine(Engine):
    """Engine with the ONLY change: report visibility from the proven visibility map.

    Everything except the two visibility predicates in load() is byte-identical to the
    production Engine.load().
    """

    visibility = None  # {report_id(str): visible_from datetime(UTC)} — set before load()

    def load(self):
        pg = pg_pilot_conn(autocommit=True)
        cur = pg.cursor()

        def rows(sql, p=()):
            cur.execute(sql, p)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

        cur.execute("CREATE TEMP TABLE _vis(report_id text PRIMARY KEY, visible_from timestamptz)")
        cur.executemany("INSERT INTO _vis VALUES (%s, %s)",
                        [(k, v) for k, v in self.visibility.items()])

        self.companies = rows("SELECT id::text AS company_id, display_name, is_active FROM core.companies")
        self.securities = rows("""
            SELECT id::text AS security_id, company_id::text AS company_id, codal_symbol,
                   tsetmc_ins_code, is_primary, is_active,
                   (SELECT count(*) FROM market.price_observations p WHERE p.security_id = s.id) AS price_rows
            FROM core.securities s""")
        self.superseded = {r["supersedes_report_id"] for r in rows(
            "SELECT supersedes_report_id::text AS supersedes_report_id FROM ingestion.reports WHERE supersedes_report_id IS NOT NULL")}

        # PIT-correct visibility: a report is visible iff its proven visible_from <= cutoff.
        # (V1 used period_end <= as_of for legacy rows — the audited leak. Nothing else changed.)
        self.stmt = rows("""
            SELECT st.company_id::text AS company_id, st.statement_type, st.period_end_date,
                   st.fiscal_year, st.fiscal_month, st.is_restated,
                   rv.version_no, rv.collected_at, f.metric_code, f.period_order,
                   f.canonical_value, f.canonical_unit, r.id::text AS report_id
            FROM fundamentals.financial_facts f
            JOIN fundamentals.financial_statements st ON st.id = f.statement_id
            JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
            JOIN ingestion.reports r ON r.id = st.report_id
            JOIN _vis v ON v.report_id = r.id::text
            WHERE v.visible_from <= %s""",
            (self.cutoff,))

        self.monthly = rows("""
            SELECT m.company_id::text AS company_id, m.period_end_date, m.sales_amount_rial,
                   m.quantity_unit
            FROM fundamentals.monthly_activities m
            JOIN ingestion.reports r ON r.id = m.report_id
            JOIN _vis v ON v.report_id = r.id::text
            WHERE v.visible_from <= %s""",
            (self.cutoff,))

        if self.market_pit == "trade_date":
            self.prices = rows("""
                SELECT security_id::text AS security_id, trade_date, collected_at,
                       closing_price_rial, last_price_rial, high_price_rial, low_price_rial,
                       trade_value_rial
                FROM market.price_observations
                WHERE trade_date <= %s
                ORDER BY security_id, trade_date DESC, collected_at DESC""", (self.market_as_of_date,))
        else:
            self.prices = rows("""
                SELECT security_id::text AS security_id, trade_date, collected_at,
                       closing_price_rial, last_price_rial, high_price_rial, low_price_rial,
                       trade_value_rial
                FROM market.price_observations
                WHERE collected_at <= %s
                ORDER BY security_id, trade_date DESC, collected_at DESC""", (self.cutoff,))

        self.share_structure = rows("""
            SELECT id, security_id::text AS security_id, company_id::text AS company_id,
                   shares_count, market_value_rial, eps_rial, as_of_date, source, collected_at
            FROM core.share_structure
            WHERE as_of_date <= %s""", (self.as_of,))

        self.tsetmc_current = []
        if self.market_pit != "trade_date":
            try:
                self.tsetmc_current = rows("""
                    SELECT id, security_id::text AS security_id, shares_count, collected_at, source
                    FROM market.tsetmc_current_shares
                    WHERE collected_at <= %s
                    ORDER BY security_id, collected_at DESC""", (self.cutoff,))
            except Exception:
                self.tsetmc_current = []

        self.codal_titles = rows("""
            SELECT r.company_id::text AS company_id, r.title, r.period_end_date
            FROM ingestion.reports r
            WHERE r.source = 'codal' AND r.report_type = 'financial_statement'
              AND r.title IS NOT NULL AND r.period_end_date IS NOT NULL
              AND r.published_at IS NOT NULL AND r.published_at <= %s
            ORDER BY r.period_end_date""", (self.cutoff,))
        pg.close()


def main() -> int:
    # visibility map from the audited lineage artifact (provable rows only)
    visdf = pd.read_parquet(HERE / "input_report_visibility_v2.parquet")
    visdf = visdf[visdf.provable == True]
    visibility = {r.report_id: r.visible_from.to_pydatetime() for r in visdf.itertuples()}
    print(f"visibility rows (provable): {len(visibility)}")

    grid = {}
    with open(SIG, encoding="utf-8-sig", newline="") as fh:
        import csv
        for r in csv.DictReader(fh):
            grid.setdefault(r["signal_date"], []).append(r["symbol"])
    dates = sorted(grid)
    print(f"signal dates: {len(dates)} ({dates[0]}..{dates[-1]})")

    iv = load_intervals()
    sec = {}
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
        for s, i, ins in cur.fetchall():
            sec[s] = (i, ins)
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]

    # adjusted series (canonical adjusted-return pipeline, same as frozen validation runs)
    events = {}
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT security_id::text, action_date, adjustment_factor
                       FROM market.corporate_actions
                       WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
        for sid, d, f in cur.fetchall():
            events.setdefault(sid, []).append(
                (d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(f)))
    adj_series = {}
    for sym, (sid, ins) in sec.items():
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        dates_s, raw = [], {}
        for r in recs:
            s = str(r["dEven"])
            d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
            dates_s.append(d)
            raw[d] = float(r["pClosing"])
        evs = sorted(events.get(sid, []), key=lambda e: e[0])
        c, run, ei = {}, 1.0, len(evs) - 1
        for d in reversed(dates_s):
            dd = dt.date.fromisoformat(d)
            while ei >= 0 and evs[ei][0] > dd:
                run *= evs[ei][1]
                ei -= 1
            c[d] = run
        adj_series[sym] = {"dates": dates_s, "adj": {d: raw[d] * c[d] for d in dates_s}}

    PITEngine.visibility = visibility
    n_rows = 0
    out = open(OUT / "ui_score_historical_pit_v2.jsonl", "w", encoding="utf-8")
    for k, d in enumerate(dates):
        dd = dt.date.fromisoformat(d)
        cut = EOD(dd.year, dd.month, dd.day)
        eng = PITEngine(dd, cut, market_pit="trade_date", market_as_of_date=dd, valuation=VAL_DIRECT)
        eng.load()
        injected = []
        for sym in grid[d]:
            e = eligible_shares(iv.get(sym), dd, cut)
            if e:
                injected.append({"id": len(injected), "security_id": e["security_id"],
                                 "shares_count": e["shares"], "as_of_date": e["valid_from"],
                                 "collected_at": e["knowledge_from"],
                                 "source": "tsetmc_share_intervals"})
        eng.share_structure = injected
        eng.load = lambda: None
        m = eng.compute()
        bysym = {v.get("symbol"): v for v in m.values()}
        for sym in grid[d]:
            v = bysym.get(sym)
            if v is None:
                continue
            ranks = {f: v.get(f) for cat in WEIGHTS.values() for f in cat}
            contributions = {f: (wf[f] * v.get(f))
                             for cat, wf in WEIGHTS.items() for f in wf if v.get(f) is not None}
            row = {
                "calculation_version": VERSION, "as_of": d,
                "knowledge_cutoff": cut.isoformat(),
                "symbol": sym, "security_id": v.get("security_id"),
                "score_version": "canonical-v1-dev",
                "raw_metrics": {f: v.get(f) for f in RAW_FIELDS},
                "ranks": ranks, "weighted_contributions": contributions,
                "growth_score": v["growth_score"], "profitability_score": v["profitability_score"],
                "valuation_score": v["valuation_score"], "market_score": v["market_score"],
                "data_quality_score": v["data_quality_score"],
                "ui_score": v["quant_score"],
                "dq_flags": v["_dq"].flags,
                "missing_components": [f for f in ranks if v.get(f) is None],
                "n_factors_missing": sum(1 for f in ranks.values() if f is None),
            }
            out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            n_rows += 1
        out.flush()
        print(f"[{k+1}/{len(dates)}] {d}: universe={len(m)} rows_written={n_rows}", flush=True)
    out.close()
    print(f"DONE rows={n_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
