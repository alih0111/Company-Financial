# -*- coding: utf-8 -*-
"""
broker_agah.py — خواندن سبد و مانده نقدی از پنل معاملات برخط آگاه.

پنل: https://online.agah.com/login
پرتفو: https://online.agah.com/auth/portfolio/asset

ورود: نام کاربری/کد ملی + کلمه عبور + کد امنیتی.
کد امنیتی به‌ترتیب از این مسیرها حل می‌شود:
  ۱) OCR خودکار (کتابخانه ddddocr در صورت نصب بودن) — تا ۲ تلاش.
  ۲) ورود دستی از UI: تصویر کپچا به‌صورت data-URL در
     exchange_dir/challenge.json منتشر می‌شود و پاسخ از answer.json
     خوانده می‌شود (سرور این فایل‌ها را به UI وصل می‌کند).

نشست مرورگر در profile_dir (به‌ازای هر شخص جداگانه) ذخیره می‌شود؛
بنابراین سینک بعدیِ همان شخص، تا اعتبار نشست، بدون کپچا انجام می‌شود.

ورودی از طریق stdin به‌صورت JSON:
  {"username": "...", "password": "...", "login_url": "...", "portfolio_url": "...",
   "headless": true, "timeout_sec": 300, "dump_dir": "...", "profile_dir": "...",
   "exchange_dir": "..."}

ساختار واقعی API آگاه (کشف‌شده از پاسخ‌های شبکه پنل):
  - پرتفو:  data.data[]  با securityTitle/companyName/securityIsin/numberOfShares/
    averageBuyPrice/calculatedTodayPrice/calculatedAssetCost/calculatedGain/... و
    data.assetSummary جمع کل.
  - مانده:  data با lastBalance/tradableBalanceT1/T2/payableBalance*/credit/block.

خروجی: فایل JSON در --out با ساختار:
  {"ok": true,
   "holdings": [{"symbol","name","isin","nscid","quantity","avg_buy_price","last_price",
                 "cost_basis","market_value","gain","gain_percent","sector","state"}],
   "cash": {"available": N, "last_balance": N, "tradable_t1": N, "tradable_t2": N, ...},
   "summary": {assetSummary},
   "login": {"mode": "session|auto|manual", "attempts": N},
   "captured": {"responses": N, "dump_dir": "..."}}

در حالت ناموفق، ok=false و error تنظیم می‌شود.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import TimeoutError as PWTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover — parserها باید بدون playwright قابل ایمپورت باشند
    PWTimeoutError = TimeoutError
    sync_playwright = None

DEFAULT_LOGIN_URL = "https://online.agah.com/login"
DEFAULT_PORTFOLIO_URL = "https://online.agah.com/auth/portfolio/asset"

# ─────────────────────────── ابزار عددی ───────────────────────────

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_TRANS = {ord(c): str(i) for i, c in enumerate(_PERSIAN_DIGITS)}
_DIGIT_TRANS.update({ord(c): str(i) for i, c in enumerate(_ARABIC_DIGITS)})


def to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).translate(_DIGIT_TRANS)
    s = s.replace("\u066c", "").replace(" ", "").replace("\u200c", "")  # جداکننده هزارگان عربی/فاصله
    s = s.replace("\u066b", ".")  # ممیز فارسی ٫
    s = s.replace("ريال", "").replace("ریال", "").replace("تومان", "").replace("٪", "%")
    if "," in s:
        parts = s.split(",")
        # اگر ممیز اعشاری به‌صورت کاما آمده باشد (یک کاما و حداکثر دو رقم بعدش)
        if "." not in s and len(parts) == 2 and len(parts[1].strip("-")) in (1, 2):
            s = parts[0] + "." + parts[1]
        else:
            s = s.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


# ─────────────────────────── استخراج از DOM ───────────────────────────

SYMBOL_HINTS = ("symbol", "نماد", "instrumentcode", "instrument_code", "ticker", "l18", "inscode", "isin")
NAME_HINTS = ("name", "نام", "شرکت", "company")
QTY_HINTS = ("quantity", "qty", "تعداد", "مقدار", "balance", "موجودی", "count", "share", "volume")
AVG_HINTS = ("avgbuyprice", "averageprice", "avgcost", "buyprice", "میانگین", "بهای", "costprice", "average", "avg_price", "خرید")
PRICE_HINTS = ("lastprice", "closingprice", "price", "قیمت", "آخرین")
VALUE_HINTS = ("value", "ارزش", "marketvalue")
CASH_HINTS = ("قدرت خرید", "مانده", "نقد", "cash", "balance", "available", "buyingpower", "withdrawable", "موجودی نقد")


def _match_col(header: str, hints: tuple[str, ...]) -> bool:
    h = (header or "").strip().lower()
    return any(hint.lower() in h for hint in hints)


def parse_dom_tables(page) -> list[dict]:
    try:
        tables = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('table')).map(t =>
                Array.from(t.querySelectorAll('tr')).map(tr =>
                    Array.from(tr.querySelectorAll('th,td')).map(td => (td.innerText || '').trim())
                )
            )
            """
        )
    except Exception:
        return []

    best: list[dict] = []
    for table in tables or []:
        if len(table) < 2:
            continue
        header = table[0]
        col = {}
        for idx, cell in enumerate(header):
            if "symbol" not in col and _match_col(cell, SYMBOL_HINTS):
                col["symbol"] = idx
            elif "name" not in col and _match_col(cell, NAME_HINTS):
                col["name"] = idx
            elif "qty" not in col and _match_col(cell, QTY_HINTS):
                col["qty"] = idx
            elif "avg" not in col and _match_col(cell, AVG_HINTS):
                col["avg"] = idx
            elif "price" not in col and _match_col(cell, PRICE_HINTS):
                col["price"] = idx
            elif "value" not in col and _match_col(cell, VALUE_HINTS):
                col["value"] = idx
        if "qty" not in col or ("symbol" not in col and "name" not in col):
            continue

        rows = []
        for row in table[1:]:
            if len(row) <= col["qty"]:
                continue
            qty = to_float(row[col["qty"]])
            if qty is None or qty == 0:
                continue
            sym = row[col["symbol"]] if "symbol" in col and col["symbol"] < len(row) else ""
            name = row[col["name"]] if "name" in col and col["name"] < len(row) else ""
            avg = to_float(row[col["avg"]]) if "avg" in col and col["avg"] < len(row) else None
            price = to_float(row[col["price"]]) if "price" in col and col["price"] < len(row) else None
            rows.append({
                "symbol": (sym or name or "").strip(),
                "name": (name or sym or "").strip(),
                "quantity": qty,
                "avg_buy_price": avg,
                "last_price": price,
            })
        if len(rows) > len(best):
            best = rows
    return best


