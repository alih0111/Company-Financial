"""Phase-3 tests: Codal versioning/raw, retry manifest, conflict prevention, modes."""

from __future__ import annotations

import json
import os
import pathlib
import re
import uuid

import pytest

from canonical_ingest import config
from canonical_ingest.config import IngestionMode
from canonical_ingest.db import transaction
from canonical_ingest.service import dual_write_report

RESOLVABLE = "آردینه"
# unique per test run so version/raw assertions are deterministic (additive rows)
SELFTEST_SRID = f"codal:selftest:{uuid.uuid4().hex}"
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "canonical_ingest"


def _configured() -> bool:
    try:
        config._load_env_files()
        return bool(config.canonical_dsn())
    except Exception:
        return False


def _scalar(sql, params=()):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


# ---- modes -----------------------------------------------------------------
def test_writes_are_opt_in(monkeypatch):
    monkeypatch.delenv("CDF_INGESTION_MODE", raising=False)
    assert config.load_mode() == IngestionMode.LEGACY_ONLY
    monkeypatch.setenv("CDF_INGESTION_MODE", "canonical_only")
    assert config.load_mode() == IngestionMode.CANONICAL_ONLY  # exists but not default


# ---- static conflict prevention -------------------------------------------
def test_canonical_ingest_is_the_only_py2_canonical_writer():
    # canonical_ingest must contain the canonical INSERTs ...
    writer = (_SRC / "writer.py").read_text(encoding="utf-8")
    assert "INSERT INTO ingestion.reports" in writer
    assert "INSERT INTO fundamentals.monthly_activities" in writer
    assert "INSERT INTO market.price_observations" in writer
    # ... and must never write legacy heuristics.
    forbidden = re.compile(r"product[123]|npunitratio|opk|opamt", re.IGNORECASE)
    for path in _SRC.glob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name


def test_legacy_scripts_delegate_to_canonical_hook():
    py = _SRC.parents[2] / "py"
    for name, marker in (("brs_prices.py", "dual_write_market_rows"),
                         ("MianSql2.py", "dual_write_monthly_values"),
                         ("MianSql.py", "dual_write_financial_by_key")):
        text = (py / name).read_text(encoding="utf-8")
        assert "canonical_hook" in text and marker in text, name


# ---- retry manifest --------------------------------------------------------
def test_retry_record_writes_manifest(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(_SRC.parents[2] / "py"))
    import canonical_hook  # noqa: E402
    monkeypatch.setattr(canonical_hook, "_OUT_DIR", tmp_path)
    canonical_hook._retry_record("market_price", {"company_id": "x"}, "boom")
    data = (tmp_path / "canonical_retry_manifest.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(data)["status"] == "pending"


# ---- Codal version/raw semantics (DB) -------------------------------------
pytestmark_db = pytest.mark.skipif(not _configured(), reason="canonical DSN not configured")


@pytestmark_db
def test_codal_source_report_id_and_raw_dedup_and_versioning():
    kw = dict(name=RESOLVABLE, source="codal", source_report_id=SELFTEST_SRID,
              title="selftest", payload_type="html", parser_name="phase3_test", parser_version="v1")
    v1 = dual_write_report(**kw, content_text="<html>v1</html>")
    v1b = dual_write_report(**kw, content_text="<html>v1</html>")   # identical -> dedup
    v2 = dual_write_report(**kw, content_text="<html>v2</html>")   # changed -> new version
    assert v1.status == "written"
    assert v1b.inserted == 0
    assert v2.inserted >= 1

    srid = _scalar("SELECT source_report_id FROM ingestion.reports WHERE source_report_id=%s", (SELFTEST_SRID,))
    assert srid == SELFTEST_SRID
    versions = _scalar("SELECT count(*) FROM ingestion.report_versions rv JOIN ingestion.reports r ON r.id=rv.report_id "
                       "WHERE r.source_report_id=%s", (SELFTEST_SRID,))
    raw = _scalar("SELECT count(*) FROM raw.report_payloads rp JOIN ingestion.report_versions rv ON rv.id=rp.report_version_id "
                  "JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (SELFTEST_SRID,))
    assert versions == 2  # v1 + v2, identical re-fetch created none
    assert raw == 2       # raw dedup per (version, type, hash)


@pytestmark_db
def test_parser_rerun_new_parse_run_without_new_version():
    kw = dict(name=RESOLVABLE, source="codal", source_report_id=SELFTEST_SRID,
              title="selftest", content_text="<html>v2</html>", payload_type="html")
    dual_write_report(**kw, parser_name="phase3_test", parser_version="v2")  # rerun, same content
    versions = _scalar("SELECT count(*) FROM ingestion.report_versions rv JOIN ingestion.reports r ON r.id=rv.report_id "
                       "WHERE r.source_report_id=%s", (SELFTEST_SRID,))
    runs = _scalar("SELECT count(*) FROM ingestion.parse_runs pr JOIN ingestion.report_versions rv ON rv.id=pr.report_version_id "
                   "JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (SELFTEST_SRID,))
    assert versions == 2  # no new source version
    assert runs >= 2      # new parse_run recorded
