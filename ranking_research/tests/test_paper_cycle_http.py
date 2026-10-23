import urllib.error
from unittest.mock import Mock, patch

import pytest

from ranking_research.future_eval_v12_30.http_retry import open_readonly, ReadOnlyRateLimitedError


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
