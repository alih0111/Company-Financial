"""Canonical Score v2 (QVT) — central configuration.

score_version = "canonical-v2-qvt". Three independent axes:

  Q (quality)    — شرکت باکیفیت           max 40
  V (valuation)  — ارزندگی                max 35
  T (timing)     — شرایط ورود             max 25

plus two independent systems that are ARCHITECTURE-ONLY in this skeleton
phase — they must never read as approved or risk-free:

  Data Confidence — CONFIDENCE["status"] = "not_evaluated"
  Risk Gate       — RISK_GATE["status"]  = "not_evaluated"

Reuse contract with Score v4 (deliberate, no duplicated algorithms):
  * industry family mapping (general/bank/insurance/investment) is REUSED
    from score_v4_config.family_for_category — V2 carries no keyword table of
    its own, so both engines classify a TSETMC category identically. V4's
    tested contract: first keyword match over the ZWNJ-stripped lowercased
    category text (bank -> insurance -> investment), default "general".
  * percentile ranking reuses score_v4.midrank (see score_v2.py).
  * V2 does NOT reuse V4's category weights/factor set, and does NOT repeat
    V1's 0.3 missing-neutral (see SCORING_POLICY below).

Design contracts (v2):
  * AXIS_WEIGHTS sum to exactly 100 — validated at import.
  * Per family, the READY factor weights of every axis sum exactly to that
    axis's max — validated at import.
  * Factors marked needs_development (roic, ev_ebit, fcf_yield,
    distance_from_52w_high) carry a target_weight for the final design but
    are NOT in any family map and are NEVER scored — no automatic surrogate,
    no fabricated input (داده معتبرشان هنوز کامل نیست). Activating one is a
    config recalibration (re-carve the family maps), never an engine change.
  * A missing factor renormalizes the axis over present weights; a missing
    ESSENTIAL factor or axis coverage below
    SCORING_POLICY["min_axis_coverage"] yields score_status
    "insufficient_data" and total_score None — no fake-precise number.
  * Changing industrial weights = editing FAMILY_WEIGHTS (pure data); the
    engine reads it unchanged.
  * Composite factors (margins, earnings_growth) carry an APPROVED internal
    component-weight table COMPOSITE_COMPONENT_WEIGHTS (step 2-B-3-B):
    factor_blend_score = Σ w_c · percentile_combined_c, produced only when
    EVERY component is valid AND ranked — no partial blend, no weight
    redistribution, never re-ranked. General family only; specialized
    families keep pending_blend until their own evidence-based contracts
    exist (presence in FAMILY_WEIGHTS activates nothing).
"""

from __future__ import annotations

import math

SCORE_VERSION = "canonical-v2-qvt"

AXIS_ORDER = ["quality", "valuation", "timing"]
AXIS_WEIGHTS = {"quality": 40, "valuation": 35, "timing": 25}
AXIS_OUTPUT_FIELDS = {
    "quality": ("quality_score", "quality_contribution"),
    "valuation": ("valuation_score", "valuation_contribution"),
    "timing": ("timing_score", "timing_contribution"),
}

# Industry model families — SAME contract as v4 (see module docstring).
FAMILIES = ("general", "bank", "insurance", "investment")

READY = "ready"
NEEDS_DEVELOPMENT = "needs_development"

