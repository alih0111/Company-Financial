#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""گام ۲-ک-۱۳ — افزایش واقعی پوشش Q/V از کدال (sandbox، فقط‌خواندنی).

هدف: برای نمادهایی که منبع legacy (miandore2) ترازنامه/جریان نقد/درآمد
آن‌ها را ندارد، صورت‌های مالی حسابرسی‌شدهٔ سالانه + میاندوره‌ای را از مسیرهای
عمومی کدال واکشی، پارس و به شکل «فکت» به موتور درون‌حافظه‌ای تزریق می‌کنیم؛
سپس خط لولهٔ رسمی Q (pilot_v2_qvt.run_pilot) و V (pilot_v2_value.run_value_pilot)
را روی همان موتور بازاجرا می‌کنیم.

قواعد:
  * هیچ نوشتن DB؛ هیچ backfill؛ هیچ تغییر snapshot رسمی.
  * PIT: فقط گزارش‌هایی که PublishDateTime آن‌ها ≤ cutoff است.
  * هیچ مقداری حدس زده نمی‌شود؛ متریک نامعلوم تزریق نمی‌شود.
  * تزریق فقط برای (شرکت، دوره، متریک، ترتیب)های «غایب» انجام می‌شود؛ مقدار
    legacy هرگز بازنویسی نمی‌شود.

