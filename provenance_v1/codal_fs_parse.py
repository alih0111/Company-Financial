#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""پارسر فقط‌خواندنی صورت‌های مالی کدال (گام ۲-ک-۱۳).

ورودی: HTML خروجی «Excel» کدال (excel.codal.ir/service/Excel/GetAll/<serial>/0)
که در واقع مجموعه‌ای از جدول‌های HTML است.

قواعد سخت (بدون حدس):
  * ارقام کدال «میلیون ریال» هستند (سرصفحهٔ صورت‌ها همین را می‌گوید و با
    مقایسهٔ فکت‌های رسمی موجود راستی‌آزمایی شده) → canonical = value × 1e6.
  * eps/operating_eps «ریال» هستند و بدون ضریب ذخیره می‌شوند.
  * عنوان ردیف‌ها بدون نیم‌فاصله و با یکسان‌سازی ي/ك عربی تطبیق داده می‌شود.
  * هیچ ردیفی که عنوانش دقیقاً شناخته نشده معادل هیچ متریکی فرض نمی‌شود.
  * ستون‌ها فقط بر اساس سرصفحهٔ تاریخ‌دار جدول تفسیر می‌شوند؛ اگر ترتیب
    دوره‌ها قابل اثبات نباشد، آن جدول کنار گذاشته می‌شود (بدون حدس).
