#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۹ / P1 — پروندهٔ اقتصادی قابل بازتولید برای نامزدهای اصلی و مبهم.

هدف: تفکیک قطعی «پرسنتایل آرتیفکت» از «نسبت مالی خام» و بازکردن معنای
اقتصادی هر عدد، تا مشخص شود نامزدی مثل بوعلی واقعاً قابل دفاع است یا فقط
آستانهٔ عددی را رد کرده است.

منابع (همه canonical / دارای provenance واقعی):
  - canonical_v1_metrics.json  → نسبت‌های خام (roe, net_margin, np_ttm,
    op_ttm, ocf_ttm, pe, pb, ps, market_cap, shares, price, ...) + _ttm_prov
    + _valuation_prov
  - v2_q_observed_report.json  → پرسنتایل عوامل Q (بدون raw؛ قرارداد Q فقط
    درصد رتبه دارد) + پوشش + گیت‌ها
  - v2_value_pilot.json        → p/e/p/b/p/s خام و درصد + گروه نرمال‌سازی
  - v2_t_pilot.json            → مومنتوم/نقدشوندگی/نوسان خام و درصد
  - _board_2k8_live.json       → گروه تصمیم و اندازهٔ گروه همتا (تنها منبع گروه)

خروجی: provenance_v1/output/economic_cases_2k9_<TAG>.json
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

TARGETS = [
    # (symbol, role)
    ("بوعلی", "نامزد جذاب فعلی — پروندهٔ اصلی"),
    ("شسپا", "نزدیک — بنیادی قوی، گروه همتای کوچک"),
    ("شبصیر", "نزدیک — بنیادی قوی، گروه همتای کوچک"),
    ("سباقر", "نزدیک — بنیادی قوی، ارزندگی ضعیف"),
    ("غاذر", "نزدیک — بنیادی قوی، ارزندگی ضعیف"),
    ("آردینه", "نزدیک — بنیادی قوی، ارزندگی میانه"),
    ("ساروم", "نزدیک — بنیادی قوی، ارزندگی ضعیف"),
    ("شپدیس", "نزدیک — بنیادی قوی، ارزندگی مرزی"),
    ("نان", "ارزان‌نمای پرریسک"),
    ("فولاد", "ارزان‌نمای پرریسک"),
    ("ذوب", "ارزان‌نمای پرریسک — سود عملیاتی منفی"),
    ("غپینو", "ارزان‌نمای پرریسک"),
    ("شیران", "ارزان‌نمای پرریسک"),
    ("زبینا", "ارزان‌نمای پرریسک"),
    ("تلیسه", "ارزان‌نمای پرریسک"),
    ("کپارس", "ارزان‌نمای پرریسک"),
    ("کحافظ", "ارزان‌نمای پرریسک"),
    ("کلر", "از ۱۶ نامزد ۲-ک-۷"),
    ("غمینو", "از ۱۶ نامزد ۲-ک-۷"),
    ("سهگمت", "از ۱۶ نامزد ۲-ک-۷"),
    ("غکورش", "از ۱۶ نامزد ۲-ک-۷"),
    ("کرماشا", "از ۱۶ نامزد ۲-ک-۷"),
    ("شکام", "از ۱۶ نامزد ۲-ک-۷"),
    ("خراسان", "از ۱۶ نامزد ۲-ک-۷"),
    ("سقاین", "از ۱۶ نامزد ۲-ک-۷"),
    ("سصوفی", "از ۱۶ نامزد ۲-ک-۷"),
]

metrics = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))
q = json.load(open(os.path.join(ART, "v2_q_observed_report.json"), encoding="utf-8"))
v = json.load(open(os.path.join(ART, "v2_value_pilot.json"), encoding="utf-8"))
t = json.load(open(os.path.join(ART, "v2_t_pilot.json"), encoding="utf-8"))
qc = q["companies"]
vc = v["v_observed_report"]["companies"]
tc = t["t_observed_report"]["companies"]
live = json.load(open(os.path.join(OUT, "_board_2k8_live.json"), encoding="utf-8"))
ob = live["opportunity_board"]
GROUP_FA = {
    "attractive_candidates": "نامزد جذاب برای بررسی جدی",
    "fundamentals_waiting": "بنیادی مناسب — منتظر شرایط بهتر",
    "apparent_value_risk": "ارزان‌نما — نیازمند احتیاط",
    "blocked_or_insufficient": "شواهد ناکافی/مانع",
}
board_by_sym = {}
for g in GROUP_FA:
    for e in ob.get(g, []):
        board_by_sym[e["symbol"]] = (g, e)

