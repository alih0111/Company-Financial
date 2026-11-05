"""Canonical Score v4 — pipeline and CLI.

score_version = "v4". Companion config: score_v4_config.py (single source of
every weight/threshold). Audit of the v3 baseline it replaces:
analytics_canonical_v1/SCORE_V4_AUDIT.md.

Pipeline (per run, one as_of/source_cutoff):

  Engine.compute()            v3 metric engine, unchanged — raw metrics
  build_v4_inputs()           history bundle: TTM series, quarterly YoY, price
                              relatives, sector mapping, freshness ages
  assemble_raw()              family-aware raw factor inputs
  validate_raw()              economic validity -> status valid/missing/invalid
  winsor_bounds/apply_winsor  P1/P99 per raw metric, universe-wide
  compute_market_percentiles  market midrank per factor
  compute_sector_percentiles  sector midrank per factor (small-sample fallback)
  score_company()             weight x combined percentile per factor; missing
                              -> 0.5 neutral, invalid -> 0.0; category sums;
                              penalties; confidence (independent); adjusted
  store_run_v4()              NEW append-only score_runs row (score_version
                              'v4') + company_scores (v4 and legacy columns)
                              + factor_scores + metric_snapshots

Usage:
  set CDF_PILOT_DB=company_financial_analytics_shadow_v121
  python score_v4.py --as-of 2026-10-05 --cutoff 2026-10-05T20:00:00+00:00 [--store]
"""

from __future__ import annotations

import argparse
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

import compute_metrics as CM  # noqa: E402
from compute_metrics import Engine, num  # noqa: E402
from report_chain_ttm import resolve_ttm  # noqa: E402
import score_v4_config as CFG  # noqa: E402

TRADING_DAYS_3M = 63
TRADING_DAYS_6M = 126


# ---------------------------------------------------------------------------
# PIT sector mapping
# ---------------------------------------------------------------------------
def load_sector_map(as_of: dt.date) -> dict[str, str]:
    """company_id -> TSETMC industry category valid at as_of."""
    pg = pg_pilot_conn(autocommit=True)
    try:
        with pg.cursor() as cur:
            cur.execute("""
                SELECT company_id::text, category
                FROM core.company_classification
                WHERE valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)
                ORDER BY valid_from""", (as_of, as_of))
            return {cid: cat for cid, cat in cur.fetchall()}
    finally:
        pg.close()


def _months_between(d1: dt.date, d2: dt.date) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def _cells_sorted_desc(report: dict) -> list:
    return sorted(report.keys(), key=lambda k: k[0] * 12 + k[1], reverse=True)


