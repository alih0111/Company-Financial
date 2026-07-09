from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from bs4 import Tag

from codal_ingestor.domain import (
    FinancialFactData,
    ProfitLossReportData,
    normalize_label,
    normalize_text,
    to_decimal,
)
from codal_ingestor.parsers.common import (
    DATE_RE,
    detect_currency_unit,
    expand_visible_cells,
    extract_date_from_table,
    get_column_headers,
    soup_from_html,
)


@dataclass(slots=True)
class ParsedRow:
    title: str
    raw_title: str
    cells: list[Tag]


def find_profit_loss_table(html: str) -> Tag | None:
    soup = soup_from_html(html)
    candidates = soup.select("table.rayanDynamicStatement")
    required_markers = (
        "درآمدهای عملیاتی",
        "سود زیان ناخالص",
        "سود زیان عملیاتی",
        "سود زیان خالص",
        "سرمایه",
    )
    best: Tag | None = None
    best_score = -1
    for table in candidates:
        normalized = normalize_label(table.get_text(" ", strip=True))
        score = sum(1 for marker in required_markers if normalize_label(marker) in normalized)
        if score > best_score:
            best_score = score
            best = table
    return best if best_score >= 2 else None


def get_period_columns(table: Tag) -> list[dict]:
    columns = get_column_headers(table)
    periods: list[dict] = []
    for column in columns:
        if column["index"] == 0 or column["text"] == "شرح":
            continue
        if "درصد تغییر" in column["text"]:
            continue
        if DATE_RE.search(normalize_text(column["raw"])) or "دوره منتهی" in column["text"]:
            periods.append(column)

    if not periods:
        for column in columns:
            if column["index"] == 0 or column["text"] == "شرح":
                continue
            if "درصد تغییر" not in column["text"]:
                periods.append(column)
    return sorted(periods, key=lambda item: item["index"])[:3]


def get_rows(table: Tag) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    for tr in table.select("tbody tr"):
        cells = expand_visible_cells(tr, "td")
        if not cells:
            continue
        raw_title = normalize_text(cells[0].get_text(" ", strip=True))
        title = normalize_label(raw_title)
        if title:
            rows.append(ParsedRow(title=title, raw_title=raw_title, cells=cells))
    return rows


def _row_has_numeric(row: ParsedRow, indexes: Iterable[int]) -> bool:
    for index in indexes:
        if index >= len(row.cells):
            continue
        if to_decimal(row.cells[index].get_text(" ", strip=True)) is not None:
            return True
    return False


def find_row(
    rows: list[ParsedRow],
    *,
    exact_titles: tuple[str, ...] = (),
    contains_all: tuple[str, ...] = (),
    excludes: tuple[str, ...] = (),
    indexes: list[int],
) -> ParsedRow | None:
    exact = {normalize_label(item) for item in exact_titles}
    contains = tuple(normalize_label(item) for item in contains_all)
    excluded = tuple(normalize_label(item) for item in excludes)
    partial: list[ParsedRow] = []

    for row in rows:
        if any(item and item in row.title for item in excluded):
            continue
        if not _row_has_numeric(row, indexes):
            continue
        if row.title in exact:
            return row
        if contains and all(item in row.title for item in contains):
            partial.append(row)
    return partial[0] if partial else None


def _value(row: ParsedRow | None, index: int):
    if row is None or index >= len(row.cells):
        return None
    return to_decimal(row.cells[index].get_text(" ", strip=True))


def parse_profit_loss_html(
    *,
    html: str,
    company_name: str,
    source_url: str,
    report_date: str | None,
) -> ProfitLossReportData:
    table = find_profit_loss_table(html)
    if table is None:
        raise ValueError("profit/loss table was not found")

    periods = get_period_columns(table)
    if len(periods) < 2:
        raise ValueError("at least two financial periods are required")
    indexes = [int(item["index"]) for item in periods]
    rows = get_rows(table)

    net_eps = find_row(
        rows,
        exact_titles=(
            "سود (زیان) خالص هر سهم - ریال",
            "سود زیان خالص هر سهم ریال",
        ),
        contains_all=("سود", "زیان", "خالص", "هر سهم", "ریال"),
        excludes=("درصد",),
        indexes=indexes,
    )
    if net_eps is None:
        net_eps = find_row(
            rows,
            exact_titles=("سود (زیان) پایه هر سهم",),
            contains_all=("سود", "زیان", "پایه", "هر سهم"),
            indexes=indexes,
        )

    capital = find_row(
        rows,
        exact_titles=("سرمایه",),
        contains_all=("سرمایه",),
        excludes=("افزایش", "کاهش"),
        indexes=indexes,
    )
    operating_eps = find_row(
        rows,
        exact_titles=("عملیاتی (ریال)", "عملیاتی ریال"),
        contains_all=("عملیاتی", "ریال"),
        excludes=("غیرعملیاتی", "سود", "زیان"),
        indexes=indexes,
    )
    operating_profit = find_row(
        rows,
        exact_titles=("سود (زیان) عملیاتی", "سود(زیان) عملیاتی"),
        contains_all=("سود", "زیان", "عملیاتی"),
        excludes=("هر سهم", "قبل از مالیات", "در حال تداوم", "متوقف شده", "غیرعملیاتی"),
        indexes=indexes,
    )
    net_profit = find_row(
        rows,
        exact_titles=("سود (زیان) خالص", "سود(زیان) خالص"),
        contains_all=("سود", "زیان", "خالص"),
        excludes=("هر سهم", "عملیات", "در حال تداوم", "متوقف شده"),
        indexes=indexes,
    )

    if net_eps is None or capital is None or operating_profit is None:
        missing = [
            name
            for name, row in (
                ("net_eps", net_eps),
                ("capital", capital),
                ("operating_profit", operating_profit),
            )
            if row is None
        ]
        raise ValueError(f"required rows were not found: {', '.join(missing)}")

    amount_unit = detect_currency_unit(table.get_text(" ", strip=True))
    if amount_unit == "unknown":
        amount_unit = "million_rial"

    facts: list[FinancialFactData] = []
    metrics = (
        ("net_eps", net_eps, "rial_per_share"),
        ("capital", capital, amount_unit),
        ("operating_eps", operating_eps, "rial_per_share"),
        ("operating_profit", operating_profit, amount_unit),
        ("net_profit", net_profit, amount_unit),
    )

    for order, period in enumerate(periods, start=1):
        header = period["raw"] or f"period_{order}"
        index = int(period["index"])
        for metric_code, row, unit_code in metrics:
            if row is None:
                continue
            facts.append(
                FinancialFactData(
                    period_order=order,
                    period_header=header,
                    metric_code=metric_code,
                    value=_value(row, index),
                    unit_code=unit_code,
                )
            )

    period_end = report_date or extract_date_from_table(table)
    if not period_end:
        raise ValueError("report date was not found")

    raw_payload = {
        "period_headers": [period["parts"] for period in periods],
        "matched_rows": {
            "net_eps": net_eps.raw_title,
            "capital": capital.raw_title,
            "operating_eps": operating_eps.raw_title if operating_eps else None,
            "operating_profit": operating_profit.raw_title,
            "net_profit": net_profit.raw_title if net_profit else None,
        },
    }

    return ProfitLossReportData(
        company_name=company_name,
        period_end_jalali=period_end,
        source_url=source_url,
        facts=tuple(facts),
        raw_payload=raw_payload,
    )
