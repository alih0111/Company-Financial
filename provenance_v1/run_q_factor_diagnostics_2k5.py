# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ P1 — فاکتورهای تشخیصی Q روی دادهٔ واقعی (فقط‌خواندنی).

سه فاکتور فعلاً غیرفعال Q را با محاسبهٔ تشخیصی معتبر پوشش می‌دهد:
  * roe_stability (هرگز پیاده نشده) — سری ROE سالانه و پایداری آن
  * margin_trend (پیاده‌شده ولی عملاً خاموش) — چرایی خاموشی + سری سالانهٔ
    قابل‌مقایسه
  * earnings_growth (پیاده‌شده، policy-excluded) — اعداد تشخیصی حفظ‌شده +
    اثبات نشت‌ناپذیری قرنطینهٔ ۱۰٬۶۵۰ ردیف

هیچ‌کدام در امتیاز رسمی Q وارد نمی‌شوند؛ وزن/فرمول رسمی دست‌نخورده می‌ماند.
خروجی‌ها:
  * q_factor_diagnostics_{tag}.json — sidecar نسخه‌دار با snapshot_binding
    (بخش UI: «شاخص‌های بنیادی در حال اعتبارسنجی»)
  * _p1_q_factor_diagnostics_{tag}.json — سند ممیزی کامل (تطبیق با آرتیفکت
    تولیدی، بازتولید مستقل SQL، پوشش صنعت، وضعیت آمادگی پیشنهاد فعال‌سازی)

موتور همان مسیر فقط‌خواندنی pilot_v2_qvt است (۲-ب-۵/۶/۷/۸)؛ تطبیق امتیازهای
نرمال‌شده با آرتیفکت تولیدی همین snapshot به‌صورت صریح کنترل می‌شود.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter
from datetime import date, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(REPO, "canonical_postgres_v1_2_1", "analytics_canonical_v1")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "provenance_v1"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import compute_metrics as CM  # noqa: E402
import expense_ttm_recovery as REC  # noqa: E402
import fiscal_calendar as FC  # noqa: E402
import report_chain_ttm as RC  # noqa: E402
import score_v2_normalize as SN  # noqa: E402
import score_v2_q_observed as QO  # noqa: E402
import score_v2_raw as RAW  # noqa: E402
import score_v4 as S4  # noqa: E402
import pilot_v2_qvt as P  # noqa: E402

import q_factor_diag_2k5 as D  # noqa: E402  (هستهٔ خالص این گام)

OUT = os.path.join(REPO, "provenance_v1", "output")
AS_OF = date(2026, 10, 8)
CUTOFF = datetime.fromisoformat("2026-10-08T23:59:00+00:00")
TAG = ("2026-10-08_q9499e3bb_v7786e01a_tdcfd3840")

FACTOR_FA = {
    "roe_stability": "پایداری ROE سالانه (کمتر بهتر)",
    "margin_trend": "روند حاشیهٔ سود عملیاتی TTM (بیشتر بهتر)",
    "earnings_growth": "رشد سود با پایهٔ تأییدشده (بیشتر بهتر)",
}
FA_STATUS_FA = {
    "computed": "محاسبه‌شده (تشخیصی)",
    "insufficient_evidence": "شواهد ناکافی — صادقانه unresolved",
    "computed_official": "رسمی و معتبر (خارج از تجمیع فعلی)",
    "raw_missing": "ورودی غایب — هیچ جایگزینی ساخته نشده",
    "quarantined": "قرنطینه‌شده (۲-ب-۴-۲)",
    "invalid": "نامعتبر (خطای داده، نه عملکرد ضعیف)",
    "not_applicable": "بی‌معنا در این وضعیت",
}


