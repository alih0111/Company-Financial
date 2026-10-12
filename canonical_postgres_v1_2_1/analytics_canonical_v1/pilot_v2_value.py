"""Observed-V pilot for Score v2 (step 2-J-1) — the first REAL, industry-
relative valuation output. Deliberately NOT a final V:

  * ``v_observed_points`` = Σ (config weight of an available factor × its
    normalized score), computed per company over ITS model family's V weight
    table (general: pe 13 + pb 12 + ps 10 = 35; bank/insurance/investment:
    pe 13 + pb 22 = 35). The axis target is 35, but no missing weight is ever
    redistributed and the points are NEVER divided by covered_weight — an
    incomplete company keeps an incomplete point total, honestly labeled.
  * A missing factor has no score share and is never read as cheap or
    expensive: it contributes nothing and its absence is named.
  * Companies are NEVER ranked by ``v_observed_points`` — coverage differs
    across companies, so a rank would compare different denominators.
  * The relative-cheapness label is exact: ranking pe/pb/ps inside a peer
    family is RELATIVE valuation, never an intrinsic-value claim.
  * There is no valuation_score / v_final / Q+V combination / QVT total
    anywhere in this pilot, and the Q axis output of 2-B-8 is untouched.
  * Data Confidence and the Risk Gate stay independent, not_evaluated.

Weight-table control (mission 2-J-1 section 2): every family's V weights are
read live from score_v2_config.FAMILY_WEIGHTS and must sum exactly to
AXIS_WEIGHTS["valuation"] (35). Any inconsistency raises VWeightInconsistency
and STOPS. The needs_development factors ev_ebit / fcf_yield carry target
weights (6 + 5) in the registry but are in NO family map and are NEVER scored
or redistributed — no automatic surrogate.

Market inputs (mission 2-J-1 section 3) come ONLY from the engine's own
loaded rows: prices from market.price_observations (engine PIT filter), share
counts from the engine's current-share precedence (TSETMC zTitad primary,
BRS vendor fallback; no share count is ever inferred from capital or nominal
value), equity from the engine's own latest report cell. No new SQL, no
guessing; every record carries the price trade date, the share snapshot date
and their gap, so capital-change consistency is visible (the store carries no
corporate-action evidence to prove it).

Q-axis overlap reads the saved 2-B-8 artifact output/v2_q_observed_report.json
(same reproducible snapshot) — never recomputed here, never modified.

Pure aggregation: same doctrine as score_v2_q_observed (step 2-B-6) —
math.fsum over sorted keys, deterministic, no database writes, no clock.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parent.parent / "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402  (read-only metric engine)
import fiscal_calendar as FC  # noqa: E402
import report_chain_ttm as RC  # noqa: E402
import score_v2 as S2  # noqa: E402  (family resolution via V4 mapping)
import score_v2_config as CFG2  # noqa: E402  (read-only weight registry)
import score_v2_normalize as SN  # noqa: E402
import score_v2_value_normalize as VN  # noqa: E402
import score_v2_value_raw as VRW  # noqa: E402
import score_v4 as S4  # noqa: E402  (PIT sector map, SELECT-only)

# pilot_v2_qvt supplies the engine-adjacent helpers reused verbatim (they are
# pure functions over the engine's own data); importing the module runs no
# pipeline (main() is import-guarded).
import pilot_v2_qvt as QP  # noqa: E402

STAGE = "pilot_v2_value_exploratory"
AXIS = "valuation"

DISCLAIMER = (
    "گام ۲-ج-۱ — v_observed_points یک خروجی مشاهده‌شده آزمایشی ارزندگی نسبی است، "
    "نه V کامل از ۳۵ و نه سیگنال خرید. وزن مفقود بازتوزیع نمی‌شود، امتیاز ناقص "
    "بر مبنای پوشش نرمال نمی‌شود، شرکت‌ها بر اساس آن رتبه‌بندی نمی‌شوند و "
    "ارزندگی نسبی ادعای ارزش ذاتی نیست. Data Confidence و Risk Gate مستقل و "
    "فعلاً not_evaluated هستند و هیچ ترکیب Q+V یا امتیاز کل QVT ساخته نمی‌شود."
)

COV_EPS = 1e-12


class VWeightInconsistency(ValueError):
    """A family's V weight table contradicts the config/raw-layer contract —
    aggregation must STOP and the inconsistency be reported, never auto-fixed
    in code."""


def v_weight_table(family: str) -> dict:
    """The family's V-axis weight table, read live from config, with the
    implementation status per factor.

    Raises VWeightInconsistency when the weights do not sum exactly to
    AXIS_WEIGHTS["valuation"], a mapped factor is not a READY valuation
    factor, or a READY valuation factor mapped for this family is missing
    from the raw layer's scope (stale config vs raw contract) — stop, never
    auto-fix.
    """
    if family not in CFG2.FAMILIES:
        raise ValueError(f"unknown family {family!r}; expected one of "
                         f"{CFG2.FAMILIES}")
    fam_map = CFG2.FAMILY_WEIGHTS[family]
    weights = {fid: w for fid, w in fam_map.items()
               if CFG2.V2_QVT_FACTORS[fid]["axis"] == AXIS}

    rows = {}
    for fid in sorted(weights):
        spec = CFG2.V2_QVT_FACTORS[fid]
        if spec["availability"] != CFG2.READY:
            raise VWeightInconsistency(
                f"{fid}: a needs_development factor must never appear in a "
                "family weight map")
        if fid not in VRW.IN_SCOPE_V_FACTORS:
            raise VWeightInconsistency(
                f"{fid}: mapped for {family} but absent from the value raw "
                "layer's scope — aggregation stops (report the "
                "inconsistency, never auto-fix)")
        rows[fid] = {"weight": weights[fid], "essential": spec["essential"],
                     "direction": spec["direction"],
                     "implementation": "implemented",
                     "in_aggregation_scope": True,
                     "aggregation_note": None}

    total = math.fsum(weights[f] for f in sorted(weights))
    target = CFG2.AXIS_WEIGHTS[AXIS]
    if abs(total - target) > 1e-9:
        raise VWeightInconsistency(
            f"{family} V-axis weights sum to {total}, expected {target} — "
            "aggregation stops; weights are recalibrated in config, never "
            "auto-fixed here")

    not_in_map = {fid: {"target_weight": spec["target_weight"],
                        "availability": spec["availability"],
                        "essential": spec["essential"],
                        "note": spec["note"]}
                  for fid, spec in sorted(CFG2.V2_QVT_FACTORS.items())
                  if spec["axis"] == AXIS and fid not in fam_map}
    return {"family": family, "axis": AXIS,
            "target_weight": target,
            "total_weight": total,
            "weights": dict(sorted(weights.items())),
            "rows": rows,
            "factors_not_in_family_map": not_in_map}


def _scored_factor(rollup) -> tuple:
    """(score, kind) when the rollup carries a usable normalized score —
    single ``ranked`` with a finite percentile_combined in [0, 1]. A ranked
    state with an out-of-range or non-finite score is refused loudly."""
    if not isinstance(rollup, dict):
        return None, None
    if rollup.get("normalization_status") != SN.NR_RANKED:
        return None, None
    val = rollup.get("percentile_combined")
    if (isinstance(val, bool) or not isinstance(val, (int, float))
            or not math.isfinite(val) or not 0.0 <= float(val) <= 1.0):
        return None, None
    return float(val), "percentile_combined"


def _no_score_reason(rollup) -> str:
    st = (rollup or {}).get("normalization_status")
    if st is None:
        return "no normalize rollup for this company/factor"
    if st == SN.NR_RANKED:
        return ("score_refused: the rollup claims ranked but its score is "
                "not a finite number in [0, 1]")
    return {
        SN.NR_INSUFFICIENT_PEERS:
            "insufficient_peers: family peer population below family_min_n",
        SN.NR_NON_FINITE: "not_ranked_non_finite",
        SN.NR_PIT_STRICT: "not_ranked_pit_strict",
        SN.NR_AFTER_AS_OF: "published_after_as_of",
        "not_ranked_raw_missing":
            "raw_missing: a valuation input is absent — a missing factor has "
            "no score share, never a zero-performance reading",
        "not_ranked_raw_invalid": "raw_invalid: the raw layer refused the value",
        "not_ranked_raw_not_applicable":
            "raw_not_applicable: economically meaningless for this company",
    }.get(st, f"unranked: {st}")


def _diag_bucket(reason: str) -> str:
    for prefix, bucket in (
            ("insufficient_peers", "insufficient_peers"),
            ("raw_missing", "missing"),
            ("raw_invalid", "invalid"),
            ("raw_not_applicable", "not_applicable"),
            ("score_refused", "score_refused"),
            ("no normalize rollup", "other_refusals")):
        if reason.startswith(prefix):
            return bucket
    return "other_refusals"


def build_v_observed_report(normalize_out: dict,
                            raw_by_company: dict,
                            company_meta: dict,
                            *,
                            symbols: dict | None = None,
                            coverage_threshold: float | None = None,
                            display_limit: int = 24) -> dict:
    """Aggregate the observed-V pilot over every model family.

    Per company (under ITS family's table): per-factor weight / raw value /
    score / contribution, v_observed_points over scored factors only,
    covered / missing weight and coverage_ratio against the 35 target, the
    essential gate (pe and pb), pilot_eligible, and the independent Data
    Confidence / Risk-Gate diagnostics. Companies are never ranked by points.
    """
    thr = (CFG2.SCORING_POLICY["min_axis_coverage"]
           if coverage_threshold is None else float(coverage_threshold))
    if not 0 < thr <= 1:
        raise ValueError(f"coverage_threshold must be in (0, 1], got {thr!r}")

    tables = {fam: v_weight_table(fam) for fam in CFG2.FAMILIES}
    all_rollups = normalize_out.get("factors", {})

    companies: dict = {}
    n_eligible = n_any = n_zero = 0
    valid_by_factor: Counter = Counter()
    scored_by_factor: Counter = Counter()
    refusal_by_factor: dict = {}
    covered_hist: Counter = Counter()

    for cid in sorted(company_meta):
        meta = company_meta[cid] or {}
        fam = meta.get("model_family")
        table = tables[fam]
        weights, rows = table["weights"], table["rows"]
        target = table["target_weight"]
        essentials = sorted(f for f, r in rows.items() if r["essential"])

        rollups = all_rollups.get(cid, {})
        factors: dict = {}
        covered_pairs: list = []
        points_pairs: list = []
        ess_missing: list = []
        diag: Counter = Counter()

        for fid in sorted(weights):
            row = rows[fid]
            ru = rollups.get(fid) or {}
            score, kind = _scored_factor(ru)
            fentry = {"weight": row["weight"],
                      "essential": row["essential"],
                      "direction": row["direction"],
                      "raw_status": ru.get("raw_status"),
                      "raw_value": ru.get("raw_value"),
                      "normalization_status": ru.get("normalization_status"),
                      "n_valid_market_family": None,
                      "n_valid_sector": None,
                      "warnings": list(ru.get("warnings") or [])}
            rec = next((r for r in normalize_out.get("records", [])
                        if r["company_id"] == cid and r["factor_id"] == fid),
                       None)
            if rec:
                fentry["n_valid_market_family"] = rec["n_valid_market_family"]
                fentry["n_valid_sector"] = rec["n_valid_sector"]
            if score is None:
                reason = _no_score_reason(ru)
                fentry.update({"score": None, "score_kind": None,
                               "included": False,
                               "contribution_points": None,
                               "not_included_reason": reason})
                diag[_diag_bucket(reason)] += 1
                refusal_by_factor.setdefault(fid, Counter())[reason] += 1
            else:
                fentry.update({"score": score, "score_kind": kind,
                               "included": True,
                               "contribution_points": row["weight"] * score,
                               "not_included_reason": None})
                covered_pairs.append((fid, row["weight"]))
                points_pairs.append((fid, row["weight"] * score))
                scored_by_factor[fid] += 1
            if ru.get("raw_status") == "valid":
                valid_by_factor[fid] += 1
            if row["essential"] and not fentry["included"]:
                ess_missing.append(fid)
            factors[fid] = fentry

        covered = math.fsum(w for _f, w in sorted(covered_pairs))
        points = (math.fsum(p for _f, p in sorted(points_pairs))
                  if points_pairs else None)
        ratio = covered / target
        ess_ok = not ess_missing
        cov_ok = ratio >= thr - COV_EPS
        eligible = ess_ok and cov_ok

        n_eligible += eligible
        n_any += bool(points_pairs)
        n_zero += not points_pairs
        covered_hist[f"{round(covered, 6):g}"] += 1

        warnings = sorted({w for fid in sorted(raw_by_company.get(cid) or {})
                           for w in (raw_by_company[cid][fid].get("warnings")
                                     or [])})
        entry = {
            "company_id": cid,
            "symbol": (symbols or {}).get(cid),
            "model_family": fam,
            "industry": meta.get("industry"),
            "factors": factors,
            "v_observed_points": points,
            "covered_weight": covered,
            "missing_weight": target - covered,
            "coverage_ratio": ratio,
            "coverage_threshold_met": cov_ok,
            "essential_status": {"required": essentials,
                                 "missing": sorted(ess_missing),
                                 "all_satisfied": ess_ok},
            "pilot_eligible": eligible,
            "diagnostic_counts": dict(sorted(diag.items())),
            "data_confidence": {
                "status": "not_evaluated",
                "covered_weight": covered,
                "coverage_ratio": ratio,
                "missing_reasons": {
                    fid: factors[fid]["not_included_reason"]
                    for fid in sorted(factors)
                    if not factors[fid]["included"]},
                "note": ("diagnostic only — the numeric Data Confidence "
                         "formula is not approved yet; no confidence "
                         "coefficient touches v_observed_points"),
            },
            "risk_gate": {
                "status": "not_evaluated",
                "final_evaluation": "not_evaluated",
                "financial_warnings": warnings,
                "note": ("warnings are preserved evidence only; absence of "
                         "warnings is never a low-risk or risk-cleared "
                         "verdict; no risk penalty is applied to "
                         "v_observed_points"),
            },
        }
        companies[cid] = entry

    summary = {
        "n_companies_total": len(companies),
        "n_any_score": n_any,
        "n_zero_coverage": n_zero,
        "n_pilot_eligible": n_eligible,
        "n_raw_valid_by_factor": dict(sorted(valid_by_factor.items())),
        "n_scored_by_factor": dict(sorted(scored_by_factor.items())),
        "refusal_reasons_by_factor": {
            fid: dict(sorted(c.items()))
            for fid, c in sorted(refusal_by_factor.items())},
        "max_covered_weight_observed": max(
            (e["covered_weight"] for e in companies.values()), default=0.0),
        "covered_weight_distribution": dict(sorted(
            covered_hist.items(), key=lambda kv: float(kv[0]))),
        "policy": {
            "coverage_threshold": thr,
            "threshold_source": "score_v2_config.SCORING_POLICY"
                                ".min_axis_coverage",
            "renormalization": ("forbidden — a missing factor's weight is "
                                "never redistributed and v_observed_points "
                                "is never divided by covered_weight"),
            "ranking": ("companies are never ranked by v_observed_points — "
                        "coverage differs across companies; and relative "
                        "cheapness is NOT an intrinsic-value claim"),
            "independent_systems": ("Data Confidence and Risk Gate stay "
                                    "not_evaluated; no coefficient or "
                                    "penalty touches the points"),
        },
    }
    return {
        "stage": STAGE,
        "score_version": CFG2.SCORE_VERSION,
        "as_of": normalize_out.get("as_of"),
        "pit_policy": normalize_out.get("pit_policy"),
        "disclaimer": DISCLAIMER,
        "purpose": (
            "first observed-V pilot output — an honest partial sum of "
            "RELATIVE cheapness over the factors that actually scored; NOT a "
            "final V out of 35, never renormalized over covered weight, "
            "never a purchase signal, never an intrinsic-value estimate"),
        "weight_tables": {fam: tables[fam] for fam in sorted(tables)},
        "companies": companies,
        "summary": summary,
        "display_sample": select_display_sample(companies, display_limit),
    }


def select_display_sample(companies: dict, limit: int = 24) -> list:
    """Deterministic display selection across coverage classes — an
    illustrative sample for the report, NEVER a ranking by points."""
    buckets = {"eligible": [], "essential_gap": [], "partial": [],
               "no_score": []}
    for cid in sorted(companies):
        e = companies[cid]
        if e.get("pilot_eligible"):
            buckets["eligible"].append(cid)
        elif e.get("essential_status", {}).get("missing"):
            buckets["essential_gap"].append(cid)
        elif e.get("covered_weight", 0.0) > 0:
            buckets["partial"].append(cid)
        else:
            buckets["no_score"].append(cid)
    order = ["eligible", "essential_gap", "partial", "no_score"]
    idx = {k: 0 for k in order}
    picks: list = []
    while len(picks) < limit:
        progressed = False
        for k in order:
            if idx[k] < len(buckets[k]):
                picks.append(buckets[k][idx[k]])
                idx[k] += 1
                progressed = True
                if len(picks) >= limit:
                    return picks
        if not progressed:
            break
    return picks


# ---------------------------------------------------------------------------
# engine-adjacent inputs — the pilot resolves everything from the engine's
# OWN loaded rows; no new SQL anywhere (same doctrine as the Q pilot)
# ---------------------------------------------------------------------------
def build_market_channel(eng, as_of: dt.date) -> tuple[dict, dict]:
    """({cid: channel}, diag) — PIT price row + share-snapshot evidence per
    company, from engine.prices / engine.current_shares / engine.metrics
    only.

    engine.prices is ordered security_id, trade_date DESC (the engine's own
    PIT filter is already applied at load time), so the FIRST row per
    security is exactly the row behind the engine's latest_price.
    """
    latest_px: dict = {}
    for r in getattr(eng, "prices", []) or []:
        sid = r["security_id"]
        if sid not in latest_px:
            latest_px[sid] = r

    cur_shares = getattr(eng, "current_shares", {}) or {}
    channel: dict = {}
    diag = {"n_companies": len(eng.metrics), "n_with_price": 0,
            "n_with_shares": 0, "n_with_both": 0, "n_price_after_as_of": 0,
            "price_age_over_policy": 0, "n_share_older_than_price": 0,
            "n_tsetmc_primary": 0, "n_vendor_fallback": 0}
    for cid in sorted(eng.metrics):
        m = eng.metrics[cid] or {}
        sid = m.get("security_id")
        px = latest_px.get(sid) if sid else None
        cur = cur_shares.get(sid) if sid else None
        price = m.get("latest_price")
        ptd = px.get("trade_date") if px else None
        entry = {
            "price": price,
            "price_trade_date": ptd,
            "price_collected_at": px.get("collected_at") if px else None,
            "price_age_days": (as_of - ptd).days
            if (ptd is not None and as_of is not None) else None,
            "shares": m.get("shares_outstanding"),
            "share_source": (cur or {}).get("source")
            or (m.get("_valuation_prov") or {}).get("share_source"),
            "share_source_date": (cur or {}).get("source_as_of")
            or ((cur or {}).get("collected_at").date()
                if (cur or {}).get("collected_at") is not None else None),
            "share_cross_check": (cur or {}).get("cross_check_status"),
        }
        ssd = entry.get("share_source_date")
        entry["share_price_gap_days"] = (
            (ptd - ssd).days
            if (ptd is not None and ssd is not None) else None)
        channel[cid] = entry

        if entry["price"] is not None:
            diag["n_with_price"] += 1
        if entry["shares"] is not None:
            diag["n_with_shares"] += 1
        if entry["price"] is not None and entry["shares"] is not None:
            diag["n_with_both"] += 1
        if ptd is not None and ptd > as_of:
            diag["n_price_after_as_of"] += 1
        age = entry.get("price_age_days")
        if age is not None and age > VRW.PRICE_STALE_DAYS:
            diag["price_age_over_policy"] += 1
        gap = entry.get("share_price_gap_days")
        if gap is not None and gap > 0:
            diag["n_share_older_than_price"] += 1
        if (cur or {}).get("source") == "TSETMC_ZTITAD_CURRENT":
            diag["n_tsetmc_primary"] += 1
        elif (cur or {}).get("source") == "BRS_SHARE_STRUCTURE_CURRENT":
            diag["n_vendor_fallback"] += 1
    return channel, diag


def resolve_equity(eng) -> dict:
    """{cid: {"equity", "period_end_date"}} — total_equity order-1 from the
    engine's OWN latest report cell (exactly the cell the engine's direct
    P/B reads: max (fy*12+fm) over report_index). Read-only replication; a
    company without a total_equity fact gets no entry (missing, never 0)."""
    rep_index = eng.report_index()
    out: dict = {}
    for cid, rep in rep_index.items():
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        cell = rep.get(latest) or {}
        v = (cell.get("total_equity") or {}).get(1)
        if v is None:
            continue
        out[cid] = {"equity": float(v),
                    "period_end_date": cell.get("_period")}
    return out


def net_profit_sentinel_legs(eng, sentinel_cells: dict,
                             durations_by_company: dict) -> tuple[dict, dict]:
    """({cid: [leg, ...]}, diag) — the exact legacy-sentinel net_profit legs
    behind each company's resolved current net_profit_ttm, named per the
    resolution path the ENGINE itself recorded in _ttm_prov:

      ANNUAL_REPORT_12M / DIRECT (fm=12)  -> latest order-1 only
      DIRECT_CANONICAL (fm!=12)           -> latest orders 1 + 3 - 2
      REPORT_CHAIN_TTM                    -> latest o1 + (fy-1, fm) o1
                                             + prev-annual-cell o1
    A company whose TTM did not resolve gets no legs (its P/E is missing
    regardless). Diagnostic only — nothing is dropped here; the warning
    travels on the pe raw record.
    """
    rep_index = eng.report_index()
    out: dict = {}
    diag = {"n_companies_checked": 0, "n_with_sentinel_legs": 0,
            "n_unresolved_ttm": 0}
    for cid in sorted(eng.metrics):
        m = eng.metrics[cid] or {}
        prov = (m.get("_ttm_prov") or {}).get("net_profit_ttm")
        rep = rep_index.get(cid) or {}
        if not rep or prov not in (RC.PROV_ANNUAL_REPORT, RC.PROV_DIRECT,
                                   RC.PROV_CHAIN):
            diag["n_unresolved_ttm"] += 1
            continue
        diag["n_companies_checked"] += 1
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        fy, fm = latest
        legs: list = []
        if prov == RC.PROV_CHAIN:
            cand = [(latest, 1), ((fy - 1, fm), 1)]
            anchor = FC.prev_annual_cell(durations_by_company.get(cid) or {},
                                         *latest)
            if anchor is not None:
                cand.append((anchor, 1))
        elif prov == RC.PROV_DIRECT and fm != 12:
            cand = [(latest, 1), (latest, 3), (latest, 2)]
        else:  # annual report or a December direct cell: order-1 only
            cand = [(latest, 1)]
        cells = sentinel_cells.get(cid) or set()
        for (key, order) in cand:
            if (key[0], key[1], "net_profit", order) in cells:
                legs.append(f"net_profit@{key[0]}/{key[1]}(order {order})")
        if legs:
            out[cid] = legs
            diag["n_with_sentinel_legs"] += 1
    return out, diag


def engine_cross_check(raw_by_company: dict, eng) -> dict:
    """Verify the raw layer's construction against the engine's own direct
    valuation (both derive from the same engine inputs): pe/ps/pb must agree
    to relative 1e-9 wherever the raw record is VALID and the engine value
    exists; the recomputed market cap must equal the engine's. Mismatches do
    not stop the run — they are reported loudly and never silently trusted.
    """
    ok = Counter()
    mismatch: list = []
    n_engine_value = Counter()
    for cid in sorted(raw_by_company):
        m = eng.metrics.get(cid) or {}
        rec = raw_by_company[cid]
        mkt = rec["pe"]["market"]
        price, shares = mkt.get("price"), mkt.get("shares")
        raw_mcap = (price * shares
                    if price is not None and shares is not None else None)
        eng_mcap = m.get("market_cap")
        if raw_mcap is not None and eng_mcap is not None:
            if math.isclose(raw_mcap, eng_mcap, rel_tol=1e-9):
                ok["market_cap"] += 1
            else:
                mismatch.append({"company_id": cid, "what": "market_cap",
                                 "raw": raw_mcap, "engine": eng_mcap})
        for fid in VRW.IN_SCOPE_V_FACTORS:
            eng_v = m.get(fid)
            if eng_v is None:
                continue
            n_engine_value[fid] += 1
            rv = rec[fid].get("raw_value")
            if rec[fid]["status"] != "valid" or rv is None:
                mismatch.append({"company_id": cid, "what": fid,
                                 "raw_status": rec[fid]["status"],
                                 "engine": eng_v,
                                 "note": "engine produced a value the raw "
                                         "layer refused — state semantics "
                                         "differ by design, listed here"})
                continue
            if math.isclose(rv, eng_v, rel_tol=1e-9, abs_tol=1e-12):
                ok[fid] += 1
            else:
                mismatch.append({"company_id": cid, "what": fid,
                                 "raw": rv, "engine": eng_v})
    return {"agreements": dict(sorted(ok.items())),
            "n_engine_values_seen": dict(sorted(n_engine_value.items())),
            "n_mismatches": len(mismatch),
            "mismatches": mismatch[:10],
            "note": ("the raw layer recomputes each ratio from its own "
                     "quantity with V2 state semantics; the engine's values "
                     "are the same construction without the V2 gates — a "
                     "refusal where the engine has a value is the raw layer "
                     "being STRICTER (e.g. loss-maker P/E), not a "
                     "disagreement about arithmetic")}


def load_q_eligible(path: Path) -> tuple[set, dict]:
    """The 98 pilot-eligible companies of the 2-B-8 Q run, from the saved
    artifact (same reproducible snapshot) — read-only; never recomputed or
    modified here."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    eligible = {cid for cid, e in d.get("companies", {}).items()
                if e.get("pilot_eligible")}
    return eligible, {"path": str(path), "as_of": str(d.get("as_of")),
                      "n_pilot_eligible": len(eligible),
                      "stage": d.get("stage")}


