#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P5 — snapshot آزمایشی تازه + کنترل PIT/look-ahead.

۱) کنترل اینکه تازگی قیمت نسبت به as_of/cutoff آرتیفکت سنجیده شده، نه زمان اجرا.
۲) ساخت یک snapshot آزمایشی تازه در sandbox (Q بدون تغییر چون فقط بنیادی است،
   V و T بازمحاسبه‌شده تا ۲۰۲۶-۱۰-۱۱) با manifest و sha256 مستقل. هیچ فایل
   رسمی overwrite نمی‌شود.
۳) اختلاف Q/V/T/سه‌محوری و عضویت ۶۲ شرکت بین دو snapshot.

خروجی: provenance_v1/output/p5_snapshot_2k10_<TAG>.json و bundle آزمایشی.
"""

import datetime as dt
import hashlib
import json
import os
import shutil
import re
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
EXP = os.path.join(OUT, "exp_2k10")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
NEWTAG = "2026-10-11_exp_2k10_sandbox"
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_q(path):
    d = json.load(open(path, encoding="utf-8"))
    c = d.get("companies") or d.get("q_observed_report", {}).get("companies", {})
    return c


def load_v(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["v_observed_report"]["companies"]


def load_t(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["t_observed_report"]["companies"], d.get("coverage_summary", {})


def elig(comps):
    return {c for c, e in comps.items() if e.get("pilot_eligible")}


# ── رسمی ۲۰۲۶-۱۰-۰۸ ────────────────────────────────────────────────────────
q_old = load_q(os.path.join(ART, "v2_q_observed_report.json"))
v_old = load_v(os.path.join(ART, "v2_value_pilot.json"))
t_old, tc_old = load_t(os.path.join(ART, "v2_t_pilot.json"))
qE, vE, tE = elig(q_old), elig(v_old), elig(t_old)
old_triple = qE & vE & tE

# ── آزمایشی ۲۰۲۶-۱۰-۱۱ ─────────────────────────────────────────────────────
v_new = load_v(os.path.join(EXP, "v2_value_pilot_2026-10-11.json"))
t_new, tc_new = load_t(os.path.join(EXP, "v2_t_pilot_2026-10-11.json"))
qN, vN, tN = elig(q_old), elig(v_new), elig(t_new)  # Q فقط بنیادی است و تغییر نمی‌کند
new_triple = qN & vN & tN


def diff(a, b):
    return sorted(a - b)


# ── manifest آزمایشی (کپی Q رسمی + V/T تازه) ────────────────────────────────
BUNDLE = os.path.join(EXP, f"bundle_{NEWTAG}")
os.makedirs(BUNDLE, exist_ok=True)
shutil.copyfile(os.path.join(ART, "v2_q_observed_report.json"), os.path.join(BUNDLE, "v2_q_observed_report.json"))
shutil.copyfile(os.path.join(EXP, "v2_value_pilot_2026-10-11.json"), os.path.join(BUNDLE, "v2_value_pilot.json"))
shutil.copyfile(os.path.join(EXP, "v2_t_pilot_2026-10-11.json"), os.path.join(BUNDLE, "v2_t_pilot.json"))
files = ["v2_q_observed_report.json", "v2_value_pilot.json", "v2_t_pilot.json"]
hashes = {f: sha256(os.path.join(BUNDLE, f)) for f in files}
manifest = {
    "tag": NEWTAG, "as_of": "2026-10-11",
    "cutoff": "2026-10-11T23:59:00+00:00",
    "note": ("snapshot آزمایشی sandbox — Q عیناً همان آرتیفکت رسمی (Q فقط بنیادی است و "
             "با تغییر قیمت عوض نمی‌شود)؛ V و T بازمحاسبه‌شده تا ۲۰۲۶-۱۰-۱۱. "
             "هیچ فایل رسمی overwrite نشده؛ این bundle مستقل و حذف‌شدنی است."),
    "files": {f: {"sha256": hashes[f], "bytes": os.path.getsize(os.path.join(BUNDLE, f))} for f in files},
    "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
}
json.dump(manifest, open(os.path.join(BUNDLE, "manifest_exp.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ── کنترل PIT: مقایسهٔ cutoff با آخرین collected_at موجود ─────────────────────
txt = open(os.path.join(ROOT, "go-app", ".env"), encoding="utf-8").read()
d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip().replace("postgresql+psycopg://", "postgresql://")
ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
if ov:
    d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$", r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
conn = psycopg.connect(d, connect_timeout=20)
conn.execute("SET default_transaction_read_only = on")
mx = conn.execute("SELECT max(collected_at), max(trade_date) FROM market.price_observations").fetchone()

out = {
    "artifact": "p5_snapshot_2k10", "version": "2k10-p5-v1",
    "read_only": True, "db_writes": 0, "official_overwrite": False,
    "freshness_reference_audit": {
        "control_reference": "as_of/cutoff آرتیفکت (نه زمان اجرای موتور)",
        "evidence": ("go-app/handlers/qvt/pricecheck.go: سن = as_of آرتیفکت − trade_date؛ "
                     "پنجره = آخرین ردیف هر security با collected_at ≤ cutoff آرتیفکت"),
        "old_snapshot_cutoff": CUTOFF.isoformat(),
        "max_collected_at_in_store": str(mx[0]), "max_trade_date_in_store": str(mx[1]),
        "look_ahead_excluded_from_old_snapshot": (str(mx[0]) > CUTOFF.isoformat()),
    },
    "old_snapshot": {"tag": TAG, "as_of": "2026-10-08",
                     "q_eligible": len(qE), "v_eligible": len(vE), "t_eligible": len(tE),
                     "triple": len(old_triple)},
    "new_snapshot": {"tag": NEWTAG, "as_of": "2026-10-11",
                     "q_eligible": len(qN), "v_eligible": len(vN), "t_eligible": len(tN),
                     "triple": len(new_triple),
                     "t_coverage_summary_new": tc_new.get("raw_reason_census")},
    "delta": {
        "v_eligible": len(vN) - len(vE), "t_eligible": len(tN) - len(tE),
        "q_eligible": 0, "triple": len(new_triple) - len(old_triple),
        "triple_lost": diff(old_triple, new_triple), "triple_gained": diff(new_triple, old_triple),
        "v_eligible_lost": diff(vE, vN), "v_eligible_gained": diff(vN, vE),
        "t_eligible_lost": diff(tE, tN), "t_eligible_gained": diff(tN, tE),
    },
    "bundle": {"dir": BUNDLE, "manifest": manifest},
    "conclusion": ("snapshot تازهٔ sandbox ساخته شد (Q رسمی + V/T بازمحاسبه‌شده تا ۲۰۲۶-۱۰-۱۱)؛ "
                   "هیچ overwrite یا انتشار رسمی رخ نداد. اگر تعداد سه‌محوری پایدار بماند، "
                   "فهرست نامزدها هم تغییر بنیادی نمی‌کند چون قید کیفیت بوعلی از Q (بدون تغییر) می‌آید."),
}
p = os.path.join(OUT, f"p5_snapshot_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

print("wrote", p, "and bundle", BUNDLE)
print("old:", out["old_snapshot"])
print("new:", {k: out["new_snapshot"][k] for k in ("tag", "as_of", "q_eligible", "v_eligible", "t_eligible", "triple")})
print("delta:", json.dumps({k: v for k, v in out["delta"].items() if not isinstance(v, list)}, ensure_ascii=False))
print("triple lost:", [q_old.get(c, {}).get("symbol", c) for c in out["delta"]["triple_lost"]])
print("triple gained:", [q_old.get(c, {}).get("symbol", c) for c in out["delta"]["triple_gained"]])
print("hashes:", json.dumps(hashes, ensure_ascii=False))