# -----------------------------------------------------------------------------
# Factor registry. Per factor:
#   axis            — one of AXIS_ORDER
#   direction       — "higher" | "lower" (higher_is_better on the RAW metric;
#                     skeleton inputs are already direction-normalized to
#                     1.0 = best, direction is kept for the raw stage)
#   availability    — READY | NEEDS_DEVELOPMENT
#   target_weight   — intended weight in the final design (baseline = the
#                     "general" family map for ready factors, validated)
#   essential       — missing value forces score_status "insufficient_data"
#                     (only binding for families whose map includes the factor)
#   industry_method — optional per-family evaluation note (architecture hook;
#                     no full per-industry model is built in this phase)
# -----------------------------------------------------------------------------
V2_QVT_FACTORS = {
    # ---------------- Q — کیفیت بنیادی (40) ----------------
    "roe_level": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 7, "essential": True,
        "note": "بازدهی حقوق مالکانه — هسته‌ی کیفیت سودآوری",
    },
    "roe_stability": {
        "axis": "quality", "direction": "lower", "availability": READY,
        "target_weight": 3, "essential": False,
        "note": "نوسان‌پذیری ROE سالانه — کمتر بهتر",
    },
    "margins": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 6, "essential": True,
        "note": "حاشیه سود عملیاتی/خالص (ترکیب موزون)",
    },
    "margin_trend": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 3, "essential": False,
        "note": "روند حاشیه سود عملیاتی TTM نسبت به سال قبل — تفاضل برحسب "
                "واحد درصد از پایه‌های TTM سال قبل (گام ۲-ب-۵؛ فیلد مشتق "
                "موتور که TTM را با YTD هم‌گزارش مقایسه می‌کند استفاده "
                "نمی‌شود)",
    },
    "cash_conversion": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 4, "essential": False,
        "note": "تبدیل سود به وجه نقد",
    },
    "earnings_quality": {
        "axis": "quality", "direction": "lower", "availability": READY,
        "target_weight": 3, "essential": False,
        "note": "سهم وابستگی به اقلام غیرعملیاتی از سود عملیاتی TTM هم‌دوره — "
                "کمتر بهتر (گام ۲-ب-۷: صورت TTM درون‌گزارشی؛ فقط روی سود "
                "عملیاتی مثبت؛ نماینده «کیفیت کامل سود» یا کیفیت نقدی "
                "نیست)",
    },
    "interest_coverage": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 3, "essential": False,
        "note": "پوشش هزینه مالی بر پایه سود عملیاتی TTM هم‌دوره — proxy "
                "پوشش، نه EBIT استاندارد (گام ۲-ب-۷: مخرج finance_cost_ttm "
                "درون‌گزارشی؛ هزینه صفر یا قرارداد علامت ناسازگار → "
                "not_applicable)",
    },
    "leverage": {
        "axis": "quality", "direction": "lower", "availability": READY,
        "target_weight": 4, "essential": False,
        "note": "نسبت بدهی به دارایی — کمتر بهتر",
    },
    "revenue_growth": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 4, "essential": False,
        "note": "رشد فروش — مقایسه هم‌گزارش order-1/order-2 همان پنجره "
                "(گام ۲-ب-۵؛ ترکیب ۱۲م/۳م/CAGR طرح اولیه کنار گذاشته شد)",
    },
    "earnings_growth": {
        "axis": "quality", "direction": "higher", "availability": READY,
        "target_weight": 3, "essential": False,
        "note": "رشد سود (ترکیب سود خالص/EPS/عملیاتی در مرحله خام)",
    },
    "roic": {
        "axis": "quality", "direction": "higher", "availability": NEEDS_DEVELOPMENT,
        "target_weight": 5, "essential": False,
        "note": "نیازمند NOPAT و دارایی‌های عملیاتی؛ داده معتبر هنوز کامل نیست — "
                "هیچ جایگزین خودکاری مجاز نیست",
    },
    # ---------------- V — ارزندگی (35) ----------------
    "pe": {
        "axis": "valuation", "direction": "lower", "availability": READY,
        "target_weight": 13, "essential": True,
        "note": "P/E نرمال‌شده (میانه سود سالانه؛ ضد باد-به-توسعه) — الگوی V4",
        "industry_method": {
            "bank": "محور P/B؛ P/E روی سود بانکداری",
            "insurance": "محور P/B",
            "investment": "محور P/B",
        },
    },
    "pb": {
        "axis": "valuation", "direction": "lower", "availability": READY,
        "target_weight": 12, "essential": True,
        "note": "P/B — برای بانک/بیمه/سرمایه‌گذاری وزن غالب",
    },
    "ps": {
        "axis": "valuation", "direction": "lower", "availability": READY,
        "target_weight": 10, "essential": False,
        "note": "P/S — فقط خانواده general (برای بانک/بیمه بی‌معناست، الگوی V4)",
    },
    "ev_ebit": {
        "axis": "valuation", "direction": "lower", "availability": NEEDS_DEVELOPMENT,
        "target_weight": 6, "essential": False,
        "note": "نیازمند EBIT استانداردشده و خالص بدهی؛ داده هنوز کامل نیست — "
                "هیچ جایگزین خودکاری مجاز نیست",
    },
    "fcf_yield": {
        "axis": "valuation", "direction": "higher", "availability": NEEDS_DEVELOPMENT,
        "target_weight": 5, "essential": False,
        "note": "نیازمند TTM جریان وجه نقد آزاد از صورت جریان وجوه نقد؛ داده "
                "هنوز کامل نیست — هیچ جایگزین خودکاری مجاز نیست",
    },
    # ---------------- T — شرایط ورود (25) ----------------
    "momentum_6m_rel": {
        "axis": "timing", "direction": "higher", "availability": READY,
        "target_weight": 7, "essential": True,
        "note": "بازده ۶ ماهه نسبی به بازار",
    },
    "momentum_3m_rel": {
        "axis": "timing", "direction": "higher", "availability": READY,
        "target_weight": 5, "essential": False,
        "note": "بازده ۳ ماهه نسبی به بازار",
    },
    "relative_strength_6m_sector": {
        "axis": "timing", "direction": "higher", "availability": READY,
        "target_weight": 5, "essential": False,
        "note": "قدرت نسبی ۶ ماهه در صنعت",
    },
    "liquidity": {
        "axis": "timing", "direction": "higher", "availability": READY,
        "target_weight": 4, "essential": True,
        "note": "ارزش معاملات ۳۰ روزه",
    },
    "low_volatility": {
        "axis": "timing", "direction": "lower", "availability": READY,
        "target_weight": 4, "essential": False,
        "note": "نوسان ۳۰ روزه — کمتر بهتر",
    },
    "distance_from_52w_high": {
        "axis": "timing", "direction": "higher", "availability": NEEDS_DEVELOPMENT,
        "target_weight": 4, "essential": False,
        "note": "نیازمند تاریخچه قیمتی ۵۲ هفته در موتور؛ داده هنوز کامل نیست — "
                "هیچ جایگزین خودکاری مجاز نیست",
    },
}

