"""SHADOW V1.1 — build_shadow_portfolio.py

Freezes the monthly shadow decision for `score-portfolio-v1-top20` per the active spec
bound in shadow_v1_state.json (V1.1 supersedes V1 for schedule/guard/identity semantics;
all economics of V1 are unchanged):

  - decision run   = earliest qualifying production run (V1.1 §2): as_of_date must be the
                     LAST canonical trading date of its calendar month, source cutoff
                     within the frozen window (V1.1 §3), completed after the freeze
                     instant, projected execution date not yet underway (no backfill)
  - eligible       = every company_scores row of that run (ranking universe, spec §8)
  - selection      = n = max(1, floor(0.20 x N_eligible)), order (quant_score DESC, symbol ASC)
  - identity       = company_id:ins_code; certified map / append-only onboarding ledger +
                     live price-source evidence (V1.1 §7); unresolved/ambiguous = no fill
  - orders         = PAPER only, frozen before any execution observation (V1 §6)
  - artifacts      = written once, never overwritten, hashes recorded (V1 §14)

Modes:
  (no args)              production mode: ingests the next frozen decision from the DB
  --fixture FILE --outdir DIR   TEST mode: rebuild from a fixture snapshot into DIR
                         (DIR must live under portfolio_shadow/tests); never touches
                         shadow_v1_state.json and never creates shadow observations.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\RFA\Company-Financial\portfolio_research")))

import pandas as pd
import psycopg

import shadow_common as sc
from deterministic_accounting import rebalance_accounts  # noqa: F401  (engine identity)
from repair_accounting_v1 import build_adj, price_at     # certified chain logic, unmodified

SPEC_SHA = "959b56904added66812ab3726fc067112d7bc12ab3d58d8334f3c4381540df3a"  # SHADOW_V1 (superseded; preserved)
SELECTION_PCT = 0.20            # prereg §3, frozen
SHADOW_DIR = sc.ROOT / "portfolio_shadow"


def verify_active_spec(state: dict) -> str:
    """V1.1: the active spec file + its SHA-256 are bound in shadow_v1_state.json."""
    active = state.get("active_spec") or {}
    path = sc.ROOT / active["file"]
    if sc.sha256_file(path) != active["sha256"]:
        raise RuntimeError(f"active spec hash mismatch: {active['file']} — refusing to run")
    return active["sha256"]


def load_snapshot_from_db(run_id: str) -> dict:
    """Authoritative decision snapshot from the permanent DB tables (spec §2)."""
    with psycopg.connect(sc.DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT score_version, as_of_date::text, source_cutoff_at,
                              completed_at, code_version, status
                       FROM analytics.score_runs WHERE id=%s""", (run_id,))
        ver, as_of, cutoff, completed, code_version, status = cur.fetchone()
        cur.execute("""SELECT company_id::text, primary_security_id::text, quant_score,
                              data_quality_score, growth_score, profitability_score,
                              valuation_score, market_score, input_hash, details
                       FROM analytics.company_scores WHERE run_id=%s
                       ORDER BY company_id""", (run_id,))
        cs = cur.fetchall()
        cur.execute("""SELECT company_id::text, factor_code, percentile
                       FROM analytics.factor_scores WHERE run_id=%s
                       ORDER BY company_id, factor_code""", (run_id,))
        fs = cur.fetchall()
        cur.execute("""SELECT s.codal_symbol, s.tsetmc_ins_code::text, s.company_id::text
                       FROM core.securities s WHERE s.is_primary
                       ORDER BY s.company_id, s.id""")
        sec_rows = cur.fetchall()
    factors: dict[str, dict[str, float]] = {}
    for cid, fc, pct in fs:
        factors.setdefault(cid, {})[fc] = float(pct) if pct is not None else None
    sec_by_company: dict[str, list[tuple[str, str]]] = {}
    for sym, ins, cid in sec_rows:
        sec_by_company.setdefault(cid, []).append((sym, ins))
    rows = []
    for cid, secid, qs, dq, g, p, v, m, ih, details in cs:
        primaries = sec_by_company.get(cid) or []
        sym, ins = primaries[0] if primaries else (None, None)
        rows.append({
            "company_id": cid, "security_id": secid, "symbol": sym, "ins_code": ins,
            "primary_count": len(primaries),
            "quant_score": float(qs) if qs is not None else None,
            "data_quality_score": float(dq) if dq is not None else None,
            "growth_score": float(g), "profitability_score": float(p),
            "valuation_score": float(v), "market_score": float(m),
            "input_hash": ih, "dq_details": details, "factor_percentiles": factors.get(cid, {}),
        })
    return {"run_id": str(run_id), "score_version": ver, "as_of_date": as_of,
            "knowledge_cutoff": cutoff.isoformat() if cutoff else None,
            "completed_at": completed.isoformat() if completed else None,
            "code_version": code_version, "status": status,
            "n_companies": len(rows), "rows": rows}


