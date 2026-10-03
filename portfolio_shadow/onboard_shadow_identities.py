"""SHADOW V1.1 — deterministic identity onboarding (spec §7).

Classifies every company of the latest `canonical-v1-dev` production run:

  HISTORICAL_MAP_VERIFIED  bound by the certified historical identity map
                           (mapping_status=UNIQUE, same symbol + ins_code as the
                           company's primary security in core.securities)
  FORWARD_MAP_VERIFIED     not in the historical map, but deterministic evidence is
                           complete: exactly ONE primary security; canonical symbol and
                           TSETMC ins_code present; raw closing cache exists for
                           (symbol, ins_code) and every record inside it carries the
                           same insCode; the symbol is not bound by the map to another
                           instrument. Persisted append-only in
                           identity_onboarding_ledger.jsonl (this script is the ONLY
                           writer).
  UNRESOLVED               no primary security / missing symbol or ins_code / no cache
  AMBIGUOUS                multiple primary securities, map conflict, symbol reuse
                           across instruments, or price-source identity conflict

No ad-hoc symbol-only acceptance. A selected UNRESOLVED/AMBIGUOUS name can never
receive a paper fill (its target weight stays cash, frozen failed-execution rule).

Idempotent: already-onboarded identities are re-verified live but never re-appended.
Run AFTER refresh_raw_caches_forward.py so new caches exist as evidence.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import psycopg

import shadow_common as sc


def classify(rows: list[dict], imap: pd.DataFrame) -> list[dict]:
    imap_by_company = {r.company_id: r for r in imap.itertuples()}
    imap_by_symbol = {}
    for r in imap.itertuples():
        imap_by_symbol.setdefault(r.symbol, set()).add(str(r.ins_code))
    out = []
    for r in rows:
        cls, detail = None, {}
        pc = r["primary_count"]
        if pc == 0:
            cls, detail["reason"] = "UNRESOLVED", "no_primary_security"
        elif pc > 1:
            cls, detail["reason"] = "AMBIGUOUS", f"multiple_primary_securities ({pc})"
        elif not r["symbol"] or not r["ins_code"]:
            cls, detail["reason"] = "UNRESOLVED", "missing_symbol_or_ins_code"
        else:
            m = imap_by_company.get(r["company_id"])
            if m is not None:
                if (str(m.mapping_status) == "UNIQUE" and str(m.ins_code) == str(r["ins_code"])
                        and str(m.symbol) == str(r["symbol"])):
                    cls = "HISTORICAL_MAP_VERIFIED"
                else:
                    cls, detail["reason"] = "AMBIGUOUS", "certified_map_conflict"
            elif r["symbol"] in imap_by_symbol and str(r["ins_code"]) not in imap_by_symbol[r["symbol"]]:
                cls, detail["reason"] = "AMBIGUOUS", "symbol_bound_to_different_instrument_in_map"
            else:
                scan = sc.cache_identity_scan(r["symbol"], r["ins_code"])
                detail["cache_evidence"] = scan
                if not scan.get("cache_exists"):
                    cls, detail["reason"] = "UNRESOLVED", "no_price_cache"
                elif scan["insCode_mismatches"] > 0:
                    cls, detail["reason"] = "AMBIGUOUS", "price_source_identity_conflict"
                else:
                    cls = "FORWARD_MAP_VERIFIED"
        out.append({**r, "classification": cls, "detail": detail})
    return out


def main() -> int:
    with psycopg.connect(sc.DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT id::text FROM analytics.score_runs
                       WHERE score_version='canonical-v1-dev' AND status='completed'
                       ORDER BY completed_at DESC LIMIT 1""")
        run_row = cur.fetchone()
        if run_row is None:
            print(json.dumps({"error": "no canonical-v1-dev run exists"}))
            return 1
        run_id = run_row[0]
        cur.execute("""SELECT cs.company_id::text, s.codal_symbol, s.tsetmc_ins_code::text,
                              (SELECT COUNT(*) FROM core.securities x
                                WHERE x.company_id = cs.company_id AND x.is_primary)
                       FROM analytics.company_scores cs
                       LEFT JOIN core.securities s
                              ON s.company_id = cs.company_id AND s.is_primary
                       WHERE cs.run_id = %s
                       ORDER BY cs.company_id, s.id""", (run_id,))
        raw = cur.fetchall()
    by_company: dict[str, dict] = {}
    for cid, sym, ins, pcnt in raw:
        d = by_company.setdefault(cid, {"company_id": cid, "symbol": sym,
                                        "ins_code": ins, "primary_count": 0})
        if sym is not None:
            d.update({"symbol": sym, "ins_code": ins, "primary_count": int(pcnt)})
    imap = pd.read_parquet(sc.IDENTITY_MAP)
    rows = classify([by_company[k] for k in sorted(by_company)], imap)

    counts = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1

    # append-only ledger: record newly FORWARD_MAP_VERIFIED identities exactly once
    existing = sc.ledger_onboarded()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    batch_id = f"ONBOARD-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    new_lines = []
    for r in sorted(rows, key=lambda x: x["company_id"]):
        if r["classification"] != "FORWARD_MAP_VERIFIED":
            continue
        key = (r["company_id"], r["symbol"], r["ins_code"])
        if key in existing:
            continue
        new_lines.append(json.dumps({
            "record_kind": "ONBOARDED_IDENTITY", "batch_id": batch_id, "appended_at_utc": now,
            "company_id": r["company_id"], "symbol": r["symbol"], "ins_code": r["ins_code"],
            "classification": "FORWARD_MAP_VERIFIED",
            "basis_run_id": run_id,
            "evidence": r["detail"].get("cache_evidence", {}),
        }, ensure_ascii=False, sort_keys=True))
    if new_lines:
        with open(sc.IDENTITY_LEDGER, "a", encoding="utf-8") as fh:
            fh.write("\n".join(new_lines) + "\n")

    # price-observability is a separate dimension (V1.1 §8) — reported, never a filter
    with_cache = sum(1 for r in rows if r["detail"].get("cache_evidence", {}).get("cache_exists"))
    summary = {"artifact_kind": "IDENTITY_ONBOARDING_COUNTS", "batch_id": batch_id,
               "appended_at_utc": now, "basis_run_id": run_id, "n_classified": len(rows),
               "classification_counts": counts, "newly_appended_to_ledger": len(new_lines),
               "ledger_total_onboarded": len(existing) + len(new_lines),
               "with_price_cache": with_cache,
               "note": "identity classification governs fill eligibility only; "
                       "ranking universe and Top20 selection are untouched (spec §8)"}
    out = sc.ROOT / "portfolio_shadow" / "launch_audit" / \
        f"identity_onboarding_counts_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
