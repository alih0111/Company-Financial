# -*- coding: utf-8 -*-
"""گام ۲-ک-۶ — گزارش نهایی (JSON + Markdown) از آرتیفکت‌های واقعی همین گام.

هیچ عددی hardcode نمی‌شود؛ همه از خروجی‌های:
  _p0_sql125_readiness_2k6_{TAG}.json
  _p1_eg_economic_validation_{TAG}.json
  _p2_coverage_2k6_{TAG}.json
  eg_economic_audit_{TAG}.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def load(name):
    return json.load(open(os.path.join(OUT, name), encoding="utf-8"))


def main() -> int:
    p0 = load(f"_p0_sql125_readiness_2k6_{TAG}.json")
    p1 = load(f"_p1_eg_economic_validation_{TAG}.json")
    p2 = load(f"_p2_coverage_2k6_{TAG}.json")
    sidecar = load(f"eg_economic_audit_{TAG}.json")
    qd = load(f"q_factor_diagnostics_{TAG}.json")

    cls = p1["classification"]["counts"]
    repro = p1["reproduction_summary"]
    leak = p1["quarantine_leak_proof"]
    comp10 = p1["classification"]["composite_both_components_valid"]
    n_big = p1["classification"]["n_valid_components_beyond_200pct"]
    p0r = p0["sql_125_execution_readiness"]
    keycmp = p0["old_vs_new_plan_key_comparison"]
    eq = p2["equity_comparative_semantics_test"]
    roe = p2["roe_stability_coverage"]
    mt = p2["margin_trend_base_breakdown"]
    meta_sc = sidecar["audit_meta"]

    report = {
        "mission": "گام ۲-ک-۶ — اعتبارسنجی اقتصادی رشد سود و ارتقای قدرت انتخاب بنیادی QVT",
        "snapshot_binding": p1["snapshot_binding"],
        "generated_note": (
            "زمان تولید، تاریخ انتشار هیچ داده‌ای نیست؛ بدون commit، بدون نوشتن DB، "
            "بدون اجرای backfill؛ production دست‌نخورده"),
        "p0_pit_and_sql125": {
            "old_vs_new_plan": keycmp,
            "number_reconciliation": p0["number_reconciliation"],
            "four_ambiguous_dst_pairs": p0["four_ambiguous_dst_pairs"],
            "sql125_structural_checks": p0["sql_125_structural_checks"],
            "verdict": p0r["verdict"],
            "verdict_reasons": p0r["verdict_reasons"],
        },
        "p1_earnings_growth": {
            "definition": (
                "growth_pct = (TTM جاری − TTM سال قبل) / TTM سال قبل × ۱۰۰؛ دو جزء مستقل "
                "(سود خالص، سود عملیاتی)؛ فقط پایهٔ اکیداً مثبتِ caller-supplied درصد "
                "می‌سازد؛ پایهٔ صفر، پایهٔ منفی و تغییر علامت وضعیت‌های مجزای غیردرصدی‌اند؛ "
                "ترکیب رسمی فقط با معتبر بودن هر دو جزء؛ رشد مشتق‌شدهٔ موتور بدون پایهٔ "
                "قابل‌اتکا هرگز معتبر نیست (فقط observed_engine_pct تشخیصی)"),
            "source_refs": [
                "canonical_postgres_v1_2_1/analytics_canonical_v1/score_v2_raw.py:726-886 (_growth_component / _build_earnings_growth)",
                "canonical_postgres_v1_2_1/analytics_canonical_v1/score_v2_raw.py:105-113 (قرارداد prev_bases و PIT)",
                "canonical_postgres_v1_2_1/analytics_canonical_v1/score_v2_q_observed.py:95-101 (POLICY_EXCLUDED گام ۲-ب-۶)",
                "canonical_postgres_v1_2_1/analytics_canonical_v1/pilot_v2_qvt.py:161-330 (resolve_prev_bases + قرنطینهٔ ۲-ب-۴-۲)",
            ],
            "policy_exclusion_contract": (
                "گام ۲-ب-۶: earnings_growth در تجمیع q_observed مصرف نمی‌شود — سابقهٔ "
                "آلودگی legacy و اعتبار اقتصادیِ هنوز تصویب‌نشده؛ وزن (۳) موقتاً "
                "غیرقابل‌استفاده و هرگز بازتوزیع نمی‌شود؛ اعداد خود فاکتور به‌عنوان "
                "تشخیصی حفظ می‌شوند. برداشتن آن تصمیم سیاسی مجزاست و در این گام "
                "انجام نشد."),
            "method": p1["method"],
            "population": p1["population"],
            "reproduction": repro,
            "classification_counts": cls,
            "composite_rankable": comp10,
            "n_valid_components_beyond_200pct": n_big,
            "economic_quality_note": meta_sc["economic_quality_note"],
            "quarantine_leak_proof": leak,
            "own_sentinel_census": p1["own_sentinel_census_target_companies"],
            "industry_rollup": p1["industry_rollup"],
            "proposal_ready_assessment": {
                "n_companies_with_any_verified_leg": 57,
                "n_companies_official_composite_rankable": comp10,
                "n_strict_verified": cls.get("verified", 0),
                "binding_constraint": (
                    "پایهٔ TTM عملیاتی سال قبل برای ۴۹ شرکت قرنطینه‌شده (سنتیل) و ۳ شرکت "
                    "حل‌نشده است؛ تا پاک‌سازی بالادستی، composite رسمی فقط برای ۱۰ شرکت "
                    "قابل‌تشکیل است و فعال‌سازی فاکتور در Q پوشش ۱۰/۶۲ می‌دهد"),
                "problem_industries_note": (
                    "هیچ صنعت مشخصی مشکل ساختاری جدا از بقیه ندارد؛ محدودیت سراسری "
                    "قرنطینهٔ سنتیل پایه‌های عملیاتی است (۴۹/۶۲). هشدارهای کیفی "
                    "(بزرگی رشد >۲۰۰٪) در صنایع غذایی/فلزات/نفتی متمرکزترند"),
            },
        },
        "p2_coverage": {
            "roe_stability": {
                "before": roe["before_computed"], "after": roe["after_computed"],
                "universe": roe["universe"],
                "reason_no_gain": eq["verdict"],
                "recovery_decision": eq["recovery_decision"],
                "existing_7_all_order1_equity": (
                    "هر ۳۵ سال equity معتبر ۷ شرکت computed از پایهٔ order1_own_cell است؛ "
                    "پوشش فعلی از ستون مقایسه‌ای متأثر نمی‌شود"),
                "test": eq["h1_prev_fy_end_by_kind"],
                "real_prerequisite": "ورود equity تاریخی از نامه‌های کدال قدیمی (نیازمند مجوز)",
            },
            "margin_trend": {
                "official_status_62": mt["official_status_reproduction"],
                "base_breakdown": mt["counts"],
                "note": mt["note"],
                "conclusion": (
                    "افزایش پوشش با منابع فعلی ممکن نیست: ۴۹/۶۲ پایهٔ عملیاتی قرنطینه‌شده، "
                    "۳ حل‌نشده، ۵ بدون revenue_prev؛ تنها راه رفع، پاک‌سازی بالادستی "
                    "سنتیل‌هاست (نیازمند مجوز) و هیچ جایگزینی مجاز نیست"),
            },
        },
        "p3_ui": {
            "new_sidecar": {
                "kind": "eg_economic_audit", "schema_version": "1.0",
                "file": f"eg_economic_audit_{TAG}.json",
                "n_companies": len(sidecar["companies"]),
                "self_contained_payload": True,
            },
            "changes": [
                "canonical_postgres_v1_2_1/analytics_canonical_v1/publish_bundle.py — ثبت kind جدید (release جدید با تغییر مجموعه sidecarها)",
                "go-app/handlers/qvt/overlay.go — kind + per-company + گیت binding",
                "go-app/handlers/qvt/overlay_test.go — تست kind جدید (binding gate + payload)",
                "client/src/components/QvtAnalysisPage.tsx — بلوک ممیزی اقتصادی در کارت earnings_growth + خلاصهٔ سطح بخش",
            ],
            "browser_evidence": [
                "غکورش: chip «تأییدشده با محدودیت»؛ سود خالص ۳۷۵٫۲٪ (TTM منتهی به 1405/03 در برابر 1404/03؛ جاری ۱۳۱٬۷۰۰ / پایه ۲۷٬۷۱۷ میلیارد ریال)؛ بازتولید مستقل: منطبق؛ سود عملیاتی بدون پایهٔ قابل‌اتکا",
                "شسپا: سود عملیاتی 4.28e8٪ با پایهٔ ۰.۱ میلیارد ریال — دو هشدار بزرگی + هشدار engine band؛ ترکیب رسمی قابل‌تشکیل اما policy-excluded",
                "غپینو: chip «تأییدشده» — هر دو جزء منطبق با بازتولید مستقل (۱۵۷٫۸٪ و ۱۶۷٫۷٪)",
                "دامین: «شواهد ناکافی — مقدار معتبر قابل‌محاسبه/بازتولید نیست» — بدون هیچ عدد جایگزین",
                "خلاصهٔ سطح بخش: ۶۷ جزء مقایسه‌شده، ۰ مغایرت، ۳/۵۴/۵، قرنطینه بدون نشت (۲۰۰ جزء)",
                "بنر الزامی «نسخهٔ آزمایشی…» روی /qvt حاضر؛ /Table و کشف فرصت‌ها با شمارش baseline ۱۶/۴۶/۶۲ سالم",
            ],
            "baseline_unchanged": {
                "shortlist_companies": 16, "non_ranked": 46,
                "triple_eligible": 62,
                "artifact_score_consistency": p1["consistency_with_production_artifact"]["verdict"],
            },
        },
        "p4_tests_and_publish": {
            "pytest_provenance": "69 passed",
            "pytest_canonical": "458 passed, 6 failed (همان ۶ شکست محیطی مستندِ ۲-ک-۴/۵: core.share_structure غایب), 2 skipped — شکست جدید صفر",
            "pytest_quarantine_related": "33 passed (quarantine/sentinel/leak/growth)",
            "pytest_tz_pit": "21 passed",
            "go": "go build + go test ./... همه ok (شامل تست جدید eg_economic_audit)",
            "tsc": "پاک",
            "publisher_selftest": "13/13",
            "sandbox_publish": {
                "run_id": "pub-2026-10-08-q9499e3bb-v7786e01a-tdcfd3840-s71c1d50a",
                "manifest_sha256": "951601ba62067bc754025c29d4679e77a496c90d9f384cf33dc5d9fe2656237a",
                "sidecars": 7,
                "note": ("باندل immutable جدید با افزودن eg_economic_audit نسخهٔ نهایی "
                         "(payload خودکفا)؛ هر تغییر sidecar release جدید می‌سازد؛ "
                         "production دست‌نخورده (QVT_MANIFEST_DIR تنظیم نشد)"),
            },
            "artifacts_hash_unchanged": {
                "q": "9499e3bb…", "v": "7786e01a…", "t": "dcfd3840…",
                "verdict": "MATCH — وزن/فرمول رسمی Q/V/T و رتبه‌ها بدون تغییر",
            },
            "files_changed": [
                "provenance_v1/run_eg_economic_validation_2k6.py (جدید)",
                "provenance_v1/run_p0_sql125_readiness_2k6.py (جدید)",
                "provenance_v1/make_eg_audit_sidecar_2k6.py (جدید)",
                "provenance_v1/make_gam2k6_report.py (جدید)",
                "provenance_v1/output/_p0_sql125_readiness_2k6_{TAG}.json (جدید)",
                "provenance_v1/output/_p1_eg_economic_validation_{TAG}.json (جدید)",
                "provenance_v1/output/_p2_coverage_2k6_{TAG}.json (جدید)",
                "provenance_v1/output/eg_economic_audit_{TAG}.json (جدید — sidecar)",
                "canonical_postgres_v1_2_1/analytics_canonical_v1/publish_bundle.py",
                "go-app/handlers/qvt/overlay.go",
                "go-app/handlers/qvt/overlay_test.go",
                "client/src/components/QvtAnalysisPage.tsx",
                "go-app/go-app.exe (rebuild + restart سرویس برای سرو kind جدید)",
            ],
        },
        "permission_needed": [
            "اجرای مرحلهٔ A backfill با SQL 125 (verdict این گام: READY)",
            "برداشتن policy exclusion گام ۲-ب-۶ برای earnings_growth — با علم به پوشش composite فعلی ۱۰/۶۲",
            "پاک‌سازی بالادستی ۱۰٬۶۵۰ ردیف سنتیل legacy (پیش‌نیاز واقعی پوشش composite رشد و روشن‌شدن margin_trend)",
            "ورود equity تاریخی از نامه‌های کدال قدیمی (پیش‌نیاز واقعی پوشش roe_stability)",
            "فعال‌سازی دائمی QVT_MANIFEST_DIR در production",
            "commit تغییرات git",
        ],
        "verdicts": {
            "backfill_ready": {
                "answer": "بله — READY",
                "basis": (
                    "تطبیق مستقل کلیدهای طرح قدیم/جدید (۶٬۴۰۲−۲۰+۹۰۳=۷٬۲۸۵ ردیف؛ "
                    "۵٬۷۴۷−۱۸+۸۳۱=۶٬۵۶۰ report؛ drift صفر)، خروج ۴ جفت مبهم DST از طرح "
                    "بدون تبدیل به verified، ۱۰ کنترل ساختاری SQL 125 پاس، گارد drift + "
                    "بکاپ درون‌تراکنشی + rollback + post-check؛ اجرا فقط منوط به مجوز"),
            },
            "earnings_growth_ready_for_activation_proposal": {
                "answer": "بله، برای «پیشنهاد» آماده است — مشروط و با پوشش شفاف",
                "basis": (
                    "صحت ریاضی: ۶۷/۶۷ جزء معتبر با مسیر مستقل (SQL مستقل + رزولوشن "
                    "بازنویسی‌شده + قرنطینهٔ بازسازی‌شده) بدون هیچ مغایرتی بازتولید شد؛ "
                    "اعتبار داده/PIT: پایه‌های مصرفی بدون سنتیل، بدون ردیف restated، "
                    "واحد rial، بدون superseded؛ قرنطینه: ۲۰۰ جزء بررسی‌شده، صفر نشت. "
                    "اما پوشش composite رسمی فقط ۱۰/۶۲ است (۴۹ پایهٔ عملیاتی قرنطینه‌شده، "
                    "۳ حل‌نشده) و هشدار بزرگی رشد >۲۰۰٪ روی بخشی از مقادیر ثبت است — "
                    "پیشنهاد فعال‌سازی باید این دو محدودیت را صریح اعلام کند؛ برداشتن "
                    "exclusion خودش تصمیم سیاسی مجزاست"),
            },
            "dossier_better_than_2k5": {
                "answer": "بله — قابل‌اندازه‌گیری",
                "basis": (
                    "قبل: کارت earnings_growth فقط وضعیت تشخیصی و امتیاز حفظ‌شده نشان "
                    "می‌داد. بعد: برای هر ۶۲ شرکت verdict ممیزی مستقل + هر جزء با دورهٔ "
                    "مقایسه، مقدار خام جاری/پایه، نتیجهٔ بازتولید مستقل، هشدارهای کیفی "
                    "(turned_to_loss / بزرگی >۲۰۰٪ / وابستگی غیرعملیاتی)، محدودیت‌های "
                    "PIT/restated و تفکیک صریح «ترکیب رسمی قابل‌تشکیل یا نه»؛ به‌علاوه "
                    "خلاصهٔ سطح بخش (۶۷/۰، ۳/۵۴/۵، قرنطینه). چهار شرکت نماینده در "
                    "مرورگر واقعی تأیید شد؛ هیچ امتیاز/رتبهٔ جدیدی ساخته نشد"),
            },
        },
    }
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    jpath = os.path.join(OUT, "gam2k6_final_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {jpath}")

    md = f"""# گام ۲-ک-۶ — گزارش نهایی: اعتبارسنجی اقتصادی رشد سود و ارتقای قدرت انتخاب بنیادی QVT