def parse_cash_from_text(text: str) -> float | None:
    for hint in CASH_HINTS:
        idx = text.find(hint)
        if idx < 0:
            continue
        window = text[idx : idx + 120]
        val = to_float(window)
        if val is not None:
            return val
    return None


# ─────────────────────────── استخراج دقیق از API آگاه ───────────────────────────
# ساختار کشف‌شده از پاسخ‌های واقعی پنل (agah-dump/resp_*.json):
#   پرتفو: {"isSuccess":true,"data":{"data":[{securityTitle, companyName, securityIsin,
#            instrumentNscid, numberOfShares, averageBuyPrice, calculatedAverageBuyPrice,
#            calculatedTodayPrice, calculatedHeadLinePrice, calculatedAssetCost,
#            calculatedTodayCost, calculatedGain, calculatedGainPercent, sectorTitle,
#            instrumentStateTitle, isSecurityActive, ...}],
#            "assetSummary": {...}, "totalCount": N}}
#   مانده: {"isSuccess":true,"data":{"lastBalance":N,"tradableBalanceT1":N,
#            "tradableBalanceT2":N,"payableBalanceWithAgahCreditT*":N,
#            "payableBalanceWithoutAgahCreditT0":N,"credit":N,"block":N,
#            "settlementDateT*":"..."}}