def next_decision_run(pg, state: dict) -> tuple[dict | None, list[dict]]:
    """V1.1 §2 monthly decision rule (forward analogue of the recovered historical rule):
    the decision for calendar month M is the EARLIEST qualifying production run (by
    completed_at, after the spec freeze instant) whose as_of_date equals the LAST
    canonical trading date of month M, with the source-cutoff window of V1.1 §3.
    Months with no such run are skipped (historical precedent: 3 skipped months).
    A decision whose projected execution date has already begun is not created
    (no backfilled decisions): month skipped as LATE.
    Returns (chosen_run_row, ignored_rows)."""
    frozen = dt.datetime.fromisoformat(state["spec_frozen_at_utc"].replace("Z", "+00:00"))
    with pg.cursor() as cur:
        cur.execute("""SELECT id::text, as_of_date::text, source_cutoff_at, completed_at,
                              code_version
                       FROM analytics.score_runs
                       WHERE status='completed' AND score_version='canonical-v1-dev'
                         AND completed_at > %s
                       ORDER BY completed_at""", (frozen,))
        cand = cur.fetchall()
        cal = [d for d, _ in sc.shadow_calendar_rows(pg)]
    cal_set = set(cal)
    last_day_of = {}
    for d in cal:
        last_day_of[d[:7]] = max(last_day_of.get(d[:7], ""), d)
    last_month = None
    if state["decisions"]:
        last_month = state["decisions"][-1]["as_of_date"][:7]
    chosen, ignored = None, []
    for rid, as_of, cutoff, completed, code_version in cand:
        d = dt.date.fromisoformat(as_of)
        now_tehran = dt.datetime.now(sc.TEHRAN)
        ok, reason = sc.run_qualifies(d, cutoff, completed)
        if not ok:
            ignored.append({"run_id": rid, "as_of_date": as_of, "reason": f"guard rejected: {reason}"})
            continue
        if cutoff is not None:
            cut = sc.to_tehran(cutoff)
            eod_utc = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0, 0),
                                          tzinfo=dt.timezone.utc)
            lower = dt.datetime.combine(d, dt.time(12, 45), tzinfo=sc.TEHRAN)
            if cut < lower or cut > eod_utc:
                ignored.append({"run_id": rid, "as_of_date": as_of,
                                "reason": f"source_cutoff {cut.isoformat()} outside frozen window "
                                          f"[12:45 Tehran as_of, EOD UTC as_of] (V1.1 §3)"})
                continue
        if as_of not in cal_set:
            ignored.append({"run_id": rid, "as_of_date": as_of,
                            "reason": "as_of_date is not a canonical trading date (V1.1 §2)"})
            continue
        target = last_day_of.get(as_of[:7])
        month_end = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        structural = all(dt.date.fromisoformat(f"{d.year:04d}-{d.month:02d}-{dd:02d}").weekday() in (3, 4)
                         for dd in range(d.day + 1, month_end.day + 1))
        certain_last = structural or now_tehran.date() > month_end
        if as_of != target or not certain_last:
            ignored.append({"run_id": rid, "as_of_date": as_of,
                            "reason": f"as_of is not a CERTIFIABLE last canonical trading date of its "
                                      f"month (recorded last {target}; structural={structural}) (V1.1 §2)"})
            continue
        if last_month is not None and as_of[:7] <= last_month:
            ignored.append({"run_id": rid, "as_of_date": as_of,
                            "reason": f"same-or-earlier month than last decision {last_month} "
                                      f"(monthly cadence)"})
            continue
        e_next = sc.first_execution_date(cal, as_of)
        if e_next is None:
            ignored.append({"run_id": rid, "as_of_date": as_of,
                            "reason": "no canonical trading date after as_of yet"})
            continue
        if e_next < now_tehran.date() or (e_next == now_tehran.date()
                                          and now_tehran.time() >= dt.time(12, 45)):
            ignored.append({"run_id": rid, "as_of_date": as_of,
                            "reason": f"projected execution date {e_next} already underway/past — "
                                      f"decision would be backfilled (V1.1 §2 no-backfill)"})
            continue
        chosen = {"run_id": rid, "as_of_date": as_of, "source_cutoff_at": cutoff.isoformat(),
                  "completed_at": completed.isoformat(), "code_version": code_version}
        break
    return chosen, ignored


