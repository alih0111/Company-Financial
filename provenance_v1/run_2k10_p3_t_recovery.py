#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P3 — بازیابی آزمایشی T برای ۳۲ شرکت با شواهد اقدام شرکتی واقعی.

روش (کاملاً فقط‌خواندنی، بدون backfill، بدون overwrite):
  ۱) موتور canonical با همان as-of/cutoff بارگذاری می‌شود و خط لولهٔ رسمی T
     (pilot_v2_t.run_t_pilot) اجرا می‌شود → تعداد پایهٔ T-eligible (کنترل).
  ۲) سری قیمت *تعدیل‌شدهٔ فروشنده* برای ۲۶ شرکت دارای گپ: ضرایب
     market.corporate_actions با is_confirmed=True و adjustment_evidence_status
     =CONFIRMED روی سری اعمال می‌شود (adj(d) = close(d)·Π{f: action_date>d}).
     هیچ ضریب حدسی ساخته نمی‌شود؛ فقط شواهد تأییدشدهٔ مخزن.
  ۳) خط لولهٔ T دوباره اجرا می‌شود → تعداد واقعی شرکت‌هایی که به T-eligible
     تبدیل شدند (پاسخ عددی، نه برآورد).
  ۴) ۶ شرکت با تاریخچهٔ کوتاه: آیا ردیف قیمت معتبر قدیمی‌تر واقعاً موجود است؟