# ---------------------------------------------------------------------------
# History bundle
# ---------------------------------------------------------------------------
def build_v4_inputs(eng: Engine, sector_map: dict[str, str]) -> dict:
    """company_id -> derived v4 inputs beyond the v3 single snapshot.

    Everything is PIT: the Engine already filtered statements/monthlies by
    (as_of, cutoff); prices follow the engine's market_pit mode; sector rows
    are valid at as_of.
    """
    report_all = getattr(eng, "report_index_by_company", {})
    durations_all = getattr(eng, "durations_by_company", {})
    fiscal_cal = getattr(eng, "fiscal_cal", {})
    monthly_by_company: dict[str, list] = {}
    for m in eng.monthly:
        monthly_by_company.setdefault(m["company_id"], []).append(m)

    company_security = {cid: v.get("security_id") for cid, v in eng.metrics.items()}

    px_by_security: dict[str, list] = {}
    for p in eng.prices:
        px_by_security.setdefault(p["security_id"], []).append(p)
    stock_returns: dict[str, dict] = {}
    m3_all: list[float] = []
    m6_all: list[float] = []
    for sec_id, rows in px_by_security.items():
        r3 = _price_return(rows, TRADING_DAYS_3M)
        r6 = _price_return(rows, TRADING_DAYS_6M)
        stock_returns[sec_id] = {"r3": r3, "r6": r6}
        if r3 is not None:
            m3_all.append(r3)
        if r6 is not None:
            m6_all.append(r6)
    market_r3 = statistics.median(m3_all) if len(m3_all) >= 5 else None
    market_r6 = statistics.median(m6_all) if len(m6_all) >= 5 else None

    sector_members: dict[str, list[str]] = {}
    for cid, cat in sector_map.items():
        if cid in eng.metrics:
            sector_members.setdefault(cat, []).append(cid)

    out: dict = {}
    for cid, v in eng.metrics.items():
        rep = report_all.get(cid, {})
        durations_c = durations_all.get(cid, {})
        ann_month, _state, _src = CM.annual_month_of(fiscal_cal, cid)
        sec_id = v.get("security_id")
        category = sector_map.get(cid)
        bundle: dict = {
            "sector": category,
            "score_model": CFG.family_for_category(category),
            "profit_report_age_months": None,
            "market_data_age_days": None,
        }

        # ---- per-cell report-chain walk (latest 16 cells, desc) ----
        bs_rows: list[dict] = []
        for cell in _cells_sorted_desc(rep)[:16]:
            cell_d = durations_c.get(cell)
            is_annual = True if cell_d == 12 else None
            anchor = CM.prev_annual_cell(durations_c, *cell)
            row: dict = {"cell": cell, "period_end": rep[cell].get("_period")}
            for metric in ("revenue", "net_profit"):
                val, _prov = resolve_ttm(rep, metric, *cell, annual_month=ann_month,
                                         is_annual=is_annual, prev_annual_cell=anchor)
                row[metric] = val
            eq = num((rep[cell].get("total_equity") or {}).get(1))
            liab = num((rep[cell].get("total_liabilities") or {}).get(1))
            assets = num((rep[cell].get("total_assets") or {}).get(1))
            row["equity"] = eq
            row["debt_ratio"] = (liab / assets) if (liab is not None and assets) else None
            bs_rows.append(row)

        # profit freshness: age of the latest eligible report period
        if rep:
            latest_period = bs_rows[0]["period_end"]
            if latest_period is not None:
                bundle["profit_report_age_months"] = max(0, _months_between(latest_period, eng.as_of))
        # market freshness
        srows = px_by_security.get(sec_id, []) if sec_id else []
        if srows:
            bundle["market_data_age_days"] = max(0, (eng.as_of - max(r["trade_date"] for r in srows)).days)

        # ---- multi-year revenue CAGR from annual anchors ----
        annual_rows = [r for r in bs_rows
                       if durations_c.get(r["cell"]) == 12 or r["cell"][1] == 12]
        by_fy: dict[int, dict] = {}
        for r in annual_rows:
            if r["revenue"] is not None:
                by_fy.setdefault(r["cell"][0], r)
        ann_seq = [by_fy[y] for y in sorted(by_fy, reverse=True)]
        cagr = None
        if len(ann_seq) >= 4 and ann_seq[-1]["revenue"] and ann_seq[0]["revenue"]:
            v_now, v_old = ann_seq[0]["revenue"], ann_seq[3]["revenue"]
            if v_old > 0 and v_now > 0:
                cagr = ((v_now / v_old) ** (1.0 / 3.0) - 1.0) * 100.0
        bundle["revenue_cagr_3y"] = cagr

        # ---- ROE volatility across annual anchors ----
        roe_annual = [r["net_profit"] / r["equity"] * 100.0
                      for r in annual_rows
                      if r["equity"] and r["equity"] > 0 and r["net_profit"] is not None]
        bundle["roe_volatility"] = statistics.pstdev(roe_annual) if len(roe_annual) >= 3 else None

        # ---- normalized earnings for valuation (anti-windfall) ----
        # A single windfall quarter (FX revaluation, asset sale — e.g. a
        # +353T rial Q4 after a +9T rial 9M) makes the headline P/E look
        # artificially cheap. The P/E factor is therefore built on the median
        # of the last CFG.NORMALIZED_YEARS annual net profits when at least
        # two annual anchors exist; a median <= 0 (historically loss-making)
        # yields None = deliberate missing (never the spike-inflated ratio).
        # With fewer than two annual anchors the current TTM P/E is kept.
        annual_np = [r["net_profit"] for r in annual_rows if r["net_profit"] is not None][:CFG.NORMALIZED_YEARS]
        bundle["annual_net_profits"] = annual_np
        mc = v.get("market_cap")
        if len(annual_np) >= 2:
            median_np = statistics.median(annual_np)
            bundle["normalized_net_profit"] = median_np
            bundle["pe_normalized"] = (mc / median_np) if (mc and median_np and median_np > 0) else None
        else:
            bundle["normalized_net_profit"] = None
            bundle["pe_normalized"] = v.get("pe")

        # ---- debt trend + penalty inputs ----
        debt_annual = [r["debt_ratio"] for r in annual_rows if r["debt_ratio"] is not None]
        bundle["debt_ratio_change"] = (debt_annual[0] - debt_annual[1]
                                       if len(debt_annual) >= 2 else None)
        bundle["equity_latest"] = (bs_rows[0]["equity"] if bs_rows else None)
        bundle["debt_ratio_latest"] = (bs_rows[0]["debt_ratio"] if bs_rows
                                       else v.get("debt_ratio"))

        # ---- quarterly YoY from monthly sales ----
        q_yoy = _quarterly_yoy(monthly_by_company.get(cid, []))
        bundle["revenue_yoy_acceleration"] = (q_yoy[-1] - q_yoy[-2]) if len(q_yoy) >= 2 else None
        last8 = q_yoy[-8:]
        bundle["quarter_yoy_positive_fraction"] = (sum(1 for g in last8 if g >= 0) / len(last8)
                                                   if len(last8) >= 4 else None)

        # ---- multi-quarter net-profit deterioration (YoY signs, oldest->newest) ----
        bundle["net_ttm_yoy_signs"] = _net_ttm_yoy_signs(bs_rows)

        # ---- single-quarter profit concentration (windfall evidence) ----
        # Raw cumulative figures of the latest fiscal year: when one quarter
        # carries most of the annual profit (e.g. a Q4 FX revaluation worth 97%
        # of the year), the TTM is windfall-dominated even without any cash
        # statement. Uses the reported order-1 cum values, not TTM.
        bundle["quarter_profit_concentration"] = _quarter_concentration(rep, durations_c)

        # ---- price relatives ----
        sr = stock_returns.get(sec_id, {}) if sec_id else {}
        bundle["return_6m_rel_market"] = _diff(sr.get("r6"), market_r6)
        bundle["return_3m_rel_market"] = _diff(sr.get("r3"), market_r3)
        sector_r6 = None
        members = sector_members.get(category, []) if category else []
        if len(members) > 1:
            sec_vals = []
            for m_cid in members:
                if m_cid == cid:
                    continue
                m_sid = company_security.get(m_cid)
                r6 = (stock_returns.get(m_sid) or {}).get("r6") if m_sid else None
                if r6 is not None:
                    sec_vals.append(r6)
            if len(sec_vals) >= CFG.MIN_SECTOR_SAMPLE:
                sector_r6 = statistics.median(sec_vals)
        bundle["return_6m_rel_sector"] = _diff(sr.get("r6"), sector_r6)

        out[cid] = bundle
    return out


