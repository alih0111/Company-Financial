from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import jdatetime


_PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_DATE_RE = re.compile(r"((?:13|14)\d{2})/(\d{1,2})/(\d{1,2})")


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).translate(_PERSIAN_ARABIC_DIGITS)
    text = _INVISIBLE_CHARS_RE.sub("", text)
    text = text.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ۀ", "ه")
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def normalize_label(value: str | None) -> str:
    text = normalize_text(value).lower()
    text = text.replace("ؤ", "و").replace("إ", "ا").replace("أ", "ا")
    text = re.sub(r"[()\[\]{}:؛،,.%٪/\\ـ_\-–—]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_company_name(value: str) -> str:
    normalized = normalize_text(value).lower()
    if not normalized:
        raise ValueError("company name cannot be empty")
    return normalized


def normalize_jalali_date(value: str) -> str:
    normalized = normalize_text(value)
    match = _DATE_RE.search(normalized)
    if match is None:
        raise ValueError(f"invalid Jalali date: {value!r}")
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}/{month:02d}/{day:02d}"


def jalali_to_gregorian(value: str) -> date:
    normalized = normalize_jalali_date(value)
    parsed = jdatetime.datetime.strptime(normalized, "%Y/%m/%d").date()
    return parsed.togregorian()


def to_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = normalize_text(str(value))
    text = text.replace(",", "").replace("٬", "")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    if text in {"", "-", "--", "---"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    cleaned = re.sub(r"[^\d.+-]", "", text)
    if cleaned in {"", "+", "-", "."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class MonthlyReportData:
    company_name: str
    period_end_jalali: str
    source_url: str
    production_quantity: Decimal | None
    sales_quantity: Decimal | None
    sales_amount: Decimal | None
    domestic_sales_amount: Decimal | None = None
    export_sales_amount: Decimal | None = None
    currency_unit: str = "unknown"
    quantity_unit: str = "reported_unit"
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FinancialFactData:
    period_order: int
    period_header: str
    metric_code: str
    value: Decimal | None
    unit_code: str


@dataclass(frozen=True, slots=True)
class ProfitLossReportData:
    company_name: str
    period_end_jalali: str
    source_url: str
    facts: tuple[FinancialFactData, ...]
    raw_payload: dict[str, Any] | None = None


def canonical_payload(report: MonthlyReportData | ProfitLossReportData) -> dict[str, Any]:
    payload = asdict(report)
    return json.loads(json.dumps(payload, default=str, ensure_ascii=False))


def content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
