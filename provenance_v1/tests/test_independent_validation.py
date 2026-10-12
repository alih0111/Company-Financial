"""گام ۲-ک-۲ — تست‌های بدون دیتابیس برای منطق اعتبارسنجی مستقل.

پیاده‌سازی مستقل TTM (my_ttm) و پروب T (stock_returns / my_vol_liq) و
استخراج مدت دوره از عنوان کدال — قراردادهای مستند لایه خام بازتولید و
رفتارهای سخت (رد پایه‌های PIT-اثبات‌نشده) کنترل می‌شوند.
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_independent_validation import (  # noqa: E402
    LIQ_MIN_OBS, my_ttm, my_vol_liq, fnum, rdiff_ok, rel_diff,
    stock_returns, title_duration_months, months_back)


def cell(value, pit="E2_recovered_verified", report="r1"):
    return {"value": value, "pit": pit, "report_id": report,
            "period_end": "2026-01-01", "pub_at": "2026-01-02T00:00:00",
            "title": None, "unit": "rial"}


def ok_vis(d):
    return d is not None and d["pit"] != "unproven"


# ── title_duration_months ────────────────────────────────────────────────

def test_title_duration_interim_and_annual():
    assert title_duration_months(
        "اطلاعات و صورت‌های مالی میاندوره‌ای تلفیقی دوره ۶ ماهه منتهی به "
        "۱۴۰۴/۰۴/۳۱ (حسابرسی شده)") == 6
    assert title_duration_months(
        "اطلاعات و صورت‌های مالی میاندوره‌ای دوره ۹ ماهه منتهی به "
        "۱۴۰۴/۰۹/۳۰ (حسابرسی نشده)") == 9
    assert title_duration_months(
        "صورت‌های مالی تلفیقی سال مالی منتهی به ۱۴۰۱/۱۲/۲۹") == 12
    assert title_duration_months("صورت‌های مالی سالانه ۱۴۰۳") == 12
    assert title_duration_months("اطلاعات و ارقام عملکرد ماهانه") is None
    assert title_duration_months(None) is None


# ── my_ttm: پیاده‌سازی مستقل ─────────────────────────────────────────────

def _cells(cur, p3=None, p2=None, annual=None, pit="E2_recovered_verified"):
    cells = {
        (1405, 4): {"metrics": {"net_profit": {
            1: cell(cur, pit),
            **({3: cell(p3, pit)} if p3 is not None else {}),
            **({2: cell(p2, pit)} if p2 is not None else {}),
        }}},
    }
    if annual is not None:
        cells[(1404, 12)] = {"metrics": {"net_profit": {1: cell(annual, pit)}}}
    return cells


def test_my_ttm_same_report_legs():
    # TTM = cur + prior_FY - prior_YTD از همان گزارش
    v, prov, legs = my_ttm(_cells(900, 300, 100), "net_profit", 1405, 4,
                           12, False, ok_vis)
    assert v == 900 + 300 - 100
    assert prov == "SAME_REPORT_LEGS"
    assert legs["prior_full_fy"]["value"] == 300


def test_my_ttm_annual_cell():
    # fm == annual_month → سلول جاری همان گزارش سالانه است
    v, prov, _ = my_ttm(_cells(500), "net_profit", 1405, 4, 4, False, ok_vis)
    assert v == 500 and prov == "ANNUAL_CELL"


def test_my_ttm_chain_legs():
    cells = {
        (1405, 4): {"metrics": {"net_profit": {1: cell(200)}}},
        (1404, 12): {"metrics": {"net_profit": {1: cell(1000)}}},
        (1404, 4): {"metrics": {"net_profit": {1: cell(150)}}},
    }
    v, prov, legs = my_ttm(cells, "net_profit", 1405, 4, 12, False, ok_vis)
    assert v == 1000 + 200 - 150
    assert prov == "CHAIN_LEGS"
    assert legs["annual_anchor_m1"]["cell"] == [1404, 12]


def test_my_ttm_refuses_unproven_legs():
    # پایهٔ بدون تاریخ انتشار اثبات‌شده هرگز مصرف نمی‌شود — حتی اگر مقدار باشد
    cells = _cells(900, 300, 100, pit="unproven")
    v, prov, _ = my_ttm(cells, "net_profit", 1405, 4, 12, False, ok_vis)
    assert v is None
    assert prov == "INSUFFICIENT_OR_UNPROVEN"


def test_my_ttm_chain_skips_unproven_anchor():
    # anchor سالانهٔ بدون تاریخ → به anchor قدیمی‌ترِ اثبات‌شده نمی‌رسیم مگر
    # واقعاً موجود باشد؛ با anchor unproven و بدون قدیمی‌تر، None برمی‌گردد
    cells = {
        (1405, 4): {"metrics": {"net_profit": {1: cell(200)}}},
        (1404, 12): {"metrics": {"net_profit": {1: cell(1000, "unproven")}}},
        (1404, 4): {"metrics": {"net_profit": {1: cell(150)}}},
    }
    v, prov, legs = my_ttm(cells, "net_profit", 1405, 4, 12, False, ok_vis)
    assert v is None and prov == "NO_PROVEN_ANNUAL_ANCHOR"


# ── پروب T مستقل ─────────────────────────────────────────────────────────

def test_stock_returns_basic_and_gap():
    import datetime as dt
    base = dt.date(2026, 10, 5)
    # 100 → 110؛ اولین نقطه قبل از مرجع ۶ماهه (2026-04-08)
    recs = [{"date": base - dt.timedelta(days=200), "close": 100.0,
             "tv": 1.0, "collected_at": None},
            {"date": base, "close": 110.0, "tv": 1.0, "collected_at": None}]
    r6, r3, age, g6, g3 = stock_returns(recs, base)
    assert abs(r6 - 0.10) < 1e-9 and abs(r3 - 0.10) < 1e-9
    assert g6 is False and g3 is False
    # پرش ۲۵٪ — هیچ سشن TSE پیوسته‌ای تولید نمی‌کند → gap flag
    recs2 = [{"date": base - dt.timedelta(days=200), "close": 100.0,
              "tv": 1.0, "collected_at": None},
             {"date": base - dt.timedelta(days=90), "close": 125.0,
              "tv": 1.0, "collected_at": None},
             {"date": base, "close": 125.0, "tv": 1.0, "collected_at": None}]
    r6b, r3b, _age, g6b, _g3 = stock_returns(recs2, base)
    assert g6b is True
    assert r6b is not None  # مقدار خام هست؛ فقط در benchmark مصرف نمی‌شود


def test_my_vol_liq_contract():
    import statistics
    import datetime as dt
    base = dt.date(2026, 10, 5)
    closes = [100.0 + (i % 3) for i in range(40)]
    recs = [{"date": base - dt.timedelta(days=39 - i), "close": c,
             "tv": float(1000 + i), "collected_at": None}
            for i, c in enumerate(closes)]
    vol, liq, diag = my_vol_liq(recs)
    rets = [closes[i + 1] / closes[i] - 1.0 for i in range(len(closes) - 1)]
    assert abs(vol - statistics.stdev(rets[-30:])) < 1e-12
    assert abs(liq - (sum(range(1010, 1040)) / 30)) < 1e-9
    assert diag["n_vol_returns"] == 30


# ── کمکی‌ها ──────────────────────────────────────────────────────────────

def test_rel_diff_and_fnum():
    assert rel_diff(100.0, 100.0) == 0.0
    assert rdiff_ok(100.0, 100.000001)
    assert not rdiff_ok(100.0, 101.0)
    assert rel_diff(None, 1.0) is None
    assert fnum(float("inf")) is None
    assert fnum("12.5") == 12.5
    assert fnum(None) is None
    assert fnum(True) is None  # bool هرگز عدد مالی نیست


def test_months_back_clamps_day():
    assert months_back(date(2026, 8, 31), 6) == date(2026, 2, 28)
    assert months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_back(date(2026, 10, 8), 3) == date(2026, 7, 8)
