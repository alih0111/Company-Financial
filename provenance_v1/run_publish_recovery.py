# -*- coding: utf-8 -*-
"""GAM 2-K-1 axis 1 runner — publication-date recovery + PIT audit.

READ-ONLY: opens the canonical DB with default_transaction_read_only=on and
asserts the setting before any query. Produces JSON + Markdown reports under
provenance_v1/output/ bound to the exact sha256 of the three QVT artifacts,
so the recovery evidence can never be mistaken for a newer snapshot.

What it does (no engine is modified, no score recomputed):
1. loads v2_q_observed_report.json / v2_value_pilot.json / v2_t_pilot.json,
   records sha256+size+as_of+cutoff, population = union of company ids;
2. mirrors compute_metrics.py's eligibility predicate and report_index cell
   winner ((period_end_date, version_no), superseded excluded) to find the
   exact report rows Q (and V's equity) actually scored from;
3. resolves each winner row's real publication instant via
   codal_publish_resolver (E1 in-DB codal rows + E2 pub_backfill caches);
4. runs the PIT audit: confirmed_lookahead / possible_lookahead /
   unknown — never asserting lookahead without a dated evidence trail;
5. emits before/after status counts under the evidence contract.

Run:
  python provenance_v1/run_publish_recovery.py \
    [--artifact-dir canonical_postgres_v1_2_1/analytics_canonical_v1/output]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codal_publish_resolver import (  # noqa: E402
    CodalPublishResolver,
    ST_ALREADY_PUBLISHED,
    ST_AMBIGUOUS,
    ST_CONFLICTING,
    ST_NO_EVIDENCE,
    ST_VERIFIED,
    gregorian_to_jalali_text,
    norm_digits,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO, "go-app", ".env")
CACHE_DIR_DEFAULT = os.path.join(REPO, "historical_codal_backfill", "output", "pub_backfill")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# read-only import of the engine's numeric coercion so the mirror stays
# faithful (no copy-drift); compute_metrics.py itself is never modified.
sys.path.insert(0, os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1"))
from compute_metrics import num  # noqa: E402

GENERATED_NOTE = ("این گزارش فقط برای همین snapshot تولید شده است؛ استفاده از آن "
                  "برای snapshot دیگر ممنوع است. زمان تولیدِ گزارش، تاریخ انتشار "
                  "هیچ داده‌ای نیست.")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_dsn() -> str:
    txt = open(ENV_PATH, encoding="utf-8").read()
    d = re.search(r"^DATABASE_URL\s*=\s*\"?([^\"\n#]+)\"?", txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r"^CDF_CANONICAL_DB\s*=\s*\"?([^\"\n#]+)\"?", txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


def iso(dt):
    return dt.isoformat() if dt is not None else None


def load_artifacts(base: str):
    names = {"q": "v2_q_observed_report.json", "v": "v2_value_pilot.json",
             "t": "v2_t_pilot.json"}
    docs, binding = {}, {}
    for k, fn in names.items():
        p = os.path.join(base, fn)
        raw = open(p, "rb").read()
        docs[k] = json.loads(raw)
        binding[k] = {"file": fn, "sha256": hashlib.sha256(raw).hexdigest(),
                      "size_bytes": len(raw)}
    as_of = docs["v"]["as_of"]
    cutoff = docs["v"]["cutoff"]
    for k in ("q", "t"):
        a = str(docs[k].get("as_of") or "")
        if a[:10] != str(as_of)[:10]:
            raise SystemExit(f"as_of mismatch between artifacts: {k}={a} vs v={as_of}")
    binding["as_of"] = as_of
    binding["cutoff"] = cutoff
    binding["note"] = GENERATED_NOTE
    return docs, binding


def as_of_date(as_of) -> date:
    s = str(as_of)[:10]
    return date.fromisoformat(s)


def cutoff_dt(cutoff) -> datetime:
    return datetime.fromisoformat(str(cutoff).replace(" ", "T"))


# ── engine mirror (compute_metrics.py:430-458; do not modify the engine) ────

def fiscal_ym(period_end_date):
    """Engine mirror (compute_metrics.py:276-280): jalali (year, month) of a
    period end — anchors fiscal cells when fiscal_year/fiscal_month are NULL."""
    import jdatetime
    return (jdatetime.date.fromgregorian(date=period_end_date).year,
            jdatetime.date.fromgregorian(date=period_end_date).month)


def fetch_stmt_rows(conn, cids, as_of_d, cutoff):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT st.company_id::text AS company_id, st.statement_type,
               st.period_end_date, st.fiscal_year, st.fiscal_month,
               st.is_restated, st.is_audited,
               rv.version_no, rv.collected_at, f.metric_code, f.period_order,
               f.canonical_value, f.canonical_unit,
               r.id::text AS report_id, r.source, r.source_report_id,
               r.title, r.published_at, r.jalali_period_text
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
          AND ((r.published_at IS NULL AND st.period_end_date <= %s)
            OR (r.published_at IS NOT NULL AND r.published_at <= %s))
        """,
        (cids, as_of_d, cutoff))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def fetch_superseded(conn):
    cur = conn.cursor()
    cur.execute("SELECT supersedes_report_id::text FROM ingestion.reports "
                "WHERE supersedes_report_id IS NOT NULL")
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    return out


