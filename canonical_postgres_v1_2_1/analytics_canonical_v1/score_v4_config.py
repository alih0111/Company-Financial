"""Score v4 central configuration.

Every tunable of the v4 score lives here: category weights, per-family factor
weights, validity ranges, winsorization flags, sector blending, neutral
percentile, confidence components and penalty rules. Nothing else in the v4
pipeline may hard-code a weight.

Design contract (v4):
  * Category weights sum to exactly 100 — validated at import time, per family.
  * Each family's factor weights must sum to the same category maxima —
    validated at import time.
  * Score and confidence are independent outputs; confidence NEVER multiplies
    the score (ranking shrinkage uses `adjusted_score`, stored separately).
  * A missing factor input is neutral (percentile 0.5) and costs confidence,
    never score. An invalid input costs score (percentile 0) and confidence.
"""

from __future__ import annotations

SCORE_VERSION_V4 = "v4"
NEUTRAL_PERCENTILE = 0.5     # v3 used 0.30 — missing data dragged scores down
INVALID_PERCENTILE = 0.0     # invalid is economically bad: worst rank
MISSING_CONFIDENCE_PENALTY = 100.0 / 45.0   # per missing factor, in confidence points (45 = completeness weight)
INVALID_CONFIDENCE_PENALTY = 100.0 / 90.0   # invalid costs half a missing

# ----------------------------------------------------------------------------
# Categories — weights are the sum of their factors' weights in each family.
# ----------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    "growth": 25,
    "quality": 25,
    "valuation": 25,
    "financial_strength": 15,
    "market": 10,
}
CATEGORY_ORDER = ["growth", "quality", "valuation", "financial_strength", "market"]

# ----------------------------------------------------------------------------
# Sector-relative blending
# ----------------------------------------------------------------------------
SECTOR_WEIGHT = 0.50         # combined = 0.50*sector + 0.50*market percentile
MARKET_WEIGHT = 0.50
MIN_SECTOR_SAMPLE = 5        # sectors smaller than this fall back to market-only
# Below MIN_SECTOR_SAMPLE the blend weight decays linearly to zero at 1 member.
SECTOR_BLEND_DECAY = True

# Loss-making companies: book/sales multiples (P/B, P/S) of a loss-maker are
# trap-prone — the market is discounting broken fundamentals, not offering
# cheap value. Their book-multiple factors score NEUTRAL (like missing data)
# instead of rewarding statistical cheapness. P/E is already handled by the
# normalized-earnings median (median <= 0 -> missing).
LOSS_MAKER_VALUATION_NEUTRAL = True

# Anti-windfall valuation: the P/E factor is built on the median of the last
# N annual net profits (normalized earnings) instead of the TTM snapshot, so a
# single windfall quarter cannot make a company look statistically cheap.
NORMALIZED_YEARS = 3

# ----------------------------------------------------------------------------
# Sector (industry) -> model family mapping. Matched against the TSETMC
# category text in core.company_classification (lowercased, ZWNJ stripped).
# Order matters: first match wins. Default is "general".
# ----------------------------------------------------------------------------
FAMILY_KEYWORDS = [
    ("bank", ("بانک", "موسسات اعتباری")),
    ("insurance", ("بیمه",)),
    ("investment", ("سرمایه گذاری", "هلدینگ", "صندوق سرمایه", "نهادهای مالی واسط",
                    "توسعه", "leasing", "لیموزینگ")),
    # NOTE: "توسعه" (development) matches holding-style issuers (شرکت‌های توسعه‌ای)
    # which behave like investment companies in the canonical data.
]

