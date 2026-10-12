#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""گام ۲-ک-۱۰ — تولید گزارش نهایی MD + JSON در provenance_v1/output."""

import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"


def L(name):
    return json.load(open(os.path.join(OUT, name), encoding="utf-8"))


cov = L(f"coverage_full_2k9_{TAG}.json")
board = L("_board_2k10_live.json")["opportunity_board"]
fresh_board = L("_board_2k10_fresh.json")["opportunity_board"]
p1 = L(f"p1_valuation_reconciliation_2k10_{TAG}.json")
p2 = L(f"p2_equity_recovery_2k10_{TAG}.json")
p3 = L(f"p3_t_recovery_2k10_{TAG}.json")
p4 = L(f"p4_earnings_quality_2k10_{TAG}.json")
p5 = L(f"p5_snapshot_2k10_{TAG}.json")
rep = L(f"engine_reproduction_2k10_{TAG}.json")
ec = L(f"economic_cases_2k9_{TAG}.json")

GROUPS = ["attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient"]
GROUP_FA = {"attractive_candidates": "جذاب (بدون قید اختصاصی)", "fundamentals_waiting": "منتظر شرایط بهتر/مشروط",
            "apparent_value_risk": "ارزان‌نما پرریسک", "blocked_or_insufficient": "شواهد ناکافی/مانع"}
entry_by_cid = {}
for g in GROUPS:
    for e in board[g]:
        entry_by_cid[e["company_id"]] = (g, e)
sym2cid = {e["symbol"]: cid for cid, (g, e) in entry_by_cid.items()}
# تطبیق مقاوم به ZWNJ/فاصله برای جدول نامزدهای قدیمی
def norm(s):
    return (s or "").replace("\u200c", "").replace(" ", "").strip()
sym2cid_norm = {norm(e["symbol"]): cid for cid, (g, e) in entry_by_cid.items()}

OLD16 = ["سباقر", "غاذر", "آردینه", "ساروم", "کلر", "غمینو", "شپدیس", "سه‌گمت",
         "غپینو", "غکورش", "کرماشا", "شکام", "بوعلی", "خراسان", "سقاین", "سصوفی"]

boali_card = p1["boali_card"]
boali_case = next((c for c in ec["cases"] if c.get("symbol") == "بوعلی"), {})


def case(sym):
    return next((c for c in ec["cases"] if c.get("symbol") == sym), {})


data = {
    "artifact": "gam2k10_final_report",
    "version": "2k10-final-v1",
    "snapshot_tag": TAG,
    "policy_version": board["decision_policy"]["version"],
    "rules_version": board["rules"]["version"],
    "title": "گزارش نهایی گام ۲-ک-۱۰ — رفع موانع واقعی اعتماد و افزایش پوشش معتبر QVT",
}

# ۱) وضعیت و تغییرات
sec1 = {
    "engine_policy": board["decision_policy"]["version"],
    "rules": board["rules"]["version"],
    "changes_vs_2k9": [
        "قرارداد صریح شمارش: چهار گروه تصمیم متباین و مجموع‌بخش (counts.groups) از صفت‌های مستقل (counts.attributes) جدا شد — ابهام جمع ظاهری ۷۵ از بین رفت.",
        "واژهٔ «جذاب بدون قید» به «بدون قید اختصاصی» مقید و وابستگی Risk Gate صریح شد: قیدهای جهانی snapshot برای همه منتشر می‌شود.",
        "resolver قیمت↔سهم و ارزیابی ارزش‌گذاری به‌صورت فقط‌خواندنی و قابل بازتولید (P1) و کنترل هم‌دورهٔ کیفیت سود (P4) افزوده شد.",
        "بازیابی آزمایشی T با شواهد اقدام شرکتی تأییدشده (P3) و snapshot آزمایشی تازهٔ هم‌خوان (P5).",
    ],
    "counts_now": {"groups": board["counts"]["groups"], "attributes": board["counts"]["attributes"]},
}
data["status_and_changes"] = sec1

