"""Observed-Q aggregation pilot for Score v2 (steps 2-B-6 / 2-B-7) — general
family.

This module produces the FIRST observed fundamental-quality output:
``q_observed_points`` = Σ (config weight of an available, permitted factor ×
its normalized score), computed per general-family company from the raw +
normalize layers' existing output. It is deliberately NOT a final Q:

  * The Q axis target is 40, but no missing weight is ever redistributed and
    ``q_observed_points`` is NEVER divided by ``covered_weight`` — an
    incomplete company keeps an incomplete point total, honestly labeled.
  * A missing factor has no score share and is never read as zero
    performance: it contributes nothing, and its absence is named.
  * Companies are NEVER ranked by ``q_observed_points`` — coverage differs
    across companies, so a rank would compare different denominators.
  * ``q_observed_points`` is the only aggregate; there is no
    quality_score / q_final_score / V / T / total anywhere.
  * Data Confidence and the Risk Gate stay independent systems:
    ``status: not_evaluated`` — diagnostics only, no numeric confidence, no
    risk penalty touches the points.

Step 2-B-7 scope: interest_coverage and earnings_quality JOINED the raw
layer through the same-window expense-TTM channel (within-report assembly
only; no cross-report chain, no YTD scaling, no guessed leg — the pilot
resolves the channel). They are aggregable here like any other in-scope
factor; where their comparative legs are absent they stay missing with an
honest reason, and their weights (3 + 3) are never redistributed.

Step 2-B-6 conservative policy (mission §3): ``earnings_growth`` — its own
blended scores are PRESERVED as diagnostics (never deleted or rewritten) but
NOT consumed by this aggregation, because its legacy-contamination history
and economic validity are not yet ratified. Its weight is temporarily
unusable, not transferred.

Weight-table control (mission §2): the family's Q weights are read directly
from score_v2_config.FAMILY_WEIGHTS and must sum exactly to
AXIS_WEIGHTS["quality"] (40). Any inconsistency — a wrong sum, a READY
config factor absent from the raw layer's scope without a documented
blocker, a stale policy/note naming a factor the raw layer implements or
the map does not contain — raises QWeightInconsistency and STOPS the
aggregation. The table is never auto-fixed here; recalibration is a config
edit, not code.

Factor-score admission (mission §4): a factor enters the sum only when its
normalize rollup carries a usable score — composite ``blended`` with a
finite factor_blend_score in [0, 1], or single ``ranked`` with a finite
percentile_combined in [0, 1] — AND this step's policy permits it. A rollup
that claims a ranked/blended state with an out-of-range or non-finite score
is refused loudly (defense in depth), never consumed.

Pure and deterministic: in-memory inputs only, no database, no engine, no
clock; math.fsum over sorted keys so results are independent of input dict
order.
"""

from __future__ import annotations

import math
from collections import Counter

import score_v2_config as CFG2
import score_v2_normalize as SN
import score_v2_raw as RAW

__all__ = [
    "STAGE",
    "DISCLAIMER",
    "QWeightInconsistency",
    "POLICY_EXCLUDED",
    "q_weight_table",
    "build_q_observed_report",
    "select_display_sample",
]

SCORE_VERSION = CFG2.SCORE_VERSION
STAGE = "q_observed_pilot"
AXIS = "quality"

DISCLAIMER = (
    "گام ۲-ب-۶/۲-ب-۷ — q_observed_points یک خروجی مشاهده‌شده آزمایشی است، نه Q کامل "
    "از ۴۰ و نه سیگنال خرید. وزن مفقود بازتوزیع نمی‌شود، امتیاز ناقص بر مبنای "
    "پوشش نرمال نمی‌شود، شرکت‌ها بر اساس آن رتبه‌بندی نمی‌شوند و Data "
    "Confidence و Risk Gate مستقل و فعلاً not_evaluated هستند. دو فاکتور "
    "پوشش/کیفیت از گام ۲-ب-۷ با TTM هم‌دوره درون‌گزارشی وارد دامنه شدند و "
    "هرجا اجزای گزارش غایب است صادقانه missing می‌مانند."
)