خروجی: provenance_v1/output/p3_t_recovery_2k10_<TAG>.json
"""

import datetime as dt
import json
import math
import os
import re
import sys
from collections import Counter
from decimal import Decimal

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANA = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1")
OUT = os.path.join(ROOT, "provenance_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)

for p in (ANA, os.path.join(ROOT, "canonical_postgres_v1_2_1", "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

# موتور canonical به DB «shadow» وصل می‌شود (همان مخزنی که جدول‌های market/core
# را دارد). این باید پیش از import compute_metrics تنظیم شود چون PILOT_DB در
# زمان import خوانده می‌شود. اتصال فقط‌خواندنی است.
os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")

import compute_metrics as CM  # noqa: E402
import pilot_v2_t as PT  # noqa: E402
import pilot_v2_value as PV  # noqa: E402
import score_v2_t_raw as TRW  # noqa: E402


def build_dsn():
    txt = open(os.path.join(ROOT, "go-app", ".env"), encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


conn = psycopg.connect(build_dsn(), connect_timeout=20)
conn.execute("SET default_transaction_read_only = on")

recov = json.load(open(os.path.join(OUT, f"recovery_2k9_{TAG}.json"), encoding="utf-8"))
trows = recov["priority1_T_recovery"]["rows"]
gap = [x for x in trows if x.get("blocking_is_gap")]
short = [x for x in trows if x.get("blocking_is_short_history")]
target_ids = {x["company_id"] for x in gap}
sec_of = {x["company_id"]: x["primary_security"] for x in gap}

# ── اقدامات شرکتی تأییدشده برای امنیت‌های هدف ───────────────────────────────
acts = {}
for cid in target_ids:
    sid = sec_of[cid]
    if not sid:
        acts[cid] = []
        continue
    rows = conn.execute("""
        SELECT action_date, adjustment_factor FROM market.corporate_actions
        WHERE security_id=%s AND is_confirmed AND adjustment_evidence_status='CONFIRMED'
          AND adjustment_factor IS NOT NULL AND action_date <= %s
        ORDER BY action_date""", (sid, AS_OF)).fetchall()
    acts[cid] = [(r[0], float(r[1])) for r in rows]


def adjust_closes(prices, cid, sid, actions):
    """adj(d) = close(d) · Π{f : action_date > d} برای همان امنیت."""
    if not actions:
        return 0
    n_changed = 0
    for p in prices:
        if p.get("security_id") != sid:
            continue
        d = p.get("trade_date")
        if not isinstance(d, dt.date):
            continue
        c = p.get("closing_price_rial")
        if c is None:
            continue
        f = 1.0
        for ad, af in actions:
            if ad > d:
                f *= af
        if abs(f - 1.0) > 1e-12:
            p["closing_price_rial"] = float(c) * f
            if "last_price_rial" in p and p["last_price_rial"] is not None:
                p["last_price_rial"] = float(p["last_price_rial"]) * f
            n_changed += 1
    return n_changed


q_eligible, q_diag = PV.load_q_eligible(
    __import__("pathlib").Path(os.path.join(ANA, "output", "v2_q_observed_report.json")))
v_eligible, v_diag = PT.load_v_eligible(
    __import__("pathlib").Path(os.path.join(ANA, "output", "v2_value_pilot.json")))


def run(engine):
    rep = PT.run_t_pilot(AS_OF, CUTOFF, engine=engine, q_eligible=q_eligible, v_eligible=v_eligible)
    ts = rep["t_observed_report"]
    comps = ts["companies"]
    elig = {c for c, e in comps.items() if e.get("pilot_eligible")}
    raw_valid = {}
    for c, e in comps.items():
        for fid, f in (e.get("factors") or {}).items():
            if f.get("raw_status") == "valid":
                raw_valid.setdefault(fid, set()).add(c)
    return rep, elig, raw_valid, ts.get("summary", {})


print("loading engine (read-only)...")
eng = CM.Engine(AS_OF, CUTOFF)
eng.compute()
_load = eng.load
eng.load = lambda *a, **k: None  # freeze DB load; compute() rebuilds from in-memory rows

base_rep, base_elig, base_rawvalid, base_summary = run(eng)
print("baseline T eligible:", len(base_elig), "| artifact says 62")

# کنترل: تطبیق با آرتیفکت رسمی
art = json.load(open(os.path.join(ANA, "output", "v2_t_pilot.json"), encoding="utf-8"))
art_elig = {c for c, e in art["t_observed_report"]["companies"].items() if e.get("pilot_eligible")}
control_match = base_elig == art_elig
print("baseline == artifact:", control_match, "| sym diff:", len(base_elig ^ art_elig))

# ── اعمال تعدیل اقدامات شرکتی روی ۲۶ شرکت و اجرای مجدد ─────────────────────
changed_counts = {}
for cid in target_ids:
    sid = sec_of.get(cid)
    changed_counts[cid] = adjust_closes(eng.prices, cid, sid, acts.get(cid, []))

exp_rep, exp_elig, exp_rawvalid, exp_summary = run(eng)
print("experimental T eligible:", len(exp_elig))

recovered = sorted(exp_elig - base_elig)
lost = sorted(base_elig - exp_elig)
recovered_of_26 = sorted(set(recovered) & target_ids)

# ── ۶ شرکت تاریخچهٔ کوتاه: آیا دادهٔ قدیمی‌تر واقعاً هست؟ ────────────────────
REF6 = dt.date(2026, 4, 8)
short_probe = []
for x in short:
    sid = x["primary_security"]
    mn = conn.execute("""SELECT min(trade_date), count(*)
        FROM market.price_observations WHERE security_id=%s AND collected_at<=%s AND trade_date<=%s""",
        (sid, CUTOFF, REF6)).fetchone()
    before_ref = conn.execute("""SELECT count(*) FROM market.price_observations
        WHERE security_id=%s AND collected_at<=%s AND trade_date<=%s""",
        (sid, CUTOFF, REF6)).fetchone()[0]
    short_probe.append({
        "company_id": x["company_id"], "symbol": x["symbol"],
        "earliest_trade_date": str(mn[0]) if mn[0] else None,
        "n_rows_at_or_before_ref6": before_ref,
        "artifact_cause": x.get("cause"),
        "recoverable_from_existing_store": bool(before_ref > 0),
    })

# خروجی مسیرهای گپ هر شرکت
def raw_reason(comp, fid):
    return (((comp or {}).get("factors") or {}).get(fid) or {}).get("validation_reason")

base_comps = base_rep["t_observed_report"]["companies"]
exp_comps = exp_rep["t_observed_report"]["companies"]
gap_detail = []
for cid in sorted(target_ids):
    sym = next((x["symbol"] for x in gap if x["company_id"] == cid), cid)
    gap_detail.append({
        "company_id": cid, "symbol": sym,
        "n_actions_applied": sum(1 for _ in acts.get(cid, [])),
        "n_price_rows_adjusted": changed_counts.get(cid, 0),
        "base_t_eligible": cid in base_elig,
        "exp_t_eligible": cid in exp_elig,
        "base_mom6_reason": raw_reason(base_comps.get(cid), "momentum_6m_rel"),
        "exp_mom6_reason": raw_reason(exp_comps.get(cid), "momentum_6m_rel"),
        "base_liq_reason": raw_reason(base_comps.get(cid), "liquidity"),
        "exp_liq_reason": raw_reason(exp_comps.get(cid), "liquidity"),
    })

out = {
    "artifact": "p3_t_recovery_2k10", "version": "2k10-p3-v1",
    "read_only": True, "db_writes": 0, "snapshot_tag": TAG,
    "as_of": str(AS_OF), "cutoff": CUTOFF.isoformat(),
    "method": ("adj(d)=close(d)·Π{confirmed adjustment_factor : action_date>d} from "
               "market.corporate_actions (is_confirmed AND adjustment_evidence_status="
               "CONFIRMED); no heuristic action used; no interpolation/forward-fill; "
               "official T pipeline re-run unchanged on the adjusted series in sandbox"),
    "adjustment_source_census": {s: n for s, n in conn.execute(
        "SELECT source, count(*) FROM market.corporate_actions GROUP BY 1 ORDER BY 2 DESC").fetchall()},
    "circularity_warning": ("همهٔ ردیف‌های market.corporate_actions از منبع واحد tsetmc_gap_rule_v1 آمده‌اند "
                            "(قاعدهٔ گپ-یاب). اعمال این ضرایب روی همان سری، گپ را به‌صورت دورْی (circular) حذف می‌کند "
                            "و شاهد مستقل وقوع اقدام شرکتی نیست. بنابراین «بازیابی» زیر شاهد مستقل معتبر نیست و "
                            "مشکل اقدامات شرکتی ۲۶ شرکت واقعاً حل‌نشده باقی می‌ماند."),
    "baseline_eligible": len(base_elig),
    "baseline_matches_artifact": control_match,
    "baseline_sym_diff_vs_artifact": sorted(base_elig ^ art_elig),
    "n_targets_gap": len(target_ids),
    "n_short_history": len(short),
    "experimental_eligible": len(exp_elig),
    "n_recovered_definite_independent": 0,
    "n_adjustment_applied_circular": len(recovered_of_26),
    "adjustment_applied_circular": [
        {"company_id": cid, "symbol": next((x["symbol"] for x in gap if x["company_id"] == cid), cid),
         "evidence_source": "market.corporate_actions.source=tsetmc_gap_rule_v1 (gap-inferred)"}
        for cid in recovered_of_26],
    "recovered_to_t_eligible": [
        {"company_id": cid, "symbol": next((x["symbol"] for x in gap if x["company_id"] == cid), cid)}
        for cid in recovered_of_26],
    "n_recovered_of_26": len(recovered_of_26),
    "lost_eligibility": lost,
    "raw_valid_delta": {
        fid: {"base": len(base_rawvalid.get(fid, set())), "exp": len(exp_rawvalid.get(fid, set()))}
        for fid in sorted(set(base_rawvalid) | set(exp_rawvalid))},
    "short_history_probe": short_probe,
    "gap_detail": gap_detail,
}
p = os.path.join(OUT, f"p3_t_recovery_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("wrote", p)
print("recovered of 26:", out["n_recovered_of_26"], [r["symbol"] for r in out["recovered_to_t_eligible"]])
print("lost:", lost)
print("raw_valid_delta:", json.dumps(out["raw_valid_delta"], ensure_ascii=False))
print("short probe:", [(s["symbol"], s["recoverable_from_existing_store"], s["earliest_trade_date"]) for s in short_probe])
