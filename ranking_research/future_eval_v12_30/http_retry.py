"""Small, bounded Retry-After-aware retry for official read-only HTTP sources."""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime
import time
import urllib.error
import urllib.request


class ReadOnlyRateLimitedError(RuntimeError):
    """A bounded retry was exhausted; callers should stop that source."""

    def __init__(self, *, attempts: int, retry_after_seconds: float | None, retry_at_utc: str | None):
        super().__init__("HTTP_429_READ_ONLY_RETRY_EXHAUSTED")
        self.attempts = attempts
        self.retry_after_seconds = retry_after_seconds
        self.retry_at_utc = retry_at_utc


def _retry_after(exc: urllib.error.HTTPError) -> tuple[float, str]:
    value = exc.headers.get("Retry-After", "")
    now = dt.datetime.now(dt.timezone.utc)
    try:
        delay = max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=dt.timezone.utc)
            delay = max(0.0, (target - now).total_seconds())
        except (TypeError, ValueError, OverflowError):
            delay = 60.0
    return delay, (now + dt.timedelta(seconds=delay)).isoformat()


def open_readonly(request: urllib.request.Request, timeout: int = 35):
    """Return (response, attempts, retry_wait); retry 429 at most once.

    Retry-After is obeyed up to two minutes. Longer server delays are surfaced to
    the caller with a retry timestamp, without sleeping early or retrying.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout), 1, 0.0
    except urllib.error.HTTPError as exc:
        if exc.code != 429:
            raise
        delay, retry_at = _retry_after(exc)
        exc.close()
        if delay > 120:
            raise ReadOnlyRateLimitedError(attempts=1, retry_after_seconds=delay, retry_at_utc=retry_at)
        time.sleep(delay)
        try:
            return urllib.request.urlopen(request, timeout=timeout), 2, delay
        except urllib.error.HTTPError as retry_exc:
            if retry_exc.code != 429:
                raise
            next_delay, next_retry_at = _retry_after(retry_exc)
            retry_exc.close()
            raise ReadOnlyRateLimitedError(attempts=2, retry_after_seconds=next_delay,
                                           retry_at_utc=next_retry_at) from None