# -----------------------------------------------------------------------------
# Step 2-B-6 policy (mission §3): earnings_growth is diagnostic-only in this
# aggregation. Its own scores stay visible on its factor entry; its weight is
# temporarily unusable and NOT redistributed. Guards in q_weight_table refuse
# a stale entry (factor not in the family map, or not implemented in the raw
# layer at all).
# -----------------------------------------------------------------------------
POLICY_EXCLUDED = {
    "earnings_growth": (
        "policy_excluded_step_2b6: earnings_growth stays diagnostic-only — "
        "legacy-contamination history and not-yet-ratified economic validity; "
        "its weight (3) is temporarily unusable, never redistributed; the "
        "factor's own blended scores are preserved, just not consumed here"),
}

# Q-axis factors the config declares READY but the raw layer does not
# implement, with the documented blocker (mission §2 wants these explicit).
# Guards refuse a stale note (raw layer implements the factor) and a missing
# note (READY factor absent from the raw scope with no documented reason).
# 2-B-7 removed interest_coverage / earnings_quality from here when the
# same-window expense-TTM channel brought them into the raw scope.
_NOT_IN_RAW_SCOPE = {
    "roe_stability": (
        "not_implemented", (
            "not_implemented: intentionally outside the step 2-B-5 batch "
            "scope; no engine metric exists yet")),
}

_TOLERANCE = 1e-9
_COV_EPS = 1e-12


class QWeightInconsistency(ValueError):
    """The family Q weight table is inconsistent with the config/raw-layer
    contract — aggregation must STOP and the inconsistency be reported
    (mission §2), never auto-fixed in code."""


