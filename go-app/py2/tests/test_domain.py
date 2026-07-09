from decimal import Decimal

from codal_ingestor.domain import jalali_to_gregorian, normalize_text, to_decimal


def test_normalize_persian_text() -> None:
    assert normalize_text("  شركت\u200c نمونه  ") == "شرکت نمونه"


def test_parenthesized_number_is_negative() -> None:
    assert to_decimal("(۱٬۲۳۴)") == Decimal("-1234")


def test_missing_number_is_none() -> None:
    assert to_decimal("-") is None


def test_jalali_conversion() -> None:
    assert jalali_to_gregorian("1403/01/01").isoformat() == "2024-03-20"
