#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""واکشی فقط‌خواندنی صورت‌های مالی از کدال (گام ۲-ک-۱۳).

مسیرهای مجاز و عمومی کدال:
  * فهرست:   https://search.codal.ir/api/search/v2/q?Symbol=<sym>&PageNumber=n
  * خروجی:   https://excel.codal.ir/service/Excel/GetAll/<LetterSerial>/0
             (HTML جدول‌دار؛ همان چیزی که پارسر محلی می‌خواند)

قواعد:
  * فقط GET عمومی؛ هیچ ورود/ارسال/تغییر در کدال انجام نمی‌شود.
  * فقط گزارش‌هایی که PublishDateTime آن‌ها ≤ cutoff است استفاده می‌شوند (PIT).
  * دادهٔ خام در پوشهٔ sandbox ذخیره می‌شود؛ هیچ نوشتنی در DB انجام نمی‌شود.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

SEARCH = "https://search.codal.ir/api/search/v2/q"
UA = {"User-Agent": "Mozilla/5.0 (compatible; canonical-qvt-readonly/2k13)"}

FS_MARK = ("صورت‌های مالی", "صورت های مالی", "صورتهای مالی")
ANNUAL_MARK = ("سال مالی منتهی به", "سال مالی منتهي به", "دوره ۱۲ ماهه", "12 ماهه")
INTERIM_MARK = ("میاندوره", "میان‌دوره", "دوره ۳ ماهه", "دوره ۶ ماهه", "دوره ۹ ماهه",
                "دوره 3 ماهه", "دوره 6 ماهه", "دوره 9 ماهه")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u200c", " ")).strip()


def _open_with_retry(url: str, headers: dict, timeout: int, attempts: int = 3):
    """GET با پس‌روی نمایی کوتاه برای 429/5xx — بدون تغییر سمت کدال.

    تعداد تلاش کم است تا در حالت throttle طولانی، هر نماد سریع رد شود و کار
    روی بقیهٔ نمادها ادامه یابد (به‌جای معطلی چنددقیقه‌ای روی یک درخواست).
    """
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(20, 6 * (2 ** i)))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(min(20, 4 * (2 ** i)))
    raise last


def fetch_json(url: str, timeout: int = 30):
    r = _open_with_retry(url, {**UA, "Accept": "application/json"}, timeout)
    with r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch_bytes(url: str, referer: str = "https://www.codal.ir/", timeout: int = 60) -> bytes:
    r = _open_with_retry(url, {**UA, "Referer": referer, "Accept": "*/*"}, timeout)
    with r:
        return r.read()


_JAL = re.compile(r"(1[34]\d{2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> dt.date:
    """تبدیل تقویم جلالی به میلادی (الگوریتم استاندارد، بدون وابستگی خارجی)."""
    jy -= 979
    jm_adj = jm - 1
    jd_adj = jd - 1
    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4
    for i in range(jm_adj):
        j_day_no += 31 if i < 6 else 30
    j_day_no += jd_adj
    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097
    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False
    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365
    gd = g_day_no + 1
    months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return dt.date(gy, gm + 1, gd)


def jalali_date_in(text: str):
    m = _JAL.search(_norm(text).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    if not m:
        return None
    try:
        return dt.date(*jalali_to_gregorian(int(m.group(1)), int(m.group(2)), int(m.group(3))).timetuple()[:3])
    except Exception:
        return None


def publish_date(text: str):
    """PublishDateTime (جلالی) → date میلادی."""
    return jalali_date_in(text)


def search_symbol(symbol: str, pages: int = 3, page_size: int = 20) -> list[dict]:
    letters = []
    for p in range(1, pages + 1):
        url = (f"{SEARCH}?Symbol={urllib.parse.quote(symbol)}&Audited=true&NotAudited=true"
               f"&PageNumber={p}&PageSize={page_size}")
        try:
            d = fetch_json(url)
        except Exception as e:
            letters.append({"__error__": f"page {p}: {type(e).__name__}: {e}"})
            break
        got = d.get("Letters") or []
        letters.extend(got)
        if not got:
            break
        time.sleep(1.5)
    return letters


def classify_letter(letter: dict) -> str | None:
    t = _norm(letter.get("Title") or "")
    if not any(m in t for m in FS_MARK):
        return None
    if any(m in t for m in ANNUAL_MARK) and "حسابرسی" in t:
        return "annual_audited"
    if any(m in t for m in INTERIM_MARK):
        return "interim"
    if any(m in t for m in ANNUAL_MARK):
        return "annual"
    return None


def select_reports(letters: list[dict], cutoff: dt.datetime, max_interim: int = 4) -> dict:
    """جدیدترین گزارش سالانهٔ حسابرسی‌شده + تا max_interim گزارش میاندوره‌ای، همه با PIT."""
    ann, interim = [], []
    for L in letters:
        kind = classify_letter(L)
        if kind is None:
            continue
        pub = publish_date(L.get("PublishDateTime") or "")
        if pub is None or pub > cutoff.date():
            continue
        period = jalali_date_in(L.get("Title") or "")
        rec = {
            "tracing_no": L.get("TracingNo"),
            "title": _norm(L.get("Title")),
            "kind": kind,
            "publish_date": pub.isoformat() if pub else None,
            "period_end": period.isoformat() if period else None,
            "excel_url": L.get("ExcelUrl") or "",
            "decision_url": ("https://www.codal.ir" + L["Url"]) if L.get("Url") else "",
        }
        if kind == "annual_audited":
            ann.append(rec)
        elif kind == "interim":
            interim.append(rec)
    ann.sort(key=lambda r: (r["period_end"] or "", r["publish_date"] or ""), reverse=True)
    interim.sort(key=lambda r: (r["period_end"] or "", r["publish_date"] or ""), reverse=True)
    # حذف تکراری‌ها بر اساس (دوره)
    def dedupe(rs):
        seen, out = set(), []
        for r in rs:
            k = (r["period_end"], r["kind"])
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out
    return {"annual": dedupe(ann)[:2], "interim": dedupe(interim)[:max_interim]}


def fetch_report_html(rec: dict) -> dict:
    """HTML خروجی کدال برای یک گزارش؛ ExcelUrl ترجیح دارد، وگرنه صفحهٔ تصمیم."""
    if rec.get("excel_url"):
        try:
            b = fetch_bytes(rec["excel_url"])
            body = b.decode("utf-8", "replace")
            if "<table" in body.lower():
                return {"ok": True, "via": "excel", "html": body}
        except Exception as e:
            rec.setdefault("errors", []).append(f"excel: {type(e).__name__}: {e}")
    if rec.get("decision_url"):
        try:
            b = fetch_bytes(rec["decision_url"])
            body = b.decode("utf-8", "replace")
            if "<table" in body.lower():
                return {"ok": True, "via": "decision", "html": body}
            return {"ok": False, "via": "decision", "html": body,
                    "note": "decision page has no <table> (Angular shell) — no statement rows"}
        except Exception as e:
            return {"ok": False, "via": "decision", "error": f"{type(e).__name__}: {e}"}
    return {"ok": False, "via": "none", "error": "no usable url"}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sym = sys.argv[1] if len(sys.argv) > 1 else "فباهنر"
    cutoff = dt.datetime.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.datetime(2026, 10, 8, 23, 59)
    letters = search_symbol(sym, pages=4)
    sel = select_reports(letters, cutoff)
    print(json.dumps({"symbol": sym, "n_letters": len(letters), "selected": sel},
                     ensure_ascii=False, indent=1)[:3000])
