"""Raw V (valuation) factor extraction and validation for Score v2 — step 2-J-1.

Extraction/validation layer ONLY for the three READY valuation factors
(pe, pb, ps). No scoring, no weights, no percentiles, no ranking: those
belong to the normalization layer and the observed-V pilot.

Construction contract (score_v2_config.V2_QVT_FACTORS + VALUATION_DIRECT.md):

    market_cap = PIT price x PIT shares_outstanding          (rial)
    pe         = market_cap / net_profit_ttm    (only net_profit_ttm > 0)
    pb         = market_cap / total_equity      (only equity > 0)
    ps         = market_cap / revenue_ttm       (only revenue_ttm > 0)

Each ratio is computed from its OWN economic quantity — the identities
PS = PE x net_margin and PB = PE x ROE are never used (VALUATION_DIRECT.md:
one bad PE would contaminate all three). All inputs arrive through the
caller: the ``metrics`` dict of compute_metrics.Engine.compute() (engine-
resolved TTM primitives and shares, never recomputed from statements here),
a ``market`` channel with the PIT price row and share-snapshot evidence
(resolved by the pilot from the engine's OWN loaded rows — no new SQL), and
``equity_by_company`` resolved by the pilot from the engine's report_index
latest cell (exactly the cell the engine's own P/B reads). This module stays
pure and deterministic: no database, no engine, no clock.

Financial gates (mission 2-J-1 section 4 — a ratio is never allowed to read
as excellent cheapness from a broken or negative input):

  pe   net_profit_ttm missing            -> missing
       net_profit_ttm == 0               -> not_applicable (undefined)
       net_profit_ttm < 0                -> not_applicable + loss_maker warning
       pe computed and > PE_ANOMALY_BAND -> stays VALID + above-band warning
       (a loss-making company can NEVER produce a negative "cheap" P/E
       because the ratio is not computed at all)
  pb   total_equity missing              -> missing
       total_equity == 0                 -> not_applicable
       total_equity < 0                  -> not_applicable + negative_equity
                                            warning (never "excellent" value)
       pb computed and > PB_ANOMALY_BAND -> stays VALID + above-band warning
  ps   revenue_ttm missing               -> missing
       revenue_ttm < 0                   -> invalid (negative revenue is a
                                            definite data error, Q doctrine)
       revenue_ttm == 0                  -> not_applicable
       family != general                 -> not_applicable (config: "P/S —
                                            فقط خانواده general؛ برای
                                            بانک/بیمه بی‌معناست")
       ps computed and > PS_ANOMALY_BAND -> stays VALID + above-band warning

Anomaly bands reuse the V1 engine's own validity bands (compute_metrics
rank_and_score: PE <= 60, PB <= 30, PS <= 100) — no new cutoffs invented.
A value beyond a band stays VALID with a recorded warning (real but unusual
economics are never deleted at the raw layer); winsorization and later
layers decide. Non-finite computed results are invalid, never kept.

Market-data gates (mission 2-J-1 section 3 — price/share trust):
  * no price row                      -> missing
  * price <= 0 or non-finite          -> invalid (a zero/negative price is
     never a valid trade price)
  * price trade date after as_of      -> invalid (lookahead guard; defense
     in depth — the engine's own collected_at filter should prevent it)
  * no PIT share snapshot             -> missing (no share count is ever
     guessed from capital or nominal value, VALUATION_DIRECT.md section 1)
  * shares <= 0 or non-finite         -> invalid
  * share snapshot older than the price trade date -> the ratio stays
     computable with an explicit warning: the store carries NO corporate-
     action evidence, so capital-change consistency between the two dates
     is unprovable and must stay visible, not silent
  * price age over PRICE_STALE_DAYS   -> stays computable with a stale-price
     warning (the last REAL trade is still the last real trade; a halted or
     illiquid symbol is marked, not hidden)
  * balance sheet older than BALANCE_SHEET_STALE_DAYS (one fiscal year)
     before as_of                      -> stays computable with a stale-
     balance-sheet warning

PIT contract: the financial input's publication evidence is checked with
score_v2_raw._metric_pit (the same verified/unverified/after_as_of contract
as Q; verified requires a timestamp AND a non-empty source_ref — the pilot
cannot fabricate source_ref, so exploratory records stay unverified). Market
inputs carry no publication timestamp in the store; their temporal evidence
(price trade date / collection time, share snapshot date, both bounded by
as_of/cutoff at channel build time) is recorded verbatim on every record.

Unit contract: canonical rial throughout (price rial x share count ->
market cap rial; TTM flows and equity canonical rial) — the ratios are
unit-free. Any non-rial canonical value never reaches this layer (the
engine's report_index drops it with an unknown_unit flag).
"""