# ----------------------------------------------------------------------------
# Factor configuration. Per factor:
#   category          — one of CATEGORY_ORDER
#   direction         — "higher" | "lower" (higher_is_better)
#   sector_relative   — whether the sector blend applies
#   valid             — (min, max) economic validity range; outside = INVALID
#   winsorize         — clip ranked values to P1/P99 of the universe
#   needs             — raw metric fields the blend reads (documentation/testing)
# Family weights below must sum to CATEGORY_WEIGHTS per category.
# ----------------------------------------------------------------------------
FACTOR_CONFIG = {
    # ---------------- growth ----------------
    "revenue_growth": {
        "category": "growth", "direction": "higher", "sector_relative": True,
        "valid": (-95.0, 400.0), "winsorize": True,
        "needs": ("revenue_growth", "sales_growth_12m", "sales_growth_3m", "revenue_cagr_3y"),
        "blend": {"revenue_growth": 0.50, "sales_growth_12m": 0.30, "sales_growth_3m": 0.20},
        "cagr_share": 0.25,  # when a 3y CAGR exists it takes this share of the blend
        "component_cap": 1000.0,
    },
    "earnings_growth": {
        "category": "growth", "direction": "higher", "sector_relative": True,
        "valid": (-95.0, 500.0), "winsorize": True,
        "needs": ("net_profit_growth", "eps_growth", "operating_profit_growth"),
        "blend": {"net_profit_growth": 0.55, "eps_growth": 0.25, "operating_profit_growth": 0.20},
        # a single component beyond this magnitude is a near-zero-denominator
        # artifact (e.g. 771,000,000% "growth"): drop that leg and renormalize
        # instead of invalidating the whole subfactor
        "component_cap": 1000.0,
    },
    "growth_acceleration": {
        "category": "growth", "direction": "higher", "sector_relative": False,
        "valid": (-200.0, 200.0), "winsorize": True,
        "needs": ("revenue_yoy_acceleration",),
    },
    "growth_consistency": {
        "category": "growth", "direction": "higher", "sector_relative": False,
        "valid": (0.0, 1.0), "winsorize": False,
        "needs": ("quarter_yoy_positive_fraction",),
    },
    # ---------------- quality ----------------
    "roe_level": {
        "category": "quality", "direction": "higher", "sector_relative": True,
        "valid": (-100.0, 150.0), "winsorize": True,
        "needs": ("roe",),
    },
    "roe_stability": {
        "category": "quality", "direction": "higher", "sector_relative": False,
        "valid": (0.0, 200.0), "winsorize": False,
        "needs": ("roe_volatility",),   # stdev of annual ROE — lower is better
    },
    "margins": {
        "category": "quality", "direction": "higher", "sector_relative": True,
        "valid": (-90.0, 90.0), "winsorize": True,
        "needs": ("operating_margin", "net_margin"),
        "blend": {"operating_margin": 0.60, "net_margin": 0.40},
    },
    "margin_trend": {
        "category": "quality", "direction": "higher", "sector_relative": True,
        "valid": (-40.0, 40.0), "winsorize": True,
        "needs": ("margin_trend",),
    },
    "cash_conversion": {
        "category": "quality", "direction": "higher", "sector_relative": True,
        "valid": (-2.0, 5.0), "winsorize": True,
        "needs": ("cash_conversion",),
    },
    "earnings_quality": {
        "category": "quality", "direction": "lower", "sector_relative": False,
        "valid": (0.0, 150.0), "winsorize": True,
        "needs": ("earnings_quality",),   # non-operating share of operating profit
    },
    "interest_coverage": {
        "category": "quality", "direction": "higher", "sector_relative": False,
        "valid": (0.0001, 60.0), "winsorize": True,
        "needs": ("interest_coverage",),
    },
    # ---------------- valuation ----------------
    "pe": {
        "category": "valuation", "direction": "lower", "sector_relative": True,
        "valid": (0.5, 60.0), "winsorize": True,
        "needs": ("pe",),
    },
    "pb": {
        "category": "valuation", "direction": "lower", "sector_relative": True,
        "valid": (0.1, 30.0), "winsorize": True,
        "needs": ("pb",),
    },
    "ps": {
        "category": "valuation", "direction": "lower", "sector_relative": True,
        "valid": (0.05, 40.0), "winsorize": True,
        "needs": ("ps",),
    },
    # ---------------- financial strength ----------------
    "leverage": {
        "category": "financial_strength", "direction": "lower", "sector_relative": True,
        "valid": (0.0, 2.5), "winsorize": True,
        "needs": ("debt_ratio",),
    },
    "current_ratio": {
        "category": "financial_strength", "direction": "higher", "sector_relative": False,
        "valid": (0.05, 25.0), "winsorize": True,
        "needs": ("current_ratio",),
    },
    "debt_trend": {
        "category": "financial_strength", "direction": "lower", "sector_relative": False,
        "valid": (-0.5, 0.5), "winsorize": True,
        "needs": ("debt_ratio_change",),   # debt_ratio now − a year ago (pp of assets)
    },
    # ---------------- market ----------------
    "momentum_6m_rel": {
        "category": "market", "direction": "higher", "sector_relative": False,
        "valid": (-95.0, 300.0), "winsorize": True,
        "needs": ("return_6m_rel_market",),
    },
    "momentum_3m_rel": {
        "category": "market", "direction": "higher", "sector_relative": False,
        "valid": (-95.0, 200.0), "winsorize": True,
        "needs": ("return_3m_rel_market",),
    },
    "relative_strength_6m_sector": {
        "category": "market", "direction": "higher", "sector_relative": False,
        "valid": (-95.0, 300.0), "winsorize": True,
        "needs": ("return_6m_rel_sector",),
    },
    "liquidity": {
        "category": "market", "direction": "higher", "sector_relative": False,
        "valid": (0.0, None), "winsorize": True,
        "needs": ("avg_trade_value_30d",),
    },
    "low_volatility": {
        "category": "market", "direction": "lower", "sector_relative": False,
        "valid": (0.0, 15.0), "winsorize": True,
        "needs": ("volatility_30d",),
    },
}

