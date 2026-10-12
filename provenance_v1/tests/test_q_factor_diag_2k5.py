# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ P1 — تست هستهٔ خالص فاکتورهای تشخیصی (بدون DB).

بازتولید مستقل نمونه‌ها، کنترل نشت قرنطینه، مقایسهٔ دوره‌ها و واحدها، و
دادهٔ مفقود — همه با فیچورهای سینتتیک قطعی.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import q_factor_diag_2k5 as D  # noqa: E402


# ── roe_stability ─────────────────────────────────────────────────────────────
def test_roe_stability_computed_over_three_valid_years():
    series = [
        {"fy": 1400, "net_profit": 100.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1401, "net_profit": 200.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1402, "net_profit": 150.0, "equity": 1000.0, "quarantined": False},
    ]
    r = D.roe_stability_from_series(series)
    assert r["status"] == "computed"
    # ROE: 10, 20, 15 → mean 15 → var (25+25+0)/3 → std = sqrt(50/3)
    import math
    assert math.isclose(r["value"], math.sqrt(50.0 / 3.0))
    assert r["n_valid"] == 3
    assert r["direction"] == "lower_is_better"


def test_roe_negative_years_are_valid_data_not_dropped():
    """ROE منفی سالِ ضررده است: معتبر می‌ماند و در پراکندگی وارد می‌شود."""
    series = [
        {"fy": 1400, "net_profit": -100.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1401, "net_profit": 200.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1402, "net_profit": 150.0, "equity": 1000.0, "quarantined": False},
    ]
    r = D.roe_stability_from_series(series)
    assert r["status"] == "computed"
    assert r["n_valid"] == 3
    assert any(v["roe_pct"] == -10.0 for v in r["valid_years"])
    assert r["min_roe_pct"] == -10.0


def test_roe_invalid_equity_excluded_without_substitution():
    """equity صفر/منفی/غایب → سال حذف با دلیل صریح؛ هیچ ROE جایگزینی ساخته
    نمی‌شود و اگر تعداد معتبر زیر حداقل برود → insufficient_evidence."""
    series = [
        {"fy": 1400, "net_profit": 100.0, "equity": 0.0, "quarantined": False},
        {"fy": 1401, "net_profit": 100.0, "equity": -50.0, "quarantined": False},
        {"fy": 1402, "net_profit": 100.0, "equity": None, "quarantined": False},
        {"fy": 1403, "net_profit": 100.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1404, "net_profit": 100.0, "equity": 1000.0, "quarantined": False},
    ]
    r = D.roe_stability_from_series(series)
    # فقط ۲ سال معتبر از ۵ → زیر حداقل ۳ سال → insufficient_evidence صادقانه
    assert r["status"] == "insufficient_evidence"
    assert r["value"] is None
    assert r["n_valid"] == 2
    reasons = {e["fy"]: e["reason"] for e in r["excluded_years"]}
    assert reasons[1400] == "equity_nonpositive"
    assert reasons[1401] == "equity_nonpositive"
    assert reasons[1402] == "equity_missing"


def test_roe_below_min_periods_is_insufficient():
    series = [
        {"fy": 1402, "net_profit": 100.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1403, "net_profit": 120.0, "equity": 1000.0, "quarantined": False},
    ]
    r = D.roe_stability_from_series(series)
    assert r["status"] == "insufficient_evidence"
    assert r["value"] is None


def test_roe_window_is_last_five_years():
    series = [{"fy": fy, "net_profit": 100.0, "equity": 1000.0,
               "quarantined": False} for fy in range(1396, 1404)]
    r = D.roe_stability_from_series(series)
    assert r["window"] == [1399, 1400, 1401, 1402, 1403]


def test_roe_quarantined_year_excluded():
    series = [
        {"fy": 1400, "net_profit": 1_000_000.0, "equity": 1000.0,
         "quarantined": True},
        {"fy": 1401, "net_profit": 200.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1402, "net_profit": 150.0, "equity": 1000.0, "quarantined": False},
        {"fy": 1403, "net_profit": 120.0, "equity": 1000.0, "quarantined": False},
    ]
    r = D.roe_stability_from_series(series)
    assert r["status"] == "computed"
    assert any(e["reason"] == "quarantined_legacy_sentinel"
               for e in r["excluded_years"])
    assert all(v["fy"] != 1400 for v in r["valid_years"])


# ── margin_trend ──────────────────────────────────────────────────────────────
def test_margin_trend_official_like_for_like_ttm():
    r = D.margin_trend_official(cur_op_ttm=200.0, cur_rev_ttm=1000.0,
                                prev_op=100.0, prev_rev=1000.0)
    assert r["status"] == "computed"
    assert r["value_pp"] == 10.0  # 20% − 10%