# -----------------------------------------------------------------------------
# Per-family factor weights — READY factors only (planned factors must NEVER
# appear here; validated at import). Every family must satisfy the axis
# maxima exactly. Editing this table re-calibrates any industry without
# touching the engine.
#
# Family calibrations follow the v4 evidence base:
#   bank / insurance — deposit-funded balance sheets: cash_conversion,
#     interest_coverage and P/S are not meaningful; P/B leads valuation.
#   investment — earnings are portfolio marks: operating-margin machinery
#     (margins, cash_conversion, interest_coverage) excluded; P/B-led.
# -----------------------------------------------------------------------------
FAMILY_WEIGHTS = {
    "general": {
        # Q: 7+3+6+3+4+3+3+4+4+3 = 40
        "roe_level": 7, "roe_stability": 3, "margins": 6, "margin_trend": 3,
        "cash_conversion": 4, "earnings_quality": 3, "interest_coverage": 3,
        "leverage": 4, "revenue_growth": 4, "earnings_growth": 3,
        # V: 13+12+10 = 35
        "pe": 13, "pb": 12, "ps": 10,
        # T: 7+5+5+4+4 = 25
        "momentum_6m_rel": 7, "momentum_3m_rel": 5,
        "relative_strength_6m_sector": 5, "liquidity": 4, "low_volatility": 4,
    },
    "bank": {
        # Q: 8+3+7+4+3+6+5+4 = 40 (no cash_conversion / interest_coverage)
        "roe_level": 8, "roe_stability": 3, "margins": 7, "margin_trend": 4,
        "earnings_quality": 3, "leverage": 6, "revenue_growth": 5,
        "earnings_growth": 4,
        # V: 13+22 = 35 (P/B-led, no P/S)
        "pe": 13, "pb": 22,
        # T: 25
        "momentum_6m_rel": 7, "momentum_3m_rel": 5,
        "relative_strength_6m_sector": 5, "liquidity": 4, "low_volatility": 4,
    },
    "insurance": {
        # Q: 8+3+7+4+3+6+5+4 = 40
        "roe_level": 8, "roe_stability": 3, "margins": 7, "margin_trend": 4,
        "earnings_quality": 3, "leverage": 6, "revenue_growth": 5,
        "earnings_growth": 4,
        # V: 13+22 = 35
        "pe": 13, "pb": 22,
        # T: 25
        "momentum_6m_rel": 7, "momentum_3m_rel": 5,
        "relative_strength_6m_sector": 5, "liquidity": 4, "low_volatility": 4,
    },
    "investment": {
        # Q: 9+5+4+4+7+5+6 = 40 (no margins / cash_conversion / interest_coverage)
        "roe_level": 9, "roe_stability": 5, "margin_trend": 4,
        "earnings_quality": 4, "leverage": 7, "revenue_growth": 5,
        "earnings_growth": 6,
        # V: 13+22 = 35
        "pe": 13, "pb": 22,
        # T: 25
        "momentum_6m_rel": 7, "momentum_3m_rel": 5,
        "relative_strength_6m_sector": 5, "liquidity": 4, "low_volatility": 4,
    },
}

