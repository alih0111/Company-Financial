"""Phase-7 tests: py2 conflicting-schema guard + Codal supersession/raw (DB)."""

from __future__ import annotations

import uuid
import warnings

import pytest

from canonical_ingest import config
from canonical_ingest.db import transaction
from canonical_ingest.service import dual_write_report

RESOLVABLE = "آردینه"


def _configured() -> bool:
    try:
        config._load_env_files()
        return bool(config.canonical_dsn())
    except Exception:
        return False


def test_conflicting_py2_writer_is_deprecated():
    # static guard: the conflicting py2 writer must be marked non-canonical.
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1] / "src" / "codal_ingestor" / "repository.py"
    src = repo.read_text(encoding="utf-8")
    assert "DeprecationWarning" in src
    assert "NON-CANONICAL" in src


def _scalar(sql, params=()):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


@pytest.mark.skipif(not _configured(), reason="canonical DSN not configured")
def test_codal_supersession_and_raw_dedup():
    s1 = f"codal:selftest:sup1-{uuid.uuid4().hex}"
    s2 = f"codal:selftest:sup2-{uuid.uuid4().hex}"
    a = dual_write_report(name=RESOLVABLE, source="codal", source_report_id=s1, title="t",
                          content_text="<html>a</html>", payload_type="html", parser_name="p7", parser_version="v1")
    b = dual_write_report(name=RESOLVABLE, source="codal", source_report_id=s1, title="t",
                          content_text="<html>a</html>", payload_type="html", parser_name="p7", parser_version="v1")
    c = dual_write_report(name=RESOLVABLE, source="codal", source_report_id=s1, title="t",
                          content_text="<html>b</html>", payload_type="html", parser_name="p7", parser_version="v1")
    d = dual_write_report(name=RESOLVABLE, source="codal", source_report_id=s2, title="corrected",
                          content_text="<html>corrected</html>", payload_type="html", parser_name="p7",
                          parser_version="v1", supersedes_source_report_id=s1)
    raw = _scalar("SELECT count(*) FROM raw.report_payloads rp JOIN ingestion.report_versions rv ON rv.id=rp.report_version_id "
                  "JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (s1,))
    vers = _scalar("SELECT count(*) FROM ingestion.report_versions rv JOIN ingestion.reports r ON r.id=rv.report_id "
                   "WHERE r.source_report_id=%s", (s1,))
    linked = _scalar("""SELECT (r2.supersedes_report_id = r1.id) FROM ingestion.reports r1, ingestion.reports r2
                        WHERE r1.source_report_id=%s AND r2.source_report_id=%s""", (s1, s2))
    assert a.status == "written"
    assert b.inserted == 0          # identical content -> no new version
    assert c.inserted >= 1          # changed content -> new version
    assert vers == 2
    assert raw == 2                 # raw dedup per version
    assert d.inserted >= 1
    assert linked is True           # supersession lineage