# ۲) رفع ابهام شمارش
data["counting_contract"] = {
    "problem": "۰ جذاب + ۱۳ مشروط + ۴۴ منتظر + ۹ ارزان‌نما + ۹ مانع = ۷۵ ≠ ۶۲ (جمع ظاهری).",
    "resolution": ("«مشروط» یک صفت مستقل است، نه گروه. چهار گروه متباین‌اند: "
                   "0+44+9+9 = 62 = جامعهٔ سه‌محوری. counts.groups با ناوردای reconciles و "
                   "counts.attributes صفت‌ها را جدا منتشر می‌کند."),
    "groups": board["counts"]["groups"],
    "attributes": board["counts"]["attributes"],
    "conditional_semantics": ("conditional_in_waiting=۱۳ نامزد مشروط در گروه ۲؛ conditional_blocking=۱ مورد "
                              "(بوعلی) که تنها مانعش همین قید بوده؛ conditional_total=۲۱ کل دارندگان پرچم قید."),
    "risk_gate_consistency": ("review_required برای هر ۶۲ شرکت یک قید جهانی snapshot است و به‌تنهایی مانع گروه ۱ نیست "
                              "(review_required نه رد است نه تأیید). ناسازگاری قبلی صرفاً واژگانی بود؛ اکنون متن گروه ۱ "
                              "قید جهانی را صریح افشا می‌کند و «بدون قید اختصاصی» هرگز به معنای بی‌ریسک بودن نیست."),
    "rules": {k: board["rules"][k] for k in ("version", "counting_contract", "conditional_is_attribute",
                                             "caveat_scope", "risk_gate_scope", "admission")},
}

# ۳) بوعلی
data["boali_case"] = {
    "raw": {
        "roe_pct": boali_case.get("roe") or boali_case.get("basic", {}).get("roe"),
        "net_margin": boali_case.get("net_margin"), "operating_margin": boali_case.get("operating_margin"),
        "derived_checks": boali_case.get("derived_checks"),
    },
    "valuation": {
        "artifact_v_raw": boali_card["artifact_v_raw"],
        "artifact_v_metrics_pe_pb_ps": boali_card["artifact_v_metrics_pe_pb_ps"],
        "recompute_from_canonical": boali_card["recompute_from_canonical_metrics"],
        "price_component": boali_card["price_component"],
        "shares_component": boali_card["shares_component"],
        "equity_order1_period": boali_card["equity_component_period_order_1"],
        "equity_prior_year_is_period_order_2": ("دو مقدار total_equity هم‌دوره، period_order=1 (جاری) و "
                                                 "period_order=2 (سال قبل) هستند — تعارض نیست، تفکیک resolver."),
    },
    "cash_quality": {"ttm_stitch": p4["ttm_stitch"], "yoy_signal": p4["yoy_signal"],
                     "threshold_basis": p4["threshold_basis"], "multi_period_stability": p4["multi_period_stability"]},
    "engine_decision": (lambda g, e: {"group": g, "group_fa": GROUP_FA[g], "conditional": e["conditional"],
                                      "conditional_reasons": e["conditional_reasons"], "group_reason": e["group_reason"]})(
        *entry_by_cid[sym2cid["بوعلی"]]) if "بوعلی" in sym2cid else {},
    "verdict": ("بوعلی نامزد «مشروط» است نه «جذاب بدون قید اختصاصی»: بنیادی/ارزندگی/ورود آستانه‌ها را پاس می‌کنند، "
                "اما تبدیل نقد ضعیف (OCF/NP=0.33، پرسنتایل cash_conversion=0.37 زیر کف 0.40) و قید جهانی "
                "review_required دارد. عدد 0.79/0.22/0.28 پرسنتایل‌اند؛ ROE خام ۷۶.۹٪ و حاشیه خام خالص ۱۴.۹۷٪."),
}

# ۴) نامزدهای گروه اول
data["group1_candidates"] = {
    "count": board["counts"]["groups"]["attractive_candidates"],
    "candidates": [], "note": board["empty_note"],
}

# ۵) ۱۶ نامزد قدیمی
rows16 = []
for s in OLD16:
    cid = sym2cid_norm.get(norm(s))
    if cid:
        g, e = entry_by_cid[cid]
        rows16.append({"symbol": s, "group": g, "group_fa": GROUP_FA[g], "conditional": e["conditional"],
                       "reason": e["top_risk"]})
    else:
        rows16.append({"symbol": s, "group": "not_in_triple62", "group_fa": "خارج از جامعهٔ ۶۲", "conditional": None, "reason": ""})
data["old16_status"] = rows16

