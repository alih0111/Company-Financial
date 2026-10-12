# -*- coding: utf-8 -*-
"""GAM 2-K-1 axis 2 runner — shares/price/corporate-actions timeline audit
and independent valuation reproduction (P/E, P/S, P/B, market cap).

READ-ONLY. Reuses the snapshot-bound machinery of run_publish_recovery and
imports the engine's own contracts (compute_metrics.pit_share_snapshot /
select_current_shares / direct_valuation, report_chain_ttm.resolve_ttm) so the
reproduction is faithful rather than approximate. No artifact or DB is
modified; proposed recomputations for event-exposed companies live ONLY in
this diagnostic report.

Outputs (bound to the same artifact sha256 triple):
  provenance_v1/output/valuation_audit_<asof>_<q8>_<v8>_<t8>.json / .md
"""

from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_publish_recovery import (  # noqa: E402
    OUT_DIR, REPO,
    as_of_date, build_cells, build_dsn, cutoff_dt, fetch_company_names,
    fetch_company_symbols, fetch_stmt_rows, fetch_superseded, iso,
    load_artifacts,
)

# read-only imports of the engine contracts being audited
sys.path.insert(0, os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1"))
from compute_metrics import (  # noqa: E402
    direct_valuation, num, pit_share_snapshot, select_current_shares,
)
from fiscal_calendar import (  # noqa: E402
    annual_month_of, build_fiscal_calendar, prev_annual_cell, STATE_EXPLICIT,
)
from report_chain_ttm import (  # noqa: E402
    resolve_ttm, PROV_CHAIN,
)

TOL = 1e-9

VERDICTS = {
    "MATCH_EXACT": "تطبیق کامل — بازتولید بدون شکاف زمانی",
    "MATCH_WITH_TIME_LIMITATION": "تطبیق با محدودیت زمانی — شکاف snapshot/قیمت بدون رویداد تأییدشده",
    "MATCH_WITH_POSSIBLE_EVENT": "تطبیق با رویداد محتمل (نوع دسته‌بندی‌نشده/استنباطی) در بازه حساس",
    "EVENT_EXPOSURE_FLAGGED": "رویداد شرکتی معتبر در بازه حساس — نیازمند بازبینی ارزندگی",
    "SUSPECTED_COMPUTATION_ERROR": "تعارض واقعی — بازتولید با آرتیفکت نمی‌خواند",
    "INSUFFICIENT_EVIDENCE": "شواهد ناکافی (قیمت/سهام/صورت مالی مفقود)",
}


def fetch_securities(conn, cids):
    cur = conn.cursor()
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.id::text AS security_id,
                s.codal_symbol, s.tsetmc_ins_code
            FROM core.securities s
            WHERE s.company_id::text = ANY(%s) AND s.is_active
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, security_id, codal_symbol, tsetmc_ins_code FROM sec
        """, (cids,))
    out = {r[0]: {"security_id": r[1], "codal_symbol": r[2],
                  "tsetmc_ins_code": r[3]} for r in cur.fetchall()}
    cur.close()
    return out


def fetch_latest_prices(conn, sec_ids, cutoff):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (security_id::text)
            security_id::text AS security_id, trade_date, collected_at,
            last_price_rial, closing_price_rial
        FROM market.price_observations
        WHERE security_id::text = ANY(%s) AND collected_at <= %s
        ORDER BY security_id::text, trade_date DESC, collected_at DESC
        """, (sec_ids, cutoff))
    out = {r[0]: {"trade_date": r[1], "collected_at": r[2],
                  "last": num(r[3]), "close": num(r[4])} for r in cur.fetchall()}
    cur.close()
    return out


def fetch_tsetmc_current(conn, sec_ids, cutoff):
    cur = conn.cursor()
    cur.execute(
        "SELECT security_id::text, shares_count, collected_at "
        "FROM market.tsetmc_current_shares "
        "WHERE security_id::text = ANY(%s) AND collected_at <= %s "
        "ORDER BY security_id::text, collected_at DESC", (sec_ids, cutoff))
    out = [{"security_id": r[0], "shares_count": num(r[1]), "collected_at": r[2]}
           for r in cur.fetchall()]
    cur.close()
    return out


