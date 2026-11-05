"""Company fiscal calendar, derived from explicit Codal report titles.

The report-chain TTM resolver must anchor on the company's **actual** annual
report. Assuming the fiscal year ends in Jalali month 12 is wrong for non-Esfand
issuers (e.g. شلیا reports 2/5/8/11, شمس/فپنتا/قلرست report 1/4/7/10).

The only explicit evidence in the canonical store is the Codal report title
(`ingestion.reports.title`, source='codal', report_type='financial_statement'),
which states both the duration ("دوره ۳ ماهه" / "سال مالی" / "۱۲ ماهه") and the
period end ("منتهی به YYYY/MM/DD"). Duration is never inferred from the calendar
month — this mirrors `fiscalYearDurationFromTitle` in the Go read layer.

Per company the calendar exposes:

    annual_month  the fiscal month of a 12-month report (evidence-backed)
    source        provenance string
    state         EXPLICIT when a 12-month report exists, else UNKNOWN

When the state is UNKNOWN no annual anchor may be assumed: the caller must
return a data-quality-blocked TTM rather than a guessed one.
"""
from __future__ import annotations

import re
from collections import Counter

STATE_EXPLICIT = "EXPLICIT"
STATE_UNKNOWN = "UNKNOWN"

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DATE_RE = re.compile(r"(1[34]\d{2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")


def normalize_digits(text: str) -> str:
    return (text or "").translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def parse_title(title: str) -> tuple[int, int]:
    """Parse a Codal report title -> (fiscal_year, duration_months).

    Zeros when a field is not explicitly present. Duration never falls back to
    the calendar month.
    """
    t = normalize_digits(title or "")
    if not t.strip():
        return 0, 0

    duration = 0
    for candidate in (12, 9, 6, 3):
        if re.search(rf"{candidate}\s*ماهه", t):
            duration = candidate
            break
    if duration == 0 and ("سال مالی" in t or "12 ماهه" in t):
        duration = 12

    year = 0
    marker = t.find("منتهی به")
    m = _DATE_RE.search(t[marker:]) if marker >= 0 else None
    if m is None:
        m = _DATE_RE.search(t)
    if m:
        year = int(m.group(1))
    return year, duration


def build_fiscal_calendar(rows) -> tuple[dict, dict]:
    """Derive per-cell durations and the per-company annual anchor month.

    ``rows``: (company_id, title, fiscal_year, fiscal_month) where fiscal_year /
    fiscal_month identify the statement cell the title belongs to. Later rows win
    for a given cell (callers pass PIT-ordered rows).

    Returns:
      durations[(company_id, (fy, fm))] = duration_months
      calendar[company_id] = {"annual_month", "source", "state", "n_12m",
                              "months_seen"}
    """
    durations: dict = {}
    calendar: dict = {}
    for company_id, title, fy, fm in rows:
        if fy is None or fm is None:
            continue
        _title_fy, dur = parse_title(title or "")
        if dur == 0:
            continue
        durations[(company_id, (fy, fm))] = dur
        entry = calendar.setdefault(company_id, {"annual_month": None,
                                                 "source": None,
                                                 "state": STATE_UNKNOWN,
                                                 "n_12m": 0,
                                                 "months": Counter()})
        if dur == 12:
            entry["n_12m"] += 1
            entry["months"][fm] += 1
            entry["annual_month"] = entry["months"].most_common(1)[0][0]
            entry["state"] = STATE_EXPLICIT
            entry["source"] = "codal_report_title:12m"
    for entry in calendar.values():
        entry["months_seen"] = sorted(entry["months"])
        del entry["months"]
    return durations, calendar


def annual_month_of(calendar: dict, company_id: str) -> tuple[int | None, str, str | None]:
    """(annual_month, state, source) for a company."""
    entry = calendar.get(company_id)
    if not entry or entry["state"] != STATE_EXPLICIT or not entry["annual_month"]:
        return None, STATE_UNKNOWN, None
    return entry["annual_month"], STATE_EXPLICIT, entry["source"]


def prev_annual_cell(durations_by_cell: dict, fy: int, fm: int):
    """Previous fiscal year's annual (duration 12) cell, or None.

    Anchoring on the previous annual *cell* rather than a fixed calendar month
    keeps the TTM correct across a fiscal-year change (a company may have
    12-month reports ending in two different months over its history).

    The anchor must be 1..12 Jalali months before the current cell: an older
    annual report is not the prior fiscal year, and chaining against it would
    silently build a multi-year window instead of a trailing twelve months.
    """
    best = None
    for (cfy, cfm), dur in (durations_by_cell or {}).items():
        if dur != 12:
            continue
        gap = (fy - cfy) * 12 + (fm - cfm)
        if not (1 <= gap <= 12):
            continue
        if best is None or (cfy, cfm) > best:
            best = (cfy, cfm)
    return best
