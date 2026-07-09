from __future__ import annotations

import re

from bs4 import Tag

from codal_ingestor.domain import MonthlyReportData, normalize_label, normalize_text, to_decimal
from codal_ingestor.parsers.common import (
    build_header_grid,
    detect_currency_unit,
    expand_visible_cells,
    extract_date_from_table,
    is_hidden_cell,
    soup_from_html,
)


def is_one_month_header(value: str) -> bool:
    return bool(re.search(r"دوره\s*(?:یک|1)\s*ماهه", normalize_text(value)))


def find_supported_statement_table(html: str) -> Tag | None:
    soup = soup_from_html(html)
    tables = soup.select("table.rayanDynamicStatement")
    for table in tables:
        headers = [
            normalize_text(th.get_text(" ", strip=True))
            for th in table.select("thead th")
            if not is_hidden_cell(th)
        ]
        has_period = any(is_one_month_header(item) for item in headers)
        has_metric = any(
            any(keyword in item for keyword in ("تعداد تولید", "تعداد فروش", "مبلغ فروش", "درآمد", "درامد"))
            for item in headers
        )
        if has_period and has_metric:
            return table
    return tables[0] if tables else None


def one_month_columns(table: Tag) -> list[dict]:
    grid = build_header_grid(table)
    if not grid:
        return []
    max_columns = max(len(row) for row in grid)
    result: list[dict] = []

    for column_index in range(max_columns):
        headers: list[str] = []
        for row in grid:
            if column_index >= len(row):
                continue
            value = row[column_index]
            if value and value not in headers:
                headers.append(value)
        if any(is_one_month_header(item) for item in headers):
            result.append(
                {
                    "index": column_index,
                    "headers": headers,
                    "combined": normalize_label(" | ".join(headers)),
                }
            )
    return result


def find_total_cells(table: Tag) -> list[Tag] | None:
    for tr in reversed(table.select("tbody tr")):
        cells = expand_visible_cells(tr, "td")
        if not cells:
            continue
        title = normalize_label(cells[0].get_text(" ", strip=True))
        if title in {"جمع", "جمع کل", "مجموع"} or re.fullmatch(
            r"جمع(?: کل)? درآمدهای? عملیاتی", title
        ):
            return cells
    return None


def find_named_row_cells(table: Tag, phrases: tuple[str, ...]) -> list[Tag] | None:
    normalized_phrases = tuple(normalize_label(item) for item in phrases)
    for tr in table.select("tbody tr"):
        cells = expand_visible_cells(tr, "td")
        if not cells:
            continue
        title = normalize_label(cells[0].get_text(" ", strip=True))
        if any(phrase in title for phrase in normalized_phrases):
            return cells
    return None


def value_at(cells: list[Tag] | None, index: int):
    if cells is None or index >= len(cells):
        return None
    return to_decimal(cells[index].get_text(" ", strip=True))


def parse_monthly_html(
    *,
    html: str,
    company_name: str,
    source_url: str,
    report_date: str | None,
) -> MonthlyReportData:
    table = find_supported_statement_table(html)
    if table is None:
        raise ValueError("monthly activity table was not found")

    columns = one_month_columns(table)
    if not columns:
        raise ValueError("one-month columns were not found")

    total_cells = find_total_cells(table)
    if total_cells is None:
        raise ValueError("monthly total row was not found")

    production_index: int | None = None
    sales_quantity_index: int | None = None
    sales_amount_index: int | None = None
    revenue_index: int | None = None

    for item in columns:
        combined = item["combined"]
        index = int(item["index"])
        if "تعداد تولید" in combined:
            production_index = index
        elif "تعداد فروش" in combined:
            sales_quantity_index = index
        elif "مبلغ فروش" in combined:
            sales_amount_index = index
        elif "درآمد" in combined or "درامد" in combined:
            if revenue_index is None or "طی دوره" in combined:
                revenue_index = index

    if sales_amount_index is not None:
        production = value_at(total_cells, production_index) if production_index is not None else None
        sales_quantity = (
            value_at(total_cells, sales_quantity_index)
            if sales_quantity_index is not None
            else None
        )
        sales_amount = value_at(total_cells, sales_amount_index)
        amount_index = sales_amount_index
        report_kind = "product"
    elif revenue_index is not None:
        production = None
        sales_quantity = None
        sales_amount = value_at(total_cells, revenue_index)
        amount_index = revenue_index
        report_kind = "service"
    else:
        raise ValueError("supported monthly amount column was not found")

    domestic_cells = find_named_row_cells(table, ("جمع فروش داخلی", "فروش داخلی"))
    export_cells = find_named_row_cells(table, ("جمع فروش صادراتی", "فروش صادراتی"))
    domestic_amount = value_at(domestic_cells, amount_index)
    export_amount = value_at(export_cells, amount_index)

    period_end = report_date or extract_date_from_table(table)
    if not period_end:
        raise ValueError("report date was not found")

    currency_unit = detect_currency_unit(table.get_text(" ", strip=True))
    if currency_unit == "unknown":
        currency_unit = "million_rial"

    raw_payload = {
        "report_kind": report_kind,
        "one_month_columns": columns,
        "selected_indexes": {
            "production": production_index,
            "sales_quantity": sales_quantity_index,
            "sales_amount": sales_amount_index,
            "revenue": revenue_index,
        },
    }

    return MonthlyReportData(
        company_name=company_name,
        period_end_jalali=period_end,
        source_url=source_url,
        production_quantity=production,
        sales_quantity=sales_quantity,
        sales_amount=sales_amount,
        domestic_sales_amount=domestic_amount,
        export_sales_amount=export_amount,
        currency_unit=currency_unit,
        quantity_unit="reported_unit",
        raw_payload=raw_payload,
    )