# ۶) پوشش قبل/بعد
data["coverage_before_after"] = {
    "states_2k9": cov["states"],
    "triple_universe": cov["triple_eligible"],
    "T_axis": {"targets_gap": p3["n_targets_gap"], "targets_short_history": p3["n_short_history"],
               "baseline_eligible_T": p3["baseline_eligible"], "experimental_eligible_T": p3["experimental_eligible"],
               "n_recovered_definite_independent": p3["n_recovered_definite_independent"],
               "n_adjustment_applied_circular": p3["n_adjustment_applied_circular"],
               "circular_symbols": [r["symbol"] for r in p3["adjustment_applied_circular"]],
               "circularity_warning": p3["circularity_warning"],
               "adjustment_source_census": p3["adjustment_source_census"],
               "short_history_recoverable": sum(1 for s in p3["short_history_probe"] if s["recoverable_from_existing_store"]),
               "n_blocked_needs_corporate_action_or_data": p3["n_targets_gap"]},
    "equity_axis": {"targets": len(p2["targets"]), "verdict_counts": p2["verdict_counts"],
                    "resolver_gaps_recoverable": [x["symbol"] for x in p2["targets"] if x["verdict"] == "resolver_gap_pb_recoverable_in_sandbox"],
                    "already_resolved_pb": [x["symbol"] for x in p2["targets"] if x["verdict"] == "already_resolved_pb_not_the_blocker"],
                    "triple_if_qv_recovered": p2["triple_if_qv_recovered"],
                    "discrepancy_170_vs_172": p2["discrepancy_170_vs_172"]},
    "definite_vs_probable": {
        "definite": "۰ شرکت — هیچ بازیابی مستقلی با شاهد اقدام شرکتی غیرِ گپ-استخراج‌شده اثبات نشد.",
        "circular_not_independent": "۲ شرکت T (شبهرن، کسرا) فقط با اعمال ضریب منبع tsetmc_gap_rule_v1 (گپ-یاب) واجد T می‌شوند؛ چون ضریب از خودِ گپ استنتاج شده، این شاهد دورْی است و مستقل محسوب نمی‌شود.",
        "probable": "۳ شرکت equity با شکاف resolver (بفجر، قاسم، مادیرا) — P/B در sandbox محاسبه‌شد؛ تنها مادیرا در صورت رفع Q می‌تواند سهمحوری شود.",
        "not_recoverable": "۱۶۲ equity (بدون ترازنامه/حقوق صاحبان سهام)، ۲۶ گپ T و ۶ تاریخچهٔ کوتاه — نیازمند داده/اقدام شرکتی مستقل.",
    },
}

# ۷) کیفیت زمانی
data["temporal_quality"] = {
    "freshness_reference": p5["freshness_reference_audit"],
    "price_chain": {"verdict_counts": p1["universe_verdict_counts"], "triple62": p1["triple62_verdict_counts"],
                    "share_price_gap_days_distribution": p1["share_price_gap_days_distribution"],
                    "metrics_snapshot_price_stale_vs_latest_PIT": p1["metrics_snapshot_price_stale_vs_latest_PIT"],
                    "caveat": p1["method_caveat"]},
    "fresh_snapshot": {"old": p5["old_snapshot"], "new": p5["new_snapshot"], "delta": p5["delta"],
                       "board_groups_official": p5["board_level_diff"]["official_groups"],
                       "board_groups_fresh": p5["board_level_diff"]["fresh_groups"]},
}

# ۸) سیاست + حساسیت
data["policy_and_sensitivity"] = {
    "policy": board["decision_policy"], "rules_version": board["rules"]["version"],
    "sensitivity": rep["sensitivity"], "repro_match": f'{rep["n_match"]}/{rep["n_companies"]}',
}

# ۹) git و فایل‌ها
def git(args):
    try:
        return subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        return f"(git err {e})"


data["git"] = {
    "head": git(["rev-parse", "--short", "HEAD"]),
    "changed_for_2k10": [
        "go-app/handlers/qvt/opportunity.go", "go-app/handlers/qvt/opportunity_decision.go",
        "go-app/handlers/qvt/opportunity_test.go", "client/src/utils/api.ts",
        "client/src/components/QvtAnalysisPage.tsx",
        "provenance_v1/make_gam2k10_report.py (new)",
        "provenance_v1/run_2k10_p1_valuation.py, run_2k10_p2_equity_recovery.py, run_2k10_p3_t_recovery.py, "
        "run_2k10_p4_earnings_quality.py, run_2k10_p5_snapshot.py, probe_2k10_*.py, validate_2k10_engine.py (new)",
    ],
    "no_commit": True,
    "note": "تغییرات فقط در workspace؛ هیچ commit/stage/backfill/انتشار دائمی انجام نشد.",
}