def extract_agah_portfolio(payloads: list) -> tuple[list[dict], dict | None]:
    """پاسخ پرتفوی آگاه را دقیق parse می‌کند؛ خروجی: (holdings, assetSummary)."""
    for obj in payloads:
        if not isinstance(obj, dict):
            continue
        data = obj.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            continue
        items = data["data"]
        if not items or not all(isinstance(i, dict) for i in items):
            continue
        if not any(("securityTitle" in i) or ("numberOfShares" in i) for i in items[:3]):
            continue

        holdings = []
        for it in items:
            qty = to_float(it.get("numberOfShares"))
            if qty is None or qty == 0:
                continue
            avg = to_float(it.get("averageBuyPrice"))
            if avg is None:
                avg = to_float(it.get("calculatedAverageBuyPrice"))
            last = to_float(it.get("calculatedTodayPrice"))
            if not last:
                last = to_float(it.get("calculatedHeadLinePrice"))
            holdings.append({
                "symbol": str(it.get("securityTitle") or "").strip(),
                "name": str(it.get("companyName") or "").strip(),
                "isin": str(it.get("securityIsin") or "").strip(),
                "nscid": str(it.get("instrumentNscid") or "").strip(),
                "quantity": qty,
                "avg_buy_price": avg,
                "last_price": last,
                "cost_basis": to_float(it.get("calculatedAssetCost")),
                "market_value": to_float(it.get("calculatedTodayCost")),
                "gain": to_float(it.get("calculatedGain")),
                "gain_percent": to_float(it.get("calculatedGainPercent")),
                "sector": str(it.get("sectorTitle") or "").strip(),
                "state": str(it.get("instrumentStateTitle") or "").strip(),
                "is_active": bool(it.get("isSecurityActive", True)),
            })

        if holdings:
            summary = data.get("assetSummary")
            return holdings, summary if isinstance(summary, dict) else None
    return [], None


BALANCE_FLOAT_KEYS = (
    ("last_balance", ("lastBalance",)),
    ("tradable_t1", ("tradableBalanceT1",)),
    ("tradable_t2", ("tradableBalanceT2",)),
    ("payable_without_credit_t0", ("payableBalanceWithoutAgahCreditT0",)),
    ("payable_with_credit_t1", ("payableBalanceWithAgahCreditT1",)),
    ("payable_with_credit_t2", ("payableBalanceWithAgahCreditT2",)),
    ("credit", ("credit",)),
    ("block", ("block",)),
)


def extract_agah_balance(payloads: list) -> dict | None:
    """پاسخ مانده/قدرت خرید آگاه را دقیق parse می‌کند."""
    for obj in payloads:
        if not isinstance(obj, dict):
            continue
        data = obj.get("data")
        if not isinstance(data, dict):
            continue
        if not any(k in data for k in ("lastBalance", "tradableBalanceT1", "tradableBalanceT2")):
            continue
        out: dict = {}
        for key, srcs in BALANCE_FLOAT_KEYS:
            for src in srcs:
                if src in data:
                    out[key] = to_float(data.get(src))
                    break
        if out:
            return out
    return None


def wait_for_portfolio(payloads: list, page, attempts: int = 4, delay_ms: int = 2500) -> tuple[list[dict], dict | None]:
    """چند بار تلاش می‌کند پاسخ پرتفو برسد (SPA ممکن است دیر لود کند)."""
    holdings, summary = extract_agah_portfolio(payloads)
    for _ in range(attempts):
        if holdings:
            return holdings, summary
        page.wait_for_timeout(delay_ms)
        holdings, summary = extract_agah_portfolio(payloads)
    return holdings, summary


# ─────────────────────────── استخراج از JSON شبکه ───────────────────────────

def _find_holdings_in_json(obj) -> list[dict]:
    found: list[dict] = []

    def visit(node):
        if isinstance(node, list):
            candidate = []
            for item in node:
                if isinstance(item, dict) and _looks_like_holding(item):
                    candidate.append(_normalize_holding(item))
            if candidate:
                found.extend(candidate)
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            for v in node.values():
                visit(v)

    visit(obj)
    return found


def _get_key(d: dict, hints: tuple[str, ...]):
    for k in d.keys():
        if _match_col(k, hints):
            return d[k]
    return None


def _looks_like_holding(d: dict) -> bool:
    has_qty = _get_key(d, QTY_HINTS) is not None
    has_id = _get_key(d, SYMBOL_HINTS) is not None or _get_key(d, NAME_HINTS) is not None
    return has_qty and has_id