def build_cells(stmt_rows, superseded):
    """company -> (fy,fm) -> cell dict; winner rank (period_end, version_no).

    Mirrors Engine.report_index in compute_metrics.py:437-458 — including the
    per-cell metric->period_order->value maps (unit filter rial families) so
    TTM/valuation can be reproduced faithfully by the audit scripts.
    """
    idx = defaultdict(dict)
    for st in stmt_rows:
        if st["report_id"] in superseded:
            continue
        cid = st["company_id"]
        fy, fm = st["fiscal_year"], st["fiscal_month"]
        if fy is None or fm is None:
            fy, fm = fiscal_ym(st["period_end_date"])
        key = (fy, fm)
        cell = idx[cid].setdefault(key, {"_period": st["period_end_date"],
                                         "_ver": st["version_no"],
                                         "_winner_report": st["report_id"],
                                         "metrics": {}})
        cur_rank = (st["period_end_date"], st["version_no"])
        if cur_rank < (cell["_period"], cell["_ver"]):
            continue
        cell["_period"], cell["_ver"] = cur_rank
        cell["_winner_report"] = st["report_id"]
        if st["canonical_unit"] not in (None, "rial", "rial_per_share"):
            continue
        cell["metrics"].setdefault(st["metric_code"], {})[st["period_order"]] = \
            num(st["canonical_value"])
    return idx


def fetch_monthly_rows(conn, cids, as_of_d, cutoff):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.company_id::text AS company_id, m.period_end_date,
               m.sales_amount_rial,
               r.id::text AS report_id, r.source, r.published_at,
               r.jalali_period_text
        FROM fundamentals.monthly_activities m
        JOIN ingestion.reports r ON r.id = m.report_id
        WHERE m.company_id::text = ANY(%s)
          AND ((r.published_at IS NULL AND m.period_end_date <= %s)
            OR (r.published_at IS NOT NULL AND r.published_at <= %s))
        ORDER BY m.company_id, m.period_end_date DESC
        """,
        (cids, as_of_d, cutoff))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def fetch_company_symbols(conn, cids):
    cur = conn.cursor()
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.codal_symbol
            FROM core.securities s
            WHERE s.company_id::text = ANY(%s) AND s.is_active
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, codal_symbol FROM sec
        """, (cids,))
    out = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()
    return out


def fetch_company_names(conn, cids):
    cur = conn.cursor()
    cur.execute("SELECT id::text, display_name FROM core.companies "
                "WHERE id::text = ANY(%s)", (cids,))
    out = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()
    return out