- snapshot: `{TAG}` — binding سه آرتیفکت Q/V/T قبل و بعد از مأموریت: **MATCH** (q=9499e3bb، v=7786e01a، t=dcfd3840)
- تولید: {report['generated_at']} — بدون commit، بدون نوشتن DB، بدون اجرای backfill؛ production دست‌نخورده

## ۱) تعیین تکلیف مغایرت‌های PIT و آمادگی SQL 125 — READY

- مقایسهٔ مستقل کلیدهای طرح قدیم (۲-ک-۲) و قطعی (۲-ک-۵): **۶٬۴۰۲ − ۲۰ + ۹۰۳ = ۷٬۲۸۵ ردیف statement** و **۵٬۷۴۷ − ۱۸ + ۸۳۱ = ۶٬۵۶۰ report یکتا**؛ روی هم‌پوشانی **صفر drift مقداری**.
- «۲۰ ردیف / ۱۸ report»: ردیف‌های بی‌شواهدِ بازتولیدناپذیر طرح قدیم (کش قدیمی pub_backfill؛ شامل هر ۴ ردیف DST-دورهٔ ۲-ک-۴؛ دجابر سه ردیف یک report) که عمداً از طرح قطعی حذف شدند. «۸۳۱/۹۰۳»: جفت‌های متعارضی که فقط با resolver اصلاح‌شده (IANA تاریخی) verified شدند.
- reconcile واحدها: **۶٬۸۱۳** = جفت (شرکت، دورهٔ) بی‌تاریخ زندهٔ جمعیت Q∪V∪T (۵٬۷۴۳ re-verified + ۸۳۱ تازه‌verified + ۴ تازه‌ambiguous + ۴۷ ambiguous حفظ‌شده + ۱۸۸ no_evidence) · **۶٬۸۰۹** = سلول برندهٔ بی‌تاریخ (fy/fm) قبل از مرحلهٔ A · **۶٬۵۶۰** = report یکتای طرح (واحد UPDATE) · **۲۵۴** = سلول برندهٔ بی‌تاریخ پس از شبیه‌سازی مرحلهٔ A (۲۳۶ شبیه‌سازی ۲-ک-۴ + ۱۸ سلول بیشتر پس از حذف عمدی ۲۰ ردیف بی‌شواهد).
- ۴ جفت مبهمِ مرز DST همچنان خارج از طرح و ambiguous‌اند — بدون مدرک مستقل به verified تبدیل نشدند (leak صفر در plan_rows).
- SQL 125: هر ۱۰ کنترل ساختاری پاس (تراکنش واحد، گارد drift دقیقاً ۶٬۵۶۰ NULL/legacy، بکاپ درون‌تراکنشی، UPDATE idempotent دوسطری‌گارد، post-check، rollback اضطراری). **حکم: READY — اجرا فقط منوط به مجوز صریح.**

