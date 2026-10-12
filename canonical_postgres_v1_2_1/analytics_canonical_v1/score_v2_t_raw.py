"""Raw T (timing) factor extraction and validation for Score v2 — step 2-D-1.

Extraction/validation layer ONLY for the five READY timing factors
(momentum_6m_rel, momentum_3m_rel, relative_strength_6m_sector, liquidity,
low_volatility). No scoring, no weights, no percentiles, no ranking: those
belong to the normalization layer and the observed-T pilot. The
needs_development factor distance_from_52w_high is NEVER computed here (the
config forbids any automatic surrogate).

Factor contract (score_v2_config.V2_QVT_FACTORS, the registry governs — the
three mission categories are only lenses onto it):

    momentum_6m_rel            higher — "بازده ۶ ماهه نسبی به بازار"
                               = stock 6-month return  -  market 6-month return
    momentum_3m_rel            higher — "بازده ۳ ماهه نسبی به بازار"
                               = stock 3-month return  -  market 3-month return
    relative_strength_6m_sector higher — "قدرت نسبی ۶ ماهه در صنعت"
                               = stock 6-month return  -  industry 6-month mean
    liquidity                  higher — "ارزش معاملات ۳۰ روزه"
                               = mean trade value over the security's last 30
                               sessions (the V1 engine's own avg_trade_value_30d
                               construction, deduplicated per day)
    low_volatility             lower — "نوسان ۳۰ روزه"
                               = sample stdev of daily returns over the last
                               ~30 adjusted closes (the V1 engine's own
                               volatility_30d construction, hardened)

Price basis: market.price_observations is, in this store, ENTIRELY the
vendor-adjusted series (price_series = 'adjusted' on every row,
adjustment_method = vendor_adjusted / legacy_brs_adjusted) — so the momentum
windows ride the ADJUSTED closes. "Relative to market / sector" uses the
equal-weighted mean return of the evaluated population (market) and of the
company's own industry group (sector) over the SAME window, computed only
from valid member returns: no external index is invented, and — because a
single-scalar benchmark shifts every company by the same constant — the
cross-sectional ordering is invariant to any other common benchmark choice.

Gates (mission 2-D-1 sections 2-3 — history depth, adjustment trust, halts):

  history   no row for the security, or no valid adjusted close
            (close must be finite and >= PRICE_FLOOR: a 1-rial placeholder
            row is not a trade)                  -> missing no_price_history
  lookahead trade_date > as_of rows are dropped at extraction (defense in
            depth on top of the engine's collected_at/trade_date filter)
  staleness latest valid close older than STALE_DAYS before as_of
                                                 -> invalid price_stale on
            ALL five factors (a momentum/liquidity/volatility reading on a
            months-old price is not a current entry condition; the halt is
            marked, not hidden — last_trade_date stays on the record)
  momentum  no valid close on/before the window reference date
            (as_of minus 6/3 calendar months)    -> missing
            insufficient_history_6m / _3m — a shorter history is NEVER
            silently relabeled as a full-window return
            any consecutive-close return with |r| >= JUMP_BAND inside the
            return chain (base inclusive)        -> invalid
            suspected_unadjusted_gap_in_window — the adjusted series left a
            gap no continuous trading under TSE price limits can produce
            (a missed capital-action adjustment or a data hole); the value
            is refused, never scored: a capital-increase jump must not earn
            a momentum or volatility reading
  sector    industry unclassified                -> not_applicable
            industry_unclassified
            fewer than SECTOR_BENCH_MIN_MEMBERS valid 6-month returns in the
            industry group (self included)       -> not_applicable
            insufficient_sector_benchmark
  liquidity fewer than LIQ_MIN_OBS non-null trade values among the last 30
            sessions                             -> missing
            insufficient_history_liquidity
            window span over WINDOW_MAX_SPAN_DAYS -> invalid
            window_span_too_long (the "30-session" label would lie)
            no-trade sessions (trade value 0) are REAL observations inside
            the mean; missing values are counted separately and never
            fabricated — both stay on the record
  volatility fewer than VOL_MIN_RETURNS daily returns among the last
            VOL_WINDOW_CLOSES closes             -> missing
            insufficient_history_volatility
            window span over WINDOW_MAX_SPAN_DAYS -> invalid
            window_span_too_long
            any |return| >= JUMP_BAND inside the volatility window
                                                 -> invalid
            suspected_unadjusted_gap_in_window

PIT contract: market rows carry no publication timestamp; their temporal
evidence is the collection time, bounded by the caller to collected_at <=
cutoff (engine filter, re-checked per record as available_at = max
collected_at used). Records declare pit_status "collected_at_bounded" — NOT
RAW.PIT_VERIFIED: the store has no per-observation source_ref, so
historical_strict ranking refuses them (no backtest claim), mirroring the V
layer's doctrine.

Pure and deterministic: in-memory inputs only, no database, no engine, no
clock; identical inputs in any order produce identical output.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics

import score_v2_raw as RAW

__all__ = [
    "STAGE",
    "IN_SCOPE_T_FACTORS",
    "PRICE_FLOOR",
    "STALE_DAYS",
    "JUMP_BAND",
    "VOL_WINDOW_CLOSES",
    "VOL_MIN_RETURNS",
    "LIQ_WINDOW_OBS",
    "LIQ_MIN_OBS",
    "WINDOW_MAX_SPAN_DAYS",
    "SECTOR_BENCH_MIN_MEMBERS",
    "extract_daily_history",
    "build_t_raw",
]

STAGE = "t_raw_extraction"

IN_SCOPE_T_FACTORS = (
    "liquidity", "low_volatility", "momentum_3m_rel", "momentum_6m_rel",
    "relative_strength_6m_sector",
)

# Experimental thresholds of this step — declared, never hidden.
PRICE_FLOOR = 100.0        # rial: a close below this is a placeholder row
STALE_DAYS = 14            # latest close age hard gate for ALL T factors
JUMP_BAND = 0.21           # one-day |return| no TSE session can produce
VOL_WINDOW_CLOSES = 31     # last 31 closes -> up to 30 daily returns
VOL_MIN_RETURNS = 10       # a "30-day" stdev needs a real sample
LIQ_WINDOW_OBS = 30        # sessions (config: ارزش معاملات ۳۰ روزه)
LIQ_MIN_OBS = 10
WINDOW_MAX_SPAN_DAYS = 60  # a 30-session window may not silently span months
SECTOR_BENCH_MIN_MEMBERS = 2  # industry members (self included) for rs6

UNITS = {"momentum_6m_rel": "return_fraction",
         "momentum_3m_rel": "return_fraction",
         "relative_strength_6m_sector": "return_fraction",
         "liquidity": "rial",
         "low_volatility": "daily_return_stdev"}

DEFINITIONS = {
    "momentum_6m_rel":
        "stock 6-month adjusted return - equal-weight market 6-month return",
    "momentum_3m_rel":
        "stock 3-month adjusted return - equal-weight market 3-month return",
    "relative_strength_6m_sector":
        "stock 6-month adjusted return - equal-weight industry 6-month mean",
    "liquidity":
        "mean trade value over the security's last 30 deduplicated sessions",
    "low_volatility":
        "sample stdev of daily adjusted-close returns over the last ~30 "
        "closes (lower is better)",
}


def _num(x):
    """float or None — non-finite / non-numeric becomes None (definite
    corruption never masquerades as data)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def months_back(d: dt.date, months: int) -> dt.date:
    """d shifted back a whole number of calendar months, day clamped to the
    target month's length (Aug 31 - 6m -> Feb 28/29)."""
    y = d.year
    m = d.month - months
    while m <= 0:
        m += 12
        y -= 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last))


