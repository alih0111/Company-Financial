"""Canonical PostgreSQL writer.

All writes are explicit, idempotent and chain-consistent
(report -> report_version -> parse_run -> normalized output). No raw INSERTs are
scattered elsewhere; this is the single canonical write boundary.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from psycopg.types.json import Jsonb


class CanonicalWriter:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.cur = conn.cursor()

    # -- registry -----------------------------------------------------------
    def ensure_report(
        self,
        *,
        company_id: str,
        security_id: Optional[str],
        source: str,
        source_report_id: str,
        report_type: Optional[str],
        period_end_date: Optional[str],
        jalali_period_text: Optional[str],
        title: Optional[str] = None,
        source_url: Optional[str] = None,
        published_at: Optional[str] = None,
        processing_status: str = "completed",
        supersedes_report_id: Optional[str] = None,
    ) -> tuple[str, bool]:
        self.cur.execute(
            """
            INSERT INTO ingestion.reports
              (company_id, security_id, source, source_report_id, report_type, title,
               period_end_date, jalali_period_text, published_at, source_url, processing_status,
               supersedes_report_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, source_report_id) DO UPDATE SET
              supersedes_report_id = COALESCE(EXCLUDED.supersedes_report_id, ingestion.reports.supersedes_report_id),
              security_id = COALESCE(EXCLUDED.security_id, ingestion.reports.security_id),
              report_type = COALESCE(EXCLUDED.report_type, ingestion.reports.report_type),
              title = COALESCE(EXCLUDED.title, ingestion.reports.title),
              period_end_date = COALESCE(EXCLUDED.period_end_date, ingestion.reports.period_end_date),
              jalali_period_text = COALESCE(EXCLUDED.jalali_period_text, ingestion.reports.jalali_period_text),
              published_at = COALESCE(EXCLUDED.published_at, ingestion.reports.published_at),
              source_url = COALESCE(EXCLUDED.source_url, ingestion.reports.source_url),
              processing_status = EXCLUDED.processing_status
            RETURNING id, (xmax = 0) AS inserted
            """,
            (company_id, security_id, source, source_report_id, report_type, title,
             period_end_date, jalali_period_text, published_at, source_url, processing_status,
             supersedes_report_id),
        )
        rid, inserted = self.cur.fetchone()
        return str(rid), bool(inserted)

    def lookup_report_id(self, source: str, source_report_id: str) -> Optional[str]:
        self.cur.execute(
            "SELECT id FROM ingestion.reports WHERE source=%s AND source_report_id=%s",
            (source, source_report_id),
        )
        row = self.cur.fetchone()
        return str(row[0]) if row else None

    def append_report_version(
        self,
        *,
        report_id: str,
        content_hash: str,
        source_url: Optional[str] = None,
        collected_at: Optional[str] = None,
    ) -> tuple[str, bool]:
        self.cur.execute(
            """
            INSERT INTO ingestion.report_versions (report_id, version_no, content_hash, source_url, collected_at)
            VALUES (%s, COALESCE((SELECT MAX(version_no) FROM ingestion.report_versions WHERE report_id=%s),0)+1,
                    %s, %s, COALESCE(%s, now()))
            ON CONFLICT (report_id, content_hash) DO NOTHING
            RETURNING id
            """,
            (report_id, report_id, content_hash, source_url, collected_at),
        )
        row = self.cur.fetchone()
        if row:
            return str(row[0]), True
        self.cur.execute(
            "SELECT id FROM ingestion.report_versions WHERE report_id=%s AND content_hash=%s",
            (report_id, content_hash),
        )
        return str(self.cur.fetchone()[0]), False

    def start_parse_run(
        self,
        *,
        report_version_id: str,
        parser_name: str,
        parser_version: str,
        code_version: Optional[str] = None,
        parameters: Optional[dict] = None,
    ) -> tuple[str, bool]:
        self.cur.execute(
            """SELECT id FROM ingestion.parse_runs
               WHERE report_version_id=%s AND parser_name=%s AND parser_version=%s AND status='completed'
               LIMIT 1""",
            (report_version_id, parser_name, parser_version),
        )
        row = self.cur.fetchone()
        if row:
            return str(row[0]), False
        self.cur.execute(
            """INSERT INTO ingestion.parse_runs
               (report_version_id, parser_name, parser_version, code_version, parameters, status)
               VALUES (%s,%s,%s,%s,%s,'running') RETURNING id""",
            (report_version_id, parser_name, parser_version, code_version, Jsonb(parameters or {})),
        )
        return str(self.cur.fetchone()[0]), True

    def finish_parse_run(self, parse_run_id: str, *, status: str, error_message: Optional[str] = None) -> None:
        self.cur.execute(
            "UPDATE ingestion.parse_runs SET status=%s, finished_at=now(), error_message=%s WHERE id=%s AND status='running'",
            (status, error_message, parse_run_id),
        )

    def store_raw_payload(
        self,
        *,
        report_version_id: str,
        payload_type: str,
        content_hash: str,
        content_text: Optional[str] = None,
        content_json: Optional[dict] = None,
        storage_uri: Optional[str] = None,
        mime_type: Optional[str] = None,
        byte_size: Optional[int] = None,
        collected_at: Optional[str] = None,
    ) -> tuple[Optional[str], bool]:
        self.cur.execute(
            """INSERT INTO raw.report_payloads
               (report_version_id, payload_type, content_hash, content_text, content_json,
                storage_uri, mime_type, byte_size, collected_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s, now()))
               ON CONFLICT (report_version_id, payload_type, content_hash) DO NOTHING
               RETURNING id""",
            (report_version_id, payload_type, content_hash, content_text,
             Jsonb(content_json) if content_json is not None else None,
             storage_uri, mime_type, byte_size, collected_at),
        )
        row = self.cur.fetchone()
        return (str(row[0]), True) if row else (None, False)

    # -- normalized ---------------------------------------------------------
    def find_monthly_activity(self, company_id: str, period_end_date: str) -> Optional[str]:
        self.cur.execute(
            """SELECT id FROM fundamentals.monthly_activities
               WHERE company_id=%s AND period_end_date=%s LIMIT 1""",
            (company_id, period_end_date),
        )
        row = self.cur.fetchone()
        return str(row[0]) if row else None

    def find_statement(self, company_id: str, period_end_date: str, statement_type: str) -> Optional[str]:
        self.cur.execute(
            """SELECT id FROM fundamentals.financial_statements
               WHERE company_id=%s AND period_end_date=%s AND statement_type=%s LIMIT 1""",
            (company_id, period_end_date, statement_type),
        )
        row = self.cur.fetchone()
        return str(row[0]) if row else None

    def insert_monthly_activity(
        self,
        *,
        company_id: str,
        security_id: Optional[str],
        report_id: str,
        report_version_id: str,
        parse_run_id: str,
        period_end_date: str,
        jalali_period_text: Optional[str],
        production_quantity: Any = None,
        sales_quantity: Any = None,
        sales_amount_rial: Any = None,
        reported_sales_amount: Any = None,
        reported_currency_unit: Optional[str] = None,
        reported_unit_multiplier: Any = None,
        quantity_unit: Optional[str] = None,
    ) -> tuple[Optional[str], bool]:
        self.cur.execute(
            """INSERT INTO fundamentals.monthly_activities
               (company_id, security_id, report_id, report_version_id, parse_run_id,
                period_end_date, jalali_period_text, production_quantity, sales_quantity,
                sales_amount_rial, reported_sales_amount, reported_currency_unit,
                reported_unit_multiplier, quantity_unit)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (parse_run_id) DO NOTHING
               RETURNING id""",
            (company_id, security_id, report_id, report_version_id, parse_run_id,
             period_end_date, jalali_period_text, production_quantity, sales_quantity,
             sales_amount_rial, reported_sales_amount, reported_currency_unit,
             reported_unit_multiplier, quantity_unit),
        )
        row = self.cur.fetchone()
        return (str(row[0]), True) if row else (None, False)

    def ensure_statement(
        self,
        *,
        company_id: str,
        report_id: str,
        report_version_id: str,
        parse_run_id: str,
        statement_type: str,
        period_end_date: str,
        is_cumulative: Optional[bool],
        reported_currency_unit: str = "million_rial",
    ) -> tuple[str, bool]:
        self.cur.execute(
            """INSERT INTO fundamentals.financial_statements
               (company_id, report_id, report_version_id, parse_run_id, statement_type,
                period_end_date, is_cumulative, reported_currency_unit)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (parse_run_id, statement_type) DO NOTHING
               RETURNING id""",
            (company_id, report_id, report_version_id, parse_run_id, statement_type,
             period_end_date, is_cumulative, reported_currency_unit),
        )
        row = self.cur.fetchone()
        if row:
            return str(row[0]), True
        self.cur.execute(
            "SELECT id FROM fundamentals.financial_statements WHERE parse_run_id=%s AND statement_type=%s",
            (parse_run_id, statement_type),
        )
        return str(self.cur.fetchone()[0]), False

    def insert_fact(
        self,
        *,
        statement_id: str,
        metric_code: str,
        period_order: int,
        comparison_type: Optional[str],
        reported_value: Any,
        reported_unit: Optional[str],
        canonical_value: Any,
        canonical_unit: Optional[str],
        row_title: Optional[str] = None,
        source_row_key: Optional[str] = None,
    ) -> tuple[Optional[str], bool]:
        self.cur.execute(
            """INSERT INTO fundamentals.financial_facts
               (statement_id, metric_code, row_title, period_order, comparison_type,
                reported_value, reported_unit, canonical_value, canonical_unit,
                is_derived_from_source, source_row_key)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s)
               ON CONFLICT (statement_id, metric_code, period_order) DO NOTHING
               RETURNING id""",
            (statement_id, metric_code, row_title, period_order, comparison_type,
             reported_value, reported_unit, canonical_value, canonical_unit, source_row_key),
        )
        row = self.cur.fetchone()
        return (str(row[0]), True) if row else (None, False)

    def insert_price_observation(
        self,
        *,
        security_id: str,
        trade_date: str,
        source: str,
        values: dict,
        collected_at: Optional[str] = None,
        jalali_date_text: Optional[str] = None,
        provenance: Optional[dict] = None,
    ) -> tuple[Optional[str], bool]:
        observation_hash = _observation_hash(security_id, trade_date, source, values)
        # Natural-key compatibility lookup: an identical logical observation may
        # already exist under a different historical content-hash serialization
        # (e.g. rows written by the migration). Do not append a duplicate.
        series = values.get("price_series", "adjusted")
        self.cur.execute(
            """SELECT id FROM market.price_observations
               WHERE security_id=%s AND trade_date=%s AND source=%s AND price_series=%s
                 AND closing_price_rial IS NOT DISTINCT FROM %s
                 AND volume IS NOT DISTINCT FROM %s
                 AND trade_value_rial IS NOT DISTINCT FROM %s
               LIMIT 1""",
            (security_id, trade_date, source, series,
             values.get("closing_price_rial"), values.get("volume"), values.get("trade_value_rial")),
        )
        existing = self.cur.fetchone()
        if existing:
            return str(existing[0]), False
        self.cur.execute(
            """INSERT INTO market.price_observations
               (security_id, trade_date, price_series, first_price_rial, open_price_rial,
                high_price_rial, low_price_rial, closing_price_rial, last_price_rial,
                yesterday_price_rial, closing_change_rial, closing_change_percent,
                last_change_rial, last_change_percent, volume, trade_value_rial, trade_count,
                is_adjusted, adjustment_method, adjustment_version, provenance, source,
                source_url, collected_at, jalali_date_text, observation_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       COALESCE(%s, now()),%s,%s)
               ON CONFLICT (security_id, trade_date, source, price_series, observation_hash) DO NOTHING
               RETURNING id""",
            (
                security_id, trade_date, values.get("price_series", "adjusted"),
                values.get("first_price_rial"), values.get("open_price_rial"),
                values.get("high_price_rial"), values.get("low_price_rial"),
                values.get("closing_price_rial"), values.get("last_price_rial"),
                values.get("yesterday_price_rial"), values.get("closing_change_rial"),
                values.get("closing_change_percent"), values.get("last_change_rial"),
                values.get("last_change_percent"), values.get("volume"),
                values.get("trade_value_rial"), values.get("trade_count"),
                values.get("is_adjusted", True), values.get("adjustment_method"),
                values.get("adjustment_version"), Jsonb(provenance or {}), source,
                values.get("source_url"), collected_at, jalali_date_text, observation_hash,
            ),
        )
        row = self.cur.fetchone()
        return (str(row[0]), True) if row else (None, False)

    # -- diagnostics --------------------------------------------------------
    def quarantine(
        self,
        *,
        entity_type: str,
        issue_code: str,
        severity: str,
        details: dict,
        entity_id: Optional[str] = None,
    ) -> str:
        self.cur.execute(
            """INSERT INTO ingestion.data_quality_issues
               (entity_type, entity_id, issue_code, severity, details)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (entity_type, entity_id, issue_code, severity, Jsonb(details)),
        )
        return str(self.cur.fetchone()[0])


def _observation_hash(security_id: str, trade_date: str, source: str, values: dict) -> str:
    parts = [security_id, trade_date, source, values.get("price_series", "adjusted")]
    for key in ("first_price_rial", "open_price_rial", "high_price_rial", "low_price_rial",
                "closing_price_rial", "last_price_rial", "yesterday_price_rial",
                "closing_change_rial", "closing_change_percent", "last_change_rial",
                "last_change_percent", "volume", "trade_value_rial", "trade_count"):
        parts.append(str(values.get(key)))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