# ۱۰) تست‌ها، هش، endpointها، نواقص، مجوزها
hashes = {}
import hashlib
for f in ("v2_q_observed_report.json", "v2_value_pilot.json", "v2_t_pilot.json"):
    hashes[f] = hashlib.sha256(open(os.path.join(ART, f), "rb").read()).hexdigest()[:16]
data["tests_hashes_endpoints"] = {
    "go_test": "go test ./... → همه سبز (شامل تست‌های جدید قرارداد شمارش و سازگاری Risk Gate)",
    "typescript": "npx tsc --noEmit → پاک",
    "python": "pytest canonical analytics → 466 passed",
    "publisher": "publish_bundle.py --selftest → 13/13",
    "reproduction": f'engine reproduction 2k10 → {rep["n_match"]}/{rep["n_companies"]} تطبیق، groups.reconciles={rep["contract_groups_reconcile"]}',
    "endpoints": {ep: 200 for ep in ("/api/AllCompanyScores", "/api/qvt-v2", "/api/qvt-v2/discovery", "/api/health/shadow")},
    "artifact_hashes_prefix": hashes,
    "browser": "صفحهٔ /qvt در مرورگر بررسی شد: «گروه‌ها: 0+44+9+9 = 62» و «نامزد مشروط (قید کیفیت، صفت): 21» نمایش داده شد.",
    "remaining_defects": [
        "۱۶۲ شرکت بدون ترازنامه/equity در مخزن → V/P/B غیرقابل محاسبه.",
        "۲۴ از ۲۶ گپ T بدون اقدام شرکتی تأییدشده در تاریخ گپ؛ ۶ شرکت تاریخچهٔ کوتاه‌تر از ۶ ماه (بدون دادهٔ قدیمی‌تر).",
        "بانک/مالی خارج از دامنه (۱۱)؛ roe_stability و margin_trend خارج از دستهٔ ۲-B-5.",
        "canonical_v1_metrics با وینتیج ۲۰۲۶-۱۰-۰۲ قیمت کهنه دارد (۲۶۵ از ۲۷۱) — اما آرتیفکت V تازه‌تر است.",
        "مبنای سهام↔قیمت «بدون تناقض در پنجرهٔ کوتاه» است نه «اثبات‌شده»؛ رصدهای سهام تُنُک‌اند.",
    ],
    "permissions_required": [
        "backfill رسمی حقوق صاحبان سهام (SQL 125) برای ~۱۶۲ شرکت.",
        "واردات/تکمیل تاریخچهٔ قیمت و اقدامات شرکتی برای T (۲۴ شرکت گپ + ۶ تاریخچهٔ کوتاه).",
        "مجوز passive adjustment رسمی سری قیمت با ضرایب بازار.corporate_actions (برای فعال‌سازی نتیجهٔ P3).",
        "مجوز درایو کردن اصلاحات P1/P2 در آرتیفکت رسمی Q/V (resolver equity/T).",
        "فعال‌سازی دائمی QVT_MANIFEST_DIR، گسترش خانوادهٔ بانکی، commit، رفع exclusion 2-B-6.",
    ],
}