# ----------------------------------------------------------------------------
# Model families: per-family factor weights. Factors absent from a family are
# NOT scored for it (no neutral, no confidence cost — they do not belong to the
# model). Every family must satisfy the category maxima.
# ----------------------------------------------------------------------------
FACTOR_FAMILIES = {
    "general": {
        "revenue_growth": 8, "earnings_growth": 7, "growth_acceleration": 5, "growth_consistency": 5,
        "roe_level": 5, "roe_stability": 3, "margins": 5, "margin_trend": 3,
        "cash_conversion": 4, "earnings_quality": 3, "interest_coverage": 2,
        "pe": 9, "pb": 8, "ps": 8,
        "leverage": 7, "current_ratio": 4, "debt_trend": 4,
        "momentum_6m_rel": 3, "momentum_3m_rel": 2, "relative_strength_6m_sector": 2,
        "liquidity": 2, "low_volatility": 1,
    },
    # Banks: current ratio / cash conversion / interest coverage and P/S are not
    # meaningful for deposit-funded balance sheets; P/B leads valuation.
    "bank": {
        "revenue_growth": 8, "earnings_growth": 7, "growth_acceleration": 5, "growth_consistency": 5,
        "roe_level": 6, "roe_stability": 3, "margins": 6, "margin_trend": 4, "earnings_quality": 3,
        "cash_conversion": 3,
        "pe": 9, "pb": 16,
        "leverage": 9, "debt_trend": 6,
        "momentum_6m_rel": 3, "momentum_3m_rel": 2, "relative_strength_6m_sector": 2,
        "liquidity": 2, "low_volatility": 1,
    },
    # Insurance: premium growth ~ revenue growth, investment income dominates
    # non-operating; current ratio / cash conversion excluded, P/B-led valuation.
    "insurance": {
        "revenue_growth": 8, "earnings_growth": 7, "growth_acceleration": 5, "growth_consistency": 5,
        "roe_level": 6, "roe_stability": 3, "margins": 6, "margin_trend": 4, "earnings_quality": 3,
        "cash_conversion": 3,
        "pe": 9, "pb": 16,
        "leverage": 9, "debt_trend": 6,
        "momentum_6m_rel": 3, "momentum_3m_rel": 2, "relative_strength_6m_sector": 2,
        "liquidity": 2, "low_volatility": 1,
    },
    # Investment / holding: earnings are portfolio marks; P/B and earnings growth
    # carry the model, operating-margin machinery is excluded.
    "investment": {
        "revenue_growth": 6, "earnings_growth": 9, "growth_acceleration": 5, "growth_consistency": 5,
        "roe_level": 8, "roe_stability": 5, "margin_trend": 4, "earnings_quality": 4,
        "cash_conversion": 4,
        "pe": 9, "pb": 16,
        "leverage": 8, "current_ratio": 3, "debt_trend": 4,
        "momentum_6m_rel": 3, "momentum_3m_rel": 2, "relative_strength_6m_sector": 2,
        "liquidity": 2, "low_volatility": 1,
    },
}

