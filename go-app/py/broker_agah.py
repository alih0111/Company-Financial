# -*- coding: utf-8 -*-
"""
broker_agah.py — خواندن سبد و مانده نقدی از پنل معاملات برخط آگاه.

پنل: https://online.agah.com/login
پرتفو: https://online.agah.com/auth/portfolio/asset

ورود: نام کاربری/کد ملی + کلمه عبور + کد امنیتی (کد را کاربر دستی در پنجره وارد می‌کند).

ورودی از طریق stdin به‌صورت JSON:
  {"username": "...", "password": "...", "login_url": "...", "portfolio_url": "...",
   "headless": false, "timeout_sec": 300, "dump_dir": "...", "profile_dir": "..."}

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
   "captured": {"responses": N, "dump_dir": "..."}}

اولویت استخراج: API دقیق آگاه → جدول DOM → JSON عام.
dump_dir شامل resp_*.json و page.html و page.png (اسکرین‌شات) است.

در حالت ناموفق، ok=false و needs_discovery=true و مسیر dump برگردانده می‌شود
تا ساختار واقعی پنل استخراج و parser نهایی شود.
"""

from __future__ import annotations

import argparse
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


# ─────────────────────────── ورود و ناوبری ───────────────────────────

def fill_login(page, username: str, password: str) -> None:
    def try_fill(selectors, value):
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(value, timeout=3000)
                    return True
            except Exception:
                continue
        return False

    try_fill(
        [
            "input[placeholder*='نام کاربری']",
            "input[placeholder*='کد ملی']",
            "input[name*='username']",
            "input[id*='user']",
            "input[type='text']",
        ],
        username,
    )
    try_fill(["input[type='password']", "input[name*='pass']", "input[id*='pass']"], password)


def wait_for_login(page, portfolio_url: str, timeout_sec: int) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            url = page.url or ""
        except Exception:
            url = ""
        if "/login" not in url and ("/auth/" in url or "portfolio" in url or "dashboard" in url):
            return True
        page.wait_for_timeout(1500)
    return False


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
    profile_dir = Path(cfg.get("profile_dir") or "./.runtime/chromium-profile-agah")
    dump_dir = Path(args.dump_dir) if args.dump_dir else Path("./.runtime/agah-dump")
    profile_dir.mkdir(parents=True, exist_ok=True)

    result = {"ok": False, "holdings": [], "cash": {"available": None}, "captured": {"responses": 0, "dump_dir": str(dump_dir)}}

    try:
        if sync_playwright is None:  # pragma: no cover
            result["error"] = "playwright unavailable: نصب/فعال‌سازی playwright لازم است"
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return 1
        with sync_playwright() as pw:
            launch = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "viewport": {"width": 1400, "height": 900},
                "args": ["--disable-gpu", "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check"],
            }
            binary = os.getenv("CHROMIUM_BINARY")
            if binary:
                launch["executable_path"] = binary
            context = pw.chromium.launch_persistent_context(**launch)
            page = context.pages[0] if context.pages else context.new_page()

            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except PWTimeoutError:
                pass
            page.wait_for_timeout(2000)

            # اگر قبلاً لاگین نشده، فرم را پر کن و منتظر ورود دستی کد امنیتی بمان.
            if "/login" in (page.url or ""):
                if username and password:
                    fill_login(page, username, password)
                print("منتظر تکمیل ورود دستی (نام کاربری/رمز/کد امنیتی) در پنجره مرورگر...", file=sys.stderr)
                if not wait_for_login(page, portfolio_url, args.timeout):
                    result["error"] = "login timeout: کد امنیتی/ورود در زمان مقرر تکمیل نشد"
                    result["needs_discovery"] = True
                    Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    context.close()
                    return 2

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

            Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            context.close()
            return 0
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
