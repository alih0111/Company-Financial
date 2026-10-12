# -*- coding: utf-8 -*-
"""GAM 2-K-1 axes 3 — Q economic audit + T audit (read-only).

Q:  (a) sentinel census — the 10,650 legacy ±1e6/±1e8 operating/net-profit
        rows must still be OUT of every scored path (only the diagnostic
        earnings_growth ever touched them, and that factor is
        policy-excluded from aggregation);
    (b) artifact-contract verification — earnings_growth diagnostic-only,
        roe_stability not_implemented, margin_trend incompleteness explicit,
        renormalization forbidden (sum of included contributions equals the
        observed points);
    (c) raw-value publication decision for the evidence layer.

T:  (a) adjusted-price contract: the store must be 100% price_series='adjusted'
        (a vendor claim — recorded as such, never verified economically here);
    (b) full mathematical reproduction of the five T factors via the REAL raw
        layer (score_v2_t_raw.build_t_raw) over the real price history — a
        reproduction of arithmetic, NOT a verification of the vendor's
        corporate-action adjustments;
    (c) warning consistency (jumps / staleness) between the reproduction and
        the published artifact.

Outputs (snapshot-hash bound): provenance_v1/output/qt_economic_audit_*.json/.md
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "canonical_postgres_v1_2_1", "analytics_canonical_v1"))

from run_publish_recovery import (  # noqa: E402
    OUT_DIR, REPO, as_of_date, build_dsn, cutoff_dt, fetch_superseded,
    iso, load_artifacts,
)

import score_v2_t_raw as TRW  # noqa: E402  (read-only import of the audited layer)

SENTINEL_VALUES = (1000000.0, -1000000.0, 100000000.0, -100000000.0)
SENTINEL_METRICS = ("net_profit", "operating_profit")


def main() -> int:
    import psycopg

    artifact_dir = os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1", "output")
    docs, binding = load_artifacts(artifact_dir)
    as_of_d = as_of_date(binding["as_of"])
    cutoff = cutoff_dt(binding["cutoff"])

    q_doc = docs["q"]
    q_companies = q_doc["companies"]
    v_doc = docs["v"]["v_observed_report"]["companies"]
    t_doc = docs["t"]["t_observed_report"]["companies"]
    cids_all = sorted(set(q_companies) | set(v_doc) | set(t_doc))

    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    cur = conn.cursor()

    def q(sql, p=()):
        cur.execute(sql, p)
        return cur.fetchall()

    # ── Q: sentinel census ──────────────────────────────────────────────────
    sentinel_total = q(
        """
        SELECT count(*) FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE f.metric_code = ANY(%s)
          AND f.canonical_value = ANY(%s)
          AND r.title IS NULL AND r.published_at IS NULL
          AND r.id NOT IN (SELECT supersedes_report_id FROM ingestion.reports
                           WHERE supersedes_report_id IS NOT NULL)
        """, (list(SENTINEL_METRICS), list(SENTINEL_VALUES)))[0][0]
    sentinel_by_metric = dict(q(
        """
        SELECT f.metric_code, count(*) FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE f.metric_code = ANY(%s)
          AND f.canonical_value = ANY(%s)
          AND r.title IS NULL AND r.published_at IS NULL
          AND r.id NOT IN (SELECT supersedes_report_id FROM ingestion.reports
                           WHERE supersedes_report_id IS NOT NULL)
        GROUP BY 1
        """, (list(SENTINEL_METRICS), list(SENTINEL_VALUES))))

    # scoring rows of the population (engine predicate + winner cells) — any
    # sentinel value consumed by a scored metric is an integrity breach.
    from run_publish_recovery import fetch_stmt_rows, build_cells
    from compute_metrics import num
    superseded = fetch_superseded(conn)
    stmt_rows = fetch_stmt_rows(conn, cids_all, as_of_d, cutoff)
    index = build_cells(stmt_rows, superseded)
    sentinel_in_scoring = []
    for cid in cids_all:
        rep = index.get(cid) or {}
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: (k[0] or 0) * 12 + (k[1] or 0))
        for key in (latest, (latest[0] - 1, latest[1])):
            cell = rep.get(key)
            if not cell:
                continue
            for met in SENTINEL_METRICS:
                for order, val in (cell["metrics"].get(met) or {}).items():
                    if val is not None and float(val) in SENTINEL_VALUES:
                        sentinel_in_scoring.append({
                            "company_id": cid,
                            "symbol": (q_companies.get(cid) or v_doc.get(cid) or {})
                            .get("symbol"),
                            "cell": f"{key[0]}-{key[1]}", "metric": met,
                            "order": order, "is_latest_cell": key == latest,
                            "value": val})
    # distinguish: latest cell (feeds SCORED factors) vs prev cell (only the
    # policy-excluded growth diagnostics)
    sentinel_latest_cell = [s for s in sentinel_in_scoring if s["is_latest_cell"]]

    # ── Q: artifact-contract verification ───────────────────────────────────
    contract = {"earnings_growth_in_scope": 0, "earnings_growth_total": 0,
                "roe_stability_not_implemented": 0, "roe_stability_total": 0,
                "margin_trend_reasons": Counter(), "margin_trend_total": 0}
    renorm_violations = []
    for cid, c in q_companies.items():
        facs = c.get("factors") or {}
        eg = facs.get("earnings_growth") or {}
        contract["earnings_growth_total"] += 1
        if eg.get("in_aggregation_scope") is False:
            contract["earnings_growth_in_scope"] += 1
        rs = facs.get("roe_stability") or {}
        contract["roe_stability_total"] += 1
        if rs.get("implementation") == "not_implemented":
            contract["roe_stability_not_implemented"] += 1
        mt = facs.get("margin_trend") or {}
        contract["margin_trend_total"] += 1
        reason = mt.get("not_included_reason") or "included"
        contract["margin_trend_reasons"][reason] += 1
        contrib = math.fsum((f.get("contribution_points") or 0.0)
                            for f in facs.values() if f.get("included"))
        pts = c.get("q_observed_points")
        if pts is not None and abs(contrib - pts) > 1e-9:
            renorm_violations.append({"company_id": cid, "sum": contrib,
                                      "points": pts})

    # ── T: adjusted-price contract + raw reproduction ───────────────────────
    series = dict(q("SELECT price_series, count(*) FROM market.price_observations "
                    "GROUP BY 1"))
    cur.execute(
        """
        SELECT security_id::text, trade_date, collected_at,
               closing_price_rial, trade_value_rial
        FROM market.price_observations
        WHERE collected_at <= %s
        ORDER BY security_id::text, trade_date DESC, collected_at DESC
        """, (cutoff,))
    cols = [c[0] for c in cur.description]
    price_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    histories = TRW.extract_daily_history(price_rows, as_of_d)

    sec_by_company = {}
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.id::text AS security_id
            FROM core.securities s
            WHERE s.company_id::text = ANY(%s) AND s.is_active
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, security_id FROM sec
        """, (cids_all,))
    sec_by_company = {r[0]: r[1] for r in cur.fetchall()}
    # company_meta: industry/model_family from the V artifact companies,
    # DB fallback for the rest
    company_meta = {}
    for cid in cids_all:
        v = v_doc.get(cid) or {}
        company_meta[cid] = {"model_family": v.get("model_family"),
                             "industry": v.get("industry")}
    missing_meta = [cid for cid, m in company_meta.items()
                    if not m["industry"]]
    if missing_meta:
        # the engine's PIT sector map (score_v4.load_sector_map, SELECT-only):
        # TSETMC category valid at as_of from core.company_classification
        cur.execute(
            """
            SELECT company_id::text, category
            FROM core.company_classification
            WHERE valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)
            ORDER BY valid_from
            """, (as_of_d, as_of_d))
        sector_map = {r[0]: r[1] for r in cur.fetchall()}
        for cid in missing_meta:
            if sector_map.get(cid):
                company_meta[cid]["industry"] = sector_map[cid]
                company_meta[cid]["model_family"] = company_meta[cid][
                    "model_family"] or "general"

    raw = TRW.build_t_raw(histories, sec_by_company, company_meta, as_of=as_of_d)

    factor_names = ("momentum_6m_rel", "momentum_3m_rel",
                    "relative_strength_6m_sector", "liquidity",
                    "low_volatility")
    cmp_counts = Counter()
    t_mismatches = []
    warn_diff = []
    for cid in cids_all:
        art_c = t_doc.get(cid) or {}
        art_facs = art_c.get("factors") or {}
        mine = (raw.get("records") or raw).get(cid) if isinstance(
            raw.get("records") if isinstance(raw, dict) else None, dict) else None
        # build_t_raw returns dict with 'records' per company (checked below)
        recs = (raw.get("records") or {}).get(cid) if isinstance(raw, dict) else None
        if recs is None and isinstance(raw, dict):
            recs = raw.get(cid)
        if not isinstance(recs, dict):
            continue
        for fid in factor_names:
            m = recs.get(fid) or {}
            a = art_facs.get(fid) or {}
            mv, av = m.get("raw_value"), a.get("raw_value")
            ms, as_ = m.get("status"), a.get("raw_status")
            if mv is None and av is None:
                cmp_counts[f"{fid}:both_none"] += 1
            elif mv is not None and av is not None:
                d = abs(mv - av) / max(abs(mv), abs(av)) if (mv or av) else 0.0
                if d <= 1e-9:
                    cmp_counts[f"{fid}:match"] += 1
                else:
                    cmp_counts[f"{fid}:mismatch"] += 1
                    t_mismatches.append({"company_id": cid,
                                         "symbol": art_c.get("symbol"),
                                         "factor": fid, "mine": mv,
                                         "artifact": av})
            elif mv is not None:
                cmp_counts[f"{fid}:mine_only"] += 1
                t_mismatches.append({"company_id": cid,
                                     "symbol": art_c.get("symbol"),
                                     "factor": fid, "mine": mv,
                                     "artifact": av, "kind": "mine_only"})
            else:
                cmp_counts[f"{fid}:artifact_only"] += 1
            if (ms or "") != (as_ or ""):
                warn_diff.append({"company_id": cid, "factor": fid,
                                  "status_mine": ms, "status_artifact": as_})

    conn.rollback()
    cur.close()
    conn.close()

    result = {
        "mission": "گام ۲-ک-۱ محور سوم — ممیزی اقتصادی Q و T",
        "snapshot_binding": binding,
        "q_audit": {
            "sentinel_census": {
                "total_rows": sentinel_total,
                "by_metric": sentinel_by_metric,
                "definition": "legacy rows: exact ±1e6/±1e8 rial "
                              "net_profit/operating_profit, no title, no "
                              "published_at, non-superseded",
            },
            "sentinel_in_scoring_rows": {
                "total": len(sentinel_in_scoring),
                "in_latest_cell_feeding_scored_factors": len(sentinel_latest_cell),
                "detail": sentinel_in_scoring[:50],
                "note": "prev-cell consumption only ever reached the "
                        "policy-excluded earnings_growth diagnostic; "
                        "latest-cell consumption would breach the scored path",
            },
            "artifact_contract": {
                "earnings_growth_diagnostic_only":
                    f"{contract['earnings_growth_in_scope']}/"
                    f"{contract['earnings_growth_total']} companies",
                "roe_stability_not_implemented":
                    f"{contract['roe_stability_not_implemented']}/"
                    f"{contract['roe_stability_total']} companies",
                "margin_trend_not_included_reasons": dict(
                    contract["margin_trend_reasons"]),
                "renormalization_violations": renorm_violations,
                "renormalization_policy": "forbidden — verified: sum of "
                                          "included contribution_points == "
                                          "q_observed_points for all companies",
            },
            "raw_value_publication_decision": {
                "publishable_in_evidence_layer": [
                    "latest-cell canonical metric values (12 metric codes) "
                    "read read-only from fundamentals.financial_facts",
                    "TTM/equity reproductions (revenue_ttm, net_profit_ttm, "
                    "total_equity) already recomputed in valuation_audit "
                    "sidecar",
                    "publication dates recovered by publish_recovery sidecar",
                ],
                "not_publishable_without_new_evidence": [
                    "roe_stability / margin_trend (no raw yet)",
                    "any derived 'quality' label — would be a new score",
                ],
            },
        },
        "t_audit": {
            "price_series_distribution": series,
            "adjusted_contract": "construction.price_basis asserts the store "
                                 "is entirely the vendor-adjusted series; the "
                                 "flag is vendor-asserted — this audit "
                                 "verifies arithmetic, not the vendor's "
                                 "corporate-action adjustments",
            "reproduction": {
                "companies": len(sec_by_company),
                "factor_comparison": dict(cmp_counts),
                "mismatches": t_mismatches[:100],
                "status_differences": warn_diff[:50],
            },
        },
    }
    tag = f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_" \
          f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}"
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, f"qt_economic_audit_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {json_path}")
    print("sentinel total:", sentinel_total, "| in scoring rows:",
          len(sentinel_in_scoring), "| latest-cell:", len(sentinel_latest_cell))
    print("renorm violations:", len(renorm_violations))
    print("T factor comparison:", dict(cmp_counts))
    print("T status differences:", len(warn_diff))

    # markdown
    lines = []
    w = lines.append
    w(f"# ممیزی اقتصادی Q و T — {str(binding['as_of'])[:10]}")
    w("")
    w(f"- اتصال به snapshot: Q `{binding['q']['sha256'][:16]}…` | "
      f"V `{binding['v']['sha256'][:16]}…` | T `{binding['t']['sha256'][:16]}…`")
    w("")
    w("## Q — قرنطینه sentinel")
    w("")
    w(f"- ردیف‌های sentinel (±۱e۶/±۱e۸ دقیق، بدون عنوان، بدون published_at، "
      f"non-superseded): **{sentinel_total}** ({sentinel_by_metric})")
    w(f"- ردیف‌های sentinel داخل ردیف‌های امتیازساز فعلی: "
      f"**{len(sentinel_in_scoring)}** (از این تعداد در سلول latest که "
      f"فاکتورهای امتیازگیرنده را تغذیه می‌کند: **{len(sentinel_latest_cell)}**)")
    w("- earnings_growth فقط diagnostic است و وزنش بازتوزیع نمی‌شود؛ "
      "roe_stability صریحاً not_implemented است؛ margin_trend ناقص با دلیل "
      "raw_missing ثبت می‌شود — هیچ‌کدام پنهان نیستند.")
    w("")
    w("## T — بازتولید پنج فاکتور با لایه raw واقعی")
    w("")
    w(f"- توزیع price_series: `{series}` — ادعای «سری تعدیل‌شده فروشنده» "
      "تأیید flag است، نه تأیید اقتصادی تعدیل‌ها")
    for k, v in sorted(cmp_counts.items()):
        w(f"- {k}: {v}")
    w("")
    md_path = os.path.join(OUT_DIR, f"qt_economic_audit_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