sym2cid = {c.get("symbol"): cid for cid, c in metrics.items()}


def f2(x, nd=4):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def pct_score(cm, fid):
    f = (cm or {}).get("factors", {}).get(fid, {})
    return f.get("score"), f.get("raw_value"), f.get("warnings") or [], f.get("included")


rows = []
for sym, role in TARGETS:
    cid = sym2cid.get(sym)
    if not cid:
        rows.append({"symbol": sym, "role": role, "error": "در canonical_v1_metrics یافت نشد"})
        continue
    m = metrics[cid]
    qcm, vcm, tcm = qc.get(cid), vc.get(cid), tc.get(cid)

    np_ttm = m.get("net_profit_ttm")
    op_ttm = m.get("operating_profit_ttm")
    ocf_ttm = m.get("ocf_ttm")
    rec = {
        "symbol": sym,
        "role": role,
        "company_id": cid,
        "industry": m.get("symbol") and (qcm or {}).get("industry"),
        "model_family": (qcm or {}).get("model_family"),
        "board_group": (board_by_sym.get(sym) or (None, None))[0],
        "board_group_fa": GROUP_FA.get((board_by_sym.get(sym) or (None,))[0]),
        "axes_eligible": {
            "q": bool(qcm and qcm.get("pilot_eligible")),
            "v": bool(vcm and vcm.get("pilot_eligible")),
            "t": bool(tcm and tcm.get("pilot_eligible")),
        },
        "raw_financials": {
            "roe_pct_raw": f2(m.get("roe"), 2),
            "net_margin_pct_raw": f2(m.get("net_margin"), 2),
            "operating_margin_pct_raw": f2(m.get("operating_margin"), 2),
            "net_profit_ttm": np_ttm,
            "operating_profit_ttm": op_ttm,
            "ocf_ttm": ocf_ttm,
            "eps_ttm": m.get("eps_ttm"),
            "debt_ratio": f2(m.get("debt_ratio"), 4),
            "interest_coverage_raw": f2(m.get("interest_coverage"), 4),
            "cash_conversion_raw": f2(m.get("cash_conversion"), 4),
            "earnings_quality_raw": f2(m.get("earnings_quality"), 4),
            "revenue_growth_pct": f2(m.get("revenue_growth"), 2),
            "net_profit_growth_pct": f2(m.get("net_profit_growth"), 2),
            "latest_price": m.get("latest_price"),
            "shares_outstanding": m.get("shares_outstanding"),
            "market_cap": m.get("market_cap"),
            "pe_raw": f2(m.get("pe"), 4),
            "pb_raw": f2(m.get("pb"), 4),
            "ps_raw": f2(m.get("ps"), 4),
            "price_momentum_30d_pct": f2(m.get("price_momentum_30d"), 2),
            "volatility_30d": f2(m.get("volatility_30d"), 4),
            "avg_trade_value_30d_rial": m.get("avg_trade_value_30d"),
        },
        "artifact_percentiles": {
            "q": {k: f2(pct_score(qcm, k)[0], 4) for k in
                  ("roe_level", "margins", "leverage", "interest_coverage", "cash_conversion",
                   "earnings_quality", "revenue_growth")},
            "v": {k: {"score": f2(pct_score(vcm, k)[0], 4), "raw": f2(pct_score(vcm, k)[1], 4)}
                  for k in ("pe", "pb", "ps")},
            "t": {k: {"score": f2(pct_score(tcm, k)[0], 4), "raw": f2(pct_score(tcm, k)[1], 4)}
                  for k in ("momentum_6m_rel", "momentum_3m_rel", "relative_strength_6m_sector",
                            "liquidity", "low_volatility")},
        },
    }
    # میانگین پرسنتایل ارزندگی — همان خوانش موتور (میانگین سادهٔ عوامل مشاهده‌شده)
    vs = [pct_score(vcm, k)[0] for k in ("pe", "pb", "ps") if pct_score(vcm, k)[0] is not None]
    rec["artifact_percentiles"]["v"]["mean_included"] = f2(sum(vs) / len(vs), 4) if vs else None

    # ── بررسی تکراری‌بودن سود و تضاد سود/جریان نقد ─────────────────────────
    checks = {}
    if np_ttm is not None and op_ttm is not None:
        checks["net_sign"] = "مثبت" if np_ttm > 0 else ("منفی" if np_ttm < 0 else "صفر")
        checks["operating_sign"] = "مثبت" if op_ttm > 0 else ("منفی" if op_ttm < 0 else "صفر")
        if np_ttm > 0 and op_ttm <= 0:
            checks["recurrence"] = "خطر: سود خالص مثبت اما سود عملیاتی منفی — سود از اقلام غیرعملیاتی/غیرتکراری"
        elif np_ttm > 0 and op_ttm > 0 and op_ttm >= np_ttm:
            checks["recurrence"] = "هستهٔ عملیاتی سود را کامل پوشش می‌دهد (سود عملیاتی ≥ سود خالص)"
        elif np_ttm > 0 and op_ttm > 0 and op_ttm < np_ttm:
            checks["recurrence"] = "سود خالص بیش از سود عملیاتی — بخشی از سود غیرعملیاتی است؛ نیازمند بررسی"
        else:
            checks["recurrence"] = "سود خالص نامثبت — ارزندگی سودمحور ناممکن"
        checks["op_to_net"] = f2(op_ttm / np_ttm, 4) if np_ttm else None
    if np_ttm and ocf_ttm is not None:
        checks["ocf_to_net"] = f2(ocf_ttm / np_ttm, 4)
        if np_ttm > 0:
            r = ocf_ttm / np_ttm
            if r < 0.5:
                checks["cash_quality"] = "ضعیف: جریان نقد عملیاتی کمتر از نیمی از سود خالص — کیفیت سود/تبدیل نقد نامطمئن"
            elif r > 1.5:
                checks["cash_quality"] = "قوی: جریان نقد عملیاتی بیش از سود خالص"
            else:
                checks["cash_quality"] = "قابل قبول: جریان نقد عملیاتی نزدیک سود خالص"
    rec["derived_checks"] = checks

    # ── مبنای P/E و هم‌تاریخی بودن ─────────────────────────────────────────
    vp = m.get("_valuation_prov", {})
    tp = m.get("_ttm_prov", {})
    basis = {
        "pe_method": vp.get("pe_method"),
        "pb_method": vp.get("pb_method"),
        "share_source": vp.get("share_source"),
        "share_as_of_date": vp.get("share_as_of_date"),
        "share_source_collected_at": vp.get("share_source_collected_at"),
        "share_cross_check_status": vp.get("share_cross_check_status"),
        "net_profit_provenance": tp.get("net_profit_ttm"),
        "operating_cash_flow_provenance": tp.get("operating_cash_flow_ttm"),
    }
    pb_warn = pct_score(vcm, "pb")[2]
    basis["share_vs_price_same_date_proven"] = not any(
        "share_snapshot_older_than_price" in w for w in pb_warn)
    basis["share_vs_price_warning"] = next(
        (w for w in pb_warn if "share_snapshot_older_than_price" in w), None)
    rec["pe_pb_basis"] = basis

    # ── کیفیت شواهد هر عامل مهم (برچسب not_verified در صورت پارازیت) ─────────
    ev = {}
    for axis_name, cm in (("q", qcm), ("v", vcm), ("t", tcm)):
        for fid in (cm or {}).get("factors", {}):
            _, _, warns, inc = pct_score(cm, fid)
            tags = []
            if any("order3_recovered_from_raw_letter" in w for w in warns):
                tags.append("not_verified: از نامهٔ خام بازیابی‌شده (order3) — نیازمند تأیید مستقل")
            if any("negative_operating_profit" in w for w in warns):
                tags.append("negative_operating_profit")
            if any("share_snapshot_older_than_price" in w for w in warns):
                tags.append("basis_not_proven")
            if any("loss_maker" in w for w in warns):
                tags.append("loss_maker")
            if tags:
                ev[f"{axis_name}.{fid}"] = tags
    rec["evidence_quality_flags"] = ev
    rec["risk_gate_status"] = (qcm or {}).get("risk_gate", {}).get("status") or \
        (qcm or {}).get("risk_gate", {}).get("final_evaluation")
    rec["confidence_status"] = (qcm or {}).get("data_confidence", {}).get("status")

    # گروه همتا از تختهٔ زنده (اگر در ۶۲ باشد) + پشتیبانی نرمال‌سازی V
    be = (board_by_sym.get(sym) or (None, None))[1]
    if be:
        rec["peer_group"] = {
            "board_group_size": be.get("group_size"),
            "group_label": be.get("group_label"),
            "value_defensible": be.get("value_defensible"),
            "value_cheap": be.get("value_cheap"),
            "fundamental": be.get("fundamental"),
            "fundamental_label": be.get("fundamental_label"),
            "entry": be.get("entry"),
            "entry_label": be.get("entry_label"),
            "group_reason": be.get("group_reason"),
            "top_risk": be.get("top_risk"),
        }
    else:
        rec["peer_group"] = None
    ns = [pct_score(vcm, k)[1] is not None and (vcm or {}).get("factors", {}).get(k, {}).get("n_valid_sector")
          for k in ("pe", "pb", "ps")]
    rec["v_sector_support"] = {
        "pe_n_sector": (vcm or {}).get("factors", {}).get("pe", {}).get("n_valid_sector"),
        "pb_n_sector": (vcm or {}).get("factors", {}).get("pb", {}).get("n_valid_sector"),
        "ps_n_sector": (vcm or {}).get("factors", {}).get("ps", {}).get("n_valid_sector"),
    }
    rows.append(rec)