# ── audit machinery ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir",
                    default=os.path.join(REPO, "canonical_postgres_v1_2_1",
                                         "analytics_canonical_v1", "output"))
    ap.add_argument("--cache-dir", default=CACHE_DIR_DEFAULT)
    ap.add_argument("--limit-companies", type=int, default=0,
                    help="debug: limit population size")
    args = ap.parse_args()

    import psycopg

    docs, binding = load_artifacts(args.artifact_dir)
    as_of_d = as_of_date(binding["as_of"])
    cutoff = cutoff_dt(binding["cutoff"])

    q_companies = set(docs["q"]["companies"])
    v_companies = set(docs["v"]["v_observed_report"]["companies"])
    t_companies = set(docs["t"]["t_observed_report"]["companies"])
    cids_all = sorted(q_companies | v_companies | t_companies)
    if args.limit_companies:
        cids_all = cids_all[: args.limit_companies]
    shortlist_ids = []
    token_file = os.environ.get("QVT_API_TOKEN_FILE",
                                os.path.join(os.environ.get("TEMP", "/tmp"),
                                             "qvt_token.txt"))
    try:
        import urllib.request
        token = ""
        if os.path.isfile(token_file):
            token = open(token_file, encoding="utf-8").read().strip()
        req = urllib.request.Request(
            "http://localhost:5000/api/qvt-v2/discovery",
            headers={"Authorization": f"Bearer {token}"} if token else {})
        with urllib.request.urlopen(req, timeout=20) as resp:
            disc = json.load(resp)
        for g in disc["shortlist"]["groups"]:
            for e in g["entries"]:
                shortlist_ids.append(e["company_id"])
    except Exception as exc:  # API unavailable — keep going, note it
        print(f"WARN: shortlist fetch failed: {exc}")

    dsn = build_dsn()
    conn = psycopg.connect(dsn)
    conn.execute("SET default_transaction_read_only = on")
    ro = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
    assert ro == "on", "refusing to run outside a read-only session"
    print(f"DB connected (read-only={ro}); population={len(cids_all)} "
          f"as_of={as_of_d} cutoff={cutoff.isoformat()}")

    resolver = CodalPublishResolver(conn, args.cache_dir)
    print(f"cache evidence: files={resolver.cache_files_loaded} "
          f"letters={resolver.cache_letters_loaded} "
          f"without_date={resolver.cache_letters_without_date}")

    cids_arr = list(cids_all)
    symbols = fetch_company_symbols(conn, cids_arr)
    names = fetch_company_names(conn, cids_arr)
    superseded = fetch_superseded(conn)
    stmt_rows = fetch_stmt_rows(conn, cids_arr, as_of_d, cutoff)
    cells = build_cells(stmt_rows, superseded)
    monthly_rows = fetch_monthly_rows(conn, cids_arr, as_of_d, cutoff)

    # winner report rows per company: latest cell + prev-year cell
    report_rows = {}
    for cid in cids_all:
        rep = cells.get(cid) or {}
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: (k[0] or 0) * 12 + (k[1] or 0))
        winner_ids = {rep[latest]["_winner_report"]}
        prev = (latest[0] - 1, latest[1])
        if prev in rep:
            winner_ids.add(rep[prev]["_winner_report"])
        report_rows[cid] = sorted(winner_ids)

    # rows by report_id (metadata for resolution)
    rows_by_report = {}
    for st in stmt_rows:
        rows_by_report.setdefault(st["report_id"], st)

    def resolve_report_row(rid: str):
        st = rows_by_report[rid]
        if st["published_at"] is not None:
            return {"status": ST_ALREADY_PUBLISHED,
                    "publish_at": iso(st["published_at"]), "resolution": None}
        pj = norm_digits(st["jalali_period_text"] or "") or \
            gregorian_to_jalali_text(st["period_end_date"])
        res = resolver.resolve_statement(
            st["company_id"], symbols.get(st["company_id"]), pj,
            st["period_end_date"],
            is_audited=st["is_audited"], is_restated=st["is_restated"])
        return {"status": res.status, "publish_at": iso(res.publish_at),
                "resolution": res.to_dict()}

    # resolve every scoring-input row
    per_company_rows = {}
    for cid in cids_all:
        items = []
        for rid in report_rows.get(cid, []):
            st = rows_by_report[rid]
            r = resolve_report_row(rid)
            items.append({
                "report_id": rid, "source": st["source"],
                "source_report_id": st["source_report_id"],
                "period_end_date": st["period_end_date"].isoformat()
                if st["period_end_date"] else None,
                "fiscal_year": st["fiscal_year"], "fiscal_month": st["fiscal_month"],
                "version_no": st["version_no"], "title": st["title"],
                "db_published_at": iso(st["published_at"]),
                "resolved": r,
            })
        per_company_rows[cid] = items

    # monthly: engine uses up to the 24 latest non-null periods
    monthly_by_company = defaultdict(list)
    for m in monthly_rows:
        monthly_by_company[m["company_id"]].append(m)
    per_company_monthly = {}
    for cid in cids_all:
        ms = monthly_by_company.get(cid, [])
        used = [m for m in ms if m["sales_amount_rial"] is not None][:24]
        items = []
        for m in used:
            if m["published_at"] is not None:
                st_ = ST_ALREADY_PUBLISHED
                pub = iso(m["published_at"]); res_d = None
            else:
                pj = norm_digits(m["jalali_period_text"] or "") or \
                    gregorian_to_jalali_text(m["period_end_date"])
                res = resolver.resolve_monthly(
                    cid, symbols.get(cid), pj)
                st_ = res.status
                pub = iso(res.publish_at)
                res_d = res.to_dict()
            items.append({
                "period_end_date": m["period_end_date"].isoformat()
                if m["period_end_date"] else None,
                "report_id": m["report_id"], "source": m["source"],
                "db_published_at": iso(m["published_at"]),
                "resolved": {"status": st_, "publish_at": pub,
                             "resolution": res_d},
            })
        per_company_monthly[cid] = items

    # ── company-level before/after (evidence contract, same row set) ────────
    EV_VERIFIED, EV_PARTIAL, EV_UNVERIFIED, EV_CONFLICT = (
        "verified_from_source", "partially_verified", "unverified", "conflicting")

    def origin_status(items):
        if not items:
            return None
        before = []
        for it in items:
            before.append(it["db_published_at"] is not None)
        if all(before):
            return EV_VERIFIED
        if any(before):
            return EV_PARTIAL
        return EV_UNVERIFIED

    def origin_status_after(items, cutoff):
        if not items:
            return None
        eff = []
        lookahead = False
        conflict = False
        for it in items:
            st = it["resolved"]["status"]
            pub = it["resolved"]["publish_at"]
            if st == ST_CONFLICTING:
                conflict = True
            if st in (ST_ALREADY_PUBLISHED, ST_VERIFIED) and pub:
                dt = datetime.fromisoformat(pub)
                if dt > cutoff:
                    lookahead = True
                    eff.append(True)  # has a date (a future one — flagged)
                    continue
                eff.append(True)
            else:
                eff.append(False)
        if lookahead or conflict:
            return EV_CONFLICT
        if all(eff):
            return EV_VERIFIED
        if any(eff):
            return EV_PARTIAL
        return EV_UNVERIFIED

    before_counts, after_counts = Counter(), Counter()
    companies = {}
    for cid in cids_all:
        items = per_company_rows.get(cid, [])
        b = origin_status(items)
        a = origin_status_after(items, cutoff)
        if b:
            before_counts[b] += 1
        if a:
            after_counts[a] += 1
        # monthly before/after
        mitems = per_company_monthly.get(cid, [])
        companies[cid] = {
            "company_id": cid,
            "display_name": names.get(cid),
            "codal_symbol": symbols.get(cid),
            "q_origin_before": b,
            "q_origin_after": a,
            "scoring_rows": items,
            "monthly_used_periods": len(mitems),
            "monthly_statuses": dict(Counter(i["resolved"]["status"] for i in mitems)),
        }

    # ── PIT audit buckets ───────────────────────────────────────────────────
    bucket_counts = Counter()
    pit_findings = {"confirmed_lookahead": [], "possible_lookahead": [],
                    "unknown": [], "conflicting_evidence": []}
    affected_companies = defaultdict(set)
    for cid in cids_all:
        for it in per_company_rows.get(cid, []):
            st = it["resolved"]["status"]
            pub = it["resolved"]["publish_at"]
            if st == ST_ALREADY_PUBLISHED:
                bkt = "confirmed_within_cutoff"
            elif st == ST_VERIFIED:
                dt = datetime.fromisoformat(pub) if pub else None
                if dt is None:
                    bkt = "unknown"
                elif dt > cutoff:
                    bkt = "confirmed_lookahead"
                else:
                    bkt = "recovered_within_cutoff"
            elif st == ST_AMBIGUOUS:
                cdates = [datetime.fromisoformat(c["publish_at"])
                          for c in (it["resolved"]["resolution"] or {}).get("candidates", [])
                          if c.get("publish_at")]
                if cdates and any(c > cutoff for c in cdates):
                    bkt = "possible_lookahead"
                elif cdates:
                    bkt = "unproven_but_within_cutoff"
                else:
                    bkt = "unknown"
            elif st == ST_CONFLICTING:
                bkt = "conflicting_evidence"
            else:
                bkt = "unknown"
            bucket_counts[bkt] += 1
            if bkt in pit_findings:
                pit_findings[bkt].append({
                    "company_id": cid, "symbol": symbols.get(cid),
                    "report_id": it["report_id"],
                    "period_end": it["period_end_date"],
                    "publish_at": pub,
                })
                affected_companies[bkt].add(cid)

    monthly_bucket_counts = Counter()
    for cid in cids_all:
        for it in per_company_monthly.get(cid, []):
            monthly_bucket_counts[it["resolved"]["status"]] += 1

    conn.rollback()
    conn.close()

    # ── output ──────────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)
    tag = f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_" \
          f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}"
    result = {
        "mission": "گام ۲-ک-۱ محور اول — بازیابی تاریخ انتشار واقعی + ممیزی PIT",
        "snapshot_binding": binding,
        "population": {
            "n_companies": len(cids_all),
            "n_with_scoring_rows": sum(1 for c in companies.values()
                                       if c["scoring_rows"]),
            "shortlist_ids": shortlist_ids,
        },
        "evidence_sources": {
            "cache_dir": args.cache_dir,
            "cache_files_loaded": resolver.cache_files_loaded,
            "cache_letters_loaded": resolver.cache_letters_loaded,
            "cache_letters_without_date": resolver.cache_letters_without_date,
            "db_tracing_published_rows": len(resolver.db_published_by_tracing),
        },
        "recovery_summary": {
            "scoring_rows_total": sum(len(v) for v in per_company_rows.values()),
            "scoring_rows_by_status": dict(Counter(
                it["resolved"]["status"]
                for v in per_company_rows.values() for it in v)),
            "monthly_periods_total": sum(len(v) for v in per_company_monthly.values()),
            "monthly_by_status": dict(monthly_bucket_counts),
        },
        "company_status_change": {
            "contract": "winning report rows of the latest + previous-year "
                        "cells (engine mirror compute_metrics.py:437-458); "
                        "statuses follow the evidence contract",
            "before": dict(before_counts),
            "after": dict(after_counts),
        },
        "pit_audit": {
            "buckets": dict(bucket_counts),
            "companies_affected": {k: len(v) for k, v in affected_companies.items()},
            "findings": {k: v[:200] for k, v in pit_findings.items()},
            "rule": "بدون تاریخ واقعی، lookahead قطعی اعلام نمی‌شود؛ "
                    "confirmed فقط با تاریخ تأییدشده، possible با تطبیق مبهم، "
                    "unknown یعنی هیچ شواهدی",
        },
        "companies": companies,
    }
    json_path = os.path.join(OUT_DIR, f"publish_recovery_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {json_path}")

    md_path = write_md(result, tag)
    print(f"wrote {md_path}")

    print("\n=== recovery summary ===")
    print("scoring rows:", result["recovery_summary"])
    print("company before:", dict(before_counts))
    print("company after :", dict(after_counts))
    print("pit buckets   :", dict(bucket_counts))
    return 0


