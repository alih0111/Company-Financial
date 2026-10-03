"""Part 5 — SHADOW vs certified price-contract parity (3 legs, event classes)."""
import sys, json, gzip, random, traceback
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\RFA\Company-Financial\portfolio_research")
import execute_score_portfolio_v1 as ex
import repair_accounting_v1 as rep
import psycopg

adjA, calA = ex.build_adj()
adjB, calB = rep.build_adj()
DSN, RAW = ex.DSN, ex.RAW
with psycopg.connect(DSN) as pg, pg.cursor() as cur:
    cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
    sec = {s: (i, ins) for s, i, ins in cur.fetchall()}
    cur.execute("""SELECT security_id::text, action_date::text, adjustment_factor
                   FROM market.corporate_actions
                   WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
    ev = {}
    for sid, d, f in cur.fetchall():
        ev.setdefault(sid, []).append((d, float(f)))


def legC_price(sym, d):
    """Independent recomputation: raw pClosing last session <= d, x CONFIRMED factors
    with event date > d multiplied in the certified sequence (ascending stable sort,
    consumed newest-first)."""
    s = sec.get(sym)
    if not s:
        return None, None
    gz = RAW / f"raw_{sym}_{s[1]}.json.gz"
    if not gz.exists():
        return None, None
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        recs = json.loads(fh.read())["closingPriceDaily"]
    by_date = {}
    for r in recs:
        k = str(r["dEven"])
        k = f"{k[:4]}-{k[4:6]}-{k[6:8]}"
        by_date[k] = r
    dates = sorted(by_date)
    prev = None
    for dd in dates:
        if dd > d:
            break
        prev = dd
    if prev is None:
        return None, None
    raw = float(by_date[prev]["pClosing"])
    evs_asc = sorted(ev.get(s[0], []), key=lambda t: t[0])
    c = 1.0
    for e_d, f in reversed(evs_asc):
        if e_d > d:
            c *= f
        else:
            break
    return raw * c, prev


hist = json.loads(Path(r"D:\RFA\Company-Financial\portfolio_shadow\launch_audit\historical_decision_schedule.json").read_text())
rng = random.Random(20261003)
syms = sorted(set(adjA) & set(adjB))
samples = []
for x in hist:
    sd = x["score_date"]
    e = next((d for d in calA if d > sd), None)
    if e:
        for sym in rng.sample(syms, 2):
            samples.append({"sym": sym, "date": e, "class": "normal"})

cls_map = {"capital_increase": "capital_increase", "rights_issue": "rights_issue",
           "reverse_split": "reverse_split", "other": "unclassified_mechanical_reset"}
per_class = {v: 0 for v in cls_map.values()}
with psycopg.connect(DSN) as pg, pg.cursor() as cur:
    cur.execute("""SELECT ca.security_id::text, ca.action_type, ca.action_date::text
                   FROM market.corporate_actions ca
                   WHERE ca.source='tsetmc_gap_rule_v1' AND ca.adjustment_evidence_status='CONFIRMED'
                     AND ca.action_date >= '2021-01-01' ORDER BY ca.action_date""")
    evrows = cur.fetchall()
sym_by_sid = {v[0]: k for k, v in sec.items()}
for sid, at, ad in evrows:
    if per_class[cls_map[at]] >= 30:
        continue
    sym = sym_by_sid.get(sid)
    if sym is None or sym not in adjA:
        continue
    e = next((d for d in calA if d > ad), None)
    if e is None or e > "2026-06-30":
        continue
    if any(s["sym"] == sym and s["date"] == e for s in samples):
        continue
    samples.append({"sym": sym, "date": e, "class": cls_map[at], "event_date": ad})
    per_class[cls_map[at]] += 1

compared = consistent_absent = 0
mismatch, max_abs, max_rel = [], 0.0, 0.0
raw_checked = raw_conflict = 0
for smp in samples:
    sym, d = smp["sym"], smp["date"]
    a = ex.price_at(adjA, sym, d)[0]
    b = rep.price_at(adjB, sym, d)  # repair_accounting_v1.price_at returns a scalar (observer's import)
    c, _ = legC_price(sym, d)
    if a is None and b is None and c is None:
        consistent_absent += 1
        continue
    vals = {"A": a, "B": b, "C": c}
    if any(v is None for v in vals.values()):
        mismatch.append({**smp, "issue": f"leg disagreement, missing {[k for k, v in vals.items() if v is None]}"})
        continue
    compared += 1
    dm = max(abs(vals["A"] - vals[k]) for k in ("B", "C"))
    rl = dm / abs(vals["A"])
    max_abs, max_rel = max(max_abs, dm), max(max_rel, rl)
    if rl > 1e-12:
        mismatch.append({**smp, "A": a, "B": b, "C": c, "rel": rl})
    # raw pClosing identity at exact sessions
    ins = sec[sym][1]
    gz = RAW / f"raw_{sym}_{ins}.json.gz"
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            rows = [r for r in json.loads(fh.read())["closingPriceDaily"]
                    if str(r["dEven"]) == d.replace("-", "")]
        if rows:
            raw_checked += 1
            if len({float(r["pClosing"]) for r in rows}) > 1:
                raw_conflict += 1

print(f"samples={len(samples)} compared={compared} consistent_absent={consistent_absent} "
      f"mismatches={len(mismatch)} max_abs={max_abs:.3e} max_rel={max_rel:.3e}")
print(f"raw exact-session checks={raw_checked} conflicting_dup_pClosing={raw_conflict}")
for m in mismatch[:10]:
    print("  MISMATCH:", m)
out = {"sample_size": len(samples), "compared_priced": compared,
       "consistent_absent": consistent_absent, "mismatches": mismatch,
       "max_abs_diff": max_abs, "max_rel_diff": max_rel, "per_class": per_class,
       "legs": "A=execute_score_portfolio_v1.build_adj (certified execution pipeline); "
               "B=repair_accounting_v1.build_adj (chain source imported by shadow observer); "
               "C=independent recomputation in certified factor order",
       "calendars_identical_A_B": calA == calB,
       "exact_session_raw_pClosing_checks": raw_checked,
       "conflicting_duplicate_pClosing_sessions": raw_conflict}
Path(r"D:\RFA\Company-Financial\portfolio_shadow\launch_audit\price_contract_parity.json").write_text(
    json.dumps(out, indent=1, default=str), encoding="utf-8")
print("saved")