out = {
    "artifact": "economic_cases_2k9",
    "version": "2k9-economic-cases-v1",
    "snapshot_tag": TAG,
    "purpose": "پروندهٔ اقتصادی قابل بازتولید: تفکیک پرسنتایل آرتیفکت از نسبت خام، "
               "تکراری‌بودن سود، تبدیل نقد، مبنای P/E و گروه همتا",
    "sources": {
        "raw_financials": "canonical_v1_metrics.json (compute_metrics canonical pipeline)",
        "percentiles_q": "v2_q_observed_report.json (percentile_combined — فقط رتبه، بدون raw)",
        "percentiles_v": "v2_value_pilot.json (raw + percentile عوامل pe/pb/ps)",
        "percentiles_t": "v2_t_pilot.json (raw + percentile عوامل بازار)",
        "board_groups": "_board_2k8_live.json (گروه تصمیم و اندازهٔ گروه همتا)",
    },
    "metric_notes": {
        "roe_0_79_etc": "اعداد گزارش ۲-ک-۸ (roe 0.79، حاشیه 0.22، اهرم 0.28) پرسنتایل عوامل Q هستند، نه نسبت‌های مالی خام؛ "
                        "نسبت خام در raw_financials آمده است (مثلاً roe_pct_raw بوعلی).",
        "q_artifact_has_no_raw": "قرارداد آرتیفکت Q فقط percentile_combined دارد؛ raw از خط لولهٔ canonical_v1 گرفته می‌شود "
                                 "و مبنای جمعیت نرمال‌سازی هرکدام متفاوت است.",
    },
    "cases": rows,
}
p = os.path.join(OUT, f"economic_cases_2k9_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote:", p, os.path.getsize(p), "bytes")
print("cases:", len(rows))
for r in rows[:8]:
    print(r.get("symbol"), "| group:", r.get("board_group_fa"), "| roe_raw:", r.get("raw_financials", {}).get("roe_pct_raw"),
          "| pe:", r.get("raw_financials", {}).get("pe_raw"), "| vmean:", r.get("artifact_percentiles", {}).get("v", {}).get("mean_included"))
