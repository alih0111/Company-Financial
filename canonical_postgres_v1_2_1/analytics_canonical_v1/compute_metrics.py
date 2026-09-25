"""Canonical Analytics v1 — metric engine (score_version = canonical-v1-dev).

Reads ONLY canonical schemas (core, ingestion, fundamentals, market). No SQL
Server, no legacy CSV, no Product1/NPUnitRatio/OpK/OpAmt, no compat_v37.

Baseline factor weights are `baseline_weights_v37` = NOT VALIDATED FOR CANONICAL V1.

Usage:
  set CDF_PILOT_DB=company_financial_analytics_shadow_v121
  python compute_metrics.py [--as-of 2026-09-24] [--cutoff 2026-09-24T20:41:02+00:00] [--store]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import statistics
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

from data_quality import DQ  # noqa: E402
from report_chain_ttm import (resolve_ttm, PROV_DIRECT, PROV_CHAIN,  # noqa: E402
                              PROV_NO_ANNUAL, PROV_NO_COMPARABLE, PROV_PIT, PROV_INSUFFICIENT)

OUT = HERE / "output"
SCORE_VERSION = "canonical-v1-dev"

# Prototype baseline only — NOT VALIDATED FOR CANONICAL V1.
BASELINE_WEIGHTS_V37 = {
    "SalesGrowth": 10, "SalesGrowth3M": 6, "RevenueGrowth": 5,
    "OperatingProfitGrowth": 5, "NetProfitGrowth": 10,
    "OperatingMargin": 4, "NetMargin": 4, "ROERank": 6, "MarginTrend": 3,
    "InterestCoverage": 3, "CashConversion": 2, "EarningsQuality": 4,
    "PE": 11, "PS": 3, "PB": 2,
    "Liquidity": 3, "Leverage": 2, "CurrentRatio": 2, "Stability": 1,
    "LowVolatility": 2, "Momentum": 1,
}

MONETARY = {"revenue", "net_profit", "operating_profit", "finance_cost",
            "other_non_operating", "operating_cash_flow"}


def num(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def cap(v, lo, hi):
    if v is None:
        return None
    return lo if v < lo else hi if v > hi else v


def midrank(values: dict, higher_is_better=True, neutral=0.3, invalid_zero=None):
    present = {k: v for k, v in values.items() if v is not None}
    n = len(present)
    out = {k: neutral for k in values}
    if n == 1:
        for k in present:
            out[k] = 0.5
        return out
    if n == 0:
        return out
    ordered = sorted(present.values())
    for k, v in present.items():
        less = bisect_left(ordered, v)
        tie = bisect_right(ordered, v) - less
        pct = (2 * less + (tie - 1)) / (2 * (n - 1))
        out[k] = (1.0 - pct) if not higher_is_better else pct
    if invalid_zero is not None:
        for k in values:
            if values[k] is not None and invalid_zero(values[k]):
                out[k] = 0.0
    return out


def fiscal_ym(period_end_date):
    import jdatetime
    j = jdatetime.date.fromgregorian(date=period_end_date)
    return j.year, j.month


class Engine:
    def __init__(self, as_of: dt.date, cutoff: dt.datetime,
                 market_pit: str = "collected_at", market_as_of_date: dt.date | None = None):
        self.as_of = as_of
        self.cutoff = cutoff
        # market_pit: "collected_at" (canonical contract, default) or "trade_date"
        # (historical backtest proxy: a price for trade_date d is available at end of d).
        self.market_pit = market_pit
        self.market_as_of_date = market_as_of_date or as_of
        self.flags_by_company: dict[str, DQ] = {}

    def load(self):
        pg = pg_pilot_conn(autocommit=True)
        cur = pg.cursor()

        def rows(sql, p=()):
            cur.execute(sql, p)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

        self.companies = rows("SELECT id::text AS company_id, display_name, is_active FROM core.companies")
        self.securities = rows("""
            SELECT id::text AS security_id, company_id::text AS company_id, codal_symbol,
                   tsetmc_ins_code, is_primary, is_active,
                   (SELECT count(*) FROM market.price_observations p WHERE p.security_id = s.id) AS price_rows
            FROM core.securities s""")
        self.superseded = {r["supersedes_report_id"] for r in rows(
            "SELECT supersedes_report_id::text AS supersedes_report_id FROM ingestion.reports WHERE supersedes_report_id IS NOT NULL")}

        # eligible statements (PIT). Reports migrated from legacy synthetic chains
        # have no published_at; their visibility proxy is period_end_date <= as_of.
        # Reports with a known published_at must satisfy the cutoff.
        self.stmt = rows("""
            SELECT st.company_id::text AS company_id, st.statement_type, st.period_end_date,
                   st.fiscal_year, st.fiscal_month, st.is_restated,
                   rv.version_no, rv.collected_at, f.metric_code, f.period_order,
                   f.canonical_value, f.canonical_unit, r.id::text AS report_id
            FROM fundamentals.financial_facts f
            JOIN fundamentals.financial_statements st ON st.id = f.statement_id
            JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
            JOIN ingestion.reports r ON r.id = st.report_id
            WHERE (r.published_at IS NULL AND st.period_end_date <= %s)
               OR (r.published_at IS NOT NULL AND r.published_at <= %s)""",
            (self.as_of, self.cutoff))

        self.monthly = rows("""
            SELECT m.company_id::text AS company_id, m.period_end_date, m.sales_amount_rial,
                   m.quantity_unit
            FROM fundamentals.monthly_activities m
            JOIN ingestion.reports r ON r.id = m.report_id
            WHERE (r.published_at IS NULL AND m.period_end_date <= %s)
               OR (r.published_at IS NOT NULL AND r.published_at <= %s)""",
            (self.as_of, self.cutoff))

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
        pg.close()

    # ---------- population ----------
    def build_subjects(self):
        sec_by_company = {}
        for s in self.securities:
            if not s["is_active"]:
                continue
            prev = sec_by_company.get(s["company_id"])
            rank = (1 if s["is_primary"] else 0, int(s["price_rows"] or 0), s["security_id"])
            if prev is None or rank > prev[0]:
                sec_by_company[s["company_id"]] = (rank, s)
        # financial availability
        fin_companies = set()
        monthly_counts = {}
        for st in self.stmt:
            if st["report_id"] in self.superseded:
                continue
            if st["statement_type"] == "income_statement":
                fin_companies.add(st["company_id"])
        for m in self.monthly:
            monthly_counts[m["company_id"]] = monthly_counts.get(m["company_id"], 0) + 1

        subjects = {}
        for c in self.companies:
            cid = c["company_id"]
            if not c["is_active"]:
                continue
            has_fin = cid in fin_companies
            has_monthly = monthly_counts.get(cid, 0) >= 6
            if not (has_fin or has_monthly):
                continue
            sec = sec_by_company.get(cid)
            security = sec[1] if sec else None
            subjects[cid] = {
                "company_id": cid, "display_name": c["display_name"],
                "security_id": security["security_id"] if security else None,
                "symbol": security["codal_symbol"] if security else None,
                "has_financial": has_fin, "has_monthly": has_monthly,
                "monthly_count": monthly_counts.get(cid, 0),
            }
        return subjects

    # ---------- facts ----------
    def report_index(self):
        """company -> (fy,fm) -> metric -> order -> value, latest eligible version wins."""
        idx = {}
        for st in self.stmt:
            if st["report_id"] in self.superseded:
                continue
            cid = st["company_id"]
            fy, fm = st["fiscal_year"], st["fiscal_month"]
            if fy is None or fm is None:
                fy, fm = fiscal_ym(st["period_end_date"])
            key = (fy, fm)
            cell = idx.setdefault(cid, {}).setdefault(key, {"_period": st["period_end_date"], "_ver": st["version_no"]})
            # prefer later period_end_date, then higher version
            cur_rank = (st["period_end_date"], st["version_no"])
            if cur_rank < (cell["_period"], cell["_ver"]):
                continue
            cell["_period"], cell["_ver"] = cur_rank
            if st["canonical_unit"] not in (None, "rial", "rial_per_share"):
                self.flags_by_company.setdefault(cid, DQ()).add("unknown_unit")
                continue
            cell.setdefault(st["metric_code"], {})[st["period_order"]] = num(st["canonical_value"])
        return idx

    def ttm(self, report, metric, fy, fm):
        cell = report.get((fy, fm))
        if not cell:
            return None
        d = cell.get(metric)
        if not d:
            return None
        cur = d.get(1)
        if cur is None:
            return None
        if fm == 12:
            return cur
        fy_prev = d.get(3)
        ly = d.get(2)
        if fy_prev is None or ly is None:
            return None
        return cur + fy_prev - ly

    # ---------- metrics ----------
    def compute(self):
        self.load()
        subjects = self.build_subjects()
        report = self.report_index()
        self.subjects = subjects

        # monthly per company
        monthly = {}
        for m in self.monthly:
            monthly.setdefault(m["company_id"], {})[m["period_end_date"]] = num(m["sales_amount_rial"])
        # prices per security
        px = {}
        for p in self.prices:
            px.setdefault(p["security_id"], []).append(p)

        metrics = {}
        for cid, s in subjects.items():
            dq = self.flags_by_company.setdefault(cid, DQ())
            rep = report.get(cid, {})
            if not rep:
                dq.add("missing_current_financials")
            latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1]) if rep else None
            prev = (latest[0] - 1, latest[1]) if latest else None

            # sales
            ms = sorted(monthly.get(cid, {}).items(), reverse=True)  # (date, amt)
            vals = [v for _, v in ms if v is not None]
            sales_ttm = sum(vals[:12]) if len(vals) >= 6 else None
            sales_prev12 = sum(vals[12:24]) if len(vals) >= 24 else None
            sales_g12 = ((sales_ttm - sales_prev12) / abs(sales_prev12) * 100.0) \
                if (sales_ttm is not None and sales_prev12 not in (None, 0)) else None
            s3 = sum(vals[:3]) if len(vals) >= 6 else None
            p3 = sum(vals[3:6]) if len(vals) >= 6 else None
            sales_g3 = ((s3 - p3) / abs(p3) * 100.0) if (s3 is not None and p3 not in (None, 0)) else None
            stability = None
            if len(vals) >= 12:
                w = vals[:12]
                mean = sum(w) / len(w)
                if mean:
                    stability = 1.0 - (statistics.pstdev(w) / abs(mean))
            if not ms:
                dq.add("missing_monthly_activity")

            def g(metric, order=1):
                cell = rep.get(latest)
                return cell.get(metric, {}).get(order) if cell else None

            prov = {}

            def rtt(metric, fy, fm, tag):
                v, p = resolve_ttm(rep, metric, fy, fm)
                prov[tag] = p
                return v

            if latest:
                revenue_ttm = rtt("revenue", *latest, "revenue_ttm")
                net_ttm = rtt("net_profit", *latest, "net_profit_ttm")
                op_ttm = rtt("operating_profit", *latest, "operating_profit_ttm")
                eps_ttm = rtt("eps", *latest, "eps_ttm")
                ocf_ttm = rtt("operating_cash_flow", *latest, "operating_cash_flow_ttm")
            else:
                revenue_ttm = net_ttm = op_ttm = eps_ttm = ocf_ttm = None
            if prev:
                revenue_prev = rtt("revenue", *prev, "revenue_prev")
                net_prev = rtt("net_profit", *prev, "net_profit_prev")
                op_prev = rtt("operating_profit", *prev, "operating_profit_prev")
            else:
                revenue_prev = net_prev = op_prev = None
            if latest and (net_ttm is None or revenue_ttm is None):
                dq.add("missing_comparable_period")
            for tag, code in (("operating_profit_ttm", PROV_NO_ANNUAL),
                              ("operating_profit_ttm", PROV_NO_COMPARABLE),
                              ("net_profit_ttm", PROV_NO_ANNUAL),
                              ("net_profit_ttm", PROV_NO_COMPARABLE)):
                if prov.get(tag) == code:
                    dq.add("missing_comparable_period")
            op_ly = g("operating_profit", 2)
            revenue_ly = g("revenue", 2)

            equity = g("total_equity")
            cur_assets = g("current_assets")
            cur_liab = g("current_liabilities")
            liab = g("total_liabilities")
            assets = g("total_assets")
            finance = g("finance_cost")
            other_nonop = g("other_non_operating")

            net_margin = (net_ttm / abs(revenue_ttm) * 100.0) if (net_ttm is not None and revenue_ttm) else None
            op_margin = (op_ttm / abs(revenue_ttm) * 100.0) if (op_ttm is not None and revenue_ttm) else None
            op_margin_ly = (op_ly / abs(revenue_ly) * 100.0) if (op_ly is not None and revenue_ly) else None
            trend = (op_margin - op_margin_ly) if (op_margin is not None and op_margin_ly is not None) else None
            roe = (net_ttm / equity * 100.0) if (net_ttm is not None and equity and equity > 0) else None
            cur_ratio = (cur_assets / cur_liab) if (cur_assets is not None and cur_liab and cur_liab > 0) else None
            debt_ratio = (liab / assets) if (liab is not None and assets and assets > 0) else None
            rev_g = ((g("revenue", 1) - revenue_ly) / abs(revenue_ly) * 100.0) \
                if (g("revenue", 1) is not None and revenue_ly) else None
            op_g = ((op_ttm - op_prev) / abs(op_prev) * 100.0) if (op_ttm is not None and op_prev) else None
            np_g = ((net_ttm - net_prev) / abs(net_prev) * 100.0) if (net_ttm is not None and net_prev) else None
            interest = (op_ttm / abs(finance)) if (op_ttm is not None and finance) else None
            earnings_q = (abs(other_nonop) / abs(op_ttm) * 100.0) if (other_nonop is not None and op_ttm) else None
            cash_conv = (ocf_ttm / net_ttm) if (ocf_ttm is not None and net_ttm and net_ttm > 0) else None

            # market
            srows = px.get(s["security_id"], []) if s["security_id"] else []
            latest_price = num((srows[0]["last_price_rial"] if srows[0]["last_price_rial"] is not None
                                else srows[0]["closing_price_rial"])) if srows else None
            latest_close = num(srows[0]["closing_price_rial"]) if srows else None
            mom = None
            if len(srows) >= 30 and latest_close is not None:
                c30 = num(srows[29]["closing_price_rial"])
                if c30:
                    mom = (latest_close - c30) / abs(c30) * 100.0
            vol = None
            rets = []
            if len(srows) >= 2:
                closes = [num(x["closing_price_rial"]) for x in srows]
                for i in range(1, min(30, len(closes))):
                    if closes[i] is not None and closes[i - 1]:
                        rets.append((closes[i] - closes[i - 1]) * 100.0 / closes[i - 1])
                if len(rets) > 1:
                    vol = statistics.stdev(rets)
            tvs = [num(x["trade_value_rial"]) for x in srows[:30] if x["trade_value_rial"] is not None]
            liq = sum(tvs) / len(tvs) if tvs else None
            if not srows:
                dq.add("missing_price")
            pe = None
            if latest_price and eps_ttm and eps_ttm != 0:
                pe = latest_price / eps_ttm
            ps = (pe * net_margin / 100.0) if (pe is not None and net_margin is not None and net_margin > 0) else None
            pb = (pe * roe / 100.0) if (pe is not None and roe is not None and roe > 0) else None

            metrics[cid] = {
                "symbol": s["symbol"], "security_id": s["security_id"],
                "sales_ttm": sales_ttm, "sales_growth_12m": sales_g12, "sales_growth_3m": sales_g3,
                "sales_stability": stability,
                "revenue_ttm": revenue_ttm, "revenue_growth": rev_g,
                "net_profit_ttm": net_ttm, "operating_profit_ttm": op_ttm, "eps_ttm": eps_ttm,
                "net_profit_growth": np_g, "operating_profit_growth": op_g,
                "net_margin": net_margin, "operating_margin": op_margin, "margin_trend": trend,
                "roe": roe, "current_ratio": cur_ratio, "debt_ratio": debt_ratio,
                "interest_coverage": interest, "earnings_quality": earnings_q, "cash_conversion": cash_conv,
                "price_momentum_30d": mom, "volatility_30d": vol, "avg_trade_value_30d": liq,
                "latest_price": latest_price, "pe": pe, "ps": ps, "pb": pb,
                "ocf_ttm": ocf_ttm,
                "has_financial": s["has_financial"], "has_monthly": s["has_monthly"],
                "has_price": bool(srows), "_dq": dq, "_ttm_prov": prov,
            }
        self.metrics = metrics
        self.rank_and_score()
        return metrics

    def rank_and_score(self):
        m = self.metrics

        def rank(field, getter, neutral=0.3, higher=True, invalid_zero=None):
            vals = {c: getter(v) for c, v in m.items()}
            out = midrank(vals, higher_is_better=higher, neutral=neutral, invalid_zero=invalid_zero)
            for c in m:
                m[c][field] = out[c]

        rank("SalesGrowthRank", lambda v: cap(v["sales_growth_12m"], -150, 150))
        rank("SalesGrowth3MRank", lambda v: cap(v["sales_growth_3m"], -150, 150))
        rank("RevenueGrowthRank", lambda v: cap(v["revenue_growth"], -200, 200))
        rank("OperatingProfitGrowthRank", lambda v: cap(v["operating_profit_growth"], -250, 250))
        rank("NetProfitGrowthRank", lambda v: cap(v["net_profit_growth"], -300, 300))
        rank("OperatingMarginRank", lambda v: cap(v["operating_margin"], -80, 80))
        rank("NetMarginRank", lambda v: cap(v["net_margin"], -60, 60))
        rank("MarginTrendRank", lambda v: cap(v["margin_trend"], -25, 25))
        rank("InterestCoverageRank", lambda v: (None if v["interest_coverage"] is None else
             (-999999.0 if v["interest_coverage"] <= 0 else min(v["interest_coverage"], 20.0))), neutral=0.5)
        rank("EarningsQualityRank", lambda v: (None if v["earnings_quality"] is None else
             min(abs(v["earnings_quality"]), 150.0)), neutral=0.5, higher=False)
        rank("PERank", lambda v: (v["pe"] if (v["pe"] is not None and 0 < v["pe"] <= 60) else 999999.0),
             neutral=0.0, higher=False, invalid_zero=lambda x: x >= 999999.0)
        rank("PSRank", lambda v: (v["ps"] if (v["ps"] is not None and 0 < v["ps"] <= 100) else 999999.0),
             neutral=0.0, higher=False, invalid_zero=lambda x: x >= 999999.0)
        rank("PBRank", lambda v: (v["pb"] if (v["pb"] is not None and 0 < v["pb"] <= 30) else 999999.0),
             neutral=0.0, higher=False, invalid_zero=lambda x: x >= 999999.0)
        rank("LiquidityRank", lambda v: v["avg_trade_value_30d"], neutral=0.0)
        rank("StabilityRank", lambda v: v["sales_stability"], neutral=0.3)
        rank("LowVolatilityRank", lambda v: v["volatility_30d"], neutral=0.3, higher=False)
        rank("MomentumRank", lambda v: cap(v["price_momentum_30d"], -50, 40))
        rank("ROERank", lambda v: cap(v["roe"], -150, 150))
        rank("LeverageRank", lambda v: (None if v["debt_ratio"] is None else min(v["debt_ratio"], 50.0)),
             neutral=0.3, higher=False)
        rank("CurrentRatioRank", lambda v: (None if v["current_ratio"] is None else min(v["current_ratio"], 15.0)))
        rank("CashConversionRank", lambda v: cap(v["cash_conversion"], -2, 5))

        for c, v in m.items():
            growth = (10 * v["SalesGrowthRank"] + 6 * v["SalesGrowth3MRank"] + 5 * v["RevenueGrowthRank"]
                      + 5 * v["OperatingProfitGrowthRank"] + 10 * v["NetProfitGrowthRank"])
            gp = (6.0 if (v["sales_growth_12m"] is not None and v["sales_growth_12m"] < -20) else 0.0) \
                + (5.0 if (v["operating_profit_growth"] is not None and v["operating_profit_growth"] < -25) else 0.0)
            growth = max(growth - gp, 0.0)
            prof = (4 * v["OperatingMarginRank"] + 4 * v["NetMarginRank"] + 6 * v["ROERank"]
                    + 3 * v["MarginTrendRank"] + 3 * v["InterestCoverageRank"]
                    + 2 * v["CashConversionRank"] + 4 * v["EarningsQualityRank"])
            pp = (10.0 if (v["net_profit_ttm"] is not None and v["net_profit_ttm"] < 0) else 0.0) \
                + (4.0 if (v["interest_coverage"] is not None and v["interest_coverage"] < 1.5) else 0.0) \
                + (3.0 if (v["margin_trend"] is not None and v["margin_trend"] < -2) else 0.0)
            nop = v["earnings_quality"]
            if nop is not None:
                pp += 0.0 if nop <= 20 else (8.0 if nop >= 100 else (nop - 20.0) / 80.0 * 8.0)
            prof = max(prof - pp, 0.0)
            val = (11 * v["PERank"] + 3 * v["PSRank"] + 2 * v["PBRank"])
            vp = 8.0 if (v["pe"] is None or v["pe"] <= 0 or v["pe"] > 60) else 0.0
            val = max(val - vp, 0.0)
            mkt = (3 * v["LiquidityRank"] + 2 * v["LeverageRank"] + 2 * v["CurrentRatioRank"]
                   + 1 * v["StabilityRank"] + 2 * v["LowVolatilityRank"] + 1 * v["MomentumRank"])
            fresh_fin = v["has_financial"]
            dq = v["_dq"].score(v["has_financial"], v["has_monthly"], v["has_price"], fresh_fin, v["has_price"])
            v["growth_score"] = round(growth, 1)
            v["profitability_score"] = round(prof, 1)
            v["valuation_score"] = round(val, 1)
            v["market_score"] = round(mkt, 1)
            v["data_quality_score"] = dq
            v["quant_score"] = round(dq * (growth + prof + val + mkt), 2)

    def digest(self):
        payload = {c: {k: v for k, v in sorted(self.metrics[c].items()) if not k.startswith("_")}
                   for c in sorted(self.metrics)}
        return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-09-24")
    ap.add_argument("--cutoff", default="2026-09-24T20:41:02+00:00")
    ap.add_argument("--store", action="store_true")
    args = ap.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    OUT.mkdir(parents=True, exist_ok=True)
    eng = Engine(as_of, cutoff)
    metrics = eng.compute()
    digest = eng.digest()

    (OUT / "canonical_v1_metrics.json").write_text(
        json.dumps({c: {**{k: v for k, v in m.items() if not k.startswith("_")},
                         "_ttm_prov": m.get("_ttm_prov", {})}
                    for c, m in metrics.items()}, indent=1, default=str), encoding="utf-8")
    (OUT / "canonical_v1_hash.txt").write_text(digest + "\n", encoding="utf-8")
    print("population:", len(metrics), "hash:", digest)
    missing = {k: sum(1 for v in metrics.values() if v[k] is None)
               for k in ("net_profit_ttm", "revenue_ttm", "eps_ttm", "pe", "roe", "sales_ttm")}
    print("missing:", missing)
    if args.store:
        store_run(eng, metrics, as_of, cutoff, digest)
    return 0


def store_run(eng, metrics, as_of, cutoff, digest):
    pg = pg_pilot_conn()
    try:
        with pg.cursor() as cur:
            cur.execute("""INSERT INTO analytics.score_runs
                (score_version, as_of_date, source_cutoff_at, status, completed_at, code_version, parameters)
                VALUES (%s,%s,%s,'completed',now(),%s,%s) RETURNING id""",
                (SCORE_VERSION, as_of, cutoff, "canonical-v1-dev+report-chain-ttm",
                 json.dumps({"baseline_weights_v37": BASELINE_WEIGHTS_V37,
                             "weights_validated": False, "input_hash": digest,
                             "implementation_revision": "report-chain-ttm-v1"})))
            run_id = cur.fetchone()[0]
            for cid, v in metrics.items():
                cur.execute("""INSERT INTO analytics.company_scores
                    (run_id, company_id, primary_security_id, quant_score, data_quality_score,
                     growth_score, profitability_score, valuation_score, market_score, input_hash, details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id, company_id) DO NOTHING""",
                    (run_id, cid, v["security_id"], v["quant_score"], v["data_quality_score"],
                     v["growth_score"], v["profitability_score"], v["valuation_score"], v["market_score"],
                     digest, json.dumps(v["_dq"].as_dict(), ensure_ascii=False)))
                for fc, w in BASELINE_WEIGHTS_V37.items():
                    field = f"{fc}Rank" if not fc.endswith("Rank") else fc
                    pct = v.get(field)
                    if pct is None:
                        continue
                    cur.execute("""INSERT INTO analytics.factor_scores
                        (run_id, company_id, factor_code, percentile, weighted_score, weight, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_id, company_id, factor_code) DO NOTHING""",
                        (run_id, cid, fc, pct, pct * w, w, json.dumps({"weights_validated": False})))
            pg.commit()
            print("stored score_run", run_id, "companies", len(metrics))
    finally:
        pg.close()


if __name__ == "__main__":
    raise SystemExit(main())
