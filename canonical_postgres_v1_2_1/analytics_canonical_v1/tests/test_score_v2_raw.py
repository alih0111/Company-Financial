"""Score v2 raw-layer unit tests (steps 2-B-1 / 2-B-1.5) — pure, no database.

Covers build_q_raw() for the four in-scope Q factors (margins,
cash_conversion, leverage, earnings_growth): the five-status vocabulary,
real-zero vs missing vs invalid, zero denominators, loss makers, profit sign
flips in BOTH directions, the anomaly-vs-invalid three-tier doctrine, the
PIT contract (bare timestamps never verify; after-as_of look-ahead is
invalid; per-component temporal checks and period mismatch), determinism
and the numeric-validity contract: status valid requires every COMPUTED
value to be finite (step 2-B-2.2). All inputs are fixed synthetic dicts
shaped like Engine.compute() metrics[cid].

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_raw.py -q
"""

from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import score_v2_config as CFG  # noqa: E402
import score_v2_raw as SR  # noqa: E402

REQUIRED_FIELDS = ("factor_id", "raw_value", "status", "source_metric",
                   "source_period", "available_at", "pit_status",
                   "validation_reason", "unit", "definition", "warnings")

GOOD_PREV_BASES = {"C1": {"net_profit_prev": 80.0,
                          "operating_profit_prev": 125.0}}


# ---------------------------------------------------------------------------
# Synthetic Engine.compute()-shaped metrics (fixed, deterministic)
# ---------------------------------------------------------------------------
def good_metrics() -> dict:
    """A healthy general-family company plus unrelated engine keys the raw
    layer must ignore."""
    return {
        # irrelevant engine fields — must not affect the raw layer
        "symbol": "ABC1", "security_id": "sec-1", "pe": 8.0, "pb": 1.2,
        "market_cap": 5.0e12, "roe": 22.0, "has_monthly": True, "_dq": set(),
        # the fields the raw layer consumes
        "revenue_ttm": 1000.0,
        "net_profit_ttm": 100.0,
        "operating_profit_ttm": 150.0,
        "ocf_ttm": 90.0,
        "debt_ratio": 0.4,
        "net_profit_growth": 25.0,
        "operating_profit_growth": 20.0,
    }


def one_company(**over) -> dict:
    m = good_metrics()
    m.update(over)
    return {"C1": m}


def build(metrics=None, **kw):
    return SR.build_q_raw(metrics if metrics is not None else one_company(), **kw)


# ---------------------------------------------------------------------------
# 1. Contract shape
# ---------------------------------------------------------------------------
def test_valid_happy_path_all_four_factors():
    # 2-B-1.5: earnings_growth is valid ONLY against a supplied prior-year
    # base — the engine-derived percents alone can never make it valid.
    out = build(prev_bases=GOOD_PREV_BASES)
    recs = out["C1"]
    assert set(recs) == set(SR.IN_SCOPE_FACTORS)
    assert recs["margins"]["status"] == "valid"
    assert recs["margins"]["raw_value"] == {"operating_margin_pct": 15.0,
                                            "net_margin_pct": 10.0}
    assert recs["cash_conversion"]["status"] == "valid"
    assert recs["cash_conversion"]["raw_value"] == pytest.approx(0.9)
    assert recs["leverage"]["status"] == "valid"
    assert recs["leverage"]["raw_value"] == pytest.approx(0.4)
    assert recs["earnings_growth"]["status"] == "valid"
    assert recs["earnings_growth"]["raw_value"] == {
        "net_profit_growth_pct": 25.0, "operating_profit_growth_pct": 20.0}
    assert recs["earnings_growth"]["components"][
        "net_profit_growth_pct"]["value"] == pytest.approx(25.0)


def test_growth_without_verified_base_never_valid():
    # §1 headline fix: the engine-derived +25% must NOT become a usable
    # valid value — its prior-year base is unverified. Status is missing
    # (the base input is absent from this layer), and the derived percent
    # survives only as an explicit diagnostic, never as raw_value.
    rec = build()["C1"]["earnings_growth"]
    assert rec["status"] == "missing"
    assert rec["raw_value"]["net_profit_growth_pct"] is None
    assert rec["raw_value"]["operating_profit_growth_pct"] is None
    comp = rec["components"]["net_profit_growth_pct"]
    assert comp["status"] == "missing"
    assert comp["value"] is None
    assert comp["observed_engine_pct"] == pytest.approx(25.0)
    assert "cannot be distinguished" in comp["reason"]


def test_record_contract_fields_present():
    for rec in build(prev_bases=GOOD_PREV_BASES)["C1"].values():
        for field in REQUIRED_FIELDS:
            assert field in rec, field
        assert isinstance(rec["warnings"], list)
        assert rec["factor_id"] in SR.IN_SCOPE_FACTORS
        assert rec["source_metric"]
        assert rec["unit"] and rec["definition"]


def test_irrelevant_engine_keys_ignored():
    a = build(one_company(price_momentum_30d=51.0, volatility_30d=3.3),
              prev_bases=GOOD_PREV_BASES)
    b = build(prev_bases=GOOD_PREV_BASES)
    assert a == b


