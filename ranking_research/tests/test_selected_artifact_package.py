import hashlib
import json
import zipfile

import pytest

from scripts.selected_artifact_package import make_package, restore_package, verify_package
from scripts.financial_evidence_inventory import inventory as financial_inventory


def inventory(root, data=b"fixture"):
    source = root / "inputs" / "sample.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    document = {"artifacts": [{"path": "inputs/sample.json", "present": True,
                                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
    path = root / "inventory.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return source, path


def test_roundtrip_and_no_overwrite(tmp_path):
    root = tmp_path / "source"; root.mkdir()
    _, inv = inventory(root)
    package = tmp_path / "backup.zip"
    make_package(root, inv, package)
    assert len(verify_package(package)) == 1
    destination = tmp_path / "restore"
    restore_package(package, destination)
    assert (destination / "inputs/sample.json").read_bytes() == b"fixture"
    with pytest.raises(FileExistsError):
        make_package(root, inv, package)
    with pytest.raises(FileExistsError):
        restore_package(package, destination)


def test_changed_input_cannot_be_published(tmp_path):
    root = tmp_path / "source"; root.mkdir()
    source, inv = inventory(root)
    source.write_bytes(b"changed")
    package = tmp_path / "backup.zip"
    with pytest.raises(ValueError, match="ARTIFACT_CHANGED"):
        make_package(root, inv, package)
    assert not package.exists()


def test_rejects_traversal_and_extra_members(tmp_path):
    root = tmp_path / "source"; root.mkdir()
    _, inv = inventory(root)
    data = json.loads(inv.read_text())
    data["artifacts"][0]["path"] = "../outside"
    inv.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="UNSAFE_ARTIFACT_PATH"):
        make_package(root, inv, tmp_path / "bad.zip")
    data["artifacts"][0]["path"] = "inputs/sample.json"
    inv.write_text(json.dumps(data))
    package = tmp_path / "extra.zip"
    make_package(root, inv, package)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("extra.txt", b"unexpected")
    with pytest.raises(ValueError, match="PACKAGE_MEMBERS_INVALID"):
        verify_package(package)


def test_financial_inventory_includes_immutable_dynamic_and_legacy_evidence(tmp_path):
    root = tmp_path / "source"; root.mkdir()
    selected_input, selected = inventory(root)
    owner = root / "ranking_research/output/owner_current_market_2026-10-15"
    owner.mkdir(parents=True)
    features = root / "financial/owner_features.csv"; features.parent.mkdir()
    features.write_bytes(b"features")
    (owner / "registration.json").write_text(json.dumps({"financial_path": str(features), "source_manifest": {}}), encoding="utf-8")
    page = root / "dynamic/page.html"; page.parent.mkdir(); page.write_bytes(b"page")
    manifest = root / "dynamic/manifest.json"
    manifest.write_text(json.dumps({"pages": [{"path": str(page), "sha256": hashlib.sha256(b"page").hexdigest()}]}), encoding="utf-8")
    reports = [{"dynamic_manifest_path": str(manifest), "dynamic_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
               {"symbol": "TEST", "tracing_no": "1"}]
    (features.parent / "input_reports.json").write_text(json.dumps(reports), encoding="utf-8")
    legacy = root / "provenance_v1/output/coverage_verified/raw/TEST_1.html"
    legacy.parent.mkdir(parents=True); legacy.write_bytes(b"legacy")
    result = financial_inventory(root, selected)
    names = {item["path"] for item in result["artifacts"]}
    assert {"dynamic/page.html", "dynamic/manifest.json", "financial/owner_features.csv",
            "provenance_v1/output/coverage_verified/raw/TEST_1.html"} <= names
    page.write_bytes(b"changed")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        financial_inventory(root, selected)
    page.write_bytes(b"page")
    selected_input.write_bytes(b"changed selected input")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        financial_inventory(root, selected)