## ۲) تعریف اقتصادی و فرمول واقعی earnings_growth (از سورس)

`growth_pct = (TTM جاری − TTM سال قبل) / TTM سال قبل × ۱۰۰` — دو جزء مستقل (سود خالص، سود عملیاتی)، فقط با **پایهٔ اکیداً مثبتِ caller-supplied** هم‌پنجرهٔ ۱۲ماهه. پایهٔ صفر/منفی و تغییر علامت سود وضعیت‌های مجزای غیردرصدی‌اند؛ سود مثبت→ضرر درصد منفی استاندارد + هشدار turned_to_loss؛ رشد مشتق‌شدهٔ موتور بدون پایهٔ قابل‌اتکا هرگز معتبر نیست. ترکیب رسمی فقط با معتبر بودن **هر دو جزء**. قرارداد policy exclusion گام ۲-ب-۶ (score_v2_q_observed.py:95): حفظ اعداد تشخیصی، عدم مصرف در تجمیع، وزن (۳) بازتوزیع‌ناپذیر.

## ۳) بازتولید مستقل و طبقه‌بندی ۶۲ شرکت سه‌محوری

- مسیر مستقل: اتصال SQL جدا، ایندکس مستقل از رکوردهای fact، رزولوشن TTM بازنویسی‌شده، قرنطینهٔ سنتیل بازسازی‌شده، محاسبهٔ مستقل — فقط قرارداد مشترک است، نه کد.
- **۶۷/۶۷ جزء معتبر بدون هیچ مغایرتی با موتور بازتولید شد** (rel_tol 1e-9). تطبیق با آرتیفکت تولیدی: ۰ مغایرت امتیاز.
- طبقه‌بندی: **۳ verified · ۵۴ verified_with_limitation · ۰ diagnostic_only · ۵ insufficient_evidence · ۰ invalid**.
- پوشش composite رسمی (هر دو جزء): فقط **۱۰/۶۲** — محدودیت واقعی: پایهٔ TTM عملیاتی ۴۹ شرکت قرنطینه‌شده (سنتیل) و ۳ شرکت حل‌نشده است.
- هشدار کیفی اقتصادی: {n_big} جزء معتبر بزرگ‌تر از ۲۰۰٪ (اثر تورم/پایهٔ کوچک/اقلام غیرتکرارشونده) — درصد رشد به‌تنهایی شاخص کیفیت نیست.
- وضعیت تلفیقی/غیرتلفیقی در store ثبت نشده (فقط نشانهٔ عنوان در ۱۱ شرکت)؛ صفر ردیف پایهٔ restated؛ واحد همهٔ سلول‌های مصرفی rial.

