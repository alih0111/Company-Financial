"""Canonical Score v2 (QVT) — standalone computational skeleton.

score_version = "canonical-v2-qvt". Companion config: score_v2_config.py.

THIS IS A SKELETON: no factor is computed from raw financials here, nothing
touches the database, no run is stored, nothing is served, no Go/React/API
surface knows about it. The engine takes ALREADY-NORMALIZED factor values in
[0, 1] (1.0 = best in universe, direction already applied) and does the axis
aggregation, breakdown, coverage and status contract only. When every
supplied test value is valid the math is fully computable; factors whose data
pipeline does not exist yet (needs_development) never produce a real score.

Reuse from Score v4 — no rewriting of existing algorithms:
  score_v4.midrank                        percentile engine (reused here by
                                          percentile_normalize; the raw-metric
                                          stage will reuse it the same way)
  score_v4_config.family_for_category     general/bank/insurance/investment
                                          mapping — single source of family
                                          truth, shared with v4
Identified for reuse in the NEXT stage, deliberately not wired yet:
  score_v4.winsor_bounds / apply_winsor   P1/P99 clipping (coupled to v4's
                                          module globals; v2 will call the
                                          same algorithm parametrized on its
                                          own registry)
  score_v4.combined_percentile            sector/market blend with linear
                                          decay for small industry samples
  score_v4.compute_confidence + CONFIDENCE_COMPONENTS
                                          the Data Confidence stage
  score_v4.PENALTY_RULES / compute_penalties
                                          the Risk Gate template
Direct reuse was rejected only for validate_raw (hard-coupled to v4's
CFG.FACTOR_CONFIG globals and to raw-metric ranges; the v2 skeleton input
domain is the normalized [0,1] interval with reject-on-out-of-domain
semantics instead).

Missing-data contract (differs from v1 BY DESIGN):
  * value None            -> factor missing; the axis renormalizes over the
                             present weights (never v1's 0.3 pay-for-absence
                             neutral, never a fabricated zero)
  * essential factor missing, or axis coverage below
    SCORING_POLICY["min_axis_coverage"]
                          -> score_status "insufficient_data", axis scores
                             and total_score None — no fake-precise number
  * 0.0 is a REAL zero (worst rank) and is never conflated with missing
  * values outside [0,1], NaN/inf, non-numeric types and unknown factor ids
    are REJECTED (ValueError), not silently coerced

Usage (pure, in-process, no DB):
    from score_v2 import ScoreV2Engine
    eng = ScoreV2Engine("general")
    result = eng.score({"roe_level": 0.8, "pe": 0.3, "momentum_6m_rel": 0.6, ...})
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
BASE = HERE.parent
if str(BASE / "migration_tools") not in sys.path:
    sys.path.insert(0, str(BASE / "migration_tools"))

import score_v2_config as CFG  # noqa: E402
import score_v4 as S4  # noqa: E402  (reused percentile engine)
import score_v4_config as V4CFG  # noqa: E402  (reused family mapping)

SCORE_STATUS_SCORED = "scored"
SCORE_STATUS_INSUFFICIENT = "insufficient_data"

FACTOR_SCORED = "scored"
FACTOR_MISSING = "missing"
FACTOR_NOT_IN_MODEL = "not_in_model"
FACTOR_NOT_IMPLEMENTED = "not_implemented"


def resolve_family(category_text: str | None) -> tuple[str, str]:
    """(family, family_status) — reuses V4's tested keyword mapping.

    A missing/empty category text yields ("general", "unclassified"): the
    company is scored on the general model but the output states plainly that
    no classification was available — it is never silently presented as a
    positive classification.
    """
    family = V4CFG.family_for_category(category_text)
    status = "classified" if category_text else "unclassified"
    return family, status


def percentile_normalize(cross_section: dict[str, dict[str, float | None]]
                         ) -> dict[str, dict[str, float | None]]:
    """Direction-aware cross-section normalization, reusing v4's midrank.

    {company: {factor_id: raw}} -> {company: {factor_id: percentile in
    [0,1] with 1.0 = best, or None}}. This is the entry point the raw-metric
    stage will feed; the skeleton itself consumes its output.
    """
    factor_ids: set[str] = set()
    for vals in cross_section.values():
        factor_ids.update(vals)
    ranked: dict[str, dict] = {}
    for fid in sorted(factor_ids):
        if fid not in CFG.V2_QVT_FACTORS:
            raise ValueError(f"unknown factor id {fid!r}")
        higher_is_better = CFG.V2_QVT_FACTORS[fid]["direction"] == "higher"
        vals = {cid: v.get(fid) for cid, v in cross_section.items()}
        ranked[fid] = S4.midrank(vals, higher_is_better)
    return {cid: {fid: ranked[fid][cid] for fid in ranked} for cid in cross_section}


class ScoreV2Engine:
    """Axis aggregator for one industry family. Pure — holds no DB state."""

    def __init__(self, family: str = "general"):
        if family not in CFG.FAMILIES:
            raise ValueError(
                f"unknown family {family!r}; valid families: {list(CFG.FAMILIES)}")
        self.family = family
        self._family_weights = CFG.FAMILY_WEIGHTS[family]

    # ------------------------------------------------------------------
    def score(self, factor_values: dict) -> dict:
        if not isinstance(factor_values, dict):
            raise ValueError("factor_values must be a dict {factor_id: value|None}")
        registry = CFG.V2_QVT_FACTORS
        unknown = sorted(k for k in factor_values if k not in registry)
        if unknown:
            raise ValueError(f"unknown factor ids: {unknown}")
        for fid, val in factor_values.items():
            if val is None:
                continue
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(
                    f"factor {fid!r}: expected a number in [0,1] or None, got {val!r}")
            f = float(val)
            if math.isnan(f) or math.isinf(f) or not (0.0 <= f <= 1.0):
                raise ValueError(
                    f"factor {fid!r}: {val!r} outside the normalized domain [0,1]")

        policy = CFG.SCORING_POLICY
        fam = self._family_weights
        axes: dict[str, dict] = {}
        breakdown: dict[str, dict] = {}

        for axis in CFG.AXIS_ORDER:
            axis_max = CFG.AXIS_WEIGHTS[axis]
            fmap = [(fid, w) for fid, w in fam.items()
                    if registry[fid]["axis"] == axis]
            scored: list[tuple[str, float, float]] = []
            missing: list[str] = []
            for fid, w in fmap:
                val = factor_values.get(fid)
                if val is None:
                    missing.append(fid)
                else:
                    scored.append((fid, w, float(val)))
            present_w = sum(w for _, w, _ in scored)
            coverage = round(present_w / axis_max, policy["breakdown_decimals"])
            missing_essential = [fid for fid in missing if registry[fid]["essential"]]
            insufficient = (
                bool(missing_essential)
                or present_w <= 0
                or coverage < policy["min_axis_coverage"]
            )
            if insufficient:
                axis_score = None
                contribution = None
            else:
                raw = sum(w * v for _, w, v in scored)
                axis_score = round(100.0 * raw / present_w, policy["score_decimals"])
                contribution = round(axis_max * axis_score / 100.0,
                                     policy["score_decimals"])
            axes[axis] = {
                "axis_max": axis_max,
                "scored_weight": round(present_w, 6),
                "coverage": coverage,
                "n_scored": len(scored),
                "n_model": len(fmap),
                "missing_essential": missing_essential,
                "score": axis_score,
                "contribution": contribution,
            }

        total = None
        if all(axes[a]["contribution"] is not None for a in CFG.AXIS_ORDER):
            total = round(sum(axes[a]["contribution"] for a in CFG.AXIS_ORDER),
                          policy["score_decimals"])
        status = (SCORE_STATUS_SCORED
                  if all(axes[a]["score"] is not None for a in CFG.AXIS_ORDER)
                  else SCORE_STATUS_INSUFFICIENT)

        scored_weight_total = sum(axes[a]["scored_weight"] for a in CFG.AXIS_ORDER)
        result = {
            "score_version": CFG.SCORE_VERSION,
            "model_family": self.family,
            "quality_score": axes["quality"]["score"],
            "valuation_score": axes["valuation"]["score"],
            "timing_score": axes["timing"]["score"],
            "quality_contribution": axes["quality"]["contribution"],
            "valuation_contribution": axes["valuation"]["contribution"],
            "timing_contribution": axes["timing"]["contribution"],
            "total_score": total,
            "score_status": status,
            "factor_breakdown": breakdown,
            "data_coverage": {
                "axes": {a: {k: axes[a][k] for k in
                             ("axis_max", "scored_weight", "coverage",
                              "n_scored", "n_model", "missing_essential")}
                         for a in CFG.AXIS_ORDER},
                "overall": round(scored_weight_total / 100.0,
                                 policy["breakdown_decimals"]),
            },
            # independent systems — skeleton phase: never read as approved/risk-free
            "confidence_status": CFG.CONFIDENCE["status"],
            "risk_status": CFG.RISK_GATE["status"],
        }

        for fid, spec in registry.items():
            in_model = fid in fam
            supplied = factor_values.get(fid)
            entry: dict = {"axis": spec["axis"]}
            if in_model:
                entry["weight"] = fam[fid]
                if supplied is None:
                    entry["status"] = FACTOR_MISSING
                    entry["input"] = None
                    entry["weighted_score"] = None
                    if spec["essential"]:
                        entry["note"] = "فاکتور حیاتی بدون داده — insufficient_data"
                else:
                    entry["status"] = FACTOR_SCORED
                    entry["input"] = float(supplied)
                    entry["weighted_score"] = round(
                        fam[fid] * float(supplied), policy["breakdown_decimals"])
            elif spec["availability"] == CFG.NEEDS_DEVELOPMENT:
                entry["status"] = FACTOR_NOT_IMPLEMENTED
                entry["weight"] = None
                entry["input"] = supplied
                entry["weighted_score"] = None
                if supplied is not None:
                    entry["note"] = ("فاکتور نیازمند توسعه است؛ ورودی نادیده گرفته "
                                     "شد و هیچ جایگزینی محاسبه نشد")
            else:
                entry["status"] = FACTOR_NOT_IN_MODEL
                entry["weight"] = None
                entry["input"] = supplied
                entry["weighted_score"] = None
            breakdown[fid] = entry

        return result


def score_company(category_text: str | None, factor_values: dict) -> dict:
    """Convenience entry: resolve the family from the TSETMC category text
    (reusing v4's mapping) and score. Adds family_status to the output."""
    family, family_status = resolve_family(category_text)
    result = ScoreV2Engine(family).score(factor_values)
    result["family_status"] = family_status
    return result