def q_weight_table(family: str = "general") -> dict:
    """The family's Q-axis weight table, read live from config, with the
    implementation status and the step's aggregation gate per factor.

    Raises QWeightInconsistency (aggregation stops) when: the weights do not
    sum exactly to AXIS_WEIGHTS["quality"]; a factor is documented out of the
    raw scope that the raw layer actually implements (stale note); a READY
    config factor is absent from the raw scope with no documented blocker; a
    POLICY_EXCLUDED entry is stale (unknown to the family map or not
    implemented in the raw layer).
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
        if fid in RAW.IN_SCOPE_FACTORS:
            impl = "implemented"
            if fid in _NOT_IN_RAW_SCOPE:
                raise QWeightInconsistency(
                    f"{fid}: documented out of the raw layer's scope but the "
                    "raw layer implements it — stale step note, aggregation "
                    "stops")
            if fid in POLICY_EXCLUDED:
                agg, cat, note = False, "policy_excluded", POLICY_EXCLUDED[fid]
            else:
                agg, cat, note = True, "aggregable", None
        elif spec["availability"] == CFG2.NEEDS_DEVELOPMENT:
            impl = "needs_development"
            agg, cat, note = False, "needs_development", (
                "needs_development: no valid data path yet — no automatic "
                "surrogate is allowed (config)")
        else:
            if fid not in _NOT_IN_RAW_SCOPE:
                raise QWeightInconsistency(
                    f"{fid}: READY in config but absent from the raw layer's "
                    "scope with no documented blocker — aggregation stops "
                    "(report the inconsistency, never auto-fix)")
            impl, note = _NOT_IN_RAW_SCOPE[fid]
            agg, cat = False, impl
        rows[fid] = {"weight": weights[fid], "essential": spec["essential"],
                     "direction": spec["direction"],
                     "implementation": impl,
                     "scope_category": cat,
                     "in_aggregation_scope": agg,
                     "aggregation_note": note}

    total = math.fsum(weights[f] for f in sorted(weights))
    target = CFG2.AXIS_WEIGHTS[AXIS]
    if abs(total - target) > _TOLERANCE:
        raise QWeightInconsistency(
            f"{family} Q-axis weights sum to {total}, expected {target} — "
            "aggregation stops; weights are recalibrated in config, never "
            "auto-fixed here")

    stale_policy = sorted(set(POLICY_EXCLUDED) - set(fam_map))
    if stale_policy:
        raise QWeightInconsistency(
            f"POLICY_EXCLUDED names factor(s) outside the {family} map: "
            f"{stale_policy}")
    for fid in POLICY_EXCLUDED:
        if fid not in RAW.IN_SCOPE_FACTORS:
            raise QWeightInconsistency(
                f"POLICY_EXCLUDED names {fid!r}, which the raw layer does "
                "not implement — stale exclusion")
    stale_notes = sorted(set(_NOT_IN_RAW_SCOPE) - set(fam_map))
    if stale_notes:
        raise QWeightInconsistency(
            f"_NOT_IN_RAW_SCOPE documents factor(s) outside the {family} "
            f"map: {stale_notes}")

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
    """(score, kind) when the rollup carries a usable normalized score.

    Composite ``blended`` -> factor_blend_score; single ``ranked`` ->
    percentile_combined. Anything else — including a ranked/blended state
    whose score is not a finite number in [0, 1] — returns (None, None);
    the caller names the refusal instead of consuming a bad score.
    """
    if not isinstance(rollup, dict):
        return None, None
    st = rollup.get("normalization_status")
    if st == SN.FS_BLENDED:
        val, kind = rollup.get("factor_blend_score"), "factor_blend_score"
    elif st == SN.NR_RANKED:
        val, kind = rollup.get("percentile_combined"), "percentile_combined"
    else:
        return None, None
    if (isinstance(val, bool) or not isinstance(val, (int, float))
            or not math.isfinite(val) or not 0.0 <= float(val) <= 1.0):
        return None, None
    return float(val), kind


def _no_score_reason(rollup) -> str:
    """Honest, categorized refusal reason for a factor with no usable score."""
    st = (rollup or {}).get("normalization_status")
    if st is None:
        return "no normalize rollup for this company/factor"
    if st in (SN.NR_RANKED, SN.FS_BLENDED):
        return ("score_refused: the rollup claims ranked/blended but its "
                "score is not a finite number in [0, 1]")
    return {
        SN.NR_INSUFFICIENT_PEERS:
            "insufficient_peers: family peer population below family_min_n",
        SN.FS_INSUFFICIENT_PEERS:
            "insufficient_peers: a component's peer population is below "
            "family_min_n",
        SN.FS_PENDING_DATA:
            "pending_data: a composite component is missing or "
            "not_applicable",
        SN.FS_UNAVAILABLE:
            "unavailable: invalid / non-finite / PIT-refused component data",
        SN.NR_PENDING_BLEND:
            "pending_blend: no approved component blend contract",
        SN.NR_NON_FINITE: "not_ranked_non_finite",
        SN.NR_PIT_STRICT: "not_ranked_pit_strict",
        SN.NR_AFTER_AS_OF: "published_after_as_of",
        "not_ranked_raw_missing":
            "raw_missing: the factor's inputs are absent — a missing factor "
            "has no score share, never a zero-performance reading",
        "not_ranked_raw_invalid": "raw_invalid: the raw layer refused the value",
        "not_ranked_raw_not_applicable":
            "raw_not_applicable: economically meaningless for this company",
    }.get(st, f"unranked: {st}")


def _diag_bucket(reason: str) -> str:
    for prefix, bucket in (
            ("insufficient_peers", "insufficient_peers"),
            ("pending_data", "pending_data"),
            ("unavailable", "unavailable"),
            ("raw_missing", "missing"),
            ("raw_invalid", "invalid"),
            ("raw_not_applicable", "not_applicable"),
            ("pending_blend", "other_refusals"),
            ("score_refused", "score_refused"),
            ("no normalize rollup", "other_refusals")):
        if reason.startswith(prefix):
            return bucket
    return "other_refusals"


def _included_pit_states(fid: str, rollup: dict, rec_index: dict,
                         cid: str) -> list:
    """PIT states of the parts behind an INCLUDED factor's score."""
    if rollup.get("composite"):
        comps = (rollup.get("components") or {})
        return [c.get("pit_status") for c in comps.values()
                if c.get("pit_status")]
    rec = rec_index.get((cid, fid, None))
    return [rec["pit_status"]] if rec and rec.get("pit_status") else []