def resolve_identity(rows: list[dict]) -> list[dict]:
    """V1.1 §7 identity gate: company_id:ins_code via the company's primary security in
    core.securities, cross-checked against the certified historical map; companies not in
    the map are fill-eligible only if onboarded in the append-only identity ledger AND the
    live price-source evidence still verifies (cache exists, every record insCode matches).
    UNRESOLVED/AMBIGUOUS/not-onboarded names can never receive a paper fill."""
    imap = pd.read_parquet(sc.IDENTITY_MAP)
    imap_by_company = {r.company_id: r for r in imap.itertuples()}
    onboarded = sc.ledger_onboarded()
    for r in rows:
        pc = r.get("primary_count", 1 if (r["symbol"] and r["ins_code"]) else 0)
        r["primary_count"] = pc
        r["identity_detail"] = None
        if not r["ins_code"] or pc != 1:
            r["identity_status"] = "IDENTITY_ERROR"
            r["identity_detail"] = ("UNRESOLVED: missing ins_code" if not r["ins_code"]
                                    else f"AMBIGUOUS: {pc} primary securities")
            r["portfolio_security_key"] = None
            continue
        r["portfolio_security_key"] = f"{r['company_id']}:{r['ins_code']}"
        m = imap_by_company.get(r["company_id"])
        if m is not None:
            if str(m.ins_code) == str(r["ins_code"]) and str(m.mapping_status) == "UNIQUE" \
                    and str(m.symbol) == str(r["symbol"]):
                r["identity_status"] = "MAP_VERIFIED"          # HISTORICAL_MAP_VERIFIED
            else:
                r["identity_status"] = "IDENTITY_ERROR"
                r["identity_detail"] = "AMBIGUOUS: certified_map_conflict"
            continue
        led = onboarded.get((r["company_id"], r["symbol"], r["ins_code"]))
        scan = sc.cache_identity_scan(r["symbol"], r["ins_code"])
        if led is not None and scan.get("cache_exists") and scan["insCode_mismatches"] == 0:
            r["identity_status"] = "FORWARD_MAP_VERIFIED"
        elif led is None:
            r["identity_status"] = "IDENTITY_ERROR"
            r["identity_detail"] = ("UNRESOLVED: not onboarded (no cache evidence)"
                                    if not scan.get("cache_exists")
                                    else "UNRESOLVED: cache evidence present but not onboarded")
        else:
            r["identity_status"] = "IDENTITY_ERROR"
            r["identity_detail"] = ("AMBIGUOUS: price_source_identity_conflict"
                                    if scan.get("cache_exists") else
                                    "UNRESOLVED: onboarded cache missing at build time")
    return rows


