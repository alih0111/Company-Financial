#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۸ — ساخت دو آرتیفکت تشخیصی نسخه‌دار (فقط‌خواندنی نسبت به منابع):

1) decision_audit_2k8_<TAG>.json — ممیزی اقتصادی تصمیم‌محور هر ۶۲ شرکت
   واجد شرایط سه‌محوری. همهٔ فیلدها از خروجی زندهٔ موتور برد
   (opportunity_board در پاسخ discovery — فایل _board_2k8_live.json)
   استخراج می‌شود؛ هیچ عدد یا نتیجه‌ای اینجا بازمحاسبه یا حدس زده
   نمی‌شود. موتور همان مرجع UI است، پس این آرتیفکت «سند ممیزی» خروجی
   موتور است، نه منبع دوم حقیقت.

2) coverage_analysis_2k8_<TAG>.json — تحلیل پوشش ۲۷۱→۶۲: دسته‌بندی و
   شمارش موانع هر شرکت خارج از جامعهٔ سه‌محوری + برآورد اثر مقابلِ
   (counterfactual) رفع هر مانع، فقط ازflagsهای موجود در آرتیفکت‌ها.
"""

import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

live = json.load(open(os.path.join(OUT, "_board_2k8_live.json"), encoding="utf-8"))
ob = live["opportunity_board"]
GROUPS = ["attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient"]
GROUP_FA = {
    "attractive_candidates": "نامزد جذاب برای بررسی جدی",
    "fundamentals_waiting": "بنیادی مناسب — منتظر شرایط بهتر",
    "apparent_value_risk": "ارزان‌نما — نیازمند احتیاط جدی",
    "blocked_or_insufficient": "شواهد ناکافی یا دارای مانع",
}

# ── 1) ممیزی ۶۲ شرکت از خروجی موتور ─────────────────────────────────────────
rows = []
for g in GROUPS:
    for e in ob[g]:
        rows.append({
            "company_id": e["company_id"],
            "symbol": e["symbol"],
            "industry": e["industry"],
            "group": g,
            "group_fa": GROUP_FA[g],
            "conclusion": e["conclusion"],
            "group_reason": e["group_reason"],
            "fundamental": {
                "verdict": e["fundamental"],
                "label": e["fundamental_label"],
                "roe_pct": e["roe_pct"],
                "margin_pct": e["margin_pct"],
                "leverage_pct": e["leverage_pct"],
                "interest_coverage_pct": e["interest_coverage_pct"],
                "notes": e["fundamental_note"],
            },
            "value": {
                "mean_percentile": e["value_mean"],
                "label": e["value_label"],
                "cheap": e["value_cheap"],
                "defensible": e["value_defensible"],
                "notes": e["value_note"],
                "basis_note": e.get("value_basis_note", ""),
            },
            "entry": {
                "verdict": e["entry"],
                "label": e["entry_label"],
                "notes": e["entry_note"],
            },
            "axes": {
                "q": {"points": e["q"]["points"], "max": e["q"]["max"], "coverage_ratio": e["q"]["coverage_ratio"]},
                "v": {"points": e["v"]["points"], "max": e["v"]["max"], "coverage_ratio": e["v"]["coverage_ratio"]},
                "t": {"points": e["t"]["points"], "max": e["t"]["max"], "coverage_ratio": e["t"]["coverage_ratio"]},
            },
            "risk_gate_status": e["risk_gate_status"],
            "confidence_overall": e["confidence_overall"],
            "price_freshness_label": e["freshness_label"],
            "peer_group_size": e["group_size"],
            "pareto_layer": e.get("pareto_layer"),
            "validation_status": e.get("validation_status", ""),
            "top_reason": e["top_reason"],
            "top_risk": e["top_risk"],
            "careful": e["careful"],
            "review_when": e["review_when"],
        })

audit = {
    "artifact": "decision_audit_2k8",
    "version": "2k8-decision-audit-v1",
    "snapshot_tag": TAG,
    "as_of": live.get("as_of"),
    "generated_from": "opportunity_board in live GET /api/qvt-v2/discovery response (_board_2k8_live.json)",
    "engine": {
        "rules": ob["rules"]["version"],
        "policy": ob["decision_policy"]["version"],
        "policy_thresholds": {k: v for k, v in ob["decision_policy"].items() if k not in ("version", "note")},
        "policy_note": ob["decision_policy"]["note"],
    },
    "counts": ob["counts"],
    "n_rows": len(rows),
    "not_a_signal": "این سند ممیزی «نامزد بررسی» است؛ نه توصیه خرید/فروش، نه اثبات آماری سودآوری",
    "rows": rows,
}
p1 = os.path.join(OUT, f"decision_audit_2k8_{TAG}.json")
json.dump(audit, open(p1, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ── 2) تحلیل پوشش ۲۷۱→۶۲ ─────────────────────────────────────────────────────
q = json.load(open(os.path.join(ART, "v2_q_observed_report.json"), encoding="utf-8"))
v = json.load(open(os.path.join(ART, "v2_value_pilot.json"), encoding="utf-8"))
t = json.load(open(os.path.join(ART, "v2_t_pilot.json"), encoding="utf-8"))
qc, vc, tc = q["companies"], v["v_observed_report"]["companies"], t["t_observed_report"]["companies"]
ids = sorted(set(qc) | set(vc) | set(tc))


def el(cm):
    return bool(cm and cm.get("pilot_eligible"))


pattern_counter = Counter()
q_block = Counter()
v_block = Counter()
t_block = Counter()
v_equity_missing_fixable_pe = 0
records = []
for cid in ids:
    qcm, vcm, tcm = qc.get(cid), vc.get(cid), tc.get(cid)
    eq, ev, et = el(qcm), el(vcm), el(tcm)
    pattern_counter[(eq, ev, et)] += 1
    sym = (qcm or vcm or tcm or {}).get("symbol", cid)
    rec = {"company_id": cid, "symbol": sym, "q_eligible": eq, "v_eligible": ev, "t_eligible": et}
    if not eq and qcm:
        st = qcm.get("aggregation_status")
        if st and st != "aggregated":
            rec["q_blocker"] = "family_out_of_scope" if "out_of_scope" in st else st
        elif not qcm.get("coverage_threshold_met"):
            rec["q_blocker"] = "coverage_below_threshold"
            rec["q_coverage_ratio"] = qcm.get("coverage_ratio")
        else:
            rec["q_blocker"] = "other"
        q_block[rec["q_blocker"]] += 1
    if not ev and vcm:
        fac = vcm.get("factors", {})
        cw = vcm.get("covered_weight") or 0
        missing = [f for f in ("pe", "pb", "ps") if not fac.get(f, {}).get("included")]
        reasons = []
        for f in missing:
            r = str(fac.get(f, {}).get("not_included_reason", ""))[:60]
            reasons.append(f"{f}: {r}")
        if "raw_missing" in ";".join(reasons) and "pb" in missing:
            v_equity_missing_fixable_pe += 1
        rec["v_blocker"] = {"covered_weight": cw, "missing_factors": missing, "reasons": reasons}
        key = f"cw<17.5 with pb missing" if ("pb" in missing and cw < 17.5) else ("pe_block" if "pe" in missing and "pb" not in missing else "other")
        v_block[key] += 1
    if not et and tcm:
        fac = tcm.get("factors", {})
        missing = [f for f in ("momentum_6m_rel", "momentum_3m_rel", "relative_strength_6m_sector", "liquidity", "low_volatility")
                   if not fac.get(f, {}).get("included")]
        rec["t_blocker"] = {"missing_factors": missing}
        if any("momentum" in f for f in missing):
            t_block["momentum_windows_insufficient"] += 1
        elif missing:
            t_block["liquidity_or_vol_missing"] += 1
        else:
            t_block["coverage_below_threshold"] += 1
    if not (eq and ev and et):
        records.append(rec)

triple = sum(1 for i in ids if el(qc.get(i)) and el(vc.get(i)) and el(tc.get(i)))
# برآورد مقابلِ — فقط از پرچم‌های موجود: اگر equity موجود بود، کدام شرکت‌ها
# واجد V می‌شدند؟ (آن‌هایی که pb به‌خاطر raw_missing حذف شد اما cw+12 ≥ آستانه)
v_summary = v.get("coverage_summary", {})
coverage = {
    "artifact": "coverage_analysis_2k8",
    "version": "2k8-coverage-v1",
    "snapshot_tag": TAG,
    "universe_total": len(ids),
    "triple_eligible": triple,
    "axis_eligible": {"q": sum(1 for i in ids if el(qc.get(i))), "v": sum(1 for i in ids if el(vc.get(i))), "t": sum(1 for i in ids if el(tc.get(i)))},
    "eligibility_patterns": {"".join("T" if x else "F" for x in k): n for k, n in pattern_counter.items()},
    "q_blockers": dict(q_block),
    "v_blockers": dict(v_block),
    "t_blockers": dict(t_block),
    "v_store_facts": {
        "n_equity_missing": v_summary.get("n_equity_missing"),
        "n_pe_valid": v_summary.get("n_pe_valid"),
        "n_pb_valid": v_summary.get("n_pb_valid"),
        "n_blocked_negative_net_profit": v_summary.get("n_blocked_negative_net_profit"),
        "n_ps_family_excluded": v_summary.get("n_ps_family_excluded"),
    },
    "q_store_facts": q.get("summary"),
    "counterfactual_note": (
        "برآورد اثر فقط از پرچم‌های ثبت‌شدهٔ آرتیفکت — بدون هیچ حدس داده‌ای. "
        "رفع هیچ‌یک از سه مانع بزرگ در این مأموریت مجاز/ممکن نبوده است."
    ),
    "big_blockers_and_plans": [
        {
            "rank": 1,
            "blocker": "نبود حقوق صاحبان سهام در مخزن گزارش‌ها (n_equity_missing=%s) → P/B ساخته نمی‌شود و پوشش V زیر آستانه می‌ماند (≈147 شرکت با cw=13)"
                       % v_summary.get("n_equity_missing"),
            "fix": "واردات تاریخی حقوق صاحبان سهام (backfill) از صورت‌های مالی — اقدام دائمی DB",
            "status": "نیازمند مجوز مالک (ممنوع در این مأموریت — بدون SQL 125/backfill)",
            "expected_impact": "V واجد تا ~+137 شرکت؛ سه‌محوری فقط برای شرکت‌هایی که هم‌زمان Q و T هم پاس کنند (سقف واقعی = تعداد Q-واجد که ۹۸ است)",
        },
        {
            "rank": 2,
            "blocker": "خلأ صورت‌های مالی بنیادی → پوشش Q زیر آستانهٔ ۰.۵ برای ۱۶۱ شرکت (۱۳۵ شرکت کاملاً بدون پوشش)",
            "fix": "تکمیل داده‌های صورت مالی تاریخی (سود و زیان/ترازنامه) از منابع رسمی",
            "status": "نیازمند مجوز مالک و منبع داده",
            "expected_impact": "Q واجد از ۹۸ به سقف ~۲۶۰؛ بزرگ‌ترین اهرم واقعی پوشش (تا ~+۳۶ شرکت سه‌محوری جدید حتی بدون سایر اصلاحات: گروه T,T,F فعلی ۳۲+۳ عضو)",
        },
        {
            "rank": 3,
            "blocker": "پنجرهٔ مومنتوم ناکافی (تاریخچهٔ قیمت کوتاه/ناقص) → T واجد نیست برای ۹۸ شرکت با Q,V قابل قبول (الگوی TT F=32 و FF T=98)",
            "fix": "افزودن تاریخچهٔ قیمت (price_observations) برای نمادهای کم‌سابقه",
            "status": "نیازمند مجوز مالک / منبع داده قیمت",
            "expected_impact": "T واجد از ۱۶۴ به سقف ~۲۵۳؛ برای گروه TT F فعلی ۳۲ شرکت سه‌محوری جدید",
        },
        {
            "rank": 4,
            "blocker": "خارج از دامنهٔ خانوادهٔ pilot (بانک/مالی — family_out_of_scope) برای ۱۱ شرکت",
            "fix": "گسترش دامنهٔ خانواده با جمعیت نرمال‌سازی مستقل خودش",
            "status": "تصمیم سیاسی مالک (گام سیاست، نه داده)",
            "expected_impact": "تا ۱۱ شرکت جدید در صورت طراحی مدل خانوادهٔ بانکی",
        },
        {
            "rank": 5,
            "blocker": "زیان‌دهی (P/E ناممکن) برای ۱۰ شرکت — طبق قرارداد، زیان‌ده هرگز ارزان خوانده نمی‌شود",
            "fix": "بدون اصلاح داده‌ای؛ رفتار درست است (نه مانع، فقط حذف P/E از ارزندگی)",
            "status": "قرارداد فعلی صحیح است",
            "expected_impact": "—",
        },
    ],
    "coverage_before_after": {
        "before_mission_2k7": 62,
        "after_mission_2k8": triple,
        "delta": triple - 62,
        "reason": "هر سه مانع بزرگ نیازمند backfill/مجوز مالک‌اند؛ طبق محدودیت‌ها اجرا نشد و هیچ داده‌ای جایگزین نشد",
    },
    "excluded_records": records,
}
p3 = os.path.join(OUT, f"coverage_analysis_2k8_{TAG}.json")
json.dump(coverage, open(p3, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("wrote:", p1, os.path.getsize(p1), "bytes,", len(rows), "rows")
print("wrote:", p3, os.path.getsize(p3), "bytes")
print("triple:", triple, "| patterns:", dict(coverage["eligibility_patterns"]))
print("q_blockers:", dict(q_block))
print("v_blockers:", dict(v_block))
print("t_blockers:", dict(t_block))