# -----------------------------------------------------------------------------
# Composite-factor internal component weights (step 2-B-3-B) — the approved
# blend contract for the two composite Q factors. In the normalization rollup
# (score_v2_normalize), factor_blend_score = Σ_c w_c · percentile_combined_c
# is produced ONLY when every component of the factor is valid AND ranked:
# all-or-nothing — no partial blend, no redistribution of a missing
# component's weight, no fabricated 0 / 0.5 substitute for absent data, and
# the result is a [0, 1] SCORE, never re-ranked into a "percentile".
#
# Scope: the "general" family ONLY. bank / insurance / investment keep the
# pending_blend contract until their own specialized, evidence-based
# contracts are ratified — presence in FAMILY_WEIGHTS does NOT activate this
# table for them. Exact agreement of the component keys with the raw layer's
# real components is enforced at blend time in score_v2_normalize (a
# mismatch refuses the blend instead of producing a wrong one).
#
# Calibration (financial architect, step 2-B-3-A/B — provisional and open to
# backtest recalibration; recalibration = editing this table, never code):
#   margins 0.60 operating / 0.40 net — the below-the-line dimension is
#     already represented by roe_level / interest_coverage /
#     earnings_quality, while the operating line has no other Q
#     representative; net margin keeps a real weight because the
#     operating/net gap is itself a quality signal.
#   earnings_growth 0.50 / 0.50 — the raw layer's state classification
#     already surfaces pathological sign-change cases as component absence
#     (not values), net-earnings momentum is measured by no other Q factor,
#     and the factor's axis weight is small (3 of 40).
# -----------------------------------------------------------------------------
COMPOSITE_COMPONENT_WEIGHTS = {
    "general": {
        "margins": {
            "operating_margin_pct": 0.60,
            "net_margin_pct": 0.40,
        },
        "earnings_growth": {
            "operating_profit_growth_pct": 0.50,
            "net_profit_growth_pct": 0.50,
        },
    },
}

# The exact component sets score_v2_raw builds for each composite factor —
# mirrored here so a table that drops, renames or invents a component fails
# loudly AT IMPORT, not just at blend time. The mirror itself is pinned
# against the real raw output by the normalization test
# test_config_weights_match_raw_components_exactly, and the normalize rollup
# independently refuses any residual mismatch (pending_blend, never a wrong
# blend).
COMPOSITE_EXPECTED_COMPONENTS = {
    "margins": ("operating_margin_pct", "net_margin_pct"),
    "earnings_growth": ("operating_profit_growth_pct",
                        "net_profit_growth_pct"),
}

# -----------------------------------------------------------------------------
# Scoring policy — the missing-data contract of v2 (deliberately NOT v1's
# 0.3 neutral, which paid points for absent data; and NOT a fabricated zero):
# renormalize over present weights; fail loud with "insufficient_data" when
# data is critically incomplete.
# -----------------------------------------------------------------------------
SCORING_POLICY = {
    "min_axis_coverage": 0.50,
    "missing_factor_handling": "renormalize_present_weights",
    "insufficient_data_on_essential_missing": True,
    "score_decimals": 2,
    "breakdown_decimals": 4,
}