def write_md(result: dict, tag: str) -> str:
    b = result["snapshot_binding"]
    rec = result["recovery_summary"]
    pit = result["pit_audit"]
    lines = []
    w = lines.append
    w(f"# گزارش بازیابی تاریخ انتشار و ممیزی PIT — {str(b['as_of'])[:10]}")
    w("")
    w(f"- اتصال به snapshot: Q `{b['q']['sha256'][:16]}…` | V `{b['v']['sha256'][:16]}…` | "
      f"T `{b['t']['sha256'][:16]}…` — cutoff `{b['cutoff']}`")
    w(f"- {GENERATED_NOTE}")
    w("")
    w("## خلاصه بازیابی")
    w("")
    w(f"- ردیف‌های امتیازساز بررسی‌شده: **{rec['scoring_rows_total']}**")
    for k, v in sorted(rec["scoring_rows_by_status"].items()):
        w(f"  - {k}: {v}")
    w(f"- دوره‌های فعالیت ماهانه استفاده‌شده: **{rec['monthly_periods_total']}**")
    for k, v in sorted(rec["monthly_by_status"].items()):
        w(f"  - {k}: {v}")
    w("")
    w("## وضعیت شرکت‌ها (قبل ← بعد)")
    w("")
    w("| وضعیت | قبل | بعد |")
    w("|---|---|---|")
    keys = ["verified_from_source", "partially_verified", "unverified", "conflicting"]
    for k in keys:
        w(f"| {k} | {result['company_status_change']['before'].get(k, 0)} | "
          f"{result['company_status_change']['after'].get(k, 0)} |")
    w("")
    w("## ممیزی PIT")
    w("")
    for k in ["confirmed_within_cutoff", "recovered_within_cutoff",
              "confirmed_lookahead", "possible_lookahead",
              "unproven_but_within_cutoff", "unknown", "conflicting_evidence"]:
        if pit["buckets"].get(k):
            w(f"- **{k}**: {pit['buckets'][k]} ردیف "
              f"({pit['companies_affected'].get(k, 0)} شرکت)")
    w("")
    w("## پیشنهاد اصلاح دائمی (فقط طرح — اجرا نشده، نیازمند بازبینی)")
    w("")
    w("```sql")
    w("-- نمونه طرح: backfill published_at برای ردیف‌های legacy با شواهد تأییدشده")
    w("-- (فقط پس از بازبینی کمیته داده؛ شواهد هر ردیف در report.json موجود است)")
    w("UPDATE ingestion.reports r SET published_at = $1")
    w("WHERE r.id = $2 AND r.published_at IS NULL")
    w("  AND EXISTS (SELECT 1 FROM provenance_staging_evidence e")
    w("              WHERE e.report_id = $2 AND e.status = 'verified_publication_date');")
    w("```")
    w("")
    path = os.path.join(OUT_DIR, f"publish_recovery_{tag}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


if __name__ == "__main__":
    raise SystemExit(main())