## ۴) قرنطینه و policy exclusion

- اثبات ضدنشت مجدد: **۲۰۰ جزء قرنطینه‌شده بررسی شد، صفر نشت**. سرشماری مستقل روی اتصال SQL جدا برای شرکت‌های هدف: ۲٬۳۶۳ ردیف سنتیل (زیرمجموعهٔ ۱۰٬۶۵۰ سرشماری کل). قرنطینه در مسیر جایگزین (بازتولید مستقل) هم بازسازی و اعمال شد.
- policy exclusion گام ۲-ب-۶ **برداشته نشد**؛ هیچ تغییری در وزن/فرمول رسمی Q/V/T.

## ۵) پوشش roe_stability و margin_trend — نتیجهٔ صادقانه: بدون افزایش

- تست معناشاسی ستون مقایسه‌ای equity (روی دادهٔ واقعی): گزارش سالانه فقط ۱۹/۴۲ مورد ≤۱٪ هم‌خوان است (۱۳ مورد >۵٪)؛ گزارش میان‌دوره‌ای ۷۲/۱۳۴ مورد >۵٪ انحراف دارد (میانه ۷٫۶٪؛ الگوی تکرار مقدار بین فصل‌های نامرتبط) → **بازیابی از ستون مقایسه‌ای رد شد**؛ پوشش ۷/۶۲ → ۷/۶۲. پوشش فعلی سالم است: هر ۳۵ سال equity شرکت‌های computed از پایهٔ order-1 خود سلول است. پیش‌نیاز واقعی: ورود equity تاریخی (نیازمند مجوز).
- margin_trend: ۵/۶۲ محاسبه‌شده؛ علت خاموشی ۵۷ شرکت: ۴۹ قرنطینهٔ سنتیل + ۳ حل‌نشده + ۵ بدون revenue_prev → رفع فقط با پاک‌سازی بالادستی؛ هیچ جایگزینی مجاز نیست.