# -----------------------------------------------------------------------------
# Data Confidence — INDEPENDENT system, never a multiplier of the score
# (v1 multiplied DQ into the score; that contract is dead in v2/v4).
# Skeleton phase: NOT evaluated, must never read as approved.
# -----------------------------------------------------------------------------
CONFIDENCE = {
    "status": "not_evaluated",
    "design": "استقلال کامل از امتیاز؛ در فاز بعد از ساختار "
              "CONFIDENCE_COMPONENTS موتور V4 (کامل‌بودن/تازگی مالی/تازگی "
              "بازار/پوشش ماهانه/ناهنجاری‌ها) استفاده مجدد می‌شود",
}

# -----------------------------------------------------------------------------
# Risk Gate — INDEPENDENT system, evidence-based rules only (v4's
# PENALTY_RULES structure is the template). Skeleton phase: NOT evaluated;
# rules block intentionally empty and extensible.
# -----------------------------------------------------------------------------
RISK_GATE = {
    "status": "not_evaluated",
    "enabled": False,
    "rules": {},
    "design": "فقط قواعد مبتنی بر شواهد؛ الگوی PENALTY_RULES موتور V4",
}


# -----------------------------------------------------------------------------
# Runtime validation — a broken config must fail loudly here, not silently in
# a score run.
# -----------------------------------------------------------------------------
def _validate_composite_component_weights(table) -> None:
    """Structural validation of COMPOSITE_COMPONENT_WEIGHTS (step 2-B-3-B).

    Runs at import over the shipped table and is unit-testable directly.
    Checks: known family; known READY factor; non-empty component map; every
    weight a finite non-bool real number with POSITIVE value (every listed
    component is required — a zero weight would be a silent omission);
    weights summing to exactly 1 within a 1e-9 tolerance, summed with
    math.fsum over sorted keys so the check is independent of dict order.
    The exact-match against the raw layer's real component names is enforced
    at blend time in score_v2_normalize (refusal, never a wrong blend).
    """
    if not isinstance(table, dict) or not table:
        raise ValueError(
            "COMPOSITE_COMPONENT_WEIGHTS must be a non-empty dict of "
            "family -> factor -> component weights")
    for family, factors in table.items():
        if family not in FAMILIES:
            raise ValueError(
                f"COMPOSITE_COMPONENT_WEIGHTS: unknown family {family!r}")
        if not isinstance(factors, dict) or not factors:
            raise ValueError(
                f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}] must be a "
                "non-empty dict of factor -> component weights")
        for fid, weights in factors.items():
            if fid not in V2_QVT_FACTORS:
                raise ValueError(
                    f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}]: unknown "
                    f"factor {fid!r}")
            if V2_QVT_FACTORS[fid]["availability"] != READY:
                raise ValueError(
                    f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]: a "
                    "needs_development factor must never get a blend table")
            if fid in COMPOSITE_EXPECTED_COMPONENTS and \
                    set(weights) != set(COMPOSITE_EXPECTED_COMPONENTS[fid]):
                raise ValueError(
                    f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]: "
                    f"component keys {sorted(weights)} do not exactly match "
                    f"the raw layer's real components "
                    f"{sorted(COMPOSITE_EXPECTED_COMPONENTS[fid])}")
            if not isinstance(weights, dict) or not weights:
                raise ValueError(
                    f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}] must "
                    "be a non-empty dict of component weights")
            for comp, w in weights.items():
                if isinstance(w, bool) or not isinstance(w, (int, float)):
                    raise ValueError(
                        f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]"
                        f"[{comp!r}]: weight must be a real number, got "
                        f"{w!r}")
                if not math.isfinite(w):
                    raise ValueError(
                        f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]"
                        f"[{comp!r}]: weight must be finite, got {w!r}")
                if w <= 0:
                    raise ValueError(
                        f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]"
                        f"[{comp!r}]: every required component must carry a "
                        f"POSITIVE weight, got {w!r}")
            total = math.fsum(weights[c] for c in sorted(weights))
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"COMPOSITE_COMPONENT_WEIGHTS[{family!r}][{fid!r}]: "
                    f"component weights must sum to 1, got {total!r}")


