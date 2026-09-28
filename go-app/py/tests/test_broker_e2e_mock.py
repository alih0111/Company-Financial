# -*- coding: utf-8 -*-
"""تست E2E کالکتور آگاه روی سرور mock (بدون سایت واقعی).

کل چرخه ورود/خواندن سبد را با همان سلکتورهای پنل واقعی می‌آزماید:
  ۱) ورود خودکار با OCR (ddddocr) + parse پرتفو/مانده
  ۲) استفاده مجدد از نشست پروفایل همان شخص (بدون صفحه لاگین)
  ۳) مسیر دستی: انتشار کپچا در exchange_dir و پاسخ از answer.json
  ۴) جداسازی نشست: با پروفایل تازه و رمز اشتباه، صفحه لاگین ظاهر می‌شود
     و داده کسی خوانده نمی‌شود.

پیش‌نیاز: playwright + یک کرومیوم (نصب playwright یا کروم سیستمی) و ddddocr.
اجرا (کند است؛ جدا از تست‌های آفلاین):
    cd go-app && python -m unittest py.tests.test_broker_e2e_mock -v
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

TESTS = os.path.dirname(os.path.abspath(__file__))
PY = os.path.dirname(TESTS)
if PY not in sys.path:
    sys.path.insert(0, PY)
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import mock_agah_server  # noqa: E402

COLLECTOR = os.path.join(PY, "broker_agah.py")
RUN_TIMEOUT = 180


def _answer_challenges(exchange_dir: Path, stop: threading.Event):
    """شبیه‌سازی UI: تصویر کپچا را OCR و answer.json را می‌نویسد."""
    try:
        import ddddocr

        ocr = ddddocr.DdddOcr(show_ad=False)
    except Exception:
        return
    seen = None
    while not stop.is_set():
        ch = exchange_dir / "challenge.json"
        try:
            if ch.exists():
                data = json.loads(ch.read_text(encoding="utf-8"))
                key = (data.get("attempt"), str(data.get("captcha", ""))[-48:])
                if key != seen:
                    seen = key
                    raw = base64.b64decode(data["captcha"].split(",", 1)[-1])
                    code = "".join(c for c in str(ocr.classification(raw)).upper() if c.isalnum())
                    if code:
                        tmp = exchange_dir / "answer.json.tmp"
                        tmp.write_text(json.dumps({"code": code}), encoding="utf-8")
                        os.replace(tmp, exchange_dir / "answer.json")
        except Exception:
            pass
        stop.wait(0.4)


class BrokerE2ETests(unittest.TestCase):
    srv = None
    base = None

    @classmethod
    def setUpClass(cls):
        cls.srv = mock_agah_server.start_mock_agah()
        port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{port}"

    @classmethod
    def tearDownClass(cls):
        if cls.srv:
            cls.srv.shutdown()

    def _run(self, cfg: dict, timeout_sec: int = 90, env_extra: dict | None = None):
        tmp = tempfile.mkdtemp(prefix="agah_e2e_")
        out_path = os.path.join(tmp, "out.json")
        dump_dir = os.path.join(tmp, "dump")
        env = os.environ.copy()
        env.update(env_extra or {})
        proc = subprocess.run(
            [sys.executable, COLLECTOR, "--out", out_path, "--dump-dir", dump_dir, "--timeout", str(timeout_sec)],
            input=json.dumps(cfg).encode("utf-8"),
            capture_output=True,
            timeout=RUN_TIMEOUT,
            env=env,
            cwd=PY,
        )
        self.assertTrue(os.path.exists(out_path), f"no output; stderr={proc.stderr.decode(errors='replace')[-400:]}")
        result = json.loads(Path(out_path).read_text(encoding="utf-8"))
        return proc.returncode, result, proc.stderr.decode(errors="replace")

    def _cfg(self, username: str, password: str, profile_dir: str, exchange_dir: str | None = None) -> dict:
        cfg = {
            "username": username,
            "password": password,
            "login_url": f"{self.base}/login",
            "portfolio_url": f"{self.base}/auth/portfolio/asset",
            "headless": True,
            "timeout_sec": 90,
            "profile_dir": profile_dir,
        }
        if exchange_dir:
            cfg["exchange_dir"] = exchange_dir
        return cfg

    # ── ۱) ورود خودکار OCR و خواندن سبد ──
    def test_auto_login_ocr_and_parse(self):
        profile = tempfile.mkdtemp(prefix="agah_prof_auto_")
        code, result, _ = self._run(self._cfg(mock_agah_server.MOCK_USER, mock_agah_server.MOCK_PASS, profile))
        self.assertEqual(code, 0)
        self.assertTrue(result.get("ok"), result.get("error"))
        self.assertEqual(result.get("login", {}).get("mode"), "auto")
        self.assertGreaterEqual(result.get("login", {}).get("attempts", 0), 1)
        symbols = [h["symbol"] for h in result.get("holdings", [])]
        self.assertEqual(symbols, ["کاسپین", "رهیاب"])
        self.assertEqual(result.get("cash", {}).get("last_balance"), 77148)

    # ── ۲) نشست همان شخص: بدون صفحه لاگین (حتی با رمز اشتباه) ──
    def test_session_reuse_skips_login(self):
        profile = tempfile.mkdtemp(prefix="agah_prof_sess_")
        code, first, _ = self._run(self._cfg(mock_agah_server.MOCK_USER, mock_agah_server.MOCK_PASS, profile))
        self.assertEqual(code, 0)
        self.assertTrue(first.get("ok"))

        # سینک دوم همان شخص: نباید صفحه لاگین بیاید.
        code, second, _ = self._run(self._cfg(mock_agah_server.MOCK_USER, "TotallyWrong", profile))
        self.assertEqual(code, 0)
        self.assertEqual(second.get("login", {}).get("mode"), "session")
        self.assertTrue(second.get("ok"))

    # ── ۳) مسیر دستی: کپچا از UI (challenge/answer) ──
    def test_manual_captcha_via_exchange(self):
        profile = tempfile.mkdtemp(prefix="agah_prof_man_")
        exchange = tempfile.mkdtemp(prefix="agah_exch_")
        stop = threading.Event()
        answerer = threading.Thread(
            target=_answer_challenges, args=(Path(exchange), stop), daemon=True
        )
        answerer.start()
        try:
            code, result, _ = self._run(
                self._cfg(mock_agah_server.MOCK_USER, mock_agah_server.MOCK_PASS, profile, exchange),
                env_extra={"AGAH_DISABLE_OCR": "1"},
            )
        finally:
            stop.set()
            answerer.join(timeout=5)
        self.assertEqual(code, 0)
        self.assertTrue(result.get("ok"), result.get("error"))
        self.assertEqual(result.get("login", {}).get("mode"), "manual")

    # ── ۴) پروفایل تازه + رمز اشتباه: لاگین رد می‌شود و داده‌ای خوانده نمی‌شود ──
    def test_fresh_profile_wrong_password_cannot_read_data(self):
        profile = tempfile.mkdtemp(prefix="agah_prof_bad_")
        code, result, _ = self._run(
            self._cfg(mock_agah_server.MOCK_USER, "WrongPassword", profile), timeout_sec=45
        )
        self.assertEqual(code, 2)
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("holdings"), [])
        login = result.get("login", {})
        # صفحه لاگین ظاهر شده و ورود رد شده است (نه نشست کسی دیگر).
        self.assertGreaterEqual(login.get("attempts", 0), 1)
        self.assertIsNotNone(login.get("error"))


if __name__ == "__main__":
    unittest.main()