def _raw_warnings(raw_factors: dict) -> list:
    """Every real warning the raw layer recorded for this company (factor
    level and composite component level), deduplicated, deterministic."""
    out: list = []
    for fid in sorted(raw_factors or {}):
        rec = raw_factors[fid]
        out.extend(rec.get("warnings") or [])
        comps = rec.get("components") or {}
        for comp in sorted(comps):
            out.extend(comps[comp].get("warnings") or [])
    return sorted(set(out))


_RISK_FLAG_TAGS = ("negative_equity", "financial_distress_or_anomaly",
                   "turned_to_loss", "magnitude_anomaly",
                   "component_period_mismatch")


def _risk_flags(warnings: list) -> dict:
    """Structured counts for the named real warning tags — present only when
    the raw layer actually emitted them (mission §6)."""
    flags: dict = {}
    for w in warnings:
        for tag in _RISK_FLAG_TAGS:
            if w.startswith(tag):
                flags[tag] = flags.get(tag, 0) + 1
    return dict(sorted(flags.items()))


def build_q_observed_report(normalize_out: dict,
                            raw_by_company: dict,
                            company_meta: dict,
                            *,
                            family: str = "general",
                            coverage_threshold: float | None = None,
                            symbols: dict | None = None,
                            display_limit: int = 20) -> dict:
    """Aggregate the observed-Q pilot report for one model family.

    normalize_out  : output of score_v2_normalize.normalize_q_cross_section
    raw_by_company : output of score_v2_raw.build_q_raw (same run)
    company_meta   : {cid: {"model_family", "industry"}} as given to normalize
    symbols        : optional {cid: symbol} for display

    Per general company: per-factor weight/score/contribution, the
    q_observed_points sum over PERMITTED scored factors only,
    covered/missing weight and coverage_ratio against the 40 target, the
    essential gate, pilot_eligible, and independent Data Confidence /
    Risk-Gate diagnostics. Non-{family} companies get an explicit
    family_out_of_scope entry and are never aggregated.
    """
    table = q_weight_table(family)
    weights, rows = table["weights"], table["rows"]
    target = table["target_weight"]
    thr = (CFG2.SCORING_POLICY["min_axis_coverage"]
           if coverage_threshold is None else float(coverage_threshold))
    if not 0 < thr <= 1:
        raise ValueError(f"coverage_threshold must be in (0, 1], got {thr!r}")
    essentials = sorted(f for f, r in rows.items() if r["essential"])
    agg_scope = sorted(f for f, r in rows.items() if r["in_aggregation_scope"])
    policy_excluded = sorted(set(weights) - set(agg_scope))

    rec_index = {(r.get("company_id"), r.get("factor_id"),
                  r.get("component_id")): r
                 for r in normalize_out.get("records", [])}
    all_rollups = normalize_out.get("factors", {})

    companies: dict = {}
    n_ess_ok = n_cov_ok = n_eligible = n_any = n_zero = n_eligible_cf = 0
    scored_by_factor: Counter = Counter()
    covered_hist: Counter = Counter()

    for cid in sorted(company_meta):
        meta = company_meta[cid] or {}
        fam = meta.get("model_family")
        entry = {"company_id": cid,
                 "symbol": (symbols or {}).get(cid),
                 "model_family": fam,
                 "industry": meta.get("industry")}
        if fam != family:
            entry["aggregation_status"] = "family_out_of_scope"
            entry["reason"] = (f"model_family {fam!r}: this pilot aggregates "
                               f"the {family!r} family only")
            companies[cid] = entry
            continue

        rollups = all_rollups.get(cid, {})
        factors: dict = {}
        covered_pairs: list = []
        points_pairs: list = []
        pit_counts: Counter = Counter()
        ess_missing: list = []
        diag: Counter = Counter()

        for fid in sorted(weights):
            row = rows[fid]
            ru = rollups.get(fid) or {}
            score, kind = _scored_factor(ru)
            fentry = {"weight": row["weight"],
                      "essential": row["essential"],
                      "direction": row["direction"],
                      "implementation": row["implementation"],
                      "in_aggregation_scope": row["in_aggregation_scope"],
                      "normalization_status": ru.get("normalization_status"),
                      "warnings": list(ru.get("warnings") or [])}
            if not row["in_aggregation_scope"]:
                # the factor's own score stays visible as a diagnostic —
                # preserved, never consumed, never redistributed
                fentry.update({"score": score, "score_kind": kind,
                               "included": False,
                               "contribution_points": None,
                               "not_included_reason": row["aggregation_note"]})
                diag[row["scope_category"]] += 1
            elif score is None:
                reason = _no_score_reason(ru)
                fentry.update({"score": None, "score_kind": None,
                               "included": False,
                               "contribution_points": None,
                               "not_included_reason": reason})
                diag[_diag_bucket(reason)] += 1
            else:
                fentry.update({"score": score, "score_kind": kind,
                               "included": True,
                               "contribution_points": row["weight"] * score,
                               "not_included_reason": None})
                covered_pairs.append((fid, row["weight"]))
                points_pairs.append((fid, row["weight"] * score))
                scored_by_factor[fid] += 1
                pit_counts.update(_included_pit_states(fid, ru, rec_index,
                                                       cid))
            if row["essential"] and not fentry["included"]:
                ess_missing.append(fid)
            factors[fid] = fentry

        covered = math.fsum(w for _f, w in sorted(covered_pairs))
        points = (math.fsum(p for _f, p in sorted(points_pairs))
                  if points_pairs else None)
        ratio = covered / target
        cov_ok = ratio >= thr - _COV_EPS
        ess_ok = not ess_missing
        eligible = ess_ok and cov_ok

        # counterfactual for the policy effect (mission §5): eligibility if
        # the step's policy exclusions were lifted — same threshold, same
        # essentials; this changes NOTHING in the reported points
        covered_cf = covered
        for fid in policy_excluded:
            score, _kind = _scored_factor(rollups.get(fid) or {})
            if score is not None:
                covered_cf += weights[fid]
        eligible_cf = (ess_ok
                       and covered_cf / target >= thr - _COV_EPS)

        n_ess_ok += ess_ok
        n_cov_ok += cov_ok
        n_eligible += eligible
        n_eligible_cf += eligible_cf
        n_any += bool(points_pairs)
        n_zero += not points_pairs
        covered_hist[f"{round(covered, 6):g}"] += 1

        warnings = _raw_warnings(raw_by_company.get(cid) or {})
        entry.update({
            "aggregation_status": "aggregated",
            "factors": factors,
            "q_observed_points": points,
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
                "pit_status_counts": dict(sorted(pit_counts.items())),
                "missing_reasons": {fid: factors[fid]["not_included_reason"]
                                    for fid in sorted(factors)
                                    if not factors[fid]["included"]},
                "note": ("diagnostic only — the numeric Data Confidence "
                         "formula is not approved yet; no confidence "
                         "coefficient touches q_observed_points"),
            },
            "risk_gate": {
                "status": "not_evaluated",
                "final_evaluation": "not_evaluated",
                "financial_warnings": warnings,
                "flags": _risk_flags(warnings),
                "note": ("warnings are preserved evidence only; absence of "
                         "warnings is never a low-risk or risk-cleared "
                         "verdict; no risk penalty is applied to "
                         "q_observed_points"),
            },
            "limitations": _limitations(factors, ess_missing, policy_excluded,
                                        weights),
        })
        companies[cid] = entry

    summary = {
        "n_companies_total": len(companies),
        "n_general": sum(1 for e in companies.values()
                         if e["aggregation_status"] == "aggregated"),
        "n_family_out_of_scope": sum(
            1 for e in companies.values()
            if e["aggregation_status"] == "family_out_of_scope"),
        "n_any_score": n_any,
        "n_zero_coverage": n_zero,
        "n_essentials_satisfied": n_ess_ok,
        "n_coverage_threshold_met": n_cov_ok,
        "n_pilot_eligible": n_eligible,
        "eligibility_policy_effect": {
            "n_eligible_under_policy": n_eligible,
            "n_eligible_if_policy_exclusions_lifted": n_eligible_cf,
            "delta": n_eligible_cf - n_eligible,
            "note": ("counterfactual only — the reported q_observed_points "
                     "never include policy-excluded factors"),
        },
        "max_covered_weight_observed": max(
            (e["covered_weight"] for e in companies.values()
             if e["aggregation_status"] == "aggregated"),
            default=0.0),
        "covered_weight_distribution": dict(sorted(
            covered_hist.items(), key=lambda kv: float(kv[0]))),
        "n_scored_by_factor": dict(sorted(scored_by_factor.items())),
        "note_vs_previous_diagnostic": (
            "the step 2-B-5 q_readiness diagnostic counted candidates against "
            "all ten general Q weights (max coverable 31); this pilot "
            "aggregates the raw layer's in-scope factors minus this step's "
            "policy exclusion (earnings_growth), so the eligible count is "
            "stricter by construction — since 2-B-7 the two expense-TTM "
            "factors join the scope where their legs resolve"),
    }
    return {
        "stage": STAGE,
        "score_version": SCORE_VERSION,
        "as_of": normalize_out.get("as_of"),
        "pit_policy": normalize_out.get("pit_policy"),
        "disclaimer": DISCLAIMER,
        "purpose": (
            "first observed-Q pilot output — an honest partial sum over the "
            "factors that actually scored; NOT a final Q out of 40, never "
            "renormalized over covered weight, never a purchase signal"),
        "family": family,
        "weight_table": table,
        "policy": {
            "coverage_threshold": thr,
            "threshold_source": ("score_v2_config.SCORING_POLICY"
                                 ".min_axis_coverage"),
            "policy_exclusions": dict(sorted(POLICY_EXCLUDED.items())),
            "renormalization": ("forbidden — a missing factor's weight is "
                                "never redistributed and q_observed_points "
                                "is never divided by covered_weight"),
            "ranking": ("companies are never ranked by q_observed_points — "
                        "coverage differs across companies"),
            "independent_systems": ("Data Confidence and Risk Gate stay "
                                    "not_evaluated; no coefficient or "
                                    "penalty touches the points"),
        },
        "companies": companies,
        "summary": summary,
        "display_sample": select_display_sample(companies, display_limit),
    }