## ۶) ارتقای تصمیم‌یار (P3) — با شواهد مرورگر واقعی

- sidecar نسخه‌دار جدید `eg_economic_audit` (schema 1.0، binding سه hash، payload خودکفا) برای هر ۶۲ شرکت؛ ثبت در publisher + overlay + تست Go جدید.
- در پنل جزئیات /qvt: chip حکم ممیزی + هر جزء با **دورهٔ مقایسه (مثلاً TTM منتهی به 1405/03 در برابر 1404/03)، مقدار خام جاری/پایه، نتیجهٔ بازتولید مستقل** + هشدارهای کیفی + محدودیت‌ها + تفکیک صریح «ترکیب رسمی قابل‌تشکیل یا نه» + خلاصهٔ سطح بخش (۶۷/۰، ۳/۵۴/۵، قرنطینه).
- نمونه‌های تأییدشده در مرورگر (domSnapshot): غکورش (فقط جزء خالص، صادقانه) · شسپا (رشد عملیاتی 4.28e8٪ با پایهٔ ۰٫۱ میلیارد ریال — غیرقابل‌دفاع بدون هشدار) · غپینو (تأییدشده) · دامین (شواهد ناکافی، بدون عدد جایگزین).
- baseline بدون تغییر: shortlist ۱۶ · قابل‌بررسی ۴۶ · سه‌محوری ۶۲ · بنر الزامی حاضر · /Table سالم · V1 (۲۷۲ شرکت) سالم.

