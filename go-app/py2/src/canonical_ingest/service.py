"""Dual-write orchestration.

Each dual-write is additive and isolated:

* LEGACY_ONLY (default) -> no canonical write at all.
* DUAL_WRITE / CANONICAL_ONLY -> canonical write inside one explicit
  transaction; any failure rolls back and is returned as an error without
  affecting the legacy path (the legacy write already happened / is untouched).
* Unresolved identity -> quarantine row, no fabricated identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import IngestionMode, load_mode, writes_canonical
from .db import transaction
from .identity import primary_security_for_company, resolve_company, resolve_security
from .writer import CanonicalWriter


@dataclass
class DualWriteResult:
    domain: str
    status: str
    inserted: int = 0
    skipped: int = 0
    detail: str = ""
    error: str = ""
    ids: dict = field(default_factory=dict)

    @property
    def written(self) -> bool:
        return self.status == "written"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dual_write_report(
    *,
    legacy_company_id: str | None = None,
    ins_code: str | int | None = None,
    name: str | None = None,
    symbol: str | None = None,
    source: str = "codal",
    source_report_id: str,
    report_type: str | None = None,
    period_end_date: str | None = None,
    jalali_period_text: str | None = None,
    title: str | None = None,
    source_url: str | None = None,
    published_at: str | None = None,
    content_text: str | None = None,
    content_json: dict | None = None,
    payload_type: str = "json",
    collected_at: str | None = None,
    parser_name: str = "canonical_ingest",
    parser_version: str = "v1",
    supersedes_source_report_id: str | None = None,
    mode: IngestionMode | None = None,
) -> DualWriteResult:
    if not writes_canonical(mode):
        return DualWriteResult("codal_report", "skipped_legacy_only")
    try:
        with transaction() as conn:
            w = CanonicalWriter(conn)
            company_id = resolve_company(conn.cursor(), legacy_company_id=legacy_company_id,
                                         ins_code=ins_code, name=name, symbol=symbol)
            if not company_id:
                w.quarantine(entity_type="company", issue_code="identity_conflict", severity="high",
                             details={"domain": "codal_report", "source_report_id": source_report_id,
                                      "legacy_company_id": legacy_company_id, "name": name,
                                      "symbol": symbol})
                return DualWriteResult("codal_report", "quarantined", detail="company unresolved")
            security_id = resolve_security(conn.cursor(), legacy_company_id=legacy_company_id,
                                           ins_code=ins_code, symbol=symbol, name=name)
            supersedes_id = None
            if supersedes_source_report_id:
                supersedes_id = w.lookup_report_id(source, str(supersedes_source_report_id))
            rid, r_ins = w.ensure_report(
                company_id=company_id, security_id=security_id, source=source,
                source_report_id=source_report_id, report_type=report_type,
                period_end_date=period_end_date, jalali_period_text=jalali_period_text,
                title=title, source_url=source_url, published_at=published_at,
                supersedes_report_id=supersedes_id,
            )
            digest = _content_hash(content_text if content_text is not None else repr(content_json or {}))
            vid, v_ins = w.append_report_version(report_id=rid, content_hash=digest,
                                                 source_url=source_url, collected_at=collected_at)
            _pid, p_ins = w.start_parse_run(report_version_id=vid, parser_name=parser_name,
                                            parser_version=parser_version)
            raw_ins = False
            if content_text is not None or content_json is not None:
                byte_size = len(content_text.encode("utf-8")) if content_text is not None else None
                _rawid, raw_ins = w.store_raw_payload(
                    report_version_id=vid, payload_type=payload_type, content_hash=digest,
                    content_text=content_text, content_json=content_json,
                    mime_type="application/json" if payload_type == "json" else "text/html",
                    byte_size=byte_size, collected_at=collected_at,
                )
            w.finish_parse_run(_pid, status="completed")
            return DualWriteResult(
                "codal_report", "written",
                inserted=int(r_ins) + int(v_ins) + int(p_ins) + int(raw_ins),
                skipped=int(not r_ins) + int(not v_ins) + int(not p_ins) + int(not raw_ins),
                ids={"report_id": rid, "report_version_id": vid},
            )
    except Exception as exc:  # noqa: BLE001 - isolation boundary
        return DualWriteResult("codal_report", "canonical_error", error=str(exc))


def dual_write_monthly(
    *,
    legacy_company_id: str,
    period_end_date: str,
    jalali_period_text: str | None = None,
    production_quantity: Any = None,
    sales_quantity: Any = None,
    sales_amount_rial: Any = None,
    reported_sales_amount: Any = None,
    reported_currency_unit: str | None = "million_rial",
    reported_unit_multiplier: Any = 1000000,
    quantity_unit: str | None = None,
    source_report_id: str | None = None,
    content_json: dict | None = None,
    collected_at: str | None = None,
    mode: IngestionMode | None = None,
) -> DualWriteResult:
    if not writes_canonical(mode):
        return DualWriteResult("monthly_activity", "skipped_legacy_only")
    try:
        with transaction() as conn:
            w = CanonicalWriter(conn)
            cur = conn.cursor()
            company_id = resolve_company(cur, legacy_company_id=legacy_company_id)
            if not company_id:
                w.quarantine(entity_type="company", issue_code="identity_conflict", severity="high",
                             details={"domain": "monthly_activity", "legacy_company_id": legacy_company_id,
                                      "period_end_date": period_end_date})
                return DualWriteResult("monthly_activity", "quarantined", detail="company unresolved")
            security_id = resolve_security(cur, legacy_company_id=legacy_company_id) \
                or primary_security_for_company(cur, company_id)
            srid = source_report_id or f"legacy:{legacy_company_id}:{period_end_date}:monthly"
            digest = _content_hash(srid)
            rid, r_ins = w.ensure_report(
                company_id=company_id, security_id=security_id, source="legacy_sqlserver",
                source_report_id=srid, report_type="monthly_activity",
                period_end_date=period_end_date, jalali_period_text=jalali_period_text,
            )
            vid, v_ins = w.append_report_version(report_id=rid, content_hash=digest, collected_at=collected_at)
            pid, p_ins = w.start_parse_run(report_version_id=vid, parser_name="legacy_sqlserver",
                                           parser_version="legacy_import_v1")
            # Logical idempotency: never create a duplicate monthly row for the same
            # (company, period), regardless of parse-chain identity.
            existing = w.find_monthly_activity(company_id, period_end_date)
            if existing:
                w.finish_parse_run(pid, status="completed")
                return DualWriteResult(
                    "monthly_activity", "written",
                    inserted=int(r_ins) + int(v_ins) + int(p_ins),
                    skipped=1 + int(not r_ins) + int(not v_ins) + int(not p_ins),
                    detail="already present", ids={"monthly_activity_id": existing},
                )
            mid, m_ins = w.insert_monthly_activity(
                company_id=company_id, security_id=security_id, report_id=rid,
                report_version_id=vid, parse_run_id=pid, period_end_date=period_end_date,
                jalali_period_text=jalali_period_text, production_quantity=production_quantity,
                sales_quantity=sales_quantity, sales_amount_rial=sales_amount_rial,
                reported_sales_amount=reported_sales_amount,
                reported_currency_unit=reported_currency_unit,
                reported_unit_multiplier=reported_unit_multiplier, quantity_unit=quantity_unit,
            )
            w.finish_parse_run(pid, status="completed")
            return DualWriteResult(
                "monthly_activity", "written",
                inserted=int(r_ins) + int(v_ins) + int(p_ins) + int(m_ins),
                skipped=int(not r_ins) + int(not v_ins) + int(not p_ins) + int(not m_ins),
                ids={"report_id": rid, "report_version_id": vid, "parse_run_id": pid,
                     "monthly_activity_id": mid},
            )
    except Exception as exc:  # noqa: BLE001
        return DualWriteResult("monthly_activity", "canonical_error", error=str(exc))


def dual_write_financial(
    *,
    legacy_company_id: str,
    period_end_date: str,
    jalali_period_text: str | None = None,
    facts: list[dict],
    source_report_id: str | None = None,
    content_json: dict | None = None,
    collected_at: str | None = None,
    mode: IngestionMode | None = None,
) -> DualWriteResult:
    if not writes_canonical(mode):
        return DualWriteResult("financial_statement", "skipped_legacy_only")
    try:
        with transaction() as conn:
            w = CanonicalWriter(conn)
            cur = conn.cursor()
            company_id = resolve_company(cur, legacy_company_id=legacy_company_id)
            if not company_id:
                w.quarantine(entity_type="company", issue_code="identity_conflict", severity="high",
                             details={"domain": "financial_statement", "legacy_company_id": legacy_company_id,
                                      "period_end_date": period_end_date})
                return DualWriteResult("financial_statement", "quarantined", detail="company unresolved")
            security_id = resolve_security(cur, legacy_company_id=legacy_company_id) \
                or primary_security_for_company(cur, company_id)
            srid = source_report_id or f"legacy:{legacy_company_id}:{period_end_date}:financial"
            digest = _content_hash(srid)
            rid, r_ins = w.ensure_report(
                company_id=company_id, security_id=security_id, source="legacy_sqlserver",
                source_report_id=srid, report_type="financial_statement",
                period_end_date=period_end_date, jalali_period_text=jalali_period_text,
            )
            vid, v_ins = w.append_report_version(report_id=rid, content_hash=digest, collected_at=collected_at)
            pid, p_ins = w.start_parse_run(report_version_id=vid, parser_name="legacy_sqlserver",
                                           parser_version="legacy_import_v1")
            inserted = int(r_ins) + int(v_ins) + int(p_ins)
            skipped = int(not r_ins) + int(not v_ins) + int(not p_ins)
            seen_statements: set[str] = set()
            for fact in facts:
                stype = fact["statement_type"]
                if w.find_statement(company_id, period_end_date, stype):
                    # Statement for this (company, period, type) already exists; do
                    # not create duplicate facts.
                    skipped += 1
                    seen_statements.add(stype)
                    continue
                sid, s_ins = w.ensure_statement(
                    company_id=company_id, report_id=rid, report_version_id=vid, parse_run_id=pid,
                    statement_type=stype, period_end_date=period_end_date,
                    is_cumulative=fact.get("is_cumulative"),
                )
                inserted += int(s_ins)
                skipped += int(not s_ins)
                seen_statements.add(stype)
                _fid, f_ins = w.insert_fact(
                    statement_id=sid, metric_code=fact["metric_code"],
                    period_order=fact["period_order"], comparison_type=fact.get("comparison_type"),
                    reported_value=fact.get("reported_value"), reported_unit=fact.get("reported_unit"),
                    canonical_value=fact.get("canonical_value"), canonical_unit=fact.get("canonical_unit"),
                    row_title=fact.get("row_title"), source_row_key=fact.get("source_row_key"),
                )
                inserted += int(f_ins)
                skipped += int(not f_ins)
            w.finish_parse_run(pid, status="completed")
            return DualWriteResult("financial_statement", "written", inserted=inserted, skipped=skipped,
                                   ids={"report_id": rid, "report_version_id": vid, "parse_run_id": pid,
                                        "statements": len(seen_statements)})
    except Exception as exc:  # noqa: BLE001
        return DualWriteResult("financial_statement", "canonical_error", error=str(exc))


def dual_write_market(
    *,
    legacy_company_id: str | None = None,
    ins_code: str | int | None = None,
    symbol: str | None = None,
    observations: list[dict],
    source: str = "brs",
    mode: IngestionMode | None = None,
) -> DualWriteResult:
    if not writes_canonical(mode):
        return DualWriteResult("market_price", "skipped_legacy_only")
    try:
        with transaction() as conn:
            w = CanonicalWriter(conn)
            cur = conn.cursor()
            security_id = resolve_security(cur, legacy_company_id=legacy_company_id,
                                           ins_code=ins_code, symbol=symbol)
            if not security_id:
                w.quarantine(entity_type="security", issue_code="identity_conflict", severity="high",
                             details={"domain": "market_price", "legacy_company_id": legacy_company_id,
                                      "symbol": symbol})
                return DualWriteResult("market_price", "quarantined", detail="security unresolved")
            inserted = skipped = 0
            for obs in observations:
                _id, ins = w.insert_price_observation(
                    security_id=security_id, trade_date=obs["trade_date"], source=obs.get("source", source),
                    values=obs, collected_at=obs.get("collected_at"),
                    jalali_date_text=obs.get("jalali_date_text"), provenance=obs.get("provenance"),
                )
                inserted += int(ins)
                skipped += int(not ins)
            return DualWriteResult("market_price", "written", inserted=inserted, skipped=skipped,
                                   ids={"security_id": security_id})
    except Exception as exc:  # noqa: BLE001
        return DualWriteResult("market_price", "canonical_error", error=str(exc))