def _normalize_holding(d: dict) -> dict:
    sym = _get_key(d, SYMBOL_HINTS)
    name = _get_key(d, NAME_HINTS)
    return {
        "symbol": str(sym if sym is not None else (name or "")).strip(),
        "name": str(name if name is not None else (sym or "")).strip(),
        "quantity": to_float(_get_key(d, QTY_HINTS)),
        "avg_buy_price": to_float(_get_key(d, AVG_HINTS)),
        "last_price": to_float(_get_key(d, PRICE_HINTS)),
    }


def parse_json_payloads(payloads: list) -> list[dict]:
    best: list[dict] = []
    for obj in payloads:
        rows = [r for r in _find_holdings_in_json(obj) if r.get("quantity")]
        if len(rows) > len(best):
            best = rows
    return best


# ─────────────────────────── حل خودکار کپچا (OCR) ───────────────────────────
# کپچای پنل آگاه یک تصویر data-URL داخل DOM است (حدود ۵ کاراکتر حرف بزرگ/عدد).
# ddddocr روی این سبک کپچا دقت بالایی دارد؛ اگر نصب نبود، مسیر دستی فعال می‌شود.

_OCR = None
_OCR_TRIED = False


def get_ocr():
    global _OCR, _OCR_TRIED
    if not _OCR_TRIED:
        _OCR_TRIED = True
        if os.getenv("AGAH_DISABLE_OCR", "").strip().lower() in ("1", "true", "yes"):
            return None
        try:
            import ddddocr  # type: ignore

            _OCR = ddddocr.DdddOcr(show_ad=False)
        except Exception:
            _OCR = None
    return _OCR


def solve_captcha_image(img_bytes: bytes) -> str | None:
    """کپچا را با OCR می‌خواند؛ خروجی فقط حروف/ارقام لاتین بزرگ یا None."""
    if not img_bytes:
        return None
    ocr = get_ocr()
    if ocr is None:
        return None
    try:
        text = ocr.classification(img_bytes)
    except Exception:
        return None
    text = re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    return text or None


def decode_data_url(data_url: str) -> bytes:
    try:
        return base64.b64decode(data_url.split(",", 1)[-1])
    except Exception:
        return b""


# ─────────────────────────── تبادل کپچا با سرور (ورود دستی) ───────────────────────────

class ChallengeBroker:
    """تبادل کپچا/پاسخ بین کالکتور و UI از طریق فایل‌ها:
    challenge.json = {"captcha": "<data-url>", "attempt": N}
    answer.json    = {"code": "..."}
    """

    def __init__(self, exchange_dir: Path | None):
        self.dir = exchange_dir

    @property
    def enabled(self) -> bool:
        return self.dir is not None

    def publish(self, data_url: str, attempt: int) -> None:
        if not self.enabled or not data_url:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            ans = self.dir / "answer.json"
            if ans.exists():
                ans.unlink()
            payload = json.dumps(
                {"captcha": data_url, "attempt": attempt, "ts": time.time()},
                ensure_ascii=False,
            )
            tmp = self.dir / "challenge.json.tmp"
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.dir / "challenge.json")
        except Exception:
            pass

    def wait_answer(self, deadline: float, poll_sec: float = 1.5) -> str | None:
        if not self.enabled:
            return None
        path = self.dir / "answer.json"
        while time.time() < deadline:
            try:
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    code = str(data.get("code") or "").strip()
                    try:
                        path.unlink()
                    except Exception:
                        pass
                    if code:
                        return code
            except Exception:
                pass
            time.sleep(poll_sec)
        return None

    def clear(self) -> None:
        if not self.enabled:
            return
        try:
            (self.dir / "challenge.json").unlink(missing_ok=True)
        except Exception:
            pass


# ─────────────────────────── ورود و ناوبری ───────────────────────────
# سلکتورهای واقعی پنل آگاه (Angular SPA) + جایگزین‌های عمومی.