زیرفرمان‌ها:
  fetch   <symbols-file>       واکشی+پارس+cache به JSON
  recompute <cache-file>       تزریق + بازاجرای Q/V + خروجی گزارش
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANA = ROOT / "canonical_postgres_v1_2_1" / "analytics_canonical_v1"
for p in (str(Path(__file__).resolve().parent), str(ANA),
          str(ROOT / "canonical_postgres_v1_2_1" / "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import codal_fs_fetch as F  # noqa: E402
import codal_fs_parse as P  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)
SNAP = ROOT / "provenance_v1" / "output" / "exp_2k13_codal"
RAW = SNAP / "raw"
CACHE = SNAP / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

# متریک‌های «جریان/انباشتی» که order3 (سال مالی قبل) لازم دارند.
FLOW = {"revenue", "net_profit", "operating_profit", "operating_cash_flow", "eps"}
PER_SHARE = {"eps", "operating_eps"}


def _conn():
    import psycopg
    import re
    txt = (ROOT / "go-app" / ".env").read_text(encoding="utf-8")
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    cn = psycopg.connect(d, connect_timeout=20)
    cn.execute("SET default_transaction_read_only = on")
    return cn


def company_universe() -> list[dict]:
    cn = _conn()
    c = cn.cursor()
    c.execute("""SELECT co.id::text, co.display_name, s.codal_symbol
                 FROM core.companies co LEFT JOIN core.securities s
                   ON s.company_id = co.id AND s.is_primary
                 ORDER BY co.display_name""")
    out = [{"company_id": r[0], "display_name": r[1], "symbol": r[2]} for r in c.fetchall()]
    cn.close()
    return out


# ── ساخت فکت از گزارش‌های پارس‌شدهٔ کدال ─────────────────────────────────────
def facts_from_company(parsed: dict, company_id: str) -> list[dict]:
    """parsed = {"annual":[{...period_end, statements...}], "interim":[...]}

    ساختار سه‌ستونی (هم‌شکل با miandore2) بازسازی می‌شود:
      order1 = ستون دورهٔ جاری گزارش
      order2 = ستون دورهٔ مشابه سال قبل (ستون دوم گزارش)
      order3 = مقدار «سال مالی قبل» = مقدار order1 آخرین گزارش سالانه‌ای که
               period_end آن ≤ دورهٔ این سلول است (بدون فرض ماه ۱۲).
    """
    facts: list[dict] = []
    annuals = []
    for a in parsed.get("annual", []):
        if a.get("period_end") and a.get("statements"):
            annuals.append(a)
    annuals.sort(key=lambda a: a["period_end"])

    def annual_first_before(pe_iso: str, stype: str, metric: str):
        best = None
        for a in annuals:
            if a["period_end"] <= pe_iso:
                v = (a["statements"].get(stype) or {}).get(metric, {}).get(1)
                if v is not None:
                    best = v
            else:
                break
        return best

    def emit(stype, pe, pub, metric, order, value, tracing):
        facts.append({"statement_type": stype, "period_end_date": pe,
                      "publish_date": pub, "metric_code": metric,
                      "period_order": order, "value": value, "tracing_no": tracing})

    for a in annuals:
        pe = a["period_end"]
        for stype, mm in a["statements"].items():
            for metric, orders in mm.items():
                if orders.get(1) is not None:
                    emit(stype, pe, a.get("publish_date"), metric, 1, orders[1], a["tracing_no"])
                if orders.get(2) is not None:
                    emit(stype, pe, a.get("publish_date"), metric, 2, orders[2], a["tracing_no"])
    for it in parsed.get("interim", []):
        pe = it.get("period_end")
        if not pe:
            continue
        for stype, mm in it["statements"].items():
            for metric, orders in mm.items():
                if orders.get(1) is not None:
                    emit(stype, pe, it.get("publish_date"), metric, 1, orders[1], it["tracing_no"])
                if orders.get(2) is not None:
                    emit(stype, pe, it.get("publish_date"), metric, 2, orders[2], it["tracing_no"])
                if stype in ("income_statement", "cash_flow"):
                    fy_prev = annual_first_before(pe, stype, metric)
                    if fy_prev is not None:
                        emit(stype, pe, it.get("publish_date"), metric, 3, fy_prev, it["tracing_no"])
    return facts


def cmd_fetch(args):
    sys.stdout.reconfigure(encoding="utf-8")
    symbols = [s.strip() for s in Path(args.symbols_file).read_text(encoding="utf-8").splitlines()
               if s.strip() and not s.startswith("#")]
    universe = {u["symbol"]: u for u in company_universe()}
    manifest = []
    done = 0
    for sym in symbols:
        cf = CACHE / f"{sym}.json"
        if cf.exists() and not args.refresh:
            try:
                prev = json.loads(cf.read_text(encoding="utf-8"))
                if prev.get("ok"):
                    done += 1
                    continue  # resumable: از قبل کامل است
            except Exception:
                pass
        u = universe.get(sym)
        rec = {"symbol": sym, "company_id": u["company_id"] if u else None, "errors": []}
        try:
            letters_cache = RAW / f"{sym}_letters.json"
            cached = None
            if letters_cache.exists() and not args.refresh:
                cached = json.loads(letters_cache.read_text(encoding="utf-8"))
                if cached and any(isinstance(x, dict) and "__error__" in x for x in cached):
                    cached = None  # خطای ذخیره‌شده را استفاده نکن
            if cached is not None:
                letters = cached
            else:
                letters = F.search_symbol(sym, pages=args.pages)
                if not any(isinstance(x, dict) and "__error__" in x for x in letters):
                    letters_cache.write_text(json.dumps(letters, ensure_ascii=False), encoding="utf-8")
                else:
                    rec["errors"].append("search: " + str(letters[0].get("__error__")))
            sel = F.select_reports(letters, CUTOFF, max_interim=args.max_interim)
            parsed = {"annual": [], "interim": []}
            for kind in ("annual", "interim"):
                for r in sel[kind]:
                    cache_html = RAW / f"{sym}_{r['tracing_no']}.html"
                    if cache_html.exists() and not args.refresh:
                        got = {"ok": True, "via": "cache", "html": cache_html.read_text(encoding="utf-8")}
                    else:
                        got = F.fetch_report_html(r)
                    if not got.get("ok"):
                        rec["errors"].append({"tracing": r["tracing_no"], "why": got.get("error") or got.get("note")})
                        continue
                    pr = P.parse_report(got["html"])
                    # دوره از سرصفحهٔ صورت سود و زیان (یا سرصفحهٔ اولین صورت)
                    jh = pr["period_headers"].get("income_statement") or \
                        next(iter(pr["period_headers"].values()), None)
                    if got.get("via") != "cache":
                        cache_html.write_text(got["html"], encoding="utf-8")
                    parsed[kind].append({
                        "tracing_no": r["tracing_no"], "title": r["title"],
                        "publish_date": r["publish_date"], "period_end": r["period_end"],
                        "period_end_jalali": (list(jh[0]) if jh else None),
                        "via": got.get("via"), "statements": pr["statements"],
                        "consolidation": pr.get("consolidation", {}),
                    })
            # تزریق مرجع شرکت
            facts = facts_from_company(parsed, rec["company_id"]) if rec["company_id"] else []
            rec["n_facts"] = len(facts)
            rec["annual_periods"] = [a["period_end"] for a in parsed["annual"]]
            rec["interim_periods"] = [i["period_end"] for i in parsed["interim"]]
            rec["facts"] = facts
            rec["parsed"] = parsed
            rec["ok"] = bool(facts)
        except Exception as e:
            rec["ok"] = False
            rec["errors"].append(f"{type(e).__name__}: {e}")
        (CACHE / f"{sym}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        nmetrics = sum(len(mm) for a in rec.get("parsed", {}).get("annual", []) for mm in a["statements"].values())
        print(f"{sym:14s} ok={rec.get('ok')} facts={rec.get('n_facts')} "
              f"annual={rec.get('annual_periods')} interim={rec.get('interim_periods')} "
              f"errors={len(rec['errors'])}")
        manifest.append({"symbol": sym, "ok": rec.get("ok"), "n_facts": rec.get("n_facts"),
                         "annual_periods": rec.get("annual_periods"),
                         "interim_periods": rec.get("interim_periods"),
                         "errors": rec["errors"]})
        time.sleep(args.delay)
    (SNAP / "fetch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nfetched {len(symbols)} symbols; manifest -> {SNAP/'fetch_manifest.json'}")

def _title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return P.norm(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""


def _kind_from_title(title: str) -> str:
    t = title.replace("\u200c", "")
    if "میاندوره" in t or "میان دوره" in t or re.search(r"دوره\s*\d+\s*ماهه", t):
        return "interim"
    return "annual"


def cmd_rebuild(args):
    """cache را از HTMLهای خام ذخیره‌شده بازمی‌سازد (بدون شبکه).

    طبقه‌بندی سالانه/میاندوره از <title> صفحه؛ دوره از سرصفحهٔ صورت‌ها.
    publish_date از HTML در دسترس نیست، پس None می‌ماند و موتور همان قاعدهٔ
    مستند خودش را به‌کار می‌برد: published_at NULL → period_end <= as_of.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    symbols = [s.strip() for s in Path(args.symbols_file).read_text(encoding="utf-8").splitlines()
               if s.strip() and not s.startswith("#")]
    universe = {u["symbol"]: u for u in company_universe()}
    for sym in symbols:
        u = universe.get(sym)
        files = sorted(RAW.glob(f"{sym}_*.html"))
        rec = {"symbol": sym, "company_id": u["company_id"] if u else None, "errors": [],
               "facts": [], "parsed": {"annual": [], "interim": []}, "ok": False}
        for f in files:
            if f.name.startswith("smoke_"):
                continue
            try:
                tracing = int(f.stem.rsplit("_", 1)[1])
            except Exception:
                continue
            html = f.read_text(encoding="utf-8")
            pr = P.parse_report(html)
            if not pr["statements"]:
                rec["errors"].append({"tracing": tracing, "why": "no statement tables parsed"})
                continue
            jh = pr["period_headers"].get("income_statement") or \
                next(iter(pr["period_headers"].values()), None)
            kind = P.duration_label(html, jh[0] if jh else None) or "annual"
            rec["parsed"][kind].append({
                "tracing_no": tracing, "title": _title_of(html), "publish_date": None,
                "period_end": None, "period_end_jalali": (list(jh[0]) if jh else None),
                "via": "cache", "statements": pr["statements"],
                "consolidation": pr.get("consolidation", {}),
            })
        # period_end میلادی از تاریخ جلالی
        for kind in ("annual", "interim"):
            for r in rec["parsed"][kind]:
                jy = r["period_end_jalali"]
                if jy:
                    import jdatetime
                    r["period_end"] = jdatetime.date(*jy).togregorian().isoformat()
        rec["facts"] = facts_from_company(rec["parsed"], rec["company_id"]) if rec["company_id"] else []
        rec["n_facts"] = len(rec["facts"])
        rec["annual_periods"] = [a["period_end"] for a in rec["parsed"]["annual"]]
        rec["interim_periods"] = [i["period_end"] for i in rec["parsed"]["interim"]]
        rec["ok"] = bool(rec["facts"])
        (CACHE / f"{sym}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{sym:14s} rebuild ok={rec['ok']} facts={rec['n_facts']} "
              f"annual={rec['annual_periods']} interim={rec['interim_periods']} err={len(rec['errors'])}")


def cmd_targets(args):
    """نمادهای نیازمند تکمیل: خانوادهٔ general که Q یا V آن‌ها واجد شرایط نیست."""
    sys.stdout.reconfigure(encoding="utf-8")
    q = json.loads((ANA / "output" / "v2_q_observed_report.json").read_text(encoding="utf-8"))
    v = json.loads((ANA / "output" / "v2_value_pilot.json").read_text(encoding="utf-8"))
    t = json.loads((ANA / "output" / "v2_t_pilot.json").read_text(encoding="utf-8"))
    qc = q["companies"]
    vc = v["v_observed_report"]["companies"]
    tc = t["t_observed_report"]["companies"]
    sym_of = {cid: (qc[cid].get("symbol") or "") for cid in qc}
    rows = []
    for cid, rec in qc.items():
        if rec.get("model_family") != "general":
            continue
        qe = bool(rec.get("pilot_eligible"))
        ve = bool(vc.get(cid, {}).get("pilot_eligible"))
        te = bool(tc.get(cid, {}).get("pilot_eligible"))
        sym = sym_of.get(cid) or ""
        if qe and ve and te:
            continue
        rows.append((sym, cid, qe, ve, te))
    rows.sort()
    out = SNAP / "target_symbols.txt"
    out.write_text("\n".join(r[0] for r in rows if r[0]) + "\n", encoding="utf-8")
    need_q_or_v = [r for r in rows if not (r[2] and r[3])]
    print(f"targets (general, not triple-eligible): {len(rows)}")
    print(f"  of which need Q or V: {len(need_q_or_v)}")
    print(f"  blocked only by T (Q&V ok): {len([r for r in rows if r[2] and r[3] and not r[4]])}")
    print(f"-> {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("fetch")
    pf.add_argument("symbols_file")
    pf.add_argument("--pages", type=int, default=3)
    pf.add_argument("--max-interim", type=int, default=4)
    pf.add_argument("--delay", type=float, default=3.0)
    pf.add_argument("--refresh", action="store_true")
    pf.set_defaults(func=cmd_fetch)
    pb = sub.add_parser("rebuild")
    pb.add_argument("symbols_file")
    pb.set_defaults(func=cmd_rebuild)
    pt = sub.add_parser("targets")
    pt.set_defaults(func=cmd_targets)
    pr = sub.add_parser("recompute")
    pr.add_argument("--out-tag", default="exp_2k13_sandbox")
    pr.set_defaults(func=cmd_recompute)
    args = ap.parse_args()
    return args.func(args)


# ── تزریق و بازاجرا ─────────────────────────────────────────────────────────
ALLOWED_METRICS = {
    "balance_sheet": {"total_assets", "current_assets", "total_liabilities",
                      "current_liabilities", "total_equity"},
    "income_statement": {"revenue", "operating_profit", "finance_cost",
                         "other_non_operating", "net_profit", "eps",
                         "operating_eps", "capital"},
    "cash_flow": {"operating_cash_flow"},
}


def _load_caches() -> list[dict]:
    out = []
    for f in sorted(CACHE.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        if rec.get("ok") and rec.get("facts"):
            out.append(rec)
    return out


def _inject(engine, caches: list[dict]) -> dict:
    """فکت‌های کدال را به engine.stmt اضافه می‌کند (فقط متریک-دوره‌های غایب).

    اگر برای یک (شرکت، دوره، متریک) هر ترتیبی از قبل (legacy) موجود باشد،
    کل آن متریک-دوره رد می‌شود تا هرگز مقدار legacy و کدال در یک ردیف مخلوط
    نشوند (سازگاری نسخه/منبع درون هر سلول حفظ شود).
    """
    existing_pm = {(r["company_id"], r["period_end_date"], r["metric_code"])
                   for r in engine.stmt}
    added = skipped_existing = skipped_notallowed = skipped_badperiod = 0
    per_company = {}
    for rec in caches:
        cid = rec["company_id"]
        for f in rec["facts"]:
            stype, metric, order = f["statement_type"], f["metric_code"], int(f["period_order"])
            if metric not in ALLOWED_METRICS.get(stype, set()):
                skipped_notallowed += 1
                continue
            try:
                pe = dt.date.fromisoformat(f["period_end_date"])
            except Exception:
                skipped_badperiod += 1
                continue
            if pe > AS_OF:
                skipped_badperiod += 1
                continue
            pm = (cid, pe, metric)
            if pm in existing_pm:
                skipped_existing += 1
                continue
            per_share = metric in PER_SHARE
            canon = float(f["value"]) if per_share else float(f["value"]) * 1_000_000.0
            col = CUTOFF
            if f.get("publish_date"):
                try:
                    col = dt.datetime.combine(dt.date.fromisoformat(f["publish_date"]),
                                              dt.time(23, 59), tzinfo=dt.timezone.utc)
                except Exception:
                    col = CUTOFF
            engine.stmt.append({
                "company_id": cid, "statement_type": stype, "period_end_date": pe,
                "fiscal_year": None, "fiscal_month": None, "is_restated": False,
                "version_no": 1, "collected_at": col,
                "metric_code": metric, "period_order": order,
                "canonical_value": canon,
                "canonical_unit": "rial_per_share" if per_share else "rial",
                "report_id": f"codal-2k13-{cid}-{pe.isoformat()}-{f['tracing_no']}",
            })
            added += 1
            per_company[cid] = per_company.get(cid, 0) + 1
    return {"added": added, "skipped_existing": skipped_existing,
            "skipped_notallowed": skipped_notallowed, "skipped_badperiod": skipped_badperiod,
            "n_companies": len(per_company),
            "companies_with_facts": sorted(per_company.keys())}


def cmd_recompute(args):
    sys.stdout.reconfigure(encoding="utf-8")
    # موتور canonical باید پیش از import به مخزن shadow وصل شود (PILOT_DB در زمان
    # import خوانده می‌شود). فقط‌خواندنی.
    os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
    import compute_metrics as CM
    import pilot_v2_qvt as PQ
    import pilot_v2_value as PV
    import expense_ttm_recovery as REC
    from pilot_v2_qvt import fiscal_calendar_for

    caches = _load_caches()
    print(f"caches with facts: {len(caches)}")

    engine = CM.Engine(AS_OF, CUTOFF)
    engine.compute()
    engine.load = lambda *a, **k: None  # در حافظه قفل شود

    def q_run(tag):
        rep_index = engine.report_index()
        durations, _ = fiscal_calendar_for(engine)
        rec = REC.recover_expense_order3(rep_index, durations, AS_OF, CUTOFF)
        report = PQ.run_pilot(AS_OF, CUTOFF, sample_limit=10, engine=engine, expense_recovery=rec)
        qo = report["q_observed"]
        return qo, {c for c, e in qo["companies"].items() if e.get("pilot_eligible")}

    def v_run():
        rep = PV.run_value_pilot(AS_OF, CUTOFF, engine=engine)
        vrep = rep["v_observed_report"]["companies"]
        return rep, {c for c, e in vrep.items() if e.get("pilot_eligible")}

    base_qo, base_q = q_run("base")
    base_v_rep, base_v = v_run()
    print(f"BASELINE  Q-eligible={len(base_q)}  V-eligible={len(base_v)}")

    inj = _inject(engine, caches)
    print(f"injected facts: {inj['added']} (existing {inj['skipped_existing']}, "
          f"bad {inj['skipped_badperiod']}, notallowed {inj['skipped_notallowed']}) "
          f"across {inj['n_companies']} companies")

    exp_qo, exp_q = q_run("exp")
    exp_v_rep, exp_v = v_run()
    print(f"EXPANDED  Q-eligible={len(exp_q)}  V-eligible={len(exp_v)}")
    print(f"  Q gained {len(exp_q - base_q)}")
    print(f"  V gained {len(exp_v - base_v)}")

    # T از آرتیفکت رسمی (تغییرناپذیر) — فقط برای شمارش سه‌محوری
    t_path = ANA / "output" / "v2_t_pilot.json"
    T = json.loads(t_path.read_text(encoding="utf-8"))["t_observed_report"]["companies"]
    tset = {c for c, e in T.items() if e.get("pilot_eligible")}
    base_triple = base_q & base_v & tset
    exp_triple = exp_q & exp_v & tset
    print(f"  T-eligible (official)={len(tset)}")
    print(f"  TRIPLE baseline={len(base_triple)}  expanded={len(exp_triple)}  "
          f"gained={len(exp_triple - base_triple)} lost={len(base_triple - exp_triple)}")

    out = {
        "stage": "exp_2k13_codal_expansion",
        "as_of": AS_OF.isoformat(), "cutoff": CUTOFF.isoformat(),
        "note": "sandbox only — no DB write, no official snapshot overwrite; "
                "T reused from the immutable official artifact",
        "injection": inj,
        "baseline": {"q_eligible": len(base_q), "v_eligible": len(base_v),
                     "t_eligible": len(tset), "triple": len(base_triple)},
        "expanded": {"q_eligible": len(exp_q), "v_eligible": len(exp_v),
                     "t_eligible": len(tset), "triple": len(exp_triple)},
        "q_gained": sorted(exp_q - base_q), "v_gained": sorted(exp_v - base_v),
        "triple_gained": sorted(exp_triple - base_triple),
        "triple_lost": sorted(base_triple - exp_triple),
    }
    (SNAP / "expansion_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # بستهٔ آزمایشی: آرتیفکت‌های Q/V بازمحاسبه‌شده + T رسمی کپی‌شده (بدون overwrite)
    bundle = SNAP / f"bundle_{args.out_tag}"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "v2_q_observed_report.json").write_text(json.dumps(exp_qo, ensure_ascii=False, default=str), encoding="utf-8")
    (bundle / "v2_value_pilot.json").write_text(json.dumps(exp_v_rep, ensure_ascii=False, default=str), encoding="utf-8")
    import shutil
    shutil.copyfile(t_path, bundle / "v2_t_pilot.json")
    (bundle / "README.txt").write_text(
        "snapshot آزمایشی ۲-ک-۱۳ (sandbox) — Q/V با فکت‌های بازپرکردهٔ کدال بازمحاسبه شده؛\n"
        "T عیناً همان آرتیفکت رسمی و تغییرناپذیر است. هیچ فایل رسمی overwrite نشده.\n"
        "برای نمایش روی /ranking: QVT_V2_ARTIFACT_DIR=<this dir> را به go-app بدهید.\n",
        encoding="utf-8")

    # رتبه‌بندی آزمایشی بر پایهٔ سه‌محوریِ گسترده (برای گزارش/صفحه)
    def pts(companies, cid, key):
        r = companies.get(cid) or {}
        v = r.get(key)
        return float(v) if isinstance(v, (int, float)) else None
    overlay = []
    for cid in exp_triple:
        qp = pts(exp_qo["companies"], cid, "q_observed_points")
        # V report ساختارش v_observed_report است
        vp = pts(exp_v_rep["v_observed_report"]["companies"], cid, "v_observed_points")
        tp = pts(T, cid, "t_observed_points")
        sym = (exp_qo["companies"].get(cid) or {}).get("symbol")
        overlay.append({"company_id": cid, "symbol": sym, "q": qp, "v": vp, "t": tp,
                        "score": None if None in (qp, vp, tp) else round(qp + vp + tp, 1),
                        "in_official_triple": cid in base_triple})
    overlay.sort(key=lambda r: (-(r["score"] or -1), r["symbol"] or ""))
    for i, r in enumerate(overlay):
        r["rank"] = i + 1
    out["triple_overlay_top"] = overlay[:15]
    (SNAP / "expansion_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("TOP (expanded triple):")
    for r in overlay[:10]:
        print(f"  {r['rank']:2d}. {r['symbol']:10s} score={r['score']} (q={r['q']:.1f} v={r['v']:.1f} t={r['t']:.1f})"
              + ("  [was in official 62]" if r["in_official_triple"] else "  [NEW]"))
    print(f"report -> {SNAP/'expansion_report.json'}")
    print(f"bundle -> {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
