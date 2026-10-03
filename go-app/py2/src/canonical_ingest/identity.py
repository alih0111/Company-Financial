"""Canonical identity resolution.

Company and Security are distinct canonical entities. Resolution uses the
existing canonical mappings and source identifiers; it never derives identity
from a display name hash and never fabricates rows. Unresolved identities are
returned as None so the caller can quarantine them.
"""

from __future__ import annotations

from typing import Any, Optional

SOURCE_SYSTEM = "sqlserver_codal"


def _scalar(cur: Any, sql: str, params: tuple) -> Optional[str]:
    cur.execute(sql, params)
    row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def resolve_company(
    cur: Any,
    *,
    legacy_company_id: str | None = None,
    ins_code: str | int | None = None,
    name: str | None = None,
    symbol: str | None = None,
) -> Optional[str]:
    if legacy_company_id:
        got = _scalar(
            cur,
            """SELECT target_uuid FROM core.legacy_entity_map
               WHERE source_system=%s AND entity_type='company' AND legacy_key=%s
               ORDER BY confidence DESC NULLS LAST LIMIT 1""",
            (SOURCE_SYSTEM, str(legacy_company_id)),
        )
        if got:
            return got
    if ins_code not in (None, ""):
        got = _scalar(
            cur,
            "SELECT company_id FROM core.securities WHERE tsetmc_ins_code=%s LIMIT 1",
            (int(ins_code),),
        )
        if got:
            return got
    if name:
        got = _scalar(
            cur,
            """SELECT s.company_id FROM core.security_aliases a
               JOIN core.securities s ON s.id = a.security_id
               WHERE a.alias_value=%s AND a.alias_type IN ('company_name','symbol')
               LIMIT 1""",
            (name.strip(),),
        )
        if got:
            return got
    # نام قانونی کدال اغلب با alias های ما یکی نیست؛ نماد کدال مطمئن‌ترین
    # کلید دوم است (ستون codal_symbol در core.securities برای همین است).
    if symbol not in (None, ""):
        got = _scalar(
            cur,
            "SELECT company_id FROM core.securities WHERE codal_symbol=%s "
            "AND company_id IS NOT NULL LIMIT 1",
            (symbol.strip(),),
        )
        if got:
            return got
        got = _scalar(
            cur,
            """SELECT s.company_id FROM core.security_aliases a
               JOIN core.securities s ON s.id = a.security_id
               WHERE a.alias_value=%s AND a.alias_type = 'symbol'
               LIMIT 1""",
            (symbol.strip(),),
        )
        if got:
            return got
    return None


def resolve_security(
    cur: Any,
    *,
    legacy_company_id: str | None = None,
    ins_code: str | int | None = None,
    symbol: str | None = None,
    name: str | None = None,
) -> Optional[str]:
    if legacy_company_id:
        got = _scalar(
            cur,
            """SELECT target_uuid FROM core.legacy_entity_map
               WHERE source_system=%s AND entity_type='security' AND legacy_key=%s
               ORDER BY confidence DESC NULLS LAST LIMIT 1""",
            (SOURCE_SYSTEM, str(legacy_company_id)),
        )
        if got:
            return got
    if ins_code not in (None, ""):
        got = _scalar(
            cur,
            "SELECT id FROM core.securities WHERE tsetmc_ins_code=%s LIMIT 1",
            (int(ins_code),),
        )
        if got:
            return got
    for value in (symbol, name):
        if value:
            got = _scalar(
                cur,
                """SELECT s.id FROM core.security_aliases a
                   JOIN core.securities s ON s.id = a.security_id
                   WHERE a.alias_value=%s AND a.alias_type IN ('symbol','company_name')
                   LIMIT 1""",
                (value.strip(),),
            )
            if got:
                return got
    return None


def primary_security_for_company(cur: Any, company_id: str) -> Optional[str]:
    return _scalar(
        cur,
        """SELECT id FROM core.securities
           WHERE company_id=%s
           ORDER BY is_primary DESC, created_at ASC LIMIT 1""",
        (company_id,),
    )
