"""Cross-sectional normalization (percentile ranking) for Score v2 T factors.

Step 2-D-1 — timing normalization ONLY. It turns the validated raw records
of score_v2_t_raw.build_t_raw() into comparable cross-sectional percentiles
for the five READY timing factors. It does NOT weight factors, does NOT
produce a T score, and knows nothing about Q, V, Confidence or the Risk Gate.

Direction contract: directions are read live from config
V2_QVT_FACTORS[...]["direction"] per factor — momentum_6m_rel /
momentum_3m_rel / relative_strength_6m_sector / liquidity are "higher"
is better (the strongest company gets the highest percentile),
low_volatility is "lower" is better (the calmest company gets the highest
percentile). midrank is called with higher_is_better=direction=="higher",
so the mapping raw -> percentile is inverted exactly once, here.

Reuse contract (identical to score_v2_value_normalize, sanctioned reuse of
the tested statistical machinery — no algorithm is reinvented):
  * SN.RankPolicy          the SAME thresholds object (family_min_n=10 ->
                           insufficient_peers; winsor_min_n=20 -> P1/P99
                           bounds; the three-zone sector policy)
  * SN._winsor_bounds      the parametric P1/P99 winsor with V4's min-sample
                           guard, one consistent transform per family
                           population, reused for the sector ranks
  * SN._sector_weight      V4's SECTOR_BLEND_DECAY form reparametrized to the
                           three-zone policy
  * S4.midrank             the tested V4 midrank percentile engine
Comparison-population doctrine is IDENTICAL to Q and V:
  * only economically VALID raw values enter a population; missing /
    invalid / not_applicable never do; exclusions stay visible
  * model families never mix — general ranks against general, bank against
    bank, insurance against insurance, investment against investment
  * unknown industry joins no sector population (family rank only, warning)
  * real zeros are values (an exact-zero relative return is information);
    non-finite eligible values are excluded under "non_finite" before they
    can reach percentile or winsor math
  * a family population below family_min_n yields insufficient_peers — no
    percentile at all instead of a seemingly precise rank
PIT policies are the same two (current_exploratory / historical_strict):
T records are "collected_at_bounded" (collection-time evidence, no
per-observation source_ref in the store), so historical_strict refuses them
ALL (NR_PIT_STRICT, no backtest claim) and exploratory ranks them with an
explicit exploratory-only warning — the defense-in-depth publication guard
re-checks every eligible value's available_at against as_of in BOTH
policies.

Pure and deterministic: in-memory inputs only, no database, no engine, no
clock; identical inputs in any company order produce identical output.
"""

from __future__ import annotations

import math

import score_v2_config as CFG2
import score_v2_normalize as SN
import score_v2_raw as RAW
import score_v2_t_raw as TRW
import score_v4 as S4

__all__ = ["normalize_t_cross_section", "RankPolicy", "STAGE"]

STAGE = "t_normalize_cross_section"
SCORE_VERSION = CFG2.SCORE_VERSION


def _collect_units(raw_by_company: dict) -> dict:
    """(fid) -> {"eligible": {cid: entry}, "excluded": {status: count}}

    entry = {"value", "pit_status", "available_at", "warnings"} — the same
    shape the Q/V normalization collects. Non-finite valid values are
    excluded under "non_finite" (defense in depth).
    """
    units: dict = {}
    for cid in sorted(raw_by_company):
        for fid in sorted(raw_by_company[cid]):
            if fid not in TRW.IN_SCOPE_T_FACTORS:
                continue
            rec = raw_by_company[cid][fid]
            unit = units.setdefault(fid, {"eligible": {}, "excluded": {}})
            if rec["status"] == RAW.STATUS_VALID:
                value = float(rec["raw_value"])
                if not math.isfinite(value):
                    unit["excluded"]["non_finite"] = \
                        unit["excluded"].get("non_finite", 0) + 1
                    continue
                unit["eligible"][cid] = {
                    "value": value,
                    "pit_status": rec["pit_status"],
                    "available_at": rec.get("available_at"),
                    "warnings": list(rec["warnings"]),
                }
            else:
                unit["excluded"][rec["status"]] = \
                    unit["excluded"].get(rec["status"], 0) + 1
    return units


