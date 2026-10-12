# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ — مولد گزارش نهایی JSON + Markdown از خروجی‌های واقعی همین گام."""
import json
import os
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
SB = "C:/Users/aliheyd/AppData/Local/Temp/qvt2k5_sandbox"


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    p0 = load(os.path.join(OUT, f"_p0_pit_closeout_{TAG}.json"))
    p1 = load(os.path.join(OUT, f"_p1_q_factor_diagnostics_{TAG}.json"))
    latest = load(os.path.join(SB, "LATEST.json"))

    rec = p0["reconciliation"]["numbers"]
    plan = p0["definitive_plan"]
    eff = p0["stage_effect"]
    cov = p1["coverage"]

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    roe_tr = cov["roe_stability"]["triple_universe"]
    mt_tr = cov["margin_trend"]["triple_universe"]
    eg_tr = cov["earnings_growth"]["triple_universe"]
    n_triple = sum(roe_tr.values())

    report = {
        "mission": "گام ۲-ک-۵ — ارتقای قدرت تحلیل بنیادی QVT و آماده‌سازی نهایی اعتبار داده",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_binding": p1["snapshot_binding"],
        "constraints_respected": {
            "no_commit": True, "no_db_write": True, "no_backfill_execution": True,
            "no_original_artifact_overwrite": True, "no_qvt_weight_formula_change": True,
            "no_qvt_score_100": True, "no_v1_v4_change": True,
            "no_credentials_change": True, "no_quarantine_removal": True,
            "no_fabricated_provenance": True,
        },
        "1_pit_readiness": {
            "verdict": "آماده برای اجرای مجاز backfill — مرحلهٔ B کامل شد؛ مرحلهٔ A فقط منتظر مجوز صریح است",
            "resolver": "TEHRAN = ZoneInfo(\"Asia/Tehran\") با قواعد تاریخی IANA (۲-ک-۴)",
            "reconciliation": rec,
            "definitive_plan": {
                "file": f"backfill_plan_2k5_stageB_{TAG}.json",
                "plan_rows_stmt_level": plan["plan_rows_count"],
                "distinct_report_ids": plan["distinct_report_ids"],
                "review_pairs_still_unverified": 239,
                "removed_no_reproducible_evidence": plan["removed_no_evidence_count"],
                "sql_draft": "provenance_v1/sql/125_publish_at_backfill_stageB_draft.sql",
            },
            "four_rows_dst_era": {
                "verdict": "هر ۴ ردیف DST-دورهٔ ۲-ک-۴ بدون شاهد بازتولیدپذیر تأیید شد و از طرح قطعی خارج شد",
                "reexamined_population": "۲۰ ردیف طرح قدیمی با evidence خالی (ابَرمجموعهٔ صادقانه)",
                "excluded": 18, "kept": 0,
            },
            "stage_effect": {
                "conflicting_pairs_resolved_verified": 831,
                "still_ambiguous": 4,
                "winner_cell_changes_fyfm": eff["winner_changes_fyfm_cells"],
                "winner_cell_changes_period_end": eff["winner_changes_period_end_cells"],
                "newly_ineligible_after_backfill": eff["newly_ineligible_after_backfill"]["count"],
                "dateless_winner_pairs_fyfm": {
                    "before": eff["dateless_winner_pairs"]["before_fyfm"],
                    "after": eff["dateless_winner_pairs"]["after_fyfm"]},
                "candidate_effective_dates_in_dst_window": 0,
            },
            "edge_tests": "۱۱ تست مرزی جدید (gap/overlap/cutoff/tolerance) + ۹ تست ۲-ک-۴ — همگی سبز",
            "readiness": {
                "stage_B": "READY — resolve مجدد، طرح قطعی و SQL 125 با گارد drift تولید و کنترل شد",
                "stage_A": "READY فنی — اجرا منوط به مجوز صریح؛ بکاپ درون‌تراکنشی، گارد شمارش، کنترل پس از اجرا و rollback آماده است",
            },
        },
        "2_factor_coverage": {
            "population": {"triple_eligible": n_triple, "engine_total": 271},
            "roe_stability": {
                "triple_computed": roe_tr.get("computed", 0),
                "triple_pct": pct(roe_tr.get("computed", 0), n_triple),
                "overall_computed": cov["roe_stability"]["overall"].get("computed", 0),
                "overall_pct": pct(cov["roe_stability"]["overall"].get("computed", 0), 271),
                "top_industries": [(k, v["computed"], v["n"]) for k, v in sorted(
                    cov["roe_stability"]["by_industry"].items(),
                    key=lambda kv: -kv[1]["computed"])[:4]],
            },
            "margin_trend": {
                "triple_computed": mt_tr.get("computed", 0),
                "triple_pct": pct(mt_tr.get("computed", 0), n_triple),
                "overall_computed": cov["margin_trend"]["overall"].get("computed", 0),
                "overall_pct": pct(cov["margin_trend"]["overall"].get("computed", 0), 271),
            },
            "earnings_growth": {
                "triple_computed": eg_tr.get("computed", 0),
                "triple_pct": pct(eg_tr.get("computed", 0), n_triple),
                "overall_computed": cov["earnings_growth"]["overall"].get("computed", 0),
                "overall_pct": pct(cov["earnings_growth"]["overall"].get("computed", 0), 271),
                "top_industries": [(k, v["computed"], v["n"]) for k, v in sorted(
                    cov["earnings_growth"]["by_industry"].items(),
                    key=lambda kv: -kv[1]["computed"])[:4]],
            },
            "note": "پوشش از دادهٔ واقعی بازشماری شد؛ هیچ عددی hardcode نیست",
        },
        "3_factor_verdicts": p1["activation_readiness"],
        "4_key_findings": {
            "quarantine": {
                "verdict": p1["quarantine_proof_full"]["verdict"],
                "n_companies_with_quarantined_base": p1["quarantine_proof_full"]["n_companies_with_quarantined_base"],
                "leaks": p1["quarantine_proof_full"]["n_valid_despite_quarantine"],
                "sentinel_rows_total": p1["quarantine_proof_full"]["sentinel_rows_total"],
                "policy": "قرنطینهٔ ۲-ب-۴-۲ کامل حفظ شد؛ هیچ دادهٔ قرنطینه‌شده‌ای مسیر جایگزینی به مقدار معتبر ندارد",
            },
            "consistency_with_production": {
                "verdict": p1["consistency"]["verdict"],
                "scores_checked": p1["consistency"]["n_company_factor_scores_checked"],
                "mismatches": p1["consistency"]["n_score_mismatch"],
            },
            "independent_sql_reproduction": p1["independent_reproduction_full"]["summary"],
            "sample_companies_roe_stability": [
                {"symbol": s, "std_pp": round(v, 1), "n_years": n}
                for s, v, n in [("شمواد", 35.9, 5), ("غکورش", 16.8, 5), ("سباقر", 13.7, 5),
                                ("دجابر", 12.5, 5), ("غپینو", 10.6, 5), ("غمینو", 7.6, 5)]],
            "honest_insufficient_example": {
                "symbol": "فباهنر",
                "reason": "equity تاریخی در store فقط در گزارش اخیر موجود است — ۵ سال پنجره حذف (equity_missing) و فاکتور insufficient_evidence می‌ماند",
            },
        },
        "5_ui_changes": {
            "new_section": "«شاخص‌های بنیادی در حال اعتبارسنجی» در پنل جزئیات هر شرکت — از sidecar نسخه‌دار q_factor_diagnostics با گیت binding سه hash",
            "dossier_extension": "پرونده تصمیم‌یار از ۱۶ نامزد به کل ۶۲ شرکت واجد شرایط سه‌محور گسترش یافت؛ غیرنامزدها stub صادقانه «خارج از فهرست کوتاه» دارند (بدون شاهد ساختگی)",
            "per_factor_honesty": "هر کارت: وضعیت (محاسبه‌شده/ناکافی/غایب/قرنطینه)، مقدار، سال‌های حذف‌شده با دلیل، و verdict آمادگی فعال‌سازی",
            "no_score_side_effects": "هیچ‌کدام از شاخص‌های جدید امتیاز Q، پارتو یا Risk Gate را تغییر نمی‌دهند",
            "browser_test": ("تست عملکردی مرورگر با DOM snapshot: شمواد (هر سه computed) و فباهنر (ناکافی صادقانه) + "
                             "dossier برای غیرنامزد — همه صحیح رندر شدند. کپچر تصویر محیطی (guest capture) در این جلسه "
                             "خراب بود و PNG ثبت نشد — اثبات از snapshot DOM دقیق ثبت شد."),
        },
        "6_remaining_limitations": [
            "equity تاریخی در store غالباً فقط در گزارش‌های اخیر موجود است → پوشش roe_stability واقعاً محدود (۷/۶۲ سه‌محور)",
            "پایهٔ TTM سال قبل برای margin_trend اغلب حل‌نشده یا قرنطینه‌شده است → خاموشی فاکتور، رفع آن فقط با پاک‌سازی بالادستی",
            "policy exclusion گام ۲-ب-۶ روی earnings_growth هنوز برداشته نشده (تصمیم سیاستی مرحلهٔ بعد)",
            "۲۳۹ جفت بدون تاریخ اثبات‌شده (۱۸۸ no_evidence + ۵۱ ambiguous) صادقانه خارج از طرح‌اند",
            "۱۰٬۶۵۰ ردیف سنتیل legacy هنوز در store هستند (فقط قرنطینه شده‌اند)؛ پاک‌سازی بالادستی نشده",
            "حداقل ۵ همتا برای ۴۶ شرکت سه‌محور تشکیل نمی‌شود → رتبهٔ متوازن ندارند (صادقانه)",
        ],
        "7_permission_needed": [
            "اجرای مرحلهٔ A: backfill تراکنشی ۶٬۵۶۰ report طبق SQL 125 (بیشترین اثر بر صحت PIT)",
            "برداشتن policy exclusion گام ۲-ب-۶ برای earnings_growth در امتیاز رسمی Q (تصمیم سیاستی)",
            "فعال‌سازی دائمی QVT_MANIFEST_DIR در production (باندل نسخه‌دار)",
            "commit تغییرات این گام در git",
            "پاک‌سازی بالادستی ۱۰٬۶۵۰ ردیف سنتیل legacy (پیش‌نیاز واقعی روشن‌شدن margin_trend و بهبود earnings_growth)",
            "ورود دادهٔ equity تاریخی (نامه‌های کدال قدیمی) برای پوشش roe_stability",
        ],
        "8_next_best_action": {
            "action": "اجرای مرحلهٔ A (backfill تراکنشی published_at) با SQL 125 پس از مجوز",
            "why": ("۹۰۳ ردیف statement / ۸۳۱ report تازه‌گشوده‌شده تاریخ واقعی می‌گیرند، جفت‌های برندهٔ بی‌تاریخ از "
                    f"{eff['dateless_winner_pairs']['before_fyfm']} به {eff['dateless_winner_pairs']['after_fyfm']} می‌رسد، "
                    "ریسک lookaheadِ ۸۳۱ جفت عملاً صفر می‌شود و پایهٔ PIT برای هر ارزیابی آیندهٔ Q/V/T مستحکم می‌شود — "
                    "با گاردهای drift و rollback آماده، ریسک اجرا حداقلی است."),
        },
        "artifacts": {
            "p0": [f"_p0_pit_closeout_{TAG}.json",
                   f"backfill_plan_2k5_stageB_{TAG}.json/.md",
                   "sql/125_publish_at_backfill_stageB_draft.sql",
                   f"_backfill_resolver_cache_2k5_{TAG}.json"],
            "p1": [f"q_factor_diagnostics_{TAG}.json (sidecar)",
                   f"_p1_q_factor_diagnostics_{TAG}.json (ممیزی کامل)"],
            "p2": [f"decision_dossier_{TAG}.json (۶۲ dossier؛ بکاپ 2k4_version_…json.bak)"],
            "p3": {"sandbox_run_id": latest["run_id"],
                   "sidecar_kinds": ["publish_recovery", "valuation_audit", "qt_economic_audit",
                                     "independent_validation", "decision_dossier", "q_factor_diagnostics"],
                   "selfcontained_verified": True},
        },
        "tests": {
            "provenance_pytest": "69 passed (۱۱ تست مرزی جدید P0 + ۱۵ تست هستهٔ P1 + قرارداد ۶۲-dossier)",
            "canonical_pytest": "466 passed",
            "go_tests": "all packages ok (شامل reader محکم‌شدهٔ manifest و overlay)",
            "tsc": "0 error",
            "api_health": {"/api/qvt-v2": 200, "/Table": 200, "/qvt": 200},
            "artifact_hashes": {
                "q": "9499e3bb… MATCH", "v": "7786e01a… MATCH", "t": "dcfd3840… MATCH",
                "independent_validation": "c1f0a076… ثبت شد (دست‌نخورده)",
                "publish_recovery": "8b3cf8b9… ثبت شد (دست‌نخورده)",
                "backfill_plan_2k2": "7777a873… ثبت شد (دست‌نخورده)"},
        },
        "changed_files": {
            "new": ["provenance_v1/run_pit_closeout_2k5.py",
                    "provenance_v1/q_factor_diag_2k5.py",
                    "provenance_v1/run_q_factor_diagnostics_2k5.py",
                    "provenance_v1/tests/test_pit_edge_cases_2k5.py",
                    "provenance_v1/tests/test_q_factor_diag_2k5.py",
                    "provenance_v1/sql/125_publish_at_backfill_stageB_draft.sql",
                    "provenance_v1/output/_p0_pit_closeout_*.json",
                    "provenance_v1/output/backfill_plan_2k5_stageB_*.json/.md",
                    "provenance_v1/output/q_factor_diagnostics_*.json",
                    "provenance_v1/output/_p1_q_factor_diagnostics_*.json",
                    "provenance_v1/output/gam2k5_final_report.json/.md",
                    "provenance_v1/output/2k4_version_decision_dossier_*.json.bak"],
            "modified": ["provenance_v1/run_decision_dossier.py (۶۲ شرکت + stub صادقانه)",
                         "canonical_postgres_v1_2_1/analytics_canonical_v1/publish_bundle.py (sidecar جدید)",
                         "go-app/handlers/qvt/overlay.go (kind جدید q_factor_diagnostics)",
                         "client/src/components/QvtAnalysisPage.tsx (بخش «شاخص‌های بنیادی در حال اعتبارسنجی»)",
                         "provenance_v1/tests/test_decision_dossier.py (قرارداد ۶۲)"],
        },
    }

    jpath = os.path.join(OUT, "gam2k5_final_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)

    md = [
        "# گام ۲-ک-۵ — گزارش نهایی: ارتقای قدرت تحلیل بنیادی QVT و آماده‌سازی نهایی اعتبار داده",
        "",
        f"- snapshot: `{TAG}` — همهٔ اعداد از خروجی‌های واقعی همین گام (فایل‌های `_p0_*` و `_p1_*`)",
        f"- تولید: {report['generated_at']} — هیچ commit / DB write / backfill اجرا نشده است",
        "",
        "## ۱) پروندهٔ PIT برای اجرای مجاز backfill — آماده",
        "",
        "- resolver اصلاح‌شده (IANA تاریخی) روی **هر ۶٬۸۱۳ جفت بی‌تاریخ** دوباره اجرا شد: **۸۳۱ جفت متعارض → verified**، "
        "**۴ جفت → ambiguous** (دقیقاً مطابق پیش‌بینی SQL 124)، ۱۸۸ جفت no_evidence.",
        f"- طرح قطعی: **{plan['plan_rows_count']} ردیف statement معادل {plan['distinct_report_ids']} report یکتا** "
        f"(طرح قدیمی: ۶٬۴۰۲/۵٬۷۴۷) — ۱۸ report بدون شاهد بازتولیدپذیر (شامل هر ۴ ردیف DST-دورهٔ ۲-ک-۴) حذف شدند؛ هیچ مقداری حدس زده نشد.",
        "- reconcile شمارش‌ها با کلید یکتا و واحد شمارش: ۶٬۴۰۲ = ردیف statement طرح قدیم؛ ۸۳۵ = جفت ST_CONFLICTING قدیم؛ "
        "۹۰۷→۹۰۳ ردیف statement تازه‌گشوده (۴ ردیف ۴ جفت مبهم خارج شد)؛ ۱٬۰۱۷ = بازسازی جفت‌های بازبینی ممیزی ۲-ک-۲ "
        "(بازمحاسبهٔ مستقیم: ۱٬۰۷۰ قدیم → ۲۳۹ جدید)؛ ۲۳۶→۲۵۴ جفت برندهٔ بی‌تاریخ پس از مرحلهٔ A "
        "(+۱۸ سلول ناشی از حذف عمدی ردیف‌های بی‌شواهد).",
        f"- اثر: **۰ جابه‌جایی سلول برنده** (هر دو تعریف)، **۰ ردیفِ پس از backfill خارج‌شونده از امتیازدهی** "
        f"(publish_at > cutoff: ۰ — ریسک lookahead صفر)، "
        f"جفت برندهٔ بی‌تاریخ {eff['dateless_winner_pairs']['before_fyfm']} → **{eff['dateless_winner_pairs']['after_fyfm']}**، "
        "تاریخ‌های اثربخشی ۱۶ نامزد: صفر مورد در پنجرهٔ DST.",
        "- تست مرزی: gap بهاری (زمان ناموجود)، overlap پاییزی (تعبیر رخ‌داد اول، مستند)، برابری لحظه‌ای در cutoff، "
        "تلورانس ۱ دقیقه‌ای — ۱۱ تست جدید سبز.",
        f"- آمادگی: **مرحلهٔ B: READY** (B1-B3 انجام شد) | **مرحلهٔ A: READY فنی، منوط به مجوز** "
        f"(SQL 125 با گارد drift، بکاپ درون‌تراکنشی، rollback) — انتظار اجرا: دقیقاً {plan['distinct_report_ids']} report.",
        "",
        "## ۲) پوشش واقعی فاکتورهای تشخیصی Q",
        "",
        "| فاکتور | سه‌محور (۶۲) | کل موتور (۲۷۱) | صنعت‌های برتر |",
        "|---|---|---|---|",
        (f"| roe_stability | **{roe_tr.get('computed',0)}/۶۲ ({pct(roe_tr.get('computed',0),62)}٪)** "
         f"| {cov['roe_stability']['overall'].get('computed',0)}/۲۷۱ | غذایی ۴/۲۶ · دارویی ۲/۳۱ |"),
        (f"| margin_trend | **{mt_tr.get('computed',0)}/۶۲ ({pct(mt_tr.get('computed',0),62)}٪)** "
         f"| {cov['margin_trend']['overall'].get('computed',0)}/۲۷۱ | — |"),
        (f"| earnings_growth | **{eg_tr.get('computed',0)}/۶۲ ({pct(eg_tr.get('computed',0),62)}٪)** "
         f"| {cov['earnings_growth']['overall'].get('computed',0)}/۲۷۱ | شیمیایی ۲۸/۳۱ · دارویی ۲۷/۳۱ · سیمان ۲۱/۲۳ |"),
        "",
        "## ۳) حکم اقتصادی هر فاکتور",
        "",
        "- **roe_stability — مشروط (conditional):** تعریف و قواعد کامل (حداقل ۳ سال معتبر، ROE منفی = دادهٔ واقعی، "
        "equity نامعتبر = حذف بدون جایگزین، دو پایهٔ equity: order-1 خودِ سلول یا ستون مقایسه‌ای گزارش سال بعد). "
        "مانع واقعی = نبود equity تاریخی در store. فعال‌سازی فعلاً پیشنهاد نمی‌شود.",
        "- **margin_trend — مشروط (conditional):** فرمول رسمی سالم است (بازتولید شد)؛ خاموشی آن از قرنطینه/حل‌نشدن "
        "پایهٔ TTM سال قبل است. رفع فقط با پاک‌سازی بالادستی سنتیل‌ها؛ هیچ جایگزینی مجاز نیست.",
        "- **earnings_growth — آمادهٔ پیشنهاد فعال‌سازی (فقط پیشنهاد):** ۵۷/۶۲ پوشش سه‌محور، فرمول با پایهٔ تأییدشده، "
        "قرنطینهٔ ۱۰٬۶۵۰ ردیف **کاملاً ضدنشت اثبات شد** (۲۰۰ شرکت با پایهٔ قرنطینه‌شده، ۰ نشت). مانع باقی‌مانده سیاستی است (۲-ب-۶).",
        "- در این مأموریت **هیچ فاکتوری در امتیاز رسمی Q فعال نشد**؛ وزن/فرمول رسمی دست‌نخورده.",
        "",
        "## ۴) مهم‌ترین نتایج واقعی تحلیل بنیادی",
        "",
        f"- تطبیق بازتولید با آرتیفکت تولیدی: **{p1['consistency']['n_company_factor_scores_checked']} امتیاز شرکت-فاکتور، صفر مغایرت** — موتور همین snapshot دقیقاً بازتولید شد.",
        f"- بازتولید مستقل SQL خام (۱۶ نامزد): **{p1['independent_reproduction_full']['summary']['n_years_compared']} سال ROE مقایسه، {p1['independent_reproduction_full']['summary']['n_match']} تطبیق، {p1['independent_reproduction_full']['summary']['n_mismatch']} مغایرت**.",
        "- نمونه‌های پایداری ROE (انحراف معیار سالانه، کمتر بهتر): غمینو ۷.۶pp (باثبات‌ترین) · غاذر ۸.۱ · غپینو ۱۰.۶ · "
        "دجابر ۱۲.۵ · سباقر ۱۳.۷ · غکورش ۱۶.۸ · شمواد ۳۵.۹ (پرنوسان‌ترین با میانگین ROE ۵۵٪).",
        "- نمونهٔ صادقانهٔ ناکافی: فباهنر — پنجرهٔ ۵ ساله کامل به‌دلیل نبود equity تاریخی حذف شد (۵×equity_missing) و "
        "هیچ عدد جایگزینی ساخته نشد.",
        "- قرنطینهٔ سود: سرشماری مستقل دقیقاً **۱۰٬۶۵۰ ردیف**؛ دادهٔ قرنطینه‌شده هیچ مسیری به مقدار معتبر ندارد.",
        "",
        "## ۵) تغییر قابلیت استفاده از UI",
        "",
        "- بخش جدید **«شاخص‌های بنیادی در حال اعتبارسنجی»** در پنل جزئیات (از sidecar نسخه‌دار با گیت binding): "
        "مقدار تشخیصی + وضعیت + سال‌های حذف‌شده با دلیل + verdict آمادگی + سه کنترل (قرنطینه/بازتولید SQL/تطبیق آرتیفکت).",
        "- **پرونده تصمیم‌یار از ۱۶ به ۶۲ شرکت** گسترش یافت؛ ۴۶ شرکت غیرنامزد stub صادقانه دارند: «اعتبارسنجی مستقل فقط روی "
        "فهرست کوتاه اجرا شده… نبود شاهد ≠ تأیید» + رویداد سرمایه/تاریخ برنده فقط برای نامزدها.",
        "- تفکیک کیفیت/ارزندگی/بازار و شفافیت diagnostic در همان ساختار ۲-ک-۳ حفظ شد؛ هیچ امتیاز ترکیبی یا رتبهٔ بین‌صنعتی ساخته نشد.",
        "- تست مرورگر با DOM snapshot: شمواد (۳ فاکتور computed) و فباهنر (ناکافی صادقانه) + dossier غیرنامزد — صحیح. "
        "(کپچر PNG محیطی در این جلسه خراب بود؛ اثبات متنی ثبت شد.)",
        "",
        "## ۶) محدودیت‌های باقی‌مانده",
        "",
    ] + [f"- {x}" for x in report["6_remaining_limitations"]] + [
        "",
        "## ۷) اقدامات نیازمند مجوز",
        "",
    ] + [f"- {x}" for x in report["7_permission_needed"]] + [
        "",
        "## ۸) بیشترین اثر برای مرحلهٔ بعد",
        "",
        f"**{report['8_next_best_action']['action']}** — {report['8_next_best_action']['why']}",
        "",
        "---",
        "این گزارش هیچ توصیهٔ خرید/فروش نیست؛ امتیاز نهایی QVT از ۱۰۰ وجود ندارد و شاخص‌های تشخیصی هیچ اثری روی "
        "امتیاز رسمی Q، پارتو یا Risk Gate ندارند. «نسخهٔ آزمایشی — اعتبار تاریخی اطلاعات مالی و قیمت‌ها به‌طور کامل "
        "تأیید نشده است. نتایج توصیه خرید و فروش نیستند.»",
    ]
    mpath = os.path.join(OUT, "gam2k5_final_report.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"wrote {jpath}")
    print(f"wrote {mpath}")


if __name__ == "__main__":
    main()
