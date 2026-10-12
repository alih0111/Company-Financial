# -*- coding: utf-8 -*-
"""Unit tests for codal_publish_resolver — DB-free, cache fixtures on disk.

Run: python -m pytest provenance_v1/tests/test_codal_publish_resolver.py -q
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codal_publish_resolver import (  # noqa: E402
    CodalLetter,
    CodalPublishResolver,
    DBCodalRow,
    Resolution,
    ST_AMBIGUOUS,
    ST_CONFLICTING,
    ST_NO_EVIDENCE,
    ST_VERIFIED,
    gregorian_to_jalali_text,
    norm_digits,
    parse_persian_datetime,
    title_period_jalali,
)


class FakeCursor:
    def __init__(self, routes):
        self._routes = routes  # list[(needle, rows)]
        self._rows = []

    def execute(self, sql, params=()):
        self._rows = []
        for needle, rows in self._routes:
            if needle in sql:
                self._rows = rows() if callable(rows) else rows
                return

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, routes):
        self._routes = routes

    def cursor(self):
        return FakeCursor(self._routes)


def write_cache(tmp_path, name, symbol, letter_type, letters):
    doc = {"symbol": symbol, "letter_type": letter_type, "total": len(letters),
           "pages": 1, "letters": letters}
    (tmp_path / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return str(tmp_path)


# ---------- parsers ----------

def test_norm_digits_and_title_period():
    assert norm_digits("۱۴۰۵/۰۷/۰۲") == "1405/07/02"
    assert title_period_jalali(
        "اطلاعات و صورت‌های مالی میاندوره‌ای  دوره ۳ ماهه منتهی به  ۱۴۰۵/۰۳/۳۱ (حسابرسی نشده)"
    ) == "1405/03/31"
    assert title_period_jalali("no period here") is None
    assert title_period_jalali(None) is None


def test_parse_persian_datetime_tehran_offset():
    dt = parse_persian_datetime("۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴")
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 9, 24, 16, 28)
    assert dt.utcoffset().total_seconds() == 3.5 * 3600


def test_jalali_gregorian_roundtrip():
    j = gregorian_to_jalali_text(date(2020, 6, 20))
    assert j == "1399/03/31"
    dt = parse_persian_datetime("1399/03/31 09:26:05")
    assert (dt.year, dt.month, dt.day) == (2020, 6, 20)


# ---------- fixtures helpers ----------

def make_resolver(tmp_path, cache_files, db_routes):
    cache_dir = tmp_path / "caches"
    cache_dir.mkdir(exist_ok=True)
    for name, symbol, letter_type, letters in cache_files:
        write_cache(cache_dir, name, symbol, letter_type, letters)
    conn = FakeConn(db_routes)
    return CodalPublishResolver(conn, str(cache_dir))


def db_routes_for(fin_rows, company_tracings, tracing_published=()):
    return [
        ("company_id = %s::uuid AND published_at IS NOT NULL",
         lambda: fin_rows),
        ("SELECT DISTINCT source_report_id FROM ingestion.reports",
         lambda: [(t,) for t in company_tracings]),
        ("SELECT source_report_id, published_at FROM ingestion.reports",
         lambda: list(tracing_published)),
    ]


# ---------- resolver behaviour ----------

def test_single_db_row_is_verified_and_corroborated(tmp_path):
    pub = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    caches = [("ول GMT_lt6.json", "ول GMT", 6, [{
        "tracing_no": "1001", "title": "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱",
        "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"}])]
    routes = db_routes_for(
        [("r-uuid-1", "1001", "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱", pub, "1404/04/31", date(2025, 7, 22))],
        ["1001"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-1", "ول GMT", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_VERIFIED
    assert res.publish_at == pub
    assert res.evidence[0]["corroboration"] == "db_row_and_cache_agree"


def test_db_cache_disagreement_is_conflicting(tmp_path):
    pub_db = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    caches = [("ول GMT_lt6.json", "ول GMT", 6, [{
        "tracing_no": "1001", "title": "t", "publish_datetime": "۱۴۰۴/۰۵/۰۹ ۰۸:۰۰:۰۰",
        "letter_code": "ن-۱۰", "url": "u"}])]
    routes = db_routes_for(
        [("r-1", "1001", "t", pub_db, "1404/04/31", date(2025, 7, 22))], ["1001"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-1", "ول GMT", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_CONFLICTING
    assert "1001" in res.reason


def test_correction_letter_never_inherits_original_date(tmp_path):
    """Two letters, same period, different dates (original + اصلاحیه) — with
    no usable is_audited/is_restated refinement the match is ambiguous."""
    d1 = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    d2 = parse_persian_datetime("۱۴۰۴/۰۶/۱۵ ۱۲:۰۰:۰۰")
    caches = [("ول GMT_lt6.json", "ول GMT", 6, [
        {"tracing_no": "2001", "title": "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱",
         "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
        {"tracing_no": "2002", "title": "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱ (اصلاحیه)",
         "publish_datetime": "۱۴۰۴/۰۶/۱۵ ۱۲:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
    ])]
    # DB has BOTH codal rows (original + correction) for this company+period
    routes = db_routes_for([
        ("r-1", "2001", "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱", d1, "1404/04/31", date(2025, 7, 22)),
        ("r-2", "2002", "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱ (اصلاحیه)", d2, "1404/04/31", date(2025, 7, 22)),
    ], ["2001", "2002"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-1", "ول GMT", "1404/04/31", date(2025, 7, 22),
                              is_audited=None, is_restated=False)
    assert res.status == ST_AMBIGUOUS
    assert len(res.candidates) == 2
    assert res.publish_at is None


def test_single_distinct_date_among_multiple_letters_is_verified(tmp_path):
    d1 = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    caches = [("ول GMT_lt6.json", "ول GMT", 6, [
        {"tracing_no": "3001", "title": "الف منتهی به ۱۴۰۴/۰۴/۳۱",
         "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
        {"tracing_no": "3002", "title": "ب منتهی به ۱۴۰۴/۰۴/۳۱",
         "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
    ])]
    routes = db_routes_for([
        ("r-1", "3001", "الف منتهی به ۱۴۰۴/۰۴/۳۱", d1, "1404/04/31", date(2025, 7, 22)),
        ("r-2", "3002", "ب منتهی به ۱۴۰۴/۰۴/۳۱", d1, "1404/04/31", date(2025, 7, 22)),
    ], ["3001", "3002"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-1", "ول GMT", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_VERIFIED
    assert res.publish_at == d1


def test_cache_only_match_requires_proven_symbol_binding(tmp_path):
    d1 = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    caches = [("کاما_lt6.json", "کاما", 6, [{
        "tracing_no": "4001", "title": "صورت‌های مالی منتهی به ۱۴۰۴/۰۴/۳۱",
        "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"}])]

    # (a) no DB tracing overlap -> not verified
    routes = db_routes_for([], [])  # no codal rows at all
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-9", "کاما", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_AMBIGUOUS
    assert "binding not proven" in res.reason

    # (b) company has another codal row whose tracing_no is in the cache
    routes = db_routes_for([], ["4001"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-9", "کاما", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_VERIFIED
    assert res.publish_at == d1


def test_no_evidence_when_nothing_matches(tmp_path):
    r = make_resolver(tmp_path, [], db_routes_for([], []))
    res = r.resolve_statement("cid-1", "غایب", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_NO_EVIDENCE


def test_monthly_resolution(tmp_path):
    d1 = parse_persian_datetime("۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴")
    caches = [("ول GMT_lt58.json", "ول GMT", 58, [{
        "tracing_no": "5001", "title": "گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به  ۱۴۰۵/۰۶/۳۱",
        "publish_datetime": "۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴", "letter_code": "ن-۳۱", "url": "u"}])]
    routes = db_routes_for([], ["5001"])  # binding proven
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_monthly("cid-1", "ول GMT", "1405/06/31")
    assert res.status == ST_VERIFIED
    assert res.publish_at == d1

    # wrong letter_type never leaks into statement resolution
    res2 = r.resolve_statement("cid-1", "ول GMT", "1405/06/31", None)
    assert res2.status == ST_NO_EVIDENCE


def test_monthly_multiple_dates_is_ambiguous(tmp_path):
    caches = [("ول GMT_lt58.json", "ول GMT", 58, [
        {"tracing_no": "6001", "title": "ماهانه منتهی به ۱۴۰۵/۰۶/۳۱",
         "publish_datetime": "۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴", "letter_code": "ن-۳۱", "url": "u"},
        {"tracing_no": "6002", "title": "ماهانه منتهی به ۱۴۰۵/۰۶/۳۱ (اصلاحیه)",
         "publish_datetime": "۱۴۰۵/۰۸/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۳۱", "url": "u"},
    ])]
    routes = db_routes_for([], ["6001", "6002"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_monthly("cid-1", "ول GMT", "1405/06/31")
    assert res.status == ST_AMBIGUOUS


def test_ambiguous_match_never_verified_even_with_binding(tmp_path):
    """Direct guard of the hardest mission rule."""
    caches = [("کاما_lt6.json", "کاما", 6, [
        {"tracing_no": "7001", "title": "منتهی به ۱۴۰۴/۰۴/۳۱",
         "publish_datetime": "۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
        {"tracing_no": "7002", "title": "منتهی به ۱۴۰۴/۰۴/۳۱ (حسابرسی شده)",
         "publish_datetime": "۱۴۰۴/۰۷/۰۱ ۱۰:۰۰:۰۰", "letter_code": "ن-۱۰", "url": "u"},
    ])]
    routes = db_routes_for([], ["7001", "7002"])
    r = make_resolver(tmp_path, caches, routes)
    res = r.resolve_statement("cid-1", "کاما", "1404/04/31", date(2025, 7, 22))
    assert res.status == ST_AMBIGUOUS


def test_resolution_dict_serializable():
    res = Resolution(status=ST_NO_EVIDENCE, reason="x")
    d = res.to_dict()
    assert d["status"] == ST_NO_EVIDENCE and d["publish_at"] is None


def test_db_tracing_published_loaded(tmp_path):
    pub = parse_persian_datetime("۱۴۰۴/۰۵/۰۱ ۱۰:۰۰:۰۰")
    routes = db_routes_for([], [], tracing_published=[("9001", pub)])
    r = make_resolver(tmp_path, [], routes)
    assert r.db_published_by_tracing["9001"] == pub
    assert r.cache_files_loaded == 0