def extract_daily_history(prices: list, as_of: dt.date) -> dict:
    """{security_id: [day record, ...]} — the engine's flat price rows turned
    into per-security ascending daily series.

    One record per (security, trade_date): engine rows are ordered trade_date
    DESC, collected_at DESC, so the FIRST row seen per date carries the latest
    collection. Rows with trade_date > as_of are dropped here (lookahead
    guard, defense in depth beyond the engine's own PIT filter).
    """
    seen: dict = {}
    for r in prices or []:
        sid = r.get("security_id")
        d = r.get("trade_date")
        if sid is None or d is None or d > as_of:
            continue
        bucket = seen.setdefault(sid, {})
        if d in bucket:
            continue  # first seen = latest collected_at (engine order)
        bucket[d] = {"date": d,
                     "close": _num(r.get("closing_price_rial")),
                     "tv": _num(r.get("trade_value_rial")),
                     "collected_at": r.get("collected_at")}
    return {sid: sorted(days.values(), key=lambda x: x["date"])
            for sid, days in seen.items()}


class _Facts:
    """Per-security market facts shared by all five factor gates."""

    __slots__ = ("valid_closes", "last_d", "last_c", "age_days",
                 "bases", "chains", "vol", "liq", "available_at")

    def __init__(self) -> None:
        self.valid_closes: list = []
        self.last_d = None
        self.last_c = None
        self.age_days = None
        self.bases: dict = {}
        self.chains: dict = {}
        self.vol: dict = {}
        self.liq: dict = {}
        self.available_at = None


