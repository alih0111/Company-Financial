"""Legacy-script -> canonical ingestion hook.

Called by the existing ingestion scripts *after* their successful SQL Server
write. It never changes legacy behavior and never raises into the caller.

Mode contract (``CDF_INGESTION_MODE``):
  * LEGACY_ONLY (default): returns immediately, imports nothing canonical,
    performs zero PostgreSQL work.
  * DUAL_WRITE / CANONICAL_ONLY: attempts the canonical write in a separate,
    isolated transaction and records a per-batch result.

Canonical writer: ``go-app/py2/src/canonical_ingest`` (single write boundary).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

_HERE = pathlib.Path(__file__).resolve()
_GO_APP = _HERE.parent.parent
_PY2_SRC = _GO_APP / "py2" / "src"
_OUT_DIR = _GO_APP.parent / "ingestion_migration_v1" / "output"
log = logging.getLogger("codal.canonical_hook")

_LEGACY_ONLY = "legacy_only"
_IRST = timezone(timedelta(hours=3, minutes=30))

_loaded = False
_import_error: str | None = None


def ingestion_mode() -> str:
    return (os.environ.get("CDF_INGESTION_MODE", "") or "").strip().lower() or _LEGACY_ONLY


def dual_write_enabled() -> bool:
    return ingestion_mode() in ("dual_write", "canonical_only")


def sqlserver_mode() -> str:
    """active | fallback | offline_expected (default active)."""
    m = (os.environ.get("CDF_SQLSERVER_MODE", "") or "active").strip().lower()
    return m if m in ("active", "fallback", "offline_expected") else "active"


def sql_connection_required() -> bool:
    """Whether a legacy SQL Server connection must be established.

    Canonical-authority domains do not require SQL Server; when the operator has
    declared SQL Server offline, mirror/fallback must be treated as optional.
    """
    if sqlserver_mode() == "offline_expected":
        return False
    # Any domain still under legacy authority needs SQL Server.
    return not (market_canonical_authority() and monthly_canonical_authority()
                and financial_canonical_authority() and codal_canonical_authority())


def canonical_only_offline() -> bool:
    """True when canonical writes must proceed without any SQL Server connection."""
    return sqlserver_mode() == "offline_expected" and dual_write_enabled()


def mirror_status_for_sql() -> str:
    """Human/machine mirror status when SQL Server is not available."""
    return "offline_expected" if sqlserver_mode() == "offline_expected" else "unavailable"


def resolve_legacy_key(name: str | None = None, symbol: str | None = None,
                       ins_code: str | int | None = None) -> str | None:
    """Resolve a canonical legacy company key (32-hex) from PostgreSQL only.

    Used by canonical-only ingestion so SQL Server is not needed for identity.
    Returns None when the entity is not in the canonical universe.
    """
    if not _load():
        return None
    from canonical_ingest.db import connect
    try:
        with connect() as conn:
            cur = conn.cursor()
            params = []
            clauses = []
            if ins_code not in (None, ""):
                clauses.append("sec.tsetmc_ins_code = %s")
                params.append(int(ins_code))
            if symbol:
                clauses.append("(sec.codal_symbol = %s OR sec.brs_name = %s OR sa.alias_value = %s)")
                params.extend([symbol, symbol, symbol])
            if name:
                clauses.append("(c.display_name = %s OR c.legal_name = %s OR sa.alias_value = %s)")
                params.extend([name, name, name])
            if not clauses:
                return None
            sql = (
                "SELECT lem.legacy_key FROM core.legacy_entity_map lem "
                "JOIN core.companies c ON c.id = lem.target_uuid AND lem.entity_type='company' "
                "LEFT JOIN core.securities sec ON sec.company_id = c.id "
                "LEFT JOIN core.security_aliases sa ON sa.security_id = sec.id "
                "WHERE lem.legacy_key ~ '^[0-9a-f]{32}$' AND (" + " OR ".join(clauses) + ") LIMIT 1"
            )
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return str(row[0]) if row else None
    except Exception:
        return None


def resolve_legacy_keys_for_market(items: list[dict]) -> dict[int, str]:
    """Resolve a daily market batch in one read-only canonical query.

    This is equivalent to ``resolve_legacy_key`` for the BRS symbol/name
    predicates, while avoiding one database connection per instrument.
    Returned keys are indexed by the original input row position.
    """
    if not items or not _load():
        return {}
    from canonical_ingest.db import connect
    symbols = [str(x.get("l18") or "") for x in items]
    names = [str(x.get("l30") or "") for x in items]
    sql = """
        SELECT i.ord, (
          SELECT lem.legacy_key
          FROM core.legacy_entity_map lem
          JOIN core.companies c ON c.id = lem.target_uuid
            AND lem.entity_type = 'company'
          LEFT JOIN core.securities sec ON sec.company_id = c.id
          LEFT JOIN core.security_aliases sa ON sa.security_id = sec.id
          WHERE lem.legacy_key ~ '^[0-9a-f]{32}$'
            AND (
              sec.codal_symbol = i.symbol OR sec.brs_name = i.symbol
              OR sa.alias_value = i.symbol OR c.display_name = i.name
              OR c.legal_name = i.name OR sa.alias_value = i.name
            )
          LIMIT 1
        ) AS legacy_key
        FROM unnest(%s::text[], %s::text[])
          WITH ORDINALITY AS i(symbol, name, ord)
    """
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (symbols, names))
                return {int(pos) - 1: str(key) for pos, key in cur.fetchall() if key}
    except Exception:
        return {}


def facts_from_values(*, report_date: str | None = None, values: dict | None = None) -> list:
    """Build normalized in-memory financial facts from parsed values.

    ``values`` is keyed by metric_code (eps, operating_eps, capital,
    operating_profit, revenue, net_profit, finance_cost, other_non_operating,
    total_assets, current_assets, total_liabilities, current_liabilities,
    total_equity, operating_cash_flow). Money is rial; ps metrics are per-share.

    Comparative columns use suffixed keys: ``<metric>_last_year`` becomes
    period_order 2 (prior_year_same_period) and ``<metric>_fy_prev`` becomes
    period_order 3 (prior_fiscal_year). Only the statement metrics that carry
    comparatives in _FACT_MAP accept them (eps, operating_eps, operating_profit,
    revenue, net_profit). This is the single in-memory representation feeding
    the canonical writer and (optionally) the legacy mirror, so the two cannot
    diverge.
    """
    from decimal import Decimal
    values = values or {}
    ps_metrics = {"eps", "operating_eps"}
    monetary = {"revenue", "net_profit", "operating_profit", "finance_cost",
                "other_non_operating", "operating_cash_flow", "total_assets",
                "current_assets", "total_liabilities", "current_liabilities",
                "total_equity"}
    # Statement metrics with comparative columns in _FACT_MAP (capital is part
    # of the legacy map but facts_from_values has never emitted capital facts).
    COMPARATIVE_METRICS = {"eps", "operating_eps", "operating_profit", "revenue", "net_profit"}
    ORDER_SUFFIXES = {"_last_year": (2, "prior_year_same_period"),
                      "_fy_prev": (3, "prior_fiscal_year")}
    facts = []
    for code, val in values.items():
        if val is None:
            continue
        order, comparison, base = 1, "current", code
        for suffix, (suffix_order, suffix_comparison) in ORDER_SUFFIXES.items():
            if code.endswith(suffix) and code[: -len(suffix)] in COMPARATIVE_METRICS:
                base, order, comparison = code[: -len(suffix)], suffix_order, suffix_comparison
                break
        try:
            d = Decimal(str(val))
        except Exception:
            continue
        if order != 1 and float(d) == 0.0:
            # Codal renders an absent comparative cell as "-" and to_number maps
            # it to 0.0. A fabricated zero comparative would corrupt the
            # analytics TTM (cur + fy_prev - ly), so absent stays absent: the
            # fact is omitted and the TTM falls back to the report chain.
            continue
        if base in ps_metrics:
            facts.append({"statement_type": "income_statement", "metric_code": base, "period_order": order,
                          "comparison_type": comparison, "reported_value": d,
                          "reported_unit": "rial_per_share", "canonical_value": d,
                          "canonical_unit": "rial_per_share", "kind": "ps",
                          "source_row_key": f"income_statement:{base}:{order}"})
        elif base in monetary:
            # Parser values are in million_rial (legacy convention); canonical is rial.
            facts.append({"statement_type": "income_statement" if base in
                          ("revenue", "net_profit", "operating_profit", "finance_cost", "other_non_operating")
                          else "balance_sheet", "metric_code": base, "period_order": order,
                          "comparison_type": comparison, "reported_value": d,
                          "reported_unit": "million_rial",
                          "canonical_value": d * Decimal(1000000), "canonical_unit": "rial",
                          "kind": "m", "source_row_key": f"{'income_statement' if base in ('revenue','net_profit','operating_profit','finance_cost','other_non_operating') else 'balance_sheet'}:{base}:{order}"})
    return facts


def status_artifact(domain: str, outcome: str, canonical_status: str, mirror: str,
                    attempted: int = 0, inserted: int = 0, skipped: int = 0,
                    quarantined: int = 0) -> dict:
    """Uniform canonical status record including offline mirror semantics."""
    return {"domain": domain, "authority": "CANONICAL", "outcome": outcome,
            "canonical_status": canonical_status, "legacy_mirror_status": mirror,
            "rows_attempted": attempted, "canonical_inserted": inserted,
            "canonical_skipped": skipped, "quarantined": quarantined,
            "retry_backlog": retry_backlog_count({
                "MARKET_PRICE": "market_price", "MONTHLY_ACTIVITY": "monthly_activity",
                "FINANCIAL_STATEMENT": "financial_statement", "CODAL": "codal_report",
            }.get(domain, "market_price"))}


def market_authority() -> str:
    """MARKET_PRICE authority: 'legacy' (default) or 'canonical'."""
    return (os.environ.get("CDF_MARKET_INGESTION_AUTHORITY", "") or "legacy").strip().lower()


def market_canonical_authority() -> bool:
    return market_authority() in ("canonical", "canonical_primary", "primary")


def market_fallback_enabled() -> bool:
    raw = (os.environ.get("CDF_MARKET_FALLBACK_LEGACY", "") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def monthly_authority() -> str:
    """MONTHLY_ACTIVITY authority: 'legacy' (default) or 'canonical'."""
    return (os.environ.get("CDF_MONTHLY_INGESTION_AUTHORITY", "") or "legacy").strip().lower()


def monthly_canonical_authority() -> bool:
    return monthly_authority() in ("canonical", "canonical_primary", "primary")


def monthly_fallback_enabled() -> bool:
    raw = (os.environ.get("CDF_MONTHLY_FALLBACK_LEGACY", "") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def financial_authority() -> str:
    """FINANCIAL_STATEMENT authority: 'legacy' (default) or 'canonical'."""
    return (os.environ.get("CDF_FINANCIAL_INGESTION_AUTHORITY", "") or "legacy").strip().lower()


def financial_canonical_authority() -> bool:
    return financial_authority() in ("canonical", "canonical_primary", "primary")


def financial_fallback_enabled() -> bool:
    raw = (os.environ.get("CDF_FINANCIAL_FALLBACK_LEGACY", "") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def codal_authority() -> str:
    """CODAL authority: 'legacy' (default) or 'canonical'."""
    return (os.environ.get("CDF_CODAL_INGESTION_AUTHORITY", "") or "legacy").strip().lower()


def codal_canonical_authority() -> bool:
    return codal_authority() in ("canonical", "canonical_primary", "primary")


def codal_fallback_enabled() -> bool:
    raw = (os.environ.get("CDF_CODAL_FALLBACK_LEGACY", "") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def known_codal_report_ids(source_report_ids: list) -> set:
    """کدام TracingNoها از قبل با بدنه در canonical موجودند.

    فقط گزارشی «شناخته‌شده» است که حداقل یک نسخه با بدنهٔ واقعی
    (``raw.report_payloads.content_text``) داشته باشد. ردیف‌های metadata-only
    که مسیرهای soak/مایگریشن با ``fetch_body=False`` نوشته‌اند نباید dedup را
    قفل کنند؛ وگرنه گزارش برای همیشه «قبلاً دریافت‌شده» شمرده می‌شود ولی
    هیچ عددی از آن استخراج نمی‌شود. در هر خطا مجموعه‌ی خالی برمی‌گردد
    (رفتار fail-open مثل بقیه مرزهای isolation) — یعنی گزارش دوباره ingest
    می‌شود، نه اینکه از دست برود.
    """
    ids = [str(s).strip() for s in (source_report_ids or []) if str(s).strip()]
    if not ids or not _load():
        return set()
    try:
        canonical_ingest = _canonical["mod"]
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT r.source_report_id
                   FROM ingestion.reports r
                   WHERE r.source = 'codal'
                     AND r.source_report_id = ANY(%s)
                     AND EXISTS (
                       SELECT 1 FROM ingestion.report_versions v
                       JOIN raw.report_payloads rp ON rp.report_version_id = v.id
                       WHERE v.report_id = r.id AND rp.content_text IS NOT NULL
                     )""",
                (ids,),
            )
            return {str(row[0]) for row in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        try:
            print(json.dumps({"domain": "CODAL", "health": "DEDUP_LOOKUP_FAILED",
                              "error": str(exc)}, ensure_ascii=False))
        except Exception:
            pass
        return set()


def incomplete_codal_reports(*, days: int = 7, limit: int = 80,
                             letter_types: tuple[int, ...] = (6, 58),
                             symbol: str | None = None) -> list[dict]:
    """گزارش‌های کدال که ردیفشان ثبت شده ولی بدنه‌شان ذخیره نشده است.

    مسیرهای soak/مایگریشن با ``fetch_body=False`` فقط metadata نوشته‌اند.
    چنین ردیفی «دریافت‌شده» نیست و بدنه/اعدادش باید دوباره گرفته شود.
    خروجی برای ``sync_codal`` قابل استفاده است (TracingNo/Symbol/Url).
    """
    if not _load() or limit <= 0:
        return []
    allowed = tuple(int(x) for x in (letter_types or ()) if int(x) in (6, 58))
    if not allowed:
        return []
    letter_re = "|".join(str(x) for x in allowed)
    canonical_ingest = _canonical["mod"]
    try:
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT r.source_report_id, r.title, r.source_url, r.published_at,
                          COALESCE(sec.codal_symbol, c.display_name) AS symbol,
                          c.display_name
                   FROM ingestion.reports r
                   JOIN core.companies c ON c.id = r.company_id
                   LEFT JOIN LATERAL (
                       SELECT codal_symbol FROM core.securities
                       WHERE company_id = r.company_id
                         AND COALESCE(BTRIM(codal_symbol), '') <> ''
                       ORDER BY is_primary DESC, created_at ASC LIMIT 1
                   ) sec ON true
                   WHERE r.source = 'codal'
                     AND r.published_at >= now() - make_interval(days => %s)
                     AND r.source_url IS NOT NULL
                     AND r.source_url ~ ('[?&]let=(' || %s || ')(&|$)')
                     AND NOT (r.source_url ~ '[?&]let=6(&|$)'
                              AND r.title LIKE '%%حسابرسی شده%%')
                     AND NOT EXISTS (
                       SELECT 1 FROM ingestion.report_versions v
                       JOIN raw.report_payloads rp ON rp.report_version_id = v.id
                       WHERE v.report_id = r.id AND rp.content_text IS NOT NULL
                     )
                     AND (%s::text IS NULL OR sec.codal_symbol = %s)
                   ORDER BY r.published_at DESC NULLS LAST
                   LIMIT %s""",
                (int(days), letter_re, symbol, symbol, int(limit)),
            )
            out = []
            for row in cur.fetchall():
                published = row[3]
                out.append({
                    "report_id": str(row[0]),
                    "title": row[1],
                    "url": row[2],
                    "published_at": published.isoformat() if published is not None else None,
                    "symbol": row[4],
                    "company_name": row[5],
                })
            return out
    except Exception as exc:  # noqa: BLE001
        try:
            print(json.dumps({"domain": "CODAL", "health": "INCOMPLETE_LOOKUP_FAILED",
                              "error": str(exc)}, ensure_ascii=False))
        except Exception:
            pass
        return []


def codal_reports_missing_values(*, days: int = 7, hours: int = 6, limit: int = 80,
                                 letter_types: tuple[int, ...] = (6, 58),
                                 symbol: str | None = None) -> list[dict]:
    """گزارش‌هایی که بدنه دارند ولی اعدادشان هنوز استخراج نشده است.

    استخراج موفق یا unsupported با یک ``parse_run`` به نام ``codal_values``
    علامت می‌خورد؛ پس ترمیم بعدی دوباره سراغشان نمی‌رود. ``hours`` پنجرهٔ
    تازگیِ نسخهٔ بدنه است تا فقط بدنه‌هایی که همین اجرا/اجرای قبلی ذخیره شده‌اند
    (مثلاً پس از لغو نیمه‌کاره) دوباره استخراج شوند، نه کل تاریخچه.
    """
    if not _load() or limit <= 0:
        return []
    allowed = tuple(int(x) for x in (letter_types or ()) if int(x) in (6, 58))
    if not allowed:
        return []
    letter_re = "|".join(str(x) for x in allowed)
    canonical_ingest = _canonical["mod"]
    try:
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT r.source_report_id, r.title, r.source_url, r.published_at,
                          COALESCE(sec.codal_symbol, c.display_name) AS symbol,
                          c.display_name
                   FROM ingestion.reports r
                   JOIN core.companies c ON c.id = r.company_id
                   LEFT JOIN LATERAL (
                       SELECT codal_symbol FROM core.securities
                       WHERE company_id = r.company_id
                         AND COALESCE(BTRIM(codal_symbol), '') <> ''
                       ORDER BY is_primary DESC, created_at ASC LIMIT 1
                   ) sec ON true
                   WHERE r.source = 'codal'
                     AND r.published_at >= now() - make_interval(days => %s)
                     AND r.source_url IS NOT NULL
                     AND r.source_url ~ ('[?&]let=(' || %s || ')(&|$)')
                     AND NOT (r.source_url ~ '[?&]let=6(&|$)'
                              AND r.title LIKE '%%حسابرسی شده%%')
                     AND EXISTS (
                       SELECT 1 FROM ingestion.report_versions v
                       JOIN raw.report_payloads rp ON rp.report_version_id = v.id
                       WHERE v.report_id = r.id AND rp.content_text IS NOT NULL
                         AND v.created_at >= now() - make_interval(hours => %s)
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM ingestion.parse_runs p
                       JOIN ingestion.report_versions v ON v.id = p.report_version_id
                       WHERE v.report_id = r.id AND p.parser_name = 'codal_values'
                     )
                     AND (%s::text IS NULL OR sec.codal_symbol = %s)
                   ORDER BY r.published_at DESC NULLS LAST
                   LIMIT %s""",
                (int(days), letter_re, int(hours), symbol, symbol, int(limit)),
            )
            out = []
            for row in cur.fetchall():
                published = row[3]
                out.append({
                    "report_id": str(row[0]),
                    "title": row[1],
                    "url": row[2],
                    "published_at": published.isoformat() if published is not None else None,
                    "symbol": row[4],
                    "company_name": row[5],
                })
            return out
    except Exception as exc:  # noqa: BLE001
        try:
            print(json.dumps({"domain": "CODAL", "health": "MISSING_VALUES_LOOKUP_FAILED",
                              "error": str(exc)}, ensure_ascii=False))
        except Exception:
            pass
        return []


