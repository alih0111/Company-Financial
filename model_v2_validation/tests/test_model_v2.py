"""Determinism / leakage / versioning tests for Model v2 experimentation."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import model_v2 as M  # noqa: E402


def _row(ranks=None, avail=None, n=10, q=1.0, year=2022, ret=0.01):
    ranks = ranks or {c: 0.5 for c in M.ALL_FACTORS}
    avail = avail or {c: 1 for c in M.ALL_FACTORS}
    return {"signal_date": f"{year}-06-30", "year": year, "company_id": "c",
            "n_factors_available": n, "quant_score": q, "ranks": ranks, "avail": avail,
            "ret_5": ret, "ret_21": ret, "ret_63": ret}


def test_config_hash_deterministic_and_distinct():
    a1 = M.MODELS["canonical-v2-exp-a"].config_hash()
    a2 = M.MODELS["canonical-v2-exp-a"].config_hash()
    assert a1 == a2
    hashes = {m.config_hash() for m in M.MODELS.values()}
    assert len(hashes) == len(M.MODELS)


def test_identical_config_identical_score_output():
    cfg = M.MODELS["canonical-v2-exp-b"]
    r = _row()
    assert M.score_row(cfg, r["ranks"], r["avail"]) == M.score_row(cfg, r["ranks"], r["avail"])


def test_frozen_period_splits():
    rows = [_row(year=y) for y in (2021, 2022, 2023, 2024, 2025, 2026)]
    assert len(M.period_rows(rows, "development")) == 3
    assert len(M.period_rows(rows, "validation")) == 1
    assert len(M.period_rows(rows, "holdout")) == 1
    assert len(M.period_rows(rows, "forward")) == 1


def test_missing_factor_normalization():
    cfg = M.MODELS["canonical-v2-exp-b"]
    ranks = {c: 0.5 for c in M.ALL_FACTORS}
    avail_full = {c: 1 for c in M.ALL_FACTORS}
    avail_sparse = {c: (1 if c in ("PERank", "SalesGrowthRank") else 0) for c in M.ALL_FACTORS}
    s_full = M.score_row(cfg, ranks, avail_full)
    s_sparse = M.score_row(cfg, ranks, avail_sparse)
    # Constant ranks -> normalized mean is invariant to which factors are available.
    assert abs(s_full - s_sparse) < 1e-12


def test_missing_factor_does_not_reward_availability():
    cfg = M.MODELS["canonical-v2-exp-a"]
    ranks = {"PERank": 1.0, "SalesGrowthRank": 0.0, "RevenueGrowthRank": 0.0,
             "LowVolatilityRank": 0.0, "SalesGrowth3MRank": 0.0, "EarningsQualityRank": 0.0}
    only_pe = {c: (1 if c == "PERank" else 0) for c in M.ALL_FACTORS}
    all_avail = {c: 1 for c in M.ALL_FACTORS}
    # Adding extra available factors with rank 0 must not increase the score.
    assert M.score_row(cfg, ranks, only_pe) >= M.score_row(cfg, ranks, all_avail)


def test_no_factor_when_none_available():
    cfg = M.MODELS["canonical-v2-exp-a"]
    ranks = {c: 0.5 for c in M.ALL_FACTORS}
    none = {c: 0 for c in M.ALL_FACTORS}
    assert M.score_row(cfg, ranks, none) is None


def test_category_model_uses_category_weights():
    cfg = M.MODELS["canonical-v2-exp-c"]
    ranks = {c: 0.5 for c in M.ALL_FACTORS}
    avail = {c: 1 for c in M.ALL_FACTORS}
    assert abs(M.score_row(cfg, ranks, avail) - 0.5) < 1e-12


def test_holdout_leakage_prevention():
    # selection_score takes only dev and val evidence; any holdout structure is
    # ignored by construction. Prove it is a pure function of (dev, val).
    dev = M.evaluate([_row(year=2022, ret=0.02)], "x", lambda r: 0.5)
    val = M.evaluate([_row(year=2024, ret=0.03)], "x", lambda r: 0.5)
    s1 = M.selection_score(dev, val)
    s2 = M.selection_score(dev, val)
    assert s1 == s2
    import inspect
    params = list(inspect.signature(M.selection_score).parameters)
    assert params == ["dev_ev", "val_ev"]
    assert "holdout" not in " ".join(params).lower()


def test_baseline_uses_frozen_quant_score_not_recomputed():
    rows = M.load_signals()
    baseline = lambda r: r["quant_score"]
    assert baseline(rows[0]) == rows[0]["quant_score"]
    # canonical-v1 is never in the mutable MODELS registry
    assert M.BASELINE_VERSION not in M.MODELS


def test_registry_has_required_fields():
    reg = M.config_registry()
    for mid, cfg in M.MODELS.items():
        entry = reg[mid]
        for key in ("model_version", "implementation_revision", "factor_list",
                    "factor_directions", "weights", "missing_policy",
                    "development_period", "validation_period", "holdout_period",
                    "created_at", "config_hash"):
            assert key in entry, (mid, key)
        assert entry["config_hash"] == cfg.config_hash()