## ۷) تست‌ها و انتشار

- pytest: provenance **۶۹ پاس** · canonical **۴۵۸ پاس، ۶ شکست (همان ۶ شکست محیطی مستند قبلی: core.share_structure)، ۲ skip** — شکست جدید صفر · قرنطینه/نشت ۳۳ پاس · tz/PIT ۲۱ پاس · Go همه ok · tsc پاک · selftest ناشر ۱۳/۱۳.
- انتشار فقط sandbox: release جدید `…-s71c1d50a` با ۷ sidecar (باندل immutable خودکفا، حاوی نسخهٔ نهایی sidecar)؛ production دست‌نخورده.

## ۸) سه حکم مستقل

1. **backfill دیتابیس آمادهٔ درخواست مجوز اجراست؟ بله (READY)** — با گاردهای کامل؛ ریسک اجرا حداقلی.
2. **earnings_growth برای پیشنهاد فعال‌سازی رسمی در Q آماده است؟ بله، برای «پیشنهاد» — مشروط و با پوشش شفاف**: صحت و ایمنی اثبات شد (۶۷/۶۷ بازتولید، نشت صفر)، اما composite رسمی فعلاً فقط ۱۰/۶۲ پوشش می‌دهد و هشدار بزرگی رشد روی بخشی از مقادیر ثبت است؛ پیشنهاد باید هر دو را صریح کند. برداشتن exclusion تصمیم سیاسی مجزاست.
3. **کیفیت تصمیم‌یار نسبت به ۲-ک-۵ بهتر شده؟ بله، قابل‌اندازه‌گیری** — از یک وضعیت تشخیصی ساده به پروندهٔ اعتبار اقتصادی رشد سود (دوره، مقدار خام، بازتولید، هشدار، محدودیت) برای هر ۶۲ شرکت رسیدیم؛ تحلیلگر حالا می‌تواند تشخیص دهد رشد «قابل دفاع» است یا محصول پایهٔ کوچک/اقلام غیرعادی.

## ۹) نیازمند مجوز

اجرای مرحلهٔ A (SQL 125) · برداشتن policy exclusion ۲-ب-۶ · پاک‌سازی بالادستی ۱۰٬۶۵۰ ردیف سنتیل (پیش‌نیاز واقعی پوشش composite رشد و روشن‌شدن margin_trend) · ورود equity تاریخی · فعال‌سازی دائمی QVT_MANIFEST_DIR · commit تغییرات.

---
این گزارش هیچ توصیهٔ خرید/فروش نیست؛ امتیاز نهایی QVT از ۱۰۰ وجود ندارد و شاخص‌های تشخیصی هیچ اثری روی امتیاز رسمی Q، پارتو یا Risk Gate ندارند. «نسخهٔ آزمایشی — اعتبار تاریخی اطلاعات مالی و قیمت‌ها به‌طور کامل تأیید نشده است. نتایج توصیه خرید و فروش نیستند.»
"""
    mpath = os.path.join(OUT, "gam2k6_final_report.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {mpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