def fetch_share_structure(conn, sec_ids, as_of_d):
    cur = conn.cursor()
    cur.execute(
        "SELECT security_id::text, shares_count, as_of_date, collected_at, source "
        "FROM core.share_structure "
        "WHERE security_id::text = ANY(%s) AND as_of_date <= %s",
        (sec_ids, as_of_d))
    out = [{"security_id": r[0], "shares_count": num(r[1]), "as_of_date": r[2],
            "collected_at": r[3], "source": r[4]} for r in cur.fetchall()]
    cur.close()
    return out


def fetch_share_events(conn, cids):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT company_id::text, event_type, shares_before, shares_after,
               announced_at, approved_at, registered_at, effective_date,
               market_ex_date, status, source_report_id
        FROM core.share_events WHERE company_id::text = ANY(%s)
        """, (cids,))
    cols = ["company_id", "event_type", "shares_before", "shares_after",
            "announced_at", "approved_at", "registered_at", "effective_date",
            "market_ex_date", "status", "source_report_id"]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return out


def fetch_corporate_actions(conn, sec_ids):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT security_id::text, action_date, action_type, adjustment_factor,
               is_confirmed, detected_heuristically, event_semantics_status,
               adjustment_evidence_status, source
        FROM market.corporate_actions WHERE security_id::text = ANY(%s)
        """, (sec_ids,))
    cols = ["security_id", "action_date", "action_type", "adjustment_factor",
            "is_confirmed", "detected_heuristically", "event_semantics_status",
            "adjustment_evidence_status", "source"]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return out


def fetch_share_intervals(conn, sec_ids):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT security_id::text, valid_from, valid_to, shares_outstanding,
               basis, status, knowledge_from
        FROM core.share_intervals WHERE security_id::text = ANY(%s)
        """, (sec_ids,))
    cols = ["security_id", "valid_from", "valid_to", "shares_outstanding",
            "basis", "status", "knowledge_from"]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return out


def fetch_codal_titles(conn, cutoff):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.company_id::text AS company_id, r.title, r.period_end_date
        FROM ingestion.reports r
        WHERE r.source = 'codal' AND r.report_type = 'financial_statement'
          AND r.title IS NOT NULL AND r.period_end_date IS NOT NULL
          AND r.published_at IS NOT NULL AND r.published_at <= %s
        ORDER BY r.period_end_date
        """, (cutoff,))
    rows = cur.fetchall()
    cur.close()
    return rows


def rel_diff(a, b):
    if a is None or b is None:
        return None
    if a == b:
        return 0.0
    den = max(abs(a), abs(b))
    return abs(a - b) / den if den else None