def normalize_t_cross_section(raw_by_company: dict,
                              company_meta: dict,
                              *,
                              as_of=None,
                              pit_policy: str = SN.PIT_CURRENT_EXPLORATORY,
                              policy: SN.RankPolicy | None = None) -> dict:
    """Rank validated raw T factors cross-sectionally, industry-relative,
    direction per config (higher for momentum/liquidity, lower for
    low_volatility).

    raw_by_company : output of score_v2_t_raw.build_t_raw
    company_meta   : {company_id: {"model_family", "industry"}}
    as_of          : evaluation date; REQUIRED for historical_strict
    pit_policy     : "current_exploratory" | "historical_strict"
    policy         : optional RankPolicy override

    Returns {"score_version", "stage", "pit_policy", "as_of", "policy",
             "records", "factors", "populations"} with the same record /
             factor / population shapes as the Q and V normalizations.
    """
    pol = policy if policy is not None else SN.RankPolicy()
    if pit_policy not in SN.PIT_POLICIES:
        raise ValueError(f"unknown pit_policy {pit_policy!r}; "
                         f"expected one of {SN.PIT_POLICIES}")
    if pit_policy == SN.PIT_HISTORICAL_STRICT and as_of is None:
        raise ValueError(
            "historical_strict requires an explicit as_of evaluation date")
    missing_meta = sorted(cid for cid in raw_by_company
                          if cid not in company_meta)
    if missing_meta:
        raise ValueError(f"company_meta missing for companies: {missing_meta}")
    for fid in TRW.IN_SCOPE_T_FACTORS:
        spec = CFG2.V2_QVT_FACTORS.get(fid)
        if spec is None or spec["axis"] != "timing":
            raise ValueError(f"factor {fid!r} is not a timing factor in "
                             "config — refuse to rank an unknown factor")
        if spec["direction"] not in ("higher", "lower"):
            raise ValueError(f"factor {fid!r}: config direction "
                             f"{spec['direction']!r} is not rankable")

    meta: dict = {}
    for cid, mm in company_meta.items():
        fam = (mm or {}).get("model_family")
        if fam not in CFG2.FAMILIES:
            raise ValueError(f"{cid}: unknown model_family {fam!r}")
        ind = (mm or {}).get("industry")
        ind = ind.strip() if isinstance(ind, str) and ind.strip() else None
        meta[cid] = (fam, ind)

    strict = pit_policy == SN.PIT_HISTORICAL_STRICT
    units = _collect_units(raw_by_company)

    records: list = []
    unit_rank: dict = {}
    populations: dict = {}

    for fid in sorted(units):
        unit = units[fid]
        higher = CFG2.V2_QVT_FACTORS[fid]["direction"] == "higher"

        def _late(e) -> bool:
            return as_of is not None and \
                RAW._ts_after(e["available_at"], as_of) is True

        def _attestable(e) -> bool:
            return e["pit_status"] == RAW.PIT_VERIFIED and \
                RAW._ts_after(e["available_at"], as_of) is False

        if strict:
            pool = {cid: e for cid, e in unit["eligible"].items()
                    if _attestable(e)}
        else:
            pool = {cid: e for cid, e in unit["eligible"].items()
                    if not _late(e)}

        fam_members: dict = {}
        for cid in sorted(pool):
            fam_members.setdefault(meta[cid][0], []).append(cid)

        unit_pops = {"factor_id": fid, "families": {},
                     "excluded": dict(sorted(unit["excluded"].items()))}
        if strict:
            unit_pops["excluded_pit_strict"] = sum(
                1 for e in unit["eligible"].values()
                if e["pit_status"] != RAW.PIT_VERIFIED)
        if as_of is not None:
            unit_pops["excluded_after_as_of"] = sum(
                1 for e in unit["eligible"].values()
                if _late(e) and (not strict
                                 or e["pit_status"] == RAW.PIT_VERIFIED))

        fam_values: dict = {}
        fam_pct: dict = {}
        fam_winsor: dict = {}
        sector_values: dict = {}
        for fam in sorted(fam_members):
            cids = fam_members[fam]
            raw_vals = {cid: pool[cid]["value"] for cid in cids}
            bounds = SN._winsor_bounds(raw_vals.values(), pol)
            norm = {cid: (v if bounds is None
                          else min(max(v, bounds[0]), bounds[1]))
                    for cid, v in raw_vals.items()}
            fam_values[fam] = norm
            fam_winsor[fam] = bounds
            fam_pct[fam] = S4.midrank(norm, higher)

            by_ind: dict = {}
            for cid in cids:
                by_ind.setdefault(meta[cid][1], []).append(cid)
            sectors = {}
            for ind in sorted(by_ind, key=lambda x: (x is None, x or "")):
                if ind is None:
                    continue
                sectors[f"family:{fam}|industry:{ind}"] = {
                    "n_valid": len(by_ind[ind])}
                sector_values[(fam, ind)] = {cid: norm[cid]
                                             for cid in by_ind[ind]}
            unit_pops["families"][fam] = {
                "n_valid": len(cids),
                "winsor": {
                    "applied": bounds is not None,
                    "low": None if bounds is None else bounds[0],
                    "high": None if bounds is None else bounds[1],
                    "n": len(cids),
                    "min_n": pol.winsor_min_n,
                    "low_q": pol.winsor_low_q,
                    "high_q": pol.winsor_high_q,
                },
                "sectors": sectors,
            }
        populations[fid] = unit_pops

        for cid in sorted(unit["eligible"]):
            fam, ind = meta[cid]
            entry = unit["eligible"][cid]
            fam_n = len(fam_values.get(fam, {}))
            sector_n = (len(sector_values[(fam, ind)])
                        if ind is not None and (fam, ind) in sector_values
                        else None)
            warnings = list(entry["warnings"])
            null_reasons: dict = {}
            weight = 0.0
            sec_p = None
            comb = None

            if strict and entry["pit_status"] != RAW.PIT_VERIFIED:
                status = SN.NR_PIT_STRICT
                fam_p = None
                null_reasons = {
                    key: "pit_not_verified_historical_strict"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            elif _late(entry):
                status = SN.NR_AFTER_AS_OF
                fam_p = None
                null_reasons = {
                    key: "collected_after_as_of"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
                warnings.append(
                    "collected_after_as_of: the record's latest market "
                    "collection timestamp is after this layer's as_of — "
                    "excluded from ranks, peer populations and winsor "
                    "bounds in every policy")
            elif strict and RAW._ts_after(entry["available_at"],
                                          as_of) is None:
                status = SN.NR_PIT_STRICT
                fam_p = None
                null_reasons = {
                    key: "pit_not_verified_historical_strict"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            elif fam_n < pol.family_min_n:
                status = SN.NR_INSUFFICIENT_PEERS
                fam_p = None
                null_reasons = {
                    key: "insufficient_peers"
                    for key in ("percentile_market_family",
                                "percentile_sector",
                                "percentile_combined")}
            else:
                status = SN.NR_RANKED
                fam_p = fam_pct[fam][cid]
                if ind is None:
                    warnings.append(
                        "industry_unknown: no industry group supplied — the "
                        "company is ranked against its model family only and "
                        "joins no sector population")
                    null_reasons["percentile_sector"] = "industry_unknown"
                elif sector_n < pol.sector_small_max:
                    null_reasons["percentile_sector"] = "sector_too_small"
                else:
                    sec_p = S4.midrank(sector_values[(fam, ind)],
                                       higher)[cid]
                    weight = SN._sector_weight(sector_n, pol)
                if sec_p is not None and weight > 0.0:
                    comb = weight * sec_p + (1.0 - weight) * fam_p
                else:
                    comb = fam_p
                if (pit_policy == SN.PIT_CURRENT_EXPLORATORY
                        and entry["pit_status"] != RAW.PIT_VERIFIED):
                    warnings.append(
                        "pit_collected_at_only: ranked on collection-time-"
                        "bounded market data without per-observation source "
                        "attribution — exploratory only, never "
                        "backtest-valid")

            peer_group = (f"family:{fam}|industry:{ind}"
                          if status == SN.NR_RANKED and weight > 0.0
                          else f"family:{fam}")
            records.append({
                "company_id": cid,
                "factor_id": fid,
                "raw_value": entry["value"],
                "normalized_input": fam_values.get(fam, {}).get(cid),
                "percentile_market_family": fam_p,
                "percentile_sector": sec_p,
                "percentile_combined": comb,
                "direction": CFG2.V2_QVT_FACTORS[fid]["direction"],
                "peer_group": peer_group,
                "n_valid_market_family": fam_n,
                "n_valid_sector": sector_n,
                "effective_sector_weight": weight,
                "validation_status": RAW.STATUS_VALID,
                "pit_status": entry["pit_status"],
                "warnings": warnings,
                "normalization_status": status,
                "pit_policy": pit_policy,
                "null_reasons": null_reasons,
                "winsor_applied": fam_winsor.get(fam) is not None,
            })
            unit_rank[(cid, fid)] = (status, comb)

    records.sort(key=lambda r: (r["company_id"], r["factor_id"]))

    factors: dict = {}
    for cid in sorted(raw_by_company):
        factors[cid] = {}
        for fid in sorted(raw_by_company[cid]):
            if fid not in TRW.IN_SCOPE_T_FACTORS:
                continue
            rec = raw_by_company[cid][fid]
            if rec["status"] == RAW.STATUS_VALID:
                st, pc = unit_rank.get((cid, fid),
                                       (SN.NR_NON_FINITE, None))
            else:
                st, pc = f"not_ranked_raw_{rec['status']}", None
            factors[cid][fid] = {
                "company_id": cid,
                "factor_id": fid,
                "normalization_status": st,
                "percentile_combined": pc,
                "raw_status": rec["status"],
                "raw_value": rec["raw_value"],
                "validation_reason": rec["validation_reason"],
                "warnings": list(rec["warnings"]),
                "market": rec["market"],
            }

    return {
        "score_version": SCORE_VERSION,
        "stage": STAGE,
        "pit_policy": pit_policy,
        "as_of": as_of,
        "policy": pol.to_dict(),
        "records": records,
        "factors": factors,
        "populations": populations,
    }
