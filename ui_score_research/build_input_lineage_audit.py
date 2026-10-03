"""UI SCORE PIT LINEAGE AUDIT (tasks 2/4/7) — knowledge-time basis per input family,
per-report visibility map from recovered publication evidence, and per-snapshot
classification of the EXISTING historical UI panel.

NO score recomputation, NO returns, NO ICs. The production score is untouched.

Visibility rule (frozen, provable only):
  codal-stamped report      -> visible_from = real DB published_at
  legacy report, matched    -> visible_from = LATEST recovered publication of that
                               (company, period) [original, or latest correction] so the
                               canonical value is provably public whichever version it is
  legacy report, unmatched  -> visible_from = NULL (UNPROVABLE; period_end is NOT a
                               publication time and is never used as one)
Snapshot classification window: contributing inputs = canonical input rows of the company
with period_end in [as_of - 730d, as_of] (TTM + YoY comparable reach).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime
import pandas as pd
import psycopg

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "ui_score_research"
PB = ROOT / "historical_codal_backfill" / "output" / "pub_backfill"
EVENT_ART = ROOT / "fundamental_event_research" / "monthly_sales_events_universe_v1_1.parquet"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
TEHRAN = ZoneInfo("Asia/Tehran")
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
RE_TITLE = re.compile(r"منتهی\s*به\s*([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})")
RAW_RE = re.compile(r"([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})\s+([۰-۹\d]{1,2}):([۰-۹\d]{2})")
WINDOW_DAYS = 730

R = {"input_families": {}, "visibility_map": {}, "snapshot_classification": {},
     "row_level_leaks": {}, "cutoff_convention": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def title_period_end(title):
    m = RE_TITLE.search((title or "").translate(FA_DIGITS))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return jdatetime.date(y, mo, d).togregorian()
    except Exception:
        return None


def parse_raw(raw):
    m = RAW_RE.match((raw or "").translate(FA_DIGITS))
    if not m:
        return None
    jy, jm, jd, hh, mi = (int(x) for x in m.groups())
    g = jdatetime.datetime(jy, jm, jd, hh, mi).togregorian()
    return dt.datetime(g.year, g.month, g.day, g.hour, g.minute, tzinfo=TEHRAN).astimezone(dt.timezone.utc)


def as_date(x):
    return x.date() if isinstance(x, dt.datetime) else x


def as_utc(x):
    if x is None:
        return None
    return x if x.tzinfo is not None else x.replace(tzinfo=dt.timezone.utc)


def main() -> int:
    # ---------------- letters from the raw backfill cache ----------------
    letters = []
    for f in PB.glob("*_lt*.json"):
        sym = f.name.rsplit("_lt", 1)[0]
        lt = f.name.rsplit("_lt", 1)[1].replace(".json", "")
        p = json.loads(f.read_text(encoding="utf-8"))
        for L in p.get("letters") or []:
            letters.append({"symbol": sym, "lt": lt, "tracing_no": str(L.get("tracing_no")),
                            "title": L.get("title"), "publish_datetime": L.get("publish_datetime")})
    lt6 = defaultdict(lambda: {"orig": [], "corr": []})
    for L in letters:
        if L["lt"] != "6":
            continue
        pend = title_period_end(L["title"])
        if pend is None:
            continue
        t = parse_raw(L["publish_datetime"])
        if t is None:
            continue
        lt6[(L["symbol"], pend)]["corr" if "اصلاحیه" in (L["title"] or "") else "orig"].append(t)

    # ---------------- canonical input rows ----------------
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT c.id::text, s.codal_symbol FROM core.companies c
                       JOIN core.securities s ON s.company_id = c.id AND s.is_primary""")
        comp2sym = dict(cur.fetchall())
        cur.execute("""SELECT st.report_id::text, st.company_id::text, st.period_end_date,
                              r.published_at, r.source
                       FROM fundamentals.financial_statements st
                       JOIN ingestion.reports r ON r.id = st.report_id""")
        stmt_rows = cur.fetchall()
        cur.execute("""SELECT m.report_id::text, m.company_id::text, m.period_end_date
                       FROM fundamentals.monthly_activities m""")
        mon_rows = cur.fetchall()
        cur.execute("SELECT id::text, company_id::text FROM core.securities")
        sec2comp = dict(cur.fetchall())
    print(f"statement rows: {len(stmt_rows)} | monthly rows: {len(mon_rows)}")

    # ---------------- visibility per report ----------------
    # monthly: recovered publication evidence from the FROZEN V1.1 event artifact
    ev = pd.read_parquet(EVENT_ART)
    ev["period_end"] = ev.period_end.map(as_date)
    mon_pub = {(cid, p): as_utc(t) for (cid, p), t in
               ev.groupby(["company_id", "period_end"]).published_at.max().items()
               if t is not None and not pd.isna(t)}
    vis = {}
    fam_of = {}
    n_status = defaultdict(int)
    for rid, cid, pend in mon_rows:
        t = mon_pub.get((cid, as_date(pend)))
        vis[rid] = t
        fam_of[rid] = "monthly_activity"
        n_status["monthly_PROVABLE" if t else "monthly_UNPROVABLE"] += 1
    # statements: codal-stamped -> real published_at; legacy -> LT6 letter evidence
    per_cp_letters = {}
    for (sym, pend), d in lt6.items():
        if len(d["orig"]) == 1:
            per_cp_letters[(sym, pend)] = max(d["orig"] + d["corr"]) if d["corr"] else d["orig"][0]
        else:
            per_cp_letters[(sym, pend)] = None  # 0 or >=2 originals -> unprovable
    for rid, cid, pend, pub, source in stmt_rows:
        if pub is not None:
            vis[rid] = as_utc(pub)
            n_status["statement_CODAL_REAL_PUBLISHED_AT"] += 1
        else:
            sym = comp2sym.get(cid)
            vis[rid] = per_cp_letters.get((sym, as_date(pend)))
            n_status["statement_PROVABLE" if vis[rid] else "statement_UNPROVABLE"] += 1
        fam_of[rid] = "financial_statement"
    R["visibility_map"] = {
        "monthly_rows": len(mon_rows),
        "statement_rows": len(stmt_rows),
        "status_counts": dict(sorted(n_status.items())),
        "rule": ("visible_from = real DB published_at (codal) or LATEST recovered publication of "
                 "the (company, period) (legacy, conservative latest-version rule); NULL = "
                 "unprovable; period_end is never used as a publication time"),
    }
    print("visibility:", dict(sorted(n_status.items())))

    pd.DataFrame([{"report_id": k, "family": fam_of[k],
                   "visible_from": v, "provable": v is not None}
                  for k, v in vis.items()]).to_parquet(
        HERE / "input_report_visibility_v2.parquet", compression="zstd", index=False)

    # ---------------- snapshot classification of the EXISTING panel ----------------
    panel = pd.read_parquet(ROOT / "research_bundle" / "monthly_pit_panel.parquet",
                            columns=["signal_date", "security_id", "symbol"])
    # company input rows: (company_id, family, period_end, visible_from)
    comp_inputs = defaultdict(list)
    for rid, cid, pend in mon_rows:
        comp_inputs[cid].append(("monthly_activity", as_date(pend), vis[rid]))
    for rid, cid, pend, pub, source in stmt_rows:
        comp_inputs[cid].append(("financial_statement", as_date(pend), vis[rid]))
    snap_class = defaultdict(int)
    leak_by_year = defaultdict(int)
    leak_by_sec = defaultdict(int)
    leak_by_fam = defaultdict(int)
    unprov_by_year = defaultdict(int)
    rows_out = []
    panel = panel.drop_duplicates(subset=["signal_date", "security_id"])
    for r in panel.itertuples():
        d = r.signal_date if isinstance(r.signal_date, dt.date) else dt.date.fromisoformat(str(r.signal_date)[:10])
        cutoff = dt.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=dt.timezone.utc)
        lo = d - dt.timedelta(days=WINDOW_DAYS)
        has_leak = has_unprov = False
        leak_fams = set()
        for fam, pend, t in comp_inputs.get(sec2comp.get(r.security_id), []):
            if not (lo <= pend <= d):
                continue
            if t is None:
                has_unprov = True
            elif t > cutoff:
                has_leak = True
                leak_fams.add(fam)
        cls = ("DIRECT_LEAK_CONFIRMED" if has_leak else
               "UNPROVABLE_LEGACY_KNOWLEDGE_TIME" if has_unprov else "PROVABLY_PIT_SAFE")
        snap_class[cls] += 1
        yr = str(d.year)
        if has_leak:
            leak_by_year[yr] += 1
            leak_by_sec[r.symbol] += 1
            for fam in leak_fams:
                leak_by_fam[fam] += 1
        if has_unprov:
            unprov_by_year[yr] += 1
        rows_out.append({"signal_date": d.isoformat(), "security_id": r.security_id,
                         "symbol": r.symbol, "classification": cls,
                         "leak_families": ";".join(sorted(leak_fams))})
    pd.DataFrame(rows_out).to_parquet(HERE / "ui_panel_v1_snapshot_classification.parquet",
                                      compression="zstd", index=False)
    n = sum(snap_class.values())
    R["snapshot_classification"] = {
        "window_days": WINDOW_DAYS,
        "snapshots_total": n,
        "PROVABLY_PIT_SAFE": snap_class.get("PROVABLY_PIT_SAFE", 0),
        "DIRECT_LEAK_CONFIRMED": snap_class.get("DIRECT_LEAK_CONFIRMED", 0),
        "UNPROVABLE_LEGACY_KNOWLEDGE_TIME": snap_class.get("UNPROVABLE_LEGACY_KNOWLEDGE_TIME", 0),
        "classification_precedence": "leak > unprovable > safe (conservative: ANY window input row)",
        "leak_snapshots_by_year": dict(sorted(leak_by_year.items())),
        "unprovable_snapshots_by_year": dict(sorted(unprov_by_year.items())),
        "leak_snapshots_top_security": dict(sorted(leak_by_sec.items(), key=lambda kv: -kv[1])[:10]),
        "leak_snapshots_by_family": dict(sorted(leak_by_fam.items())),
    }
    print("classification:", snap_class)

    # ---------------- knowledge-time basis per input family (task 2) ----------------
    R["input_families"] = {
        "monthly_sales_activity": {"factors": ["sales_growth_12m", "sales_growth_3m", "sales_stability"],
                                   "v1_basis": "D legacy period_end proxy (published_at NULL, period_end <= as_of)",
                                   "recovered_real_times": "9,615/12,180 periods (78.9%)",
                                   "v2_basis": "A recovered published_at (latest-version-conservative)"},
        "revenue_profit_eps_ttm_growth": {"factors": ["revenue_growth", "operating_profit_growth",
                                                      "net_profit_growth", "eps_growth"],
                                          "v1_basis": "D legacy proxy for 7,562 statement reports; A for 595 codal",
                                          "recovered_real_times": "LT6 letters matched for legacy periods",
                                          "v2_basis": "A where matched/codal; unavailable otherwise"},
        "margins_roe": {"factors": ["operating_margin", "net_margin", "roe", "margin_trend"],
                        "v1_basis": "D legacy proxy / A codal", "v2_basis": "same as statement family"},
        "coverage_quality": {"factors": ["interest_coverage", "cash_conversion", "earnings_quality"],
                             "v1_basis": "D/A (incl. cash_flow statements)", "v2_basis": "same"},
        "leverage_current_ratio": {"factors": ["debt_ratio", "current_ratio"],
                                   "v1_basis": "D/A (balance sheet)", "v2_basis": "same"},
        "share_count_market_cap": {"factors": ["shares_outstanding", "market_cap"],
                                   "v1_basis": "H/A core.share_intervals knowledge_from <= cutoff (real)",
                                   "v2_basis": "unchanged (already provable)"},
        "pe_ps_pb": {"factors": ["pe", "ps", "pb"],
                     "v1_basis": "mixed: market leg C (trade_date proxy), fundamental leg D/A",
                     "v2_basis": "market leg unchanged; fundamental leg now publication-gated"},
        "liquidity": {"factors": ["avg_trade_value_30d"],
                      "v1_basis": "C deterministic market-date data (trade_date <= as_of, frozen proxy)",
                      "v2_basis": "unchanged"},
        "volatility_momentum": {"factors": ["volatility_30d", "price_momentum_30d", "latest_price"],
                                "v1_basis": "C deterministic market-date data", "v2_basis": "unchanged"},
        "data_quality_multiplier": {"factors": ["data_quality_score"],
                                    "v1_basis": "derived from input completeness (inherits input bases)",
                                    "v2_basis": "unchanged logic applied to PIT-eligible inputs"},
    }

    R["cutoff_convention"] = {
        "original_validated_convention": ("cutoff = 23:59:59 UTC on the signal date, as_of = signal "
                                          "date (ui_score_historical_v1.py EOD); reused EXACTLY"),
        "pre_event_baseline_rule": "latest snapshot with knowledge_cutoff < event published_at (instant)",
        "no_performance_informed_choices": True,
    }
    R["artifacts"] = {
        "visibility_parquet": str(HERE / "input_report_visibility_v2.parquet"),
        "classification_parquet": str(HERE / "ui_panel_v1_snapshot_classification.parquet"),
        "event_artifact_sha256": sha256(EVENT_ART),
        "panel_source": "research_bundle/monthly_pit_panel.parquet",
        "audit_script_sha256": sha256(HERE / "build_input_lineage_audit.py"),
    }
    HERE.mkdir(exist_ok=True)
    (HERE / "ui_input_lineage_audit.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote:", HERE / "ui_input_lineage_audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