from __future__ import annotations

import math

import score_v2_raw as RAW

__all__ = [
    "STAGE",
    "IN_SCOPE_V_FACTORS",
    "PE_ANOMALY_BAND",
    "PB_ANOMALY_BAND",
    "PS_ANOMALY_BAND",
    "PRICE_STALE_DAYS",
    "BALANCE_SHEET_STALE_DAYS",
    "build_v_raw",
]

STAGE = "value_raw_extraction"

IN_SCOPE_V_FACTORS = ("pe", "pb", "ps")

# V1 engine's own validity bands (compute_metrics rank_and_score), reused as
# anomaly WARNING bands — beyond a band stays valid, never deleted here.
PE_ANOMALY_BAND = 60.0
PB_ANOMALY_BAND = 30.0
PS_ANOMALY_BAND = 100.0

# Experimental freshness policies (this step's explicit proposal, NOT
# backtest-optimized; declared constants, never hidden magic numbers).
PRICE_STALE_DAYS = 7
BALANCE_SHEET_STALE_DAYS = 366  # one fiscal year

_DEFINITIONS = {"pe": "market_cap / net_profit_ttm",
                "pb": "market_cap / total_equity",
                "ps": "market_cap / revenue_ttm"}


def _bad_number(x) -> bool:
    """Non-finite / non-numeric / bool inputs are definite corruption."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return True
    return not math.isfinite(x)


def _lookahead_guard(rec: dict, pit: dict) -> dict:
    """Q's look-ahead doctrine, mirrored: a VALID ratio whose financial input
    is attributable to a publication after as_of is INVALID for historical
    computation — the value is dropped, the refusal named."""
    if pit["state"] == RAW.PIT_AFTER_AS_OF \
            and rec["status"] == RAW.STATUS_VALID:
        return {**rec, "raw_value": None, "status": RAW.STATUS_INVALID,
                "validation_reason": rec["validation_reason"]
                + "; " + pit["reason"]}
    return rec


def _record(fid: str, *, raw_value, status: str, reason: str, warnings: list,
            market: dict, pit: dict) -> dict:
    return {
        "factor_id": fid,
        "raw_value": raw_value,
        "status": status,
        "validation_reason": reason,
        "warnings": warnings,
        "unit": "ratio",
        "definition": _DEFINITIONS[fid],
        "source_metric": {"pe": "net_profit_ttm", "pb": "total_equity",
                          "ps": "revenue_ttm"}[fid],
        "available_at": pit["available_at"],
        "pit_status": pit["state"],
        "pit_reason": pit["reason"],
        "market": market,
    }


def _market_block(channel: dict) -> dict:
    """Traceability echo of the market inputs behind every factor record —
    recorded verbatim whether or not the ratio could be computed."""
    return {
        "price": channel.get("price"),
        "price_trade_date": str(channel["price_trade_date"])
        if channel.get("price_trade_date") is not None else None,
        "price_collected_at": str(channel["price_collected_at"])
        if channel.get("price_collected_at") is not None else None,
        "price_age_days": channel.get("price_age_days"),
        "shares": channel.get("shares"),
        "share_source": channel.get("share_source"),
        "share_source_date": str(channel["share_source_date"])
        if channel.get("share_source_date") is not None else None,
        "share_price_gap_days": channel.get("share_price_gap_days"),
    }


def _market_gate(channel: dict) -> tuple:
    """(market_cap, gate_fields) — the shared price/shares gate.

    Success: (market_cap, {"status": None, "reason": None, "warnings"})
    where warnings carries the freshness/consistency findings (stale price,
    share snapshot older than the price). Failure: (None, fields) with a
    non-None status naming the exact refusal. Mirrors the engine's own
    construction contract.
    """
    warnings: list = []
    if not channel:
        return None, {"status": RAW.STATUS_MISSING,
                      "reason": "no_pit_market_data: no price row and no "
                                "share snapshot reached the channel",
                      "warnings": warnings}
    price = channel.get("price")
    if price is None:
        return None, {"status": RAW.STATUS_MISSING,
                      "reason": "no_price_data: the company's security has "
                                "no PIT price observation",
                      "warnings": warnings}
    if _bad_number(price):
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "non_finite_price: definite data corruption",
                      "warnings": warnings}
    if price <= 0:
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "nonpositive_price: a zero or negative price "
                                "is never a valid trade price",
                      "warnings": warnings}
    ptd = channel.get("price_trade_date")
    as_of = channel.get("as_of")
    if ptd is not None and as_of is not None and ptd > as_of:
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "price_after_as_of: a future price must "
                                "never enter a valuation (lookahead guard)",
                      "warnings": warnings}
    age = channel.get("price_age_days")
    if age is not None and age > PRICE_STALE_DAYS:
        warnings.append(
            f"stale_price: latest trade is {age} days before as_of "
            f"(freshness policy {PRICE_STALE_DAYS} days) — the last real "
            "trade, marked not hidden")
    shares = channel.get("shares")
    if shares is None:
        return None, {"status": RAW.STATUS_MISSING,
                      "reason": "no_pit_share_snapshot: no share count may be "
                                "guessed from capital or nominal value",
                      "warnings": warnings}
    if _bad_number(shares):
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "non_finite_shares: definite data corruption",
                      "warnings": warnings}
    if shares <= 0:
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "nonpositive_shares: a share count must be "
                                "positive",
                      "warnings": warnings}
    gap = channel.get("share_price_gap_days")
    if gap is not None and gap > 0:
        warnings.append(
            f"share_snapshot_older_than_price: share snapshot dates {gap} "
            "days before the price trade date and the store carries no "
            "corporate-action evidence — capital-change consistency between "
            "the two dates is unprovable")
    mcap = price * shares
    if not math.isfinite(mcap) or mcap <= 0:
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "non_finite_or_nonpositive_market_cap: "
                                "definite computation error",
                      "warnings": warnings}
    return mcap, {"status": None, "reason": None, "warnings": warnings}


def _sentinel_warnings(net_profit_sentinel: dict | None, cid: str) -> list:
    """Legacy-sentinel audit of the net_profit legs behind the resolved TTM
    (mission: an inflated legacy profit must not enter a P/E unwarned)."""
    legs = (net_profit_sentinel or {}).get(cid) or []
    if not legs:
        return []
    return [f"net_profit_ttm_consumes_legacy_sentinel_cell: exact "
            f"±1e6/±1e8 rial sentinel leg(s) {', '.join(sorted(legs))} feed "
            "the resolved net profit TTM — the ratio stays computable but "
            "the inflated-profit risk must stay visible"]


def _equity_gate(equity_by_company: dict | None, cid: str,
                 as_of) -> tuple:
    """(equity, failure_fields) for P/B — the balance-sheet stock gate.

    failure_fields with a non-None status refuse the ratio outright; the
    stale-balance-sheet path returns the equity WITH warning-only fields so
    the ratio stays computable and the staleness stays visible.
    """
    eq_row = (equity_by_company or {}).get(cid) or {}
    eq = eq_row.get("equity")
    if eq is None:
        return None, {"status": RAW.STATUS_MISSING,
                      "reason": "total_equity_missing: no total_equity "
                                "order-1 fact in the company's latest PIT "
                                "report cell",
                      "warnings": []}
    if _bad_number(eq):
        return None, {"status": RAW.STATUS_INVALID,
                      "reason": "non_finite_equity: definite data corruption",
                      "warnings": []}
    if eq == 0:
        return None, {"status": RAW.STATUS_NOT_APPLICABLE,
                      "reason": "zero_total_equity: P/B is undefined on a "
                                "zero book value",
                      "warnings": []}
    if eq < 0:
        return None, {"status": RAW.STATUS_NOT_APPLICABLE,
                      "reason": "negative_total_equity: P/B on a negative "
                                "book value must never read as cheapness",
                      "warnings": ["negative_equity: book value below zero — "
                                   "distressed or restated balance sheet"]}
    ped = eq_row.get("period_end_date")
    if ped is not None and as_of is not None:
        age = (as_of - ped).days
        if age > BALANCE_SHEET_STALE_DAYS:
            return eq, {"status": None, "reason": None, "warnings": [
                f"stale_balance_sheet: total_equity period end is {age} "
                f"days before as_of (over one fiscal year) — book value and "
                "price are far apart in time"]}
    return eq, None


def build_v_raw(metrics: dict,
                company_meta: dict,
                *,
                market: dict | None = None,
                equity_by_company: dict | None = None,
                provenance: dict | None = None,
                net_profit_sentinel: dict | None = None,
                as_of=None,
                cutoff=None) -> dict:
    """Raw V records for every company in ``metrics``.

    metrics                compute_metrics.Engine.compute() output
    company_meta           {cid: {"model_family", ...}} (family gate for ps)
    market                 {cid: price/share channel} built by the pilot from
                           the engine's OWN rows (no new SQL); the pilot pins
                           each channel's ``as_of`` (or this argument does)
    equity_by_company      {cid: {"equity", "period_end_date"}} resolved by
                           the pilot from the engine's latest report cell
    provenance             {cid: {"available_at", ...}} statement publication
                           evidence (same dict the Q raw layer receives)
    net_profit_sentinel    {cid: [leg, ...]} — legacy-sentinel net_profit legs
                           consumed by the company's current TTM resolution
    as_of                  evaluation DATE (market lookahead + staleness
                           gates)
    cutoff                 publication cutoff DATETIME for the financial
                           inputs' PIT check (the Q layer's as_of contract);
                           falls back to as_of when omitted
    """
    pit_base = cutoff if cutoff is not None else as_of
    out: dict = {}
    for cid in sorted(metrics):
        m = metrics[cid] or {}
        ch = dict((market or {}).get(cid) or {})
        if as_of is not None and ch:
            ch.setdefault("as_of", as_of)
        mkt = _market_block(ch)
        prov = (provenance or {}).get(cid)
        fam = ((company_meta or {}).get(cid) or {}).get("model_family")

        mcap, mgate = _market_gate(ch)
        gate_failed = mgate["status"] is not None
        gate_warnings = list(mgate["warnings"])
        recs: dict = {}

        # ---- P/E: market cap over a strictly positive net profit TTM -------
        pit_pe = RAW._metric_pit(prov, "net_profit", pit_base)
        if gate_failed:
            recs["pe"] = _record("pe", raw_value=None, status=mgate["status"],
                                 reason=mgate["reason"],
                                 warnings=gate_warnings,
                                 market=mkt, pit=pit_pe)
        else:
            np_ttm = m.get("net_profit_ttm")
            w_pe = gate_warnings + _sentinel_warnings(net_profit_sentinel, cid)
            if np_ttm is None:
                recs["pe"] = _record(
                    "pe", raw_value=None, status=RAW.STATUS_MISSING,
                    reason="net_profit_ttm_missing: the engine could not "
                           "resolve a same-window TTM net profit",
                    warnings=w_pe, market=mkt, pit=pit_pe)
            elif _bad_number(np_ttm):
                recs["pe"] = _record(
                    "pe", raw_value=None, status=RAW.STATUS_INVALID,
                    reason="non_finite_net_profit_ttm: definite data "
                           "corruption",
                    warnings=w_pe, market=mkt, pit=pit_pe)
            elif np_ttm == 0:
                recs["pe"] = _record(
                    "pe", raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                    reason="zero_net_profit_ttm: P/E is undefined on a zero "
                           "profit",
                    warnings=w_pe, market=mkt, pit=pit_pe)
            elif np_ttm < 0:
                w_pe = w_pe + ["loss_maker: net_profit_ttm is negative — P/E "
                               "is NOT computed; a loss maker can never read "
                               "as cheaply valued"]
                recs["pe"] = _record(
                    "pe", raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                    reason="negative_net_profit_ttm: loss-making company — "
                           "no P/E is formed",
                    warnings=w_pe, market=mkt, pit=pit_pe)
            else:
                pe = mcap / np_ttm
                if not math.isfinite(pe):
                    recs["pe"] = _record(
                        "pe", raw_value=None, status=RAW.STATUS_INVALID,
                        reason="non_finite_result: pe computed to a "
                               "non-finite number — definite computation "
                               "error, never kept as valid data",
                        warnings=w_pe, market=mkt, pit=pit_pe)
                else:
                    if pe > PE_ANOMALY_BAND:
                        w_pe = w_pe + [
                            f"pe_above_v1_valid_band: pe {pe:.1f} exceeds the "
                            f"V1 engine's own validity band (>"
                            f"{PE_ANOMALY_BAND:g}) — kept valid for "
                            "winsorization, warned here"]
                    recs["pe"] = _record(
                        "pe", raw_value=pe, status=RAW.STATUS_VALID,
                        reason="valid: market cap over a strictly positive "
                               "TTM net profit",
                        warnings=w_pe, market=mkt, pit=pit_pe)

        # ---- P/B: market cap over a strictly positive book value -----------
        pit_pb = RAW._metric_pit(prov, "total_equity", pit_base)
        if gate_failed:
            recs["pb"] = _record("pb", raw_value=None, status=mgate["status"],
                                 reason=mgate["reason"],
                                 warnings=gate_warnings,
                                 market=mkt, pit=pit_pb)
        else:
            eq, efail = _equity_gate(equity_by_company, cid, as_of)
            w_pb = gate_warnings + (list(efail["warnings"]) if efail else [])
            if efail is not None and efail.get("status") is not None:
                recs["pb"] = _record("pb", raw_value=None,
                                     status=efail["status"],
                                     reason=efail["reason"], warnings=w_pb,
                                     market=mkt, pit=pit_pb)
            elif eq is None:
                recs["pb"] = _record(
                    "pb", raw_value=None, status=RAW.STATUS_MISSING,
                    reason="total_equity_missing: no book value for this "
                           "company",
                    warnings=w_pb, market=mkt, pit=pit_pb)
            else:
                pb = mcap / eq
                if not math.isfinite(pb):
                    recs["pb"] = _record(
                        "pb", raw_value=None, status=RAW.STATUS_INVALID,
                        reason="non_finite_result: pb computed to a "
                               "non-finite number — definite computation "
                               "error, never kept as valid data",
                        warnings=w_pb, market=mkt, pit=pit_pb)
                else:
                    if pb > PB_ANOMALY_BAND:
                        w_pb = w_pb + [
                            f"pb_above_v1_valid_band: pb {pb:.1f} exceeds the "
                            f"V1 engine's own validity band (>"
                            f"{PB_ANOMALY_BAND:g}) — kept valid for "
                            "winsorization, warned here"]
                    recs["pb"] = _record(
                        "pb", raw_value=pb, status=RAW.STATUS_VALID,
                        reason="valid: market cap over a strictly positive "
                               "book value",
                        warnings=w_pb, market=mkt, pit=pit_pb)

        # ---- P/S: market cap over a strictly positive revenue TTM ----------
        pit_ps = RAW._metric_pit(prov, "revenue", pit_base)
        if gate_failed:
            recs["ps"] = _record("ps", raw_value=None, status=mgate["status"],
                                 reason=mgate["reason"],
                                 warnings=gate_warnings,
                                 market=mkt, pit=pit_ps)
        elif fam != "general":
            recs["ps"] = _record(
                "ps", raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                reason="ps_not_meaningful_for_specialized_family: config "
                       "scopes P/S to the general family (bank/insurance/"
                       "investment sales are not comparable merchandise)",
                warnings=[], market=mkt, pit=pit_ps)
        else:
            rev = m.get("revenue_ttm")
            w_ps: list = list(gate_warnings)
            if rev is None:
                recs["ps"] = _record(
                    "ps", raw_value=None, status=RAW.STATUS_MISSING,
                    reason="revenue_ttm_missing: the engine could not "
                           "resolve a same-window TTM revenue",
                    warnings=w_ps, market=mkt, pit=pit_ps)
            elif _bad_number(rev):
                recs["ps"] = _record(
                    "ps", raw_value=None, status=RAW.STATUS_INVALID,
                    reason="non_finite_revenue_ttm: definite data corruption",
                    warnings=w_ps, market=mkt, pit=pit_ps)
            elif rev < 0:
                recs["ps"] = _record(
                    "ps", raw_value=None, status=RAW.STATUS_INVALID,
                    reason="negative_revenue_ttm: negative revenue is a "
                           "definite data error (Q doctrine), never a ratio",
                    warnings=w_ps, market=mkt, pit=pit_ps)
            elif rev == 0:
                recs["ps"] = _record(
                    "ps", raw_value=None, status=RAW.STATUS_NOT_APPLICABLE,
                    reason="zero_revenue_ttm: P/S is undefined on a zero "
                           "revenue",
                    warnings=w_ps, market=mkt, pit=pit_ps)
            else:
                ps = mcap / rev
                if not math.isfinite(ps):
                    recs["ps"] = _record(
                        "ps", raw_value=None, status=RAW.STATUS_INVALID,
                        reason="non_finite_result: ps computed to a "
                               "non-finite number — definite computation "
                               "error, never kept as valid data",
                        warnings=w_ps, market=mkt, pit=pit_ps)
                else:
                    if ps > PS_ANOMALY_BAND:
                        w_ps = w_ps + [
                            f"ps_above_v1_valid_band: ps {ps:.1f} exceeds the "
                            f"V1 engine's own validity band (>"
                            f"{PS_ANOMALY_BAND:g}) — kept valid for "
                            "winsorization, warned here"]
                    recs["ps"] = _record(
                        "ps", raw_value=ps, status=RAW.STATUS_VALID,
                        reason="valid: market cap over a strictly positive "
                               "TTM revenue",
                        warnings=w_ps, market=mkt, pit=pit_ps)

        for fid in recs:
            pit = {"pe": pit_pe, "pb": pit_pb, "ps": pit_ps}[fid]
            recs[fid] = _lookahead_guard(recs[fid], pit)
        out[cid] = recs
    return out