# ----------------------------------------------------------------------------
# Confidence model — independent of the score. Components sum to 100.
# ----------------------------------------------------------------------------
CONFIDENCE_COMPONENTS = {
    # share of the family's factor inputs whose status is VALID
    "completeness": 45,
    # months since the latest eligible profit-bearing report: <=3 full credit,
    # linear decay to 0 at 15 months
    "financial_freshness": 20,
    # days since the latest market observation: <=7 full credit, 0 at 30
    "market_freshness": 15,
    # monthly-activity coverage (>=6 rows half credit)
    "monthly_coverage": 10,
    # data anomalies (sign mismatch, TTM method mismatch, share-base mismatch,
    # fiscal calendar unknown): equal share of the remaining weight
    "anomalies": 10,
}

# freshness thresholds (NOT weights — excluded from the sum-100 validation)
CONFIDENCE_THRESHOLDS = {
    "financial_fresh_full_months": 3,
    "financial_fresh_dead_months": 15,
    "market_fresh_full_days": 7,
    "market_fresh_dead_days": 30,
}

# ----------------------------------------------------------------------------
# Penalty engine — only for risks the factor scores cannot capture. Every rule
# is evidence-based on canonical data; rules whose evidence is not collected
# (auditor opinion, going concern) are deliberately absent.
# ----------------------------------------------------------------------------
PENALTY_RULES = {
    "negative_equity": {"penalty": 6.0,
                        "reason": "حقوق مالکانه منفی یا صفر"},
    "extreme_leverage": {"penalty": 4.0, "threshold": 0.85,
                         "reason": "اهرم مالی افراطی (بدهی > ۸۵٪ دارایی‌ها)"},
    "stale_filing": {"penalty": 5.0, "max_age_months": 12,
                     "reason": "گزارش سود قدیمی‌تر از ۱۲ ماه"},
    "multi_quarter_deterioration": {"penalty": 5.0, "consecutive": 3,
                                    "reason": "افت سود TTM در ۳ فصل متوالی"},
    "suspicious_earnings": {"penalty": 4.0, "threshold": 100.0,
                            "reason": "سود عملیاتی غیرعملیاتی بیش از ۱۰۰٪ سود عملیاتی"},
    "earnings_spike": {"penalty": 4.0, "spike_ratio": 2.5, "cash_backing_max": 0.6,
                       "quarter_concentration_min": 0.6,
                       "reason": "سود جاری بیش از ۲٫۵ برابر میانه‌ی سود سالانه‌ی اخیر بدون پشتوانه‌ی نقدی یا با تمرکز یک فصل (سود غیرتکرارشونده)"},
}
PENALTY_CAP = 20.0

# ----------------------------------------------------------------------------
# Runtime validation — a broken config must fail loudly here, not silently in
# a score run.
# ----------------------------------------------------------------------------
def _strip_zwnj(s: str) -> str:
    return s.replace("\u200c", " ").strip().lower()


def family_for_category(category_text: str | None) -> str:
    if not category_text:
        return "general"
    t = _strip_zwnj(category_text)
    for family, keywords in FAMILY_KEYWORDS:
        for kw in keywords:
            if kw in t:
                return family
    return "general"


def _validate() -> None:
    if sum(CATEGORY_WEIGHTS.values()) != 100:
        raise ValueError(f"v4 category weights must sum to 100, got {sum(CATEGORY_WEIGHTS.values())}")
    if set(CATEGORY_WEIGHTS) != set(CATEGORY_ORDER):
        raise ValueError("CATEGORY_ORDER and CATEGORY_WEIGHTS keys disagree")
    unknown = {f["category"] for f in FACTOR_CONFIG.values()} - set(CATEGORY_ORDER)
    if unknown:
        raise ValueError(f"factor config references unknown categories: {unknown}")
    for family, weights in FACTOR_FAMILIES.items():
        unknown_factors = set(weights) - set(FACTOR_CONFIG)
        if unknown_factors:
            raise ValueError(f"family {family} references unknown factors: {unknown_factors}")
        sums: dict[str, float] = {}
        for fcode, w in weights.items():
            cat = FACTOR_CONFIG[fcode]["category"]
            sums[cat] = sums.get(cat, 0.0) + w
        for cat, target in CATEGORY_WEIGHTS.items():
            got = sums.get(cat, 0.0)
            if abs(got - target) > 1e-9:
                raise ValueError(
                    f"family {family!r} category {cat!r} weights sum to {got}, expected {target}")
    total = sum(CONFIDENCE_COMPONENTS.values())
    if total != 100:
        raise ValueError(f"confidence components must sum to 100, got {total}")


_validate()
