"""Adapt Quick Sync's canonical PostgreSQL data to the locked ranking inputs.

This module changes no ranking formula.  It only makes already-collected,
point-in-time eligible financial statements and monthly sales visible to the
existing V12.37 input format.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PY2_SRC = ROOT / "go-app/py2/src"
if str(PY2_SRC) not in sys.path:
    sys.path.insert(0, str(PY2_SRC))

TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _iso(value) -> str:
    return pd.Timestamp(value).isoformat()


def _normal(value: object) -> str:
    text = str(value or "").translate(PERSIAN_DIGITS).replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", text).strip()


def _next_market_day(*values) -> str:
    """Conservative first usable day from publication and local receipt.

    Ranking remains PREPARATION_UNCONFIRMED.  Thursday/Friday are skipped, and
    a report is never made available before either publication or collection.
    """
    local_dates = [pd.Timestamp(value).tz_convert("Asia/Tehran").date() for value in values if value is not None]
    day = max(local_dates) + dt.timedelta(days=1)
    while day.weekday() in (3, 4):
        day += dt.timedelta(days=1)
    return day.isoformat()


def _letter_index(conn, company_ids: list[str], cutoff: pd.Timestamp):
    if not company_ids:
        return defaultdict(list)
    rows = conn.execute(
        """
        SELECT r.company_id::text, r.source_report_id, r.title, r.published_at,
               r.source_url, max(rv.collected_at) AS collected_at
        FROM ingestion.reports r
        LEFT JOIN ingestion.report_versions rv ON rv.report_id = r.id
        WHERE r.company_id = ANY(%s::uuid[])
          AND r.source = 'codal'
          AND r.processing_status = 'completed'
          AND r.published_at IS NOT NULL AND r.published_at < %s
        GROUP BY r.id
        HAVING max(rv.collected_at) IS NULL OR max(rv.collected_at) < %s
        """,
        (company_ids, cutoff.to_pydatetime(), cutoff.to_pydatetime()),
    ).fetchall()
    out = defaultdict(list)
    for company_id, source_id, title, published_at, source_url, collected_at in rows:
        out[str(company_id)].append({
            "source_id": str(source_id), "title": str(title or ""),
            "published_at": published_at, "source_url": source_url,
            "collected_at": collected_at,
        })
    return out


def _matching_letter(letters, jalali_period: str, kind: str):
    needle = _normal(jalali_period).replace("-", "/")
    matches = []
    for row in letters:
        title = _normal(row["title"])
        if needle not in title:
            continue
        if kind == "financial" and not ("صورت" in title and "مالی" in title):
            continue
        if kind == "monthly" and "گزارش فعالیت ماهانه" not in title:
            continue
        matches.append(row)
    return max(matches, key=lambda row: (row["published_at"], row["source_id"]), default=None)


def merge_canonical_inputs(reports: list[dict], lineage: list[dict], comparisons: list[dict],
                           events: pd.DataFrame, cutoff: pd.Timestamp,
                           evaluation_date: str) -> dict:
    """Merge canonical rows in place and return an auditable admission summary."""
    from canonical_ingest.config import canonical_dsn
    import psycopg

    symbols = {}
    latest_base_period = {}
    for record in reports:
        cid = str(record.get("company_id"))
        if record.get("symbol"):
            symbols[cid] = str(record["symbol"])
        period = str(record.get("period_end") or "")
        if period:
            latest_base_period[cid] = max(period, latest_base_period.get(cid, ""))
    company_ids = sorted(symbols)
    if not company_ids:
        return {"financial_admitted": 0, "sales_admitted": 0, "financial_ids": [], "state": "empty_universe"}

    with psycopg.connect(canonical_dsn()) as conn:
        letters = _letter_index(conn, company_ids, cutoff)
        financial_rows = conn.execute(
            """
            WITH picked AS (
              SELECT DISTINCT ON (fs.company_id, fs.period_end_date, fs.statement_type)
                     fs.id, fs.company_id::text AS company_id, fs.period_end_date,
                     fs.statement_type, r.source_report_id, r.jalali_period_text,
                     rv.collected_at
              FROM fundamentals.financial_statements fs
              JOIN ingestion.reports r ON r.id = fs.report_id
              JOIN ingestion.report_versions rv ON rv.id = fs.report_version_id
              WHERE fs.company_id = ANY(%s::uuid[])
                AND fs.period_end_date <= %s::date
                AND rv.collected_at < %s
              ORDER BY fs.company_id, fs.period_end_date, fs.statement_type,
                       rv.collected_at DESC, fs.created_at DESC
            )
            SELECT p.company_id, p.period_end_date, p.statement_type,
                   p.source_report_id, p.jalali_period_text, p.collected_at,
                   f.metric_code, f.period_order, f.comparison_type,
                   f.canonical_value, f.canonical_unit
            FROM picked p
            JOIN fundamentals.financial_facts f ON f.statement_id = p.id
            WHERE f.canonical_value IS NOT NULL
              AND f.canonical_unit IN ('rial', 'rial_per_share')
            ORDER BY p.company_id, p.period_end_date, p.statement_type,
                     f.metric_code, f.period_order
            """,
            (company_ids, evaluation_date, cutoff.to_pydatetime()),
        ).fetchall()

        monthly_rows = conn.execute(
            """
            SELECT DISTINCT ON (ma.company_id, ma.period_end_date)
                   ma.company_id::text, ma.security_id::text, ma.period_end_date,
                   ma.jalali_period_text, ma.sales_amount_rial,
                   r.source_report_id, rv.collected_at
            FROM fundamentals.monthly_activities ma
            JOIN ingestion.reports r ON r.id = ma.report_id
            JOIN ingestion.report_versions rv ON rv.id = ma.report_version_id
            WHERE ma.company_id = ANY(%s::uuid[])
              AND ma.period_end_date <= %s::date
              AND ma.sales_amount_rial IS NOT NULL
              AND rv.collected_at < %s
            ORDER BY ma.company_id, ma.period_end_date, rv.collected_at DESC,
                     ma.created_at DESC
            """,
            (company_ids, evaluation_date, cutoff.to_pydatetime()),
        ).fetchall()

    grouped = defaultdict(list)
    meta = {}
    for row in financial_rows:
        (cid, period, statement, source_report_id, jalali_period, collected_at,
         metric, order, comparison_type, value, unit) = row
        cid, period = str(cid), str(period)
        if period < latest_base_period.get(cid, ""):
            continue
        key = (cid, period)
        meta[key] = {"source_report_id": str(source_report_id),
                     "jalali_period": str(jalali_period or ""), "collected_at": collected_at}
        grouped[key].append({"statement_type": str(statement), "metric_code": str(metric),
                             "period_order": int(order), "comparison_type": comparison_type,
                             "value": float(value), "unit": str(unit), "basis": "parent"})

    used_keys = {(str(r.get("company_id")), str(r.get("tracing_no"))) for r in reports}
    existing_period_pubs = defaultdict(set)
    for record in reports:
        try:
            instant = pd.Timestamp(record["published_at"]).tz_convert("UTC").isoformat()
            existing_period_pubs[(str(record["company_id"]), str(record["period_end"]))].add(instant)
        except (KeyError, TypeError, ValueError):
            continue
    admitted_financial = []
    fresh_ids = set()
    for (cid, period), facts in sorted(grouped.items()):
        info = meta[(cid, period)]
        letter = _matching_letter(letters[cid], info["jalali_period"], "financial")
        published = letter["published_at"] if letter else info["collected_at"]
        observed = max(x for x in (info["collected_at"], letter and letter.get("collected_at")) if x is not None)
        tracing = "canonical:" + (letter["source_id"] if letter else info["source_report_id"])
        published_instant = pd.Timestamp(published).tz_convert("UTC").isoformat()
        if published_instant in existing_period_pubs[(cid, period)]:
            continue
        if (cid, tracing) in used_keys:
            continue
        own = [{k: fact[k] for k in ("statement_type", "metric_code", "value", "unit", "basis", "period_order")}
               for fact in facts if fact["period_order"] == 1]
        if not own:
            continue
        payload = json.dumps(own, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        record = {
            "company_id": cid, "symbol": symbols[cid], "tracing_no": tracing,
            "title": letter["title"] if letter else f"Canonical financial statement {info['jalali_period']}",
            "period_end": period, "published_at": _iso(published), "observed_at": _iso(observed),
            "available_at_utc": pd.Timestamp(observed).tz_convert("UTC").isoformat(),
            "sha256": hashlib.sha256(payload).hexdigest(), "source": "canonical_postgres_quick_sync",
            "source_report_id": letter["source_id"] if letter else info["source_report_id"],
            "source_url": letter.get("source_url") if letter else None,
            "history_basis": "canonical_quick_sync_point_in_time", "facts": own,
        }
        reports.append(record)
        lineage.append({"company_id": cid, "period": period, "published_at": record["published_at"],
                        "observed_at": record["observed_at"], "tracing_no": tracing,
                        "source": "canonical_postgres_quick_sync"})
        for fact in facts:
            if fact["period_order"] == 1:
                continue
            comparisons.append({"company_id": cid, "tracing_no": tracing, "period": period,
                "statement_type": fact["statement_type"], "metric_code": fact["metric_code"],
                "period_order": fact["period_order"], "canonical_value": fact["value"],
                "canonical_unit": fact["unit"], "comparative_period": None, "basis": "parent",
                "source": "canonical_postgres_quick_sync", "available_at_utc": record["available_at_utc"],
                "published_at": record["published_at"], "company_id_verified": cid})
        used_keys.add((cid, tracing))
        existing_period_pubs[(cid, period)].add(published_instant)
        # Recompute the locked financial factors only when Quick Sync advances
        # the company's period.  Same-period canonical copies still improve
        # lineage, but must not discard the richer frozen feature history.
        if period > latest_base_period.get(cid, ""):
            fresh_ids.add(cid)
        admitted_financial.append({"company_id": cid, "symbol": symbols[cid], "period_end": period,
                                   "tracing_no": tracing, "published_at": record["published_at"],
                                   "received_at": record["observed_at"]})

    existing_event_ids = set(events.event_id.astype(str))
    latest_event_period = {}
    for row in events[["company_id", "period_end"]].itertuples(index=False):
        cid, period = str(row.company_id), str(row.period_end)[:10]
        latest_event_period[cid] = max(period, latest_event_period.get(cid, ""))
    admitted_sales = []
    new_event_rows = []
    for cid, security_id, period, jalali_period, sales, source_report_id, collected_at in monthly_rows:
        cid, period = str(cid), str(period)
        if cid not in symbols or period <= latest_event_period.get(cid, ""):
            continue
        letter = _matching_letter(letters[cid], str(jalali_period or ""), "monthly")
        published = letter["published_at"] if letter else collected_at
        event_id = letter["source_id"] if letter else "canonical-monthly:" + str(source_report_id)
        if event_id in existing_event_ids:
            continue
        row = {column: None for column in events.columns}
        row.update({"event_id": event_id, "publication_role": "original", "is_correction": False,
            "security_id": security_id, "symbol": symbols[cid], "company_id": cid,
            "event_type": "monthly_sales_report", "period_end": dt.date.fromisoformat(period),
            "match_status": "MATCH_CANONICAL_QUICK_SYNC", "CURRENT_PERIOD_SALES": float(sales),
            "current_value_version_known": True, "current_period_has_correction": False,
            "published_at_raw_jalali": None,
            "published_at_tehran": pd.Timestamp(published).tz_convert("Asia/Tehran").tz_localize(None),
            "published_at": pd.Timestamp(published).tz_convert("UTC"),
            "tehran_date": pd.Timestamp(published).tz_convert("Asia/Tehran").date(),
            "signal_entry_date": _next_market_day(published, collected_at),
            "letter_title": letter["title"] if letter else f"Canonical monthly activity {jalali_period}",
            "source_url": letter.get("source_url") if letter else None,
            "source": "canonical_postgres_quick_sync", "ineligibility_reason": "", "event_eligible": True})
        new_event_rows.append(row)
        existing_event_ids.add(event_id)
        admitted_sales.append({"company_id": cid, "symbol": symbols[cid], "period_end": period,
                               "tracing_no": event_id, "published_at": _iso(published),
                               "received_at": _iso(collected_at), "signal_entry_date": row["signal_entry_date"]})

    if new_event_rows:
        events = pd.concat([events, pd.DataFrame(new_event_rows)], ignore_index=True)

    return {"state": "canonical_quick_sync_merged", "events": events,
            "financial_admitted": len(admitted_financial), "sales_admitted": len(admitted_sales),
            "financial_ids": sorted(fresh_ids), "financial_inputs": admitted_financial,
            "sales_inputs": admitted_sales}
