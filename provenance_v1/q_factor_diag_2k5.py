# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ P1 — هستهٔ خالص فاکتورهای تشخیصی Q (روی داده واقعی؛ DB-free).

سه فاکتور «فعلاً غیرفعال» موتور Q با محاسبهٔ تشخیصی معتبر پوشش داده می‌شوند.
هیچ‌کدام در امتیاز رسمی Q وارد نمی‌شوند (وزن و فرمول رسمی دست‌نخورده)؛ این
ماژول فقط مقدار خام، کفایت شواهد، پوشش و محدودیت‌ها را صادقانه تولید می‌کند.

قراردادهای کلیدی (مطابق موتور):
  * roe_stability — پایداری ROE سالانه؛ کمتر بهتر (config: direction=lower،
    weight 3، غیرضروری). مقدار = انحراف معیار (جمعیت) ROE سالانه برحسب واحد
    درصد در پنجرهٔ ۵ سال مالی؛ حداقل ۳ سال معتبر. سالِ معتبر: NP سالانهٔ
    ۱۲ماههٔ حل‌شده + equity ترتیب-۱ مثبت متناهی در همان سلول (fy,12) + بدون
    آلودگی سنتیل. ROE منفی سال واقعیِ ضرردهی است: معتبر می‌ماند (هیچ‌گاه
    صفر یا حذف نمی‌شود)؛ equity نامعتبر (صفر/منفی/غایب) سال را invalid_equity
    می‌کند و هیچ جایگزینی ساخته نمی‌شود.
  * margin_trend — روند حاشیهٔ سود عملیاتی فقط از دوره‌های واقعاً
    قابل‌مقایسه: TTM فعلی نسبت به TTM سال قبلِ هم‌پنجره (فرمول رسمی raw) و
    سری سالانهٔ تشخیصی فقط روی سلول‌های (fy,12) با درآمد اکیداً مثبت.
    تفاوت فصلی/سالانه/TTM صریح نگه داشته می‌شود؛ دورهٔ فصلی هرگز با سالانه
    مقایسه نمی‌شود.
  * earnings_growth — رشد سود فقط با پایهٔ تأییدشدهٔ سال قبل (prev_bases)؛
    قرنطینهٔ ۱۰٬۶۵۰ ردیف سنتیل legacy کاملاً حفظ می‌شود: دادهٔ قرنطینه‌شده
    هیچ مسیر جایگزینی به مقدار معتبر ندارد — اثباتش با
    earnings_growth_quarantine_proof.
