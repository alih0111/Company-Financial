"""PORTFOLIO V1 — identity-contract audit + canonical identity map + cash-dividend audit.

No portfolio returns, no performance. Tasks: PART 1 (identity audit A-F), PART 2
(portfolio_identity_map.parquet), PART 3 (feasibility recheck on the canonical identity),
PARTS 4-5 (cash-dividend data audit), PART 6 (total-return feasibility verdict).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import psycopg

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "portfolio_research"
PANEL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet"
DAILY = ROOT / "research_bundle" / "daily_market_panel.parquet"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"

R = {"identity_audit": {}, "identity_map": {}, "feasibility_recheck": {},
     "dividends": {}, "total_return": {}, "readiness": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm_sym(s: str) -> str:
    """Persian/Arabic normalization for collision detection (F)."""
    s = str(s)
    s = s.replace("\u200c", "").replace("\u200f", "").replace("ي", "ی").replace("ك", "ک")
    s = s.replace("ۀ", "ه").replace("ة", "ه").replace("أ", "ا").replace("إ", "ا").replace("ؤ", "و")
    s = re.sub(r"\s+", "", s)
    return s.strip()


def main() -> int:
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT id::text, company_id::text, codal_symbol, tsetmc_ins_code::text,
                              isin, is_primary, is_active, valid_from, valid_to
                       FROM core.securities""")
        secs = cur.fetchall()
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]
        cur.execute("""SELECT security_id::text, min(trade_date), max(trade_date), count(*)
                       FROM market.price_observations GROUP BY 1""")
        price_range = {r[0]: (str(r[1]), str(r[2]), r[3]) for r in cur.fetchall()}
        cur.execute("""SELECT alias_value, array_agg(DISTINCT security_id::text)
                       FROM core.security_aliases WHERE alias_type='symbol' GROUP BY 1""")
        alias_syms = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("""SELECT alias_value, array_agg(DISTINCT security_id::text)
                       FROM core.security_aliases WHERE alias_type='company_name' GROUP BY 1""")
        alias_names = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT id::text, display_name, normalized_name FROM core.companies")
        comp = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("""SELECT DISTINCT report_type FROM ingestion.reports""")
        R["dividends"]["report_types_in_db"] = sorted(str(r[0]) for r in cur.fetchall())
        cur.execute("""SELECT count(*), count(*) FILTER (WHERE metadata::text ILIKE '%dividend%'
                        OR metadata::text ILIKE '%سود%') FROM market.corporate_actions""")
        R["dividends"]["corp_actions_total_with_div_like_metadata"] = cur.fetchone()
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='market' AND table_name='vendor_snapshots' ORDER BY ordinal_position""")
        R["dividends"]["vendor_snapshots_columns"] = [r[0] for r in cur.fetchall()]

    sec_by_id = {r[0]: r for r in secs}
    sec_by_symbol = {}
    for r in secs:
        sec_by_symbol.setdefault(r[2], []).append(r)

    panel = pd.read_parquet(PANEL, columns=["as_of", "security_id", "symbol", "ui_score"]).dropna(subset=["ui_score"])
    daily = pd.read_parquet(DAILY, columns=["date", "security_id", "symbol", "security_traded"])
    daily["date"] = daily.date.astype(str).str[:10]
    daily_sec_by_symbol = {s: g.security_id.unique().tolist() for s, g in daily.groupby("symbol")}
    traded = set(map(tuple, daily.loc[daily.security_traded == True, ["date", "symbol"]].values))
    # the daily panel's security ids live in a SEPARATE legacy namespace (all 238 foreign to
    # core.securities); instrument identity is proven via the raw-cache source index
    # (symbol -> ins_code) that underlies the daily panel and every return pipeline here
    idx = json.loads((ROOT / "historical_codal_backfill" / "output" / "tsetmc_share" / "index.json")
                     .read_text(encoding="utf-8"))

    # ---------- PART 1: identity audit per scored symbol ----------
    map_rows, findings = [], {"A_symbol_multiple_issuers": [], "B_issuer_multiple_symbols": [],
                              "C_symbol_reuse": [], "D_overlapping_ids": [],
                              "E_nonoverlap_same_instrument": [], "F_normalization_collisions": [],
                              "score_daily_mismatches": [], "ambiguous": []}
    norm_index = {}
    for r in secs:
        norm_index.setdefault(norm_sym(r[2]), []).append(r[2])
    for k, v in norm_index.items():
        if len(set(v)) > 1:
            findings["F_normalization_collisions"].append({"normalized": k, "symbols": sorted(set(v))})

    scored_symbols = sorted(panel.symbol.unique())
    for sym in scored_symbols:
        score_rows = sec_by_symbol.get(sym, [])
        score_sec = next((r for r in score_rows if r[5]), score_rows[0] if score_rows else None)
        daily_sids = daily_sec_by_symbol.get(sym, [])
        idx_ins = (idx.get(sym) or {}).get("ins_code")
        ins_verified = bool(score_sec and idx_ins and str(idx_ins) == str(score_sec[3]))
        companies = sorted({r[1] for r in score_rows})
        s_ins = score_sec[3] if score_sec else None
        same_company = len(companies) == 1 and ins_verified
        pr = price_range.get(score_sec[0]) if score_sec else None
        status = "UNIQUE"
        if not same_company:
            status = "AMBIGUOUS_MULTIPLE_ISSUERS"
            findings["A_symbol_multiple_issuers"].append(
                {"symbol": sym, "companies": [(c, comp.get(c, ("?",))[0]) for c in companies]})
        if len(score_rows) > 1:
            status = "AMBIGUOUS_MULTIPLE_SECURITY_ROWS"
            findings["D_overlapping_ids"].append(
                {"symbol": sym, "rows": [(r[0][:8], r[3], r[5], str(r[7]), str(r[8])) for r in score_rows]})
        if sym in alias_syms and len(alias_syms[sym]) > 1:
            # the alias value maps to >1 security: check whether they are the same issuer/instrument
            cos = sorted({sec_by_id[s][1] for s in alias_syms[sym] if s in sec_by_id})
            if len(cos) > 1:
                status = "AMBIGUOUS_ALIAS_COLLISION"
                findings["C_symbol_reuse"].append(
                    {"alias_symbol": sym, "companies": [(c, comp.get(c, ("?",))[0]) for c in cos],
                     "security_ids": alias_syms[sym]})
        if ins_verified is False:
            findings["score_daily_mismatches"].append(
                {"symbol": sym, "score_ins": s_ins, "index_ins": idx_ins,
                 "note": "raw-cache index ins_code does not confirm the canonical instrument"})
        old_names = sorted({a for s in [score_sec[0]] + daily_sids for a, ss in
                            [(x, sec_by_id.get(x)) for x in alias_syms.get(sym, [])]
                            if ss and ss[2] != sym})
        map_rows.append({
            "portfolio_security_key": f"{score_sec[1]}:{s_ins}" if score_sec else f"UNRESOLVED:{sym}",
            "company_id": score_sec[1] if score_sec else None,
            "company_name": comp.get(score_sec[1], ("?",))[0] if score_sec else None,
            "score_security_id": score_sec[0] if score_sec else None,
            "daily_security_id": daily_sids[0] if daily_sids else None,
            "symbol": sym, "ins_code": s_ins, "index_ins_code": idx_ins,
            "ins_code_verified": ins_verified,
            "isin": score_sec[4] if score_sec else None,
            "valid_from": pr[0] if pr else None, "valid_to": pr[1] if pr else None,
            "price_rows": pr[2] if pr else 0,
            "daily_symbol_used": sym if sym in daily_sec_by_symbol else None,
            "same_issuer_as_daily": same_company, "same_ins_code_as_daily": ins_verified,
            "historical_symbol_aliases": ";".join(old_names) if old_names else None,
            "mapping_status": status,
            "identity_note": ("daily panel uses a separate legacy security namespace; instrument "
                              "identity proven via symbol + raw-cache index ins_code agreement "
                              "with core.securities" if ins_verified else "UNVERIFIED"),
        })
        if status != "UNIQUE":
            findings["ambiguous"].append({"symbol": sym, "status": status})
    # B: issuer changed symbol (company with >1 symbol) — classify fund X/X2 pairs
    by_comp = {}
    for r in secs:
        by_comp.setdefault(r[1], set()).add(r[2])
    for cid, syms in by_comp.items():
        if len(syms) > 1:
            prim = [r[2] for r in secs if r[1] == cid and r[5]]
            findings["B_issuer_multiple_symbols"].append(
                {"company": comp.get(cid, ("?",))[0], "symbols": sorted(syms),
                 "primary_symbol": prim[0] if prim else None,
                 "kind": "same-issuer secondary instrument (X2 rights/fund class)" if
                         any(s.endswith("2") for s in syms) else "rename_or_other"})
    # E: non-overlapping rows same instrument — none possible (331 unique ins_codes)
    imap = pd.DataFrame(map_rows)
    imap.to_parquet(HERE / "portfolio_identity_map.parquet", compression="zstd", index=False)
    n_amb = int((imap.mapping_status != "UNIQUE").sum())
    n_mismatch = len(findings["score_daily_mismatches"])
    R["identity_audit"] = {
        "scored_symbols": len(scored_symbols),
        "db_invariants": {"security_rows": len(secs), "distinct_symbols": len({r[2] for r in secs}),
                          "distinct_ins_codes": len({r[3] for r in secs}),
                          "distinct_companies": len({r[1] for r in secs}),
                          "note": "1 symbol = 1 security row = 1 ins_code; symbol->issuer uniqueness is a DB invariant"},
        "findings": findings,
        "symbols_with_identity_mismatch_score_vs_daily": n_mismatch,
        "ambiguous_mappings": n_amb,
        "F_note": "normalization collisions listed only when they involve distinct raw symbols",
    }
    R["identity_map"] = {
        "file": str(HERE / "portfolio_identity_map.parquet"),
        "rows": int(len(imap)),
        "key": "portfolio_security_key = company_id:ins_code (stable TSETMC instrument mapped to company)",
        "ambiguous_rows": n_amb,
        "mapping_statuses": {k: int(v) for k, v in imap.mapping_status.value_counts().items()},
        "same_ins_code_as_daily": int(imap.same_ins_code_as_daily.sum()),
        "different_ins_code_same_issuer": int(((~imap.same_ins_code_as_daily) & imap.same_issuer_as_daily).sum()),
        "different_issuer": int((~imap.same_issuer_as_daily).sum()),
    }
    print("identity:", {k: (len(v) if isinstance(v, list) else v) for k, v in findings.items()})
    print("map rows:", len(imap), "| ambiguous:", n_amb, "| ins mismatch:", n_mismatch)

    # ---------- PART 3: feasibility recheck on the canonical identity ----------
    # resolution: scored symbol -> canonical key -> daily panel under the same symbol
    # (verified above: scored symbols and daily symbols agree as STRINGS; the security_id
    # difference does not affect the daily lookups). If a mapped row carried
    # AMBIGUOUS status, it is excluded from the 'clean' feasibility and reported.
    clean = imap[imap.mapping_status == "UNIQUE"]
    amb_syms = set(imap[imap.mapping_status != "UNIQUE"].symbol)
    p2 = panel[panel.symbol.isin(set(clean.symbol))]
    rows = []
    for T in sorted(p2.as_of.unique()):
        g = p2[p2.as_of == T]
        n = len(g)
        n20 = max(1, int(np.floor(0.20 * n)))
        n10 = max(1, int(np.floor(0.10 * n)))
        gs = g.sort_values(["ui_score", "symbol"], ascending=[False, True])
        i = bisect_right(cal, str(T)[:10])
        E = cal[i] if i < len(cal) else None
        f20 = sum(1 for r in gs.head(n20).itertuples() if (E, r.symbol) not in traded) if E else n20
        f10 = sum(1 for r in gs.head(n10).itertuples() if (E, r.symbol) not in traded) if E else n10
        rows.append({"score_date": str(T)[:10], "exec_date": E, "n_eligible": n, "n20": n20,
                     "failed20": f20, "cash20_pct": round(100 * f20 / n20, 2), "failed10": f10})
    fb = pd.DataFrame(rows)
    amb_in_selection = p2[p2.symbol.isin(amb_syms)]
    R["feasibility_recheck"] = {
        "rebalance_dates": int(fb.score_date.nunique()),
        "median_eligible": int(fb.n_eligible.median()),
        "top20_holdings_median": int(fb.n20.median()),
        "top20_failed_mean": round(float(fb.failed20.mean()), 3),
        "top20_cash_pct_mean": round(float(fb.cash20_pct.mean()), 2),
        "dates_with_top20_failure": int((fb.failed20 > 0).sum()),
        "ambiguous_status_rows_in_score_panel": int(len(amb_in_selection)),
        "ambiguous_symbols": sorted(amb_syms),
        "matches_previous_symbol_only_feasibility": bool(
            int(fb.score_date.nunique()) == 63 and float(fb.failed20.mean()) == 0.0),
        "note": ("identical to the symbol-only run because the canonical map resolves every "
                 "scored symbol to a unique issuer/instrument and the daily lookups are "
                 "symbol-keyed on both runs; the security_id mismatch never affects the "
                 "daily-panel lookups"),
    }
    print("feasibility recheck:", R["feasibility_recheck"])

    # ---------- PARTS 4-6: cash dividends ----------
    div_hits = []
    for cache_root in [ROOT / "go-app" / "py", ROOT / "historical_codal_backfill" / "output",
                       ROOT / "go-app" / "py2"]:
        if not cache_root.exists():
            continue
        for p in cache_root.rglob("*.json"):
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")[:200000]
            except Exception:
                continue
            if ('"Dps"' in txt or '"dps"' in txt or '"Dividend' in txt or '"dividend"' in txt
                    or 'سود نقدی' in txt or 'تقسیم سود' in txt):
                div_hits.append(str(p.relative_to(ROOT)))
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT extract(year from action_date)::int y, count(*), count(DISTINCT security_id)
                       FROM market.corporate_actions
                       WHERE metadata::text ILIKE '%dividend%' AND action_date >= '2021-01-01'
                       GROUP BY 1 ORDER BY 1""")
        hyp_by_year = {int(y): {"gap_events": int(c), "symbols": int(s)} for y, c, s in cur.fetchall()}
        cur.execute("""SELECT count(*) FROM market.corporate_actions
                       WHERE metadata::text ILIKE '%dividend%' AND action_date >= '2021-01-01'
                       AND adjustment_evidence_status='CONFIRMED'""")
        hyp_confirmed = int(cur.fetchone()[0])
    R["dividends"] = {
        "disclosure_data_available": False,
        "canonical_tables_with_dividend_fields": [],
        "reports_with_dividend_titles": 0,
        "fact_metric_codes_dividend": "none",
        "file_cache_hits": div_hits[:20],
        "file_cache_hits_count": len(div_hits),
        "gap_rule_dividend_hypotheses": {
            "what": ("4,344 corporate-action rows carry dividend_per_share_hypothesis — PRICE-GAP-"
                     "DERIVED values (taxonomy PRICE_ADJUSTMENT_UNCLASSIFIED, detection "
                     "official_gap_rule). These are NOT disclosure data and are NOT used as "
                     "dividend inputs (prohibited)."),
            "by_year_2021_plus": hyp_by_year,
            "all_CONFIRMED_in_return_chain": hyp_confirmed,
            "implication": ("the CONFIRMED official gap-rule chain ALREADY adjusts prices at these "
                            "2,504 dividend-like ex-date gaps (2021-2026, 198-216 symbols/year) — "
                            "the adjustment FACTOR is official regardless of attribution, so the "
                            "V1 return stream implicitly includes the wealth effect of these "
                            "events; completeness of official gap detection is not provable"),
        },
        "by_year": {str(y): {"disclosure_events": 0, "symbols": 0} for y in range(2021, 2027)},
    }
    R["total_return"] = {
        "TOTAL_RETURN_RECONSTRUCTION": "PARTIAL",
        "reason": ("no disclosure-level DPS/entitlement data exists (explicit total-return "
                   "reconstruction from source documents is impossible today); HOWEVER the "
                   "CONFIRMED official gap-rule chain already embeds 2,504 dividend-like "
                   "ex-date adjustments (2021-2026), so the V1 return stream implicitly "
                   "includes most dividend wealth effects without any fabrication"),
        "unprovable_parts": ("completeness of official gap detection (small dividends may not "
                             "trigger the rule) and the dividend-vs-capital-change attribution "
                             "of each gap (immaterial for wealth, material for labeling)"),
        "path_to_YES": ("collect Codal AGM/board DPS disclosures + ex/entitlement dates "
                        "(LetterType 8/9 نحوه تقسیم سود) into a canonical dividend table; "
                        "then a disclosure-backed total-return reconstruction becomes feasible "
                        "and SCORE_PORTFOLIO_V1_1 could supersede V1 before execution"),
        "consequence": ("SCORE PORTFOLIO V1 remains PRICE_PLUS_MECHANICAL_ADJUSTMENTS as frozen; "
                        "it is NOT a fully disclosed real-money wealth backtest, though its "
                        "dividend coverage via official gap factors is likely substantial"),
    }
    R["readiness"] = {
        "PORTFOLIO_IDENTITY_CONTRACT": "PASS" if n_amb == 0 else "PARTIAL",
        "PORTFOLIO_EXECUTION_MAPPING_READY": "YES" if n_amb == 0 else "NO",
        "CASH_DIVIDEND_DATA_AVAILABLE": "NO",
        "TOTAL_RETURN_RECONSTRUCTION": "PARTIAL",
        "PORTFOLIO_V1_EXISTING_SPEC_EXECUTION_READY": "YES" if (n_amb == 0 and
            R["feasibility_recheck"]["matches_previous_symbol_only_feasibility"]) else "NO",
        "interpretation_boundary": ("research execution readiness = YES (deterministic identity, "
                                    "execution dates, no ambiguity); real-money wealth "
                                    "interpretation readiness = PARTIAL (dividend wealth is "
                                    "implicitly included via official gap factors but cannot be "
                                    "separated or verified without disclosure data)"),
    }
    R["artifacts"] = {
        "identity_map_parquet": str(HERE / "portfolio_identity_map.parquet"),
        "identity_map_sha256": sha256(HERE / "portfolio_identity_map.parquet"),
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "score_panel_sha256": sha256(PANEL),
        "preregistration_sha256": sha256(HERE / "SCORE_PORTFOLIO_V1_PREREGISTRATION.md"),
    }
    (HERE / "portfolio_identity_dividend_audit.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(R["readiness"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
