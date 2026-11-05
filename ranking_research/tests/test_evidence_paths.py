from pathlib import Path
import json
import subprocess
import sys

import pytest

from qvt_backtest.evidence_paths import provenance_path, resolve_evidence_path
from ranking_research.tests.fixture_env import fixture_environment
from ranking_research.future_eval_v12_30.sales_lineage import encode_sales_lineage


def test_sales_lineage_marks_missing_period_and_rejects_nonfinite_facts():
    data = json.loads(encode_sales_lineage([], float("nan"), 0, "sales.parquet"),
                      parse_constant=lambda _: pytest.fail("nonstandard JSON number"))
    assert data["latest_period"] is None and data["received_at"] is None
    assert data["known_months"] == 0 and data["source"] == "sales.parquet"
    with pytest.raises(ValueError, match="Out of range"):
        encode_sales_lineage([{"value": float("nan")}], "1405-06", 1, "sales.parquet")


def test_provenance_path_keeps_external_identity(tmp_path):
    root = tmp_path / "project"
    assert provenance_path(root / "data/file.json", root) == "data/file.json"
    assert provenance_path(tmp_path / "restored/file.json", root) == (tmp_path / "restored/file.json").as_posix()


def test_research_reference_cache_missing_requires_explicit_connection(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """import runpy, sys
from pathlib import Path
sys.path.insert(0, str(Path('score_v2_research').resolve()))
fn = runpy.run_path('score_v2_research/v2lib.py')['load_reference_data']
fn.__globals__['CACHE'] = Path(sys.argv[1])
fn.__globals__['DSN'] = ''
try:
    fn()
except RuntimeError as error:
    assert str(error) == 'CDF_RESEARCH_DSN_REQUIRED_WHEN_REFERENCE_CACHE_MISSING'
else:
    raise AssertionError('missing research connection must fail closed')
"""
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tmp_path / 'cache')],
                            cwd=root, capture_output=True, text=True, timeout=30,
                            env=fixture_environment())
    assert result.returncode == 0, result.stderr


def test_rebases_windows_evidence_without_touching_old_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("CDF_EVIDENCE_OLD_ROOT", r"D:\Old\Project")
    monkeypatch.setenv("CDF_EVIDENCE_NEW_ROOT", str(tmp_path))
    assert resolve_evidence_path(r"d:\old\project\qvt_backtest\output\page.html") == tmp_path / "qvt_backtest/output/page.html"
    assert resolve_evidence_path(tmp_path / "fresh.json") == tmp_path / "fresh.json"
    with pytest.raises(ValueError, match="OUTSIDE_ORIGINAL_ROOT"):
        resolve_evidence_path(r"D:\Other\page.html")
    with pytest.raises(ValueError, match="TRAVERSAL"):
        resolve_evidence_path(r"D:\Old\Project\..\secret")


def test_partial_rebase_is_refused_and_default_is_unchanged(monkeypatch):
    monkeypatch.delenv("CDF_EVIDENCE_OLD_ROOT", raising=False)
    monkeypatch.delenv("CDF_EVIDENCE_NEW_ROOT", raising=False)
    assert resolve_evidence_path("relative/file") == Path("relative/file")
    monkeypatch.setenv("CDF_EVIDENCE_OLD_ROOT", r"D:\Old")
    with pytest.raises(ValueError, match="REQUIRES_BOTH"):
        resolve_evidence_path("relative/file")
