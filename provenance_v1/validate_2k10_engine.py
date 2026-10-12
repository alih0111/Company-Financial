#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۹ / P6 — بازتولید مستقل منطق تصمیم و مقایسه با موتور Go.

این اسکریپت سیاست تصمیم v2 را (decideQ/decideV/decideT + قید کیفیت + ترتیب
blockers + switch چهارگروهی) از صفر در پایتون پیاده می‌کند و گروه محاسبه‌شدهٔ
هر ۶۲ شرکت را با گروهی که موتور Go در همان پاسخ داده مقایسه می‌کند.

ورودی‌های مستقل‌از‌تصمیم (نه چیزی که بازتولید می‌شود) از پاسخ زنده گرفته
می‌شوند: وضعیت دروازه ریسک، تأیید تازگی قیمت و مقایسه‌پذیری گروه — چون آن‌ها
محصول زیرسیستم‌های riskgate/pricecheck/discovery هستند، نه لایهٔ تصمیم.

خروجی: provenance_v1/output/engine_reproduction_2k9_<TAG>.json
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

POL = {
    "q_strong_roe": 0.65, "q_weak_roe": 0.35, "q_strong_margin": 0.50, "q_safety_min": 0.35,
    "q_weak_factor": 0.20, "q_weak_factor_n": 2, "q_cash_min": 0.40,
    "v_cheap": 0.60, "v_expensive": 0.40, "v_multiple_min": 0.50, "v_min_sector_support": 5,
    "t_momentum_ok": 0.40, "t_momentum_hostile": 0.25, "t_rs_hostile": 0.30, "t_liq_floor_rial": 10e9,
}

live = json.load(open(os.path.join(OUT, "_board_2k10_live.json"), encoding="utf-8"))
ob = live["opportunity_board"]
q = json.load(open(os.path.join(ART, "v2_q_observed_report.json"), encoding="utf-8"))["companies"]
v = json.load(open(os.path.join(ART, "v2_value_pilot.json"), encoding="utf-8"))["v_observed_report"]["companies"]
t = json.load(open(os.path.join(ART, "v2_t_pilot.json"), encoding="utf-8"))["t_observed_report"]["companies"]
balanced = {r["company_id"]: r for r in live["modes"]["balanced"]["rows"]}

GROUPS = ["attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient"]
engine_group = {}
for g in GROUPS:
    for e in ob[g]:
        engine_group[e["company_id"]] = g


def factors(cm):
    out = {}
    for fid, f in (cm or {}).get("factors", {}).items():
        out[fid] = {
            "score": f.get("score"), "raw": f.get("raw_value"),
            "nsector": f.get("n_valid_sector"), "warnings": f.get("warnings") or [],
        }
    return out


def has_warn(st, prefix):
    return st is not None and any(w.startswith(prefix) for w in st["warnings"])


def decide_q(qcm):
    f = factors(qcm)
    roe, mar = f.get("roe_level", {}), f.get("margins", {})
    lev, ic = f.get("leverage", {}), f.get("interest_coverage", {})
    for fid in ("cash_conversion", "earnings_quality", "interest_coverage", "leverage",
                "margins", "revenue_growth", "roe_level"):
        if has_warn(f.get(fid), "negative_operating_profit"):
            return "weak", True
    weak_n = sum(1 for st in (roe, mar, lev, ic) if st.get("score") is not None and st["score"] < POL["q_weak_factor"])
    if weak_n >= POL["q_weak_factor_n"]:
        return "weak", False
    if roe.get("score") is not None and roe["score"] < POL["q_weak_roe"]:
        return "weak", False
    if roe.get("score") is None and mar.get("score") is not None and mar["score"] < POL["q_weak_roe"]:
        return "weak", False
    if roe.get("score") is None and mar.get("score") is None:
        return "insufficient", False
    strong = (roe.get("score") is not None and roe["score"] >= POL["q_strong_roe"] and
              mar.get("score") is not None and mar["score"] >= POL["q_strong_margin"])
    safety = ((lev.get("score") is not None and lev["score"] >= POL["q_safety_min"]) or
              (ic.get("score") is not None and ic["score"] >= POL["q_safety_min"]))
    return ("strong" if (strong and safety) else "acceptable"), False


def decide_v(vcm, comparable):
    f = factors(vcm)
    pe, pb, ps = f.get("pe", {}), f.get("pb", {}), f.get("ps", {})
    scores = [st["score"] for st in (pe, pb, ps) if st.get("score") is not None]
    if not scores:
        return None, False, False, "شواهد ناکافی"
    mean = sum(scores) / len(scores)
    cheap = mean >= POL["v_cheap"]
    label = "ارزان نسبی" if cheap else ("گران نسبی" if mean < POL["v_expensive"] else "میانه")

    def support_ok(st):
        ns = st.get("nsector")
        return POL["v_min_sector_support"] <= 0 or ns is None or ns >= POL["v_min_sector_support"]

    pe_strong = pe.get("score") is not None and pe["score"] >= POL["v_multiple_min"]
    pb_strong = pb.get("score") is not None and pb["score"] >= POL["v_multiple_min"]
    support = (pe_strong and support_ok(pe)) or (pb_strong and support_ok(pb))
    defensible = cheap and comparable and not has_warn(pe, "loss_maker") and support
    return mean, cheap, defensible, label


