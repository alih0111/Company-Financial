"""Normal public-report session. Captchas are never bypassed or auto-submitted."""
import argparse
import base64
import http.cookiejar
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

OUT = Path(__file__).resolve().parent / "output/codal_session"
COOKIE_PATH = OUT / "session.cookies"


def allowed(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in ("www.codal.ir", "codal.ir")


class ReportRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError("Unexpected report redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url, data=None):
    if not allowed(url):
        raise ValueError("Session restricted to official Codal HTTPS")
    OUT.mkdir(parents=True, exist_ok=True)
    jar = http.cookiejar.MozillaCookieJar(str(COOKIE_PATH))
    if COOKIE_PATH.exists():
        jar.load(ignore_discard=True, ignore_expires=False)
    opener = urllib.request.build_opener(ReportRedirect(), urllib.request.HTTPCookieProcessor(jar))
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.codal.ir/"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with opener.open(req, timeout=20) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    jar.save(ignore_discard=True, ignore_expires=False)
    try:
        os.chmod(COOKIE_PATH, 0o600)
    except OSError:
        pass
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("oversized Codal response")
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["image", "verify"])
    ap.add_argument("--code", help="Explicit human-approved captcha code; not stored in reports")
    args = ap.parse_args()
    if args.action == "image":
        result = json.loads(request("https://www.codal.ir/ReportsCaptcha.aspx/GetCaptchaImage", {}))
        image = result.get("d", "")
        if not image.startswith("data:image/") or ";base64," not in image:
            raise ValueError("Unexpected captcha-image response")
        body = base64.b64decode(image.split(",", 1)[1], validate=True)
        path = OUT / "captcha.png"
        path.write_bytes(body)
        print(json.dumps({"image": str(path), "verified": False}))
    else:
        if not args.code:
            raise ValueError("Explicit approved code required")
        result = json.loads(request("https://www.codal.ir/ReportsCaptcha.aspx/VerifyCaptcha", {"code": args.code}))
        print(json.dumps({"verified": result.get("d") is True}))


if __name__ == "__main__":
    main()