def _diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def _price_return(rows: list[dict], n_back: int) -> float | None:
    """Percent return over the last n_back trading rows (rows desc by date)."""
    if len(rows) <= n_back:
        return None
    last = num(rows[0]["closing_price_rial"])
    old = num(rows[n_back]["closing_price_rial"])
    if not last or not old or old <= 0:
        return None
    return (last - old) / old * 100.0


def _quarterly_yoy(monthly_rows: list[dict]) -> list[float]:
    """Quarterly sales YoY growth (oldest->newest, percent) from monthly rows."""
    qsum: dict[int, float] = {}
    for m in monthly_rows:
        val = num(m.get("sales_amount_rial"))
        if val is None:
            continue
        d = m["period_end_date"]
        month_index = d.year * 12 + (d.month - 1)
        qsum[month_index // 3] = qsum.get(month_index // 3, 0.0) + val
    out = []
    for qi in sorted(qsum):
        prev = qsum.get(qi - 4)
        if prev is not None and prev > 0:
            out.append((qsum[qi] - prev) / prev * 100.0)
    return out


def _net_ttm_yoy_signs(bs_rows: list[dict]) -> list[int]:
    """+1/-1 net-TTM YoY direction per cell, oldest->newest (max 8)."""
    by_cell = {r["cell"]: r for r in bs_rows}
    signs: list[int] = []
    for r in bs_rows:  # desc
        prev = by_cell.get((r["cell"][0] - 1, r["cell"][1]))
        if prev is None or r["net_profit"] is None or prev["net_profit"] is None:
            continue
        signs.append(1 if r["net_profit"] > prev["net_profit"] else -1)
        if len(signs) >= 8:
            break
    return list(reversed(signs))


def _quarter_concentration(rep: dict, durations_c: dict) -> float | None:
    """Share of the latest annual profit earned in its last single quarter.

    (annual cum − preceding in-year cum) / annual cum, from the reported
    order-1 cumulative values. None when the annual cell or its in-year
    predecessor is unavailable, or when the annual profit is not positive.
    """
    cells = _cells_sorted_desc(rep)
    dur_cells = [c for c in cells if durations_c.get(c) == 12]
    annual_cell = dur_cells[0] if dur_cells else next((c for c in cells if c[1] == 12), None)
    if annual_cell is None:
        return None
    idx = cells.index(annual_cell)
    if idx + 1 >= len(cells):
        return None
    prev_cell = cells[idx + 1]
    np_a = num((rep[annual_cell].get("net_profit") or {}).get(1))
    np_prev = num((rep[prev_cell].get("net_profit") or {}).get(1))
    if not np_a or np_a <= 0 or np_prev is None:
        return None
    share = (np_a - np_prev) / np_a
    return min(max(share, 0.0), 1.0)


# ---------------------------------------------------------------------------
# Raw factor assembly (family-aware)
# ---------------------------------------------------------------------------
# factor_code -> source key. Sources are looked up in the bundle first, then in
# the engine metrics dict; blend factors are computed instead.
FACTOR_SOURCE = {
    "roe_level": "roe",
    "roe_stability": "roe_volatility",
    "margin_trend": "margin_trend",
    "cash_conversion": "cash_conversion",
    "earnings_quality": "earnings_quality",
    "interest_coverage": "interest_coverage",
    "pe": "pe_normalized",   # anti-windfall: median-earnings P/E (see build_v4_inputs)
    "pb": "pb",
    "ps": "ps",
    "leverage": "debt_ratio",
    "current_ratio": "current_ratio",
    "debt_trend": "debt_ratio_change",
    "growth_acceleration": "revenue_yoy_acceleration",
    "growth_consistency": "quarter_yoy_positive_fraction",
    "momentum_6m_rel": "return_6m_rel_market",
    "momentum_3m_rel": "return_3m_rel_market",
    "relative_strength_6m_sector": "return_6m_rel_sector",
    "liquidity": "avg_trade_value_30d",
    "low_volatility": "volatility_30d",
}


def assemble_raw(eng_metrics: dict, bundles: dict) -> dict:
    """company_id -> {"family", "raw": {factor_code: value or None}}."""
    out: dict = {}
    for cid, v in eng_metrics.items():
        b = bundles[cid]
        family = b["score_model"]
        factors = CFG.FACTOR_FAMILIES[family]
        raw: dict = {}

        def blend(code: str) -> float | None:
            cfg = CFG.FACTOR_CONFIG[code]
            parts = dict(cfg.get("blend", {}))
            component_cap = cfg.get("component_cap")
            if component_cap is not None:
                # near-zero-denominator artifacts (one leg at 771,000,000%) are
                # dropped and the remaining legs renormalized; the blended value
                # itself is still checked against the factor's valid range
                parts = {k: w for k, w in parts.items()
                         if (b.get(k) if b.get(k) is not None else v.get(k)) is None
                         or abs(b.get(k) if b.get(k) is not None else v.get(k)) <= component_cap}
            if code == "revenue_growth" and b.get("revenue_cagr_3y") is not None:
                # when a 3y CAGR exists it takes cagr_share of the blend
                share = cfg["cagr_share"]
                cagr = b["revenue_cagr_3y"]
                if component_cap is None or abs(cagr) <= component_cap:
                    num_ = share * cagr
                    den = share
                    scaled = {k: w * (1.0 - share) for k, w in parts.items()}
                else:
                    num_ = den = 0.0
                    scaled = parts
            else:
                num_ = den = 0.0
                scaled = parts
            for field, w in scaled.items():
                val = b.get(field)
                if val is None:
                    val = v.get(field)
                if val is not None:
                    num_ += w * val
                    den += w
            return (num_ / den) if den > 1e-12 else None

        for fcode in factors:
            cfg = CFG.FACTOR_CONFIG[fcode]
            if "blend" in cfg or fcode == "revenue_growth":
                raw[fcode] = blend(fcode)
            else:
                field = FACTOR_SOURCE[fcode]
                val = b.get(field)
                if val is None:
                    val = v.get(field)
                raw[fcode] = val
        # Loss-maker valuation gate: P/B and P/S cheapness of a loss-maker is a
        # value trap, not value — neutralize (None -> missing -> 0.5) instead of
        # rewarding book-multiple cheapness that the market is discounting for
        # broken fundamentals. P/E is neutralized via the earnings median.
        if CFG.LOSS_MAKER_VALUATION_NEUTRAL:
            npttm = v.get("net_profit_ttm")
            if npttm is not None and npttm < 0:
                for neutral_factor in ("pb", "ps"):
                    if neutral_factor in raw:
                        raw[neutral_factor] = None
        out[cid] = {"family": family, "raw": raw}
    return out


# ---------------------------------------------------------------------------
# Validation + winsorization
# ---------------------------------------------------------------------------
def validate_raw(assembled: dict) -> dict:
    """company_id -> {factor_code: valid|missing|invalid}."""
    out: dict = {}
    for cid, item in assembled.items():
        st: dict = {}
        for fcode, val in item["raw"].items():
            if val is None or (isinstance(val, float) and val != val):
                st[fcode] = "missing"
                continue
            lo, hi = CFG.FACTOR_CONFIG[fcode]["valid"]
            if (lo is not None and val < lo) or (hi is not None and val > hi):
                st[fcode] = "invalid"
            else:
                st[fcode] = "valid"
        out[cid] = st
    return out


def _percentile(sorted_xs: list[float], q: float) -> float:
    idx = q * (len(sorted_xs) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def winsor_bounds(assembled: dict) -> dict:
    """factor_code -> (p1, p99) across economically-valid universe values."""
    vals: dict[str, list[float]] = {}
    for item in assembled.values():
        for fcode, val in item["raw"].items():
            if val is None or (isinstance(val, float) and val != val):
                continue
            lo, hi = CFG.FACTOR_CONFIG[fcode]["valid"]
            if (lo is not None and val < lo) or (hi is not None and val > hi):
                continue
            vals.setdefault(fcode, []).append(float(val))
    out: dict = {}
    for fcode, xs in vals.items():
        if not CFG.FACTOR_CONFIG[fcode]["winsorize"] or len(xs) < 20:
            continue
        xs.sort()
        out[fcode] = (_percentile(xs, 0.01), _percentile(xs, 0.99))
    return out


def apply_winsor(assembled: dict, bounds: dict) -> dict:
    """Clip ranking inputs into the winsor bounds; keep originals for display."""
    out: dict = {}
    for cid, item in assembled.items():
        clipped = {}
        for fcode, val in item["raw"].items():
            b = bounds.get(fcode)
            if val is None or b is None:
                clipped[fcode] = val
                continue
            lo, hi = b
            clipped[fcode] = min(max(val, lo), hi)
        out[cid] = {"family": item["family"], "raw": clipped, "raw_original": item["raw"]}
    return out


# ---------------------------------------------------------------------------
# Percentiles (market + sector blend)
# ---------------------------------------------------------------------------
def midrank(values: dict, higher_is_better: bool) -> dict:
    """Midrank percentile in [0,1]; absent keys map to None."""
    present = {k: v for k, v in values.items() if v is not None}
    out = {k: None for k in values}
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(present.values())
    for k, val in present.items():
        less = bisect_left(ordered, val)
        tie = bisect_right(ordered, val) - less
        pct = (2 * less + (tie - 1)) / (2 * (n - 1))
        out[k] = pct if higher_is_better else 1.0 - pct
    return out


def compute_market_percentiles(winsorized: dict) -> dict:
    """market[factor_code][company_id] = percentile across all valid values."""
    market: dict[str, dict] = {}
    for fcode, cfg in CFG.FACTOR_CONFIG.items():
        vals = {cid: item["raw"].get(fcode) for cid, item in winsorized.items()
                if fcode in item["raw"]}
        market[fcode] = midrank(vals, cfg["direction"] == "higher")
    return market


def compute_sector_percentiles(winsorized: dict, sector_of: dict) -> dict:
    """sector[factor_code][company_id], None when the sector sample is too small."""
    members: dict[str, list[str]] = {}
    for cid, cat in sector_of.items():
        if cat and cid in winsorized:
            members.setdefault(cat, []).append(cid)
    out: dict[str, dict] = {f: {} for f in CFG.FACTOR_CONFIG}
    for fcode, cfg in CFG.FACTOR_CONFIG.items():
        for cat, cids in members.items():
            vals = {cid: winsorized[cid]["raw"].get(fcode) for cid in cids
                    if fcode in winsorized[cid]["raw"]}
            n_valid = sum(1 for x in vals.values() if x is not None)
            pct = midrank(vals, cfg["direction"] == "higher") if n_valid >= CFG.MIN_SECTOR_SAMPLE else {}
            for cid in cids:
                out[fcode][cid] = pct.get(cid) if n_valid >= CFG.MIN_SECTOR_SAMPLE else None
    return out


def combined_percentile(market_p: float | None, sector_p: float | None,
                        sector_size: int) -> float | None:
    """0.70*sector + 0.30*market; market-only when no sector percentile.

    With SECTOR_BLEND_DECAY the sector weight scales linearly from 0 at one
    member up to SECTOR_WEIGHT at MIN_SECTOR_SAMPLE members.
    """
    if market_p is None:
        return None
    if sector_p is None:
        return market_p
    w = CFG.SECTOR_WEIGHT
    if CFG.SECTOR_BLEND_DECAY and 0 <= sector_size < CFG.MIN_SECTOR_SAMPLE:
        w = CFG.SECTOR_WEIGHT * max(0, sector_size - 1) / (CFG.MIN_SECTOR_SAMPLE - 1)
    return w * sector_p + (1.0 - w) * market_p


# ---------------------------------------------------------------------------
# Confidence (independent of the score)
# ---------------------------------------------------------------------------
ANOMALY_FLAGS = ("EPS_NETPROFIT_SIGN_MISMATCH", "TTM_METHOD_MISMATCH",
                 "EPS_COMPARATIVE_SHARE_BASE_MISMATCH", "FISCAL_CALENDAR_UNKNOWN",
                 "unknown_unit")


def compute_confidence(v: dict, bundle: dict, statuses: dict) -> tuple[float, dict]:
    fam = CFG.FACTOR_FAMILIES[bundle["score_model"]]
    cc = CFG.CONFIDENCE_COMPONENTS
    th = CFG.CONFIDENCE_THRESHOLDS
    n_factors = len(fam)
    n_valid = sum(1 for s in statuses.values() if s == "valid")
    completeness = n_valid / n_factors if n_factors else 0.0

    age_m = bundle.get("profit_report_age_months")
    if age_m is None:
        fin_fresh = 0.0
    elif age_m <= th["financial_fresh_full_months"]:
        fin_fresh = 1.0
    elif age_m >= th["financial_fresh_dead_months"]:
        fin_fresh = 0.0
    else:
        span = th["financial_fresh_dead_months"] - th["financial_fresh_full_months"]
        fin_fresh = 1.0 - (age_m - th["financial_fresh_full_months"]) / span

    age_d = bundle.get("market_data_age_days")
    if age_d is None:
        mkt_fresh = 0.0
    elif age_d <= th["market_fresh_full_days"]:
        mkt_fresh = 1.0
    elif age_d >= th["market_fresh_dead_days"]:
        mkt_fresh = 0.0
    else:
        span = th["market_fresh_dead_days"] - th["market_fresh_full_days"]
        mkt_fresh = 1.0 - (age_d - th["market_fresh_full_days"]) / span

    monthly = 1.0 if v.get("has_monthly") else 0.0

    dq = v.get("_dq")
    flags = set(dq.flags) if dq is not None else set()
    anomalies_hit = sorted(flags & set(ANOMALY_FLAGS))
    anomaly_score = 1.0 - (len(anomalies_hit) / len(ANOMALY_FLAGS))

    parts = {
        "completeness": cc["completeness"] * completeness,
        "financial_freshness": cc["financial_freshness"] * fin_fresh,
        "market_freshness": cc["market_freshness"] * mkt_fresh,
        "monthly_coverage": cc["monthly_coverage"] * monthly,
        "anomalies": cc["anomalies"] * anomaly_score,
    }
    total = round(sum(parts.values()), 1)
    detail = {k: round(val, 2) for k, val in parts.items()}
    detail["valid_factors"] = f"{n_valid}/{n_factors}"
    detail["profit_report_age_months"] = age_m
    detail["market_data_age_days"] = age_d
    detail["anomaly_flags"] = anomalies_hit
    return min(100.0, max(0.0, total)), detail


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------
def compute_penalties(v: dict, bundle: dict, statuses: dict) -> tuple[float, list[dict]]:
    rules = CFG.PENALTY_RULES
    items: list[dict] = []

    equity = bundle.get("equity_latest")
    if equity is not None and equity <= 0:
        items.append({"code": "negative_equity", "penalty": rules["negative_equity"]["penalty"],
                      "reason": rules["negative_equity"]["reason"], "value": equity})

    dr = bundle.get("debt_ratio_latest")
    if dr is not None and dr > rules["extreme_leverage"]["threshold"]:
        items.append({"code": "extreme_leverage", "penalty": rules["extreme_leverage"]["penalty"],
                      "reason": rules["extreme_leverage"]["reason"], "value": dr})

    age_m = bundle.get("profit_report_age_months")
    if age_m is not None and age_m > rules["stale_filing"]["max_age_months"]:
        items.append({"code": "stale_filing", "penalty": rules["stale_filing"]["penalty"],
                      "reason": rules["stale_filing"]["reason"], "value": age_m})

    signs = bundle.get("net_ttm_yoy_signs") or []
    need = rules["multi_quarter_deterioration"]["consecutive"]
    if len(signs) >= need and all(s == -1 for s in signs[-need:]):
        items.append({"code": "multi_quarter_deterioration",
                      "penalty": rules["multi_quarter_deterioration"]["penalty"],
                      "reason": rules["multi_quarter_deterioration"]["reason"],
                      "value": need})

    # suspicious earnings only when the company reports an operating line
    nop = v.get("earnings_quality")
    if (nop is not None and statuses.get("earnings_quality") == "valid"
            and nop > rules["suspicious_earnings"]["threshold"]):
        items.append({"code": "suspicious_earnings",
                      "penalty": rules["suspicious_earnings"]["penalty"],
                      "reason": rules["suspicious_earnings"]["reason"], "value": nop})

    # earnings spike: current TTM far above the median of recent annual profits,
    # evidenced EITHER by weak cash backing (non-cash windfall) OR by extreme
    # single-quarter concentration of the annual profit (no OCF needed). A
    # cash-backed, evenly-earned jump is growth, not a risk signal. The
    # normalized P/E damps the valuation factor for every spike either way.
    median_np = bundle.get("normalized_net_profit")
    ttm_np = v.get("net_profit_ttm")
    cc = v.get("cash_conversion")
    cc_status = statuses.get("cash_conversion")
    ratio_ok = (median_np is not None and median_np > 0 and ttm_np is not None
                and ttm_np > rules["earnings_spike"]["spike_ratio"] * median_np)
    cash_evidence = (cc is not None and cc_status == "valid"
                     and cc < rules["earnings_spike"]["cash_backing_max"])
    concentration = bundle.get("quarter_profit_concentration")
    concentration_evidence = (concentration is not None
                              and concentration >= rules["earnings_spike"]["quarter_concentration_min"])
    if ratio_ok and (cash_evidence or concentration_evidence):
        items.append({"code": "earnings_spike",
                      "penalty": rules["earnings_spike"]["penalty"],
                      "reason": rules["earnings_spike"]["reason"],
                      "value": round(ttm_np / median_np, 2)})

    total = min(sum(i["penalty"] for i in items), CFG.PENALTY_CAP)
    return total, items


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_company(cid: str, eng_metrics: dict, bundles: dict, winsorized: dict,
                  statuses: dict, market_p: dict, sector_p: dict,
                  sector_sizes: dict) -> dict:
    v = eng_metrics[cid]
    bundle = bundles[cid]
    family = bundle["score_model"]
    fam = CFG.FACTOR_FAMILIES[family]

    factors: dict[str, dict] = {}
    categories: dict[str, dict] = {c: {"score": 0.0, "max": 0.0} for c in CFG.CATEGORY_ORDER}
    n_missing = n_invalid = 0
    sector = bundle.get("sector")
    sector_size = sector_sizes.get(sector, 0)

    for fcode, weight in fam.items():
        cfg = CFG.FACTOR_CONFIG[fcode]
        cat = cfg["category"]
        categories[cat]["max"] = round(categories[cat]["max"] + weight, 2)
        status = statuses[cid].get(fcode, "missing")
        cp = None
        if status == "valid":
            mp = market_p.get(fcode, {}).get(cid)
            sp = sector_p.get(fcode, {}).get(cid) if cfg["sector_relative"] else None
            cp = combined_percentile(mp, sp, sector_size)
            if cp is None:
                status = "missing"
        if status == "valid":
            percentile = cp
        elif status == "missing":
            percentile = CFG.NEUTRAL_PERCENTILE
            n_missing += 1
        else:
            percentile = CFG.INVALID_PERCENTILE
            n_invalid += 1
        earned = round(weight * percentile, 4)
        entry = {
            "category": cat,
            "weight": weight,
            "status": status,
            "percentile": round(percentile, 4),
            "market_percentile": (round(market_p[fcode][cid], 4)
                                  if market_p.get(fcode, {}).get(cid) is not None else None),
            "sector_percentile": (round(sector_p[fcode][cid], 4)
                                  if sector_p.get(fcode, {}).get(cid) is not None else None),
            "score": earned,
            "raw_value": winsorized[cid]["raw_original"].get(fcode),
            "ranked_value": winsorized[cid]["raw"].get(fcode),
        }
        # explain deliberate neutralization in the UI
        npttm = v.get("net_profit_ttm")
        if status == "missing" and fcode in ("pb", "ps") and npttm is not None and npttm < 0:
            entry["note"] = "شرکت زیان‌ده است؛ ضریب‌های دفتری خنثی امتیاز دادند (تله‌ی ارزش)"
        elif status == "missing" and fcode == "pe" and bundle.get("normalized_net_profit") is not None \
                and bundle["normalized_net_profit"] <= 0:
            entry["note"] = "میانه‌ی سود سالانه‌ی اخیر منفی است؛ P/E خنثی امتیاز داد"
        factors[fcode] = entry
        categories[cat]["score"] = round(categories[cat]["score"] + earned, 4)

    base = round(sum(c["score"] for c in categories.values()), 4)
    penalties_total, penalty_items = compute_penalties(v, bundle, statuses[cid])
    score = round(min(100.0, max(0.0, base - penalties_total)), 2)
    confidence, confidence_detail = compute_confidence(v, bundle, statuses[cid])
    cr = confidence / 100.0
    adjusted = round(cr * score + (1.0 - cr) * 50.0, 2)

    return {
        "company_id": cid,
        "symbol": v.get("symbol"),
        "security_id": v.get("security_id"),
        "score_model": family,
        "sector": sector,
        "score": score,
        "confidence": confidence,
        "adjusted_score": adjusted,
        "base_score": base,
        "penalties_total": round(penalties_total, 2),
        "penalty_items": penalty_items,
        "categories": {c: {"score": round(d["score"], 2), "max": d["max"]}
                       for c, d in categories.items()},
        "factors": factors,
        "confidence_detail": confidence_detail,
        "n_missing": n_missing,
        "n_invalid": n_invalid,
    }


def run_v4_scoring(eng: Engine, sector_map: dict[str, str]) -> tuple[dict, dict]:
    """Full v4 pipeline over a computed Engine. Returns (results, diagnostics)."""
    bundles = build_v4_inputs(eng, sector_map)
    assembled = assemble_raw(eng.metrics, bundles)
    statuses = validate_raw(assembled)
    bounds = winsor_bounds(assembled)
    winsorized = apply_winsor(assembled, bounds)
    market_p = compute_market_percentiles(winsorized)
    sector_p = compute_sector_percentiles(winsorized,
                                          {c: b.get("sector") for c, b in bundles.items()})
    sector_sizes: dict[str | None, int] = {}
    for b in bundles.values():
        s = b.get("sector")
        sector_sizes[s] = sector_sizes.get(s, 0) + 1

    results = {cid: score_company(cid, eng.metrics, bundles, winsorized, statuses,
                                  market_p, sector_p, sector_sizes)
               for cid in eng.metrics}

    # company-level score percentiles (post-scoring; not part of the score)
    score_p = midrank({cid: r["score"] for cid, r in results.items()}, True)
    for cid, r in results.items():
        r["market_percentile"] = round(score_p[cid], 4) if score_p[cid] is not None else None
        r["sector_percentile"] = None
    members: dict[str, list[str]] = {}
    for cid, b in bundles.items():
        if b.get("sector"):
            members.setdefault(b["sector"], []).append(cid)
    for cat, cids in members.items():
        if len(cids) >= CFG.MIN_SECTOR_SAMPLE:
            sp = midrank({cid: results[cid]["score"] for cid in cids}, True)
            for cid in cids:
                results[cid]["sector_percentile"] = round(sp[cid], 4) if sp[cid] is not None else None

    diag = {"winsor_bounds": {k: list(v) for k, v in bounds.items()},
            "sector_sizes": {str(k): v for k, v in sorted(sector_sizes.items(), key=lambda x: str(x[0]))}}
    return results, diag


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
V4_COLUMNS = (
    "score numeric(12,4)", "confidence numeric(12,4)", "adjusted_score numeric(12,4)",
    "score_model text", "market_percentile numeric(9,6)", "sector_percentile numeric(9,6)",
    "penalties_total numeric(12,4)", "score_breakdown jsonb", "confidence_breakdown jsonb",
    "penalties_breakdown jsonb",
)


def ensure_v4_columns(pg) -> None:
    """Idempotent in-code guard; the canonical migration lives in sql/130_score_v4.sql."""
    with pg.cursor() as cur:
        for col in V4_COLUMNS:
            cur.execute(f"ALTER TABLE analytics.company_scores ADD COLUMN IF NOT EXISTS {col}")


def config_fingerprint(digest: str, diag: dict) -> dict:
    cfg_src = (HERE / "score_v4_config.py").read_bytes()
    return {
        "score_version": CFG.SCORE_VERSION_V4,
        "category_weights": CFG.CATEGORY_WEIGHTS,
        "factor_config": CFG.FACTOR_CONFIG,
        "factor_families": CFG.FACTOR_FAMILIES,
        "neutral_percentile": CFG.NEUTRAL_PERCENTILE,
        "invalid_percentile": CFG.INVALID_PERCENTILE,
        "sector_weight": CFG.SECTOR_WEIGHT,
        "market_weight": CFG.MARKET_WEIGHT,
        "min_sector_sample": CFG.MIN_SECTOR_SAMPLE,
        "confidence_components": CFG.CONFIDENCE_COMPONENTS,
        "penalty_rules": CFG.PENALTY_RULES,
        "penalty_cap": CFG.PENALTY_CAP,
        "config_sha256": hashlib.sha256(cfg_src).hexdigest(),
        "input_hash": digest,
        "winsor_bounds": diag["winsor_bounds"],
        "sector_sizes": diag["sector_sizes"],
    }


def store_run_v4(eng: Engine, results: dict, diag: dict,
                 as_of: dt.date, cutoff: dt.datetime, digest: str) -> str:
    pg = pg_pilot_conn()
    ensure_v4_columns(pg)
    params = config_fingerprint(digest, diag)
    try:
        with pg.cursor() as cur:
            watermark = CM.input_watermark(cur)
            # run_kind='pit_backfill' is explicit: v4 is experimental/off-line and must
            # never be selectable as the served current score for its version.
            cur.execute("""INSERT INTO analytics.score_runs
                (score_version, as_of_date, source_cutoff_at, status, completed_at, code_version,
                 parameters, run_kind, input_watermark)
                VALUES (%s,%s,%s,'completed',now(),%s,%s,'pit_backfill',%s) RETURNING id""",
                (CFG.SCORE_VERSION_V4, as_of, cutoff,
                 "score-v4+sector-relative+confidence-split",
                 json.dumps(params, ensure_ascii=False, default=str),
                 json.dumps(watermark, default=str)))
            run_id = cur.fetchone()[0]
            for cid, r in results.items():
                cats = r["categories"]
                cur.execute("""INSERT INTO analytics.company_scores
                    (run_id, company_id, primary_security_id,
                     quant_score, data_quality_score, growth_score, profitability_score,
                     valuation_score, market_score, input_hash, details,
                     score, confidence, adjusted_score, score_model,
                     market_percentile, sector_percentile, penalties_total,
                     score_breakdown, confidence_breakdown, penalties_breakdown)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id, company_id) DO NOTHING""",
                    (run_id, cid, r["security_id"],
                     r["score"], round(r["confidence"] / 100.0, 4),
                     cats["growth"]["score"], cats["quality"]["score"],
                     cats["valuation"]["score"], cats["market"]["score"],
                     digest, json.dumps({"v4": True, "score_model": r["score_model"]},
                                        ensure_ascii=False),
                     r["score"], r["confidence"], r["adjusted_score"], r["score_model"],
                     r.get("market_percentile"), r.get("sector_percentile"),
                     r["penalties_total"],
                     json.dumps({"categories": cats, "base_score": r["base_score"],
                                 "sector": r["sector"],
                                 "factors": r["factors"]},
                                ensure_ascii=False, default=str),
                     json.dumps(r["confidence_detail"], ensure_ascii=False, default=str),
                     json.dumps({"total": r["penalties_total"], "items": r["penalty_items"]},
                                ensure_ascii=False, default=str)))
                for fcode, f in r["factors"].items():
                    cur.execute("""INSERT INTO analytics.factor_scores
                        (run_id, company_id, factor_code, raw_value, percentile,
                         weighted_score, weight, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_id, company_id, factor_code) DO NOTHING""",
                        (run_id, cid, f"v4_{fcode}", f["raw_value"], f["percentile"],
                         f["score"], f["weight"],
                         json.dumps({"status": f["status"],
                                     "market_percentile": f["market_percentile"],
                                     "sector_percentile": f["sector_percentile"],
                                     "ranked_value": f["ranked_value"],
                                     "score_model": r["score_model"],
                                     "category": f["category"]},
                                    ensure_ascii=False, default=str)))
                for mc, mu in CM.METRIC_UNITS.items():
                    val = eng.metrics[cid].get(mc)
                    if val is None:
                        continue
                    cur.execute("""INSERT INTO analytics.metric_snapshots
                        (run_id, as_of_date, company_id, primary_security_id, metric_code,
                         value, unit, calculation_version, source_cutoff_at, details)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_id, company_id, metric_code) DO NOTHING""",
                        (run_id, as_of, cid, r["security_id"], mc, val, mu,
                         CFG.SCORE_VERSION_V4, cutoff,
                         json.dumps({"input_hash": digest}, ensure_ascii=False)))
        pg.commit()
        return str(run_id)
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _distribution(values: list[float]) -> dict:
    if not values:
        return {}
    xs = sorted(values)

    def q(p):
        return round(_percentile(xs, p), 2)
    return {"count": len(xs), "mean": round(sum(xs) / len(xs), 2),
            "std": round(statistics.pstdev(xs), 2), "min": round(xs[0], 2),
            "p10": q(0.10), "p25": q(0.25), "p50": q(0.50), "p75": q(0.75),
            "p90": q(0.90), "max": round(xs[-1], 2)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=dt.date.today().isoformat())
    ap.add_argument("--cutoff", required=True, help="PIT source cutoff, ISO with tz")
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--outdir", default=str(HERE / "output"))
    args = ap.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    eng = Engine(as_of, cutoff)
    eng.compute()
    sector_map = load_sector_map(as_of)
    results, diag = run_v4_scoring(eng, sector_map)

    scores = [r["score"] for r in results.values()]
    confs = [r["confidence"] for r in results.values()]
    report = {
        "score_version": CFG.SCORE_VERSION_V4,
        "as_of": as_of.isoformat(),
        "cutoff": cutoff.isoformat(),
        "population": len(results),
        "score_distribution": _distribution(scores),
        "confidence_distribution": _distribution(confs),
        "category_distributions": {
            c: _distribution([r["categories"][c]["score"] for r in results.values()])
            for c in CFG.CATEGORY_ORDER},
        "model_families": {f: sum(1 for r in results.values() if r["score_model"] == f)
                           for f in CFG.FACTOR_FAMILIES},
        "sector_fallback_rate": round(sum(
            1 for r in results.values()
            if r["sector"] is None or diag["sector_sizes"].get(str(r["sector"]), 0) < CFG.MIN_SECTOR_SAMPLE
        ) / max(1, len(results)), 4),
        "penalty_counts": {code: sum(1 for r in results.values()
                                     if any(i["code"] == code for i in r["penalty_items"]))
                           for code in CFG.PENALTY_RULES},
        "missing_invalid_totals": {
            "missing_factor_slots": sum(r["n_missing"] for r in results.values()),
            "invalid_factor_slots": sum(r["n_invalid"] for r in results.values())},
        "sector_sizes": diag["sector_sizes"],
    }
    (outdir / "score_v4_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    payload = {cid: {k: v for k, v in r.items() if k != "factors"} for cid, r in results.items()}
    (outdir / "score_v4_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print(f"population: {len(results)}")
    print("score:", report["score_distribution"])
    print("confidence:", report["confidence_distribution"])
    print("families:", report["model_families"])
    print("sector fallback rate:", report["sector_fallback_rate"])
    print("penalty counts:", report["penalty_counts"])
    if args.store:
        digest = eng.digest()
        run_id = store_run_v4(eng, results, diag, as_of, cutoff, digest)
        print("stored score_run", run_id, "companies", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
