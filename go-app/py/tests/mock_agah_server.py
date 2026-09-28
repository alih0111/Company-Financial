# -*- coding: utf-8 -*-
"""سرور mock پنل آگاه برای تست E2E کالکتور (بدون سایت واقعی).

همان سلکتورهای پنل واقعی (online.agah.com) را شبیه‌سازی می‌کند:
  - input[name=userName] / input[name=password] / input[name=captcha]
  - تصویر کپچا به‌صورت data-URL داخل DOM (img[src^='data:image'])
  - دکمه رفرش کپچا (button.fa-arrows-rotate) و دکمه ورود (button[type=submit])
  - خطای فرم داخل innerText فرم («کد امنیتی نادرست است» / «نام کاربری یا کلمه عبور نادرست است»)
  - پس از ورود: /auth/portfolio/asset که دو JSON (پرتفو + مانده) fetch می‌کند.

کپچا با PIL تولید می‌شود (حروف بدون ابهام O/I/0/1) و مقایسه آن حساس به حروف
بزرگ/کوچک نیست. سشن با کوکی side نگه داشته می‌شود.
"""

from __future__ import annotations

import base64
import io
import json
import random
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageFont = None

MOCK_USER = "1000001234"
MOCK_PASS = "TestPass99"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

FIXTURES = Path(__file__).with_name("fixtures_broker")


def _load_fixture(name: str) -> dict:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text)


PORTFOLIO = _load_fixture("portfolio.json")
BALANCE = _load_fixture("balance.json")


def gen_captcha_png(code: str) -> str:
    """تصویر کپچا به‌صورت data-URL (شبیه سبک پنل: متن + خطوط نویز)."""
    w, h = 130, 31
    img = Image.new("RGB", (w, h), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    x = 8
    for ch in code:
        draw.text((x, random.randint(1, 5)), ch, fill=(20, 20, 20), font=font)
        x += 22
    for _ in range(3):
        y = random.randint(4, h - 4)
        draw.line([(0, y), (w, random.randint(0, h))], fill=(90, 90, 90), width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


LOGIN_PAGE = """<!doctype html>
<html lang="fa"><head><meta charset="utf-8"><title>سامانه معاملات آنلاین کارگزاری آگاه | آساتریدر</title></head>
<body>
<form method="post" action="/login">
  <label>نام کاربری یا کد ملی</label>
  <input type="text" name="userName" class="ht-45">
  <label>کلمه عبور</label>
  <input type="password" name="password" class="ht-45">
  <label>کد امنیتی</label>
  <div class="captcha-container border-x flex ht-100 main-bg">
    <img src="{captcha_src}" alt="">
    <button type="button" class="fa fa-arrows-rotate fs-16 icon-c" onclick="location.href='/login?refresh=1'"></button>
  </div>
  <input type="text" name="captcha" placeholder=" مقدار روبرو را وارد نمائید" class="no-border ht-100 w-100">
  {error}
  <button type="submit" class="btn btn-info w-100">ورود</button>
  <button type="button" class="btn outlined w-50">فراموشی کلمه عبور</button>
</form>
</body></html>"""

PORTFOLIO_PAGE = """<!doctype html>
<html lang="fa"><head><meta charset="utf-8"><title>پرتفو</title></head>
<body>
<div id="app">در حال بارگذاری...</div>
<script>
fetch('/api/portfolio').then(r => r.json()).catch(() => {{}});
fetch('/api/balance').then(r => r.json()).catch(() => {{}});
</script>
</body></html>"""


class MockAgahHandler(BaseHTTPRequestHandler):
    sessions: dict = {}
    lock = threading.Lock()

    def log_message(self, *args):  # بی‌صدا
        return

    # ── کمکی‌ها ──
    def _session(self):
        sid = self._cookie_sid()
        with self.lock:
            if sid not in self.sessions:
                self.sessions[sid] = {"code": gen_code(), "logged_in": False}
            return sid, self.sessions[sid]

    def _cookie_sid(self) -> str:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("side="):
                return part[5:]
        return secrets.token_hex(8)

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8", set_sid: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if set_sid:
            # کوکی ماندگار مثل پنل واقعی (پنل هم نشست را بین اجراها نگه می‌دارد).
            self.send_header("Set-Cookie", f"side={set_sid}; Path=/; Max-Age=604800")
        self.end_headers()
        self.wfile.write(body)

    # ── GET ──
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            sid, sess = self._session()
            if sess.get("logged_in"):
                # مثل پنل واقعی: با نشست فعال، صفحه لاگین به پنل ریدایرکت می‌شود.
                self.send_response(302)
                self.send_header("Location", "/auth/portfolio/asset")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if "refresh=1" in self.path:
                with self.lock:
                    sess["code"] = gen_code()
            body = LOGIN_PAGE.replace("{captcha_src}", sess["code"] and gen_captcha_png(sess["code"])).replace(
                "{error}", "")
            self._send(body.encode("utf-8"), set_sid=sid)
        elif path == "/auth/portfolio/asset":
            _, sess = self._session()
            if not sess.get("logged_in"):
                self._send(b"unauthorized", status=302)
                return
            self._send(PORTFOLIO_PAGE.encode("utf-8"))
        elif path == "/api/portfolio":
            self._send(json.dumps(PORTFOLIO).encode("utf-8"), ctype="application/json")
        elif path == "/api/balance":
            self._send(json.dumps(BALANCE).encode("utf-8"), ctype="application/json")
        elif path == "/favicon.ico":
            self._send(b"", status=404)
        else:
            self._send(b"not found", status=404)

    # ── POST ──
    def do_POST(self):
        if self.path.split("?")[0] != "/login":
            self._send(b"not found", status=404)
            return
        sid, sess = self._session()
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        user = (form.get("userName") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        captcha = (form.get("captcha") or [""])[0].strip().upper()

        if captcha != sess["code"].upper():
            error = "لطفا کد کپچا را وارد کنید." if not captcha else "کد امنیتی نادرست است."
            with self.lock:
                sess["code"] = gen_code()  # مثل پنل واقعی، کپچای تازه
        elif user != MOCK_USER or password != MOCK_PASS:
            error = "نام کاربری یا کلمه عبور نادرست است."
        else:
            with self.lock:
                sess["logged_in"] = True
            self.send_response(302)
            self.send_header("Location", "/auth/portfolio/asset")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = LOGIN_PAGE.replace("{captcha_src}", gen_captcha_png(sess["code"])).replace(
            "{error}", f'<div class="form-error">{error}</div>')
        self._send(body.encode("utf-8"), set_sid=sid)


def gen_code(n: int = 5) -> str:
    return "".join(random.choice(CODE_ALPHABET) for _ in range(n))


def start_mock_agah() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockAgahHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


if __name__ == "__main__":
    srv = start_mock_agah()
    print("mock agah on", srv.server_address, flush=True)
    threading.Event().wait()