def main() -> int:
    import psycopg

    ap = sys.argv[1:]
    artifact_dir = os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1", "output")
    if "--artifact-dir" in ap:
        artifact_dir = ap[ap.index("--artifact-dir") + 1]

    docs, binding = load_artifacts(artifact_dir)
    as_of_d = as_of_date(binding["as_of"])
    cutoff = cutoff_dt(binding["cutoff"])

    q_companies = set(docs["q"]["companies"])
    v_companies = set(docs["v"]["v_observed_report"]["companies"])
    t_companies = set(docs["t"]["t_observed_report"]["companies"])
    cids_all = sorted(q_companies | v_companies | t_companies)
    v_factors = {cid: (docs["v"]["v_observed_report"]["companies"].get(cid) or {})
                 for cid in cids_all}
    shortlist_ids = []
    token_file = os.environ.get("QVT_API_TOKEN_FILE",
                                os.path.join(os.environ.get("TEMP", "/tmp"),
                                             "qvt_token.txt"))
    try:
        import urllib.request
        token = open(token_file, encoding="utf-8").read().strip() \
            if os.path.isfile(token_file) else ""
        req = urllib.request.Request(
            "http://localhost:5000/api/qvt-v2/discovery",
            headers={"Authorization": f"Bearer {token}"} if token else {})
        with urllib.request.urlopen(req, timeout=20) as resp:
            disc = json.load(resp)
        for g in disc["shortlist"]["groups"]:
            for e in g["entries"]:
                shortlist_ids.append(e["company_id"])
    except Exception as exc:
        print(f"WARN: shortlist fetch failed: {exc}")

    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"

    cids_arr = list(cids_all)
    secs = fetch_securities(conn, cids_arr)
    names = fetch_company_names(conn, cids_arr)
    sec_ids = [s["security_id"] for s in secs.values() if s["security_id"]]
    superseded = fetch_superseded(conn)
    stmt_rows = fetch_stmt_rows(conn, cids_arr, as_of_d, cutoff)
    index = build_cells(stmt_rows, superseded)
    titles = fetch_codal_titles(conn, cutoff)
    cal_rows = []
    for company_id, title, ped in titles:
        try:
            from run_publish_recovery import fiscal_ym
            fy, fm = fiscal_ym(ped)
        except Exception:
            continue
        cal_rows.append((company_id, title, fy, fm))
    durations_cell, fiscal_cal = build_fiscal_calendar(cal_rows)
    durations_by_company = defaultdict(dict)
    for (c_id, cell_key), dur in durations_cell.items():
        durations_by_company[c_id][cell_key] = dur

    prices = fetch_latest_prices(conn, sec_ids, cutoff)
    tsetmc = fetch_tsetmc_current(conn, sec_ids, cutoff)
    vendor = fetch_share_structure(conn, sec_ids, as_of_d)
    share_events = fetch_share_events(conn, cids_arr)
    corp_actions = fetch_corporate_actions(conn, sec_ids)
    intervals = fetch_share_intervals(conn, sec_ids)
    conn.rollback()
    conn.close()

    shares_pit = pit_share_snapshot(vendor, as_of_d, cutoff)
    current_shares = select_current_shares(tsetmc, shares_pit, cutoff)
    events_by_company = defaultdict(list)
    for e in share_events:
        events_by_company[e["company_id"]].append(e)
    actions_by_security = defaultdict(list)
    for a in corp_actions:
        actions_by_security[a["security_id"]].append(a)
    intervals_by_security = defaultdict(list)
    for iv in intervals:
        intervals_by_security[iv["security_id"]].append(iv)

    results = {}
    verdict_counts = Counter()
    factor_match = Counter()

    for cid in cids_all:
        sec = secs.get(cid) or {}
        sid = sec.get("security_id")
        rep = index.get(cid) or {}
        latest = max(rep.keys(), key=lambda k: (k[0] or 0) * 12 + (k[1] or 0)) \
            if rep else None
        cell = rep.get(latest) if latest else None
        metrics_map = (cell or {}).get("metrics") or {}

        def g(metric, order=1):
            return metrics_map.get(metric, {}).get(order)

        ann_month, ann_state, ann_src = annual_month_of(fiscal_cal, cid)
        cell_durations = durations_by_company.get(cid, {})
        prov = {}

        def rtt(metric, fy, fm, tag):
            is_annual = True if cell_durations.get((fy, fm)) == 12 else None
            anchor = prev_annual_cell(cell_durations, fy, fm)
            v, p = resolve_ttm({k: c["metrics"] for k, c in rep.items()},
                               metric, fy, fm, annual_month=ann_month,
                               is_annual=is_annual, prev_annual_cell=anchor)
            if p == PROV_CHAIN and anchor is None and ann_state != STATE_EXPLICIT:
                v, p = None, "FISCAL_CALENDAR_UNKNOWN"
            prov[tag] = p
            return v

        revenue_ttm = net_ttm = None
        if latest:
            revenue_ttm = rtt("revenue", *latest, "revenue_ttm")
            net_ttm = rtt("net_profit", *latest, "net_profit_ttm")
        equity = g("total_equity")

        p = prices.get(sid) if sid else None
        latest_price = (p["last"] if p and p["last"] is not None
                        else (p["close"] if p else None))
        cur_sel = current_shares.get(sid) if sid else None
        share_row = shares_pit.get(sid) if sid else None
        if cur_sel and cur_sel["shares"]:
            shares_out = cur_sel["shares"]
        else:
            shares_out = num(share_row["shares_count"]) if share_row else None
        market_cap = (latest_price * shares_out
                      if (latest_price and latest_price > 0
                          and shares_out and shares_out > 0) else None)
        pe_engine, ps, pb = direct_valuation(market_cap, net_ttm, revenue_ttm,
                                             equity)
        # the pilot RAW layer publishes pe only when net_profit_ttm > 0
        # (score_v2_value_raw contract: "market_cap / net_profit_ttm
        # (only np_ttm > 0)"; negative/zero -> negative_net_profit_ttm reason)
        pe = pe_engine if (net_ttm is not None and net_ttm > 0) else None
        pe_excluded = pe is None and pe_engine is not None

        art = (v_factors.get(cid) or {}).get("factors") or {}
        art_pb = (art.get("pb") or {}).get("raw_value")
        art_pe = (art.get("pe") or {}).get("raw_value")
        art_ps = (art.get("ps") or {}).get("raw_value")

        diffs = {"pb": rel_diff(pb, art_pb), "pe": rel_diff(pe, art_pe),
                 "ps": rel_diff(ps, art_ps)}

        def factor_cmp(mine, theirs, negative_excluded=False,
                       family_excluded=False):
            if mine is None and theirs is None:
                return "both_none"
            if mine is not None and theirs is not None:
                d = rel_diff(mine, theirs)
                return "match" if (d is not None and d <= TOL) else "mismatch"
            if mine is not None and theirs is None:
                if family_excluded:
                    return "contract_family_excluded"
                return ("contract_negative_excluded" if negative_excluded
                        else "mine_only")
            return "artifact_only"

        fam = (v_factors.get(cid) or {}).get("model_family")
        ps_family_excluded = fam is not None and fam != "general"
        cmps = {"pb": factor_cmp(pb, art_pb),
                "pe": factor_cmp(pe, art_pe, negative_excluded=pe_excluded),
                "ps": factor_cmp(ps, art_ps,
                                 family_excluded=ps_family_excluded)}
        mismatches = [k for k in cmps
                      if cmps[k] in ("mismatch", "artifact_only")]

        # timeline: share snapshot instant vs price trade_date
        share_snapshot_date = None
        share_source = None
        if cur_sel and cur_sel["shares"]:
            share_source = cur_sel["source"]
            if cur_sel["collected_at"] is not None:
                share_snapshot_date = cur_sel["collected_at"].date()
            share_snapshot_date = share_snapshot_date or cur_sel["source_as_of"]
        elif share_row:
            share_source = share_row.get("source")
            share_snapshot_date = share_row.get("as_of_date")
        trade_date = p["trade_date"] if p else None
        gap_days = ((trade_date - share_snapshot_date).days
                    if (trade_date and share_snapshot_date) else None)

        # sensitive interval = [min(snapshot, trade), max(snapshot, trade)]
        lo, hi = sorted(x for x in (share_snapshot_date, trade_date)
                        if x is not None) or (None, None)
        ev_confirmed, ev_possible = [], []
        if lo is not None:
            for e in events_by_company.get(cid, []):
                d = e["effective_date"] or (e["registered_at"].date()
                                            if e["registered_at"] else None) \
                    or (e["announced_at"].date() if e["announced_at"] else None)
                if d and lo <= d <= hi:
                    (ev_confirmed if e["status"] == "CONFIRMED"
                     else ev_possible).append(
                        {"kind": "share_events", "event_type": e["event_type"],
                         "date": d.isoformat(), "status": e["status"],
                         "shares_before": num(e["shares_before"]),
                         "shares_after": num(e["shares_after"]),
                         "source_report_id": e["source_report_id"]})
            for a in actions_by_security.get(sid, []):
                d = a["action_date"]
                if d and lo <= d <= hi:
                    item = {"kind": "corporate_actions",
                            "action_type": a["action_type"], "date": d.isoformat(),
                            "event_semantics_status": a["event_semantics_status"],
                            "adjustment_evidence_status":
                                a["adjustment_evidence_status"],
                            "is_confirmed": a["is_confirmed"],
                            "adjustment_factor": num(a["adjustment_factor"]),
                            "source": a["source"]}
                    if (a["event_semantics_status"] == "CONFIRMED"
                            and a["adjustment_evidence_status"] == "CONFIRMED"):
                        ev_confirmed.append(item)
                    else:
                        ev_possible.append(item)

        # evidence completeness
        has_price = p is not None and latest_price is not None
        has_shares = shares_out is not None
        has_deno = (net_ttm is not None) or (revenue_ttm is not None) \
            or (equity is not None)
        art_missing = all(v is None for v in (art_pe, art_ps, art_pb))

        if not has_price or not has_shares or not has_deno:
            verdict = "INSUFFICIENT_EVIDENCE"
        elif mismatches and not art_missing:
            verdict = "SUSPECTED_COMPUTATION_ERROR"
        elif ev_confirmed:
            verdict = "EVENT_EXPOSURE_FLAGGED"
        elif ev_possible:
            verdict = "MATCH_WITH_POSSIBLE_EVENT"
        elif gap_days:
            verdict = "MATCH_WITH_TIME_LIMITATION"
        else:
            verdict = "MATCH_EXACT"

        # proposed recomputation with share_intervals KNOWN covering trade_date
        proposal = None
        if verdict == "EVENT_EXPOSURE_FLAGGED" and trade_date:
            for iv in intervals_by_security.get(sid, []):
                if iv["status"] != "KNOWN" or iv["shares_outstanding"] is None:
                    continue
                if iv["valid_from"] and iv["valid_from"] > trade_date:
                    continue
                if iv["valid_to"] and iv["valid_to"] < trade_date:
                    continue
                sh2 = num(iv["shares_outstanding"])
                if sh2 and latest_price:
                    mc2 = latest_price * sh2
                    pe2, ps2, pb2 = direct_valuation(mc2, net_ttm, revenue_ttm,
                                                     equity)
                    proposal = {
                        "basis": iv["basis"], "valid_from": iv["valid_from"].isoformat()
                        if iv["valid_from"] else None,
                        "valid_to": iv["valid_to"].isoformat()
                        if iv["valid_to"] else None,
                        "shares_outstanding": sh2,
                        "knowledge_from": iso(iv["knowledge_from"]),
                        "recomputed": {"market_cap": mc2, "pe": pe2, "ps": ps2,
                                       "pb": pb2},
                        "note": "محاسبه پیشنهادی تشخیصی — جایگزین V نشده",
                    }
                    break

        fm_counts = Counter()
        for k in ("pe", "ps", "pb"):
            fm_counts[k + ":" + cmps[k]] += 1
        for k, v in fm_counts.items():
            factor_match[k] += 1

        verdict_counts[verdict] += 1
        results[cid] = {
            "company_id": cid, "symbol": sec.get("codal_symbol"),
            "display_name": names.get(cid),
            "shortlist": cid in set(shortlist_ids),
            "price": {"trade_date": trade_date.isoformat() if trade_date else None,
                      "latest_price": latest_price,
                      "collected_at": iso(p["collected_at"]) if p else None},
            "shares": {"shares_outstanding": shares_out, "source": share_source,
                       "snapshot_date": share_snapshot_date.isoformat()
                       if share_snapshot_date else None,
                       "cross_check_status": cur_sel.get("cross_check_status")
                       if cur_sel else None,
                       "fallback_used": cur_sel.get("fallback_used")
                       if cur_sel else None},
            "gap_days": gap_days,
            "engine_inputs": {"net_profit_ttm": net_ttm, "revenue_ttm": revenue_ttm,
                              "total_equity": equity,
                              "ttm_provenance": prov,
                              "fiscal_state": ann_state},
            "recomputed": {"market_cap": market_cap, "pe": pe, "ps": ps, "pb": pb,
                           "pe_engine_direct_incl_negative": pe_engine,
                           "pe_excluded_by_contract": pe_excluded},
            "artifact_raw": {"pe": art_pe, "ps": art_ps, "pb": art_pb},
            "factor_comparison": cmps,
            "rel_diff": diffs, "mismatched_factors": mismatches,
            "events_in_sensitive_interval": {
                "confirmed": ev_confirmed, "possible": ev_possible},
            "verdict": verdict,
            "verdict_label": VERDICTS[verdict],
            "proposed_recomputation": proposal,
        }

    tag = f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_" \
          f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}"
    os.makedirs(OUT_DIR, exist_ok=True)
    result = {
        "mission": "گام ۲-ک-۱ محور دوم — سهام/اقدامات شرکتی/بازتولید ارزندگی",
        "snapshot_binding": binding,
        "population": {"n_companies": len(cids_all),
                       "shortlist_ids": shortlist_ids},
        "verdict_counts": dict(verdict_counts),
        "factor_match": dict(factor_match),
        "companies": results,
    }
    json_path = os.path.join(OUT_DIR, f"valuation_audit_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {json_path}")
    md_path = write_md(result, tag)
    print(f"wrote {md_path}")
    print("verdicts:", dict(verdict_counts))
    print("factor match:", dict(factor_match))
    return 0