def _gap_pairs(closes: list) -> list:
    """Consecutive-pair returns of an ascending valid-close list, with the
    first date of each pair (for gap reporting)."""
    out = []
    for (d1, c1), (d2, c2) in zip(closes, closes[1:]):
        out.append((d1, d2, c2 / c1 - 1.0 if c1 > 0 else None))
    return out


def _security_facts(day_records: list, as_of: dt.date) -> _Facts:
    """All window math for one security, computed once: valid closes, the
    6m/3m bases and return chains (base inclusive), the volatility window,
    the liquidity window, and the max collected_at used."""
    f = _Facts()
    if not day_records:
        return f
    f.valid_closes = [(r["date"], r["close"]) for r in day_records
                      if r["close"] is not None and r["close"] >= PRICE_FLOOR]
    if not f.valid_closes:
        return f
    f.last_d, f.last_c = f.valid_closes[-1]
    f.age_days = (as_of - f.last_d).days
    colls = [r["collected_at"] for r in day_records
             if r.get("collected_at") is not None]
    f.available_at = max(colls) if colls else None

    for fid, months in (("momentum_6m_rel", 6), ("momentum_3m_rel", 3),
                        ("relative_strength_6m_sector", 6)):
        ref = months_back(as_of, months)
        idx = None
        for i, (d, _c) in enumerate(f.valid_closes):
            if d <= ref:
                idx = i
            else:
                break
        if idx is None:
            f.bases[fid] = {"ref_date": ref, "base_date": None,
                            "base_close": None, "stock_return": None}
            f.chains[fid] = []
            continue
        bd, bc = f.valid_closes[idx]
        ret = f.last_c / bc - 1.0
        f.bases[fid] = {"ref_date": ref, "base_date": bd, "base_close": bc,
                        "stock_return": ret}
        f.chains[fid] = _gap_pairs(f.valid_closes[idx:])

    vol_closes = f.valid_closes[-VOL_WINDOW_CLOSES:]
    vrets = [(d1, d2, c2 / c1 - 1.0)
             for (d1, c1), (d2, c2) in zip(vol_closes, vol_closes[1:])
             if c1 > 0]
    f.vol = {"closes": vol_closes, "returns": vrets,
             "n_returns": len(vrets),
             "span_days": (vol_closes[-1][0] - vol_closes[0][0]).days
             if len(vol_closes) >= 2 else None}

    win = day_records[-LIQ_WINDOW_OBS:]
    tvs = [r["tv"] for r in win if r["tv"] is not None and r["tv"] >= 0.0]
    f.liq = {"window": win, "tvs": tvs, "n_sessions": len(win),
             "n_valid_tvs": len(tvs),
             "n_no_trade": sum(1 for t in tvs if t == 0.0),
             "n_missing": len(win) - len(tvs),
             "span_days": (win[-1]["date"] - win[0]["date"]).days
             if len(win) >= 2 else None}
    return f


def _gap_warnings(chains: dict) -> list:
    """Named evidence for every suspected unadjusted gap in the given
    {factor_id: pairs} windows (deduplicated across windows)."""
    seen: set = set()
    out: list = []
    for fid in sorted(chains):
        for d1, d2, r in chains[fid]:
            if r is None or abs(r) < JUMP_BAND or d2 in seen:
                continue
            seen.add(d2)
            out.append(
                f"suspected_unadjusted_gap: {d2} close moves "
                f"{r:+.1%} from {d1} — no continuous TSE session can do "
                "this; the adjusted series left a corporate-action "
                "adjustment or a data hole unapplied")
    return out


def _history_block(f: _Facts) -> dict:
    return {
        "last_trade_date": str(f.last_d) if f.last_d else None,
        "price_age_days": f.age_days,
        "n_daily_closes": len(f.valid_closes),
        "price_floor_rial": PRICE_FLOOR,
    }