def mark_codal_values_extraction(report_id: str, *, status: str = "completed",
                                 report_date: str | None = None) -> bool:
    """ثبت اینکه اعداد یک گزارش کدال استخراج شد (یا قالبش پشتیبانی نمی‌شود)."""
    if not _load() or not str(report_id or "").strip():
        return False
    if status not in ("completed", "unsupported"):
        return False
    from psycopg.types.json import Jsonb

    canonical_ingest = _canonical["mod"]
    try:
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingestion.parse_runs
                     (report_version_id, parser_name, parser_version, status,
                      finished_at, parameters)
                   SELECT v.id, 'codal_values', 'v1', %s, now(), %s
                   FROM ingestion.report_versions v
                   JOIN raw.report_payloads rp
                     ON rp.report_version_id = v.id AND rp.content_text IS NOT NULL
                   WHERE v.report_id = (
                       SELECT id FROM ingestion.reports
                       WHERE source = 'codal' AND source_report_id = %s LIMIT 1)
                     AND NOT EXISTS (
                       SELECT 1 FROM ingestion.parse_runs p
                       WHERE p.report_version_id = v.id
                         AND p.parser_name = 'codal_values')
                   ORDER BY v.version_no DESC
                   LIMIT 1""",
                (status, Jsonb({"report_date": report_date}), str(report_id)),
            )
        return True
    except Exception:  # noqa: BLE001
        return False


def codal_covered_symbols() -> set[str]:
    """نمادهای کدالِ تحت پوشش canonical (core.securities.codal_symbol).

    برای اینکه اسکن feed فقط گزارش‌های شرکت‌های تحت پوشش را «مرتبط» بداند و
    گزارش نمادهای بیرون از پوشش، اسکن را تا عمق‌های قدیمی‌تر هل ندهد.
    """
    if not _load():
        return set()
    canonical_ingest = _canonical["mod"]
    try:
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT BTRIM(codal_symbol) FROM core.securities "
                "WHERE COALESCE(BTRIM(codal_symbol), '') <> ''"
            )
            return {str(row[0]).strip() for row in cur.fetchall() if row and row[0]}
    except Exception:  # noqa: BLE001
        return set()


def seen_codal_report_ids(source_report_ids: list) -> set:
    """TracingNoهایی که قبلاً دیده شده‌اند: بدنه‌دار یا قرنطینه‌شده.

    برای تصمیم «آیا این صفحه گزارش تازه‌ای برای پوشش ما دارد؟» استفاده
    می‌شود. گزارش‌های بیرون از پوشش که یک‌بار قرنطینه شده‌اند نباید هر اجرا
    دوباره اسکن عمیق را فعال کنند.
    """
    ids = [str(s).strip() for s in (source_report_ids or []) if str(s).strip()]
    if not ids or not _load():
        return set()
    seen = known_codal_report_ids(ids)
    canonical_ingest = _canonical["mod"]
    try:
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT details->>'source_report_id'
                   FROM ingestion.data_quality_issues
                   WHERE issue_code = 'identity_conflict'
                     AND details->>'source_report_id' = ANY(%s)""",
                (ids,),
            )
            seen.update(str(row[0]) for row in cur.fetchall() if row and row[0])
    except Exception:  # noqa: BLE001
        pass
    return seen