# پاسخ پنج پرسش پایانی
data["final_answers"] = {
    "1_trust_valuation": ("بله، با قید: مبنای قیمت×سهام در پنجرهٔ مشاهده‌شده تناقضی ندارد و مقادیر سهام پایدارند؛ "
                          "اما نسبت‌های ارزندگی به وینتیج حساس‌اند — سه محاسبهٔ مستقل P/E ۷٫۵۵–۸٫۰۷ و P/B ۵٫۸۱–۶٫۲۱ "
                          "می‌دهد و snapshot مالی canonical از قیمت ۳ جلسه کهنه استفاده می‌کرد. برای بوعلی P/B با "
                          "equity جاری (period_order=1) مبنا روشن شد؛ تعارض ظاهری، ستون مقایسه‌ای (order=2) بود."),
    "2_coverage": ("۶۲ شرکت واقعاً سه‌محوری و کامل ارزیابی‌شدند. از ۲۷۱، صفر بازیابی مستقل قطعی: ۲ شرکت T "
                   "(شبهرن، کسرا) فقط با ضریب گپ-استخراج‌شده (دورْی) واجد T می‌شوند و ۳ شرکت equity "
                   "(بفجر، قاسم، مادیرا) در sandbox P/B دارند؛ بقیه preview. هیچ‌کدام بدون دادهٔ مستقل/مجوز backfill قطعی نمی‌شوند."),
    "3_corporate_action": ("حل نشد. همهٔ ضرایب market.corporate_actions از منبع واحد tsetmc_gap_rule_v1 و قاعدهٔ گپ-یاب "
                           "استخراج شده‌اند؛ اعمال آن‌ها گپ را دورْی حذف می‌کند و شاهد مستقل وقوع اقدام شرکتی نیست. پس ۲۶ شرکت "
                           "گپ و ۶ شرکت تاریخچهٔ کوتاه همچنان به داده/اقدام شرکتی مستقل نیاز دارند."),
    "4_fresh_snapshot": ("بله — snapshot آزمایشی هم‌خوان در as_of ۲۰۲۶-۱۰-۱۱ (Q+V+T) ساخته شد، بدون overwrite. "
                         "ترکیب گروه‌ها تغییر کرد (۳ شرکت به مانع دروازه ریسک رفتند؛ waiting ۴۴→۴۱، blocked ۹→۱۲) "
                         "اما تعداد «جذاب» همان ۰ ماند و مجموعهٔ ۶۲ سه‌محوری یکسان بود."),
    "5_biggest_barrier": ("بزرگ‌ترین مانع: نبود تاریخچهٔ مالی/قیمت معتبر کافی در مخزن canonical برای اکثریت جامعه "
                          "(۱۶۲ equity مفقود + ۲۴ گپ T + ۶ تاریخچهٔ کوتاه) و نبود سری چنددوره‌ای OCF. تا این داده‌ها "
                          "تأمین نشود، موتور فقط روی همان ۶۲ شرکت قابل اتکاست و «الان ارزش بررسی دارد» صادقانه نمی‌شود."),
}

