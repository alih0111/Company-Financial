import sys
from pathlib import Path
import json
import hashlib
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dynamic_financial import parsed_page, own_facts
from codal_publish_resolver import parse_persian_datetime


def test_auditor_landing_page_is_only_navigation_financial_sheets_still_verified(tmp_path, monkeypatch):
    import dynamic_financial as D
    monkeypatch.setattr(D, "STORE", tmp_path)
    nav = tmp_path / "landing.html"
    nav.write_text('<select id="ddlTable"><option value="1">صورت سود و زیان</select>', encoding="utf8")
    financial = tmp_path / "parent.html"
    financial.write_text(fixture(), encoding="utf8")
    pages = [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "role": role}
             for p, role in [(nav, "navigation_only"), (financial, "financial")]]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tracing_no": "1", "pages": pages}), encoding="utf8")
    rec = {**record(), "parser_version": "codal-dynamic-source-v4", "dynamic_manifest_path": str(manifest),
           "dynamic_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
    assert own_facts(D.verified_parsed(rec))[0]["value"] == 20e6
    with pytest.raises(ValueError, match="publication"):
        D.verified_parsed({**rec, "published_at": "2024-10-20T00:00:00Z"})
    pages[1]["role"] = "navigation_only"
    manifest.write_text(json.dumps({"tracing_no": "1", "pages": pages}), encoding="utf8")
    rec["dynamic_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="financial_datasource_marked"):
        D.verified_parsed(rec)


def test_ambiguous_income_sheet_does_not_remove_verified_cash_flow(tmp_path, monkeypatch):
    import dynamic_financial as D
    monkeypatch.setattr(D, "STORE", tmp_path)
    data = json.loads(fixture().removeprefix("var datasource = ").removesuffix(";"))
    cell = dict(data["sheets"][0]["tables"][0]["cells"][3])
    cell["value"] = "21"
    data["sheets"][0]["tables"][0]["cells"].append(cell)
    rejected = tmp_path / "ambiguous.html"
    rejected.write_text("var datasource = " + json.dumps(data) + ";", encoding="utf8")
    cash = json.loads(fixture().removeprefix("var datasource = ").removesuffix(";"))
    table = cash["sheets"][0]["tables"][0]
    table["title_Fa"] = "صورت جریان های نقدی"
    table["cells"][2]["value"] = D.H.P.ROW_TITLES["cash_flow", "operating_cash_flow"]
    accepted = tmp_path / "cash.html"
    accepted.write_text("var datasource = " + json.dumps(cash) + ";", encoding="utf8")
    pages = [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "role": role, "reason": reason}
             for p, role, reason in [(rejected, "rejected_financial", "duplicate_dynamic_cell"), (accepted, "financial", None)]]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tracing_no": "1", "pages": pages}), encoding="utf8")
    rec = {**record(), "parser_version": "codal-dynamic-source-v5", "dynamic_manifest_path": str(manifest),
           "dynamic_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
    facts = own_facts(D.verified_parsed(rec))
    assert len(facts) == 1 and facts[0]["metric_code"] == "operating_cash_flow"
    # A rejected sheet cannot conceal a different publication date.
    with pytest.raises(ValueError, match="publication"):
        D.verified_parsed({**rec, "published_at": "2024-10-20T00:00:00Z"})


def fixture(consolidated=False, unit="کلیه مبالغ به میلیون ریال است"):
    cells = [{"rowSequence": 1, "columnSequence": col, "cellGroupName": "Header", "isVisible": True, "periodEndToDate": date}
             for col, date in [(2, "1403/06/31"), (3, "1402/06/31")]]
    cells += [{"rowSequence": 4, "columnSequence": 1, "cellGroupName": "Body", "isVisible": True, "value": "سود(زیان) خالص"},
              {"rowSequence": 4, "columnSequence": 2, "cellGroupName": "Body", "isVisible": True, "value": "20", "periodEndToDate": "1403/06/31"},
              {"rowSequence": 4, "columnSequence": 3, "cellGroupName": "Body", "isVisible": True, "value": "999", "periodEndToDate": "1402/06/31"}]
    doc = {"tracingNo": 1, "publishDateTime": "1403/07/30 22:38:41", "periodEndToDate": "1403/06/31", "isConsolidated": consolidated,
           "sheets": [{"tables": [{"title_Fa": "صورت سود و زیان", "description": unit, "cells": cells}]}]}
    return "var datasource = " + json.dumps(doc) + ";"


def record():
    return {"tracing_no": "1", "published_at": parse_persian_datetime("1403/07/30 22:38:41").isoformat(), "period_end": "2024-09-21"}


def test_dynamic_parent_units_identity_and_own_column():
    facts = own_facts(parsed_page(fixture(), record()))
    assert len(facts) == 1 and facts[0]["value"] == 20e6 and facts[0]["period_order"] == 1
    assert own_facts(parsed_page(fixture(consolidated=True), record())) == []
    assert own_facts(parsed_page(fixture(unit=""), record())) == []
    with pytest.raises(ValueError, match="identity"):
        parsed_page(fixture(), {**record(), "tracing_no": "other"})
    with pytest.raises(ValueError, match="publication"):
        parsed_page(fixture(), {**record(), "published_at": "2024-10-20T00:00:00Z"})


def test_report_unit_and_explicit_parent_sheet_within_consolidated_report():
    html = fixture(consolidated=True, unit="")
    data = json.loads(html.removeprefix("var datasource = ").removesuffix(";"))
    data["sheets"][0].update({"code": 1, "title_Fa": "صورت سود و زیان"})
    prefix = '<p id="ctl00_pPriceNote">کلیه مبالغ درج شده به میلیون ریال می باشد</p><select id="ctl00_ddlTable"><option value="13">صورت سود و زیان تلفیقی</option><option value="1">صورت سود و زیان</option></select>'
    page = prefix + "var datasource = " + json.dumps(data) + ";"
    assert own_facts(parsed_page(page, record()))[0]["value"] == 20e6
    assert own_facts(parsed_page(page, {**record(), "parser_version": "codal-dynamic-source-v1"})) == []


def test_new_dropdown_with_unclosed_options_does_not_mix_parent_and_group():
    data = json.loads(fixture(consolidated=True, unit="").removeprefix("var datasource = ").removesuffix(";"))
    data["sheets"][0].update({"code": 1, "title_Fa": "صورت سود و زیان"})
    prefix = '<p id="ctl00_pPriceNote">کلیه مبالغ درج شده به میلیون ریال می باشد</p><select id="ddlTable"><option value="13">صورت سود و زیان تلفیقی<option value="1">صورت سود و زیان<option value="0">صورت وضعیت مالی</select>'
    page = prefix + "var datasource = " + json.dumps(data) + ";"
    assert own_facts(parsed_page(page, record()))[0]["value"] == 20e6
    assert own_facts(parsed_page(page, {**record(), "parser_version": "codal-dynamic-source-v2"})) == []
