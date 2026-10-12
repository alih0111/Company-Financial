"""Score v2 (QVT) skeleton unit tests — pure, no database.

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import score_v2_config as CFG  # noqa: E402
import score_v2 as S2  # noqa: E402
import score_v4_config as V4CFG  # noqa: E402
import compute_metrics as CM  # noqa: E402


def full_input(family: str = "general") -> dict:
    """Every factor the family scores, at the best normalized value."""
    return {fid: 1.0 for fid in CFG.FAMILY_WEIGHTS[family]}


def zero_input(family: str = "general") -> dict:
    """Every factor the family scores, at a REAL zero (worst — not missing)."""
    return {fid: 0.0 for fid in CFG.FAMILY_WEIGHTS[family]}


# ---------------------------------------------------------------------------
# 1. Config validation
# ---------------------------------------------------------------------------
def test_axis_weights_sum_to_100():
    assert sum(CFG.AXIS_WEIGHTS.values()) == 100
    assert CFG.AXIS_WEIGHTS == {"quality": 40, "valuation": 35, "timing": 25}
    for family, weights in CFG.FAMILY_WEIGHTS.items():
        sums = {}
        for fid, w in weights.items():
            sums[CFG.V2_QVT_FACTORS[fid]["axis"]] = \
                sums.get(CFG.V2_QVT_FACTORS[fid]["axis"], 0) + w
        assert sums == CFG.AXIS_WEIGHTS, family


def test_config_validation_rejects_bad_configs(monkeypatch):
    with pytest.raises(ValueError):
        broken = dict(CFG.AXIS_WEIGHTS, quality=39)
        monkeypatch.setattr(CFG, "AXIS_WEIGHTS", broken)
        CFG._validate()
    monkeypatch.setattr(CFG, "AXIS_WEIGHTS",
                        {"quality": 40, "valuation": 35, "timing": 25})

    with pytest.raises(ValueError):
        bad_w = dict(CFG.FAMILY_WEIGHTS["general"], pe=-13)
        monkeypatch.setattr(CFG, "FAMILY_WEIGHTS",
                            dict(CFG.FAMILY_WEIGHTS, general=bad_w))
        CFG._validate()
    with pytest.raises(ValueError):
        # a needs_development factor must never enter a family map (no surrogate)
        leaked = dict(CFG.FAMILY_WEIGHTS["general"], roic=5)
        monkeypatch.setattr(CFG, "FAMILY_WEIGHTS",
                            dict(CFG.FAMILY_WEIGHTS, general=leaked))
        CFG._validate()
    with pytest.raises(ValueError):
        monkeypatch.setattr(CFG, "FAMILY_WEIGHTS",
                            dict(CFG.FAMILY_WEIGHTS, bank={"nonexistent": 5}))
        CFG._validate()
    monkeypatch.undo()
    CFG._validate()  # restored config is clean


# ---------------------------------------------------------------------------
# 2. Full input -> exactly 100
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("family", ["general", "bank", "insurance", "investment"])
def test_full_input_scores_100_across_all_axes(family):
    res = S2.ScoreV2Engine(family).score(full_input(family))
    assert res["score_status"] == "scored"
    assert res["quality_score"] == 100.0
    assert res["valuation_score"] == 100.0
    assert res["timing_score"] == 100.0
    assert res["quality_contribution"] == 40.0
    assert res["valuation_contribution"] == 35.0
    assert res["timing_contribution"] == 25.0
    assert res["total_score"] == 100.0


# ---------------------------------------------------------------------------
# 3. Real zero is not missing (and missing is not v1's 0.3 neutral)
# ---------------------------------------------------------------------------
def test_real_zero_scores_zero_but_is_scored():
    res = S2.ScoreV2Engine("general").score(zero_input())
    assert res["score_status"] == "scored"
    assert res["total_score"] == 0.0
    assert res["quality_contribution"] == 0.0
    assert all(f["status"] == "scored" and f["input"] == 0.0
               for f in res["factor_breakdown"].values()
               if f["status"] == "scored")


def test_missing_nonessential_renormalizes_no_v1_neutral():
    """cash_conversion missing, everything else 1.0: the axis renormalizes over
    present weights — total stays 100.0 (v1's 0.3 neutral would have paid the
    absent factor points and dragged the score below 100)."""
    vals = full_input()
    vals["cash_conversion"] = None
    res = S2.ScoreV2Engine("general").score(vals)
    assert res["score_status"] == "scored"
    assert res["quality_score"] == 100.0
    assert res["total_score"] == 100.0
    assert res["factor_breakdown"]["cash_conversion"]["status"] == "missing"
    assert res["data_coverage"]["axes"]["quality"]["coverage"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 4. Axis caps
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("family", ["general", "bank", "insurance", "investment"])
def test_axis_scores_never_exceed_caps(family):
    vals = {fid: (0.73 if i % 3 == 0 else 0.41 if i % 3 == 1 else 0.17)
            for i, fid in enumerate(CFG.FAMILY_WEIGHTS[family])}
    res = S2.ScoreV2Engine(family).score(vals)
    assert 0.0 <= res["quality_score"] <= 100.0
    assert 0.0 <= res["valuation_score"] <= 100.0
    assert 0.0 <= res["timing_score"] <= 100.0
    assert 0.0 <= res["quality_contribution"] <= 40.0
    assert 0.0 <= res["valuation_contribution"] <= 35.0
    assert 0.0 <= res["timing_contribution"] <= 25.0
    assert res["score_status"] == "scored"
    assert res["total_score"] == pytest.approx(
        res["quality_contribution"] + res["valuation_contribution"]
        + res["timing_contribution"], abs=1e-9)
    assert 0.0 <= res["total_score"] <= 100.0


# ---------------------------------------------------------------------------
# 5. Invalid input is rejected
# ---------------------------------------------------------------------------
def test_invalid_inputs_rejected():
    eng = S2.ScoreV2Engine("general")
    for bad in (1.5, -0.01, float("nan"), float("inf"), "0.5", True, [0.5]):
        with pytest.raises(ValueError):
            eng.score({"pe": bad})
    with pytest.raises(ValueError):
        eng.score({"shiller_pe": 0.5})          # unknown factor id
    with pytest.raises(ValueError):
        eng.score("not a dict")
    eng.score({"pe": 0.0})                       # boundaries are valid
    eng.score({"pe": 1.0})


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------
def test_deterministic_output():
    vals = full_input("bank")
    vals.update({"roe_level": 0.62, "pe": 0.35, "pb": 0.5,
                 "momentum_6m_rel": 0.8, "liquidity": None})
    a = S2.ScoreV2Engine("bank").score(vals)
    b = S2.ScoreV2Engine("bank").score(vals)
    assert a == b


# ---------------------------------------------------------------------------
# 7. Critically incomplete data -> insufficient_data (no fake-precise score)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("essential", ["roe_level", "pe", "momentum_6m_rel"])
def test_essential_missing_yields_insufficient_data(essential):
    vals = full_input()
    vals[essential] = None
    res = S2.ScoreV2Engine("general").score(vals)
    assert res["score_status"] == "insufficient_data"
    assert res["total_score"] is None
    axis = CFG.V2_QVT_FACTORS[essential]["axis"]
    assert res[f"{axis}_score"] is None
    assert res[f"{axis}_contribution"] is None
    # the other axes are still honestly reported
    for other in ("quality", "valuation", "timing"):
        if other != axis:
            assert res[f"{other}_score"] == 100.0
    assert essential in res["data_coverage"]["axes"][axis]["missing_essential"]


def test_coverage_floor_yields_insufficient_data():
    """Essentials present, but >50% of the timing weight missing: the axis must
    refuse a confident-looking number."""
    vals = full_input()
    for fid in ("momentum_3m_rel", "relative_strength_6m_sector", "low_volatility"):
        vals[fid] = None
    res = S2.ScoreV2Engine("general").score(vals)
    assert res["score_status"] == "insufficient_data"
    assert res["timing_score"] is None
    assert res["total_score"] is None
    assert res["data_coverage"]["axes"]["timing"]["coverage"] < 0.5
    assert res["quality_score"] == 100.0
    assert res["valuation_score"] == 100.0


def test_empty_input_is_insufficient_not_zero():
    res = S2.ScoreV2Engine("general").score({})
    assert res["score_status"] == "insufficient_data"
    assert res["total_score"] is None
    assert res["data_coverage"]["overall"] == 0.0
    assert all(res[f"{a}_score"] is None for a in ("quality", "valuation", "timing"))


# ---------------------------------------------------------------------------
# 8. Confidence and Risk Gate stay not_evaluated
# ---------------------------------------------------------------------------
def test_confidence_and_risk_not_evaluated():
    for family in CFG.FAMILIES:
        res = S2.ScoreV2Engine(family).score(full_input(family))
        assert res["confidence_status"] == "not_evaluated"
        assert res["risk_status"] == "not_evaluated"
        assert "confidence" not in res        # no numeric confidence exists yet
        assert "risk_penalty" not in res
    assert CFG.CONFIDENCE["status"] == "not_evaluated"
    assert CFG.RISK_GATE["status"] == "not_evaluated"
    assert CFG.RISK_GATE["rules"] == {}
    assert CFG.RISK_GATE["enabled"] is False


# ---------------------------------------------------------------------------
# 9. Family structure + V4-reused mapping
# ---------------------------------------------------------------------------
def test_family_structure_and_mapping():
    gen = CFG.FAMILY_WEIGHTS["general"]
    bank = CFG.FAMILY_WEIGHTS["bank"]
    inv = CFG.FAMILY_WEIGHTS["investment"]
    # bank/insurance: deposit-funded factors and P/S excluded, P/B-led (v4 evidence)
    for fam in (bank, CFG.FAMILY_WEIGHTS["insurance"]):
        assert "ps" not in fam and "cash_conversion" not in fam \
            and "interest_coverage" not in fam
        assert fam["pb"] > gen["pb"]
    # investment: operating-margin machinery excluded
    assert "margins" not in inv and "cash_conversion" not in inv
    # v4 keyword contract, reused verbatim
    assert S2.resolve_family("بانک‌ها و موسسات اعتباری") == ("bank", "classified")
    assert S2.resolve_family("بیمه و صندوق بازنشستگی") == ("insurance", "classified")
    assert S2.resolve_family("سرمایه‌گذاری‌ها") == ("investment", "classified")
    assert S2.resolve_family("فلزات اساسی") == ("general", "classified")
    assert S2.resolve_family(None) == ("general", "unclassified")
    assert S2.resolve_family("") == ("general", "unclassified")
    with pytest.raises(ValueError):
        S2.ScoreV2Engine("crypto")


def test_score_company_records_unclassified_status():
    res = S2.score_company(None, full_input("general"))
    assert res["model_family"] == "general"
    assert res["family_status"] == "unclassified"
    assert res["total_score"] == 100.0


# ---------------------------------------------------------------------------
# 10. Planned factors produce NO score and no surrogate
# ---------------------------------------------------------------------------
def test_planned_factors_never_scored():
    base = S2.ScoreV2Engine("general").score(full_input())
    vals = full_input()
    vals.update({"roic": 1.0, "ev_ebit": 0.9, "fcf_yield": 1.0,
                 "distance_from_52w_high": 0.3})
    with_planned = S2.ScoreV2Engine("general").score(vals)
    assert with_planned["total_score"] == base["total_score"] == 100.0
    for fid in ("roic", "ev_ebit", "fcf_yield", "distance_from_52w_high"):
        entry = with_planned["factor_breakdown"][fid]
        assert entry["status"] == "not_implemented"
        assert entry["weighted_score"] is None
        assert entry.get("note")


# ---------------------------------------------------------------------------
# 11. Percentile normalization reuses v4's midrank
# ---------------------------------------------------------------------------
def test_percentile_normalize_reuses_v4_midrank():
    cs = {
        "a": {"roe_level": 10.0, "pe": 25.0},
        "b": {"roe_level": 20.0, "pe": 20.0},
        "c": {"roe_level": 30.0, "pe": 15.0},
        "d": {"roe_level": 40.0, "pe": 10.0},
        "e": {"roe_level": 50.0, "pe": 5.0},
        "f": {"roe_level": None, "pe": 15.0},   # missing stays missing
    }
    norm = S2.percentile_normalize(cs)
    assert norm["e"]["roe_level"] == 1.0        # higher is better
    assert norm["a"]["roe_level"] == 0.0
    assert norm["c"]["roe_level"] == pytest.approx(0.5)
    assert norm["e"]["pe"] == 1.0               # lower is better: cheapest = best
    assert norm["a"]["pe"] == 0.0               # most expensive = worst
    assert norm["f"]["roe_level"] is None
    assert norm["c"]["pe"] == pytest.approx(norm["f"]["pe"])   # tie -> equal midrank
    with pytest.raises(ValueError):
        S2.percentile_normalize({"x": {"unknown_factor": 1.0}})


# ---------------------------------------------------------------------------
# 12. Output contract keys
# ---------------------------------------------------------------------------
def test_output_contract_keys():
    res = S2.ScoreV2Engine("general").score(full_input())
    required = {
        "score_version", "quality_score", "valuation_score", "timing_score",
        "quality_contribution", "valuation_contribution", "timing_contribution",
        "total_score", "factor_breakdown", "data_coverage",
        "confidence_status", "risk_status", "score_status",
    }
    assert required <= set(res)
    assert res["score_version"] == "canonical-v2-qvt"
    breakdown = res["factor_breakdown"]["pe"]
    assert {"axis", "weight", "status", "input", "weighted_score"} <= set(breakdown)


# ---------------------------------------------------------------------------
# 13. V1 and V4 remain untouched (in-suite guard; golden suites run alongside)
# ---------------------------------------------------------------------------
def test_v1_and_v4_engines_untouched():
    assert CM.SCORE_VERSION == "canonical-v1-dev"
    assert sum(CM.BASELINE_WEIGHTS_V37.values()) == 89   # documented defect, frozen
    assert V4CFG.SCORE_VERSION_V4 == "v4"
    assert sum(V4CFG.CATEGORY_WEIGHTS.values()) == 100