def test_margin_trend_missing_prior_base_is_missing_not_zero():
    r = D.margin_trend_official(cur_op_ttm=200.0, cur_rev_ttm=1000.0,
                                prev_op=None, prev_rev=1000.0)
    assert r["status"] == "missing"
    assert r.get("value_pp") is None


def test_margin_trend_zero_prior_revenue_not_applicable_negative_invalid():
    r0 = D.margin_trend_official(200.0, 1000.0, 100.0, 0.0)
    assert r0["status"] == "not_applicable"
    rn = D.margin_trend_official(200.0, 1000.0, 100.0, -500.0)
    assert rn["status"] == "invalid"


def test_margin_trend_quarterly_never_mixed_into_annual_series():
    """سری سالانه فقط از سلول‌های (fy,12) ساخته می‌شود؛ سلول فصلی هرگز وارد
    روند نمی‌شود — کنترل در سطح runner؛ اینجا قرارداد سری سالانه."""
    op = {1401: 300.0}
    rev = {1401: 1500.0, 1402: 2000.0}
    s = D.annual_margin_from_series(op, rev)
    st = {x["fy"]: x for x in s}
    assert st[1401]["state"] == "computed"
    assert st[1402]["state"] == "operating_profit_missing"


# ── earnings_growth ───────────────────────────────────────────────────────────
def test_growth_zero_base_and_sign_flip_are_not_percentages():
    s = D.annual_growth_from_series({
        1400: 0.0, 1401: 500.0, 1402: -200.0, 1403: 300.0})
    st = {x["fy"]: x for x in s}
    assert st[1401]["state"] == "base_zero_not_applicable"
    # ۱۴۰۲: پایهٔ ۱۴۰۱ مثبت (۵۰۰) و فعلی منفی → درصد منفی استاندارد با
    # نشان turned_to_loss (هرگز نتیجهٔ مطلوب رشد خوانده نمی‌شود)
    assert st[1402]["state"] == "computed"
    assert st[1402]["turned_to_loss"] is True
    assert st[1402]["growth_pct"] == -140.0
    # ۱۴۰۳: پایهٔ منفی → not_applicable با نشان تغییر علامت (ضررده→سودده)
    assert st[1403]["state"] == "negative_base_not_applicable"
    assert st[1403]["sign_change"] is True


def test_growth_turned_to_loss_keeps_negative_percent_with_flag():
    s = D.annual_growth_from_series({1400: 200.0, 1401: -100.0})
    x = s[1]  # سال ۱۴۰۱: پایهٔ ۱۴۰۰ مثبت؛ ۱۴۰۰ خودش base_missing است
    assert x["state"] == "computed"
    assert x["growth_pct"] == -150.0
    assert x["turned_to_loss"] is True
    assert s[0]["state"] == "base_missing"


def test_quarantine_proof_detects_no_leak_and_leak():
    def rec(np_status, op_status):
        return {"earnings_growth": {"components": {
            "net_profit_growth_pct": {"status": np_status},
            "operating_profit_growth_pct": {"status": op_status}}}}

    clean = {"c1": rec("missing", "missing")}
    qt = {"c1": ["net_profit_prev"]}
    p = D.earnings_growth_quarantine_proof(clean, qt)
    assert p["verdict"].startswith("quarantine_leak_free")
    assert p["n_valid_despite_quarantine"] == 0

    leaky = {"c1": rec("valid", "missing")}
    p2 = D.earnings_growth_quarantine_proof(leaky, qt)
    assert p2["verdict"] == "LEAK_DETECTED"
    assert p2["leaks"][0]["component"] == "net_profit_growth_pct"


def test_quarantine_proof_signature_matches_2b42_policy():
    p = D.earnings_growth_quarantine_proof({}, {})
    assert p["sentinel_signature"]["values_rial"] == [
        1_000_000.0, -1_000_000.0, 100_000_000.0, -100_000_000.0]
    assert p["sentinel_signature"]["metrics"] == ["net_profit",
                                                  "operating_profit"]


# ── پوشش ──────────────────────────────────────────────────────────────────────
def test_coverage_by_industry_counts_from_real_rows():
    rows = [
        {"company_id": "a", "industry": "فلزات", "status": "computed"},
        {"company_id": "b", "industry": "فلزات", "status": "insufficient_evidence"},
        {"company_id": "c", "industry": None, "status": "raw_missing"},
    ]
    cov = D.coverage_by_industry(rows, lambda r: r["industry"])
    assert cov["فلزات"] == {"n": 2, "computed": 1, "insufficient": 1, "other": 0}
    assert cov["unknown"]["n"] == 1