def build_decision(snapshot: dict, prior_state: dict, adj: dict, cal_dates: list[str],
                   test_mode: bool = False) -> dict:
    """Deterministic decision construction (spec §3, §5, §6)."""
    rows = resolve_identity([dict(r) for r in snapshot["rows"]])
    # ranking: (quant_score DESC, symbol ASC) — spec §3, frozen tie-break
    def sort_key(r):
        qs = r["quant_score"] if r["quant_score"] is not None else float("-inf")
        return (-qs, r["symbol"] or "", r["ins_code"] or "")
    rows.sort(key=sort_key)
    for i, r in enumerate(rows, start=1):
        r["ui_rank"] = i
    n_elig = len(rows)
    n_sel = max(1, int(SELECTION_PCT * n_elig))
    selected = rows[:n_sel]
    as_of = snapshot["as_of_date"]

    # decision-time portfolio valuation on the adjusted chain (carried convention:
    # price_at returns the last known adjusted close <= as_of; exactness checked vs cache)
    holdings = prior_state.get("holdings", {})          # {key: {"symbol","ins_code","shares"}}
    cash = float(prior_state.get("cash", 1.0))
    nav = cash
    holdings_decision = {}
    for key in sorted(holdings):
        h = holdings[key]
        p = price_at(adj, h["symbol"], as_of)
        rec = sc.load_raw_cache(h["symbol"], h["ins_code"]) or {}
        exact = as_of in rec
        val = h["shares"] * (p if p is not None else 0.0)
        nav += val
        holdings_decision[key] = {"symbol": h["symbol"], "ins_code": h["ins_code"],
                                  "shares": h["shares"], "value_decision": val,
                                  "valued_at": as_of if exact else "carried_last_known"}
    decision_nav = nav

    orders, targets = [], []
    E = sc.first_execution_date(cal_dates, as_of)
    seq = 0
    for r in selected:                                   # rows already in frozen order
        seq += 1
        order_id = f"SHDW1-{as_of[:7].replace('-', '')}-{seq:03d}"
        key = r["portfolio_security_key"]
        rec = sc.load_raw_cache(r["symbol"], r["ins_code"]) if r["symbol"] and r["ins_code"] else None
        ref_price, ref_note = None, "DATA_MISSING"
        if rec:
            if as_of in rec:
                ref_price, ref_note = float(rec[as_of]["pClosing"]), "as_of_session_pClosing"
            else:
                earlier = [d for d in sorted(rec) if d <= as_of]
                if earlier:
                    d0 = earlier[-1]
                    ref_price, ref_note = float(rec[d0]["pClosing"]), f"carried_from_{d0}"
        cur_val = holdings_decision.get(key, {}).get("value_decision", 0.0) if key else 0.0
        expected_notional = decision_nav / n_sel
        delta = expected_notional - cur_val
        side = "PAPER_HOLD" if abs(delta) <= decision_nav * 1e-9 else ("PAPER_BUY" if delta > 0 else "PAPER_SELL_REBAL")
        orders.append({
            "shadow_order_id": order_id, "company_id": r["company_id"],
            "security_id": r["security_id"], "ins_code": r["ins_code"], "symbol": r["symbol"],
            "portfolio_security_key": key, "identity_status": r["identity_status"],
            "identity_detail": r.get("identity_detail"),
            "side": side, "ui_score": r["quant_score"], "ui_rank": r["ui_rank"],
            "decision_timestamp": snapshot["completed_at"], "score_as_of": as_of,
            "knowledge_cutoff": snapshot["knowledge_cutoff"],
            "eligible_execution_date": E, "reference_price_raw_pClosing": ref_price,
            "reference_price_note": ref_note, "target_weight": 1.0 / n_sel,
            "expected_notional": expected_notional, "decision_nav": decision_nav,
        })
        targets.append({
            "shadow_order_id": order_id, "company_id": r["company_id"], "ins_code": r["ins_code"],
            "symbol": r["symbol"], "portfolio_security_key": key,
            "identity_status": r["identity_status"], "ui_score": r["quant_score"],
            "ui_rank": r["ui_rank"], "target_weight": 1.0 / n_sel,
        })
    return {"rows": rows, "selected": selected, "n_eligible": n_elig, "n_selected": n_sel,
            "orders": orders, "targets": targets, "as_of": as_of,
            "decision_nav": decision_nav, "holdings_decision": holdings_decision,
            "exec_date_projected": (orders[0]["eligible_execution_date"] if orders else None)}


