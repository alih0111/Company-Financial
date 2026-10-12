# -*- coding: utf-8 -*-
"""گام ۲-ک-۶ P3 — sidecar نسخه‌دار eg_economic_audit برای UI تصمیم‌یار.

خواندن نتایج ممیزی اقتصادی مستقل earnings_growth (خروجی
run_eg_economic_validation_2k6) و ساخت sidecar per-company خودکفا با گیت
snapshot_binding (سه hash آرتیفکت Q/V/T). برای همهٔ ۶۲ شرکت جامعهٔ سه‌محوری
تولید می‌شود؛ ۵ شرکت بدون مقدار معتبر با وضعیت صادقانه (insufficient_evidence)
و دلیل. هیچ توصیه خرید/فروش و هیچ اثری روی امتیاز رسمی Q ندارد.
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

VERDICT_FA = {
    "verified": "تأییدشده — رشد سود قابل‌دفاع (هر دو جزء، بازتولید مستقل، بدون هشدار کیفی)",
    "verified_with_limitation": "تأییدشده با محدودیت — مقدار درست و بازتولیدشده، با محدودیت/هشدار ثبت‌شده",
    "diagnostic_only": "فقط تشخیصی — شواهد کافی برای طبقه‌بندی معتبر نیست",
    "insufficient_evidence": "شواهد ناکافی — مقدار معتبر قابل‌محاسبه/بازتولید نیست",
    "invalid": "نامعتبر",
}

COMP_FA = {"net_profit_growth_pct": "رشد سود خالص",
           "operating_profit_growth_pct": "رشد سود عملیاتی"}

STATUS_FA = {"valid": "معتبر", "missing": "بدون پایهٔ قابل‌اتکا",
             "not_applicable": "بی‌معنا در این وضعیت (پایهٔ صفر/منفی یا تغییر علامت)",
             "invalid": "نامعتبر"}


def main() -> int:
    audit = json.load(open(os.path.join(
        OUT, f"_p1_eg_economic_validation_{TAG}.json"), encoding="utf-8"))
    qd = json.load(open(os.path.join(
        OUT, f"q_factor_diagnostics_{TAG}.json"), encoding="utf-8"))

    binding = audit["snapshot_binding"]
    companies = {}
    # ۵۷ شرکت دارای مقدار: از ممیزی مستقل
    for cid, c in audit["companies"].items():
        comps = {}
        for k, v in c["components"].items():
            eng = v.get("engine_status")
            comps[k] = {
                "status": eng,
                "status_fa": STATUS_FA.get(eng, eng),
                "value_pct": v.get("engine_value_pct"),
                "independent_value_pct": v.get("independent_value_pct"),
                "value_match_with_engine": v.get("value_match_with_engine"),
                "base": v.get("independent_base"),
                "current_ttm": v.get("engine_current_ttm"),
                "period_current": v.get("period_current"),
                "period_base": v.get("period_base"),
                "reason": (v.get("engine_reason") or "")[:220],
            }
        companies[cid] = {
            "symbol": c["symbol"], "industry": c["industry"],
            "has_value": True,
            "verdict": c["verdict"], "verdict_fa": VERDICT_FA[c["verdict"]],
            "sub_verdicts": c["sub_verdicts"],
            "components": comps,
            "warnings": c["warnings"],
            "limitations": c["limitations"],
            "in_official_composite": all(
                v["engine_status"] == "valid" for v in c["components"].values()),
            "official_status_note": (
                "policy_excluded_step_2b6 — در تجمیع رسمی Q مصرف نمی‌شود؛ وزن (۳) "
                "بازتوزیع نمی‌شود؛ این payload کاملاً تشخیصی است"),
        }
    # ۵ شرکت سه‌محوری بدون مقدار EG
    qf62 = qd["companies"]
    n_added = 0
    for cid, c in qf62.items():
        if cid in companies or not c.get("in_triple_universe"):
            continue
        eg = c["factors"]["earnings_growth"]
        companies[cid] = {
            "symbol": c["symbol"], "industry": c["industry"],
            "has_value": False,
            "verdict": "insufficient_evidence",
            "verdict_fa": VERDICT_FA["insufficient_evidence"],
            "sub_verdicts": {"math_correctness": "n/a",
                             "source_and_pit_validity": "n/a",
                             "economic_meaningfulness": "n/a"},
            "components": {}, "warnings": [], "limitations": [],
            "in_official_composite": False,
            "official_status_note": (
                "policy_excluded_step_2b6 — در تجمیع رسمی Q مصرف نمی‌شود؛ "
                f"وضعیت تشخیصی ۲-ک-۵: {eg['status']}"),
            "diag_status_2k5": eg["status"],
        }
        n_added += 1

    counts = audit["classification"]["counts"].copy()
    counts["insufficient_evidence"] = counts.get("insufficient_evidence", 0) + n_added
    n_valid_comps = sum(
        1 for c in audit["companies"].values()
        for v in c["components"].values() if v["engine_status"] == "valid")
    n_big = audit["classification"].get("n_valid_components_beyond_200pct") or 0
    n_mid = sum(
        1 for c in audit["companies"].values() for v in c["components"].values()
        if v["engine_status"] == "valid" and v["engine_value_pct"] is not None
        and 100.0 < abs(float(v["engine_value_pct"])) <= 200.0)

    meta = {
        "mission": "گام ۲-ک-۶ P1/P3 — اعتبارسنجی اقتصادی مستقل earnings_growth",
        "definition": (
            "growth_pct = (TTM جاری − TTM سال قبل) / TTM سال قبل × ۱۰۰ — فقط با "
            "پایهٔ اکیداً مثبتِ تأمین‌شده و هم‌پنجرهٔ ۱۲ماهه؛ پایهٔ صفر/منفی و تغییر "
            "علامت سود وضعیت‌های مجزای غیردرصدی‌اند؛ دو جزء: سود خالص و سود عملیاتی؛ "
            "ترکیب رسمی فقط وقتی معتبر است که هر دو جزء معتبر باشند"),
        "method": audit["method"]["independence"],
        "reproduction_summary": audit["reproduction_summary"],
        "classification_counts": counts,
        "verdict_legend_fa": VERDICT_FA,
        "quarantine_leak_proof": audit["quarantine_leak_proof"],
        "economic_quality_note": (
            f"از {n_valid_comps} جزء معتبر رشد، {n_big} جزء بزرگی بیش از ۲۰۰٪ و "
            f"{n_mid} جزء بین ۱۰۰ تا ۲۰۰٪ دارند — در محیط تورمی/پایه‌های کوچک، درصد رشد "
            "به‌تنهایی شاخص کیفیت نیست و همیشه باید با مقدار خام پایه و دورهٔ مقایسه دیده شود؛ "
            "هشدارهای هر شرکت در همین payload آمده است"),
        "disclaimer": ("کاملاً تشخیصی: امتیاز رسمی Q، رتبه‌بندی پارتو، Data Confidence و "
                       "Risk Gate را تغییر نمی‌دهد و توصیهٔ خرید/فروش نیست. فعال‌سازی "
                       "earnings_growth در امتیاز رسمی فقط با برداشتن صریح policy "
                       "exclusion گام ۲-ب-۶ (تصمیم سیاسی مجزا) ممکن است."),
    }
    # payload هر شرکت باید خودکفا باشد (reader فقط per-company می‌خواند)
    per_company_meta = {
        "reproduction_summary": meta["reproduction_summary"],
        "classification_counts": counts,
        "quarantine_leak_proof": {
            "verdict": audit["quarantine_leak_proof"]["verdict"],
            "n_quarantined_components_checked":
                audit["quarantine_leak_proof"]["n_quarantined_components_checked"],
        },
        "economic_quality_note": meta["economic_quality_note"],
        "disclaimer": meta["disclaimer"],
        "definition": meta["definition"],
    }

    for cid in companies:
        companies[cid]["_meta"] = per_company_meta

    sidecar = {
        "mission": meta["mission"],
        "schema_note": "sidecar نسخه‌دار — kind: eg_economic_audit, schema 1.0",
        "snapshot_binding": {
            "q": binding["q"], "v": binding["v"], "t": binding["t"],
            "as_of": binding["as_of"], "cutoff": binding["cutoff"],
            "note": ("binding به هش آرتیفکت‌های Q/V/T همین snapshot؛ sidecar فقط با "
                     "تطبیق همین سه hash سرو می‌شود"),
        },
        "generated_note": ("زمان تولید این گزارش، تاریخ انتشار هیچ داده‌ای نیست؛ همهٔ "
                           "اعداد از دادهٔ واقعی همین snapshot و ممیزی مستقل آن می‌آیند."),
        "audit_meta": meta,
        "companies": companies,
    }
    path = os.path.join(OUT, f"eg_economic_audit_{TAG}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {path} — companies: {len(companies)} (+{n_added} بدون مقدار)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
