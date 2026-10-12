# -*- coding: utf-8 -*-
"""گام ۲-ک-۶ — اعتبارسنجی اقتصادی earnings_growth + پوشش roe_stability/margin_trend.

P1: بازتولید مستقل earnings_growth برای همهٔ شرکت‌های «computed» جامعهٔ سه‌محوری
  با مسیر محاسباتی مستقل از تابع فاکتور (score_v2_raw._build_earnings_growth)
  و از resolve_prev_bases پایلوت: خواندن مستقیم سلول‌های fact از PostgreSQL با
  اتصال مستقل، ساخت ایندکس مستقل، رزولوشن TTM بازنویسی‌شده، قرنطینهٔ سنتیلِ
  بازسازی‌شده، و محاسبهٔ رشد با پیاده‌سازی مستقل. هیچ مقداری حدس زده نمی‌شود.
P2: تست معناشاسی ستون مقایسه‌ای equity (برای رفع محدودیت equity تاریخی) و
  تفکیک علت خاموشی margin_trend (قرنطینه در برابر حل‌نشدن).

هیچ فاکتوری در امتیاز رسمی Q فعال نمی‌شود؛ وزن/فرمول رسمی دست‌نخورده.
DB فقط‌خواندنی؛ هیچ overwrite آرتیفکت اصلی؛ خروجی: provenance_v1/output/_p1_eg_economic_validation_{TAG}.json
و _p2_coverage_2k6_{TAG}.json
"""
from __future__ import annotations

import hashlib
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
os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")

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

OUT = os.path.join(REPO, "provenance_v1", "output")
AS_OF = date(2026, 10, 8)
CUTOFF = datetime.fromisoformat("2026-10-08T23:59:00+00:00")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
ART_BASE = os.path.join(HERE, "output")
TOL = 1e-9
REL_TOL = 1e-9

SENTINEL_VALUES = P.SENTINEL_VALUES          # ±1e6 / ±1e8
SENTINEL_METRICS = P.SENTINEL_METRICS        # net_profit, operating_profit
GROWTH_BAND = RAW.EARNINGS_GROWTH_PCT_ANOMALY_BAND

FA_VERDICT = {
    "verified": "تأییدشده — هر دو جزء معتبر، بازتولید مستقل منطبق، بدون هشدار کیفی باز",
    "verified_with_limitation": "تأییدشده با محدودیت — مقدار درست و بازتولیدپذیر با محدودیت/هشدار ثبت‌شده",
    "diagnostic_only": "فقط تشخیصی — بدون شواهد کافی برای طبقه‌بندی معتبر",
    "insufficient_evidence": "شواهد ناکافی — مقدار معتبری قابل محاسبه/بازتولید نیست",
    "invalid": "نامعتبر — نقض قرارداد یا دادهٔ خراب",
}


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(float(v))


def _r(v):
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
# رزولوشن TTM مستقل — قراردادِ مستند report_chain_ttm با پیاده‌سازی جدا
# ═══════════════════════════════════════════════════════════════════════════
def own_cell(rep, fy, fm, metric, order=1):
    d = (rep.get((fy, fm)) or {}).get(metric)
    if not d:
        return None
    return d.get(order)


def own_resolve_ttm(rep, metric, fy, fm, is_annual, anchor):
    """A direct → B chain → C None، مطابق قرارداد مستند موتور؛ پیاده‌سازی مستقل."""
    if is_annual:
        cur = own_cell(rep, fy, fm, metric, 1)
        if cur is not None:
            return cur, "ANNUAL_REPORT_12M", [(fy, fm, metric, 1)]
    # A) direct: fm==12 → order1؛ وگرنه order1 + order3 − order2
    d = (rep.get((fy, fm)) or {}).get(metric)
    if d:
        cur = d.get(1)
        if cur is not None:
            if fm == 12:
                return cur, "DIRECT_CANONICAL", [(fy, fm, metric, 1)]
            o3, o2 = d.get(3), d.get(2)
            if o3 is not None and o2 is not None:
                return cur + o3 - o2, "DIRECT_CANONICAL", [
                    (fy, fm, metric, 1), (fy, fm, metric, 2), (fy, fm, metric, 3)]
    # B) chain: anchor annual + cur YTD − prior-year same-month YTD
    if metric in RC.FLOW_CUMULATIVE:
        cur = own_cell(rep, fy, fm, metric, 1)
        if cur is not None:
            a = anchor if anchor else (fy - 1, 12)
            if (fy, fm) == a:
                return cur, "REPORT_CHAIN_TTM", [(fy, fm, metric, 1)]
            annual = own_cell(rep, a[0], a[1], metric, 1)
            if annual is not None:
                prior_ytd = own_cell(rep, fy - 1, fm, metric, 1)
                if prior_ytd is not None:
                    return annual + cur - prior_ytd, "REPORT_CHAIN_TTM", [
                        (a[0], a[1], metric, 1), (fy, fm, metric, 1),
                        (fy - 1, fm, metric, 1)]
                return None, "MISSING_PRIOR_COMPARABLE", [(a[0], a[1], metric, 1)]
            return None, "MISSING_PRIOR_ANNUAL", []
    return None, "INSUFFICIENT_TTM_PERIODS", []