def get_codal_watermark(letter_type: int):
    """آخرین sync موفق هر feed کدال (معادل legacy CodalSyncState، در پستگرس)."""
    if not _load():
        return None
    try:
        canonical_ingest = _canonical["mod"]
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS ingestion.codal_sync_state (
                       letter_type INT PRIMARY KEY,
                       last_successful_sync TIMESTAMPTZ NOT NULL,
                       updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            cur.execute(
                "SELECT last_successful_sync FROM ingestion.codal_sync_state WHERE letter_type = %s",
                (int(letter_type),),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        try:
            print(json.dumps({"domain": "CODAL", "health": "WATERMARK_READ_FAILED",
                              "error": str(exc)}, ensure_ascii=False))
        except Exception:
            pass
        return None


def resolve_codal_company_display_name(name=None, symbol=None) -> str | None:
    """نام نمایشی canonical برای پاس دادن به پارس‌کننده‌ها (MianSql/MianSql2).

    نامه‌ی کدال نام رسمی طولانی می‌آورد که اغلب با alias ها یکی نیست؛ پارس‌کننده
    برای resolve_legacy_key به نامی نیاز دارد که در canonical موجود باشد.
    """
    if not _load():
        return None
    try:
        from canonical_ingest.identity import resolve_company as _resolve_company
        canonical_ingest = _canonical["mod"]
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cid = _resolve_company(
                cur, legacy_company_id=None, ins_code=None,
                name=(name or "").strip() or None,
                symbol=(symbol or "").strip() or None,
            )
            if not cid:
                return None
            cur.execute("SELECT display_name FROM core.companies WHERE id=%s", (cid,))
            row = cur.fetchone()
            return str(row[0]) if row and row[0] else None
    except Exception:  # noqa: BLE001
        return None


def set_codal_watermark(letter_type: int, when) -> bool:
    if not _load() or when is None:
        return False
    try:
        canonical_ingest = _canonical["mod"]
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS ingestion.codal_sync_state (
                       letter_type INT PRIMARY KEY,
                       last_successful_sync TIMESTAMPTZ NOT NULL,
                       updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            cur.execute(
                """INSERT INTO ingestion.codal_sync_state (letter_type, last_successful_sync, updated_at)
                   VALUES (%s, %s, now())
                   ON CONFLICT (letter_type) DO UPDATE
                   SET last_successful_sync = EXCLUDED.last_successful_sync,
                       updated_at = now()""",
                (int(letter_type), when),
            )
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            print(json.dumps({"domain": "CODAL", "health": "WATERMARK_WRITE_FAILED",
                              "error": str(exc)}, ensure_ascii=False))
        except Exception:
            pass
        return False


def retry_backlog_count(domain: str | None = None) -> int:
    try:
        path = _OUT_DIR / "canonical_retry_manifest.jsonl"
        if not path.exists():
            return 0
        latest: dict = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except Exception:
                continue
            key = (entry.get("domain"), json.dumps(entry.get("keys"), sort_keys=True, ensure_ascii=False))
            latest[key] = entry.get("status")
        return sum(1 for (d, _k), status in latest.items()
                   if status == "pending" and (domain is None or d == domain))
    except Exception:
        return 0


def _load():
    """Lazily import the canonical package only when dual-write is enabled."""
    global _loaded, _import_error
    if _loaded:
        return True
    if _PY2_SRC.exists() and str(_PY2_SRC) not in sys.path:
        sys.path.insert(0, str(_PY2_SRC))
    try:
        import canonical_ingest  # type: ignore
        _canonical["mod"] = canonical_ingest
        _loaded = True
        return True
    except Exception as exc:  # noqa: BLE001
        _import_error = f"{type(exc).__name__}: {exc}"
        return False


_canonical: dict = {}


def _now_iso() -> str:
    return datetime.now(_IRST).isoformat()


def _gregorian(jalali: str | None) -> str | None:
    if not jalali:
        return None
    try:
        import jdatetime
        y, m, d = (int(x) for x in str(jalali).replace("-", "/").split("/"))
        return jdatetime.date(y, m, d).togregorian().isoformat()
    except Exception:
        return None


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _publish_datetime_iso(raw) -> str | None:
    """PublishDateTime کدال → ISO گرگوری برای ستون timestamptz.

    ورودی کدال شمسی با ارقام فارسی است، مثل «۱۴۰۵/۰۷/۰۴ ۱۵:۵۹:۲۴». بدون این
    تبدیل، insert با «invalid input syntax for type timestamp» شکست می‌خورد.
    سال بزرگ‌تر از ۱۵۰۰ یعنی ورودی از قبل گرگوری است و دست‌نخورده می‌رود.
    """
    if raw in (None, ""):
        return None
    text = str(raw).strip().translate(_PERSIAN_DIGITS)
    if not text:
        return None
    try:
        date_part, _, time_part = text.partition(" ")
        y, m, d = (int(x) for x in date_part.split("/")[:3])
        if y > 1500:
            return text
        hour = minute = second = 0
        if time_part:
            bits = [int(x) for x in time_part.split(":") if x != ""]
            hour = bits[0] if len(bits) > 0 else 0
            minute = bits[1] if len(bits) > 1 else 0
            second = bits[2] if len(bits) > 2 else 0
        import jdatetime
        g = jdatetime.date(y, m, d).togregorian()
        return f"{g.isoformat()}T{hour:02d}:{minute:02d}:{second:02d}+03:30"
    except Exception:
        return text


def _sqlserver_conn():
    import pyodbc
    server = os.environ["DB_SERVER"]
    db = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    pwd = os.environ["DB_PASSWORD"]
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={db};"
          f"UID={user};PWD={pwd};TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


# --------------------------------------------------------------------------
# batch status artifact
# --------------------------------------------------------------------------
_BATCH_FIELDS = [
    "domain", "script", "batch_id", "source", "legacy_result", "canonical_result",
    "rows_attempted", "rows_inserted", "rows_skipped", "rows_quarantined",
    "recon_exact", "recon_expected_conversion", "recon_other_expected",
    "recon_mismatch", "canonical_errors", "started_at", "finished_at",
]


def _record(**kw):
    try:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / "phase2_real_batches.csv"
        row = {k: kw.get(k, "") for k in _BATCH_FIELDS}
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_BATCH_FIELDS)
            if not exists:
                w.writeheader()
            w.writerow(row)
    except Exception:
        pass


def _retry_record(domain, keys, error):
    """Append a deterministic retry entry for a canonical-side failure."""
    try:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"status": "pending", "domain": domain, "keys": keys, "error": str(error)[:400],
                 "detected_at": _now_iso()}
        with (_OUT_DIR / "canonical_retry_manifest.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _log_summary(domain, legacy_result, canonical_result, inserted, skipped, quarantined, mismatches):
    try:
        print(json.dumps({
            "ingestion_hook": domain,
            "legacy": legacy_result,
            "canonical": canonical_result,
            "inserted": inserted,
            "skipped": skipped,
            "quarantined": quarantined,
            "reconciliation_mismatches": mismatches,
        }, ensure_ascii=False))
    except Exception:
        pass


# --------------------------------------------------------------------------
# MARKET PRICE
# --------------------------------------------------------------------------
_MARKET_MAP = [
    ("first_price_rial", "first_price"),
    ("high_price_rial", "high_price"),
    ("low_price_rial", "low_price"),
    ("closing_price_rial", "closing_price"),
    ("last_price_rial", "last_price"),
    ("yesterday_price_rial", "yesterday_price"),
    ("closing_change_rial", "closing_change"),
    ("closing_change_percent", "closing_change_percent"),
    ("last_change_rial", "last_change"),
    ("last_change_percent", "last_change_percent"),
    ("volume", "volume"),
    ("trade_value_rial", "trade_value"),
    ("trade_count", "trade_count"),
]


def _canonical_market_write(rows, source: str, table_name: str):
    """Canonical-only market write (no legacy). Returns status dict."""
    if not _load():
        return {"status": "canonical_error", "error": _import_error,
                "attempted": 0, "inserted": 0, "skipped": 0, "quarantined": 0, "errors": 1}
    canonical_ingest = _canonical["mod"]
    by_company: dict[str, list] = {}
    for r in rows:
        cid = r.get("company_id")
        if cid and r.get("gregorian_date"):
            by_company.setdefault(cid, []).append(r)
    attempted = inserted = skipped = quarantined = errors = 0
    for cid, group in by_company.items():
        observations = []
        for r in group:
            obs = {
                "trade_date": r["gregorian_date"], "jalali_date_text": r.get("jalali_date"),
                "price_series": "adjusted", "is_adjusted": True, "collected_at": _now_iso(),
                "provenance": {"legacy_table": table_name, "script": "brs_prices"},
            }
            for tgt, src in _MARKET_MAP:
                obs[tgt] = r.get(src)
            observations.append(obs)
        if not observations:
            continue
        attempted += len(observations)
        try:
            res = canonical_ingest.dual_write_market(
                legacy_company_id=str(cid), symbol=group[0].get("symbol"), observations=observations)
            inserted += res.inserted
            skipped += res.skipped
            if res.status == "quarantined":
                quarantined += len(observations)
            elif res.status == "canonical_error":
                errors += 1
        except Exception:
            errors += 1
    return {"status": "success" if errors == 0 else "canonical_error",
            "attempted": attempted, "inserted": inserted, "skipped": skipped,
            "quarantined": quarantined, "errors": errors}


def dual_write_market_rows(rows, source: str = "brs", table_name: str = "MarketPriceHistory"):
    """Legacy-authoritative path: canonical write is secondary (after legacy)."""
    if not dual_write_enabled() or not rows:
        return {"status": "skipped_legacy_only" if not dual_write_enabled() else "empty"}
    started = _now_iso()
    started_ts = time.time()
    res = _canonical_market_write(rows, source, table_name)
    if res["errors"]:
        _retry_record("market_price", {"companies": sorted({r.get("company_id") for r in rows if r.get("company_id")})},
                      res.get("error", "canonical_error"))
    _record(domain="market_price", script="brs_prices", source=source,
            legacy_result="success", canonical_result="success" if res["errors"] == 0 else "failed",
            rows_attempted=res["attempted"], rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=res["quarantined"], recon_exact=res["inserted"] + res["skipped"],
            recon_mismatch=0, canonical_errors=res["errors"],
            started_at=started, finished_at=_now_iso(), batch_id=f"market-{int(started_ts)}")
    _log_summary("market_price", "success", "success" if res["errors"] == 0 else "failed",
                 res["inserted"], res["skipped"], res["quarantined"], 0)
    return res


def ingest_market_authoritative(rows, legacy_writer=None, table_name: str = "MarketPriceHistory",
                                source: str = "brs"):
    """Canonical-authoritative market ingestion.

    1. canonical PostgreSQL transaction is authoritative;
    2. on success, mirror to SQL Server (mirror failure does not invalidate);
    3. on canonical failure, optionally write legacy for continuity (fallback),
       mark DEGRADED, and queue a canonical retry.
    Never raises. Returns an explicit outcome dict.
    """
    if not market_canonical_authority():
        # Authority is legacy: preserve legacy-first + secondary canonical.
        if legacy_writer:
            legacy_writer()
        res = dual_write_market_rows(rows, source=source, table_name=table_name)
        res["outcome"] = "LEGACY_AUTHORITATIVE"
        res["authority"] = "LEGACY"
        return res

    started = _now_iso()
    latest_source = max((r.get("gregorian_date") or "" for r in rows), default="")
    res = _canonical_market_write(rows, source, table_name)
    canonical_ok = res["errors"] == 0 and res["status"] == "success"

    mirror_status = "not_attempted"
    outcome = "CANONICAL_FAILED"
    if canonical_ok and legacy_writer is not None:
        try:
            legacy_writer()
            mirror_status = "success"
            outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"
        except Exception as exc:  # noqa: BLE001
            mirror_status = f"failed: {type(exc).__name__}"
            outcome = "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED"
    elif canonical_ok:
        outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"

    if not canonical_ok:
        _retry_record("market_price", {"companies": sorted({r.get("company_id") for r in rows if r.get("company_id")})},
                      res.get("error", "canonical_error"))
        if legacy_writer is not None and market_fallback_enabled():
            try:
                legacy_writer()
                mirror_status = "fallback_success"
                outcome = "CANONICAL_FAILED_LEGACY_FALLBACK_USED"
            except Exception as exc:  # noqa: BLE001
                mirror_status = f"fallback_failed: {type(exc).__name__}"
                outcome = "CANONICAL_FAILED"
        else:
            outcome = "CANONICAL_FAILED"

    authority = "CANONICAL"
    canonical_status = "success" if canonical_ok else "failed"
    health = ("HEALTHY" if canonical_ok and mirror_status == "success"
              else "DEGRADED_LEGACY_MIRROR" if canonical_ok
              else "CANONICAL_ERROR" if not res["errors"]
              else "CANONICAL_ERROR")
    _record(domain="market_price", script="brs_prices", source=source,
            legacy_result="success" if mirror_status in ("success", "fallback_success") else mirror_status,
            canonical_result=canonical_status,
            rows_attempted=res["attempted"], rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=res["quarantined"], recon_exact=res["inserted"] + res["skipped"],
            recon_mismatch=0 if canonical_ok else 1, canonical_errors=res["errors"],
            started_at=started, finished_at=_now_iso(),
            batch_id=f"market-auth-{int(time.time())}")
    summary = {
        "domain": "MARKET_PRICE", "authority": authority, "outcome": outcome,
        "canonical_status": canonical_status, "canonical_inserted": res["inserted"],
        "canonical_skipped": res["skipped"], "legacy_mirror_status": mirror_status,
        "reconciliation_status": "exact" if canonical_ok else "canonical_failed",
        "retry_backlog": retry_backlog_count("market_price"), "latest_source_time": latest_source,
        "health": health,
    }
    try:
        print(json.dumps(summary, ensure_ascii=False))
    except Exception:
        pass
    res.update({"outcome": outcome, "authority": authority, "legacy_mirror_status": mirror_status,
                "health": health, "retry_backlog": summary["retry_backlog"]})
    return res


# --------------------------------------------------------------------------
# MONTHLY ACTIVITY
# --------------------------------------------------------------------------
def _canonical_monthly_write(company_id, company_name, report_date, monthly_values):
    """Canonical-only monthly write. Returns a result-like dict."""
    if not _load():
        return {"status": "canonical_error", "error": _import_error, "inserted": 0, "skipped": 0}
    canonical_ingest = _canonical["mod"]
    try:
        values = list(monthly_values or [])
        v1 = values[0] if len(values) > 0 else None
        v2 = values[1] if len(values) > 1 else None
        v3 = values[2] if len(values) > 2 else None
        from decimal import Decimal
        amount = Decimal(str(v3)) * Decimal(1000000) if v3 is not None else None
        res = canonical_ingest.dual_write_monthly(
            legacy_company_id=str(company_id), period_end_date=_gregorian(report_date),
            jalali_period_text=report_date, production_quantity=v1, sales_quantity=v2,
            reported_sales_amount=v3, sales_amount_rial=amount,
            reported_currency_unit="million_rial", reported_unit_multiplier=1000000)
        return {"status": res.status, "inserted": res.inserted, "skipped": res.skipped,
                "error": getattr(res, "error", "")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "canonical_error", "inserted": 0, "skipped": 0, "error": str(exc)}


def dual_write_monthly_values(company_id, company_name, report_date, monthly_values):
    """Legacy-authoritative path: canonical write is secondary."""
    if not dual_write_enabled():
        return {"status": "skipped_legacy_only"}
    started = _now_iso()
    res = _canonical_monthly_write(company_id, company_name, report_date, monthly_values)
    if res["status"] == "canonical_error":
        _retry_record("monthly_activity", {"legacy_company_id": company_id, "report_date": report_date},
                      res.get("error", "canonical_error"))
    mismatch = 0 if res["status"] in ("written", "quarantined") else 1
    _record(domain="monthly_activity", script="MianSql2", source="codal",
            legacy_result="success", canonical_result="success" if res["status"] == "written" else res["status"],
            rows_attempted=1, rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=1 if res["status"] == "quarantined" else 0,
            recon_expected_conversion=1 if res["status"] == "written" else 0,
            recon_mismatch=mismatch, canonical_errors=0 if res["status"] == "written" else 1,
            started_at=started, finished_at=_now_iso(), batch_id=f"monthly-{company_id}-{report_date}")
    _log_summary("monthly_activity", "success", res["status"], res["inserted"], res["skipped"],
                 1 if res["status"] == "quarantined" else 0, mismatch)
    return {"status": res["status"], "inserted": res["inserted"], "skipped": res["skipped"]}


def ingest_monthly_authoritative(company_id, company_name, report_date, monthly_values, legacy_writer=None):
    """Canonical-authoritative monthly ingestion (canonical first, legacy mirror)."""
    if not monthly_canonical_authority():
        if legacy_writer:
            legacy_writer()
        res = dual_write_monthly_values(company_id, company_name, report_date, monthly_values)
        res["outcome"] = "LEGACY_AUTHORITATIVE"
        res["authority"] = "LEGACY"
        return res

    started = _now_iso()
    res = _canonical_monthly_write(company_id, company_name, report_date, monthly_values)
    canonical_ok = res["status"] in ("written", "quarantined") and res["status"] != "canonical_error"

    mirror_status = "not_attempted"
    outcome = "CANONICAL_FAILED"
    if canonical_ok and legacy_writer is not None:
        try:
            legacy_writer(); mirror_status = "success"
            outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"
        except Exception as exc:  # noqa: BLE001
            mirror_status = f"failed: {type(exc).__name__}"
            outcome = "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED"
    elif canonical_ok:
        outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"

    if not canonical_ok:
        _retry_record("monthly_activity", {"legacy_company_id": company_id, "report_date": report_date},
                      res.get("error", "canonical_error"))
        if legacy_writer is not None and monthly_fallback_enabled():
            try:
                legacy_writer(); mirror_status = "fallback_success"
                outcome = "CANONICAL_FAILED_LEGACY_FALLBACK_USED"
            except Exception as exc:  # noqa: BLE001
                mirror_status = f"fallback_failed: {type(exc).__name__}"
                outcome = "CANONICAL_FAILED"

    if res["status"] == "quarantined":
        health = "IDENTITY_QUARANTINE"
    elif canonical_ok and mirror_status == "success":
        health = "HEALTHY"
    elif canonical_ok:
        health = "DEGRADED_LEGACY_MIRROR"
    else:
        health = "CANONICAL_ERROR"
    _record(domain="monthly_activity", script="MianSql2", source="codal",
            legacy_result="success" if mirror_status in ("success", "fallback_success") else mirror_status,
            canonical_result="success" if canonical_ok else res["status"],
            rows_attempted=1, rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=1 if res["status"] == "quarantined" else 0,
            recon_expected_conversion=1 if canonical_ok else 0,
            recon_mismatch=0 if canonical_ok else 1, canonical_errors=0 if canonical_ok else 1,
            started_at=started, finished_at=_now_iso(), batch_id=f"monthly-auth-{company_id}-{report_date}")
    summary = {
        "domain": "MONTHLY_ACTIVITY", "authority": "CANONICAL", "outcome": outcome,
        "canonical_status": res["status"], "canonical_inserted": res["inserted"],
        "canonical_skipped": res["skipped"], "legacy_mirror_status": mirror_status,
        "reconciliation_status": "exact" if canonical_ok else "canonical_failed",
        "retry_backlog": retry_backlog_count("monthly_activity"), "health": health,
    }
    try:
        print(json.dumps(summary, ensure_ascii=False))
    except Exception:
        pass
    res.update({"outcome": outcome, "authority": "CANONICAL", "legacy_mirror_status": mirror_status,
                "health": health, "retry_backlog": summary["retry_backlog"]})
    return res


# --------------------------------------------------------------------------
# FINANCIAL STATEMENT
# --------------------------------------------------------------------------
_FACT_MAP = [
    ("income_statement", "eps", 1, "Num1_Value1", "ps", "current"),
    ("income_statement", "operating_eps", 1, "Num4_Value1", "ps", "current"),
    ("income_statement", "capital", 1, "Num2_Value1", "m", "current"),
    ("income_statement", "operating_profit", 1, "OperatingProfitNew", "m", "current"),
    ("income_statement", "finance_cost", 1, "FinanceCostsNew", "m", "current"),
    ("income_statement", "other_non_operating", 1, "OtherNonOpNew", "m", "current"),
    ("income_statement", "revenue", 1, "RevenueNew", "m", "current"),
    ("income_statement", "net_profit", 1, "NetProfitAmount", "m", "current"),
    ("income_statement", "eps", 2, "Num1_Value2", "ps", "prior_year_same_period"),
    ("income_statement", "operating_eps", 2, "Num4_Value2", "ps", "prior_year_same_period"),
    ("income_statement", "capital", 2, "Num2_Value2", "m", "prior_year_same_period"),
    ("income_statement", "operating_profit", 2, "OperatingProfitLastYear", "m", "prior_year_same_period"),
    ("income_statement", "revenue", 2, "RevenueLastYear", "m", "prior_year_same_period"),
    ("income_statement", "net_profit", 2, "NetProfitAmountLY", "m", "prior_year_same_period"),
    ("income_statement", "eps", 3, "Num1_Value3", "ps", "prior_fiscal_year"),
    ("income_statement", "capital", 3, "Num2_Value3", "m", "prior_fiscal_year"),
    ("income_statement", "operating_profit", 3, "OperatingProfitFYPrev", "m", "prior_fiscal_year"),
    ("income_statement", "revenue", 3, "RevenueFYPrev", "m", "prior_fiscal_year"),
    ("income_statement", "net_profit", 3, "NetProfitAmountFYPrev", "m", "prior_fiscal_year"),
    ("balance_sheet", "total_assets", 1, "TotalAssets", "m", "current"),
    ("balance_sheet", "current_assets", 1, "CurrentAssets", "m", "current"),
    ("balance_sheet", "total_liabilities", 1, "TotalLiabilities", "m", "current"),
    ("balance_sheet", "current_liabilities", 1, "CurrentLiabilities", "m", "current"),
    ("balance_sheet", "total_equity", 1, "TotalEquity", "m", "current"),
    ("cash_flow", "operating_cash_flow", 1, "OperatingCashFlow", "m", "current"),
]


def _facts_from_db(company_id, report_date):
    from decimal import Decimal
    conn = _sqlserver_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM dbo.miandore2 WHERE CompanyID=? AND ReportDate=?", (company_id, report_date))
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    data = dict(zip(cols, row))
    facts = []
    for stype, mcode, order, col, kind, comp in _FACT_MAP:
        if col not in data or data[col] is None:
            continue
        reported = Decimal(str(data[col]))
        facts.append({
            "statement_type": stype, "metric_code": mcode, "period_order": order,
            "comparison_type": comp, "reported_value": reported,
            "reported_unit": "rial_per_share" if kind == "ps" else "million_rial",
            "canonical_value": reported if kind == "ps" else reported * Decimal(1000000),
            "canonical_unit": "rial_per_share" if kind == "ps" else "rial",
            "kind": kind, "source_row_key": f"{stype}:{mcode}:{order}",
        })
    # Guard: Product1/2/3 / NPUnitRatio / OpK / OpAmt must never become facts.
    assert not any(f["metric_code"].lower().startswith(("product", "npunit", "opk", "opamt")) for f in facts)
    return facts


def _canonical_financial_write(company_id, report_date, facts=None):
    if not _load():
        return {"status": "canonical_error", "error": _import_error, "inserted": 0, "skipped": 0, "facts": 0}
    canonical_ingest = _canonical["mod"]
    try:
        # SQL Server is NOT the transport for canonical facts: when the parser
        # supplies normalized in-memory facts, they are written directly. The
        # legacy miandore2 read is only a backward-compatible fallback.
        if facts is None:
            facts = _facts_from_db(company_id, report_date)
        if facts is None:
            return {"status": "no_legacy_row", "inserted": 0, "skipped": 0, "facts": 0}
        if not facts:
            return {"status": "no_facts", "inserted": 0, "skipped": 0, "facts": 0}
        res = canonical_ingest.dual_write_financial(
            legacy_company_id=str(company_id), period_end_date=_gregorian(report_date),
            jalali_period_text=report_date, facts=facts)
        return {"status": res.status, "inserted": res.inserted, "skipped": res.skipped, "facts": len(facts),
                "error": getattr(res, "error", ""), "ids": getattr(res, "ids", {})}
    except Exception as exc:  # noqa: BLE001
        return {"status": "canonical_error", "inserted": 0, "skipped": 0, "facts": 0, "error": str(exc)}


def dual_write_financial_by_key(company_id, company_name, report_date, facts=None):
    """Legacy-authoritative path: canonical facts write is secondary."""
    if not dual_write_enabled():
        return {"status": "skipped_legacy_only"}
    started = _now_iso()
    res = _canonical_financial_write(company_id, report_date, facts=facts)
    if res["status"] == "canonical_error":
        _retry_record("financial_statement", {"legacy_company_id": company_id, "report_date": report_date},
                      res.get("error", "canonical_error"))
    mismatch = 0 if res["status"] in ("written", "quarantined") else 1
    _record(domain="financial_statement", script="MianSql", source="codal",
            legacy_result="success", canonical_result="success" if res["status"] == "written" else res["status"],
            rows_attempted=res["facts"], rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=1 if res["status"] == "quarantined" else 0,
            recon_expected_conversion=res["facts"] if res["status"] == "written" else 0,
            recon_mismatch=mismatch, canonical_errors=0 if res["status"] == "written" else 1,
            started_at=started, finished_at=_now_iso(), batch_id=f"financial-{company_id}-{report_date}")
    _log_summary("financial_statement", "success", res["status"], res["inserted"], res["skipped"],
                 1 if res["status"] == "quarantined" else 0, mismatch)
    return {"status": res["status"], "inserted": res["inserted"], "skipped": res["skipped"], "facts": res["facts"]}


def ingest_financial_authoritative_by_key(company_id, company_name, report_date, legacy_writer=None, facts=None):
    """Canonical-authoritative financial ingestion (canonical first, legacy mirror).

    Pass ``facts`` (normalized in-memory parser output) to decouple canonical
    ingestion from SQL Server entirely. When ``facts`` is None the legacy
    miandore2 read is used as a backward-compatible fallback only.
    """
    if not financial_canonical_authority():
        if legacy_writer:
            legacy_writer()
        res = dual_write_financial_by_key(company_id, company_name, report_date, facts=facts)
        res["outcome"] = "LEGACY_AUTHORITATIVE"
        res["authority"] = "LEGACY"
        return res

    started = _now_iso()
    res = _canonical_financial_write(company_id, report_date, facts=facts)
    canonical_ok = res["status"] in ("written", "quarantined") and res["status"] != "canonical_error"

    mirror_status = "not_attempted"
    outcome = "CANONICAL_FAILED"
    if canonical_ok and legacy_writer is not None:
        try:
            legacy_writer(); mirror_status = "success"
            outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"
        except Exception as exc:  # noqa: BLE001
            mirror_status = f"failed: {type(exc).__name__}"
            outcome = "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED"
    elif canonical_ok:
        outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"

    if not canonical_ok:
        _retry_record("financial_statement", {"legacy_company_id": company_id, "report_date": report_date},
                      res.get("error", "canonical_error"))
        if legacy_writer is not None and financial_fallback_enabled():
            try:
                legacy_writer(); mirror_status = "fallback_success"
                outcome = "CANONICAL_FAILED_LEGACY_FALLBACK_USED"
            except Exception as exc:  # noqa: BLE001
                mirror_status = f"fallback_failed: {type(exc).__name__}"
                outcome = "CANONICAL_FAILED"

    if res["status"] == "quarantined":
        health = "IDENTITY_QUARANTINE"
    elif canonical_ok and mirror_status == "success":
        health = "HEALTHY"
    elif canonical_ok:
        health = "DEGRADED_LEGACY_MIRROR"
    else:
        health = "CANONICAL_ERROR"
    _record(domain="financial_statement", script="MianSql", source="codal",
            legacy_result="success" if mirror_status in ("success", "fallback_success") else mirror_status,
            canonical_result="success" if canonical_ok else res["status"],
            rows_attempted=res["facts"], rows_inserted=res["inserted"], rows_skipped=res["skipped"],
            rows_quarantined=1 if res["status"] == "quarantined" else 0,
            recon_expected_conversion=res["facts"] if canonical_ok else 0,
            recon_mismatch=0 if canonical_ok else 1, canonical_errors=0 if canonical_ok else 1,
            started_at=started, finished_at=_now_iso(), batch_id=f"financial-auth-{company_id}-{report_date}")
    summary = {
        "domain": "FINANCIAL_STATEMENT", "authority": "CANONICAL", "outcome": outcome,
        "canonical_status": res["status"], "canonical_inserted": res["inserted"],
        "canonical_skipped": res["skipped"], "facts": res["facts"],
        "legacy_mirror_status": mirror_status,
        "reconciliation_status": "exact" if canonical_ok else "canonical_failed",
        "retry_backlog": retry_backlog_count("financial_statement"), "health": health,
    }
    try:
        print(json.dumps(summary, ensure_ascii=False))
    except Exception:
        pass
    res.update({"outcome": outcome, "authority": "CANONICAL", "legacy_mirror_status": mirror_status,
                "health": health, "retry_backlog": summary["retry_backlog"]})
    return res


# --------------------------------------------------------------------------
# CODAL REPORT (live lineage + raw capture)
# --------------------------------------------------------------------------
def _absolute_codal_url(url: str | None) -> str | None:
    """Codal's feed returns site-relative report urls; urllib needs absolute ones.

    Without this, urllib raises ``ValueError: unknown url type: '/Reports/...'``
    for every *new* report, which is exactly the "new report fails instantly"
    symptom while already-collected reports keep working.
    """
    if url is None:
        return None
    value = str(url).strip()
    if not value:
        return None
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return "https://www.codal.ir" + value
    if "://" not in value:
        return "https://www.codal.ir/" + value.lstrip("/")
    return value


def _fetch_text(url: str, max_bytes: int = 512000) -> str | None:
    try:
        if __import__("os").environ.get("CODAL_JOB_DIR"):
            from codal_transport import current
            raw, content_type, _status = current().get(url, 25)
            raw = raw[:max_bytes]
            prefix = raw[:32000].lower()
            if content_type in ("text/html", "application/xhtml+xml") and any(
                token in prefix for token in (b"captcha", "کد امنیتی".encode(), "کد تصویری".encode(), b"security code")
            ):
                raise RuntimeError("Codal challenge page was not accepted as report content")
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read(max_bytes)
        for enc in ("utf-8", "windows-1256"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", "replace")
    except (InterruptedError, TimeoutError):
        raise
    except Exception as exc:
        try:
            from codal_challenge import CodalChallengeError
            if isinstance(exc, CodalChallengeError):
                raise
        except ImportError:
            pass
        if __import__("os").environ.get("CODAL_JOB_DIR"):
            log.warning("Codal report body fetch failed for %s", url, exc_info=True)
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
        return None


def _canonical_codal_write(letter: dict, fetch_body: bool = True, supersedes_source_report_id: str | None = None):
    if not _load():
        return {"status": "canonical_error", "error": _import_error, "inserted": 0, "skipped": 0}
    canonical_ingest = _canonical["mod"]
    tracing = str(letter.get("TracingNo") or "").strip()
    if not tracing:
        return {"status": "no_tracing_no", "inserted": 0, "skipped": 0}
    name = letter.get("CompanyName")
    symbol = letter.get("Symbol")

    # شناسایی سبک (فقط نام/نماد، بدون دانلود بدنه) — نامه‌ی شرکت ناشناس را
    # همان جا قرنطینه کن؛ در فصل‌های خلوت کدال این ~۹۰٪ ترافیک دانلود را حذف می‌کند.
    pre_company_id = None
    try:
        from canonical_ingest.identity import resolve_company as _resolve_company
        with canonical_ingest.transaction() as conn, conn.cursor() as cur:
            pre_company_id = _resolve_company(
                cur,
                legacy_company_id=None,
                ins_code=None,
                name=(name or "").strip() or None,
                symbol=(symbol or "").strip() or None,
            )
    except Exception:  # noqa: BLE001 - در خطا مسیر عادی ادامه می‌دهد
        pre_company_id = None

    if pre_company_id is None:
        try:
            with canonical_ingest.transaction() as conn:
                # هر گزارش فقط یک‌بار قرنطینه می‌شود؛ بدون این گارد، هر اجرای
                # sync همان گزارش را دوباره در data_quality_issues می‌نویسد.
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM ingestion.data_quality_issues "
                        "WHERE issue_code = 'identity_conflict' "
                        "AND details->>'source_report_id' = %s LIMIT 1",
                        (tracing,),
                    )
                    already_quarantined = cur.fetchone() is not None
                if not already_quarantined:
                    canonical_ingest.CanonicalWriter(conn).quarantine(
                        entity_type="company",
                        issue_code="identity_conflict",
                        severity="high",
                        details={"domain": "codal_report", "source_report_id": tracing,
                                 "name": name, "symbol": symbol, "stage": "pre_fetch"},
                    )
        except Exception as exc:  # noqa: BLE001
            return {"status": "canonical_error", "error": str(exc), "inserted": 0,
                    "skipped": 0, "tracing_no": tracing}
        return {"status": "quarantined", "detail": "company unresolved (pre-fetch)",
                "inserted": 0, "skipped": 0, "tracing_no": tracing, "has_raw": False}

    url = _absolute_codal_url(letter.get("Url") or letter.get("PdfUrl"))
    if __import__("os").environ.get("CODAL_JOB_DIR"):
        from codal_challenge import current_channel
        channel = current_channel()
        if channel:
            channel.update(state="running_browser" if __import__("codal_transport").current()._browser_mode else "running_http",
                           stage="report_body", current_report_id=tracing,
                           message="در حال دریافت متن گزارش")
    try:
        body = _fetch_text(url) if (fetch_body and url) else None
        if fetch_body and url and not body:
            return {"status": "canonical_error", "error": "Codal report body was empty or unavailable; metadata was not marked complete",
                    "inserted": 0, "skipped": 0, "tracing_no": tracing, "has_raw": False}
    except (InterruptedError, TimeoutError):
        raise
    except Exception as exc:  # noqa: BLE001 - keep incomplete bodies out of dedup
        try:
            from codal_challenge import CodalChallengeError
            if isinstance(exc, CodalChallengeError):
                raise
        except ImportError:
            pass
        return {"status": "canonical_error", "error": f"Codal report body fetch failed: {exc}",
                "inserted": 0, "skipped": 0, "tracing_no": tracing, "has_raw": False}
    try:
        res = canonical_ingest.dual_write_report(
            name=name, symbol=symbol, source="codal",
            source_report_id=tracing, report_type="codal_letter", title=letter.get("Title"),
            source_url=url, published_at=_publish_datetime_iso(letter.get("PublishDateTime")),
            content_text=body,
            content_json=None if body else {"tracing_no": tracing, "title": letter.get("Title")},
            payload_type="html" if body else "json", collected_at=_now_iso(),
            parser_name="codal_hook", parser_version="v1",
            supersedes_source_report_id=supersedes_source_report_id)
        return {"status": res.status, "inserted": res.inserted, "skipped": res.skipped,
                "error": getattr(res, "error", ""), "ids": getattr(res, "ids", {}),
                "tracing_no": tracing, "has_raw": body is not None}
    except Exception as exc:  # noqa: BLE001
        return {"status": "canonical_error", "error": str(exc), "inserted": 0, "skipped": 0,
                "tracing_no": tracing}


def ingest_codal_authoritative(letter: dict, fetch_body: bool = True, legacy_writer=None,
                               supersedes_source_report_id: str | None = None):
    """Canonical-authoritative Codal ingestion (raw -> report/version/parse)."""
    if not codal_canonical_authority():
        if legacy_writer:
            try:
                legacy_writer()
            except Exception:
                pass
        res = _canonical_codal_write(letter, fetch_body, supersedes_source_report_id)
        res["outcome"] = "LEGACY_AUTHORITATIVE"
        res["authority"] = "LEGACY"
        return res

    started = _now_iso()
    res = _canonical_codal_write(letter, fetch_body, supersedes_source_report_id)
    canonical_ok = res["status"] in ("written", "quarantined") and res["status"] != "canonical_error"
    mirror_status = "not_attempted"
    outcome = "CANONICAL_FAILED"
    if canonical_ok and legacy_writer is not None:
        try:
            legacy_writer(); mirror_status = "success"
            outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"
        except Exception as exc:  # noqa: BLE001
            mirror_status = f"failed: {type(exc).__name__}"
            outcome = "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED"
    elif canonical_ok:
        outcome = "CANONICAL_SUCCESS_LEGACY_SUCCESS"
        if res["status"] == "quarantined":
            outcome = "QUARANTINED_IDENTITY"
    if not canonical_ok:
        _retry_record("codal_report", {"source_report_id": res.get("tracing_no", "")}, res.get("error", "canonical_error"))
        if legacy_writer is not None and codal_fallback_enabled():
            try:
                legacy_writer(); mirror_status = "fallback_success"
                outcome = "CANONICAL_FAILED_LEGACY_FALLBACK_USED"
            except Exception as exc:  # noqa: BLE001
                mirror_status = f"fallback_failed: {type(exc).__name__}"

    if res["status"] == "quarantined":
        health = "IDENTITY_QUARANTINE"
    elif canonical_ok and mirror_status == "success":
        health = "HEALTHY"
    elif canonical_ok:
        health = "DEGRADED_LEGACY_MIRROR"
    else:
        health = "CANONICAL_ERROR"
    summary = {"domain": "CODAL", "authority": "CANONICAL", "outcome": outcome,
               "canonical_status": res["status"], "legacy_mirror_status": mirror_status,
               "has_raw": res.get("has_raw", False), "tracing_no": res.get("tracing_no", ""),
               "retry_backlog": retry_backlog_count("codal_report"), "health": health}
    try:
        print(json.dumps(summary, ensure_ascii=False))
    except Exception:
        pass
    res.update({"outcome": outcome, "authority": "CANONICAL", "legacy_mirror_status": mirror_status, "health": health})
    return res


def dual_write_codal_letter(letter: dict, fetch_body: bool = True):
    """Dual-write a live Codal discovery letter: report + version + parse_run + raw.

    source_report_id = Codal TracingNo. The real fetched payload is captured in
    raw.report_payloads; identical content deduplicates.
    """
    if not dual_write_enabled():
        return {"status": "skipped_legacy_only"}
    if not _load():
        return {"status": "canonical_error", "error": _import_error}
    started = _now_iso()
    canonical_ingest = _canonical["mod"]
    tracing = str(letter.get("TracingNo") or "").strip()
    if not tracing:
        return {"status": "no_tracing_no"}
    url = _absolute_codal_url(letter.get("Url") or letter.get("PdfUrl"))
    title = letter.get("Title")
    company_name = letter.get("CompanyName")
    symbol = letter.get("Symbol")
    published = _publish_datetime_iso(letter.get("PublishDateTime"))
    body = _fetch_text(url) if (fetch_body and url) else None
    try:
        res = canonical_ingest.dual_write_report(
            name=company_name, symbol=symbol, source="codal", source_report_id=tracing,
            report_type="codal_letter", title=title, source_url=url,
            published_at=published, content_text=body,
            content_json=None if body else {"tracing_no": tracing, "title": title},
            payload_type="html" if body else "json", collected_at=_now_iso(),
            parser_name="codal_hook", parser_version="v1")
        _record(domain="codal_report", script="codal_hook", source="codal",
                legacy_result="success", canonical_result="success" if res.written else res.status,
                rows_attempted=1, rows_inserted=res.inserted, rows_skipped=res.skipped,
                rows_quarantined=1 if res.status == "quarantined" else 0,
                recon_mismatch=0 if res.status in ("written", "quarantined") else 1,
                canonical_errors=0 if res.status != "canonical_error" else 1,
                started_at=started, finished_at=_now_iso(), batch_id=f"codal-{tracing}")
        _log_summary("codal_report", "success", res.status, res.inserted, res.skipped,
                     1 if res.status == "quarantined" else 0, 0)
        return {"status": res.status, "inserted": res.inserted, "skipped": res.skipped,
                "tracing_no": tracing, "has_raw": body is not None, "ids": res.ids}
    except Exception as exc:  # noqa: BLE001
        _record(domain="codal_report", script="codal_hook", source="codal",
                legacy_result="success", canonical_result="canonical_error",
                canonical_errors=1, recon_mismatch=1, started_at=started, finished_at=_now_iso(),
                batch_id=f"codal-{tracing}")
        _retry_record("codal_report", {"source_report_id": tracing}, exc)
        return {"status": "canonical_error", "error": str(exc)}