"""

from __future__ import annotations

import re

ZERO_WIDTH = "\u200c\u200e\u200f\u202a-\u202e"
ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا"})
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# متریک‌های درون‌دامنهٔ Q/V و عنوان دقیق ردیف کدال (پس از نرمال‌سازی).
# کلید = (statement_type, metric_code) ، مقدار = عنوان نرمال‌شدهٔ ردیف.
ROW_TITLES = {
    ("balance_sheet", "total_assets"): "جمع داراییها",
    ("balance_sheet", "current_assets"): "جمع داراییهای جاری",
    ("balance_sheet", "total_liabilities"): "جمع بدهیها",
    ("balance_sheet", "current_liabilities"): "جمع بدهیهای جاری",
    ("balance_sheet", "total_equity"): "جمع حقوق مالکانه",
    ("income_statement", "revenue"): "درآمدهای عملیاتی",
    ("income_statement", "operating_profit"): "سود(زیان) عملیاتی",
    ("income_statement", "finance_cost"): "هزینههای مالی",
    ("income_statement", "other_non_operating"): "سایر درآمدها و هزینههای غیرعملیاتی",
    ("income_statement", "net_profit"): "سود(زیان) خالص",
    ("income_statement", "eps"): "سود(زیان) پایه هر سهم",
    ("income_statement", "operating_eps"): "عملیاتی(ریال)",
    ("income_statement", "capital"): "سرمایه",
    ("cash_flow", "operating_cash_flow"): "جریان خالص ورود (خروج) نقد حاصل از فعالیتهای عملیاتی",
}

# متریک‌هایی که مقدارشان «ریال بر سهم» است (بدون ضریب میلیون).
PER_SHARE = {"eps", "operating_eps"}

# نشانه‌های نوع صورت در سرصفحه/عنوان جدول.
BS_MARK = ("به تاریخ", "وضعیت مالی", "داراییها", "جمع داراییها")
IS_MARK = ("دوره منتهی به", "سود و زیان", "درآمدهای عملیاتی")
CF_MARK = ("فعالیتهای عملیاتی", "جریانهای نقدی")


def norm(text: str) -> str:
    """نرمال‌سازی عنوان/مقدار: نیم‌فاصله، ي/ك عربی، فاصله‌ها."""
    if text is None:
        return ""
    t = str(text)
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    t = t.translate(ARABIC_TO_PERSIAN)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def norm_title(text: str) -> str:
    """عنوان ردیف برای تطبیق: نرمال + حذف همهٔ فاصله‌ها."""
    return norm(text).replace(" ", "")


def to_number(text: str):
    """مقدار سلول کدال → float؛ ارقام فارسی، جداکنندهٔ هزارگان، پرانتز=منفی."""
    if text is None:
        return None
    t = norm(text)
    if t in ("", "-", "--", "—", "…", "..."):
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = t.replace(",", "").replace("٫", ".").translate(PERSIAN_DIGITS)
    t = t.replace("−", "-")
    m = re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t.strip())
    if not m:
        return None
    v = float(t)
    return -v if neg else v


def _cells(row_html: str) -> list[str]:
    out = []
    for m in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I):
        txt = re.sub(r"<[^>]+>", " ", m.group(1))
        out.append(norm(html_unescape(txt)))
    return out


def html_unescape(t: str) -> str:
    return (t.replace("&nbsp;", " ").replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&#39;", "'"))


def _rows(table_html: str) -> list[list[str]]:
    out = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I):
        cs = _cells(m.group(1))
        if any(c.strip() for c in cs):
            out.append(cs)
    return out


_JALALI = re.compile(r"(1[34]\d{2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")


def jalali_in(text: str):
    t = norm(text).translate(PERSIAN_DIGITS)
    m = _JALALI.search(t)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def classify_table(rows: list[list[str]]) -> str | None:
    """نوع صورت را از کل متن جدول تشخیص می‌دهد یا None (بدون حدس)."""
    allt = norm(" ".join(" ".join(r) for r in rows))
    at = allt.replace(" ", "")
    if norm_title("جمع داراییها") in at:
        return "balance_sheet"
    if "فعالیتهایعملیاتی" in at and "جریان" in at:
        return "cash_flow"
    if "درآمدهایعملیاتی" in at:
        return "income_statement"
    if "سود(زیان)خالص" in at and "دورهمنتهی" in at:
        return "income_statement"
    return None


def duration_label(html: str, period: tuple) -> str | None:
    """نوع دوره از برچسب پیش از تاریخ خودِ گزارش در HTML: 'annual' یا 'interim'.

    مثال‌ها: «سال مالی منتهی به ۱۴۰۴/۱۲/۲۹» (سالانه)، «دوره ۳ ماهه منتهی به
    ۱۴۰۵/۰۳/۳۱» (میاندوره‌ای)، «دوره ۱۲ ماهه منتهی به ...» (سالانه).
    """
    if not period:
        return None
    jy, jm, jd = period[0], period[1], period[2]
    t = norm(html).translate(PERSIAN_DIGITS)
    # برچسب باید بلافاصله پیش از «منتهی به <تاریخِ خودِ گزارش>» بیاید.
    pat = (rf"(سال مالی|دوره[^\n]{{0,12}}?ماهه)\s*منتهی به\s*"
           rf"{jy}\s*/\s*0*{jm}\s*/\s*0*{jd}")
    annual = interim = False
    for label in re.findall(pat, t):
        if "سال مالی" in label or "۱۲ ماهه" in label or "12 ماهه" in label:
            annual = True
        elif "ماهه" in label:
            interim = True
    if annual:
        return "annual"
    if interim:
        return "interim"
    return None


def _tables_with_captions(html: str):
    """[(caption_text, table_html)] — عنوان هر جدول از متن بلافاصله قبل از آن."""
    parts = re.split(r"(<table.*?</table>)", html, flags=re.S | re.I)
    out = []
    caption = ""
    for part in parts:
        if part.lower().startswith("<table"):
            out.append((caption, part))
            caption = ""
        else:
            txt = html_unescape(re.sub(r"<[^>]+>", " ", part))
            txt = norm(txt)
            if txt:
                caption = txt
    return out


def _caption_kind(caption: str):
    """(statement_type, consolidated?) از عنوان جدول؛ None اگر صورت مالی نیست."""
    cn = norm_title(caption)
    if not cn:
        return None
    consolidated = "تلفیقی" in cn
    if "صورتوضعیتمالی" in cn:
        return "balance_sheet", consolidated
    if "صورتجریانهاینقدی" in cn or "صورتجریانهایینقدی" in cn or "صورتجریا ن" in cn:
        return "cash_flow", consolidated
    if "صورتسودوزیان" in cn and "جامع" not in cn:
        return "income_statement", consolidated
    return None


def parse_report(html: str) -> dict:
    """HTML کدال → {statements: {stype: {metric: {order: value}}}, period_headers,
    consolidation}.

    برای هر نوع صورت، جدول «تلفیقی» (consolidated) ترجیح دارد — همان تعریف
    حسابداری سطح شرکت؛ در نبود آن، جدول شرکت مادر با برچسب صریح
    ``consolidation="parent"`` استفاده می‌شود. جدول‌های خلاصه/برآورد/تفسیری
    (که عنوان «صورت ...» ندارند) اصلاً خوانده نمی‌شوند.
    """
    picked: dict[str, dict] = {}
    for caption, t in _tables_with_captions(html):
        ck = _caption_kind(caption)
        if ck is None:
            continue
        stype, consolidated = ck
        rows = _rows(t)
        if len(rows) < 3:
            continue
        wanted = {norm_title(v): k[1] for k, v in ROW_TITLES.items() if k[0] == stype}
        header, header_dates = None, []
        for r in rows[:4]:
            dates = [d for d in (jalali_in(c) for c in r) if d]
            if len(dates) >= 2:
                header, header_dates = r, dates
                break
        if header is None:
            continue
        date_cols = [i for i, c in enumerate(header) if jalali_in(c)]
        if len(date_cols) < 2 or not (header_dates[0] > header_dates[1]):
            continue
        hits = sum(1 for r in rows if r and norm_title(r[0]) in wanted)
        if hits == 0:
            continue
        prev = picked.get(stype)
        # ترجیح: تلفیقی بر شرکت مادر؛ در همان گروه، جدول با بیشترین ردیف متریک.
        if prev is not None:
            if prev["consolidated"] and not consolidated:
                continue
            if prev["consolidated"] == consolidated and prev["hits"] >= hits:
                continue
        bucket: dict[str, dict] = {}
        for r in rows:
            if len(r) <= date_cols[0]:
                continue
            metric = wanted.get(norm_title(r[0]))
            if metric is None:
                continue
            v1 = to_number(r[date_cols[0]])
            v2 = to_number(r[date_cols[1]])
            if v1 is not None:
                bucket.setdefault(metric, {})[1] = v1
            if v2 is not None:
                bucket.setdefault(metric, {})[2] = v2
        picked[stype] = {"hits": hits, "bucket": bucket, "consolidated": consolidated,
                         "headers": [header_dates[0], header_dates[1]]}
    out = {"statements": {}, "period_headers": {}, "consolidation": {}}
    for stype, info in picked.items():
        out["statements"][stype] = info["bucket"]
        out["period_headers"][stype] = info["headers"]
        out["consolidation"][stype] = "consolidated" if info["consolidated"] else "parent"
    return out


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    p = sys.argv[1]
    html = open(p, "rb").read().decode("utf-8", "replace")
    out = parse_report(html)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