def write_md(result: dict, tag: str) -> str:
    b = result["snapshot_binding"]
    lines = []
    w = lines.append
    w(f"# ممیزی سهام/اقدامات شرکتی و بازتولید ارزندگی — {str(b['as_of'])[:10]}")
    w("")
    w(f"- اتصال به snapshot: Q `{b['q']['sha256'][:16]}…` | V `{b['v']['sha256'][:16]}…` | "
      f"T `{b['t']['sha256'][:16]}…` — cutoff `{b['cutoff']}`")
    w("- قرارداد بازتولید: واردات مستقیم `compute_metrics.direct_valuation`، "
      "`pit_share_snapshot`، `select_current_shares` و `report_chain_ttm.resolve_ttm` "
      "(فقط‌خواندنی) — هیچ فرمولی بازنویسی نشده است.")
    w("")
    w("## جمع‌بندی")
    w("")
    for k, v in sorted(result["verdict_counts"].items()):
        w(f"- **{k}** ({VERDICTS[k]}): {v}")
    w("")
    w("### تطبیق فاکتورها")
    w("")
    for k, v in sorted(result["factor_match"].items()):
        w(f"- {k}: {v}")
    w("")
    w("## رویدادهای معتبر در بازه حساس (نیازمند بازبینی ارزندگی)")
    w("")
    flagged = [c for c in result["companies"].values()
               if c["verdict"] == "EVENT_EXPOSURE_FLAGGED"]
    if not flagged:
        w("- موردی یافت نشد.")
    for c in flagged:
        w(f"- **{c['symbol']}** ({c['company_id'][:8]}): "
          f"{json.dumps(c['events_in_sensitive_interval']['confirmed'], ensure_ascii=False)[:300]}")
        if c["proposed_recomputation"]:
            w(f"  - محاسبه پیشنهادی: `{json.dumps(c['proposed_recomputation']['recomputed'], ensure_ascii=False)}` "
              f"(مبنای سهام: {c['proposed_recomputation']['basis']}، "
              f"{c['proposed_recomputation']['shares_outstanding']})")
    w("")
    w("## تعارض‌های واقعی (بازتولید ≠ آرتیفکت)")
    w("")
    bad = [c for c in result["companies"].values()
           if c["verdict"] == "SUSPECTED_COMPUTATION_ERROR"]
    if not bad:
        w("- موردی یافت نشد.")
    for c in bad:
        w(f"- **{c['symbol']}**: diffs={c['rel_diff']}, recomputed={c['recomputed']}, "
          f"artifact={c['artifact_raw']}")
    w("")
    path = os.path.join(OUT_DIR, f"valuation_audit_{tag}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


if __name__ == "__main__":
    raise SystemExit(main())