def _record(fid: str, *, raw_value, status: str, reason: str,
            warnings: list, history: dict, window: dict,
            available_at) -> dict:
    return {
        "factor_id": fid,
        "raw_value": raw_value,
        "status": status,
        "validation_reason": reason,
        "warnings": warnings,
        "unit": UNITS[fid],
        "definition": DEFINITIONS[fid],
        "source_metric": "market.price_observations (adjusted series)",
        "available_at": available_at,
        "pit_status": "collected_at_bounded",
        "pit_reason": ("market observations bounded by collected_at <= "
                       "cutoff at extraction; the store carries no "
                       "per-observation source_ref, so historical_strict "
                       "ranking refuses these records"),
        "market": {**history, "window": window},
    }


def build_t_raw(histories: dict,
                security_by_company: dict,
                company_meta: dict,
                *,
                as_of=None) -> dict:
    """Raw T records for every company in ``security_by_company``.

    histories             {security_id: day records} from
                          extract_daily_history (already as_of-bounded)
    security_by_company   {company_id: security_id} (the engine's metrics)
    company_meta          {cid: {"model_family", "industry"}} — the industry
                          builds the relative_strength_6m_sector benchmark
    as_of                 evaluation date (window references + staleness)

    Benchmarks: the market momentum benchmark is the equal-weighted mean of
    the VALID stock returns of the evaluated population (self included);
    the sector benchmark is the equal-weighted mean of the valid returns of
    the company's own industry group. Populations are built ONLY from
    companies whose own return passed every gate (stale / short-history /
    gap-refused companies never seed a benchmark).
    """
    if as_of is None:
        raise ValueError("as_of evaluation date is required")
    facts_by_company: dict = {}
    raw_returns: dict = {"momentum_6m_rel": {}, "momentum_3m_rel": {},
                         "relative_strength_6m_sector": {}}
    for cid in sorted(security_by_company):
        sid = security_by_company.get(cid)
        recs = (histories or {}).get(sid) or []
        f = _security_facts(recs, as_of)
        facts_by_company[cid] = f
        for fid in ("momentum_6m_rel", "momentum_3m_rel",
                    "relative_strength_6m_sector"):
            base = f.bases.get(fid) or {}
            if base.get("stock_return") is None or \
                    f.age_days is None or f.age_days > STALE_DAYS:
                continue
            if any(r is not None and abs(r) >= JUMP_BAND
                   for _d1, _d2, r in f.chains.get(fid) or ()):
                continue
            raw_returns[fid][cid] = base["stock_return"]

    benchmarks: dict = {}
    for fid in ("momentum_6m_rel", "momentum_3m_rel"):
        vals = raw_returns[fid]
        benchmarks[fid] = (
            {"mean": math.fsum(vals[c] for c in sorted(vals)) / len(vals),
             "n": len(vals)} if vals else None)
    ind_members: dict = {}
    for cid in sorted(raw_returns["relative_strength_6m_sector"]):
        ind = ((company_meta or {}).get(cid) or {}).get("industry")
        ind = ind.strip() if isinstance(ind, str) and ind.strip() else None
        if ind is not None:
            ind_members.setdefault(ind, []).append(cid)
    ind_bench = {ind: {"mean": math.fsum(
        raw_returns["relative_strength_6m_sector"][c]
        for c in sorted(members)) /
        len(members), "n": len(members)}
        for ind, members in sorted(ind_members.items())
        if len(members) >= SECTOR_BENCH_MIN_MEMBERS}

    out: dict = {}
    for cid in sorted(security_by_company):
        f = facts_by_company[cid]
        hist = _history_block(f)
        recs: dict = {}

        # ---- shared gates: history and staleness -------------------------
        shared_fail = None
        if f.last_c is None:
            shared_fail = (RAW.STATUS_MISSING,
                           "no_price_history: no valid adjusted close "
                           f"(finite, >= {PRICE_FLOOR:g} rial) exists for "
                           "this security up to as_of")
        elif f.age_days > STALE_DAYS:
            shared_fail = (
                RAW.STATUS_INVALID,
                f"price_stale: last trade is {f.age_days} days before as_of "
                f"(policy {STALE_DAYS} days) — momentum, liquidity and "
                "volatility on a months-old price are not a current entry "
                "condition; the halt is marked, not hidden")

        # ---- momentum_6m_rel / momentum_3m_rel ---------------------------
        for fid in ("momentum_6m_rel", "momentum_3m_rel"):
            if shared_fail is not None:
                recs[fid] = _record(
                    fid, raw_value=None, status=shared_fail[0],
                    reason=shared_fail[1], warnings=[], history=hist,
                    window=dict(f.bases.get(fid) or {}),
                    available_at=f.available_at)
                continue
            base = f.bases[fid]
            tag = "6" if "6m" in fid else "3"
            if base["stock_return"] is None:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_MISSING,
                    reason=f"insufficient_history_{tag}m: no adjusted close "
                           f"on/before the window reference {base['ref_date']}"
                           " — a shorter history is never relabeled as a "
                           "full-window return",
                    warnings=[], history=hist, window=dict(base),
                    available_at=f.available_at)
                continue
            gaps = _gap_warnings({fid: f.chains[fid]})
            if gaps:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_INVALID,
                    reason="suspected_unadjusted_gap_in_window: the return "
                           "chain contains a move no continuous TSE session "
                           "can produce — the momentum value is refused, "
                           "never scored",
                    warnings=gaps, history=hist, window=dict(base),
                    available_at=f.available_at)
                continue
            bench = benchmarks[fid]
            if bench is None:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_MISSING,
                    reason="market_benchmark_unavailable: no valid "
                           "population return exists to difference against",
                    warnings=[], history=hist, window=dict(base),
                    available_at=f.available_at)
                continue
            rel = base["stock_return"] - bench["mean"]
            recs[fid] = _record(
                fid, raw_value=rel, status=RAW.STATUS_VALID,
                reason=f"valid: stock {tag}-month adjusted return minus the "
                       "equal-weight market return of the valid population",
                warnings=[], history=hist,
                window={**dict(base), "benchmark": bench["mean"],
                        "benchmark_n": bench["n"],
                        "benchmark_kind": "equal_weight_market"},
                available_at=f.available_at)

        # ---- relative_strength_6m_sector ---------------------------------
        fid = "relative_strength_6m_sector"
        base = dict(f.bases.get(fid) or {})
        if shared_fail is not None:
            recs[fid] = _record(
                fid, raw_value=None, status=shared_fail[0],
                reason=shared_fail[1], warnings=[], history=hist,
                window=base, available_at=f.available_at)
        elif base.get("stock_return") is None:
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_MISSING,
                reason="insufficient_history_6m: no adjusted close "
                       f"on/before the window reference {base.get('ref_date')}",
                warnings=[], history=hist, window=base,
                available_at=f.available_at)
        elif _gap_warnings({fid: f.chains[fid]}):
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_INVALID,
                reason="suspected_unadjusted_gap_in_window: the return "
                       "chain contains a move no continuous TSE session can "
                       "produce — the value is refused, never scored",
                warnings=_gap_warnings({fid: f.chains[fid]}),
                history=hist, window=base, available_at=f.available_at)
        else:
            ind = ((company_meta or {}).get(cid) or {}).get("industry")
            ind = ind.strip() if isinstance(ind, str) and ind.strip() else None
            bench = ind_bench.get(ind) if ind is not None else None
            if ind is None:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                    reason="industry_unclassified: relative strength needs "
                           "an industry group; none is mapped for this "
                           "company",
                    warnings=[], history=hist, window=base,
                    available_at=f.available_at)
            elif bench is None:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                    reason=f"insufficient_sector_benchmark: fewer than "
                           f"{SECTOR_BENCH_MIN_MEMBERS} valid 6-month returns "
                           f"in industry {ind!r} (self included)",
                    warnings=[], history=hist,
                    window={**base, "industry": ind},
                    available_at=f.available_at)
            else:
                recs[fid] = _record(
                    fid, raw_value=base["stock_return"] - bench["mean"],
                    status=RAW.STATUS_VALID,
                    reason="valid: stock 6-month adjusted return minus the "
                           "equal-weight industry mean of the valid "
                           "population",
                    warnings=[], history=hist,
                    window={**base, "industry": ind,
                            "benchmark": bench["mean"],
                            "benchmark_n": bench["n"],
                            "benchmark_kind": "equal_weight_industry"},
                    available_at=f.available_at)

        # ---- liquidity ----------------------------------------------------
        fid = "liquidity"
        liq = f.liq
        if shared_fail is not None:
            recs[fid] = _record(
                fid, raw_value=None, status=shared_fail[0],
                reason=shared_fail[1], warnings=[], history=hist,
                window={"n_sessions": liq.get("n_sessions"),
                        "span_days": liq.get("span_days")},
                available_at=f.available_at)
        elif liq.get("n_valid_tvs", 0) < LIQ_MIN_OBS:
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_MISSING,
                reason=f"insufficient_history_liquidity: fewer than "
                       f"{LIQ_MIN_OBS} trade-value observations among the "
                       f"last {LIQ_WINDOW_OBS} sessions",
                warnings=[], history=hist,
                window={"n_sessions": liq.get("n_sessions"),
                        "n_valid_tvs": liq.get("n_valid_tvs"),
                        "n_no_trade": liq.get("n_no_trade"),
                        "n_missing": liq.get("n_missing"),
                        "span_days": liq.get("span_days")},
                available_at=f.available_at)
        elif (liq.get("span_days") or 0) > WINDOW_MAX_SPAN_DAYS:
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_INVALID,
                reason=f"window_span_too_long: the last "
                       f"{liq['n_sessions']} sessions span "
                       f"{liq['span_days']} days — not a 30-session "
                       "liquidity reading (halt/no-trade gaps)",
                warnings=[], history=hist,
                window={"n_sessions": liq["n_sessions"],
                        "span_days": liq["span_days"]},
                available_at=f.available_at)
        else:
            mean_tv = math.fsum(liq["tvs"]) / len(liq["tvs"])
            recs[fid] = _record(
                fid, raw_value=mean_tv, status=RAW.STATUS_VALID,
                reason="valid: mean trade value over the last 30 "
                       "deduplicated sessions (rial)",
                warnings=[f"liquidity_window_composition: "
                          f"{liq['n_no_trade']} no-trade sessions (zero "
                          f"value) and {liq['n_missing']} missing-value "
                          "sessions inside the window — counted, never "
                          "fabricated"],
                history=hist,
                window={"n_sessions": liq["n_sessions"],
                        "n_valid_tvs": liq["n_valid_tvs"],
                        "n_no_trade": liq["n_no_trade"],
                        "n_missing": liq["n_missing"],
                        "span_days": liq["span_days"]},
                available_at=f.available_at)

        # ---- low_volatility ------------------------------------------------
        fid = "low_volatility"
        vol = f.vol
        vol_win = {"n_returns": vol.get("n_returns"),
                   "span_days": vol.get("span_days")}
        if shared_fail is not None:
            recs[fid] = _record(
                fid, raw_value=None, status=shared_fail[0],
                reason=shared_fail[1], warnings=[], history=hist,
                window=vol_win, available_at=f.available_at)
        elif vol.get("n_returns", 0) < VOL_MIN_RETURNS:
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_MISSING,
                reason=f"insufficient_history_volatility: fewer than "
                       f"{VOL_MIN_RETURNS} daily returns among the last "
                       f"{VOL_WINDOW_CLOSES} closes — a '30-day' stdev "
                       "needs a real sample",
                warnings=[], history=hist, window=vol_win,
                available_at=f.available_at)
        elif (vol.get("span_days") or 0) > WINDOW_MAX_SPAN_DAYS:
            recs[fid] = _record(
                fid, raw_value=None, status=RAW.STATUS_INVALID,
                reason=f"window_span_too_long: the volatility window spans "
                       f"{vol['span_days']} calendar days — halts and gaps "
                       "make it not a 30-day reading",
                warnings=[], history=hist, window=vol_win,
                available_at=f.available_at)
        else:
            gaps = [g for g in _gap_warnings({fid: vol["returns"]})]
            if gaps:
                recs[fid] = _record(
                    fid, raw_value=None, status=RAW.STATUS_INVALID,
                    reason="suspected_unadjusted_gap_in_window: a move no "
                           "continuous TSE session can produce sits inside "
                           "the volatility window — the stdev would measure "
                           "the adjustment, not the market",
                    warnings=gaps, history=hist, window=vol_win,
                    available_at=f.available_at)
            else:
                rets = [r for _d1, _d2, r in vol["returns"]]
                sd = statistics.stdev(rets)
                recs[fid] = _record(
                    fid, raw_value=sd, status=RAW.STATUS_VALID,
                    reason="valid: sample stdev of daily adjusted-close "
                           "returns over the volatility window (lower is "
                           "better)",
                    warnings=[], history=hist, window=vol_win,
                    available_at=f.available_at)

        out[cid] = recs
    return out