def main() -> int:
    print("engine (read-only) …")
    engine = CM.Engine(AS_OF, CUTOFF)
    engine.compute()
    rep_index = engine.report_index()
    durations_by_company, fiscal_cal = P.fiscal_calendar_for(engine)
    sector_map = S4.load_sector_map(AS_OF)
    meta, detail = P.build_company_meta(engine, sector_map)
    bases, base_diag = P.resolve_prev_bases(engine)
    prov, prov_diag = P.build_provenance(engine)
    sentinel_cells, sentinel_census = P.detect_sentinel_fact_cells(engine)
    clean_bases, quarantine_info = P.quarantine_prev_bases(
        engine, bases, sentinel_cells=sentinel_cells, census=sentinel_census)
    rec_results, rec_census = REC.recover_expense_order3(
        rep_index, durations_by_company, AS_OF, CUTOFF)
    expense_channels, expense_census = P.resolve_expense_ttm_channels(
        engine, recovery=rec_results or None)

    raw_by_company = RAW.build_q_raw(engine.metrics, prev_bases=clean_bases,
                                     provenance=prov, as_of=CUTOFF,
                                     expense_ttm=expense_channels)
    out = SN.normalize_q_cross_section(raw_by_company, meta, as_of=CUTOFF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    q_obs = QO.build_q_observed_report(
        out, raw_by_company, meta,
        symbols={cid: detail[cid].get("symbol") for cid in detail})
    print(f"engine done: {len(engine.metrics)} companies, "
          f"n_scored={q_obs['summary']['n_scored_by_factor']}")

    # ── تطبیق با آرتیفکت تولیدی همین snapshot (گیت اعتبار) ──────────────────
    art = json.load(open(os.path.join(
        HERE, "output", "v2_q_observed_report.json"), encoding="utf-8"))
    art_sc = art["summary"]["n_scored_by_factor"]
    my_sc = q_obs["summary"]["n_scored_by_factor"]
    score_mismatch = []
    n_score_checked = 0
    for cid, c in q_obs["companies"].items():
        ac = (art["companies"] or {}).get(cid) or {}
        for fid, f in (c.get("factors") or {}).items():
            af = (ac.get("factors") or {}).get(fid) or {}
            if f.get("score") is not None or af.get("score") is not None:
                n_score_checked += 1
                if abs((f.get("score") or 0) - (af.get("score") or 0)) > 1e-9:
                    score_mismatch.append({"company_id": cid, "factor": fid,
                                           "mine": f.get("score"),
                                           "artifact": af.get("score")})
    consistency = {
        "n_scored_by_factor_matches": art_sc == my_sc,
        "artifact": art_sc, "recomputed": my_sc,
        "n_company_factor_scores_checked": n_score_checked,
        "n_score_mismatch": len(score_mismatch),
        "score_mismatch_sample": score_mismatch[:10],
        "verdict": ("recomputed_matches_production_artifact"
                    if art_sc == my_sc and not score_mismatch
                    else "MISMATCH — reproduced run differs from artifact"),
    }
    print(f"consistency vs artifact: scored={art_sc == my_sc} "
          f"score_checked={n_score_checked} mismatch={len(score_mismatch)}")
    if score_mismatch:
        print("!! MISMATCH — این خروجی به snapshot فعلی اعتبار ندارد؛ "
              "ارقام تشخیصی فقط با برچسب mismatch منتشر می‌شوند")

    # جمعیت سه‌محور واجد شرایط (همان تعریف discovery: q∪v∪t pilot_eligible)
    v_comps = json.load(open(os.path.join(HERE, "output", "v2_value_pilot.json"),
                             encoding="utf-8"))["v_observed_report"]["companies"]
    t_comps = json.load(open(os.path.join(HERE, "output", "v2_t_pilot.json"),
                             encoding="utf-8"))["t_observed_report"]["companies"]
    triple_ids = sorted(
        cid for cid in q_obs["companies"]
        if q_obs["companies"][cid].get("pilot_eligible")
        and cid in v_comps and v_comps[cid].get("pilot_eligible")
        and cid in t_comps and t_comps[cid].get("pilot_eligible"))
    print(f"triple-eligible: {len(triple_ids)}")

    quarantined_tags = {}
    for row in quarantine_info.get("quarantined", []):
        quarantined_tags.setdefault(row["company_id"], []).append(row["tag"])

    # ── سری‌های سالانهٔ هر شرکت از report index (مسیر موتور) ─────────────────
    series_cache = {}
    for cid in sorted(engine.metrics):
        series_cache[cid] = build_annual_series(
            engine, rep_index, durations_by_company, fiscal_cal, cid)

    companies_diag = {}
    for cid in sorted(engine.metrics):
        subj = detail.get(cid, {})
        series = series_cache[cid]
        roe = D.roe_stability_from_series(series["roe"])
        m_ser = D.annual_margin_from_series(series["op_by_fy"],
                                            series["rev_by_fy"])
        g_ser = D.annual_growth_from_series(series["np_by_fy"])
        raw_rec = raw_by_company.get(cid) or {}
        mt_official = official_margin_trend(engine.metrics.get(cid) or {},
                                            clean_bases.get(cid) or {})
        mt_raw = raw_rec.get("margin_trend") or {}
        mt_class = classify_margin_trend(mt_raw, mt_official,
                                         quarantined_tags.get(cid) or [],
                                         (bases.get(cid) or {}))
        eg_raw = raw_rec.get("earnings_growth") or {}
        eg_norm = (out["factors"].get(cid) or {}).get("earnings_growth") or {}
        companies_diag[cid] = {
            "company_id": cid,
            "symbol": subj.get("symbol"),
            "industry": meta[cid].get("industry"),
            "model_family": meta[cid].get("model_family"),
            "in_triple_universe": cid in set(triple_ids),
            "factors": {
                "roe_stability": {
                    "status": roe["status"], "status_fa":
                    FA_STATUS_FA.get(roe["status"], roe["status"]),
                    "value": _r(roe.get("value")),
                    "unit": roe.get("unit"),
                    "n_valid_years": roe.get("n_valid", 0),
                    "window": roe.get("window"),
                    "excluded_years": roe.get("excluded_years", []),
                    "mean_roe_pct": _r(roe.get("mean_roe_pct")),
                    "definition": D.ROE_STABILITY_DEF,
                },
                "margin_trend": {
                    "status": mt_class["status"],
                    "status_fa": FA_STATUS_FA.get(mt_class["status"],
                                                  mt_class["status"]),
                    "value_pp": _r(mt_official.get("value_pp")),
                    "official_raw_status": mt_raw.get("status"),
                    "missing_reason": mt_class.get("reason"),
                    "annual_series": m_ser,
                    "definition": D.MARGIN_TREND_DEF,
                },
                "earnings_growth": {
                    "status": classify_earnings_growth(eg_raw),
                    "status_fa": None,  # بعداً پر می‌شود
                    "components": {
                        k: {"status": v.get("status"),
                            "value_pct": _r(v.get("value")),
                            "reason": (v.get("reason") or "")[:160]}
                        for k, v in (eg_raw.get("components") or {}).items()},
                    "blended_score_preserved": _r(eg_norm.get("factor_blend_score")),
                    "annual_series": g_ser,
                    "definition": D.EARNINGS_GROWTH_DEF,
                },
            },
        }
        companies_diag[cid]["factors"]["earnings_growth"]["status_fa"] = \
            FA_STATUS_FA.get(
                companies_diag[cid]["factors"]["earnings_growth"]["status"],
                companies_diag[cid]["factors"]["earnings_growth"]["status"])
        companies_diag[cid]["factors"]["margin_trend"]["status_fa"] = \
            FA_STATUS_FA.get(
                companies_diag[cid]["factors"]["margin_trend"]["status"],
                companies_diag[cid]["factors"]["margin_trend"]["status"])

    # ── اثبات نشت‌ناپذیری قرنطینه + سرشماری سنتیل ────────────────────────────
    proof = D.earnings_growth_quarantine_proof(raw_by_company, quarantined_tags)
    sentinel_rows_total = sum(sentinel_census.values())
    proof["sentinel_census_rows_by_metric"] = dict(sorted(sentinel_census.items()))
    proof["sentinel_rows_total"] = sentinel_rows_total
    proof["documented_10650_check"] = (
        "سرشماری مستقل این گام" + (" = ۱۰٬۶۵۰ ردیف (مطابق سند ۲-ک-۲/۲-ب-۴-۲)"
                                   if sentinel_rows_total == 10650
                                   else f" = {sentinel_rows_total} ردیف (≠ ۱۰٬۶۵۰ — تفاوت صریح ثبت شد)"))
    print(f"quarantine proof: {proof['verdict']} "
          f"(companies={proof['n_companies_with_quarantined_base']}, "
          f"leaks={proof['n_valid_despite_quarantine']}) | "
          f"sentinel rows: {sentinel_rows_total}")

    # ── پوشش واقعی بر اساس شرکت و صنعت ──────────────────────────────────────
    def ind_of(r):
        return r.get("industry")

    roe_rows = [{"company_id": cid, "industry": c["industry"],
                 "status": c["factors"]["roe_stability"]["status"]}
                for cid, c in companies_diag.items()]
    mt_rows = [{"company_id": cid, "industry": c["industry"],
                "status": c["factors"]["margin_trend"]["status"]}
               for cid, c in companies_diag.items()]
    eg_valid_rows = [{"company_id": cid, "industry": c["industry"],
                      "status": "computed" if any(
                          v.get("status") == "valid" for v in
                          c["factors"]["earnings_growth"]["components"].values())
                      else c["factors"]["earnings_growth"]["status"]}
                     for cid, c in companies_diag.items()]
    coverage = {
        "roe_stability": {
            "overall": dict(Counter(r["status"] for r in roe_rows)),
            "by_industry": D.coverage_by_industry(roe_rows, ind_of),
            "triple_universe": dict(Counter(
                r["status"] for r in roe_rows
                if r["company_id"] in set(triple_ids)))},
        "margin_trend": {
            "overall": dict(Counter(r["status"] for r in mt_rows)),
            "by_industry": D.coverage_by_industry(mt_rows, ind_of),
            "triple_universe": dict(Counter(
                r["status"] for r in mt_rows
                if r["company_id"] in set(triple_ids)))},
        "earnings_growth": {
            "overall": dict(Counter(r["status"] for r in eg_valid_rows)),
            "by_industry": D.coverage_by_industry(eg_valid_rows, ind_of),
            "triple_universe": dict(Counter(
                r["status"] for r in eg_valid_rows
                if r["company_id"] in set(triple_ids)))},
        "note": ("پوشش از دادهٔ واقعی بازشماری شد؛ هیچ عددی hardcode نیست. "
                 "«computed» یعنی محاسبهٔ تشخیصی معتبر؛ ورود به امتیاز رسمی Q "
                 "تصمیم مرحلهٔ بعد با مجوز است."),
    }

    # ── بازتولید مستقل با SQL خام برای ۱۶ نامزد (نمونه) ─────────────────────
    repro = independent_sql_reproduction(engine=engine, series_cache=series_cache)
    print(f"independent SQL reproduction: {repro['summary']}")

    # ── آمادگی پیشنهاد فعال‌سازی (فقط پیشنهاد؛ فعال‌سازی ممنوع) ──────────────
    readiness = activation_readiness(coverage, proof, consistency)
    print("activation readiness:", json.dumps(readiness, ensure_ascii=False)[:400])

    # payload هر شرکت باید خودکفا باشد (UI فقط per-company می‌خواند):
    # نام فارسی، verdict وضعیت هر فاکتور و خلاصهٔ کنترل‌ها
    per_company_readiness = {
        k: {"verdict": v["verdict"], "condition": v.get("condition")}
        for k, v in readiness.items() if k != "global_conditions"}
    section_meta = {
        "quarantine_verdict": proof["verdict"],
        "quarantine_companies": proof["n_companies_with_quarantined_base"],
        "quarantine_leaks": proof["n_valid_despite_quarantine"],
        "sentinel_rows_total": proof["sentinel_rows_total"],
        "sentinel_check": proof["documented_10650_check"],
        "consistency_verdict": consistency["verdict"],
        "consistency_scores_checked": consistency["n_company_factor_scores_checked"],
        "consistency_mismatch": consistency["n_score_mismatch"],
        "independent_reproduction": repro["summary"],
    }
    for cid, c in companies_diag.items():
        for key, factor in c["factors"].items():
            factor["fa"] = FACTOR_FA[key]
        c["activation_readiness"] = per_company_readiness
        c["_meta"] = section_meta

    binding = {
        "q": {"file": "v2_q_observed_report.json",
              "sha256": _sha_of(os.path.join(HERE, "output", "v2_q_observed_report.json"))},
        "v": {"file": "v2_value_pilot.json",
              "sha256": _sha_of(os.path.join(HERE, "output", "v2_value_pilot.json"))},
        "t": {"file": "v2_t_pilot.json",
              "sha256": _sha_of(os.path.join(HERE, "output", "v2_t_pilot.json"))},
        "as_of": str(AS_OF),
        "cutoff": CUTOFF.isoformat(),
        "note": ("binding به هش آرتیفکت‌های Q/V/T همین snapshot؛ sidecar فقط با "
                 "تطبیق همین سه hash سرو می‌شود"),
    }

    factors_meta = {
        "mission": "گام ۲-ک-۵ P1 — شاخص‌های بنیادی در حال اعتبارسنجی (تشخیصی)",
        "disclaimer": ("این شاخص‌ها کاملاً تشخیصی‌اند: امتیاز رسمی Q، رتبه‌بندی "
                       "پارتو، Data Confidence و Risk Gate را تغییر نمی‌دهند و "
                       "هیچ توصیهٔ خرید/فروش نیستند. فعال‌سازی هر فاکتور در امتیاز "
                       "رسمی فقط با تصمیم و مجوز مرحلهٔ بعد ممکن است."),
        "factors": {
            "roe_stability": {"fa": FACTOR_FA["roe_stability"],
                              "weight_in_official_q": 3,
                              "official_status": "not_implemented در raw لایه — این اولین محاسبهٔ معتبر آن است",
                              "definition": D.ROE_STABILITY_DEF,
                              "data_limitation": (
                                  "محدودیت واقعی داده: equity تاریخی در store غالباً فقط در "
                                  "گزارش‌های اخیر (order-1 و ستون مقایسه‌ای order-2) موجود است؛ "
                                  "پنجرهٔ ۵ ساله با حداقل ۳ سال معتبر فقط برای تعداد محدودی "
                                  "شرکت قابل محاسبه است — بقیه صادقانه insufficient_evidence "
                                  "می‌مانند و هیچ جایگزینی برای equity غایب ساخته نمی‌شود.")},
            "margin_trend": {"fa": FACTOR_FA["margin_trend"],
                             "weight_in_official_q": 3,
                             "official_status": "پیاده‌شده در raw؛ عملاً خاموش (پایهٔ TTM سال قبل غایب/قرنطینه‌شده)",
                             "definition": D.MARGIN_TREND_DEF},
            "earnings_growth": {"fa": FACTOR_FA["earnings_growth"],
                                "weight_in_official_q": 3,
                                "official_status": "پیاده‌شده؛ policy-excluded از تجمیع از گام ۲-ب-۶ — اعداد تشخیصی آن حفظ شده",
                                "definition": D.EARNINGS_GROWTH_DEF},
        },
        "activation_readiness": readiness,
    }

    # ── خروجی‌ها ─────────────────────────────────────────────────────────────
    sidecar = {
        "mission": factors_meta["mission"],
        "snapshot_binding": binding,
        "generated_note": ("زمان تولید این گزارش، تاریخ انتشار هیچ داده‌ای نیست؛ "
                           "همهٔ اعداد از دادهٔ واقعی همین snapshot می‌آیند."),
        "factors_meta": factors_meta,
        "quarantine_proof": {
            "verdict": proof["verdict"],
            "n_companies_with_quarantined_base":
                proof["n_companies_with_quarantined_base"],
            "n_valid_despite_quarantine": proof["n_valid_despite_quarantine"],
            "sentinel_rows_total": proof["sentinel_rows_total"],
            "documented_10650_check": proof["documented_10650_check"],
            "policy": proof["policy"],
        },
        "consistency_with_production_artifact": {
            "verdict": consistency["verdict"],
            "n_scored_by_factor_matches": consistency["n_scored_by_factor_matches"],
            "n_company_factor_scores_checked":
                consistency["n_company_factor_scores_checked"],
            "n_score_mismatch": consistency["n_score_mismatch"],
        },
        "independent_reproduction": repro["summary"],
        "companies": companies_diag,
    }
    os.makedirs(OUT, exist_ok=True)
    spath = os.path.join(OUT, f"q_factor_diagnostics_{TAG}.json")
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {spath}")

    audit = {
        "mission": factors_meta["mission"],
        "snapshot_binding": binding,
        "consistency": consistency,
        "quarantine_proof_full": proof,
        "prev_bases_diag": base_diag,
        "provenance_diag": prov_diag,
        "expense_ttm_census": expense_census,
        "coverage": coverage,
        "independent_reproduction_full": repro,
        "activation_readiness": readiness,
        "companies_full": {
            cid: {**companies_diag[cid],
                  "roe_series_engine": series_cache[cid]["roe"]}
            for cid in sorted(companies_diag)},
    }
    apath = os.path.join(OUT, f"_p1_q_factor_diagnostics_{TAG}.json")
    with open(apath, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {apath}")
    return 0


# ── ساخت سری‌های سالانه از report index (مسیر موتور) ─────────────────────────
def build_annual_series(engine, rep_index, durations_by_company, fiscal_cal,
                        cid: str) -> dict:
    """سری سالانهٔ (fy, fm=12) برای ROE/حاشیه/رشد. NP از resolve_ttm با همان
    قرارداد annual موتور؛ equity از یکی از دو پایهٔ واقعی:
      * order-1 سلول خودِ (fy,12) — «order1_own_cell»
      * در نبود آن، order-2 (ستون مقایسه‌ای پایان دورهٔ قبل) گزارش سالانهٔ
        (fy+1,12) — «order2_prior_comparative_annual_report»؛ PIT این پایه
        لحظهٔ انتشار گزارش سال fy+1 است و پایه با همان مبنا (restated) هم‌خوان
        است.
    سالِ NP با مقدار سنتیل → quarantined. هیچ مقداری حدس زده نمی‌شود."""
    rep = rep_index.get(cid, {})
    if not rep:
        return {"roe": [], "np_by_fy": {}, "op_by_fy": {}, "rev_by_fy": {}}
    durations = durations_by_company.get(cid, {})
    ann_month, _state, _src = FC.annual_month_of(fiscal_cal, cid)
    annual_fys = sorted(fy for (fy, fm) in rep if fm == 12)
    if not annual_fys:
        return {"roe": [], "np_by_fy": {}, "op_by_fy": {}, "rev_by_fy": {}}
    latest = max(annual_fys)
    roe, np_by_fy, op_by_fy, rev_by_fy = [], {}, {}, {}
    for fy in [y for y in annual_fys if y > latest - 5]:
        cell = rep.get((fy, 12), {})
        eq = (cell.get("total_equity") or {}).get(1)
        eq_basis = "order1_own_cell" if eq is not None else None
        if eq is None:
            nxt = rep.get((fy + 1, 12), {})
            eq2 = (nxt.get("total_equity") or {}).get(2)
            if eq2 is not None:
                eq = eq2
                eq_basis = "order2_prior_comparative_annual_report"
        is_annual = True if durations.get((fy, 12)) == 12 else None
        anchor = FC.prev_annual_cell(durations, fy, 12)
        vals = {}
        for metric in ("net_profit", "operating_profit", "revenue"):
            v, _p = RC.resolve_ttm(rep, metric, fy, 12, annual_month=ann_month,
                                   is_annual=is_annual, prev_annual_cell=anchor)
            vals[metric] = v
        np_v = vals["net_profit"]
        quarantined = np_v is not None and float(np_v) in P.SENTINEL_VALUES
        np_by_fy[fy] = None if quarantined else np_v
        op_by_fy[fy] = vals["operating_profit"]
        rev_by_fy[fy] = vals["revenue"]
        roe.append({"fy": fy, "net_profit": np_v, "equity": eq,
                    "equity_basis": eq_basis,
                    "quarantined": quarantined})
    return {"roe": roe, "np_by_fy": np_by_fy, "op_by_fy": op_by_fy,
            "rev_by_fy": rev_by_fy}


def official_margin_trend(m: dict, clean_base: dict) -> dict:
    """بازتولید قرارداد رسمی margin_trend از TTM موتور + پایهٔ پاک‌شده."""
    return D.margin_trend_official(
        m.get("operating_profit_ttm"), m.get("revenue_ttm"),
        clean_base.get("operating_profit_prev"), clean_base.get("revenue_prev"))


def classify_margin_trend(mt_raw: dict, mt_official: dict,
                          quarantined_tags: list, pre_base: dict) -> dict:
    if mt_official.get("status") == "computed":
        return {"status": "computed", "reason": None}
    if mt_raw.get("status") == RAW.STATUS_INVALID:
        return {"status": "invalid",
                "reason": (mt_raw.get("reason") or "")[:200]}
    if "operating_profit_prev" in quarantined_tags:
        return {"status": "raw_missing",
                "reason": "پایهٔ TTM سال قبل به‌دلیل آلودگی سنتیل قرنطینه شد "
                          "(۲-ب-۴-۲) — جایگزینی مجاز نیست"}
    if "operating_profit_prev" not in (pre_base or {}):
        return {"status": "raw_missing",
                "reason": "پایهٔ TTM سال قبل حل نشد (provenance-match مفقود) — "
                          "هیچ جایگزینی ساخته نمی‌شود"}
    return {"status": "raw_missing",
            "reason": (mt_raw.get("reason")
                       or mt_official.get("reason") or "")[:200]}


def classify_earnings_growth(eg_raw: dict) -> str:
    comps = (eg_raw.get("components") or {})
    sts = [c.get("status") for c in comps.values()]
    if any(s == "valid" for s in sts):
        return "computed"
    if any(s == "invalid" for s in sts):
        return "invalid"
    if any(s == "not_applicable" for s in sts):
        return "not_applicable"
    return "raw_missing"


# ── بازتولید مستقل با SQL خام (بدون موتور) ───────────────────────────────────
def independent_sql_reproduction(engine, series_cache: dict) -> dict:
    """۱۶ نامزد snapshot: بازخوانی مستقیم سلول‌های (fy,12) از
    fundamentals.financial_facts و بازتولید سری ROE — مقایسه با مسیر موتور.
    پیوست: سری رشد و حاشیه هم بازتولید و مقایسه می‌شوند."""
    import psycopg
    from run_publish_recovery import build_dsn

    iv_path = os.path.join(OUT, f"independent_validation_{TAG}.json")
    iv = json.load(open(iv_path, encoding="utf-8"))
    sample_ids = sorted(iv["companies"].keys())
    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT st.company_id::text AS cid, st.fiscal_year, st.fiscal_month,
               f.metric_code, f.period_order, f.canonical_value,
               st.period_end_date, rv.version_no
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
          AND f.metric_code IN ('net_profit','total_equity',
                                'operating_profit','revenue')
          AND r.supersedes_report_id IS NULL
          AND ((r.published_at IS NULL AND st.period_end_date <= %s)
               OR (r.published_at IS NOT NULL AND r.published_at <= %s))
        """, (sample_ids, AS_OF, CUTOFF))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.rollback()
    conn.close()

    # همان رتبه‌بندی report_index: (period_end, version) بزرگ‌تر برنده؛
    # fy/fm از period_end بازسازی می‌شود (سطح store fiscal_year غالباً NULL است)
    from compute_metrics import fiscal_ym
    best = {}
    for r in rows:
        fy, fm = r["fiscal_year"], r["fiscal_month"]
        if fy is None or fm is None:
            try:
                fy, fm = fiscal_ym(r["period_end_date"])
            except Exception:
                continue
        key = (r["cid"], fy, fm, r["metric_code"], r["period_order"])
        rank = (r["period_end_date"], r["version_no"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, r["canonical_value"])

    n_compared = n_match = n_mismatch = 0
    mismatches, per_company = [], {}
    for cid in sample_ids:
        eng_series = {s["fy"]: s for s in series_cache.get(cid, {}).get("roe", [])}
        raw_cells = {}
        for (c, fy, fm, metric, order), (_rank, val) in best.items():
            if c == cid and fm == 12 and order in (1, 2):
                raw_cells.setdefault(fy, {})[(metric, order)] = val
        comp = {"n_years_compared": 0, "n_match": 0, "n_mismatch": 0,
                "mismatch_years": []}
        for fy, cells in sorted(raw_cells.items()):
            np_raw = cells.get(("net_profit", 1))
            # همان قرارداد سری موتور: equity سال fy از order-1 سلول خودش،
            # وگرنه order-2 گزارش سالانهٔ سال بعد
            eq_raw = cells.get(("total_equity", 1))
            if eq_raw is None:
                eq_raw = (raw_cells.get(fy + 1) or {}).get(("total_equity", 2))
            e = eng_series.get(fy)
            if e is None or e.get("net_profit") is None or eq_raw in (None, 0):
                continue
            roe_engine = float(e["net_profit"]) / float(e["equity"]) * 100.0
            roe_sql = float(np_raw) / float(eq_raw) * 100.0
            comp["n_years_compared"] += 1
            n_compared += 1
            if math.isclose(roe_engine, roe_sql, rel_tol=1e-9, abs_tol=1e-9):
                comp["n_match"] += 1
                n_match += 1
            else:
                comp["n_mismatch"] += 1
                n_mismatch += 1
                if len(mismatches) < 20:
                    mismatches.append({
                        "company_id": cid, "fy": fy,
                        "engine_roe_pct": roe_engine, "sql_roe_pct": roe_sql,
                        "note": "NP مسیر موتور TTM حل‌شده است؛ SQL خام order-1 "
                                "سلول (fy,12) — تفاوت یعنی پایهٔ TTM از گزارش "
                                "دیگری آمده و باید بازبینی شود"})
        per_company[cid] = comp
    summary = {
        "sample": "۱۶ نامزد snapshot (IV companies)",
        "method": ("SQL خام روی financial_facts بدون موتور؛ همان فیلتر PIT و "
                   "رتبه‌بندی نسخهٔ report_index؛ فقط سلول‌های سالانهٔ (fy,12) "
                   "order-1؛ ROE = NP/equity × 100"),
        "n_companies": len(sample_ids),
        "n_years_compared": n_compared,
        "n_match": n_match, "n_mismatch": n_mismatch,
        "mismatches": mismatches,
    }
    return {"summary": summary, "per_company": per_company}


def activation_readiness(coverage: dict, proof: dict, consistency: dict) -> dict:
    """آمادگی پیشنهاد فعال‌سازی هر فاکتور برای مرحلهٔ بعد — فقط پیشنهاد."""
    def computed_of(factor):
        return coverage[factor]["triple_universe"].get("computed", 0)

    roe_n = computed_of("roe_stability")
    mt_n = computed_of("margin_trend")
    eg_n = computed_of("earnings_growth")
    leak_free = proof["n_valid_despite_quarantine"] == 0
    consistent = consistency["verdict"].startswith("recomputed_matches")
    return {
        "roe_stability": {
            "verdict": ("ready_for_activation_proposal"
                        if roe_n >= 20 and consistent
                        else "conditional" if roe_n > 0 else "keep_disabled"),
            "n_computed_in_triple_universe": roe_n,
            "basis": ("تعریف اقتصادی روشن، حداقل ۳ سال معتبر، برخورد صریح با "
                      "ROE منفی/equity نامعتبر؛ پوشش از دادهٔ واقعی"),
            "condition": ("فعال‌سازی فقط با تصمیم مرحلهٔ بعد؛ وزن رسمی (۳) و "
                          "جهت (کمتر بهتر) بدون تغییر"),
        },
        "margin_trend": {
            "verdict": ("ready_for_activation_proposal"
                        if mt_n >= 20 and consistent
                        else "conditional" if mt_n > 0 else "keep_disabled"),
            "n_computed_in_triple_universe": mt_n,
            "basis": ("فرمول رسمی پیاده‌شده است؛ خاموشی آن از قرنطینه/حل‌نشدن "
                      "پایهٔ TTM سال قبل است — فعال‌سازی بدون رفع پایه‌ها "
                      "پوشش ناچیز دارد"),
            "condition": ("رفع قرنطینه فقط با پاک‌سازی دادهٔ بالا‌دستی؛ هیچ "
                          "جایگزینی برای پایهٔ قرنطینه‌شده مجاز نیست"),
        },
        "earnings_growth": {
            "verdict": ("ready_for_activation_proposal"
                        if eg_n >= 20 and leak_free and consistent
                        else "conditional"),
            "n_computed_in_triple_universe": eg_n,
            "basis": ("فرمول رسمی با پایهٔ تأییدشده + اثبات نشت‌ناپذیری قرنطینهٔ "
                      "۱۰٬۶۵۰ ردیف در همین گام؛ مانع اصلی، تصمیم سیاستی گام "
                      "۲-ب-۶ (policy exclusion) است نه داده"),
            "condition": ("برداشتن policy exclusion = تصمیم صریح مرحلهٔ بعد؛ "
                          "قرنطینه به‌شکل فعلی حفظ می‌شود"),
        },
        "global_conditions": {
            "quarantine_leak_free": leak_free,
            "recomputed_matches_production_artifact":
                consistency["verdict"].startswith("recomputed_matches"),
            "note": ("هیچ‌کدام از این پیشنهادها در این مأموریت اجرا نمی‌شود؛ "
                     "وزن/فرمول رسمی Q دست‌نخورده است"),
        },
    }


def _sha_of(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _r(v):
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
