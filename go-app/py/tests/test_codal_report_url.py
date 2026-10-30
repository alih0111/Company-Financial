"""Codal report urls arrive site-relative; urllib needs them absolute."""
import canonical_hook


def test_relative_report_url_is_made_absolute():
    assert (canonical_hook._absolute_codal_url("/Reports/Decision.aspx?LetterSerial=x&let=6")
            == "https://www.codal.ir/Reports/Decision.aspx?LetterSerial=x&let=6")


def test_protocol_relative_and_absolute_urls_are_kept():
    assert canonical_hook._absolute_codal_url("//www.codal.ir/x") == "https://www.codal.ir/x"
    assert canonical_hook._absolute_codal_url("https://www.codal.ir/x") == "https://www.codal.ir/x"
    assert canonical_hook._absolute_codal_url("Reports/x") == "https://www.codal.ir/Reports/x"


def test_missing_url_stays_none():
    assert canonical_hook._absolute_codal_url(None) is None
    assert canonical_hook._absolute_codal_url("") is None
    assert canonical_hook._absolute_codal_url("   ") is None
