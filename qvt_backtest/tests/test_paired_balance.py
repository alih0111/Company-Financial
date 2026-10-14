import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dynamic_financial as D
import paired_balance as P
from test_dynamic_financial import fixture, record


def balance(equity=60, consolidated=False, date="1403/06/31"):
    caption = "صورت وضعیت مالی" + (" تلفیقی" if consolidated else "")
    return f'<h2>{caption}</h2><table><tr><th>شرح</th><th>{date}</th><th>1402/12/29</th></tr>' + "".join(
        f"<tr><td>{title}</td><td>{value}</td><td>{value}</td></tr>" for title, value in
        [("جمع داراییها", 100), ("جمع بدهیها", 40), ("جمع حقوق مالکانه", equity)]) + "</table>"


def test_parent_own_period_and_balance_reconcile_required():
    assert P.parse_balance(balance(), "2024-09-21")["statements"]["balance_sheet"]["total_equity"][1] == 60
    assert P.parse_balance(balance(equity=50), "2024-09-21") is None
    assert P.parse_balance(balance(consolidated=True), "2024-09-21") is None
    assert P.parse_balance(balance(date="1402/06/31"), "2024-09-21") is None
    assert P.parse_balance(balance() + balance(), "2024-09-21") is None


def test_paired_units_are_bound_to_serial_raw_export_and_publication(tmp_path, monkeypatch):
    archive = tmp_path / "history"
    store = archive / "dynamic_sources"
    (archive / "reports").mkdir(parents=True)
    store.mkdir()
    monkeypatch.setattr(D.H, "OUT", archive)
    monkeypatch.setattr(D, "STORE", store)
    native = store / "native.html"
    native.write_text(balance(), encoding="utf8")
    rec = {**record(), "company_id": "A", "symbol": "A", "title": "گزارش 6 ماهه", "observed_at": "2026-10-13T00:00:00Z",
           "sha256": hashlib.sha256(native.read_bytes()).hexdigest()}
    original = {**rec, "facts": [], "source": "https://excel.codal.ir/service/Excel/GetAll/SERIAL/0"}
    original_path = archive / "reports/A_1.json"
    original_path.write_text(json.dumps(original), encoding="utf8")
    page = store / "official.html"
    page.write_text('<p id="ctl00_pPriceNote">کلیه مبالغ درج شده به میلیون ریال می باشد</p>' + fixture(unit=""), encoding="utf8")
    pages = [{"source": "https://www.codal.ir/Reports/Decision.aspx?LetterSerial=SERIAL", "path": str(page),
              "sha256": hashlib.sha256(page.read_bytes()).hexdigest(), "role": "financial"}]
    proof = P.prove_unit(rec, original, pages)
    assert proof
    assert P.prove_unit(rec, {**original, "source": "https://excel.codal.ir/service/Excel/GetAll/OTHER/0"}, pages) is None
    manifest = store / "manifest.json"
    manifest.write_text(json.dumps({"tracing_no": "1", "pages": pages, "native_export": {
        "path": str(native), "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "original_record_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(), "unit_proof": proof}}), encoding="utf8")
    frozen = {**rec, "parser_version": "codal-dynamic-source-v6", "dynamic_manifest_path": str(manifest),
              "dynamic_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}
    facts = D.own_facts(D.verified_parsed(frozen))
    assert next(f["value"] for f in facts if f["metric_code"] == "total_equity") == 60e6
    with pytest.raises(ValueError, match="publication"):
        D.verified_parsed({**frozen, "published_at": "2024-10-20T00:00:00Z"})
    native.write_text(balance(equity=50), encoding="utf8")
    with pytest.raises(ValueError, match="source hash"):
        D.verified_parsed(frozen)