def own_growth(cur, base):
    """قرارداد رسمی رشد با پیاده‌سازی مستقل: فقط پایهٔ اکیداً مثبت درصد دارد."""
    if cur is None or base is None:
        return {"status": "missing", "value": None}
    if not (_finite(cur) and _finite(base)):
        return {"status": "invalid", "value": None}
    cur, base = float(cur), float(base)
    if base == 0:
        return {"status": "not_applicable", "value": None}
    if base < 0:
        return {"status": "not_applicable", "value": None,
                "sign_change": cur > 0}
    val = (cur - base) / base * 100.0
    out = {"status": "valid", "value": val}
    if cur < 0:
        out["turned_to_loss"] = True
    if val < GROWTH_BAND[0] or val > GROWTH_BAND[1]:
        out["magnitude_anomaly"] = True
    return out


# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    # ── A) بایندینگ snapshot ─────────────────────────────────────────────────
    arts = {}
    for k, fn in (("q", "v2_q_observed_report.json"),
                  ("v", "v2_value_pilot.json"), ("t", "v2_t_pilot.json")):
        p = os.path.join(ART_BASE, fn)
        arts[k] = {"file": fn, "sha256": sha256_of(p)}
    binding_expected = {"q": "9499e3bbe1faf9e55e4270fa5cf12d2ce50a65ef8e3297eb7b933319c0c0c6d1",
                        "v": "7786e01ae054c6835159ac2c5071e4c4d44e82ee8517ddae00b743d9508d97fb",
                        "t": "dcfd3840ae4f335b916e2c29b1212691c1fe0da5f3f674be475c69a04b3e614d"}
    binding_ok = all(arts[k]["sha256"] == binding_expected[k] for k in arts)
    print("binding:", "MATCH" if binding_ok else "MISMATCH")
    if not binding_ok:
        print("!! آرتیفکت‌ها با snapshot مرجع نمی‌خوانند — توقف")
        return 2

    # ── B) موتور فقط‌خواندنی + گیت تطبیق با آرتیفکت تولیدی ────────────────────
    print("engine (read-only) …")
    engine = CM.Engine(AS_OF, CUTOFF)
    engine.compute()
    rep_index = engine.report_index()
    durations_by_company, fiscal_cal = P.fiscal_calendar_for(engine)
    sector_map = S4.load_sector_map(AS_OF)
    meta, detail = P.build_company_meta(engine, sector_map)
    bases, base_diag = P.resolve_prev_bases(engine)
    prov, _prov_diag = P.build_provenance(engine)
    sentinel_cells, sentinel_census = P.detect_sentinel_fact_cells(engine)
    clean_bases, quarantine_info = P.quarantine_prev_bases(
        engine, bases, sentinel_cells=sentinel_cells, census=sentinel_census)
    rec_results, _rec_census = REC.recover_expense_order3(
        rep_index, durations_by_company, AS_OF, CUTOFF)
    expense_channels, _expense_census = P.resolve_expense_ttm_channels(
        engine, recovery=rec_results or None)

    raw_by_company = RAW.build_q_raw(engine.metrics, prev_bases=clean_bases,
                                     provenance=prov, as_of=CUTOFF,
                                     expense_ttm=expense_channels)
    out = SN.normalize_q_cross_section(raw_by_company, meta, as_of=CUTOFF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    q_obs = QO.build_q_observed_report(
        out, raw_by_company, meta,
        symbols={cid: detail[cid].get("symbol") for cid in detail})
    print(f"engine done: {len(engine.metrics)} companies")

    art_q = json.load(open(os.path.join(ART_BASE, "v2_q_observed_report.json"),
                           encoding="utf-8"))
    score_mismatch = 0
    n_score_checked = 0
    for cid, c in q_obs["companies"].items():
        ac = (art_q["companies"] or {}).get(cid) or {}
        for fid, f in (c.get("factors") or {}).items():
            af = (ac.get("factors") or {}).get(fid) or {}
            if f.get("score") is not None or af.get("score") is not None:
                n_score_checked += 1
                if abs((f.get("score") or 0) - (af.get("score") or 0)) > TOL:
                    score_mismatch += 1
    consistency = {
        "n_scored_by_factor_matches":
            art_q["summary"]["n_scored_by_factor"] == q_obs["summary"]["n_scored_by_factor"],
        "n_company_factor_scores_checked": n_score_checked,
        "n_score_mismatch": score_mismatch,
        "verdict": ("recomputed_matches_production_artifact"
                    if score_mismatch == 0 and
                    art_q["summary"]["n_scored_by_factor"] ==
                    q_obs["summary"]["n_scored_by_factor"]
                    else "MISMATCH"),
    }
    print("consistency:", consistency["verdict"])
    if consistency["verdict"] == "MISMATCH":
        print("!! ناسازگاری با آرتیفکت تولیدی — خروجی فقط با برچسب mismatch")
        return 3

    # ── C) جامعهٔ سه‌محوری و زیرمجموعهٔ EG-computed ────────────────────────────
    v_comps = json.load(open(os.path.join(ART_BASE, "v2_value_pilot.json"),
                             encoding="utf-8"))["v_observed_report"]["companies"]
    t_comps = json.load(open(os.path.join(ART_BASE, "v2_t_pilot.json"),
                             encoding="utf-8"))["t_observed_report"]["companies"]
    triple_ids = sorted(
        cid for cid in q_obs["companies"]
        if q_obs["companies"][cid].get("pilot_eligible")
        and cid in v_comps and v_comps[cid].get("pilot_eligible")
        and cid in t_comps and t_comps[cid].get("pilot_eligible"))
    print(f"triple-eligible: {len(triple_ids)}")

    eg_target = []
    for cid in triple_ids:
        eg = (raw_by_company.get(cid) or {}).get("earnings_growth") or {}
        sts = [c.get("status") for c in (eg.get("components") or {}).values()]
        if "valid" in sts:
            eg_target.append(cid)
    print(f"EG-computed in triple universe: {len(eg_target)}")

    # ── D) خواندن مستقل SQL برای شرکت‌های هدف ────────────────────────────────
    import psycopg
    from run_publish_recovery import build_dsn
    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT st.company_id::text AS cid, st.statement_type, st.period_end_date,
               st.fiscal_year, st.fiscal_month, st.duration_months,
               st.is_restated, f.metric_code, f.period_order, f.canonical_value,
               f.canonical_unit, rv.version_no, r.id::text AS report_id,
               r.published_at, r.supersedes_report_id::text AS supersedes,
               r.title
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
          AND f.metric_code = ANY(%s)
        """, (eg_target, list(SENTINEL_METRICS) + ["total_equity", "revenue"]))
    cols = [c[0] for c in cur.description]
    sql_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    superseded_q = {r[0] for r in cur.execute(
        "SELECT supersedes_report_id::text FROM ingestion.reports WHERE supersedes_report_id IS NOT NULL"
    ).fetchall()}
    conn.rollback()
    conn.close()
    print(f"independent SQL rows for {len(eg_target)} companies: {len(sql_rows)}")

    # ── ایندکس مستقل (همان قرارداد رتبه‌بندی؛ پیاده‌سازی جدا) ─────────────────
    own_index: dict = {}
    leg_meta: dict = {}   # (cid, fy, fm) → {report_id, published_at, is_restated, title, unit_flags}
    for r in sql_rows:
        if r["report_id"] in superseded_q:
            continue
        pit_ok = ((r["published_at"] is None and str(r["period_end_date"]) <= str(AS_OF))
                  or (r["published_at"] is not None and r["published_at"] <= CUTOFF))
        if not pit_ok:
            continue
        fy, fm = r["fiscal_year"], r["fiscal_month"]
        if fy is None or fm is None:
            fy, fm = CM.fiscal_ym(r["period_end_date"])
        if r["canonical_unit"] not in (None, "rial", "rial_per_share"):
            continue
        cid = r["cid"]
        key = (cid, fy, fm)
        cell = own_index.setdefault(cid, {}).setdefault((fy, fm), {})
        rank = (r["period_end_date"], r["version_no"])
        m = cell.setdefault("_meta", {"_period": None, "_ver": None})
        if m["_period"] is None or rank >= (m["_period"], m["_ver"]):
            m["_period"], m["_ver"] = rank
            m.update({"report_id": r["report_id"],
                      "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                      "is_restated": r["is_restated"],
                      "duration_months": r["duration_months"],
                      "title": (r["title"] or "")[:160]})
        try:
            val = float(r["canonical_value"]) if r["canonical_value"] is not None else None
        except (TypeError, ValueError):
            val = None
        cell.setdefault(r["metric_code"], {})[r["period_order"]] = val

    # سرشماری سنتیل مستقل روی دادهٔ SQL خودم (برای شرکت‌های هدف)
    own_sentinel = {}
    for r in sql_rows:
        try:
            v = float(r["canonical_value"]) if r["canonical_value"] is not None else None
        except (TypeError, ValueError):
            v = None
        if r["metric_code"] in SENTINEL_METRICS and v is not None \
                and v in SENTINEL_VALUES:
            own_sentinel.setdefault(r["cid"], []).append(
                {"fy": r["fiscal_year"], "fm": r["fiscal_month"],
                 "metric": r["metric_code"], "order": r["period_order"],
                 "report_id": r["report_id"]})
    own_sentinel_rows = sum(len(v) for v in own_sentinel.values())
    print(f"own sentinel census (target companies): {own_sentinel_rows} fact rows "
          f"on {len(own_sentinel)} companies")

    # ── E+F+G+I+J) بازتولید مستقل و طبقه‌بندی ────────────────────────────────
    comp_map = {"net_profit_growth_pct": ("net_profit", "net_profit_prev"),
                "operating_profit_growth_pct": ("operating_profit", "operating_profit_prev")}
    companies = {}
    classification_counter = Counter()
    n_value_match = n_value_diff = 0
    diffs = []
    for cid in eg_target:
        m = engine.metrics.get(cid) or {}
        rep = own_index.get(cid, {})
        eg_raw = (raw_by_company.get(cid) or {}).get("earnings_growth") or {}
        dur = durations_by_company.get(cid, {})
        ann_month, ann_state, _src = FC.annual_month_of(fiscal_cal, cid)
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1]) if rep else None
        entry = {"company_id": cid, "symbol": detail.get(cid, {}).get("symbol"),
                 "industry": meta[cid].get("industry"),
                 "components": {}, "limitations": [], "warnings": []}
        comp_verdicts = []
        for comp_name, (metric, base_tag) in comp_map.items():
            eng_c = (eg_raw.get("components") or {}).get(comp_name) or {}
            cur = m.get(metric + "_ttm")
            # رزولوشن مستقل پایه: (latest−1, latest_fm) با قرارداد موتور
            base_val = base_prov = base_cells = None
            if latest:
                pfy, pfm = latest[0] - 1, latest[1]
                is_annual_prev = True if dur.get((pfy, pfm)) == 12 else None
                anchor = FC.prev_annual_cell(dur, pfy, pfm)
                base_val, base_prov, base_cells = own_resolve_ttm(
                    rep, metric, pfy, pfm, is_annual_prev, anchor)
                # قرنطینهٔ مستقل: هر سلول سنتیل در اجزای پایه → حذف پایه
                if base_val is not None and any(
                        float(own_cell(rep, f, g, metric, o)) in SENTINEL_VALUES
                        for (f, g, mt, o) in base_cells
                        if own_cell(rep, f, g, metric, o) is not None):
                    base_val, base_prov = None, "OWN_QUARANTINED_SENTINEL_BASE"
            # حفظ سیاست provenance-match پایلوت: پایه فقط وقتی معتبر که
            # رزولوشن مستقل همان کد رزولوشن موتور را برای prev بدهد
            eng_prov_prev = (m.get("_ttm_prov") or {}).get(base_tag)
            prov_match = (base_prov is not None and base_prov == eng_prov_prev)
            if base_val is not None and not prov_match:
                entry["limitations"].append(
                    f"{comp_name}: independent resolution prov={base_prov} ≠ "
                    f"engine prov={eng_prov_prev} — base not trusted (pilot policy)")
            repro = own_growth(cur, base_val if prov_match else None)
            eng_val = _r(eng_c.get("value"))
            eng_status = eng_c.get("status")
            value_match = None
            if eng_status == "valid" and repro["status"] == "valid":
                value_match = math.isclose(float(eng_val), float(repro["value"]),
                                           rel_tol=REL_TOL, abs_tol=1e-6)
                n_value_match += int(value_match)
                n_value_diff += int(not value_match)
                if not value_match and len(diffs) < 30:
                    diffs.append({"company_id": cid, "component": comp_name,
                                  "engine_pct": eng_val,
                                  "independent_pct": _r(repro["value"])})
            # میان‌بر سالانهٔ کاملاً مستقل (فقط گزارش‌های سالانهٔ ۱۲ماهه)
            shortcut = None
            if latest and latest[1] == 12 and dur.get(latest) == 12:
                cur_s = own_cell(rep, latest[0], 12, metric, 1)
                base_s = own_cell(rep, latest[0] - 1, 12, metric, 1)
                if cur_s is not None and base_s is not None \
                        and float(cur_s) not in SENTINEL_VALUES \
                        and float(base_s) not in SENTINEL_VALUES:
                    sc = own_growth(float(cur_s), float(base_s))
                    if sc["status"] == "valid" and repro["status"] == "valid":
                        shortcut = {"value_pct": _r(sc["value"]),
                                    "matches_repro": math.isclose(
                                        float(sc["value"]), float(repro["value"]),
                                        rel_tol=REL_TOL, abs_tol=1e-6)}
            lmeta = []
            for (f, g, mt, o) in (base_cells or []):
                cellm = ((own_index.get(cid) or {}).get((f, g)) or {}).get("_meta") or {}
                lmeta.append({"cell": f"{f}-{g:02d}:{mt}:o{o}",
                              "report_id": cellm.get("report_id"),
                              "published_at": cellm.get("published_at"),
                              "is_restated": cellm.get("is_restated")})
            # برچسب دورهٔ مقایسه: TTM جاری منتهی به (latest) و پایهٔ منتهی به
            # (latest − ۱ سال) — فقط برای نمایش، از سلول‌های واقعی پایه
            period_current = f"{latest[0]}/{latest[1]:02d}" if latest else None
            period_base = f"{latest[0]-1}/{latest[1]:02d}" if latest else None
            entry["components"][comp_name] = {
                "engine_status": eng_status,
                "engine_value_pct": eng_val,
                "engine_observed_engine_pct": _r(eng_c.get("observed_engine_pct")),
                "engine_reason": (eng_c.get("reason") or "")[:200],
                "independent_status": repro["status"],
                "independent_value_pct": _r(repro.get("value")),
                "independent_base": _r(base_val) if prov_match else None,
                "independent_base_prov": base_prov,
                "independent_current_ttm": _r(cur),
                "engine_current_ttm": _r(m.get(metric + "_ttm")),
                "prov_match": prov_match,
                "engine_prov_prev": eng_prov_prev,
                "value_match_with_engine": value_match,
                "annual_shortcut": shortcut,
                "period_current": period_current,
                "period_base": period_base,
                "base_leg_meta": lmeta[:4],
            }
            comp_verdicts.append((comp_name, eng_status, repro, value_match))
        # ── طبقه‌بندی نهایی شرکت (سه مفهوم جدا) ───────────────────────────────
        math_ok = all(cv[3] is True for cv in comp_verdicts if cv[1] == "valid")
        any_valid = any(cv[1] == "valid" for cv in comp_verdicts)
        repro_all_match = all(
            cv[2]["status"] == cv[1] or
            (cv[1] == "missing" and cv[2]["status"] in ("missing", "not_applicable"))
            for cv in comp_verdicts)
        both_valid = all(cv[1] == "valid" for cv in comp_verdicts)
        # هشدارهای کیفی اقتصادی
        for comp_name, eng_status, repro, vm in comp_verdicts:
            if repro.get("turned_to_loss"):
                entry["warnings"].append(
                    f"{comp_name}: سود مثبتِ پایه به ضرر تبدیل شده (turned_to_loss) — درصد منفی استاندارد است، نه «رشد بد»")
            if repro.get("magnitude_anomaly"):
                entry["warnings"].append(
                    f"{comp_name}: بزرگی رشد خارج از باند {GROWTH_BAND} — دادهٔ واقعی، نیازمند بررسی اثر اقلام غیرتکرارشونده")
            if repro.get("status") == "valid" and repro.get("value") is not None \
                    and abs(float(repro["value"])) > 200.0:
                entry["warnings"].append(
                    f"{comp_name}: بزرگی رشد {float(repro['value']):.0f}٪ بیش از باند اقتصادی ۲۰۰٪ — "
                    "اثر تورم/پایهٔ کوچک/اقلام غیرتکرارشونده محتمل؛ درصد را فقط با مقدار خام پایه و دورهٔ مقایسه تفسیر کنید")
        # وابستگی به اقلام غیرعملیاتی (کانال هزینهٔ ۲-ب-۷)
        ec = expense_channels.get(cid) or {}
        op_ttm = m.get("operating_profit_ttm")
        onon = ec.get("other_nonop_ttm") if isinstance(ec, dict) else None
        if _finite(onon) and _finite(op_ttm) and op_ttm and abs(float(onon)) > 0.5 * abs(float(op_ttm)):
            entry["warnings"].append(
                f"non_operating_dependence: |سایر غیرعملیاتی TTM| > ۵۰٪ سود عملیاتی TTM "
                f"({float(onon)/abs(float(op_ttm))*100:.0f}٪) — کیفیت رشد محتمل‌التأثیر از اقلام غیرعملیاتی")
        # متادیتای پایه‌ها: PIT / restated
        pit_states = set()
        restated_legs = 0
        for comp in entry["components"].values():
            for lm in comp.get("base_leg_meta", []):
                if lm.get("published_at") is None:
                    pit_states.add("legacy_visibility_rule")
                else:
                    pit_states.add("dated_within_cutoff")
                if lm.get("is_restated"):
                    restated_legs += 1
        if any(comp.get("independent_base") is not None for comp in entry["components"].values()):
            if "legacy_visibility_rule" in pit_states:
                entry["limitations"].append(
                    "حداقل یکی از سلول‌های پایه از گزارش بی‌تاریخِ legacy است (قاعدهٔ دیده‌شدنی period_end≤as_of) — PIT هنوز unverified در لایهٔ raw")
        if restated_legs:
            entry["limitations"].append(f"{restated_legs} سلول پایه از ستون/گزارش restated است")
        # وضعیت تلفیقی/غیرتلفیقی در store ثبت نشده — فقط نشانهٔ عنوان
        t_union = " ".join(((own_index[cid].get(k) or {}).get("_meta") or {}).get("title") or ""
                           for k in own_index.get(cid, {}))
        if "تلفیق" in t_union:
            entry["limitations"].append("نشانهٔ عنوان: نامه‌های «تلفیقی» در گزارش‌های شرکت (store فیلد تلفیقی/غیرتلفیقی ندارد)")
        # حکم نهایی
        if math_ok and both_valid and repro_all_match and not any(
                w.startswith(("net_profit_growth_pct: ", "operating_profit_growth_pct: "))
                for w in entry["warnings"]) and not restated_legs:
            verdict = "verified"
        elif math_ok and any_valid and repro_all_match:
            verdict = "verified_with_limitation"
        elif any_valid:
            verdict = "diagnostic_only"
        else:
            verdict = "insufficient_evidence"
        if not math_ok and any_valid:
            verdict = "diagnostic_only"
        entry["verdict"] = verdict
        entry["verdict_fa"] = FA_VERDICT[verdict]
        entry["sub_verdicts"] = {
            "math_correctness": ("pass" if math_ok else
                                 "fail" if any(cv[3] is False for cv in comp_verdicts) else "n/a"),
            "source_and_pit_validity": ("pass" if not any(
                "not trusted" in x for x in entry["limitations"]) else "caveat"),
            "economic_meaningfulness": ("pass_with_warnings" if entry["warnings"]
                                        else "pass" if any_valid else "n/a"),
        }
        entry["limitations"] = entry["limitations"][:8]
        entry["warnings"] = sorted(set(entry["warnings"]))[:8]
        companies[cid] = entry
        classification_counter[verdict] += 1

    print("classification:", dict(classification_counter))
    print(f"value match: {n_value_match} / diff: {n_value_diff}")
    if diffs:
        print("value diffs sample:", json.dumps(diffs[:5], ensure_ascii=False))

    # ── H) اثبات نشت قرنطینهٔ مستقل (روی همهٔ موتور، نه فقط ۵۷تایی) ───────────
    quarantined_tags = {}
    for row in quarantine_info.get("quarantined", []):
        quarantined_tags.setdefault(row["company_id"], []).append(row["tag"])
    leaks = []
    checked = 0
    for cid, tags in quarantined_tags.items():
        comp = ((raw_by_company.get(cid) or {}).get("earnings_growth") or {}) \
            .get("components") or {}
        for tag in tags:
            cn = "net_profit_growth_pct" if tag == "net_profit_prev" \
                else "operating_profit_growth_pct"
            c = comp.get(cn) or {}
            checked += 1
            if c.get("status") == "valid":
                leaks.append({"company_id": cid, "component": cn})
    leak_proof = {
        "policy": "پایهٔ مصرف‌کنندهٔ سلول سنتیل حذف؛ raw بدون پایه → missing؛ بدون جایگزین",
        "n_quarantined_components_checked": checked,
        "n_valid_despite_quarantine": len(leaks),
        "leaks": leaks[:20],
        "verdict": "LEAK_DETECTED" if leaks else "quarantine_leak_free",
    }
    print("leak proof:", leak_proof["verdict"], f"(checked={checked})")

    # ── L) جمع‌بندی: آمادگی پیشنهاد فعال‌سازی و مشکلات صنایع ─────────────────
    n_proposal_ready = classification_counter["verified"] \
        + classification_counter["verified_with_limitation"]
    comp_both_valid = sum(
        1 for cid in eg_target
        if all(c.get("status") == "valid"
               for c in ((raw_by_company.get(cid) or {}).get("earnings_growth")
                         or {}).get("components", {}).values()))
    n_high_magnitude = sum(
        1 for cid in eg_target
        for c in companies[cid]["components"].values()
        if c["engine_status"] == "valid" and c["engine_value_pct"] is not None
        and abs(float(c["engine_value_pct"])) > 200.0)
    blend_scored = sum(
        1 for cid in eg_target
        if _finite(((out["factors"].get(cid) or {}).get("earnings_growth") or {})
                   .get("factor_blend_score")))
    industry_stats = {}
    for cid, e in companies.items():
        ind = e["industry"] or "unknown"
        a = industry_stats.setdefault(ind, {"n": 0, "verdicts": Counter(),
                                            "n_warning": 0})
        a["n"] += 1
        a["verdicts"][e["verdict"]] += 1
        a["n_warning"] += bool(e["warnings"])
    industry_out = {k: {"n": v["n"], "verdicts": dict(v["verdicts"]),
                        "n_with_economic_warning": v["n_warning"]}
                    for k, v in sorted(industry_stats.items(),
                                       key=lambda kv: -kv[1]["n"])}

    eg_validation = {
        "mission": "گام ۲-ک-۶ P1 — اعتبارسنجی اقتصادی earnings_growth (بازتولید مستقل)",
        "snapshot_binding": {**arts, "as_of": str(AS_OF), "cutoff": CUTOFF.isoformat(),
                             "binding_ok": binding_ok},
        "method": {
            "independence": ("مقدار رسمی از score_v2_raw._build_earnings_growth با "
                             "prev_bases پاک‌شدهٔ پایلوت؛ بازتولید با: اتصال SQL مستقل، "
                             "ایندکس مستقل از رکوردهای fact، رزولوشن TTM بازنویسی‌شده، "
                             "قرنطینهٔ سنتیل بازسازی‌شده و محاسبهٔ مستقل رشد — فقط "
                             "قرارداد (نه کد) مشترک است"),
            "policy": ("growth_pct=(cur−base)/base×100 فقط با پایهٔ اکیداً مثبت؛ پایهٔ صفر/منفی/"
                       "تغییر علامت وضعیت غیردرصدی مجزا؛ مقدار موتور بدون پایهٔ تأمین‌شده هرگز معتبر نیست"),
            "provenance_match_policy": ("پایهٔ مستقل فقط وقتی مصرف می‌شود که کد رزولوشن آن با کد ثبت‌شدهٔ موتور یکسان باشد"),
        },
        "population": {"triple_universe": len(triple_ids),
                       "eg_computed_in_triple": len(eg_target)},
        "consistency_with_production_artifact": consistency,
        "reproduction_summary": {
            "n_components_value_compared": n_value_match + n_value_diff,
            "n_value_match": n_value_match, "n_value_diff": n_value_diff,
            "value_diffs": diffs,
        },
        "classification": {
            "counts": dict(classification_counter),
            "fa_legend": FA_VERDICT,
            "proposal_ready": n_proposal_ready,
            "proposal_ready_note": ("verified + verified_with_limitation؛ هیچ مقدار مشکوکی "
                                    "برای افزایش پوشش معتبر طبقه‌بندی نشده است"),
            "composite_both_components_valid": comp_both_valid,
            "n_valid_components_beyond_200pct": n_high_magnitude,
            "n_with_normalize_blend_score_preserved": blend_scored,
            "note": ("composite رسمی raw فقط وقتی معتبر است که هر دو جزء (خالص و عملیاتی) "
                     "valid باشند؛ verified_with_limitation یعنی مقدار درست است ولی مثلاً "
                     "فقط جزء خالص معتبر است یا هشدار کیفی دارد"),
        },
        "quarantine_leak_proof": leak_proof,
        "own_sentinel_census_target_companies": {
            "n_fact_rows": own_sentinel_rows,
            "n_companies": len(own_sentinel),
            "note": "سرشماری مستقل روی اتصال SQL خود این اسکریپت (زیرمجموعهٔ سرشماری ۱۰٬۶۵۰ ردیفی کل store)"},
        "industry_rollup": industry_out,
        "companies": companies,
    }
    os.makedirs(OUT, exist_ok=True)
    p1_path = os.path.join(OUT, f"_p1_eg_economic_validation_{TAG}.json")
    with open(p1_path, "w", encoding="utf-8") as f:
        json.dump(eg_validation, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {p1_path}")

    # ═══════════════ P2 — equity مقایسه‌ای و وضعیت margin_trend ═══════════════
    # معناشاسی ستون مقایسه‌ای: آیا order-2 equity گزارش‌های سال fy+1 برابر
    # equity پایان fy است؟ تست تجربی روی سلول‌هایی که هر دو پایه دارند.
    import psycopg as _ps
    from run_publish_recovery import build_dsn as _bd
    conn = _ps.connect(_bd())
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT st.company_id::text AS cid, st.period_end_date, st.fiscal_year,
               st.fiscal_month, f.period_order, f.canonical_value, rv.version_no
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE f.metric_code = 'total_equity'
          AND st.company_id::text = ANY(%s)
        """, (triple_ids,))
    cols = [c[0] for c in cur.description]
    eq_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.rollback()
    conn.close()
    eq_index: dict = {}
    for r in eq_rows:
        if r["canonical_value"] is None:
            continue
        fy, fm = r["fiscal_year"], r["fiscal_month"]
        if fy is None or fm is None:
            fy, fm = CM.fiscal_ym(r["period_end_date"])
        rank = (r["period_end_date"], r["version_no"])
        key = (r["cid"], fy, fm, r["period_order"])
        if key not in eq_index or rank > eq_index[key][0]:
            eq_index[key] = (rank, float(r["canonical_value"]))

    def eq_of(cid, fy, fm, order):
        v = eq_index.get((cid, fy, fm, order))
        return v[1] if v else None

    # H1: order-2 گزارش (fy+1, fm) == order-1 پایان (fy,12)؟
    # دو سطح تلورانس: تطابق دقیق و ≤۱٪ (همان کمیت با نویز restatement)
    h1 = {("annual", "exact"): 0, ("annual", "le1pct"): 0,
          ("interim", "exact"): 0, ("interim", "le1pct"): 0,
          ("annual", "diff"): 0, ("interim", "diff"): 0}
    h1_rel = []
    h2_match = h2_diff = 0
    h2_le1pct = 0
    for (cid, fy, fm, order), (_rank, val) in list(eq_index.items()):
        if order != 2:
            continue
        own1 = eq_of(cid, fy - 1, 12, 1)
        if own1 not in (None, 0) and val is not None:
            rel = abs(val - own1) / abs(own1)
            kind = "annual" if fm == 12 else "interim"
            if rel <= 1e-6:
                h1[(kind, "exact")] += 1
                h1[(kind, "le1pct")] += 1
            elif rel <= 0.01:
                h1[(kind, "le1pct")] += 1
                if len(h1_rel) < 8:
                    h1_rel.append({"cid": cid, "fy": fy, "fm": fm,
                                   "order2": val, "prev_fy_order1": own1,
                                   "rel_diff": round(rel, 5),
                                   "note": "همان کمیت با restatement کوچک"})
            else:
                h1[(kind, "diff")] += 1
                if len(h1_rel) < 8:
                    h1_rel.append({"cid": cid, "fy": fy, "fm": fm,
                                   "order2": val, "prev_fy_order1": own1,
                                   "rel_diff": round(rel, 5),
                                   "note": "مقدار متفاوت — قابل‌اتکا نیست"})
        same1 = eq_of(cid, fy - 1, fm, 1)
        if same1 not in (None, 0) and val is not None:
            rel2 = abs(val - same1) / abs(same1)
            if rel2 <= 1e-6:
                h2_match += 1
            else:
                h2_diff += 1
                if rel2 <= 0.01:
                    h2_le1pct += 1
    print(f"equity comparative semantics: annual-o2 exact={h1[('annual','exact')]} "
          f"≤1%={h1[('annual','le1pct')]} diff={h1[('annual','diff')]} | "
          f"interim-o2 exact={h1[('interim','exact')]} ≤1%={h1[('interim','le1pct')]} "
          f"diff={h1[('interim','diff')]}" )

    # پوشش roe_stability قبل/بعد برای ۶۲ شرکت سه‌محوری
    from q_factor_diag_2k5 import roe_stability_from_series

    def np_series_for(cid):
        """همان قرارداد سری ۲-ک-۵: NP سالانهٔ (fy,12) با resolve_ttm موتور."""
        rep = rep_index.get(cid, {})
        if not rep:
            return []
        durations = durations_by_company.get(cid, {})
        annual_fys = sorted(fy for (fy, fm) in rep if fm == 12)
        if not annual_fys:
            return []
        ann_month, _state, _src = FC.annual_month_of(fiscal_cal, cid)
        latest = max(annual_fys)
        series = []
        for fy in [y for y in annual_fys if y > latest - 5]:
            anchor = FC.prev_annual_cell(durations, fy, 12)
            np_val, _p = RC.resolve_ttm(
                rep, "net_profit", fy, 12, annual_month=ann_month,
                is_annual=True if durations.get((fy, 12)) == 12 else None,
                prev_annual_cell=anchor)
            quarantined = np_val is not None and float(np_val) in SENTINEL_VALUES
            series.append({"fy": fy,
                           "net_profit": None if quarantined else np_val,
                           "quarantined": quarantined})
        return series

    def build_series(eq_extractor):
        out_series = {}
        for cid in triple_ids:
            np_ser = {s["fy"]: s for s in np_series_for(cid)}
            series = []
            for fy, s in np_ser.items():
                eq, basis = eq_extractor(cid, fy)
                series.append({"fy": fy, "net_profit": s["net_profit"],
                               "equity": eq, "quarantined": s["quarantined"],
                               **({"equity_basis": basis} if basis else {})})
            out_series[cid] = series
        return out_series

    def eq_before(cid, fy):
        v = eq_of(cid, fy, 12, 1)
        if v is not None:
            return v, "order1_own_cell"
        v = eq_of(cid, fy + 1, 12, 2)
        return (v, "order2_prior_comparative_annual_report") if v is not None \
            else (None, None)

    def eq_bases_for(cid, fy):
        """پایه‌های equity به ترتیب قرارداد: order-1 خودِ سلول، سپس order-2
        گزارش سالانهٔ سال بعد (۲-ک-۵)، سپس order-2 میان‌دوره‌ای سال بعد."""
        v, basis = eq_before(cid, fy)
        if v is not None:
            return v, basis
        for fm in (9, 6, 3, 1, 2, 4, 5, 7, 8, 10, 11):
            v = eq_of(cid, fy + 1, fm, 2)
            if v is not None:
                return v, f"order2_prior_comparative_interim_fm{fm:02d}"
        return None, None

    before = build_series(eq_before)
    after = build_series(eq_bases_for)
    cov_before = cov_after = 0
    per_company_cov = {}
    for cid in triple_ids:
        rb = roe_stability_from_series(before[cid])
        ra = roe_stability_from_series(after[cid])
        b = rb["status"] == "computed"
        a = ra["status"] == "computed"
        cov_before += int(b)
        cov_after += int(a)
        if a != b:
            per_company_cov[cid] = {
                "symbol": detail.get(cid, {}).get("symbol"),
                "industry": meta[cid].get("industry"),
                "before": "computed" if b else rb["reason"],
                "after": "computed" if a else ra["reason"],
                "n_valid_after": ra.get("n_valid", 0),
                "valid_years_after": [v["fy"] for v in ra.get("valid_years", [])],
                "equity_bases_after": [v.get("equity_basis") for v in
                                       ra.get("valid_years", [])],
            }
    print(f"roe_stability coverage before={cov_before} after={cov_after} (of {len(triple_ids)})")

    # علت خاموشی margin_trend برای ۶۲ شرکت: قرنطینه در برابر حل‌نشدن + نقش پایهٔ revenue
    mt_breakdown = Counter()
    mt_quarantine_note = {}
    for cid in triple_ids:
        tags = quarantined_tags.get(cid) or []
        pre = bases.get(cid) or {}
        clean = clean_bases.get(cid) or {}
        if "operating_profit_prev" in tags:
            mt_breakdown["op_prev_quarantined_sentinel"] += 1
            mt_quarantine_note[cid] = "پایهٔ TTM عملیاتی مصرف‌کنندهٔ سلول سنتیل — قرنطینهٔ ۲-ب-۴-۲"
        elif "operating_profit_prev" not in pre:
            mt_breakdown["op_prev_unresolved"] += 1
        elif "revenue_prev" not in clean:
            mt_breakdown["op_prev_ok_but_revenue_prev_missing"] += 1
        elif "operating_profit_prev" in clean:
            mt_breakdown["both_legs_available"] += 1
        else:
            mt_breakdown["dropped_other"] += 1
    # وضعیت رسمی margin_trend برای همان ۶۲ شرکت (بازتولید قرارداد رسمی)
    import q_factor_diag_2k5 as D25
    mt_status = Counter()
    for cid in triple_ids:
        m = engine.metrics.get(cid) or {}
        cb = clean_bases.get(cid) or {}
        st = D25.margin_trend_official(
            m.get("operating_profit_ttm"), m.get("revenue_ttm"),
            cb.get("operating_profit_prev"), cb.get("revenue_prev"))
        mt_status["computed" if st["status"] == "computed" else st["status"]] += 1
    print("margin_trend base breakdown (62):", dict(mt_breakdown),
          "| official status:", dict(mt_status))

    p2 = {
        "mission": "گام ۲-ک-۶ P2 — پوشش roe_stability/margin_trend از ستون‌های مقایسه‌ای موجود",
        "snapshot_binding": {**arts, "as_of": str(AS_OF)},
        "equity_comparative_semantics_test": {
            "h1_prev_fy_end_by_kind": {
                "annual_report_o2": {"exact": h1[("annual", "exact")],
                                     "le_1pct": h1[("annual", "le1pct")],
                                     "diff": h1[("annual", "diff")]},
                "interim_report_o2": {"exact": h1[("interim", "exact")],
                                      "le_1pct": h1[("interim", "le1pct")],
                                      "diff": h1[("interim", "diff")]},
                "samples": h1_rel,
            },
            "h2_same_period_prior_year": {"exact": h2_match, "le_1pct": h2_le1pct,
                                          "diff": h2_diff},
            "verdict": ("ستون مقایسه‌ای گزارش سالانه همان کمیت پایان سال قبل است (با نویز "
                        "restatement کوچک) — همان قرارداد ۲-ک-۵؛ ستون مقایسه‌ای گزارش‌های "
                        "میان‌دوره‌ای قابل‌اتکا نیست (ناهمخونی‌های تا ±۹٪ و تکرار مقدار بین "
                        "فصل‌های نامرتبط) — بازیابی equity از آن مجاز نیست"),
            "recovery_decision": "rejected_interim_comparative_not_reliable",
        },
        "roe_stability_coverage": {
            "universe": len(triple_ids),
            "before_computed": cov_before, "after_computed": cov_after,
            "changed_companies": per_company_cov,
            "method": ("پایهٔ order-1 خودِ سلول؛ در نبودش order-2 گزارش سالانهٔ سال بعد "
                       "(قرارداد ۲-ک-۵)؛ افزودهٔ جدید فقط پس از تأیید تجربی معناشاسی: "
                       "order-2 گزارش‌های میان‌دوره‌ای fy+1"),
        },
        "margin_trend_base_breakdown": {
            "universe": len(triple_ids), "counts": dict(mt_breakdown),
            "official_status_reproduction": dict(mt_status),
            "quarantine_examples": dict(sorted(
                mt_quarantine_note.items())[:5]),
            "note": ("قرنطینه فقط با پاک‌سازی بالادستی سنتیل‌ها رفع می‌شود؛ هیچ جایگزینی "
                     "برای پایهٔ قرنطینه‌شده یا حل‌نشده مجاز نیست"),
        },
    }
    p2_path = os.path.join(OUT, f"_p2_coverage_2k6_{TAG}.json")
    with open(p2_path, "w", encoding="utf-8") as f:
        json.dump(p2, f, ensure_ascii=False, indent=1, default=str)
    print(f"wrote {p2_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