LOGIN_SELECTORS = {
    "username": (
        "input[name='userName']",
        "input[placeholder*='نام کاربری']",
        "input[placeholder*='کد ملی']",
        "input[name*='user']",
        "input[id*='user']",
    ),
    "password": (
        "input[name='password']",
        "input[type='password']",
        "input[name*='pass']",
        "input[id*='pass']",
    ),
    "captcha": (
        "input[name='captcha']",
        "input[placeholder*='روبرو']",
        "input[placeholder*='کد امنیتی']",
        "input[name*='captcha']",
    ),
    "submit": ("button[type='submit']",),
    "captcha_img": ("img[src^='data:image']",),
    "captcha_refresh": ("button.fa-arrows-rotate", "button.fa-sync", "button.fa-redo"),
}

LOGIN_ERROR_HINTS = ("کپچا", "نادرست", "اشتباه", "خطا", "ناموفق", "منقضی", "مسدود")


def _first_visible(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=1000):
                return loc
        except Exception:
            continue
    return None


def fill_login(page, username: str, password: str) -> None:
    user_loc = _first_visible(page, LOGIN_SELECTORS["username"])
    if user_loc is not None and username:
        try:
            user_loc.fill(username, timeout=3000)
        except Exception:
            pass
    pass_loc = _first_visible(page, LOGIN_SELECTORS["password"])
    if pass_loc is not None and password:
        try:
            pass_loc.fill(password, timeout=3000)
        except Exception:
            pass


def fill_captcha(page, code: str) -> bool:
    loc = _first_visible(page, LOGIN_SELECTORS["captcha"])
    if loc is None:
        return False
    try:
        loc.fill(code, timeout=3000)
        return True
    except Exception:
        return False


def read_captcha_data_url(page) -> str | None:
    for sel in LOGIN_SELECTORS["captcha_img"]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                src = loc.get_attribute("src", timeout=2000)
                if src and src.startswith("data:image"):
                    return src
        except Exception:
            continue
    return None


