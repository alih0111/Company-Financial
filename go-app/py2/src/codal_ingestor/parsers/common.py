from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from codal_ingestor.domain import normalize_jalali_date, normalize_label, normalize_text, to_decimal


DATE_RE = re.compile(r"(?:13|14)\d{2}/\d{1,2}/\d{1,2}")


def is_hidden_cell(tag: Tag | None) -> bool:
    if tag is None:
        return False
    if tag.has_attr("hidden"):
        return True
    if normalize_text(tag.get("aria-hidden", "")).lower() == "true":
        return True
    style = (tag.get("style") or "").replace(" ", "").lower()
    return (
        "display:none" in style
        or "visibility:hidden" in style
        or "opacity:0" in style
    )


def visible_direct_cells(row: Tag | None, cell_name: str = "td") -> list[Tag]:
    if row is None:
        return []
    return [
        cell
        for cell in row.find_all(cell_name, recursive=False)
        if isinstance(cell, Tag) and not is_hidden_cell(cell)
    ]


def expand_visible_cells(row: Tag | None, cell_name: str = "td") -> list[Tag]:
    expanded: list[Tag] = []
    for cell in visible_direct_cells(row, cell_name):
        try:
            colspan = max(1, int(cell.get("colspan", 1)))
        except (TypeError, ValueError):
            colspan = 1
        expanded.extend([cell] * colspan)
    return expanded


def build_header_grid(table: Tag) -> list[list[str | None]]:
    header_rows = table.select("thead tr")
    grid: list[list[str | None]] = []

    for row_index, tr in enumerate(header_rows):
        while len(grid) <= row_index:
            grid.append([])
        column_index = 0

        for th in visible_direct_cells(tr, "th"):
            while (
                column_index < len(grid[row_index])
                and grid[row_index][column_index] is not None
            ):
                column_index += 1

            text = normalize_text(th.get_text(" ", strip=True))
            try:
                colspan = max(1, int(th.get("colspan", 1)))
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = max(1, int(th.get("rowspan", 1)))
            except (TypeError, ValueError):
                rowspan = 1

            for target_row in range(row_index, row_index + rowspan):
                while len(grid) <= target_row:
                    grid.append([])
                required = column_index + colspan
                if len(grid[target_row]) < required:
                    grid[target_row].extend([None] * (required - len(grid[target_row])))
                for target_column in range(column_index, column_index + colspan):
                    grid[target_row][target_column] = text
            column_index += colspan

    return grid


def get_column_headers(table: Tag) -> list[dict[str, Any]]:
    grid = build_header_grid(table)
    if not grid:
        return []

    max_columns = max(len(row) for row in grid)
    columns: list[dict[str, Any]] = []
    for column_index in range(max_columns):
        parts: list[str] = []
        for row in grid:
            if column_index >= len(row):
                continue
            value = row[column_index]
            if value and value not in parts:
                parts.append(value)
        columns.append(
            {
                "index": column_index,
                "parts": parts,
                "text": normalize_label(" ".join(parts)),
                "raw": " | ".join(parts),
            }
        )
    return columns


def find_jalali_date(value: str | None) -> str | None:
    match = DATE_RE.search(normalize_text(value))
    if match is None:
        return None
    return normalize_jalali_date(match.group(0))


def extract_date_from_table(table: Tag) -> str | None:
    for column in get_column_headers(table):
        date_value = find_jalali_date(column["raw"])
        if date_value:
            return date_value
    return None


def detect_currency_unit(text: str) -> str:
    normalized = normalize_label(text)
    if "میلیون ریال" in normalized:
        return "million_rial"
    if "هزار ریال" in normalized:
        return "thousand_rial"
    if "ریال" in normalized:
        return "rial"
    return "unknown"


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def cell_decimal(cells: list[Tag], index: int):
    if index < 0 or index >= len(cells):
        return None
    return to_decimal(cells[index].get_text(" ", strip=True))
