# -*- coding: utf-8 -*-
"""گام ۲-ک-۶ P0 — بستن مغایرت‌های باقی‌مانده PIT و اعلام آمادگی SQL 125.

* مقایسهٔ مستقل کلیدهای طرح قدیم (۲-ک-۲) و طرح قطعی (۲-ک-۵ stageB):
  هم‌پوشانی، حذف (۲۰ ردیف / ۱۸ report) و اضافه (۹۰۳ ردیف / ۸۳۱ report) + drift مقداری.
* reconcile واحد شمارش اعداد ۶٬۸۱۳ / ۶٬۸۰۹ / ۶٬۵۶۰ / ۲۵۴.
* کنترل خروج‌بودن ۴ جفت مبهم (DST-مرزی) از طرح قطعی و عدم تبدیل آن‌ها به verified.
* بازبینی ساختاری SQL 125 (گارد drift، بکاپ درون‌تراکنشی، idempotency،
  کنترل پس از اجرا، rollback اضطراری) و اعلام READY/NOT_READY.

هیچ SQL اجرا نمی‌شود؛ فقط خواندن فایل‌های طرح و parse فایل SQL.
"""
from __future__ import annotations

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def main() -> int:
    old = json.load(open(os.path.join(OUT, f"backfill_plan_{TAG}.json"),
                         encoding="utf-8"))
    new = json.load(open(os.path.join(OUT, f"backfill_plan_2k5_stageB_{TAG}.json"),
                         encoding="utf-8"))
    closeout = json.load(open(os.path.join(OUT, f"_p0_pit_closeout_{TAG}.json"),
                              encoding="utf-8"))

    old_rows, new_rows = old["plan_rows"], new["plan_rows"]
    old_rids = {r["report_id"] for r in old_rows}
    new_rids = {r["report_id"] for r in new_rows}
    dropped = old_rids - new_rids
    added = new_rids - old_rids
    dropped_rows = [r for r in old_rows if r["report_id"] in dropped]
    added_rows = [r for r in new_rows if r["report_id"] in added]
    val_drift = []
    old_by = {r["report_id"]: r for r in old_rows}
    for r in new_rows:
        o = old_by.get(r["report_id"])
        if o and str(o.get("publish_at")) != str(r.get("publish_at")):
            val_drift.append(r["report_id"])

    # reconcile واحد شمارش از سند closeout (ادعای سند با جمع مؤلفه‌ها کنترل می‌شود)
    moves = closeout["reconciliation"]["status_moves_old_to_new_top"]
    pair_sum = sum(moves.values())
    dp = closeout["definitive_plan"]
    removed_detail = closeout["four_rows_reexamination"]["removed_rows_detail"]
    removed_rids = {d["report_id"] for d in removed_detail}
    amb_review = [r for r in new["review_rows"]
                  if r.get("reason") == "ambiguous_match"]
    amb_rids = {r["report_id"] for r in amb_review}
    amb_leak = amb_rids & new_rids
    removed_leak = removed_rids & new_rids

    identity = {
        "rows": (len(old_rows) - len(dropped_rows) + len(added_rows)
                 == len(new_rows)),
        "reports": (len(old_rids) - len(dropped) + len(added) == len(new_rids)),
        "plan_plus_review_plus_removed_equals_live_dateless":
            (dp["plan_rows_count"] + dp["review_rows_count"]
             + dp["removed_no_evidence_count"] == 7566),
        "removed_rows_unique_reports": len(removed_rids) == 18,
        "no_ambiguous_report_in_plan": not amb_leak,
        "no_removed_report_in_plan": not removed_leak,
        "no_value_drift_on_overlap": not val_drift,
        "closeout_pair_moves_sum": pair_sum,
    }

    # ── بازبینی ساختاری SQL 125 ─────────────────────────────────────────────
    sql_path = os.path.join(REPO, "provenance_v1", "sql",
                            "125_publish_at_backfill_stageB_draft.sql")
    sql = open(sql_path, encoding="utf-8").read()
    code_lines = [ln for ln in sql.splitlines()
                  if not ln.strip().startswith("--")]
    code = "\n".join(code_lines)
    n_tuples = len(re.findall(r"::uuid,\s*'", sql))
    checks = {
        "single_transaction": code.count("BEGIN;") == 1 and code.count("COMMIT;") == 1,
        "drift_guard_raises": "IF n_null <> n_target THEN" in sql
                              and "RAISE EXCEPTION 'drift guard" in sql,
        "drift_guard_filters_null_and_legacy":
            "AND published_at IS NULL AND source = 'legacy_sqlserver'" in sql,
        "target_count_is_6560": "n_target int := 6560" in sql,
        "plan_values_tuples_6560": n_tuples == 6560,
        "in_transaction_backup": "CREATE TEMP TABLE _backfill_backup2" in sql,
        "update_guarded_idempotent":
            code.count("published_at IS NULL") >= 2
            and "r.source = 'legacy_sqlserver'" in code,
        "post_check_raises": "RAISE EXCEPTION 'post-check failed" in sql,
        "emergency_rollback_present": "-- ======================= ROLLBACK" in sql,
        "on_commit_drop": "ON COMMIT DROP" in sql,
    }

    dst_pairs = sorted({(d["codal_symbol"], str(d["period_end_date"]))
                        for d in removed_detail
                        if d.get("flagged_in_2k4_dst_era")})
    result = {
        "mission": "گام ۲-ک-۶ P0 — تعیین تکلیف مغایرت‌های PIT و آمادگی SQL 125",
        "snapshot_binding": closeout["snapshot_binding"],
        "old_vs_new_plan_key_comparison": {
            "old_plan_rows": len(old_rows), "new_plan_rows": len(new_rows),
            "old_distinct_reports": len(old_rids),
            "new_distinct_reports": len(new_rids),
            "overlap_reports": len(old_rids & new_rids),
            "removed_reports": len(dropped), "removed_statement_rows": len(dropped_rows),
            "added_reports": len(added), "added_statement_rows": len(added_rows),
            "value_drift_on_overlap": len(val_drift),
            "explanation": (
                "۲۰ ردیف statement قدیم‌طرح (۱۸ report یکتا؛ دجابر سه ردیف دارد) "
                "شواهد publish_at بازتولیدناپذیری داشتند (از کش قدیمی pub_backfill؛ "
                "شامل ۴ ردیف DST-دورهٔ ۲-ک-۴) و از طرح قطعی حذف شدند؛ ۹۰۳ ردیف / "
                "۸۳۱ report تازه‌گشوده‌شده با resolver اصلاح‌شده اضافه شدند؛ روی "
                "هم‌پوشانی هیچ drift مقداری وجود ندارد"),
        },
        "number_reconciliation": {
            "6813": {"unit": "جفت (company, period_end) بی‌تاریخ زندهٔ جمعیت Q∪V∪T",
                     "breakdown_from_status_moves": dict(moves),
                     "sum_check": pair_sum == 6813,
                     "note": ("۵٬۷۴۳ re-verified + ۸۳۱ تازه‌verified + ۴ تازه‌ambiguous + "
                              "۴۷ ambiguous حفظ‌شده + ۱۸۸ no_evidence = ۶٬۸۱۳")},
            "6809": {"unit": "سلول برندهٔ بی‌تاریخ (company, fy/fm) قبل از مرحلهٔ A",
                     "period_end_definition": 6812,
                     "note": "شمارش ۲-ک-۴؛ در طرح قطعی ۲-ک-۵ همین جمعیت شبیه‌سازی شد"},
            "6560": {"unit": "report یکتای طرح قطعی (واحد UPDATE)",
                     "statement_rows": dp["plan_rows_count"],
                     "note": "۷٬۲۸۵ ردیف statement روی ۶٬۵۶۰ report یکتا"},
            "254": {"unit": "سلول برندهٔ بی‌تاریخ (company, fy/fm) پس از شبیه‌سازی مرحلهٔ A",
                    "period_end_definition": 257,
                    "note": ("۲۳۶ شبیه‌سازی ۲-ک-۴ (با نگه‌داشتن ۲۰ ردیف بی‌شواهد) + ۱۸ سلول "
                             "بیشتر پس از حذف عمدی آن ردیف‌ها در طرح قطعی")},
            "identity_checks": identity,
        },
        "four_ambiguous_dst_pairs": {
            "kept_out_of_plan": not amb_leak,
            "ambiguous_review_rows": len(amb_review),
            "ambiguous_pairs": len({(r["company_id"], str(r["period_end_date"]))
                                    for r in amb_review}),
            "dst_era_removed_rows_pairs": dst_pairs,
            "rule": ("زمان‌های محلی مبهمِ مرز DST فقط با مدرک مستقل به verified "
                     "تبدیل می‌شوند؛ بدون مدرک ambiguous می‌مانند و خارج از طرح‌اند"),
        },
        "sql_125_structural_checks": checks,
        "sql_125_execution_readiness": {
            "preconditions": [
                "گارد drift: دقیقاً ۶٬۵۶۰ ردیف هدف باید publish_at NULL و source legacy باشند — وگرنه EXCEPTION و abort کل تراکنش",
                "جدول طرح موقت و بکاپ درون‌تراکنشی؛ UPDATE فقط ردیف‌های NULL/legacy را می‌گیرد (idempotent)",
                "کنترل پس از اجرا: هیچ ردیف هدفی بی‌تاریخ نمی‌ماند؛ در غیر این صورت rollback",
            ],
            "concurrency": ("تراکنش واحد با قفل ردیفی؛ ورود دادهٔ جدید (نامهٔ جدید) به "
                            "ردیف‌های طرح دست نمی‌زند و فقط گارد drift را تغییر می‌دهد "
                            "که در آن صورت اجرا امن متوقف می‌شود"),
            "rollback": ("بکاپ درون‌تراکنشی + اسکریپت rollback اضطراری (مقدار NULL بازگردانی) "
                         "به‌صورت کامنت‌شده در همین فایل — اجرای آن نیازمند اپراتور است"),
            "idempotency_note": ("اجرای دوباره پس از موفقیت: گارد drift با ۰ از ۶٬۵۶۰ "
                                 "EXCEPTION می‌دهد — رفتار fail-closed، بدون اعمال دوباره"),
            "verdict": "READY" if all(checks.values()) and all(identity.values()) else "NOT_READY",
            "verdict_reasons": ([k for k, v in checks.items() if not v]
                                + [f"identity:{k}" for k, v in identity.items() if not v])
            or ["همهٔ کنترل‌های ساختاری و تطبیق کلیدها پاس شد؛ اجرا فقط منوط به مجوز صریح است"],
        },
        "not_executed": "هیچ SQL اجرا نشده؛ این خروجی فقط سند است",
    }
    path = os.path.join(OUT, f"_p0_sql125_readiness_2k6_{TAG}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {path}")
    print("identity:", identity)
    print("sql checks:", checks)
    print("verdict:", result["sql_125_execution_readiness"]["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