def wait_for_captcha(page, timeout_sec: float = 20) -> str | None:
    """منتظر ظاهر شدن تصویر کپچا می‌ماند؛ اگر صفحه از login خارج شد None برمی‌گرداند."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if "/login" not in (page.url or ""):
            return None
        src = read_captcha_data_url(page)
        if src:
            return src
        page.wait_for_timeout(500)
    return None


def submit_login(page) -> None:
    btn = _first_visible(page, LOGIN_SELECTORS["submit"])
    if btn is not None:
        try:
            btn.click(timeout=5000)
            return
        except Exception:
            pass
    # جایگزین: کلیک از طریق JS (اگر روی دکمه پوششی باشد)
    try:
        page.evaluate(
            "() => { const b = document.querySelector(\"button[type='submit']\"); if (b) b.click(); }"
        )
    except Exception:
        pass


def refresh_captcha(page) -> None:
    btn = _first_visible(page, LOGIN_SELECTORS["captcha_refresh"])
    if btn is None:
        return
    try:
        btn.click(timeout=3000)
        page.wait_for_timeout(1000)
    except Exception:
        pass


def read_login_error(page) -> str:
    """متن خطای نمایش‌داده‌شده روی فرم لاگین (در صورت وجود)."""
    text = ""
    try:
        text = page.inner_text("form", timeout=2000)
    except Exception:
        try:
            text = page.inner_text("body", timeout=2000)
        except Exception:
            return ""
    for line in (text or "").splitlines():
        line = line.strip()
        if line and len(line) < 200 and any(h in line for h in LOGIN_ERROR_HINTS):
            return line
    return ""


def login_state(page, wait_sec: float = 10) -> str:
    """تشخیص وضعیت: 'login' (فرم لاگین) یا 'inside' (نشست فعال).

    فقط URLهای معلومِ پنل (auth/portfolio/dashboard) «داخل» حسابند؛ هر URL دیگری
    (مثل about:blank در نبود شبکه) مثل فرم لاگین رفتار می‌شود تا ورود دوباره تلاش شود.
    """
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        url = page.url or ""
        if looks_authed(url):
            return "inside"
        if "/login" in url:
            try:
                if page.locator("input[name='captcha'], input[name='userName']").first.count() > 0:
                    return "login"
            except Exception:
                pass
        page.wait_for_timeout(500)
    return "inside" if looks_authed(page.url or "") else "login"


def looks_authed(url: str) -> bool:
    url = url or ""
    return bool(url) and any(k in url for k in ("/auth/", "portfolio", "dashboard"))


def do_login(page, username: str, password: str, challenge: ChallengeBroker,
             dump_dir: Path, timeout_sec: int, login_url: str = DEFAULT_LOGIN_URL) -> dict:
    """ورود با تلاش خودکار OCR و در صورت نیاز درخواست کد از UI.

    خروجی: {"mode": "auto|manual", "attempts": N, "error": str|None}
    """
    info: dict = {"mode": "auto", "attempts": 0, "error": None}
    deadline = time.time() + timeout_sec
    ocr_failures = 0
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        info["attempts"] = attempt

        # اگر به هر دلیل روی فرم لاگین نیستیم، دوباره به login برو.
        if "/login" not in (page.url or ""):
            if looks_authed(page.url or ""):
                return info  # نشست فعال
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                pass
            page.wait_for_timeout(1500)
            if looks_authed(page.url or ""):
                return info
            if "/login" not in (page.url or ""):
                continue  # صفحه هنوز آماده نیست؛ در دور بعد تلاش کن

        data_url = wait_for_captcha(page, timeout_sec=20 if attempt == 1 else 10)
        if data_url is None:
            if looks_authed(page.url or ""):
                return info  # در فاصله انتظار، وارد شده است
            info["error"] = "تصویر کپچا روی صفحه لاگین پیدا نشد"
            continue

        # ۱) تلاش خودکار با OCR (تا ۲ تلاش؛ بعد از آن مسیر دستی)
        code = None
        if ocr_failures < 2:
            code = solve_captcha_image(decode_data_url(data_url))
        via = "auto"
        if not code:
            via = "manual"
            info["mode"] = "manual"
            if not challenge.enabled:
                info["error"] = "حل خودکار کپچا ناموفق بود و مسیر ورود دستی (exchange_dir) تنظیم نشده است"
                return info
            challenge.publish(data_url, attempt)
            print("کپچا برای ورود دستی منتشر شد (challenge.json)؛ منتظر کد از UI...", file=sys.stderr)
            code = challenge.wait_answer(deadline)
            if not code:
                info["error"] = "login timeout: کد امنیتی در زمان مقرر از UI دریافت نشد"
                return info

        fill_login(page, username, password)
        if not fill_captcha(page, code):
            info["error"] = "فیلد کد امنیتی روی فرم پیدا نشد"
            continue

        submit_login(page)

        # موفقیت: خروج از صفحه login به پنل (تا ۱۵ ثانیه)
        ok = False
        for _ in range(30):
            page.wait_for_timeout(500)
            if looks_authed(page.url or ""):
                ok = True
                break

        if ok:
            challenge.clear()
            return info

        # تلاش ناموفق: ثبت خطا و تلاش دوباره با کپچای تازه
        err = read_login_error(page)
        info["error"] = err or "ورود انجام نشد (صفحه همچنان روی login است)"
        try:
            dump_dir.mkdir(parents=True, exist_ok=True)
            (dump_dir / f"login_attempt_{attempt}.txt").write_text(info["error"], encoding="utf-8")
        except Exception:
            pass
        challenge.clear()
        if via == "auto":
            ocr_failures += 1
        refresh_captcha(page)
        page.wait_for_timeout(1000)

    info["error"] = info.get("error") or "login timeout"
    return info


def goto_portfolio(page, portfolio_url: str) -> None:
    try:
        page.goto(portfolio_url, wait_until="domcontentloaded", timeout=60000)
    except PWTimeoutError:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(3000)


# ─────────────────────────── کشف/ذخیره ───────────────────────────

def capture_responses(page, dump_dir: Path) -> list:
    payloads: list = []
    dump_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def on_response(resp):
        try:
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            body = resp.text()
            if not body or len(body) > 5_000_000:
                return
            data = json.loads(body)
            payloads.append(data)
            counter["n"] += 1
            (dump_dir / f"resp_{counter['n']:03d}.json").write_text(body, encoding="utf-8")
        except Exception:
            return

    page.on("response", on_response)
    return payloads


# ─────────────────────────── main ───────────────────────────

def build_launch_args(pw, headless: bool, profile_dir: Path) -> dict:
    launch = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1400, "height": 900},
        "args": ["--disable-gpu", "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check"],
    }
    binary = os.getenv("CHROMIUM_BINARY")
    if binary:
        launch["executable_path"] = binary
        return launch
    # اگر کرومیوم دانلود‌شده playwright موجود نبود، از کروم سیستمی استفاده کن.
    try:
        exe = pw.chromium.executable_path
    except Exception:
        exe = None
    if not exe or not os.path.exists(exe):
        launch["channel"] = "chrome"
    return launch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--dump-dir", default="")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    raw = sys.stdin.read()
    cfg = json.loads(raw or "{}")
    username = (cfg.get("username") or "").strip()
    password = cfg.get("password") or ""
    login_url = cfg.get("login_url") or DEFAULT_LOGIN_URL
    portfolio_url = cfg.get("portfolio_url") or DEFAULT_PORTFOLIO_URL
    headless = bool(cfg.get("headless", False))
    timeout_sec = int(cfg.get("timeout_sec") or args.timeout)
    profile_dir = Path(cfg.get("profile_dir") or "./.runtime/chromium-profile-agah")
    exchange_raw = cfg.get("exchange_dir") or ""
    exchange_dir = Path(exchange_raw) if exchange_raw else None
    dump_dir = Path(args.dump_dir) if args.dump_dir else Path("./.runtime/agah-dump")
    profile_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "ok": False,
        "holdings": [],
        "cash": {"available": None},
        "captured": {"responses": 0, "dump_dir": str(dump_dir)},
    }

    def finish(code: int) -> int:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return code

    try:
        if sync_playwright is None:  # pragma: no cover
            result["error"] = "playwright unavailable: نصب/فعال‌سازی playwright لازم است"
            return finish(1)
        challenge = ChallengeBroker(exchange_dir)
        with sync_playwright() as pw:
            launch = build_launch_args(pw, headless, profile_dir)
            context = pw.chromium.launch_persistent_context(**launch)
            page = context.pages[0] if context.pages else context.new_page()

            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                pass
            page.wait_for_timeout(2000)

            # اگر نشست فعال وجود ندارد، وارد شو (OCR خودکار یا کد دستی از UI).
            if login_state(page) == "login":
                login_info = do_login(page, username, password, challenge, dump_dir, timeout_sec, login_url)
                result["login"] = login_info
                if login_info.get("error"):
                    result["error"] = login_info["error"]
                    context.close()
                    return finish(2)
            else:
                result["login"] = {"mode": "session", "attempts": 0}
                print("نشست فعال پیدا شد؛ از ورود رد شد.", file=sys.stderr)

            payloads = capture_responses(page, dump_dir)
            goto_portfolio(page, portfolio_url)
            page.wait_for_timeout(4000)

            # ۱) API دقیق آگاه (پاسخ‌های JSON شبکه: پرتفو + مانده)
            holdings, summary = wait_for_portfolio(payloads, page)
            source = "agah_api"
            # ۲) جدول DOM به‌عنوان جایگزین
            if not holdings:
                holdings = parse_dom_tables(page)
                source = "dom"
            # ۳) JSON عام (کشف ساختار)
            if not holdings:
                holdings = parse_json_payloads(payloads)
                source = "json"

            balance = extract_agah_balance(payloads)
            cash_val = balance.get("last_balance") if balance else None
            if cash_val is None:
                try:
                    cash_val = parse_cash_from_text(page.inner_text("body"))
                except Exception:
                    cash_val = None

            try:
                (dump_dir / "page.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            try:
                page.screenshot(path=str(dump_dir / "page.png"), full_page=True)
            except Exception:
                pass

            result["holdings"] = holdings
            cash: dict = {"available": cash_val}
            if balance:
                cash.update(balance)
            result["cash"] = cash
            if summary:
                result["summary"] = summary
            result["source"] = source
            result["captured"] = {"responses": len(payloads), "dump_dir": str(dump_dir)}
            result["ok"] = bool(holdings)
            if not holdings:
                result["needs_discovery"] = True

            challenge.clear()
            context.close()
            return finish(0)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        return finish(1)


if __name__ == "__main__":
    raise SystemExit(main())