def _limitations(factors: dict, ess_missing: list, policy_excluded: list,
                 weights: dict) -> list:
    """The company's most important limitation reasons, deterministic order:
    missing essentials first, then policy exclusions, then the always-on
    blocked/not-implemented weights, then this company's data gaps."""
    out: list = []
    for fid in sorted(ess_missing):
        out.append(f"essential {fid} (weight {weights[fid]}) has no usable "
                   f"score: {factors[fid]['not_included_reason']}")
    for fid in policy_excluded:
        out.append(factors[fid]["not_included_reason"])
    for fid in sorted(factors):
        f = factors[fid]
        if f["included"] or fid in policy_excluded:
            continue
        if f["implementation"] in ("blocked_at_raw_layer", "not_implemented",
                                   "needs_development"):
            out.append(f"{fid} (weight {weights[fid]}): "
                       f"{f['not_included_reason']}")
    for fid in sorted(factors):
        f = factors[fid]
        if f["included"] or fid in policy_excluded \
                or f["implementation"] != "implemented":
            continue
        out.append(f"{fid} (weight {weights[fid]}): "
                   f"{f['not_included_reason']}")
    return out


def select_display_sample(companies: dict, limit: int = 20) -> list:
    """A deterministic display selection across coverage classes — an
    illustrative sample for the report, NEVER a ranking by points: buckets
    (eligible / essential-gap / partial / no-score / out-of-scope) are
    round-robined in company-id order."""
    buckets = {"eligible": [], "essential_gap": [], "partial": [],
               "no_score": [], "out_of_scope": []}
    for cid in sorted(companies):
        e = companies[cid]
        if e.get("aggregation_status") == "family_out_of_scope":
            buckets["out_of_scope"].append(cid)
        elif e.get("pilot_eligible"):
            buckets["eligible"].append(cid)
        elif e.get("essential_status", {}).get("missing"):
            buckets["essential_gap"].append(cid)
        elif e.get("covered_weight", 0.0) > 0:
            buckets["partial"].append(cid)
        else:
            buckets["no_score"].append(cid)
    order = ["eligible", "essential_gap", "partial", "no_score",
             "out_of_scope"]
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
