"""Local-only HTTP/Playwright fixture for Codal transport and manual CAPTCHA IPC."""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PY_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PY_DIR))

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
    "m2kAAAAASUVORK5CYII="
)


class FixtureHandler(BaseHTTPRequestHandler):
    counts: dict[str, int] = {}
    observed_cookies: list[str] = []

    def log_message(self, *_args):
        pass

    def _count(self):
        self.counts[self.path] = self.counts.get(self.path, 0) + 1
        self.observed_cookies.append(self.headers.get("Cookie", ""))

    def _send(self, status, content_type, body, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._count()
        if self.path == "/good":
            self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            return
        if self.path == "/browser-ok":
            if "sid=fixture" in self.headers.get("Cookie", ""):
                self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            else:
                self._send(429, "text/html", b"limited", {"Set-Cookie": "sid=fixture; Path=/", "Retry-After": "0"})
            return
        if self.path == "/headed-429":
            if "solved=yes" in self.headers.get("Cookie", ""):
                self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            else:
                self._send(429, "text/html", b"limited", {"Retry-After": "0"})
            return
        if self.path == "/recovery-page":
            self._send(200, "text/html", b"<html><body>Codal report list verification fixture</body></html>",
                       {"Set-Cookie": "solved=yes; Path=/"})
            return
        if self.path == "/html-200":
            self._send(200, "text/html", b"<html><body>temporary verification error</body></html>")
            return
        if self.path == "/report-list":
            self._send(200, "text/html", b"<html><body><form><input name='search' placeholder='Search reports'></form><img alt='Codal logo' src='/logo.png'><img alt='PDF' src='/pdf.png'></body></html>")
            return
        if self.path == "/xml-then-json":
            request_count = self.counts[self.path]
            if request_count == 1:
                self._send(429, "text/html", b"limited", {"Retry-After": "0"})
            elif request_count == 2:
                self._send(200, "application/xml", b"<?xml version='1.0'?><error>temporary</error>")
            else:
                self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            return
        if self.path == "/xml-after-429":
            request_count = self.counts[self.path]
            if request_count == 1:
                self._send(429, "text/html", b"limited", {"Retry-After": "0"})
            elif request_count == 2:
                self._send(200, "application/xml", b"<?xml version='1.0'?><error>still limited</error>")
            else:
                self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            return
        if self.path == "/rate-only":
            self._send(429, "text/html", b"rate limited", {"Retry-After": "0"})
            return
        if self.path == "/challenge":
            if "solved=yes" in self.headers.get("Cookie", ""):
                self._send(200, "application/json", b'{"Letters":[],"Total":0}')
            elif "sid=fixture" in self.headers.get("Cookie", ""):
                page = ("<html><body><p>Security code</p><form method='post' action='/answer'>"
                        "<img id='captcha' alt='verification image' src='data:image/png;base64," + base64.b64encode(_PNG).decode() + "'>"
                        "<input type='text' name='code'><button type='submit'>Continue</button>"
                        "<button type='button' title='Refresh image' onclick=\"document.querySelector('#captcha').dataset.version='new'\">Refresh</button>"
                        "</form></body></html>").encode()
                self._send(200, "text/html", page)
            else:
                self._send(429, "text/html", b"limited", {"Set-Cookie": "sid=fixture; Path=/", "Retry-After": "0"})
            return
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        self._count()
        size = int(self.headers.get("Content-Length", "0"))
        answer = self.rfile.read(size).decode("ascii", "replace")
        if self.path == "/answer" and "sid=fixture" in self.headers.get("Cookie", "") and "code=1234" in answer:
            self._send(200, "text/html", b"<html><body>Accepted</body></html>", {"Set-Cookie": "solved=yes; Path=/"})
            return
        self._send(200, "text/html", b"<html><body>Security code incorrect<img src='data:image/png;base64," + base64.b64encode(_PNG) + b"'><form method='post' action='/answer'><input name='code'><button type='submit'>Continue</button><button type='button' title='Refresh image'>Refresh</button></form></body></html>")


@pytest.fixture
def fixture_server():
    FixtureHandler.counts = {}
    FixtureHandler.observed_cookies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _fresh_transport(monkeypatch, tmp_path):
    pytest.importorskip("playwright.sync_api")
    import MianSql
    import codal_transport

    if not Path(MianSql.CHROMIUM_BINARY).is_file():
        pytest.skip("configured Chromium binary is not installed")
    root = tmp_path / ("a" * 32)
    root.mkdir(parents=True)
    monkeypatch.setenv("CODAL_JOB_DIR", str(root))
    monkeypatch.setenv("CODAL_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "1")
    monkeypatch.setenv("CHROMIUM_BINARY", MianSql.CHROMIUM_BINARY)
    codal_transport.close_current()
    return codal_transport, root


def test_healthy_http_uses_no_browser_and_caches_only_valid_feed(fixture_server, monkeypatch, tmp_path):
    transport, _root = _fresh_transport(monkeypatch, tmp_path)
    try:
        client = transport.current()
        data, content_type, status = client.get(fixture_server + "/good", expect_json=True)
        assert status == 200 and content_type == "application/json"
        assert client._context is None
        assert client.get(fixture_server + "/good", expect_json=True)[0] == data
        assert FixtureHandler.counts["/good"] == 1
    finally:
        transport.close_current()


def test_http_429_falls_back_to_browser_and_keeps_cookie_session(fixture_server, monkeypatch, tmp_path):
    transport, _root = _fresh_transport(monkeypatch, tmp_path)
    try:
        data, _content_type, status = transport.current().get(fixture_server + "/browser-ok", expect_json=True)
        assert status == 200
        assert json.loads(data)["Letters"] == []
        assert any("sid=fixture" in value for value in FixtureHandler.observed_cookies)
    finally:
        transport.close_current()


def test_manual_captcha_image_answer_and_same_browser_context(fixture_server, monkeypatch, tmp_path):
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    failure = []

    def collect():
        try:
            data, _content_type, _status = transport.current().get(fixture_server + "/challenge", expect_json=True)
            assert json.loads(data)["Total"] == 0
        except Exception as exc:  # forwarded to the test thread
            failure.append(exc)
        finally:
            transport.close_current()

    worker = threading.Thread(target=collect)
    worker.start()
    challenge_path = root / "challenge.json"
    deadline = time.time() + 45
    while time.time() < deadline and not challenge_path.exists():
        time.sleep(0.05)
    status_path = root / "status.json"
    status_text = status_path.read_text(encoding="utf-8") if status_path.exists() else "no status snapshot"
    assert challenge_path.exists(), f"worker did not publish the real challenge screenshot: {failure!r}; status={status_text}"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    assert challenge["kind"] == "text"
    png = base64.b64decode(challenge["image_data_url"].split(",", 1)[1])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert challenge["can_refresh"] is True
    refresh = {"type":"refresh","job_id":root.name,"challenge_id":challenge["challenge_id"],"command_id":"fixture-refresh"}
    (root / "commands" / "fixture-refresh.json").write_text(json.dumps(refresh),encoding="utf-8")
    deadline = time.time() + 5
    second = challenge
    while time.time() < deadline:
        second = json.loads(challenge_path.read_text(encoding="utf-8"))
        if second["challenge_id"] != challenge["challenge_id"]: break
        time.sleep(0.05)
    assert second["challenge_id"] != challenge["challenge_id"]
    stale = {"type":"answer","job_id":root.name,"challenge_id":challenge["challenge_id"],"command_id":"fixture-stale","answer":"bad"}
    (root / "commands" / "fixture-stale.json").write_text(json.dumps(stale),encoding="utf-8")
    time.sleep(0.3)
    assert json.loads(challenge_path.read_text(encoding="utf-8"))["challenge_id"] == second["challenge_id"]
    wrong = {"type":"answer","job_id":root.name,"challenge_id":second["challenge_id"],"command_id":"fixture-wrong","answer":"bad"}
    (root / "commands" / "fixture-wrong.json").write_text(json.dumps(wrong),encoding="utf-8")
    deadline = time.time() + 5
    third = second
    while time.time() < deadline:
        third = json.loads(challenge_path.read_text(encoding="utf-8"))
        if third["challenge_id"] != second["challenge_id"]: break
        time.sleep(0.05)
    assert third["challenge_id"] != second["challenge_id"] and third["attempt"] == 2
    command = {"type": "answer", "job_id": root.name, "challenge_id": third["challenge_id"],
               "command_id": "fixture-answer", "answer": "1234"}
    (root / "commands" / "fixture-answer.json").write_text(json.dumps(command), encoding="utf-8")
    worker.join(timeout=25)
    assert not worker.is_alive(), "worker failed to resume after the answer"
    assert not failure, failure
    assert FixtureHandler.counts["/answer"] == 2
    assert any("solved=yes" in value for value in FixtureHandler.observed_cookies)


def test_html_200_is_not_treated_as_empty_feed(fixture_server, monkeypatch, tmp_path):
    transport, _root = _fresh_transport(monkeypatch, tmp_path)
    try:
        data, _content_type, status = transport.current().get(fixture_server + "/html-200", expect_json=True)
        assert status == 200
        assert not transport.current()._valid_json_feed(data)
        assert fixture_server + "/html-200" not in transport.current()._cache
    finally:
        transport.close_current()


def test_report_list_search_input_and_icons_are_not_a_captcha(fixture_server, monkeypatch, tmp_path):
    transport, _root = _fresh_transport(monkeypatch, tmp_path)
    try:
        client = transport.current()
        client._launch_browser()
        client._page.goto(fixture_server + "/report-list", wait_until="domcontentloaded")
        assert not client._looks_like_challenge(client._page, "text/html")
    finally:
        transport.close_current()


def test_xml_rate_limit_pauses_and_retries_without_captcha(fixture_server, monkeypatch, tmp_path):
    """Codal refuses with an XML envelope, not a security code: pause, then retry once."""
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    monkeypatch.setenv("CODAL_RATE_LIMIT_PAUSE_SECONDS", "0.2")
    failures = []

    def collect():
        try:
            data, _content_type, status = transport.current().get(
                fixture_server + "/xml-then-json", timeout=10, expect_json=True
            )
            assert status == 200
            assert json.loads(data)["Total"] == 0
        except Exception as exc:
            failures.append(exc)
        finally:
            transport.close_current()

    worker = threading.Thread(target=collect, daemon=True)
    worker.start()
    worker.join(timeout=40)
    assert not worker.is_alive(), f"worker did not recover from the XML rate limit: {failures!r}"
    assert not failures, failures
    assert FixtureHandler.counts["/xml-then-json"] == 3
    assert not (root / "challenge.json").exists(), "a rate-limit XML must not ask for a security code"


def test_headed_429_opens_codal_recovery_page_and_waits_for_operator(fixture_server, monkeypatch, tmp_path):
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    failures = []

    def collect():
        try:
            data, _content_type, status = transport.current().get(
                fixture_server + "/headed-429", timeout=10, expect_json=True,
                recovery_url=fixture_server + "/recovery-page",
            )
            assert status == 200 and json.loads(data)["Total"] == 0
        except Exception as exc:
            failures.append(exc)
        finally:
            transport.close_current()

    worker = threading.Thread(target=collect, daemon=True)
    worker.start()
    challenge_path = root / "challenge.json"
    deadline = time.time() + 30
    while time.time() < deadline and not challenge_path.exists():
        time.sleep(0.05)
    assert challenge_path.exists(), "headed 429 did not open the interactive recovery page"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    assert challenge["kind"] == "inspection" and challenge["can_manual_resume"] is True
    # No security modal was detected on the recovery page, so the panel asks the
    # operator to confirm instead of offering a text field.
    assert "کد امنیتی" in challenge["message"]
    resume = {"type": "resume", "job_id": root.name,
              "challenge_id": challenge["challenge_id"], "command_id": "headed-429-resume"}
    (root / "commands" / "headed-429-resume.json").write_text(json.dumps(resume), encoding="utf-8")
    worker.join(timeout=15)
    assert not worker.is_alive(), f"worker did not retry after browser verification: {failures!r}"
    assert not failures, failures
    assert FixtureHandler.counts["/recovery-page"] == 1
    assert any("solved=yes" in value for value in FixtureHandler.observed_cookies)


def test_after_operator_confirms_plain_429_xml_retries_without_second_prompt(fixture_server, monkeypatch, tmp_path):
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    monkeypatch.setenv("CODAL_BROWSER_RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("CODAL_RATE_LIMIT_PAUSE_SECONDS", "0.2")
    failures = []

    def collect():
        try:
            data, _content_type, status = transport.current().get(
                fixture_server + "/xml-after-429", timeout=10, expect_json=True,
                recovery_url=fixture_server + "/recovery-page",
            )
            assert status == 200 and json.loads(data)["Total"] == 0
        except Exception as exc:
            failures.append(exc)
        finally:
            transport.close_current()

    worker = threading.Thread(target=collect, daemon=True)
    worker.start()
    challenge_path = root / "challenge.json"
    deadline = time.time() + 30
    while time.time() < deadline and not challenge_path.exists():
        time.sleep(0.05)
    assert challenge_path.exists(), "initial 429 did not pause for browser inspection"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    resume = {"type": "resume", "job_id": root.name,
              "challenge_id": challenge["challenge_id"], "command_id": "xml-after-429-resume"}
    (root / "commands" / "xml-after-429-resume.json").write_text(json.dumps(resume), encoding="utf-8")
    worker.join(timeout=20)
    assert not worker.is_alive(), f"worker stayed paused after a non-CAPTCHA XML response: {failures!r}"
    assert not failures, failures
    assert FixtureHandler.counts["/xml-after-429"] == 3
    final_status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert final_status["state"] == "running_browser" and final_status.get("challenge") is None


def test_visible_mode_policy(monkeypatch):
    """Watching is on for manual runs and off for the unattended automatic one."""
    import codal_transport as ct

    transport = ct.CodalTransport.__new__(ct.CodalTransport)
    transport.channel = object()  # any interactive job
    monkeypatch.delenv("CODAL_VISIBLE_BROWSER", raising=False)
    monkeypatch.delenv("CODAL_VISIBLE_BROWSER_AUTOMATIC", raising=False)
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    monkeypatch.setenv("CODAL_JOB_SOURCE", "manual")
    assert transport.visible_collection() is True

    monkeypatch.setenv("CODAL_JOB_SOURCE", "automatic")
    assert transport.visible_collection() is False

    monkeypatch.setenv("CODAL_VISIBLE_BROWSER_AUTOMATIC", "1")
    assert transport.visible_collection() is True

    monkeypatch.setenv("CODAL_VISIBLE_BROWSER", "0")
    assert transport.visible_collection() is False

    monkeypatch.setenv("CODAL_VISIBLE_BROWSER", "1")
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "1")
    assert transport.visible_collection() is False

    transport.channel = None
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    assert transport.visible_collection() is False


def test_rate_limit_without_captcha_does_not_publish_fake_image(fixture_server, monkeypatch, tmp_path):
    from codal_transport import CodalHTTPError
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    try:
        with pytest.raises(CodalHTTPError):
            transport.current().get(fixture_server + "/rate-only", expect_json=True)
        assert not (root / "challenge.json").exists()
    finally:
        transport.close_current()


def test_blocked_feed_offers_in_site_code_form_even_without_page_markers(
        fixture_server, monkeypatch, tmp_path):
    """A blocked feed asks for the code inside the app, not in the Chromium window.

    The recovery page in this fixture has no CAPTCHA markup at all, which is the
    case the operator hit: the feed refused, but nothing on the visible page told
    them what to do. ``assume_captcha`` must still publish the code form using
    Codal's own image/verify API.
    """
    transport, root = _fresh_transport(monkeypatch, tmp_path)
    monkeypatch.setenv("CODAL_BROWSER_HEADLESS", "0")
    failures = []

    def recover():
        try:
            current = transport.current()
            current._launch_browser()
            current._codal_captcha_image = lambda page: "data:image/jpeg;base64,QUJD"
            current._codal_captcha_verify = lambda page, code: code == "ABCD"
            current._manual_browser_recovery(
                fixture_server + "/recovery-page",
                assume_captcha=True,
                message="کدال به‌جای دادهٔ گزارش‌ها صفحهٔ امنیتی برگرداند.",
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            transport.close_current()

    worker = threading.Thread(target=recover, daemon=True)
    worker.start()
    challenge_path = root / "challenge.json"
    deadline = time.time() + 30
    while time.time() < deadline and not challenge_path.exists():
        time.sleep(0.05)
    assert challenge_path.exists(), "blocked feed did not ask for the code inside the app"
    challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
    assert challenge["kind"] == "text"
    assert challenge["image_data_url"] == "data:image/jpeg;base64,QUJD"
    assert "کد امنیتی" in challenge["message"] or "کد" in challenge["message"]
    answer = {"type": "answer", "job_id": root.name,
              "challenge_id": challenge["challenge_id"], "command_id": "blocked-answer",
              "answer": "ABCD"}
    (root / "commands" / "blocked-answer.json").write_text(json.dumps(answer), encoding="utf-8")
    worker.join(timeout=20)
    assert not worker.is_alive(), f"worker stayed paused after the code was accepted: {failures!r}"
    assert not failures, failures
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "running_browser" and status.get("challenge") is None