def _validate() -> None:
    if sum(AXIS_WEIGHTS.values()) != 100:
        raise ValueError(f"v2 axis weights must sum to 100, got {sum(AXIS_WEIGHTS.values())}")
    if set(AXIS_WEIGHTS) != set(AXIS_ORDER):
        raise ValueError("AXIS_ORDER and AXIS_WEIGHTS keys disagree")
    for axis, w in AXIS_WEIGHTS.items():
        if w <= 0:
            raise ValueError(f"axis {axis!r} weight must be positive, got {w}")
        if axis not in AXIS_OUTPUT_FIELDS:
            raise ValueError(f"axis {axis!r} has no output-field mapping")

    for fid, spec in V2_QVT_FACTORS.items():
        if spec["axis"] not in AXIS_ORDER:
            raise ValueError(f"factor {fid!r} references unknown axis {spec['axis']!r}")
        if spec["direction"] not in ("higher", "lower"):
            raise ValueError(f"factor {fid!r}: invalid direction {spec['direction']!r}")
        if spec["availability"] not in (READY, NEEDS_DEVELOPMENT):
            raise ValueError(f"factor {fid!r}: invalid availability {spec['availability']!r}")
        if not isinstance(spec["target_weight"], int) or spec["target_weight"] <= 0:
            raise ValueError(f"factor {fid!r}: target_weight must be a positive int")
        if not isinstance(spec["essential"], bool):
            raise ValueError(f"factor {fid!r}: essential must be bool")
        if spec["availability"] == NEEDS_DEVELOPMENT and spec["essential"]:
            raise ValueError(f"factor {fid!r}: a needs_development factor cannot be essential")

    ready = {fid for fid, s in V2_QVT_FACTORS.items() if s["availability"] == READY}
    planned = set(V2_QVT_FACTORS) - ready
    if set(FAMILY_WEIGHTS) != set(FAMILIES):
        raise ValueError("FAMILY_WEIGHTS keys must match FAMILIES exactly")
    for family, weights in FAMILY_WEIGHTS.items():
        unknown = set(weights) - set(V2_QVT_FACTORS)
        if unknown:
            raise ValueError(f"family {family!r} references unknown factors: {unknown}")
        leaked = set(weights) & planned
        if leaked:
            raise ValueError(
                f"family {family!r} scores needs_development factors {sorted(leaked)} — "
                "no automatic surrogate is allowed")
        sums: dict[str, float] = {}
        for fid, w in weights.items():
            if w <= 0:
                raise ValueError(f"family {family!r} factor {fid!r}: weight must be positive")
            sums[V2_QVT_FACTORS[fid]["axis"]] = sums.get(V2_QVT_FACTORS[fid]["axis"], 0.0) + w
        for axis, target in AXIS_WEIGHTS.items():
            got = sums.get(axis, 0.0)
            if abs(got - target) > 1e-9:
                raise ValueError(
                    f"family {family!r} axis {axis!r} weights sum to {got}, expected {target}")
        # every axis must keep at least one essential factor in each family
        for axis in AXIS_ORDER:
            essentials = [fid for fid in weights
                          if V2_QVT_FACTORS[fid]["axis"] == axis
                          and V2_QVT_FACTORS[fid]["essential"]]
            if not essentials:
                raise ValueError(f"family {family!r} axis {axis!r} has no essential factor")
    # baseline calibration: general carries every ready factor at its target weight
    for fid in ready:
        if fid not in FAMILY_WEIGHTS["general"]:
            raise ValueError(f"ready factor {fid!r} missing from the general family map")
        if FAMILY_WEIGHTS["general"][fid] != V2_QVT_FACTORS[fid]["target_weight"]:
            raise ValueError(
                f"factor {fid!r}: general weight {FAMILY_WEIGHTS['general'][fid]} "
                f"!= target_weight {V2_QVT_FACTORS[fid]['target_weight']}")

    if not 0 < SCORING_POLICY["min_axis_coverage"] <= 1:
        raise ValueError("min_axis_coverage must be in (0, 1]")
    _validate_composite_component_weights(COMPOSITE_COMPONENT_WEIGHTS)
    # skeleton-phase gates: the two independent systems must not read as evaluated
    if CONFIDENCE["status"] != "not_evaluated":
        raise ValueError("CONFIDENCE must stay not_evaluated until its stage is implemented")
    if RISK_GATE["status"] != "not_evaluated" or RISK_GATE["rules"]:
        raise ValueError("RISK_GATE must stay not_evaluated with no rules until implemented")


_validate()