# ---------------------------------------------------------------------------
# 2. Real zero is not missing and not invalid
# ---------------------------------------------------------------------------
def test_real_zero_cash_conversion():
    out = build(one_company(ocf_ttm=0.0))
    rec = out["C1"]["cash_conversion"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == 0.0
    assert "real zero" in rec["validation_reason"]


def test_real_zero_leverage():
    rec = build(one_company(debt_ratio=0.0))["C1"]["leverage"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == 0.0


def test_real_zero_margin_component():
    out = build(one_company(operating_profit_ttm=0.0))
    rec = out["C1"]["margins"]
    assert rec["status"] == "valid"  # net margin still valid
    assert rec["components"]["operating_margin_pct"]["value"] == 0.0
    assert rec["components"]["operating_margin_pct"]["status"] == "valid"
    assert rec["raw_value"]["operating_margin_pct"] == 0.0


def test_real_zero_growth_with_prev_bases():
    out = build(one_company(net_profit_growth=0.0),
                prev_bases={"C1": {"net_profit_prev": 100.0}})
    comp = out["C1"]["earnings_growth"]["components"]["net_profit_growth_pct"]
    assert comp["status"] == "valid"
    assert comp["value"] == 0.0


# ---------------------------------------------------------------------------
# 3. Missing values
# ---------------------------------------------------------------------------
def test_missing_inputs_each_factor():
    out = build({
        "C1": {},                                   # nothing at all
        "C2": good_metrics() | {"ocf_ttm": None},   # cash statement absent
    })
    assert out["C1"]["margins"]["status"] == "missing"
    assert out["C1"]["cash_conversion"]["status"] == "missing"
    assert out["C1"]["leverage"]["status"] == "missing"
    assert out["C1"]["earnings_growth"]["status"] == "missing"
    cash = out["C2"]["cash_conversion"]
    assert cash["status"] == "missing"
    assert cash["raw_value"] is None
    assert "ocf_ttm absent" in cash["validation_reason"]


def test_missing_earnings_growth_field():
    # engine growth field absent/None -> missing, never a fabricated value
    out = build(one_company(net_profit_growth=None))
    comp = out["C1"]["earnings_growth"]["components"]["net_profit_growth_pct"]
    assert comp["status"] == "missing"
    assert "observed_engine_pct" not in comp


# ---------------------------------------------------------------------------
# 4. Zero denominator never yields a valid-looking number
# ---------------------------------------------------------------------------
def test_zero_revenue_denominator():
    rec = build(one_company(revenue_ttm=0.0))["C1"]["margins"]
    assert rec["status"] == "missing"
    assert rec["raw_value"] == {"operating_margin_pct": None,
                                "net_margin_pct": None}
    assert "zero" in rec["validation_reason"]


def test_zero_net_profit_is_not_applicable_not_zero_ratio():
    rec = build(one_company(net_profit_ttm=0.0, net_profit_growth=None))["C1"]["cash_conversion"]
    assert rec["status"] == "not_applicable"
    assert rec["raw_value"] is None
    assert "zero" in rec["validation_reason"]


# ---------------------------------------------------------------------------
# 5. Invalid data — definite errors only (2-B-1.5 three-tier doctrine)
# ---------------------------------------------------------------------------
def test_invalid_negative_revenue():
    rec = build(one_company(revenue_ttm=-100.0))["C1"]["margins"]
    assert rec["status"] == "invalid"
    assert rec["raw_value"] == {"operating_margin_pct": None,
                                "net_margin_pct": None}


def test_invalid_negative_debt_ratio():
    # accounting definition: total_liabilities / total_assets with
    # total_assets > 0 — a negative ratio is impossible, a definite error
    rec = build(one_company(debt_ratio=-0.1))["C1"]["leverage"]
    assert rec["status"] == "invalid"
    assert rec["raw_value"] is None
    assert "accounting definition" in rec["validation_reason"]


def test_invalid_nonfinite_values():
    out = build(one_company(revenue_ttm=math.nan, ocf_ttm=math.inf))
    assert out["C1"]["margins"]["status"] == "invalid"
    assert out["C1"]["cash_conversion"]["status"] == "invalid"


def test_non_numeric_values_invalid():
    out = build(one_company(debt_ratio="0.4", revenue_ttm="1000"))
    assert out["C1"]["leverage"]["status"] == "invalid"
    assert out["C1"]["margins"]["status"] == "invalid"


def test_anomaly_distinct_from_invalid():
    # 2-B-1.5: unusual magnitude stays valid with a warning; only definite
    # data errors are invalid. A warning must never blur into invalid.
    lev = build(one_company(debt_ratio=2.5))["C1"]["leverage"]
    assert lev["status"] == "valid" and lev["warnings"]
    neg = build(one_company(debt_ratio=-0.1))["C1"]["leverage"]
    assert neg["status"] == "invalid" and lev["status"] != neg["status"]
    mar = build(one_company(net_profit_ttm=80000.0))["C1"]["margins"]
    assert mar["components"]["net_margin_pct"]["status"] == "valid"
    assert mar["components"]["net_margin_pct"]["warnings"]


def test_anomaly_leverage_above_one_negative_equity_warning():
    # liabilities exceed assets -> negative equity: economically real, kept
    # as data, flagged for the later risk stage — never a penalty here
    rec = build(one_company(debt_ratio=1.15))["C1"]["leverage"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(1.15)
    assert "negative-equity" in rec["validation_reason"]
    assert any(w.startswith("negative_equity") for w in rec["warnings"])
    assert not any("financial_distress_or_anomaly" in w for w in rec["warnings"])


def test_anomaly_leverage_above_two_stays_valid_with_warning():
    # 2-B-1.5 §2: >1 is fully real; >2 is NOT a data error by itself — deep
    # distress or an artifact, decided later by winsorization / Risk Gate.
    # The raw value is always preserved.
    for dr in (2.5, 3.0, 10.0):
        rec = build(one_company(debt_ratio=dr))["C1"]["leverage"]
        assert rec["status"] == "valid", dr
        assert rec["raw_value"] == pytest.approx(dr), dr
        assert any("financial_distress_or_anomaly" in w
                   for w in rec["warnings"]), dr
        assert any(w.startswith("negative_equity") for w in rec["warnings"]), dr


def test_anomaly_magnitude_stays_valid_with_warning():
    # 2-B-1.5 §5: harsh screening bands must not delete real economic data.
    # A tiny profit against large OCF is an unusual-but-real ratio; huge
    # margin percentages likewise. Both stay valid with anomaly warnings.
    rec = build(one_company(net_profit_ttm=1.0, ocf_ttm=500.0))["C1"]["cash_conversion"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(500.0)
    assert any("magnitude_anomaly" in w for w in rec["warnings"])
    out = build(one_company(operating_profit_ttm=20000.0, net_profit_ttm=80000.0))
    mrec = out["C1"]["margins"]
    assert mrec["components"]["operating_margin_pct"]["status"] == "valid"
    assert mrec["components"]["net_margin_pct"]["status"] == "valid"
    assert mrec["raw_value"]["operating_margin_pct"] == pytest.approx(2000.0)
    assert mrec["raw_value"]["net_margin_pct"] == pytest.approx(8000.0)
    assert len(mrec["warnings"]) == 2


# ---------------------------------------------------------------------------
# 6. Composite factors — valid ONLY when every component is valid (§4)
# ---------------------------------------------------------------------------
def test_mixed_component_aggregation():
    # operating margin corrupt (non-finite), net margin fine:
    # 2-B-1.5: the factor can no longer be "valid with one broken leg" —
    # it is invalid, and the per-component detail says exactly why.
    out = build(one_company(operating_profit_ttm=math.nan))
    rec = out["C1"]["margins"]
    assert rec["status"] == "invalid"
    assert rec["components"]["operating_margin_pct"]["status"] == "invalid"
    assert rec["components"]["net_margin_pct"]["status"] == "valid"
    assert rec["raw_value"]["operating_margin_pct"] is None
    assert rec["raw_value"]["net_margin_pct"] == pytest.approx(10.0)


def test_composite_valid_plus_missing_is_missing():
    # operating profit absent, net margin fine -> the factor is missing,
    # not valid; the healthy component keeps its value and reason.
    out = build(one_company(operating_profit_ttm=None))
    rec = out["C1"]["margins"]
    assert rec["status"] == "missing"
    assert rec["components"]["operating_margin_pct"]["status"] == "missing"
    assert rec["components"]["net_margin_pct"]["status"] == "valid"
    assert rec["raw_value"]["net_margin_pct"] == pytest.approx(10.0)
    assert "operating_profit_ttm absent" in \
        rec["components"]["operating_margin_pct"]["reason"]


def test_composite_valid_plus_invalid_is_invalid():
    # growth: net leg valid against a supplied base, operating leg corrupt
    # -> composite invalid; the valid leg is still visible in components.
    pb = {"C1": {"net_profit_prev": 80.0}}
    out = build(one_company(operating_profit_ttm=math.inf), prev_bases=pb)
    rec = out["C1"]["earnings_growth"]
    assert rec["status"] == "invalid"
    assert rec["components"]["net_profit_growth_pct"]["status"] == "valid"
    assert rec["components"]["operating_profit_growth_pct"]["status"] == "invalid"
    assert rec["raw_value"]["net_profit_growth_pct"] == pytest.approx(25.0)
    assert rec["raw_value"]["operating_profit_growth_pct"] is None


# ---------------------------------------------------------------------------
# 7. Negative profit / sign changes — both directions
# ---------------------------------------------------------------------------
def test_loss_maker_cash_conversion_not_applicable():
    rec = build(one_company(net_profit_ttm=-50.0, ocf_ttm=-10.0,
                            net_profit_growth=None))["C1"]["cash_conversion"]
    assert rec["status"] == "not_applicable"
    assert rec["raw_value"] is None
    assert "loss maker" in rec["validation_reason"]


def test_growth_sign_change_with_prev_bases():
    # loss -> profit: the +300% derived percent is a misleading artifact of
    # the sign flip; it must never surface as a value, and no automatic
    # positive credit is given. 2-B-1.5: with one component not_applicable
    # the composite can no longer be valid — it is not_applicable.
    pb = {"C1": {"net_profit_prev": -10.0, "operating_profit_prev": 80.0}}
    out = build(one_company(net_profit_ttm=20.0, net_profit_growth=300.0,
                            operating_profit_ttm=88.0,
                            operating_profit_growth=10.0),
                prev_bases=pb)
    rec = out["C1"]["earnings_growth"]
    np_comp = rec["components"]["net_profit_growth_pct"]
    assert np_comp["status"] == "not_applicable"
    assert np_comp["value"] is None
    assert np_comp.get("sign_change") is True
    assert "sign change" in np_comp["reason"]
    assert rec["raw_value"]["net_profit_growth_pct"] is None
    op_comp = rec["components"]["operating_profit_growth_pct"]
    assert op_comp["status"] == "valid"
    assert op_comp["value"] == pytest.approx(10.0)
    assert rec["status"] == "not_applicable"


def test_growth_profit_to_loss_sign_change_recorded():
    # profit -> loss against a positive base: the standard-formula percent
    # (here -125%) is meaningful and kept, but the loss and the sign flip
    # are recorded independently — never a desirable growth outcome.
    pb = {"C1": {"net_profit_prev": 80.0}}
    out = build(one_company(net_profit_ttm=-20.0, net_profit_growth=-125.0),
                prev_bases=pb)
    comp = out["C1"]["earnings_growth"]["components"]["net_profit_growth_pct"]
    assert comp["status"] == "valid"
    assert comp["value"] == pytest.approx(-125.0)
    assert comp.get("sign_change") is True
    assert comp.get("current_loss") is True
    assert any("turned_to_loss" in w for w in comp["warnings"])
    rec = out["C1"]["earnings_growth"]
    assert rec["raw_value"]["net_profit_growth_pct"] == pytest.approx(-125.0)
    assert any("turned_to_loss" in w for w in rec["warnings"])


def test_growth_loss_to_deeper_loss_not_applicable():
    pb = {"C1": {"net_profit_prev": -100.0}}
    out = build(one_company(net_profit_ttm=-120.0, net_profit_growth=-20.0),
                prev_bases=pb)
    comp = out["C1"]["earnings_growth"]["components"]["net_profit_growth_pct"]
    assert comp["status"] == "not_applicable"
    assert comp["value"] is None
    assert "sign_change" not in comp  # same sign on both sides — no flip


def test_growth_zero_base_not_applicable():
    pb = {"C1": {"net_profit_prev": 0.0}}
    out = build(one_company(net_profit_ttm=50.0, net_profit_growth=None),
                prev_bases=pb)
    comp = out["C1"]["earnings_growth"]["components"]["net_profit_growth_pct"]
    assert comp["status"] == "not_applicable"
    assert "zero" in comp["reason"]


def test_growth_valid_from_prev_bases():
    pb = {"C1": {"net_profit_prev": 80.0, "operating_profit_prev": 125.0}}
    out = build(one_company(net_profit_growth=25.0,
                            operating_profit_growth=20.0), prev_bases=pb)
    comps = out["C1"]["earnings_growth"]["components"]
    assert comps["net_profit_growth_pct"]["value"] == pytest.approx(25.0)
    assert comps["operating_profit_growth_pct"]["value"] == pytest.approx(20.0)


def test_growth_partial_bases_components_independent():
    # only the net-profit base was supplied: the net leg classifies exactly,
    # the operating leg stays missing on its own — never a silent blend.
    pb = {"C1": {"net_profit_prev": 80.0}}
    out = build(prev_bases=pb)
    rec = out["C1"]["earnings_growth"]
    assert rec["components"]["net_profit_growth_pct"]["status"] == "valid"
    assert rec["components"]["net_profit_growth_pct"]["value"] == pytest.approx(25.0)
    assert rec["components"]["operating_profit_growth_pct"]["status"] == "missing"
    assert rec["status"] == "missing"


def test_growth_without_prev_bases_states_limitation():
    # 2-B-1.5 §1: without a verifiable base the derived percent is NEVER a
    # usable valid value — for any magnitude. Missing (base absent) stays
    # distinct from invalid (corruption).
    for pct in (300.0, 5.0, -40.0, 5000.0):
        rec = build(one_company(net_profit_growth=pct))["C1"]["earnings_growth"]
        comp = rec["components"]["net_profit_growth_pct"]
        assert comp["status"] == "missing", pct
        assert comp["value"] is None, pct
        assert comp["observed_engine_pct"] == pytest.approx(pct), pct
    corrupt = build(one_company(net_profit_growth=math.nan))["C1"]["earnings_growth"]
    assert corrupt["components"]["net_profit_growth_pct"]["status"] == "invalid"


# ---------------------------------------------------------------------------
# 8. PIT contract
# ---------------------------------------------------------------------------
def test_pit_unverified_by_default_no_publication_date():
    for rec in build()["C1"].values():
        assert rec["available_at"] is None
        assert rec["pit_status"] == SR.PIT_UNVERIFIED
        assert rec["source_period"] is None


def test_pit_bare_timestamp_without_origin_attribution_stays_unverified():
    # 2-B-1.5 §3: receiving a bare timestamp must NOT flip PIT to verified —
    # without evidence attributing it to the source report it proves nothing.
    import datetime as dt
    ts = dt.datetime(2026, 10, 6, 18, 0, tzinfo=dt.timezone.utc)
    prov = {"C1": {"source_period": "2026-06-30", "available_at": ts}}
    for rec in build(provenance=prov)["C1"].values():
        assert rec["pit_status"] == SR.PIT_UNVERIFIED
        assert "without origin attribution" in rec["validation_reason"]
        assert rec["available_at"] == ts  # the timestamp itself is kept


def test_pit_verified_requires_timestamp_plus_source_ref():
    import datetime as dt
    ts = dt.datetime(2026, 10, 6, 18, 0, tzinfo=dt.timezone.utc)
    prov = {"C1": {"source_period": "2026-06-30", "available_at": ts,
                   "source_ref": "codal:12345"}}
    for rec in build(provenance=prov)["C1"].values():
        assert rec["pit_status"] == SR.PIT_VERIFIED
        assert rec["available_at"] == ts
        assert rec["source_period"] == "2026-06-30"
    # per-component temporal validity is recorded independently (§3)
    mrec = build(provenance=prov)["C1"]["margins"]
    for comp in mrec["components"].values():
        assert comp["pit_status"] == SR.PIT_VERIFIED
        assert comp["available_at"] == ts
        assert comp["source_period"] == "2026-06-30"
    # a period without a publication timestamp stays unverified —
    # period_end is never promoted to available_at
    prov2 = {"C1": {"source_period": "2026-06-30"}}
    for rec in build(provenance=prov2)["C1"].values():
        assert rec["pit_status"] == SR.PIT_UNVERIFIED
        assert rec["available_at"] is None


def test_pit_after_as_of_invalid_for_history():
    # 2-B-1.5 §3: data attributable to a publication after the as_of cutoff
    # must never count as valid for historical computation (look-ahead).
    import datetime as dt
    as_of = dt.datetime(2026, 6, 30, tzinfo=dt.timezone.utc)
    late = dt.datetime(2026, 12, 31, tzinfo=dt.timezone.utc)
    prov = {"C1": {"available_at": late, "source_ref": "codal:9"}}
    out = build(provenance=prov, as_of=as_of)["C1"]
    for fid in ("margins", "cash_conversion", "leverage"):
        assert out[fid]["pit_status"] == SR.PIT_AFTER_AS_OF, fid
        assert out[fid]["status"] == "invalid", fid
        rv = out[fid]["raw_value"]
        if isinstance(rv, dict):
            assert all(v is None for v in rv.values()), fid
        else:
            assert rv is None, fid
    # growth had no verified base anyway: it stays missing, but its PIT
    # must still say after_as_of — never "verified for history"
    assert out["earnings_growth"]["pit_status"] == SR.PIT_AFTER_AS_OF
    assert out["earnings_growth"]["status"] != "valid"
    # the same provenance against a later as_of verifies normally
    out2 = build(provenance=prov,
                 as_of=dt.datetime(2027, 6, 30, tzinfo=dt.timezone.utc))["C1"]
    assert out2["leverage"]["pit_status"] == SR.PIT_VERIFIED
    assert out2["leverage"]["status"] == "valid"


def test_cash_conversion_same_period_required():
    # 2-B-1.5 §3: without provable same-window alignment of CFO and net
    # profit, cash_conversion is never presented as PIT-verified for
    # historical use — even when both metrics carry attributed timestamps.
    import datetime as dt
    ts = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
    prov = {"C1": {"metrics": {
        "ocf_ttm": {"available_at": ts, "source_ref": "codal:1"},
        "net_profit_ttm": {"available_at": ts, "source_ref": "codal:1"},
    }}}
    rec = build(provenance=prov)["C1"]["cash_conversion"]
    assert rec["status"] == "valid"          # the ratio itself is fine
    assert rec["pit_status"] == SR.PIT_UNVERIFIED
    assert "same-period" in rec["validation_reason"]
    # with equal, known source periods it verifies
    prov2 = {"C1": {"metrics": {
        "ocf_ttm": {"available_at": ts, "source_ref": "codal:1",
                    "source_period": "1405-06"},
        "net_profit_ttm": {"available_at": ts, "source_ref": "codal:1",
                           "source_period": "1405-06"},
    }}}
    rec2 = build(provenance=prov2)["C1"]["cash_conversion"]
    assert rec2["pit_status"] == SR.PIT_VERIFIED


def test_pit_component_period_mismatch_flagged():
    # 2-B-1.5 §3: inconsistent component source periods must be visible —
    # the data stays valid but PIT can never be verified for history.
    import datetime as dt
    ts = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
    prov = {"C1": {"metrics": {
        "ocf_ttm": {"available_at": ts, "source_ref": "codal:1",
                    "source_period": "1405-06"},
        "net_profit_ttm": {"available_at": ts, "source_ref": "codal:2",
                           "source_period": "1404-06"},
    }}}
    rec = build(provenance=prov)["C1"]["cash_conversion"]
    assert rec["status"] == "valid"
    assert rec["pit_status"] == SR.PIT_PERIOD_MISMATCH
    assert any("component_period_mismatch" in w for w in rec["warnings"])
    assert "inconsistent" in rec["validation_reason"]


# ---------------------------------------------------------------------------
# 9. Determinism, no-DB purity, status vocabulary
# ---------------------------------------------------------------------------
def test_deterministic_fixed_input():
    m = one_company()
    a = SR.build_q_raw(dict(m), prev_bases={"C1": {"net_profit_prev": 80.0}},
                      provenance={"C1": {"source_period": "1405Q1"}})
    b = SR.build_q_raw(dict(m), prev_bases={"C1": {"net_profit_prev": 80.0}},
                      provenance={"C1": {"source_period": "1405Q1"}})
    assert a == b


def test_module_has_no_database_or_engine_dependency():
    import ast
    tree = ast.parse(inspect.getsource(SR))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"__future__", "math"}, imported


def test_status_vocabulary_complete():
    assert {SR.STATUS_VALID, SR.STATUS_MISSING, SR.STATUS_INVALID,
            SR.STATUS_NOT_APPLICABLE, SR.STATUS_NOT_IMPLEMENTED} == {
        "valid", "missing", "invalid", "not_applicable", "not_implemented"}


def test_pit_vocabulary_complete():
    assert SR.PIT_VERIFIED == "verified"
    assert SR.PIT_UNVERIFIED == "unverified_no_publication_date"
    assert SR.PIT_AFTER_AS_OF == "after_as_of"
    assert SR.PIT_PERIOD_MISMATCH == "component_period_mismatch"


def test_not_implemented_record_helper():
    rec = SR.not_implemented_record("roic",
                                    "needs NOPAT and operating invested capital")
    assert rec["status"] == "not_implemented"
    assert rec["raw_value"] is None
    assert rec["pit_status"] == SR.PIT_UNVERIFIED
    for field in REQUIRED_FIELDS:
        assert field in rec


# ---------------------------------------------------------------------------
# 10. Alignment with the V2 config (no weight/registry changes)
# ---------------------------------------------------------------------------
def test_scope_factors_exist_in_v2_config_quality_axis():
    for fid in SR.IN_SCOPE_FACTORS:
        entry = CFG.V2_QVT_FACTORS[fid]
        assert entry["axis"] == "quality"
    assert set(SR.IN_SCOPE_FACTORS) | set(SR.NOT_IMPLEMENTED_Q_FACTORS) == {
        fid for fid, e in CFG.V2_QVT_FACTORS.items() if e["axis"] == "quality"}


def test_directions_match_v2_config():
    lower = ("leverage", "earnings_quality")
    for fid in SR.IN_SCOPE_FACTORS:
        assert CFG.V2_QVT_FACTORS[fid]["direction"] == (
            "lower" if fid in lower else "higher")


# ---------------------------------------------------------------------------
# 11. Numeric validity contract (step 2-B-2.2): valid => finite
# ---------------------------------------------------------------------------
def test_operating_margin_overflow_invalid_non_finite_result():
    # finite inputs, infinite computed ratio: 1e308 / 1.0 * 100 overflows.
    # A non-finite result is invalid — never valid data, never zero.
    out = build(one_company(revenue_ttm=1.0, operating_profit_ttm=1e308,
                            net_profit_ttm=100.0))
    rec = out["C1"]["margins"]
    comp = rec["components"]["operating_margin_pct"]
    assert comp["status"] == "invalid"
    assert comp["value"] is None
    assert "non_finite_result" in comp["reason"]
    assert rec["status"] == "invalid"
    assert rec["raw_value"]["operating_margin_pct"] is None


def test_net_margin_overflow_invalid_sibling_component_kept():
    # same overflow on the net leg; the healthy operating sibling keeps its
    # exact finite value and its anomaly warning — components stay
    # independent, the composite itself is never valid with one broken leg.
    out = build(one_company(revenue_ttm=1.0, net_profit_ttm=1e308,
                            operating_profit_ttm=150.0))
    rec = out["C1"]["margins"]
    net = rec["components"]["net_margin_pct"]
    op = rec["components"]["operating_margin_pct"]
    assert net["status"] == "invalid" and net["value"] is None
    assert "non_finite_result" in net["reason"]
    assert op["status"] == "valid"
    assert op["value"] == pytest.approx(15000.0)     # 150 / 1 * 100
    assert any("magnitude_anomaly" in w for w in op["warnings"])
    assert rec["status"] == "invalid"
    assert rec["raw_value"] == {"operating_margin_pct": 15000.0,
                                "net_margin_pct": None}


def test_cash_conversion_tiny_denominator_overflow_invalid():
    # np_ positive but so tiny that ocf / np_ overflows: inputs finite,
    # ratio impossible — invalid, value never kept (2-B-2.2).
    out = build(one_company(net_profit_ttm=1e-308, ocf_ttm=90.0))
    rec = out["C1"]["cash_conversion"]
    assert rec["status"] == "invalid"
    assert rec["raw_value"] is None
    assert "non_finite_result" in rec["validation_reason"]


def test_earnings_growth_overflow_invalid():
    # the other division path: (cur - base) / base * 100 with a huge finite
    # current value over a tiny positive base. The growth path was already
    # guarded — 2-B-2.2 pins the same contract and reason marker there.
    pb = {"C1": {"net_profit_prev": 1e-10, "operating_profit_prev": 125.0}}
    out = build(one_company(net_profit_ttm=1e300, operating_profit_ttm=150.0),
                prev_bases=pb)
    rec = out["C1"]["earnings_growth"]
    net = rec["components"]["net_profit_growth_pct"]
    assert net["status"] == "invalid" and net["value"] is None
    assert "non_finite_result" in net["reason"]
    op = rec["components"]["operating_profit_growth_pct"]
    assert op["status"] == "valid"
    assert op["value"] == pytest.approx(20.0)        # (150-125)/125*100
    assert rec["status"] == "invalid"
    assert rec["raw_value"] == {"net_profit_growth_pct": None,
                                "operating_profit_growth_pct": 20.0}


def test_huge_but_finite_results_stay_valid():
    # the guard must catch ONLY true non-finite results: huge-but-finite
    # magnitudes are real data — valid with the anomaly warning.
    rec = build(one_company(net_profit_ttm=1.0,
                            ocf_ttm=1e300))["C1"]["cash_conversion"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(1e300)
    assert math.isfinite(rec["raw_value"])
    assert any("magnitude_anomaly" in w for w in rec["warnings"])
    mrec = build(one_company(revenue_ttm=1.0, operating_profit_ttm=1e306,
                             net_profit_ttm=100.0))["C1"]["margins"]
    comp = mrec["components"]["operating_margin_pct"]
    assert comp["status"] == "valid"
    assert comp["value"] == pytest.approx(1e308)     # finite: 1e306 / 1 * 100
    assert mrec["status"] == "valid"


def test_extreme_finite_leverage_still_valid_with_independent_warnings():
    # leverage has NO arithmetic in this layer (engine-derived passthrough):
    # an extreme-but-finite debt_ratio stays valid real data with its
    # independent warnings — never auto-invalidated (2-B-2.2 §4).
    rec = build(one_company(debt_ratio=1e300))["C1"]["leverage"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(1e300)
    assert any(w.startswith("negative_equity") for w in rec["warnings"])
    assert any("financial_distress_or_anomaly" in w for w in rec["warnings"])


def test_composite_with_one_overflowing_component_aggregates_invalid():
    # composite bookkeeping under an overflowed (not corrupt-input) leg:
    # broken leg invalid, healthy leg valid with its value, factor invalid,
    # and the healthy leg's anomaly warning rolls up to the factor record.
    out = build(one_company(revenue_ttm=1.0, operating_profit_ttm=1e308,
                            net_profit_ttm=100.0))
    rec = out["C1"]["margins"]
    assert rec["status"] == "invalid"
    assert rec["components"]["operating_margin_pct"]["status"] == "invalid"
    assert rec["components"]["net_margin_pct"]["status"] == "valid"
    assert rec["raw_value"]["net_margin_pct"] == pytest.approx(10000.0)
    assert any("magnitude_anomaly" in w for w in rec["warnings"])
    assert not any("non_finite" in w for w in rec["warnings"])


def test_nonfinite_invalid_keeps_provenance_and_never_zero_substitutes():
    # an invalid computed result preserves the provenance path untouched and
    # never replaces the value with 0 (or any number): value stays None.
    import datetime as dt
    ts = dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
    prov = {"C1": {"available_at": ts, "source_ref": "codal:1",
                   "source_period": "1405-06"}}
    m = one_company(net_profit_ttm=1e-308, ocf_ttm=90.0)
    before = dict(m)
    rec = build(m, provenance=prov)["C1"]["cash_conversion"]
    assert rec["status"] == "invalid"
    assert rec["raw_value"] is None
    assert rec["pit_status"] == SR.PIT_VERIFIED
    assert rec["available_at"] == ts
    assert rec["source_period"] == "1405-06"
    assert m == before                     # the engine metrics are untouched


def test_nonfinite_result_cannot_enter_normalization_population():
    # end-to-end (2-B-2.2 §5.9): after the raw contract, an overflowing
    # ratio is invalid BEFORE normalization, so no valid-looking inf can
    # enter any ranking population — verified WITHOUT touching the
    # normalization module, whose own finite guard remains defense #2.
    import score_v2_normalize as SN
    mets = {f"C{i:02d}": good_metrics() | {"ocf_ttm": 100.0 + 7.0 * i}
            for i in range(12)}
    mets["OVF"] = good_metrics() | {"net_profit_ttm": 1e-308}
    meta = {cid: {"model_family": "general", "industry": "Metals"}
            for cid in mets}
    raw = SR.build_q_raw(mets)
    assert raw["OVF"]["cash_conversion"]["status"] == "invalid"
    out = SN.normalize_q_cross_section(raw, meta)
    assert not [r for r in out["records"]
                if r["company_id"] == "OVF"
                and r["factor_id"] == "cash_conversion"]
    pop = out["populations"]["cash_conversion"]
    assert pop["excluded"] == {"invalid": 1}
    assert pop["families"]["general"]["n_valid"] == 12
    w = pop["families"]["general"]["winsor"]
    assert (not w["applied"]) or (math.isfinite(w["low"])
                                  and math.isfinite(w["high"]))
    rollup = out["factors"]["OVF"]["cash_conversion"]
    assert rollup["normalization_status"] == "not_ranked_raw_invalid"
    assert rollup["percentile_combined"] is None
    # global invariant across every emitted normalization record
    assert all(math.isfinite(r["raw_value"]) for r in out["records"])


def test_valid_implies_finite_invariant_stress_sweep():
    # the contract itself, stressed over a grid of finite inputs: every part
    # and record reported valid carries a finite computed value, and every
    # non-valid part carries None (never a disguised number).
    combos = []
    for rev in (1.0, 1e-10):
        for op in (0.0, 1e300, -1e300, 150.0):
            for np_ in (1e-308, 1.0, 1e300):
                for ocf in (-90.0, 1e300):
                    combos.append((
                        {"revenue_ttm": rev, "operating_profit_ttm": op,
                         "net_profit_ttm": np_, "ocf_ttm": ocf,
                         "debt_ratio": 0.4},
                        {}))
    for base in (1e-10, 1.0):
        for cur in (1e300, 50.0):
            combos.append((
                {"revenue_ttm": 1000.0, "operating_profit_ttm": cur,
                 "net_profit_ttm": cur, "ocf_ttm": 90.0, "debt_ratio": 0.4},
                {"net_profit_prev": base, "operating_profit_prev": base}))

    for m, bases in combos:
        out = SR.build_q_raw(
            {"C1": m},
            prev_bases={"C1": bases} if bases else None)["C1"]
        for fid, rec in out.items():
            for comp in rec.get("components", {}).values():
                if comp["status"] == SR.STATUS_VALID:
                    assert comp["value"] is not None \
                        and math.isfinite(comp["value"]), (fid, comp)
                else:
                    assert comp["value"] is None, (fid, comp)
            if rec["status"] == SR.STATUS_VALID:
                if isinstance(rec["raw_value"], dict):
                    assert all(v is not None and math.isfinite(v)
                               for v in rec["raw_value"].values()), fid
                else:
                    assert rec["raw_value"] is not None \
                        and math.isfinite(rec["raw_value"]), fid



# ---------------------------------------------------------------------------
# 12. Step 2-B-5 factors: roe_level, margin_trend, revenue_growth
# ---------------------------------------------------------------------------
def test_roe_level_valid_positive_negative_and_real_zero():
    out = build(one_company(roe=22.0))["C1"]["roe_level"]
    assert out["status"] == "valid" and out["raw_value"] == 22.0
    assert "percent" in out["unit"]
    neg = build(one_company(roe=-35.5))["C1"]["roe_level"]
    assert neg["status"] == "valid" and neg["raw_value"] == -35.5
    assert "loss" in neg["validation_reason"]
    zero = build(one_company(roe=0.0))["C1"]["roe_level"]
    assert zero["status"] == "valid" and zero["raw_value"] == 0.0
    assert "real zero" in zero["validation_reason"]


def test_roe_level_negative_is_never_invalidated_for_its_sign():
    rec = build(one_company(roe=-150.0))["C1"]["roe_level"]
    assert rec["status"] == "valid" and rec["raw_value"] == -150.0
    assert rec["warnings"] == []


def test_roe_level_missing_when_numerator_absent():
    rec = build(one_company(roe=None, net_profit_ttm=None))["C1"]["roe_level"]
    assert rec["status"] == "missing"
    assert "no numerator" in rec["validation_reason"]


def test_roe_level_missing_with_present_numerator_names_equity_states():
    # engine emits roe only for equity > 0: roe=None with a present net
    # profit means equity missing/zero/negative — never a fabricated level,
    # so equity <= 0 can never auto-read as great performance
    rec = build(one_company(roe=None))["C1"]["roe_level"]
    assert rec["status"] == "missing"
    assert "total_equity" in rec["validation_reason"]
    assert rec["raw_value"] is None


def test_roe_level_non_finite_invalid_and_band_warning():
    rec = build(one_company(roe=float("nan")))["C1"]["roe_level"]
    assert rec["status"] == "invalid" and rec["raw_value"] is None
    big = build(one_company(roe=5000.0))["C1"]["roe_level"]
    assert big["status"] == "valid" and big["raw_value"] == 5000.0
    assert any(w.startswith("magnitude_anomaly") for w in big["warnings"])


def test_margin_trend_valid_like_for_like_ttm_diff():
    bases = {"C1": {"net_profit_prev": 80.0, "operating_profit_prev": 125.0,
                    "revenue_prev": 1000.0}}
    rec = build(prev_bases=bases)["C1"]["margin_trend"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(15.0 - 12.5)  # pp, not %
    assert "percentage points" in rec["unit"]
    assert rec["warnings"] == []


def test_margin_trend_without_bases_is_missing_never_engine_field():
    # the engine's derived margin_trend compares TTM vs a same-report YTD
    # margin (different span): it may only appear as a diagnostic, never as
    # the raw value
    rec = build(one_company(margin_trend=3.0))["C1"]["margin_trend"]
    assert rec["status"] == "missing" and rec["raw_value"] is None
    assert "not supplied" in rec["validation_reason"]


def test_margin_trend_partial_base_names_the_missing_tag():
    bases = {"C1": {"operating_profit_prev": 125.0}}   # no revenue_prev
    rec = build(prev_bases=bases)["C1"]["margin_trend"]
    assert rec["status"] == "missing"
    assert "revenue_prev" in rec["validation_reason"]


def test_margin_trend_quarantined_op_prev_is_missing_not_engine_value():
    # a quarantined base ABSENT from prev_bases must leave the factor
    # missing — the span-mismatched engine field is never substituted
    bases = {"C1": {"net_profit_prev": 80.0, "revenue_prev": 1000.0}}
    rec = build(prev_bases=bases)["C1"]["margin_trend"]
    assert rec["status"] == "missing"
    assert "operating_profit_prev" in rec["validation_reason"]


def test_margin_trend_loss_year_base_is_a_valid_negative_margin():
    bases = {"C1": {"operating_profit_prev": -50.0, "revenue_prev": 1000.0}}
    rec = build(prev_bases=bases)["C1"]["margin_trend"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(15.0 - (-5.0))
    assert rec["warnings"] == []


def test_margin_trend_zero_and_negative_prior_revenue_states():
    zero = build(prev_bases={"C1": {"operating_profit_prev": 125.0,
                                    "revenue_prev": 0.0}})
    assert zero["C1"]["margin_trend"]["status"] == "not_applicable"
    neg = build(prev_bases={"C1": {"operating_profit_prev": 125.0,
                                   "revenue_prev": -10.0}})
    assert neg["C1"]["margin_trend"]["status"] == "invalid"


def test_margin_trend_missing_current_inputs_and_non_finite():
    rec = build(one_company(operating_profit_ttm=None))["C1"]["margin_trend"]
    assert rec["status"] == "missing"
    bad = build(one_company(operating_profit_ttm=float("inf")))
    assert bad["C1"]["margin_trend"]["status"] == "invalid"
    overflow = build({"C1": dict(good_metrics(), revenue_ttm=1e-300,
                                 operating_profit_ttm=1e300,
                                 net_profit_ttm=1.0, ocf_ttm=None)})
    mt = overflow["C1"]["margin_trend"]
    assert mt["status"] == "invalid"
    assert "non_finite_result" in mt["validation_reason"]


def test_margin_trend_anomaly_band_warns_but_keeps_value():
    bases = {"C1": {"operating_profit_prev": -5000.0, "revenue_prev": 1000.0}}
    rec = build(prev_bases=bases)["C1"]["margin_trend"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(15.0 - (-500.0))
    assert any(w.startswith("magnitude_anomaly") for w in rec["warnings"])


def test_revenue_growth_valid_zero_negative_and_missing():
    ok = build(one_company(revenue_growth=12.5))["C1"]["revenue_growth"]
    assert ok["status"] == "valid" and ok["raw_value"] == 12.5
    zero = build(one_company(revenue_growth=0.0))["C1"]["revenue_growth"]
    assert zero["status"] == "valid" and zero["raw_value"] == 0.0
    assert "real zero" in zero["validation_reason"]
    neg = build(one_company(revenue_growth=-40.0))["C1"]["revenue_growth"]
    assert neg["status"] == "valid" and neg["raw_value"] == -40.0
    miss = build(one_company(revenue_growth=None))["C1"]["revenue_growth"]
    assert miss["status"] == "missing" and miss["raw_value"] is None
    assert "order-2" in miss["validation_reason"]


def test_revenue_growth_huge_value_warns_but_never_invalidated():
    # mission rule: very large growth is NOT auto-invalidated — an
    # independent data warning stays attached, the raw value is kept
    rec = build(one_company(revenue_growth=8000.0))["C1"]["revenue_growth"]
    assert rec["status"] == "valid" and rec["raw_value"] == 8000.0
    assert any(w.startswith("magnitude_anomaly") for w in rec["warnings"])
    assert rec["warnings"][0].startswith("magnitude_anomaly: revenue growth")


def test_revenue_growth_non_finite_invalid():
    rec = build(one_company(revenue_growth=float("inf")))
    assert rec["C1"]["revenue_growth"]["status"] == "invalid"


def test_new_factors_directions_match_config_registry():
    for fid in ("roe_level", "margin_trend", "revenue_growth"):
        assert CFG.V2_QVT_FACTORS[fid]["direction"] == "higher"


def test_new_factors_never_mutate_metrics_or_bases():
    import copy
    m = one_company(margin_trend=3.0)
    bases = {"C1": {"operating_profit_prev": 125.0, "revenue_prev": 1000.0}}
    m_snap, b_snap = copy.deepcopy(m), copy.deepcopy(bases)
    SR.build_q_raw(m, prev_bases=bases)
    assert m == m_snap and bases == b_snap


def test_expense_pair_in_raw_scope_but_channel_gated():
    # 2-B-7: interest_coverage / earnings_quality are IMPLEMENTED raw-layer
    # factors now — but only through the caller-supplied same-window expense
    # TTM channel. The engine's window-mismatched derived metrics (a TTM
    # numerator over an order-1 YTD denominator, the 2-B-5 audit finding)
    # are NEVER substituted: without a channel the records exist and stay
    # missing. roe_stability / roic remain the only not-implemented Q
    # factors, and the quality-axis union stays complete.
    assert "interest_coverage" in SR.IN_SCOPE_FACTORS
    assert "earnings_quality" in SR.IN_SCOPE_FACTORS
    assert set(SR.NOT_IMPLEMENTED_Q_FACTORS) == {"roe_stability", "roic"}
    assert set(SR.IN_SCOPE_FACTORS) | set(SR.NOT_IMPLEMENTED_Q_FACTORS) == {
        fid for fid, e in CFG.V2_QVT_FACTORS.items() if e["axis"] == "quality"}
    out = build(one_company(interest_coverage=4.0, earnings_quality=10.0))
    assert out["C1"]["interest_coverage"]["status"] == "missing"
    assert "channel not supplied" in \
        out["C1"]["interest_coverage"]["validation_reason"]
    assert out["C1"]["earnings_quality"]["status"] == "missing"
    assert "channel not supplied" in \
        out["C1"]["earnings_quality"]["validation_reason"]