def write_decision_artifacts(dec: dict, snapshot: dict, outdir: Path, test_mode: bool) -> dict:
    """Spec §14: write-once artifacts + hashes (deterministic serialization)."""
    month = dec["as_of"][:7].replace("-", "_")
    prefix = "test_" if test_mode else ""
    outdir.mkdir(parents=True, exist_ok=True)
    hashes = {}

    def write_json(name: str, obj):
        p = outdir / f"{prefix}{name}"
        if p.exists():
            raise RuntimeError(f"artifact exists, never overwritten: {p}")
        b = sc.canonical_json(obj).encode("utf-8")
        p.write_bytes(b)
        hashes[p.name] = {"sha256_file": sc.sha256_bytes(b)}
        return p

    def write_parquet(name: str, records: list[dict]):
        p = outdir / f"{prefix}{name}"
        if p.exists():
            raise RuntimeError(f"artifact exists, never overwritten: {p}")
        df = pd.DataFrame(sorted(records, key=lambda r: r.get("shadow_order_id", "")))
        df.to_parquet(p, compression="zstd", index=False)
        hashes[p.name] = {"sha256_file": sc.sha256_file(p),
                          "sha256_canonical_content": sc.canonical_content_hash(records)}
        return p

    snap_obj = {
        "artifact_kind": "TEST_FIXTURE_REBUILD" if test_mode else "SHADOW_DECISION_SNAPSHOT",
        "spec_sha256": SPEC_SHA, "run": {k: snapshot[k] for k in
                                         ("run_id", "score_version", "as_of_date", "knowledge_cutoff",
                                          "completed_at", "code_version", "status", "n_companies")},
        "rows": [{k: v for k, v in r.items()} for r in sorted(dec["rows"], key=lambda r: r["ui_rank"])],
    }
    write_json(f"shadow_snapshot_{month}.json", snap_obj)
    write_parquet(f"shadow_targets_{month}.parquet", dec["targets"])
    write_parquet(f"shadow_orders_{month}.parquet", dec["orders"])
    state_obj = {
        "artifact_kind": "TEST_FIXTURE_REBUILD" if test_mode else "SHADOW_DECISION_STATE",
        "spec_sha256": SPEC_SHA,
        "run": {k: snapshot[k] for k in ("run_id", "as_of_date", "knowledge_cutoff", "completed_at")},
        "decision": {"as_of_date": dec["as_of"], "n_eligible": dec["n_eligible"],
                     "n_selected": dec["n_selected"], "decision_nav": dec["decision_nav"],
                     "exec_date_projected": dec["exec_date_projected"],
                     "holdings_decision": dec["holdings_decision"]},
        "artifact_hashes": hashes,
    }
    write_json(f"shadow_portfolio_state_{month}.json", state_obj)
    return hashes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture")
    ap.add_argument("--outdir")
    args = ap.parse_args()

    if args.fixture:
        assert args.outdir and "tests" in str(Path(args.outdir).resolve()), \
            "fixture rebuilds may only write under portfolio_shadow/tests"
        snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        snapshot["rows"] = snapshot["rows"]
        adj, cal = build_adj(), None
        import psycopg as _pg
        with _pg.connect(sc.DSN) as pg:
            cal = [d for d, _ in sc.shadow_calendar_rows(pg)]
        dec = build_decision(snapshot, {"holdings": {}, "cash": 1.0}, adj, cal, test_mode=True)
        hashes = write_decision_artifacts(dec, snapshot, Path(args.outdir), test_mode=True)
        print(json.dumps({"mode": "TEST_FIXTURE", "as_of": dec["as_of"],
                          "n_eligible": dec["n_eligible"], "n_selected": dec["n_selected"],
                          "artifact_hashes": hashes}, indent=1, default=str))
        return 0

    # ---------------- production mode ----------------
    state = json.loads(sc.STATE_PATH.read_text(encoding="utf-8"))
    verify_active_spec(state)
    if state.get("spec_sha256") != SPEC_SHA:
        raise RuntimeError("state file does not record the preserved SHADOW_V1 spec hash")
    with psycopg.connect(sc.DSN) as pg:
        run, ignored = next_decision_run(pg, state)
        if run is None:
            print(json.dumps({"shadow_decision": None,
                              "message": "no qualifying production score run yet (V1.1 §2 decision rule)",
                              "ignored_runs": ignored}, indent=1))
            return 0
        snapshot = load_snapshot_from_db(run["run_id"])
        cal = [d for d, _ in sc.shadow_calendar_rows(pg)]
    # bind the run digest to the ephemeral snapshot file when they agree (spec §2)
    hash_file = sc.ROOT / "canonical_postgres_v1_2_1" / "analytics_canonical_v1" / "output" / "canonical_v1_hash.txt"
    digest = hash_file.read_text().strip() if hash_file.exists() else None
    snapshot["snapshot_file_digest_binding"] = (
        {"digest": digest, "matches_run_input_hash": digest == snapshot["rows"][0]["input_hash"]}
        if snapshot["rows"] and digest else {"digest": digest, "matches_run_input_hash": False})

    prev_pfs = state["decisions"][-1].get("post_fill_state") if state["decisions"] else None
    prior = prev_pfs["portfolio"] if prev_pfs else {"cash": 1.0, "holdings": {}}
    adj = build_adj()
    dec = build_decision(snapshot, prior, adj, cal)
    hashes = write_decision_artifacts(dec, snapshot, SHADOW_DIR, test_mode=False)

    entry = {
        "decision_month": dec["as_of"][:7], "as_of_date": dec["as_of"],
        "run_id": snapshot["run_id"], "completed_at": snapshot["completed_at"],
        "knowledge_cutoff": snapshot["knowledge_cutoff"], "code_version": snapshot["code_version"],
        "n_eligible": dec["n_eligible"], "n_selected": dec["n_selected"],
        "exec_date_projected": dec["exec_date_projected"],
        "decision_nav": dec["decision_nav"],
        "pre_decision_state": {"cash": prior.get("cash", 1.0),
                               "holdings": prior.get("holdings", {})},
        "artifact_hashes": hashes,
        "observation_final": False,
        "post_fill_state": None,
    }
    state["decisions"].append(entry)
    state["ignored_runs"] = (state.get("ignored_runs", []) + ignored)
    sc.STATE_PATH.write_text(sc.canonical_json(state) + "\n", encoding="utf-8")
    print(json.dumps({"shadow_decision": entry["decision_month"], "as_of": dec["as_of"],
                      "run_id": snapshot["run_id"], "n_eligible": dec["n_eligible"],
                      "n_selected": dec["n_selected"], "exec_date_projected": dec["exec_date_projected"],
                      "artifacts": sorted(hashes)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