def build_coverage_summary(raw_by_company: dict, v_report: dict,
                           q_eligible: set | None) -> dict:
    """Direct answers to the mission's coverage questions (section 7)."""
    keys = ("n_pe_valid", "n_pb_valid", "n_ps_valid", "n_all_three_valid",
            "n_no_price_data", "n_no_share_snapshot",
            "n_blocked_negative_net_profit", "n_blocked_zero_net_profit",
            "n_blocked_negative_equity", "n_equity_missing",
            "n_ps_family_excluded")
    n: Counter = Counter({k: 0 for k in keys})
    for cid, rec in raw_by_company.items():
        st = {fid: rec[fid]["status"] for fid in VRW.IN_SCOPE_V_FACTORS}
        rs = {fid: (rec[fid]["validation_reason"] or "") for fid in st}
        if st["pe"] == "valid":
            n["n_pe_valid"] += 1
        if st["pb"] == "valid":
            n["n_pb_valid"] += 1
        if st["ps"] == "valid":
            n["n_ps_valid"] += 1
        if all(st[f] == "valid" for f in VRW.IN_SCOPE_V_FACTORS):
            n["n_all_three_valid"] += 1
        if "no_price_data" in rs["pe"] or "no_pit_market_data" in rs["pe"]:
            n["n_no_price_data"] += 1
        if "no_pit_share_snapshot" in rs["pe"]:
            n["n_no_share_snapshot"] += 1
        if "negative_net_profit_ttm" in rs["pe"]:
            n["n_blocked_negative_net_profit"] += 1
        if "zero_net_profit_ttm" in rs["pe"]:
            n["n_blocked_zero_net_profit"] += 1
        if "negative_total_equity" in rs["pb"]:
            n["n_blocked_negative_equity"] += 1
        if "total_equity_missing" in rs["pb"]:
            n["n_equity_missing"] += 1
        if "ps_not_meaningful_for_specialized_family" in rs["ps"]:
            n["n_ps_family_excluded"] += 1
    scored = {fid: v_report["summary"]["n_scored_by_factor"].get(fid, 0)
              for fid in VRW.IN_SCOPE_V_FACTORS}
    summary = dict(sorted(n.items()))
    summary["n_scored_by_factor"] = scored
    summary["n_v_pilot_eligible"] = v_report["summary"]["n_pilot_eligible"]
    if q_eligible is not None:
        companies = v_report["companies"]
        q_any_v = q_v_eligible = 0
        for cid in q_eligible:
            e = companies.get(cid)
            if not e:
                continue
            if e["v_observed_points"] is not None:
                q_any_v += 1
            if e["pilot_eligible"]:
                q_v_eligible += 1
        summary["n_q_axis_pilot_eligible"] = len(q_eligible)
        summary["n_q_eligible_with_any_v_points"] = q_any_v
        summary["n_q_eligible_also_v_eligible"] = q_v_eligible
    return summary


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def run_value_pilot(as_of: dt.date, cutoff: dt.datetime,
                    engine=None, sector_map: dict | None = None,
                    q_eligible: set | None = None) -> dict:
    """Full read-only V pipeline over the engine population; ``engine`` and
    ``sector_map`` are injectable for offline tests."""
    if engine is None:
        engine = CM.Engine(as_of, cutoff)
    engine.compute()
    if sector_map is None:
        sector_map = S4.load_sector_map(as_of)
    meta, detail = QP.build_company_meta(engine, sector_map)
    prov, prov_diag = QP.build_provenance(engine)
    sentinel_cells, sentinel_census = QP.detect_sentinel_fact_cells(engine)
    durations_by_company, _fiscal_cal = QP.fiscal_calendar_for(engine)

    market, market_diag = build_market_channel(engine, as_of)
    equity = resolve_equity(engine)
    np_sentinel, sentinel_diag = net_profit_sentinel_legs(
        engine, sentinel_cells, durations_by_company)

    raw = VRW.build_v_raw(engine.metrics, meta, market=market,
                          equity_by_company=equity, provenance=prov,
                          net_profit_sentinel=np_sentinel, as_of=as_of,
                          cutoff=cutoff)
    cross = engine_cross_check(raw, engine)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=cutoff,
                                        pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    v_report = build_v_observed_report(
        norm, raw, meta,
        symbols={cid: detail[cid].get("symbol") for cid in detail})

    coverage_summary = build_coverage_summary(raw, v_report, q_eligible)

    return {
        "stage": STAGE,
        "score_version": CFG2.SCORE_VERSION,
        "as_of": as_of.isoformat(),
        "cutoff": cutoff.isoformat(),
        "pit_policy": SN.PIT_CURRENT_EXPLORATORY,
        "disclaimer": DISCLAIMER,
        "construction": {
            "formulas": {"market_cap": "PIT price x PIT shares_outstanding",
                         "pe": "market_cap / net_profit_ttm (only np_ttm > 0)",
                         "pb": "market_cap / total_equity (only equity > 0)",
                         "ps": "market_cap / revenue_ttm (only revenue_ttm > 0)"},
            "anomaly_bands": {"pe": VRW.PE_ANOMALY_BAND,
                              "pb": VRW.PB_ANOMALY_BAND,
                              "ps": VRW.PS_ANOMALY_BAND,
                              "source": "V1 engine's own validity bands; "
                                        "beyond a band stays valid + warning"},
            "freshness_policy": {"price_stale_days": VRW.PRICE_STALE_DAYS,
                                 "balance_sheet_stale_days":
                                     VRW.BALANCE_SHEET_STALE_DAYS,
                                 "note": "experimental thresholds of this "
                                         "step, declared not hidden"},
            "family_gate_ps": "P/S ranks in the general family only (config)",
        },
        "weight_tables": v_report["weight_tables"],
        "input_diagnostics": {
            "market_channel": market_diag,
            "equity_resolution": {
                "n_companies_with_total_equity": len(equity),
                "note": "total_equity order-1 from the engine's own latest "
                        "report cell; a missing equity is a missing P/B, "
                        "never a guessed book value"},
            "net_profit_sentinel_audit": sentinel_diag,
            "sentinel_census_by_metric": dict(sorted(
                sentinel_census.items())),
            "provenance": prov_diag,
        },
        "engine_cross_check": cross,
        "normalization_populations": norm["populations"],
        "v_observed_report": v_report,
        "coverage_summary": coverage_summary,
        "not_modified": ("Q axis output of step 2-B-8 untouched; V1/V4 "
                         "engines, Raw/Normalize/Config/ScoreV2Engine, "
                         "database, ingestion, API and UI unchanged; no "
                         "T axis, no QVT total, no commit"),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-08")
    ap.add_argument("--cutoff", default="2026-10-08T23:59:00+00:00")
    ap.add_argument("--q-report", default=str(HERE / "output"
                                              / "v2_q_observed_report.json"))
    ap.add_argument("--out", default=str(HERE / "output"
                                         / "v2_value_pilot.json"))
    args = ap.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    q_eligible, q_diag = load_q_eligible(Path(args.q_report))

    report = run_value_pilot(as_of, cutoff, q_eligible=q_eligible)
    report["q_axis_artifact"] = q_diag

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, default=str,
                                   ensure_ascii=False), encoding="utf-8")

    # ---- console summary --------------------------------------------------
    vs = report["v_observed_report"]["summary"]
    cov = report["coverage_summary"]
    print("== pilot_v2_value (2-J-1) ==", report["as_of"],
          "cutoff", report["cutoff"])
    print("companies:", vs["n_companies_total"],
          "| any v points:", vs["n_any_score"],
          "| v pilot eligible:", vs["n_pilot_eligible"])
    for fam, t in sorted(report["weight_tables"].items()):
        print(f"  weight table {fam}: {t['weights']} = {t['total_weight']}")
    print("input diagnostics:", json.dumps(report["input_diagnostics"],
                                           default=str, ensure_ascii=False))
    print("engine cross-check:", json.dumps(
        {k: v for k, v in report["engine_cross_check"].items()
         if k != "mismatches"}, default=str))
    print("raw valid:", vs["n_raw_valid_by_factor"],
          "| scored:", vs["n_scored_by_factor"])
    print("coverage summary:", json.dumps(cov, default=str,
                                          ensure_ascii=False))
    print("covered distribution:", vs["covered_weight_distribution"])
    print("refusals:", json.dumps(vs["refusal_reasons_by_factor"],
                                  default=str, ensure_ascii=False)[:2000])
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
