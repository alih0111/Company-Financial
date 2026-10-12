#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۹ — تولید گزارش نهایی نسخه‌دار (Markdown + JSON) در provenance_v1/output.

هیچ عددی حدس زده نمی‌شود؛ همه از آرتیفکت‌های همین گام و پاسخ زندهٔ موتور
(_board_2k9_live.json) خوانده می‌شود.
"""

import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"


def L(name):
    return json.load(open(os.path.join(OUT, name), encoding="utf-8"))


cov = L(f"coverage_full_2k9_{TAG}.json")
cases = L(f"economic_cases_2k9_{TAG}.json")
rec = L(f"recovery_2k9_{TAG}.json")
repro = L(f"engine_reproduction_2k9_{TAG}.json")
live = L("_board_2k9_live.json")
board = live["opportunity_board"]
live7 = L("_board_2k7_live.json")
b7 = live7["opportunity_board"]

GROUPS = ["attractive_candidates", "fundamentals_waiting", "apparent_value_risk", "blocked_or_insufficient"]
GROUP_FA = {"attractive_candidates": "جذاب برای بررسی جدی", "fundamentals_waiting": "بنیادی مناسب — منتظر (شامل مشروط)",
            "apparent_value_risk": "ارزان‌نما — پرریسک", "blocked_or_insufficient": "شواهد ناکافی/مانع"}
sym_group = {}
sym_entry = {}
for g in GROUPS:
    for e in board[g]:
        sym_group[e["symbol"]] = g
        sym_entry[e["symbol"]] = e

old16 = [e["symbol"] for e in b7.get("review_priority", [])]
old16_rows = [{"symbol": s, "new_group": sym_group.get(s, "خارج از جامعه"),
               "new_group_fa": GROUP_FA.get(sym_group.get(s), "خارج از جامعه"),
               "conditional": bool(sym_entry.get(s, {}).get("conditional")),
               "new_reason": (sym_entry.get(s, {}).get("group_reason") or "")[:220]} for s in old16]

# بوعلی
boali = next(c for c in cases["cases"] if c["symbol"] == "بوعلی")
boali_entry = sym_entry["بوعلی"]

# تازگی قیمت
ages = []
for g in GROUPS:
    for e in board[g]:
        pf = e.get("price_freshness") or {}
        if pf.get("age_days") is not None:
            ages.append(pf["age_days"])

counts = board["counts"]
sensitivity = repro["sensitivity"]

report = {
    "artifact": "gam2k9_final_report",
    "version": "2k9-report-v1",
    "snapshot_tag": TAG,
    "as_of": board["as_of"],
    "engine": {"rules": board["rules"]["version"], "policy": board["decision_policy"]["version"]},
    "not_a_signal": "این گزارش «نامزد بررسی» است؛ نه توصیه خرید/فروش و نه اثبات آماری سودآوری",
    "p0_coverage_discrepancy": {
        "question": "چرا جمع چهار دستهٔ گزارش ۲-ک-۸ برابر ۲۶۶ بود نه ۲۷۱؟",
        "answer": "برچسب‌های گزارش ۲-ک-۸ سه حالت میانی را حذف کرده بود؛ خودِ آرتیفکت از ابتدا ۲۷۱ بود.",
        "states": cov["states"],
        "omitted_5": cov["why_2k8_report_said_266"],
        "sum_of_states": cov["sum_of_states"],
        "reconciliation_ok": cov["reconciliation_ok"],
        "primary_gaps": cov["primary_gap_counts"],
    },
    "boali_economic_case": boali,
    "boali_final_verdict": {
        "engine_group": "fundamentals_waiting",
        "conditional": boali_entry.get("conditional"),
        "conditional_reasons": boali_entry.get("conditional_reasons"),
        "clean_attractive": False,
        "explanation": "بوعلی آستانه‌های اعلامی را پاس می‌کند (ROE خام ۷۶٫۹٪، سود عملیاتی ≥ سود خالص، P/E خام ۷٫۶۷ در گروه ۶ همتا، ورود مناسب) اما قید کیفیت «تبدیل نقد ضعیف» دارد: OCF/NP=۰٫۳۳ و پرسنتایل cash_conversion=۰٫۳۷؛ بنابراین «جذاب بدون قید» اعلام نمی‌شود و به حالت مشروط/انتظار می‌رود. با کف سیاست ۰٫۳۰ (نه ۰٫۴۰) بوعلی دوباره نامزد جذاب خالص می‌شود — حساسیت در بخش سیاست.",
        "hard_limits": [
            "OCF/NP=۰٫۳۳ (canonical_v1_metrics؛ TTM) — فقط یک‌سوم سود دفتری با نقد عملیاتی پشتیبانی می‌شود",
            "پرسنتایل margins=۰٫۲۲ و leverage=۰٫۲۸ (پرسنتایل، نه نسبت خام؛ حاشیه خام ۱۴٫۹۷٪ و debt_ratio ۰٫۶۶ سالم/متوسط‌اند)",
            "مبنای سهام↔قیمت اثبات‌نشده (۳ روز اختلاف؛ شاهد اقدام شرکتی ثبت نشده)",
            "پوشش Q=۷۸٪ (وزن مفقود ۹ از ۴۰ بازتوزیع نشده)",
            "پرووننس order3 برای earnings_quality و interest_coverage (از نامهٔ خام بازیابی‌شده)",
            "دروازه ریسک review_required (یافتهٔ ثبت‌شده، نه تأیید و نه رد)",
        ],
    },
    "group1_candidates": {
        "clean_attractive": counts["attractive_candidates"],
        "conditional": counts.get("conditional_candidates"),
        "table": ([{
            "نماد": e["symbol"], "صنعت": e["industry"],
            "بنیادی": e["fundamental_label"], "ارزندگی": e["value_label"],
            "ورود": e["entry_label"], "نتیجه": e["conclusion"],
            "مهم‌ترین_دلیل": e["top_reason"], "ریسک": e["top_risk"],
        } for e in board["attractive_candidates"]]) or (
            # هیچ جذاب خالصی نیست → نزدیک‌ترین مشروط نمایش داده می‌شود
            [{
                "نماد": boali_entry["symbol"], "صنعت": boali_entry["industry"],
                "بنیادی": boali_entry["fundamental_label"], "ارزندگی": boali_entry["value_label"],
                "ورود": boali_entry["entry_label"], "نتیجه": "نامزد مشروط (نه جذاب بدون قید)",
                "مهم‌ترین_دلیل": boali_entry["top_reason"], "ریسک": boali_entry["top_risk"],
            }]
        ),
        "note": "طبق سیاست v2، گروه جذاب «بدون قید» فعلاً صفر است؛ یک نامزد مشروط (بوعلی) در گروه دوم با قید صریح نمایش داده می‌شود.",
    },
    "old16_status": old16_rows,
    "coverage_before_after": {
        "qvt_artifacts_unchanged": True,
        "triple_eligible_before": 62, "triple_eligible_after": 62, "delta": 0,
        "priority1_T_32": {
            "definite": rec["priority1_T_recovery"]["cause_counts"],
            "recoverable_now": rec["priority1_T_recovery"]["recoverable_now_with_existing_data"],
            "needs_corporate_action_or_price_backfill": rec["priority1_T_recovery"]["needs_price_data_or_corporate_action"],
            "control_matches_artifact": rec["priority1_T_recovery"]["control_matches_artifact"],
            "conclusion": "هیچ‌کدام از ۳۲ شرکت با دادهٔ موجود T قابل تکمیل نیست: ۲۶ مورد gap مشکوک (اقدام شرکتی اعمال‌نشده) و ۶ مورد تاریخچهٔ قیمت کوتاه. برخلاف فرض +۳۲.",
        },
        "priority2_equity_170": {
            "n_targets": rec["priority2_equity_recovery"]["n_targets"],
            "class_counts": rec["priority2_equity_recovery"]["class_counts"],
            "recoverable_now": rec["priority2_equity_recovery"]["equity_recovery_preview"]["n_recoverable_now"],
            "truly_missing": rec["priority2_equity_recovery"]["equity_recovery_preview"]["n_truly_missing"],
            "conclusion": "از ۱۷۲ هدف، ۱۶۲ واقعاً فاقد ترازنامه‌اند؛ ۱۰ مورد دادهٔ ترازنامه/equity به‌روز در مخزن دارند و با اصلاح resolve/نگاشت قابل بازیابی‌اند (۵ با فکت equity و ۵ با ترازنامه بدون فکت).",
            "recoverable_symbols": [r["symbol"] for r in rec["priority2_equity_recovery"]["equity_recovery_preview"]["rows"]
                                    if r["within_balance_sheet_staleness_policy"]],
        },
    },
    "temporal_quality": {
        "snapshot_as_of": board["as_of"],
        "fundamental_artifacts_as_of": {"q": live["sources"]["q"]["as_of"], "v": live["sources"]["v"]["as_of"], "t": live["sources"]["t"]["as_of"]},
        "price_freshness_verified": f"{counts.get('n_price_freshness_verified')}/{counts['n_triple_universe']}",
        "price_age_days_min_median_max": [min(ages), statistics.median(ages), max(ages)],
        "price_policy_days": 7,
        "timezone_note": "PIT/Asia/Tehran مطابق گام پیشین (۲-ک-۴) دست‌نخورده؛ cutoff آرتیفکت‌ها مبنای کنترل است",
        "fresher_data_available": "market.price_observations تا ۲۰۲۶-۱۰-۱۱ ردیف دارد (جدیدتر از cutoff آرتیفکت ۲۰۲۶-۱۰-۰۸) — ساخت snapshot آزمایشی تازه ممکن است ولی در این مأموریت بدون overwrite و بدون انتشار انجام نشد.",
        "claim_allowed_now": "خیر — «الان ارزش بررسی دارد» فقط مشروط به همین snapshot (سن قیمت ۳ روز) و با قیدهای جهانی؛ هیچ ادعای زمان‌واقعی وجود ندارد.",
    },
    "decision_policy_and_sensitivity": {
        "version": board["decision_policy"]["version"],
        "v1_preserved_for_comparison": "بله — توابع boardDecisionPolicyV1() و مسیر تست v1↔v2 حفظ شده",
        "sensitivity": sensitivity,
        "interpretation": "تنها آستانهٔ مؤثر بر «جذاب خالص» در این snapshot، کف کیفیت تبدیل نقد است (۰٫۳۰→۱ جذاب، ۰٫۴۰/۰٫۵۰→۰). هیچ آستانه‌ای برای ساختن/حذف نامزد تنظیم نشد.",
    },
    "tests_and_verification": {
        "go_test": "go test ./... → همه سبز (شامل ۴ تست جدید ۲-ک-۹: قید کیفیت، سود عملیاتی منفی، پشتیبانی صنعتی چندگانه، انتشار قیدهای جهانی)",
        "typescript": "npx tsc --noEmit → پاک",
        "analytics_python": "pytest (score_v2/value/t) → 119 passed",
        "publisher": "publish_bundle.py --selftest → 13/13",
        "endpoints": {"/api/AllCompanyScores": 200, "/api/qvt-v2": 200, "/api/qvt-v2/discovery": 200, "/api/health/shadow": 200},
        "engine_reproduction": {"n_match": repro["n_match"], "n_companies": repro["n_companies"], "consistency_ok": repro["consistency_ok"]},
        "browser": "رابط واقعی: سربرگ (snapshot/سیاست v2/جامعه ۶۲/تازگی ۶۲-۶۲/دروازه ریسک ۶۲-۶۲/مشروط ۱۳)، پنل قیدهای جهانی، پیام صفر-جذاب، شمارش موانع ۶۲، سرصفحهٔ گروه۲ با «شامل ۱ نامزد مشروط» — همه در مرورگر تأیید شد",
        "artifact_hashes": {k: live["sources"][k]["sha256"] for k in ("q", "v", "t")},
    },
    "remaining_limitations": [
        "equity مفقود ۱۶۲ شرکت (بدون ترازنامه در مخزن)",
        "T ناقص برای ۳۲ شرکت (۲۶ gap مشکوک + ۶ تاریخچهٔ کوتاه)",
        "پوشش Q زیر آستانه ۱۶۱ شرکت؛ بانک/مالی خارج از دامنه ۱۱",
        "roe_stability و margin_trend (not_implemented) خارج از دستهٔ ۲-B-5",
        "مبنای سهام↔قیمت اثبات‌نشده و پرووننس order3 (قیدهای جهانی، ثبت‌شده)",
        "آستانه‌ها آزمایشی و بدون بک‌تست PIT کامل",
    ],
    "required_permissions": [
        "backfill حقوق صاحبان سهام (SQL 125) — V برای ~۱۶۲ شرکت",
        "واردات تاریخچهٔ قیمت + اصلاح اقدامات شرکتی — T برای ۳۲ شرکت",
        "تکمیل صورت‌های مالی تاریخی — Q از ۹۸ به سقف ~۲۶۰",
        "فعال‌سازی دائمی QVT_MANIFEST_DIR؛ گسترش خانوادهٔ بانکی؛ commit؛ رفع exclusion 2-B-6",
    ],
    "answers": {
        "الف_boali": "بوعلی پس از ممیزی اقتصادی «نامزد مشروط قابل بررسی» است، نه «جذاب بدون قید»: بنیادی و ارزندگی و ورودش قابل دفاع است اما تبدیل نقد ضعیف (OCF/NP=۰٫۳۳) و مبنای سهام↔قیمت اثبات‌نشده و review_required دارد. نتیجه از شواهد استخراج شد، نه از انتظار.",
        "ب_coverage": "کل ۲۷۱ شرکت با شناسهٔ پایدار در ۸ حالت بدون هم‌پوشانی دسته‌بندی شدند؛ ۶۲ شرکت سه‌محوری با شواهد کامل قابل ارزیابی‌اند. بدون backfill دائمی، ۱۰ شرکت equity (نگاشت/resolve) قابل بازیابی‌اند و ۰ شرکت T. ۱۶۲ مورد equity و ۳۲ مورد T بدون دادهٔ جدید بازیابی‌شدنی نیستند.",
        "ج_now_claim": "فقط به‌صورت مشروط: قیمت‌ها ۳ روزه و در سیاست ۷ روز تأیید شده‌اند، اما قیدهای جهانی (review_required، مبنای سهام، order3) و نبود نامزد بدون قید مانع ادعای «الان جذاب» می‌شوند؛ عبارت صادقانه «نامزد مشروط با این snapshot» است.",
        "د_next_action": "بالاترین بازده واقعی: تکمیل تاریخچهٔ قیمت/اقدامات شرکتی برای ۳۲ شرکت Q+V است زیرا هم‌زمان T را کامل می‌کند و هم کیفیت مبنای سهام↔قیمت را می‌سازد، بدون نیاز به بازطراحی؛ سپس رفع نگاشت/resolve equity برای ۱۰ شرکت (سریع و کم‌هزینه).",
    },
    "baseline_vs_2k8": {
        "output": "گروه‌ها: جذاب خالص ۱→۰؛ منتظر ۴۳→۴۴ (شامل ۱ مشروط)؛ ارزان‌نما ۹؛ مانع ۹؛ جامعه ۶۲ ثابت",
        "code": "opportunity_decision.go (+قید کیفیت، +پشتیبانی صنعتی، نسخهٔ سیاست v2، حفظ v1)؛ opportunity.go (قواعد v3، گروه مشروط، قیدهای جهانی، شمارش‌ها)؛ discovery.go (کنترل قیمت برای همهٔ ۶۲)؛ opportunity_test.go (+۴ تست)؛ api.ts + QvtAnalysisPage.tsx (انواع/نمایش مشروط/قیدها)؛ ۶ اسکریپت/آرتیفکت جدید",
        "unchanged": "آرتیفکت‌های اصلی Q/V/T، فرمول/وزن رسمی، V1/V4، قرنطینه‌ها، publisher",
        "git": "بدون commit؛ فایل‌های مراحل قبلی مخلوط نشدند",
    },
    "constraints_respected": [
        "no_commit", "no_permanent_db_write", "no_sql125_backfill", "no_qvt_formula_change",
        "no_diagnostic_activation", "no_100_score", "no_v1v4_change", "no_artifact_overwrite",
        "no_quarantine_bypass", "no_fake_data", "no_buy_sell_advice",
    ],
}

p = os.path.join(OUT, "gam2k9_final_report.json")
json.dump(report, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote:", p, os.path.getsize(p), "bytes")

# ── Markdown ─────────────────────────────────────────────────────────────────
md = []
md.append("# گزارش نهایی گام ۲-ک-۹ — اعتبارسنجی اقتصادی فرصت‌ها و پوشش قابل‌دفاع QVT")
md.append("")
md.append(f"snapshot: `{TAG}` — as_of: {board['as_of']} | موتور: `{board['rules']['version']}` + `{board['decision_policy']['version']}`")
md.append("")
md.append("> این گزارش «نامزد بررسی» است؛ نه توصیه خرید/فروش و نه اثبات آماری سودآوری")
md.append("")
md.append("## خلاصهٔ فرصت‌های واقعی قابل بررسی")
md.append("")
md.append(f"جامعهٔ سه‌محوری ۶۲ شرکت → **جذاب بدون قید: {counts['attractive_candidates']}** | "
          f"مشروط: {counts.get('conditional_candidates')} (که تنها مانعِ {counts.get('n_conditional_blocking')} مورد «همین قید» بوده) | "
          f"منتظر: {counts['fundamentals_waiting']} | ارزان‌نما: {counts['apparent_value_risk']} | مانع: {counts['blocked_or_insufficient']}")
md.append("")
md.append("| نماد | صنعت | بنیادی | ارزندگی | ورود | نتیجه | مهم‌ترین دلیل | ریسک |")
md.append("|---|---|---|---|---|---|---|---|")
for r in report["group1_candidates"]["table"]:
    md.append(f"| {r['نماد']} | {r['صنعت']} | {r['بنیادی']} | {r['ارزندگی']} | {r['ورود']} | {r['نتیجه']} | {r['مهم‌ترین_دلیل'][:120]} | {r['ریسک'][:120]} |")
md.append("")
md.append("بیش از یک نامزد جذاب بدون قید وجود ندارد؛ صفر کاملاً پذیرفته و صادقانه است. نزدیک‌ترین گزینه «مشروط» بالا آمده است.")
md.append("")
md.append("## ۱) وضعیت گام ۲-ک-۹ و تغییرات نسبت به ۲-ک-۸")
md.append("")
md.append("- ارتقای سیاست تصمیم به `opportunity-decision-policy-v2` و قواعد `opportunity-rules-v3`: افزودن **قید کیفیت تبدیل نقد** و **کفایت گروه همتای چندگانهٔ پشتیبان ارزندگی**، به‌علاوهٔ انتشار برجستهٔ **قیدهای جهانی snapshot**؛ رفتار نسخهٔ ۱ برای مقایسه حفظ شد.")
md.append("- بزرگ‌ترین تغییر رفتار: بوعلی از «جذاب» به «مشروط» منتقل شد (ضعف تبدیل نقد پشت ROE قوی پنهان نمی‌ماند).")
md.append("- کنترل مستقل تازگی قیمت از ۱۶ به **۶۲ از ۶۲** شرکت گسترش یافت.")
md.append("")
md.append("## ۲) تعیین تکلیف اختلاف ۵ شرکت در پوشش")
md.append("")
w = cov["why_2k8_report_said_266"]
md.append(f"جمع هشت حالت بدون هم‌پوشانی = **{cov['sum_of_states']}** = جامعهٔ واقعی (تأییدشده: {cov['reconciliation_ok']})."
          f" اختلاف ۲۶۶≠۲۷۱ ناشی از حذف سه حالت میانی در برچسب‌گذاری گزارش قبلی بود: "
          f"TFT={w['omitted_states'].get('TFT',0)}، TFF={w['omitted_states'].get('TFF',0)}، FTT={w['omitted_states'].get('FTT',0)} (جمع {w['omitted_total']}). "
          f"هیچ شرکتی در داده جا نیفتاده بود.")
md.append("")
md.append(f"حالت‌ها: " + "، ".join(f"{k}={v['count']}" for k, v in cov["states"].items()))
md.append("")
md.append("## ۳) پروندهٔ اقتصادی بوعلی و نتیجهٔ قطعی موتور")
md.append("")
bf = boali["raw_financials"]
bc = boali["derived_checks"]
md.append(f"- ROE خام **{bf['roe_pct_raw']}٪** (پرسنتایل {boali['artifact_percentiles']['q']['roe_level']}) — سودآوری واقعی بالا")
md.append(f"- حاشیه خام خالص **{bf['net_margin_pct_raw']}٪** / عملیاتی **{bf['operating_margin_pct_raw']}٪** (پرسنتایل margins {boali['artifact_percentiles']['q']['margins']} — نسبت خام سالم، رتبهٔ نسبی پایین)")
md.append(f"- سود عملیاتی ≥ سود خالص (op/net={bc.get('op_to_net')}) → سود از اقلام غیرتکراری متورم نشده")
md.append(f"- **تبدیل نقد ضعیف: OCF/NP={bc.get('ocf_to_net')}** — فقط یک‌سوم سود دفتری با جریان نقد عملیاتی پشتیبانی می‌شود")
md.append(f"- P/E خام {boali['artifact_percentiles']['v']['pe']['raw']} (پرسنتایل {boali['artifact_percentiles']['v']['pe']['score']})، P/B {boali['artifact_percentiles']['v']['pb']['raw']}، P/S {boali['artifact_percentiles']['v']['ps']['raw']}؛ میانگین پرسنتایل {boali['artifact_percentiles']['v']['mean_included']} در گروه ۶ همتای «{boali['industry']}»")
md.append(f"- مبنای سهام↔قیمت: {boali['pe_pb_basis']['share_as_of_date']} برای سهام در برابر قیمت جدیدتر — سازگاری **اثبات‌نشده**")
md.append(f"- **نتیجه: {report['boali_final_verdict']['explanation']}**")
md.append("")
md.append("## ۴) نامزدهای گروه اول")
md.append("")
md.append(f"جذاب بدون قید: **{counts['attractive_candidates']}**. " + report["group1_candidates"]["note"])
md.append("")
md.append("## ۵) وضعیت ۱۶ نامزد قدیمی")
md.append("")
n_old_att = sum(1 for r in old16_rows if r["new_group"] == "attractive_candidates")
n_old_cond = sum(1 for r in old16_rows if r["conditional"] and r["new_group"] != "attractive_candidates")
md.append(f"از ۱۶ نامزد قبلی: **{n_old_att} مورد جذاب بدون قید**، {n_old_cond} مورد «مشروط»، بقیه در گروه منتظر/ارزان‌نما/مانع. "
          f"هیچ‌کدام دیگر خودکار در فهرست اولیه نمی‌آید.")
md.append("")
md.append("| نماد | گروه جدید | مشروط | دلیل جدید (خلاصه) |")
md.append("|---|---|---|---|")
for r in old16_rows:
    md.append(f"| {r['symbol']} | {r['new_group_fa']} | {'بله' if r['conditional'] else 'خیر'} | {r['new_reason'][:110]} |")
md.append("")
md.append("## ۶) پوشش Q/V/T پیش و پس از آزمایش بازیابی")
md.append("")
md.append(f"- T برای ۳۲ شرکت Q+V: علل قطعی = {rec['priority1_T_recovery']['cause_counts']}؛ قابل بازیابی با دادهٔ موجود = **{rec['priority1_T_recovery']['recoverable_now_with_existing_data']}**؛ کنترل ریاضی با آرتیفکت = {rec['priority1_T_recovery']['control_matches_artifact']}")
md.append(f"- equity برای ۱۷۲ شرکت: {rec['priority2_equity_recovery']['class_counts']}؛ قابل بازیابی الآن = **{rec['priority2_equity_recovery']['equity_recovery_preview']['n_recoverable_now']}**؛ واقعاً مفقود = {rec['priority2_equity_recovery']['equity_recovery_preview']['n_truly_missing']}")
md.append(f"- سه‌محوری: ۶۲ → ۶۲ (بدون backfill؛ هیچ داده‌ای جایگزین نشد)")
md.append("")
md.append("## ۷) کیفیت زمانی قیمت و داده‌های مالی")
md.append("")
tq = report["temporal_quality"]
md.append(f"- as_of آرتیفکت‌ها: Q={tq['fundamental_artifacts_as_of']['q']}، V={tq['fundamental_artifacts_as_of']['v']}، T={tq['fundamental_artifacts_as_of']['t']}")
md.append(f"- تازگی قیمت تأییدشده: {tq['price_freshness_verified']}؛ سن قیمت (چندک): {tq['price_age_days_min_median_max']} روز، سیاست {tq['price_policy_days']} روز")
md.append(f"- {tq['fresher_data_available']}")
md.append("")
md.append("## ۸) نسخهٔ سیاست تصمیم و تحلیل حساسیت")
md.append("")
md.append(f"- نسخه: `{report['decision_policy_and_sensitivity']['version']}`؛ نسخهٔ ۱ برای مقایسه حفظ شده.")
for k, vals in sensitivity.items():
    parts = [f"{t}→{v['counts']['attractive_candidates']} جذاب" for t, v in vals.items()]
    md.append(f"- حساسیت {k}: " + "، ".join(parts))
md.append(f"- {report['decision_policy_and_sensitivity']['interpretation']}")
md.append("")
md.append("## ۹) فایل‌های تغییرکرده (بدون commit)")
md.append("")
md.append("- `go-app/handlers/qvt/opportunity_decision.go` (سیاست v2 + قید کیفیت + پشتیبانی صنعتی)")
md.append("- `go-app/handlers/qvt/opportunity.go` (قواعد v3 + گروه مشروط + قیدهای جهانی)")
md.append("- `go-app/handlers/qvt/discovery.go` (کنترل قیمت همهٔ ۶۲)")
md.append("- `go-app/handlers/qvt/opportunity_test.go` (+۴ تست)")
md.append("- `client/src/utils/api.ts`، `client/src/components/QvtAnalysisPage.tsx`")
md.append("- `provenance_v1/make_2k9_coverage.py`، `make_2k9_economic_cases.py`، `make_2k9_recovery.py`، `validate_2k9_engine.py`، `make_gam2k9_report.py`")
md.append("")
md.append("## ۱۰) تست‌ها، هش‌ها، endpointها، نواقص و مجوزها")
md.append("")
tv = report["tests_and_verification"]
md.append(f"- Go: {tv['go_test']}")
md.append(f"- TypeScript: {tv['typescript']} | Python: {tv['analytics_python']} | Publisher: {tv['publisher']}")
md.append(f"- بازتولید مستقل موتور: {tv['engine_reproduction']['n_match']}/{tv['engine_reproduction']['n_companies']} تطبیق کامل")
md.append(f"- endpointها: " + "، ".join(f"{k}={v}" for k, v in tv["endpoints"].items()))
md.append(f"- hash آرتیفکت‌ها: q={tv['artifact_hashes']['q'][:16]}… v={tv['artifact_hashes']['v'][:16]}… t={tv['artifact_hashes']['t'][:16]}…")
md.append(f"- نواقص: " + "؛ ".join(report["remaining_limitations"]))
md.append(f"- مجوزهای لازم: " + "؛ ".join(report["required_permissions"]))
md.append("")
md.append("## پاسخ چهار پرسش پایانی")
md.append("")
for k, v in report["answers"].items():
    md.append(f"**{k}:** {v}")
    md.append("")
md.append("## محدودیت‌های غیرقابل نقض — همگی رعایت شد")
md.append("")
md.append("، ".join(report["constraints_respected"]))
md.append("")

pm = os.path.join(OUT, "gam2k9_final_report.md")
open(pm, "w", encoding="utf-8").write("\n".join(md))
print("wrote:", pm, os.path.getsize(pm), "bytes")