def decide_t(tcm):
    f = factors(tcm)
    m6, rs, liq = f.get("momentum_6m_rel", {}), f.get("relative_strength_6m_sector", {}), f.get("liquidity", {})
    if m6.get("raw") is None or m6.get("score") is None:
        return "insufficient"
    if liq.get("raw") is None:
        return "insufficient"
    if liq["raw"] < POL["t_liq_floor_rial"]:
        return "insufficient"
    if m6["score"] >= POL["t_momentum_ok"]:
        return "ok"
    if m6["score"] < POL["t_momentum_hostile"] and rs.get("score") is not None and rs["score"] < POL["t_rs_hostile"]:
        return "hostile"
    return "neutral"


def axis_missing(entry):
    for ax, key in (("Q", "q"), ("V", "v"), ("T", "t")):
        if entry[key]["status"] == "missing":
            return ax
    return ""


def reproduce(cid):
    qcm, vcm, tcm = q.get(cid), v.get(cid), t.get(cid)
    entry = next(e for g in GROUPS for e in ob[g] if e["company_id"] == cid)
    row = balanced.get(cid, {})
    comparable = row.get("comparability") == "comparable" and row.get("group_valid") is True
    fresh = "تأیید شد" in (entry.get("freshness_label") or "")
    risk = entry.get("risk_gate_status")
    fund, neg_op = decide_q(qcm)
    mean, cheap, defensible, vlabel = decide_v(vcm, comparable)
    entry_v = decide_t(tcm)
    fq = factors(qcm)
    cc = fq.get("cash_conversion", {}).get("score")
    cash_weak = cc is not None and cc < POL["q_cash_min"]
    conditional = cash_weak or neg_op
    missing = axis_missing(entry)

    if risk == "blocked":
        return "blocked_or_insufficient", "risk_gate_blocked"
    if missing:
        return "blocked_or_insufficient", "missing_scores"
    if fund in ("weak", "insufficient"):
        return ("apparent_value_risk", "apparent_value_weak_fundamentals") if cheap else \
               ("blocked_or_insufficient", "weak_no_case")
    if not comparable:
        return "fundamentals_waiting", "small_group"
    if not fresh:
        return "fundamentals_waiting", "price_freshness_unverified"
    if not defensible:
        return "fundamentals_waiting", "decision_value_not_defensible"
    if entry_v != "ok":
        return "fundamentals_waiting", "decision_entry_not_ok"
    if conditional:
        return "fundamentals_waiting", "conditional_quality_caveat"
    return "attractive_candidates", "ok"


rows = []
mismatch = []
code_counts = {}


def all_counts():
    res = {g: 0 for g in GROUPS}
    codes = {}
    for cid in engine_group:
        g, code = reproduce(cid)
        res[g] += 1
        codes[code] = codes.get(code, 0) + 1
    return res, codes


for cid in engine_group:
    g, code = reproduce(cid)
    code_counts[code] = code_counts.get(code, 0) + 1
    rows.append({"company_id": cid, "symbol": next(e["symbol"] for e in ob[engine_group[cid]] if e["company_id"] == cid),
                 "engine_group": engine_group[cid], "reproduced_group": g, "code": code,
                 "match": g == engine_group[cid]})
    if g != engine_group[cid]:
        mismatch.append(rows[-1])

# ── تحلیل حساسیت — هیچ آستانه‌ای برای ساختن/حذف نامزد تنظیم نشده؛ فقط اثر ──
def sens(**over):
    base = dict(POL)
    base.update(over)
    saved = dict(POL)
    POL.clear(); POL.update(base)
    res, codes = all_counts()
    POL.clear(); POL.update(saved)
    return {"counts": res, "codes": codes}

sensitivity = {
    "v_cheap": {str(t): sens(v_cheap=t) for t in (0.55, 0.60, 0.65)},
    "q_cash_min": {str(t): sens(q_cash_min=t) for t in (0.30, 0.40, 0.50)},
    "v_min_sector_support": {str(t): sens(v_min_sector_support=t) for t in (2, 5)},
}

out = {
    "artifact": "engine_reproduction_2k10",
    "version": "2k10-reproduction-v1",
    "snapshot_tag": TAG,
    "policy_version": ob["decision_policy"]["version"],
    "rules_version": ob["rules"]["version"],
    "n_companies": len(rows),
    "n_match": sum(1 for r in rows if r["match"]),
    "n_mismatch": len(mismatch),
    "mismatches": mismatch,
    "reproduced_code_counts": code_counts,
    # قرارداد صریح گام ۲-ک-۱۰: گروه‌ها زیر counts.groups؛ صفت‌ها جدا.
    "engine_counts": ob["counts"]["groups"],
    "engine_attributes": ob["counts"]["attributes"],
    "contract_groups_reconcile": ob["counts"]["groups"]["reconciles"],
    "contract_groups_sum": (ob["counts"]["groups"]["attractive_candidates"] + ob["counts"]["groups"]["fundamentals_waiting"]
                            + ob["counts"]["groups"]["apparent_value_risk"] + ob["counts"]["groups"]["blocked_or_insufficient"]),
    "reproduced_counts": {g: sum(1 for r in rows if r["reproduced_group"] == g) for g in GROUPS},
    "consistency_ok": len(mismatch) == 0,
    "sensitivity": sensitivity,
    "rows": rows,
}
p = os.path.join(OUT, f"engine_reproduction_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote:", p)
print("match:", out["n_match"], "/", out["n_companies"], "| mismatches:", out["n_mismatch"])
print("engine counts:", out["engine_counts"])
print("repro  counts:", out["reproduced_counts"])
print("codes:", code_counts)
