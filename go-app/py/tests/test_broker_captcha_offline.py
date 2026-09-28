# -*- coding: utf-8 -*-
"""تست آفلاین ورود/کپچای broker_agah (بدون مرورگر/شبکه)."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

GO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GO not in sys.path:
    sys.path.insert(0, GO)

import broker_agah  # noqa: E402


class _StubOcr:
    def __init__(self, text: str):
        self.text = text

    def classification(self, _img: bytes) -> str:
        return self.text


class ChallengeBrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.broker = broker_agah.ChallengeBroker(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_disabled_broker(self):
        none_broker = broker_agah.ChallengeBroker(None)
        self.assertFalse(none_broker.enabled)
        self.assertIsNone(none_broker.wait_answer(time.time() + 0.1))

    def test_publish_writes_challenge_and_clears_stale_answer(self):
        stale = self.dir / "answer.json"
        stale.write_text('{"code": "OLD"}', encoding="utf-8")
        self.broker.publish("data:image/png;base64,QUJD", attempt=2)
        data = json.loads((self.dir / "challenge.json").read_text(encoding="utf-8"))
        self.assertEqual(data["captcha"], "data:image/png;base64,QUJD")
        self.assertEqual(data["attempt"], 2)
        self.assertFalse(stale.exists())

    def test_wait_answer_reads_and_consumes_code(self):
        def write_later():
            time.sleep(0.2)
            (self.dir / "answer.json").write_text('{"code": " GT4R9 "}', encoding="utf-8")

        t = threading.Thread(target=write_later)
        t.start()
        self.broker.publish("data:image/png;base64,QUJD", attempt=1)
        code = self.broker.wait_answer(deadline=time.time() + 5, poll_sec=0.05)
        t.join()
        self.assertEqual(code, "GT4R9")
        self.assertFalse((self.dir / "answer.json").exists())

    def test_wait_answer_timeout(self):
        self.broker.publish("data:image/png;base64,QUJD", attempt=1)
        code = self.broker.wait_answer(deadline=time.time() + 0.3, poll_sec=0.05)
        self.assertIsNone(code)

    def test_clear_removes_challenge(self):
        self.broker.publish("data:image/png;base64,QUJD", attempt=1)
        self.assertTrue((self.dir / "challenge.json").exists())
        self.broker.clear()
        self.assertFalse((self.dir / "challenge.json").exists())


class OcrTests(unittest.TestCase):
    def setUp(self):
        self._orig_ocr = broker_agah._OCR
        self._orig_tried = broker_agah._OCR_TRIED

    def tearDown(self):
        broker_agah._OCR = self._orig_ocr
        broker_agah._OCR_TRIED = self._orig_tried

    def test_decode_data_url(self):
        raw = b"\x89PNG fake"
        url = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(broker_agah.decode_data_url(url), raw)
        self.assertEqual(broker_agah.decode_data_url("not-a-data-url"), b"")

    def test_solve_returns_none_without_ocr(self):
        broker_agah._OCR = None
        broker_agah._OCR_TRIED = True
        self.assertIsNone(broker_agah.solve_captcha_image(b"fake-image-bytes"))

    def test_solve_cleans_and_uppercases(self):
        broker_agah._OCR = _StubOcr("g t-z4q!")
        broker_agah._OCR_TRIED = True
        self.assertEqual(broker_agah.solve_captcha_image(b"img"), "GTZ4Q")

    def test_solve_empty_image(self):
        broker_agah._OCR = _StubOcr("AB12")
        broker_agah._OCR_TRIED = True
        self.assertIsNone(broker_agah.solve_captcha_image(b""))


class LoginSelectorTests(unittest.TestCase):
    def test_selectors_cover_real_panel(self):
        # سلکتورهای واقعی پنل آگاه باید در فهرست جایگزین‌ها باشند.
        self.assertIn("input[name='userName']", broker_agah.LOGIN_SELECTORS["username"])
        self.assertIn("input[name='password']", broker_agah.LOGIN_SELECTORS["password"])
        self.assertIn("input[name='captcha']", broker_agah.LOGIN_SELECTORS["captcha"])
        self.assertIn("button[type='submit']", broker_agah.LOGIN_SELECTORS["submit"])
        self.assertIn("img[src^='data:image']", broker_agah.LOGIN_SELECTORS["captcha_img"])
        self.assertIn("button.fa-arrows-rotate", broker_agah.LOGIN_SELECTORS["captcha_refresh"])


if __name__ == "__main__":
    unittest.main()
