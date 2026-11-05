import urllib.error
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ranking_research.future_eval_v12_30.http_retry import open_readonly, ReadOnlyRateLimitedError
from ranking_research.tests.fixture_env import fixture_environment


def run_fixture(command, env):
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    if result.returncode:
        # A child can echo anything it receives. Do not include stdout, stderr,
        # argv or environment in the failure shown by pytest.
        raise AssertionError(f"fixture subprocess failed (exit {result.returncode})")
    return result.stdout


def test_fixture_failure_does_not_report_a_synthetic_secret():
    fake_secret = "synthetic-fixture-secret-490731"
    env = fixture_environment()
    env["SYNTHETIC_SECRET"] = fake_secret
    command = [sys.executable, "-c", "import os,sys; print(os.environ['SYNTHETIC_SECRET'], file=sys.stderr); sys.exit(7)"]
    with pytest.raises(AssertionError) as caught:
        run_fixture(command, env)
    assert str(caught.value) == "fixture subprocess failed (exit 7)"
    assert fake_secret not in str(caught.value)


def http_429(retry_after="2"):
    return urllib.error.HTTPError("https://example.invalid", 429, "too many", {"Retry-After": retry_after}, None)


def test_429_honors_retry_after_and_retries_once():
    response = Mock()
    request = Mock()
    with patch("ranking_research.future_eval_v12_30.http_retry.urllib.request.urlopen",
               side_effect=[http_429("2"), response]) as urlopen, \
            patch("ranking_research.future_eval_v12_30.http_retry.time.sleep") as sleep:
        actual, attempts, delay = open_readonly(request)
    assert actual is response
    assert attempts == 2
    assert delay == 2
    sleep.assert_called_once_with(2)
    assert urlopen.call_count == 2


def test_429_does_not_retry_repeatedly():
    request = Mock()
    with patch("ranking_research.future_eval_v12_30.http_retry.urllib.request.urlopen",
               side_effect=[http_429("0"), http_429("0")]) as urlopen, \
            patch("ranking_research.future_eval_v12_30.http_retry.time.sleep"):
        with pytest.raises(ReadOnlyRateLimitedError) as caught:
            open_readonly(request)
    assert urlopen.call_count == 2
    assert caught.value.attempts == 2
    assert caught.value.retry_after_seconds == 0


def test_long_retry_after_stops_without_early_retry():
    request = Mock()
    with patch("ranking_research.future_eval_v12_30.http_retry.urllib.request.urlopen",
               side_effect=http_429("121")) as urlopen, \
            patch("ranking_research.future_eval_v12_30.http_retry.time.sleep") as sleep:
        with pytest.raises(ReadOnlyRateLimitedError) as caught:
            open_readonly(request)
    urlopen.assert_called_once_with(request, timeout=35)
    sleep.assert_not_called()
    assert caught.value.attempts == 1
    assert caught.value.retry_after_seconds == 121
    assert caught.value.retry_at_utc


@pytest.mark.parametrize("code", [502, 503, 504])
def test_transient_gateway_error_retried_once(code):
    error = urllib.error.HTTPError("https://example.invalid", code, "unavailable", {}, None)
    response = Mock()
    with patch("ranking_research.future_eval_v12_30.http_retry.urllib.request.urlopen", side_effect=[error, response]) as urlopen, \
            patch("ranking_research.future_eval_v12_30.http_retry.time.sleep") as sleep:
        result, attempts, delay = open_readonly(Mock())
    assert (result, attempts, delay) == (response, 2, 2.0)
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(2.0)


def test_repeated_gateway_error_is_not_hidden():
    errors = [urllib.error.HTTPError("https://example.invalid", 502, "unavailable", {}, None) for _ in range(2)]
    with patch("ranking_research.future_eval_v12_30.http_retry.urllib.request.urlopen", side_effect=errors) as urlopen, \
            patch("ranking_research.future_eval_v12_30.http_retry.time.sleep"):
        with pytest.raises(urllib.error.HTTPError) as caught:
            open_readonly(Mock())
    assert caught.value.code == 502
    assert urlopen.call_count == 2


def test_paper_cycle_interpreter_defaults_to_current_and_allows_override(tmp_path):
    env = fixture_environment()
    command = [sys.executable, "-c", "from ranking_research.future_eval_v12_30.paper_cycle import PYTHON; print(PYTHON)"]
    default = run_fixture(command, env).strip()
    assert Path(default).resolve() == Path(sys.executable).resolve()
    configured = tmp_path / "custom-python"
    env["CDF_PAPER_PYTHON"] = str(configured)
    assert Path(run_fixture(command, env).strip()) == configured


def test_factor_builder_accepts_relocated_owner_inputs(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "registration.json").write_text(json.dumps({"financial_path": "D:/old-device/input_reports.json", "share_snapshot_path": "D:/old-device/shares.json"}), encoding="utf-8")
    inputs = tmp_path / "financial"
    env = fixture_environment()
    shares = tmp_path / "shares.json"
    env.update(V1237_OWNER_PACK=str(owner), V1237_OWNER_INPUTS=str(inputs), V1237_SHARE_PATH=str(shares))
    command = [sys.executable, "-c", "from ranking_research.future_eval_v12_30.build_codal_factor_inputs import BASE_REPORTS; print(BASE_REPORTS)"]
    assert Path(run_fixture(command, env).strip()) == inputs / "input_reports.json"
    command = [sys.executable, "-c", "from ranking_research.future_eval_v12_30.rebuild_latest_supported_v12_37 import OWNER_INPUTS,SHARE_PATH,OWNER_FEATURES_PATH; print(OWNER_INPUTS); print(SHARE_PATH); print(OWNER_FEATURES_PATH)"]
    actual = run_fixture(command, env).splitlines()
    assert list(map(Path, actual)) == [inputs, shares, inputs / "input_reports.json"]