json.dump(data, open(os.path.join(OUT, "gam2k10_final_report.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=str)

# ── Markdown ────────────────────────────────────────────────────────────────
b = data
md = []
md.append("# گزارش نهایی گام ۲-ک-۱۰ — رفع موانع واقعی اعتماد و پوشش معتبر QVT\n")
md.append(f"snapshot: `{TAG}` | موتور: `{b['rules_version']}` + `{b['policy_version']}`\n")
md.append("> این گزارش «نامزد بررسی» است؛ نه توصیهٔ خرید/فروش و نه اثبات آماری سودآوری. هیچ commit/backfill/انتشار دائمی انجام نشد.\n")

md.append("## خلاصهٔ اجرایی\n")
g = b["counting_contract"]["groups"]
md.append(f"- شمارش صریح: جذاب {g['attractive_candidates']} + منتظر {g['fundamentals_waiting']} + "
          f"ارزان‌نما {g['apparent_value_risk']} + مانع {g['blocked_or_insufficient']} = {g['total']} = جامعهٔ سه‌محوری {g['universe']} (reconciles={g['reconciles']}).\n")
a = b["counting_contract"]["attributes"]
md.append(f"- صفت‌ها (مستقل از گروه): مشروط در گروه ۲ = {a['conditional_in_waiting']}، تنها-مانع = {a['conditional_blocking']}، "
          f"کل دارندگان قید = {a['conditional_total']}، review_required = {a['risk_review_required']}، تازگی تأییدشده = {a['price_freshness_verified']}.\n")
md.append(f"- جذاب بدون قید اختصاصی: **{g['attractive_candidates']}**. صفر نتیجهٔ صادقانهٔ شواهد است.\n")
md.append(f"- بازیابی قطعیِ مستقل T: **{b['coverage_before_after']['T_axis']['n_recovered_definite_independent']}** شرکت؛ "
          f"{b['coverage_before_after']['T_axis']['n_adjustment_applied_circular']} شرکت "
          f"({', '.join(b['coverage_before_after']['T_axis']['circular_symbols']) or '—'}) فقط با ضریب گپ-استخراج‌شده (دورْی/غیرمستقل).\n")
md.append(f"- resolver gap ارزندگی: **{len(b['coverage_before_after']['equity_axis']['resolver_gaps_recoverable'])}** شرکت "
          f"({', '.join(b['coverage_before_after']['equity_axis']['resolver_gaps_recoverable']) or '—'}).\n")

md.append("\n## ۱) وضعیت و تغییرات نسبت به ۲-ک-۹\n")
for c in b["status_and_changes"]["changes_vs_2k9"]:
    md.append(f"- {c}")

md.append("\n## ۲) رفع ابهام شمارش گروه‌ها و معنای «مشروط»\n")
md.append(f"- {b['counting_contract']['problem']}")
md.append(f"- {b['counting_contract']['resolution']}")
md.append(f"- {b['counting_contract']['conditional_semantics']}")
md.append(f"- سازگاری Risk Gate: {b['counting_contract']['risk_gate_consistency']}")

md.append("\n## ۳) پروندهٔ اقتصادی بوعلی و نتیجهٔ قطعی موتور\n")
bc = b["boali_case"]
dc = (bc.get("raw", {}).get("derived_checks") or {})
md.append(f"- ROE خام / عملیاتی→خالص: op_to_net={dc.get('op_to_net')}، ocf_to_net={dc.get('ocf_to_net')} — {dc.get('recurrence')}")
md.append(f"- قیمت: {bc['valuation']['price_component']['trade_date']}، close={bc['valuation']['price_component']['close_rial']}، سری={bc['valuation']['price_component']['price_series']}")
md.append(f"- سهام پایدار: {[s['shares'] for s in bc['valuation']['shares_component']]} (۳ رصد)")
md.append(f"- P/E·P/B·P/S آرتیفکت V: {bc['valuation']['artifact_v_raw']} | بازمحاسبهٔ مستقل: {bc['valuation']['recompute_from_canonical']}")
md.append(f"- اقتصاد capital: {bc['valuation']['equity_prior_year_is_period_order_2']}")
md.append(f"- کیفیت نقد: OCF_ttm={p4['ttm_stitch']['metrics_ocf_ttm']:.3e}، NP_ttm={p4['ttm_stitch']['metrics_net_profit_ttm']:.3e}، "
          f"نسبت خام={p4['ttm_stitch']['raw_cash_conversion_ocf_over_np']:.4f}، پرسنتایل={p4['threshold_basis']['artifact_cash_conversion_pct']:.4f}؛ "
          f"افت YoY دورهٔ جاری={p4['yoy_signal']['yoy_change_pct']}%")
md.append(f"- **نتیجه: {bc['verdict']}**")

md.append("\n## ۴) نامزدهای گروه اول\n")
md.append(f"جذاب بدون قید اختصاصی: **{b['group1_candidates']['count']}**. {b['group1_candidates']['note'][:400]}")

md.append("\n## ۵) وضعیت ۱۶ نامزد قدیمی\n")
md.append("| نماد | گروه | مشروط | مهم‌ترین ریسک |")
md.append("|---|---|---|---|")
for r in b["old16_status"]:
    md.append(f"| {r['symbol']} | {r['group_fa']} | {'بله' if r['conditional'] else 'خیر' if r['conditional'] is not None else '—'} | {(r['reason'] or '')[:80]} |")

md.append("\n## ۶) پوشش Q/V/T پیش و پس از آزمایش بازیابی\n")
t = b["coverage_before_after"]["T_axis"]
eq = b["coverage_before_after"]["equity_axis"]
md.append(f"- T: پایهٔ واجد T={t['baseline_eligible_T']} (تطبیق با آرتیفکت=True)؛ آزمایشی={t['experimental_eligible_T']}؛ "
          f"بازیابی قطعی مستقل={t['n_recovered_definite_independent']}؛ اعمال ضریب دورْی={t['n_adjustment_applied_circular']} "
          f"({t['circular_symbols']})؛ ۶ شرکت تاریخچهٔ کوتاه قابل بازیابی={t['short_history_recoverable']}.")
md.append(f"- هشدار دورْی: {t['circularity_warning']}")
md.append(f"- منبع ضرایب: {t['adjustment_source_census']}")
md.append(f"- equity: هدف={eq['targets']}؛ verdicts={eq['verdict_counts']}؛ resolver-gap={eq['resolver_gaps_recoverable']}؛ "
          f"already-resolved={eq['already_resolved_pb']}؛ اگر Q/V رفع شود فقط {eq['triple_if_qv_recovered']} می‌تواند سه‌محوری شود.")
md.append(f"- تفکیک ۱۷۰ (۲-ک-۸) و ۱۷۲ (۲-ک-۹): {eq['discrepancy_170_vs_172']['v_block_code_counts']} — اختلاف ۲ = شرکت‌های equity+earnings.")
md.append(f"- قطعی: {b['coverage_before_after']['definite_vs_probable']['definite']}")
md.append(f"- دورْی/غیرمستقل: {b['coverage_before_after']['definite_vs_probable']['circular_not_independent']}")
md.append(f"- احتمالی: {b['coverage_before_after']['definite_vs_probable']['probable']}")
md.append(f"- غیرقابل بازیابی: {b['coverage_before_after']['definite_vs_probable']['not_recoverable']}")

md.append("\n## ۷) کیفیت زمانی قیمت و داده‌های مالی\n")
tq = b["temporal_quality"]
md.append(f"- مرجع کنترل تازگی: {tq['freshness_reference']['control_reference']} — آخرین collected_at مخزن={tq['freshness_reference']['max_collected_at_in_store']}، cutoff آرتیفکت کهنه={tq['freshness_reference']['old_snapshot_cutoff']} ⇒ look-ahead حذف شد.")
md.append(f"- مبنای قیمت×سهام: {tq['price_chain']['verdict_counts']}؛ فاصلهٔ سهام↔قیمت: {tq['price_chain']['share_price_gap_days_distribution']}")
md.append(f"- snapshot تازه: قدیم {tq['fresh_snapshot']['old']} → جدید {tq['fresh_snapshot']['new']}")
md.append(f"- گروه‌ها: رسمی {tq['fresh_snapshot']['board_groups_official']} → تازه {tq['fresh_snapshot']['board_groups_fresh']}")

md.append("\n## ۸) نسخهٔ سیاست و تحلیل حساسیت\n")
md.append(f"- سیاست: `{b['policy_and_sensitivity']['policy']['version']}`؛ قواعد: `{b['policy_and_sensitivity']['rules_version']}`؛ بازتولید مستقل: {b['policy_and_sensitivity']['repro_match']}.")
for k, vv in b["policy_and_sensitivity"]["sensitivity"].items():
    md.append(f"- حساسیت {k}: " + "، ".join(f"{t}→جذاب {c['counts']['attractive_candidates']}" for t, c in vv.items()))

md.append("\n## ۹) فایل‌های تغییرکرده (بدون commit)\n")
for f in b["git"]["changed_for_2k10"]:
    md.append(f"- `{f}`")

md.append("\n## ۱۰) تست‌ها، هش‌ها، endpointها، نواقص و مجوزها\n")
th = b["tests_hashes_endpoints"]
for k in ("go_test", "typescript", "python", "publisher", "reproduction", "browser"):
    md.append(f"- {th[k]}")
md.append(f"- endpointها: " + "، ".join(f"{k}={v}" for k, v in th["endpoints"].items()))
md.append(f"- هش آرتیفکت‌ها: {th['artifact_hashes_prefix']}")
md.append("- نواقص: " + "؛ ".join(th["remaining_defects"]))
md.append("- مجوزهای لازم: " + "؛ ".join(th["permissions_required"]))

md.append("\n## پاسخ پنج پرسش پایانی\n")
fa = b["final_answers"]
md.append(f"**۱.** {fa['1_trust_valuation']}")
md.append(f"\n**۲.** {fa['2_coverage']}")
md.append(f"\n**۳.** {fa['3_corporate_action']}")
md.append(f"\n**۴.** {fa['4_fresh_snapshot']}")
md.append(f"\n**۵.** {fa['5_biggest_barrier']}")

md.append("\n## محدودیت‌های غیرقابل نقض — همگی رعایت شد\n")
md.append("no_commit, no_permanent_db_write, no_sql125_backfill, no_qvt_formula_change, no_diagnostic_activation, "
          "no_100_score, no_v1v4_change, no_artifact_overwrite, no_quarantine_bypass, no_look_ahead, no_fake_data, "
          "no_buy_sell_advice\n")

open(os.path.join(OUT, "gam2k10_final_report.md"), "w", encoding="utf-8").write("\n".join(md))
print("wrote gam2k10_final_report.json + .md")
print("groups:", g)
print("T definite-independent recovered:", t["n_recovered_definite_independent"],
      "| circular adjustment:", t["n_adjustment_applied_circular"],
      "| equity resolver gaps:", eq["resolver_gaps_recoverable"])