"""
from __future__ import annotations

import math

MIN_ROE_YEARS = 3
ROE_WINDOW_YEARS = 5

ROE_STABILITY_DEF = (
    "roe_stability_diag = stdev(ROE سالانه) برحسب واحد درصد؛ ROE_y = "
    "net_profit_12m(fy) / total_equity(fy) × 100 روی سلول (fy, fiscal_month=12). "
    "کمتر بهتر. حداقل ۳ سال معتبر در پنجرهٔ حداکثر ۵ سال مالی. سال معتبر = NP "
    "و equity متناهی + equity > 0 + بدون قرنطینهٔ سنتیل. equity سالانه از دو "
    "پایهٔ واقعی می‌آید: order-1 سلول خود سال، یا در نبودش order-2 (ستون "
    "مقایسه‌ای پایان دورهٔ قبل) گزارش سالانهٔ سال بعد — هرگز میانگین‌سازی یا "
    "حدس. ROE منفی سالِ ضررده دادهٔ واقعی است و حذف نمی‌شود؛ equity نامعتبر "
    "سال را بدون جایگزین خارج می‌کند. این مقدار تشخیصی است و در امتیاز رسمی Q "
    "وارد نمی‌شود.")

MARGIN_TREND_DEF = (
    "margin_trend رسمی = حاشیهٔ سود عملیاتی TTM اکنون منهای حاشیهٔ TTM سال قبل "
    "(هر دو بر درآمد اکیداً مثبت؛ برحسب واحد درصد) — فقط پایهٔ TTM سال قبلِ "
    "provenance-match؛ پایهٔ قرنطینه‌شده یا حل‌نشده = missing صادقانه. سری "
    "سالانهٔ تشخیصی فقط روی سلول‌های (fy,12) (سالانه با سالانه مقایسه می‌شود؛ "
    "فصلی هرگز وارد روند نمی‌شود).")

EARNINGS_GROWTH_DEF = (
    "growth_pct = (جریان فعلی − پایهٔ سال قبل) / پایهٔ سال قبل × 100؛ فقط برای "
    "پایهٔ اکیداً مثبت تأییدشده. صفر بودن پایه، پایهٔ منفی و تغییر علامت سود "
    "وضعیت‌های مجزا و غیردرصدی‌اند. قرنطینهٔ ۲-ب-۴-۲ (۱۰٬۶۵۰ ردیف سنتیل "
    "±1e6/±1e8 روی net_profit/operating_profit) کامل حفظ می‌شود؛ دادهٔ "
    "قرنطینه‌شده هیچ مسیر جایگزینی به مقدار معتبر ندارد.")


def roe_stability_from_series(series: list) -> dict:
    """series: [{fy, net_profit, equity, quarantined}] (مرتب یا نامرتب؛ سال‌های
    ۱۲ماهه). خروجی: مقدار تشخیصی پایداری ROE + شواهد کفایت + سال‌های حذف‌شده
    با دلیل. خالص و deterministic."""
    by_fy = {}
    for s in series or []:
        fy = s.get("fy")
        if fy is None:
            continue
        by_fy[int(fy)] = s
    if not by_fy:
        return {"status": "insufficient_evidence", "value": None,
                "reason": "no_annual_cells", "n_valid": 0, "years": [],
                "excluded_years": [], "definition": ROE_STABILITY_DEF,
                "min_periods_rule": MIN_ROE_YEARS}
    latest = max(by_fy)
    window = sorted(fy for fy in by_fy if fy > latest - ROE_WINDOW_YEARS)
    valid, excluded = [], []
    for fy in window:
        s = by_fy[fy]
        np_, eq = s.get("net_profit"), s.get("equity")
        if s.get("quarantined"):
            excluded.append({"fy": fy,
                             "reason": "quarantined_legacy_sentinel"})
            continue
        if np_ is None or not _finite(np_):
            excluded.append({"fy": fy, "reason": "net_profit_unresolved"})
            continue
        if eq is None or not _finite(eq):
            excluded.append({"fy": fy, "reason": "equity_missing"})
            continue
        if eq <= 0:
            # equity نامعتبر: سال حذف می‌شود و هیچ ROE جایگزینی ساخته نمی‌شود
            excluded.append({"fy": fy, "reason": "equity_nonpositive"})
            continue
        valid.append({"fy": fy, "roe_pct": float(np_) / float(eq) * 100.0,
                      "net_profit": float(np_), "equity": float(eq),
                      **({"equity_basis": s["equity_basis"]}
                         if s.get("equity_basis") else {})})
    if len(valid) < MIN_ROE_YEARS:
        return {"status": "insufficient_evidence", "value": None,
                "reason": f"only_{len(valid)}_valid_years_of_min_{MIN_ROE_YEARS}",
                "n_valid": len(valid), "valid_years": valid,
                "excluded_years": excluded, "window": window,
                "definition": ROE_STABILITY_DEF,
                "min_periods_rule": MIN_ROE_YEARS}
    xs = [v["roe_pct"] for v in valid]
    mean = math.fsum(xs) / len(xs)
    var = math.fsum((x - mean) ** 2 for x in xs) / len(xs)
    std = math.sqrt(var)
    notes = []
    if mean < 0:
        notes.append("میانگین ROE پنجره منفی است — سال‌های ضررده دادهٔ واقعی‌اند")
    return {"status": "computed", "value": std, "unit": "percentage_points",
            "direction": "lower_is_better", "n_valid": len(valid),
            "mean_roe_pct": mean, "min_roe_pct": min(xs), "max_roe_pct": max(xs),
            "valid_years": valid, "excluded_years": excluded, "window": window,
            "notes": notes, "definition": ROE_STABILITY_DEF,
            "min_periods_rule": MIN_ROE_YEARS}


def annual_growth_from_series(np_by_fy: dict) -> list:
    """رشد سالانهٔ تشخیصی از سری NP سالانه؛ فقط پایهٔ اکیداً مثبت. تغییر علامت
    و پایهٔ نامعتبر وضعیت مجزا (non-pct) می‌مانند. خروجی مرتب بر fy."""
    out = []
    for fy in sorted(np_by_fy):
        prev = np_by_fy.get(fy - 1)
        cur = np_by_fy[fy]
        if cur is None or not _finite(cur):
            out.append({"fy": fy, "state": "current_missing"})
            continue
        if prev is None or not _finite(prev):
            out.append({"fy": fy, "state": "base_missing"})
            continue
        if prev == 0:
            out.append({"fy": fy, "state": "base_zero_not_applicable"})
            continue
        if prev < 0:
            out.append({"fy": fy, "state": "negative_base_not_applicable",
                        "sign_change": cur > 0})
            continue
        out.append({"fy": fy, "state": "computed",
                    "growth_pct": (float(cur) - float(prev)) / float(prev) * 100.0,
                    "turned_to_loss": cur < 0})
    return out


def annual_margin_from_series(op_by_fy: dict, rev_by_fy: dict) -> list:
    """حاشیهٔ سود عملیاتی سالانهٔ تشخیصی؛ فقط درآمد اکیداً مثبت. فصلی/TTM با
    این سری مقایسه نمی‌شوند (تفکیک دوره‌ای صریح)."""
    out = []
    for fy in sorted(set(op_by_fy) | set(rev_by_fy)):
        op, rev = op_by_fy.get(fy), rev_by_fy.get(fy)
        if rev is None or not _finite(rev):
            out.append({"fy": fy, "state": "revenue_missing"})
            continue
        if rev <= 0:
            out.append({"fy": fy, "state": "revenue_nonpositive_not_computable"})
            continue
        if op is None or not _finite(op):
            out.append({"fy": fy, "state": "operating_profit_missing"})
            continue
        out.append({"fy": fy, "state": "computed",
                    "operating_margin_pct": float(op) / float(rev) * 100.0})
    return out


def margin_trend_official(cur_op_ttm, cur_rev_ttm, prev_op, prev_rev) -> dict:
    """بازتولید قرارداد رسمی margin_trend (score_v2_raw._build_margin_trend):
    هر دو حاشیه بر درآمد اکیداً مثبت؛ پایهٔ غایب/قرنطینه‌شده = missing صادقانه؛
    درآمد قبلی صفر = n/a؛ منفی = invalid؛ تفاضل > ±200pp = warning (معتبر)."""
    if cur_op_ttm is None or cur_rev_ttm is None or prev_op is None or prev_rev is None:
        return {"status": "missing",
                "reason": "a needed input is absent (prior base unresolved "
                          "or quarantined — no substitution)"}
    if not (_finite(cur_op_ttm) and _finite(cur_rev_ttm)
            and _finite(prev_op) and _finite(prev_rev)):
        return {"status": "invalid", "reason": "non_finite input"}
    if cur_rev_ttm <= 0 or prev_rev <= 0:
        if prev_rev == 0:
            return {"status": "not_applicable",
                    "reason": "prior-year revenue is zero"}
        return {"status": "invalid",
                "reason": "negative revenue is economically impossible "
                          "(general family)"}
    cur_m = float(cur_op_ttm) / float(cur_rev_ttm) * 100.0
    prev_m = float(prev_op) / float(prev_rev) * 100.0
    trend = cur_m - prev_m
    warnings = []
    if abs(trend) > 200.0:
        warnings.append(
            f"magnitude_anomaly: trend {trend:.1f}pp beyond ±200pp — kept as "
            "real data (diagnostic)")
    return {"status": "computed", "value_pp": trend,
            "cur_margin_pct": cur_m, "prev_margin_pct": prev_m,
            "warnings": warnings}


def earnings_growth_quarantine_proof(raw_by_company: dict,
                                     quarantined_tags: dict) -> dict:
    """اثبات نشت‌ناپذیری قرنطینه: هیچ جزء رشدی که پایه‌اش قرنطینه شده نباید
    valid باشد. خروجی آمار + نقض‌ها (باید صفر باشد)."""
    checked, leaks = 0, []
    n_quarantined_companies = len(quarantined_tags or {})
    for cid, tags in (quarantined_tags or {}).items():
        rec = (raw_by_company or {}).get(cid) or {}
        comp = (rec.get("earnings_growth") or {}).get("components") or {}
        for tag in tags:
            comp_name = ("net_profit_growth_pct" if tag == "net_profit_prev"
                         else "operating_profit_growth_pct")
            c = comp.get(comp_name) or {}
            checked += 1
            if c.get("status") == "valid":
                leaks.append({"company_id": cid, "tag": tag,
                              "component": comp_name})
    return {
        "policy": ("قرنطینهٔ ۲-ب-۴-۲: پایهٔ سال قبلِ مصرف‌کنندهٔ سلول سنتیل حذف "
                   "می‌شود؛ raw لایه بدون پایه → missing؛ هیچ جایگزینی مجاز نیست"),
        "sentinel_signature": {"values_rial": [1_000_000.0, -1_000_000.0,
                                               100_000_000.0, -100_000_000.0],
                               "metrics": ["net_profit", "operating_profit"]},
        "n_companies_with_quarantined_base": n_quarantined_companies,
        "n_quarantined_components_checked": checked,
        "n_valid_despite_quarantine": len(leaks),
        "leaks": leaks,
        "verdict": ("LEAK_DETECTED" if leaks
                    else "quarantine_leak_free — دادهٔ قرنطینه‌شده هیچ مسیری "
                         "به مقدار معتبر ندارد"),
    }


def coverage_by_industry(rows: list, industry_of, status_key="status",
                         computed_states=("computed", "valid")) -> dict:
    """پوشش واقعی بر اساس صنعت: {industry: {n, computed, insufficient, other}}
    از ردیف‌های {company_id, status} — هیچ عددی hardcode نمی‌شود."""
    agg = {}
    for r in rows or []:
        ind = industry_of(r) or "unknown"
        a = agg.setdefault(ind, {"n": 0, "computed": 0, "insufficient": 0,
                                 "other": 0})
        a["n"] += 1
        st = r.get(status_key)
        if st in computed_states:
            a["computed"] += 1
        elif st in ("insufficient_evidence",):
            a["insufficient"] += 1
        else:
            a["other"] += 1
    return dict(sorted(agg.items(), key=lambda kv: (-kv[1]["computed"], kv[0])))


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(float(v))
