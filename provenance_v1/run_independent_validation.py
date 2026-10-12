"""گام ۲-ک-۲ P0 — اعتبارسنجی اقتصادی مستقل ۱۶ نامزد فهرست کوتاه.

تفاوت با ممیزی‌های ۲-ک-۱: آنجا قرارداد موتور «وفادارانه» بازتولید می‌شد
(import مستقیم direct_valuation / pit_share_snapshot / select_current_shares /
resolve_ttm). اینجا همان کمیت‌ها با پیاده‌سازی تازه و مستقل از توابع valuation
موتور، از ردیف‌های خام بازتولید و با آرتیفکت مقایسه می‌شوند:

  * TTM جریان‌ها: فرمول استاندارد FY(prev)+YTD−YTD(prev) با کد خودِ این اسکریپت
    روی financial_facts خام؛ فقط سلول‌هایی که تاریخ انتشار واقعی‌شان (E1 دیتابیس
    یا E2 بازیابی‌شده) ≤ cutoff است به‌عنوان PIT-اثبات‌شده مصرف می‌شوند.
  * قیمت/سهام/ارزش بازار: انتخاب مستقل از market.price_observations و
    market.tsetmc_current_shares / core.share_structure.
  * P/E، P/S، P/B: تقسیم مستقیم و مقایسه با raw_value آرتیفکت V.
  * فاکتورهای T نامزدها: بازتولید مستقل momentum/volatility/liquidity از سری
    قیمت خام با benchmark هم‌وزن مستقل.
  * کنترل پوشش رویدادها: تغییر تعداد سهام بدون رویداد ثبت‌شده = شکاف پوشش
    (هیچ‌وقت معادل اثبات نبود تغییر سرمایه گرفته نمی‌شود).

وضعیت هر شرکت مستقل از امتیازها و Risk Gate صادر می‌شود:
  independently_checked | consistent_but_not_independent |
  insufficient_evidence | conflicting

فقط‌خواندنی: هیچ INSERT/UPDATE/DELETE انجام نمی‌شود.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "provenance_v1"))
sys.path.insert(0, os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from codal_publish_resolver import CodalPublishResolver  # noqa: E402
from run_publish_recovery import (  # noqa: E402  (evidence infra only)
    CACHE_DIR_DEFAULT, GENERATED_NOTE, build_dsn, fiscal_ym, load_artifacts)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
ART_BASE = os.path.join(REPO, "canonical_postgres_v1_2_1",
                        "analytics_canonical_v1", "output")

# قراردادهای مستند لایه خام T (score_v2_t_raw.py) — بازپیاده‌سازی مستقل
PRICE_FLOOR = 100.0
STALE_DAYS = 14
JUMP_BAND = 0.21
VOL_WINDOW_CLOSES = 31
VOL_MIN_RETURNS = 10
LIQ_WINDOW_OBS = 30
LIQ_MIN_OBS = 10
WINDOW_MAX_SPAN_DAYS = 60

TOL = 1e-6
SENTINELS = {1_000_000.0, -1_000_000.0, 100_000_000.0, -100_000_000.0}

STATUS_DEFS = {
    "independently_checked":
        "همه اجزای مؤثر (TTM، قیمت، سهام، نسبت‌های ارزندگی و فاکتورهای T نمونه) "
        "با پیاده‌سازی مستقل از ردیف‌های خام بازتولید و با آرتیفکت منطبق شد؛ "
        "سلول‌های مالی مؤثر به گزارش/نسخه/TracingNo/تاریخ انتشار واقعی متصل و "
        "PIT آن‌ها با تاریخ واقعی اثبات شد؛ شکاف پوشش رویداد و ریسک قرنطینه "
        "یافت نشد.",
    "consistent_but_not_independent":
        "مقادیر با آرتیفکت سازگارند، اما حداقل یک حلقه زنجیره به‌صورت مستقل "
        "اثبات نشده (مثلاً تاریخ انتشار سلولی بازیابی نشده یا تقویم مالی "
        "صریح نبوده)؛ سازگاری داخلی است، نه تأیید مستقل کامل.",
    "insufficient_evidence":
        "شواهد برای بازتولید یا ردیابی مستقل کافی نیست (نبود قیمت/سهام/سلول "
        "مالی مؤثر یا نبود تاریخ انتشار قابل استناد برای سلول‌های حیاتی).",
    "conflicting":
        "تعارض واقعی مشاهده شد: ناسازگاری مقدار بازتولید مستقل با آرتیفکت، "
        "تعارض تاریخ‌های انتشار، تعارض منابع سهام یا ناسازگاری نسخه گزارش‌ها.",
}

STATUS_FA = {
    "independently_checked": "بررسی مستقل کامل",
    "consistent_but_not_independent": "سازگار اما غیرمستقل",
    "insufficient_evidence": "شواهد ناکافی",
    "conflicting": "تعارض",
}

VERIFIED = "verified_publication_date"


def fnum(x):
    """ coercing مستقل خودِ این اسکریپت (بدون import از موتور)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def rel_diff(a, b):
    if a is None or b is None:
        return None
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b), 1e-12)


def rdiff_ok(a, b, tol=TOL):
    d = rel_diff(a, b)
    return d is not None and d <= tol


# ── title duration (تقویم مالی مستقل از fiscal_calendar موتور) ───────────────

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def title_duration_months(title):
    """مدت دوره از عنوان کدال: «۶ ماهه» → 6؛ «سالانه»/«سال مالی» → 12؛
    وگرنه None (میاندوره‌های بی‌طول بدون عدد، هرگز سالانه فرض نمی‌شوند)."""
    if not title:
        return None
    t = str(title).translate(_PERSIAN_DIGITS)
    m = re.search(r"(\d{1,2})\s*ماهه", t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 12:
            return n
    if "سالانه" in t or "سال مالی" in t:
        return 12
    return None


def months_back(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


# ── fetch های مستقل (فقط‌خواندنی) ────────────────────────────────────────────

def fetch_company_facts(conn, cids):
    """همه ردیف‌های مالی ۱۶ شرکت بدون پیش‌فیلتر PIT — visibility را خودم با
    تاریخ انتشار واقعی تصمیم می‌گیرم."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT st.company_id::text AS company_id, st.statement_type,
               st.period_end_date, st.fiscal_year, st.fiscal_month,
               st.is_restated, st.is_audited,
               rv.version_no, f.metric_code, f.period_order,
               f.canonical_value, f.canonical_unit,
               r.id::text AS report_id, r.source, r.source_report_id,
               r.title, r.published_at, r.jalali_period_text
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
        """, (cids,))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def fetch_superseded(conn):
    cur = conn.cursor()
    cur.execute("SELECT supersedes_report_id::text FROM ingestion.reports "
                "WHERE supersedes_report_id IS NOT NULL")
    out = {r[0] for r in cur.fetchall()}
    cur.close()
    return out


def fetch_securities(conn, cids):
    cur = conn.cursor()
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.id::text AS security_id,
                s.codal_symbol, s.tsetmc_ins_code
            FROM core.securities s
            WHERE s.company_id::text = ANY(%s) AND s.is_active
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, security_id, codal_symbol, tsetmc_ins_code FROM sec
        """, (cids,))
    out = {r[0]: {"security_id": r[1], "codal_symbol": r[2],
                  "tsetmc_ins_code": r[3]} for r in cur.fetchall()}
    cur.close()
    return out


def fetch_company_names(conn, cids):
    cur = conn.cursor()
    cur.execute("SELECT id::text, display_name FROM core.companies "
                "WHERE id::text = ANY(%s)", (cids,))
    out = dict(cur.fetchall())
    cur.close()
    return out


def fetch_all_prices(conn, sec_ids, as_of_d, cutoff):
    """کل سری قیمت جمعیت (برای benchmark مستقل) — همان دو فیلتر PIT."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT security_id::text, trade_date, collected_at,
               closing_price_rial, last_price_rial, trade_value_rial
        FROM market.price_observations
        WHERE security_id::text = ANY(%s) AND trade_date <= %s
          AND collected_at <= %s
        ORDER BY security_id::text, trade_date DESC, collected_at DESC
        """, (sec_ids, as_of_d, cutoff))
    out = defaultdict(list)
    for r in cur.fetchall():
        out[r[0]].append({"trade_date": r[1], "collected_at": r[2],
                          "close": fnum(r[3]), "last": fnum(r[4]),
                          "tv": fnum(r[5])})
    cur.close()
    return out


def fetch_latest_price(conn, sec_ids, cutoff):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (security_id::text)
            security_id::text, trade_date, collected_at,
            last_price_rial, closing_price_rial
        FROM market.price_observations
        WHERE security_id::text = ANY(%s) AND collected_at <= %s
        ORDER BY security_id::text, trade_date DESC, collected_at DESC
        """, (sec_ids, cutoff))
    out = {r[0]: {"trade_date": r[1], "collected_at": r[2],
                  "last": fnum(r[3]), "close": fnum(r[4])}
           for r in cur.fetchall()}
    cur.close()
    return out


def fetch_tsetmc_shares(conn, sec_ids, cutoff):
    cur = conn.cursor()
    cur.execute(
        "SELECT security_id::text, shares_count, collected_at "
        "FROM market.tsetmc_current_shares "
        "WHERE security_id::text = ANY(%s) AND collected_at <= %s "
        "ORDER BY security_id::text, collected_at DESC", (sec_ids, cutoff))
    out = defaultdict(list)
    for r in cur.fetchall():
        out[r[0]].append({"shares_count": fnum(r[1]), "collected_at": r[2]})
    cur.close()
    return out


def fetch_share_structure(conn, sec_ids, as_of_d):
    cur = conn.cursor()
    cur.execute(
        "SELECT security_id::text, shares_count, as_of_date, collected_at, "
        "source FROM core.share_structure "
        "WHERE security_id::text = ANY(%s) AND as_of_date <= %s",
        (sec_ids, as_of_d))
    out = defaultdict(list)
    for r in cur.fetchall():
        out[r[0]].append({"shares_count": fnum(r[1]), "as_of_date": r[2],
                          "collected_at": r[3], "source": r[4]})
    cur.close()
    return out


def fetch_share_events(conn, cids):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT company_id::text, event_type, shares_before, shares_after,
               announced_at, approved_at, registered_at, effective_date,
               market_ex_date, status, source_report_id
        FROM core.share_events WHERE company_id::text = ANY(%s)
        """, (cids,))
    cols = ["company_id", "event_type", "shares_before", "shares_after",
            "announced_at", "approved_at", "registered_at", "effective_date",
            "market_ex_date", "status", "source_report_id"]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return out


def fetch_corporate_actions(conn, sec_ids):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT security_id::text, action_date, action_type, adjustment_factor,
               is_confirmed, detected_heuristically, event_semantics_status,
               adjustment_evidence_status, source
        FROM market.corporate_actions WHERE security_id::text = ANY(%s)
        """, (sec_ids,))
    cols = ["security_id", "action_date", "action_type", "adjustment_factor",
            "is_confirmed", "detected_heuristically", "event_semantics_status",
            "adjustment_evidence_status", "source"]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return out


# ── پیاده‌سازی مستقل TTM ─────────────────────────────────────────────────────

def my_ttm(cells, metric, fy, fm, annual_month, is_annual, visibility_ok):
    """TTM مستقل: فقط سلول‌های PIT-اثبات‌شده مصرف می‌شوند.

    returns (value, prov, legs) — legs: {leg_name: cell_ref}
    """
    legs = {}

    def leg(name, key, order):
        c = (cells.get(key) or {}).get("metrics") or {}
        d = (c.get(metric) or {}).get(order)
        if d is not None:
            legs[name] = {"cell": list(key), "order": order,
                          "value": d["value"], "pit": d["pit"],
                          "report_id": d["report_id"],
                          "visible": visibility_ok(d)}
        return d

    if is_annual:
        d = leg("current_ytd", (fy, fm), 1)
        if d and d["value"] is not None and visibility_ok(d):
            return d["value"], "ANNUAL_CELL", legs
    cur = leg("current_ytd", (fy, fm), 1)
    if not cur or cur["value"] is None or not visibility_ok(cur):
        return None, "INSUFFICIENT_OR_UNPROVEN", legs
    if fm == annual_month:
        return cur["value"], "ANNUAL_CELL", legs
    p3 = leg("prior_full_fy", (fy, fm), 3)
    p2 = leg("prior_comparable_ytd", (fy, fm), 2)
    if (p3 and p2 and p3["value"] is not None and p2["value"] is not None
            and visibility_ok(p3) and visibility_ok(p2)):
        return (cur["value"] + p3["value"] - p2["value"],
                "SAME_REPORT_LEGS", legs)
    # زنجیره: نزدیک‌ترین سلول سالانهٔ اثبات‌شدهٔ قبل از fy
    anchor, annual = None, None
    for dy in (1, 2, 3):
        d = leg(f"annual_anchor_m{dy}", (fy - dy, annual_month), 1)
        if d and d["value"] is not None and visibility_ok(d):
            anchor, annual = (fy - dy, annual_month), d
            break
    if annual is None:
        return None, "NO_PROVEN_ANNUAL_ANCHOR", legs
    py = leg("prior_comparable_ytd_cell", (fy - 1, fm), 1)
    if not py or py["value"] is None or not visibility_ok(py):
        return None, "NO_PROVEN_COMPARABLE", legs
    return (annual["value"] + cur["value"] - py["value"], "CHAIN_LEGS", legs)


# ── پیاده‌سازی مستقل T (پروب نامزدها) ────────────────────────────────────────

def build_daily_history(price_rows):
    """{sid: [day asc]} — یک رکورد per (sid, trade_date)؛ اولین ردیف دیده‌شده
    برای هر تاریخ = آخرین collection (ترتیب DESC ورودی)."""
    seen = defaultdict(dict)
    for r in price_rows:
        sid, d = r["security_id"], r["trade_date"]
        if sid is None or d is None:
            continue
        if d in seen[sid]:
            continue
        seen[sid][d] = {"date": d, "close": r["close"], "tv": r["tv"],
                        "collected_at": r["collected_at"]}
    return {sid: sorted(days.values(), key=lambda x: x["date"])
            for sid, days in seen.items()}


def stock_returns(hist_rec, as_of):
    """(ret6, ret3, stale_days, gap6, gap3) — مستقل."""
    vc = [(r["date"], r["close"]) for r in hist_rec
          if r["close"] is not None and r["close"] >= PRICE_FLOOR]
    if not vc:
        return None, None, None, False, False
    last_d, last_c = vc[-1]
    age = (as_of - last_d).days
    out = {}
    gaps = {}
    for tag, months in (("6m", 6), ("3m", 3)):
        ref = months_back(as_of, months)
        idx = None
        for i, (d, _c) in enumerate(vc):
            if d <= ref:
                idx = i
            else:
                break
        if idx is None:
            out[tag] = None
            gaps[tag] = False
            continue
        ret = last_c / vc[idx][1] - 1.0
        out[tag] = ret
        gaps[tag] = any(abs(c2 / c1 - 1.0) >= JUMP_BAND
                        for (_d1, c1), (_d2, c2) in zip(vc[idx:], vc[idx + 1:])
                        if c1)
    return out["6m"], out["3m"], age, gaps["6m"], gaps["3m"]


def my_t_probe(hist_by_sid, sec_by_cid, cids, as_of):
    """مقادیر مستقل momentum برای کل جمعیت → benchmark هم‌وزن → مقادیر نسبی."""
    raw6, raw3 = {}, {}
    facts = {}
    for cid in cids:
        sid = sec_by_cid.get(cid)
        rec = hist_by_sid.get(sid) or []
        r6, r3, age, g6, g3 = stock_returns(rec, as_of)
        facts[cid] = {"ret6": r6, "ret3": r3, "stale_days": age,
                      "gap6": g6, "gap3": g3}
        if r6 is not None and age is not None and age <= STALE_DAYS and not g6:
            raw6[cid] = r6
        if r3 is not None and age is not None and age <= STALE_DAYS and not g3:
            raw3[cid] = r3
    bench = {}
    for fid, raw in (("momentum_6m_rel", raw6), ("momentum_3m_rel", raw3)):
        bench[fid] = (math.fsum(raw[c] for c in sorted(raw)) / len(raw)
                      if raw else None)
    probe = {}
    for cid in cids:
        f = facts[cid]
        probe[cid] = {
            "ret6": f["ret6"], "ret3": f["ret3"], "stale_days": f["stale_days"],
            "gap6": f["gap6"], "gap3": f["gap3"],
            "bench6": bench["momentum_6m_rel"],
            "bench3": bench["momentum_3m_rel"],
            "bench_n6": len(raw6), "bench_n3": len(raw3),
            "momentum_6m_rel": (f["ret6"] - bench["momentum_6m_rel"]
                                if f["ret6"] is not None
                                and bench["momentum_6m_rel"] is not None
                                and not f["gap6"]
                                and f["stale_days"] is not None
                                and f["stale_days"] <= STALE_DAYS else None),
            "momentum_3m_rel": (f["ret3"] - bench["momentum_3m_rel"]
                                if f["ret3"] is not None
                                and bench["momentum_3m_rel"] is not None
                                and not f["gap3"]
                                and f["stale_days"] is not None
                                and f["stale_days"] <= STALE_DAYS else None),
        }
    return probe


def my_vol_liq(hist_rec):
    """(vol_stdev, liq_mean, diag) — مستقل."""
    vc = [(r["date"], r["close"]) for r in hist_rec
          if r["close"] is not None and r["close"] >= PRICE_FLOOR]
    vol_closes = vc[-VOL_WINDOW_CLOSES:]
    rets = [c2 / c1 - 1.0 for (_d1, c1), (_d2, c2)
            in zip(vol_closes, vol_closes[1:]) if c1 and c1 > 0]
    span = ((vol_closes[-1][0] - vol_closes[0][0]).days
            if len(vol_closes) >= 2 else None)
    vol = None
    if len(rets) >= VOL_MIN_RETURNS and (span or 0) <= WINDOW_MAX_SPAN_DAYS:
        if not any(abs(r) >= JUMP_BAND for r in rets):
            vol = statistics.stdev(rets)
    win = hist_rec[-LIQ_WINDOW_OBS:]
    tvs = [r["tv"] for r in win if r["tv"] is not None and r["tv"] >= 0.0]
    lspan = ((win[-1]["date"] - win[0]["date"]).days
             if len(win) >= 2 else None)
    liq = None
    if len(tvs) >= LIQ_MIN_OBS and (lspan or 0) <= WINDOW_MAX_SPAN_DAYS:
        liq = math.fsum(tvs) / len(tvs)
    diag = {"n_vol_returns": len(rets), "vol_span_days": span,
            "n_liq_sessions": len(win), "n_valid_tvs": len(tvs),
            "liq_span_days": lspan}
    return vol, liq, diag


# ── کمکی‌های وضعیت ───────────────────────────────────────────────────────────

def add(actions, status, msg):
    if msg not in actions:
        actions.append(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", default=ART_BASE)
    args = ap.parse_args()

    docs, binding = load_artifacts(args.artifact_dir)
    as_of_d = date.fromisoformat(str(binding["as_of"])[:10])
    cutoff = datetime.fromisoformat(str(binding["cutoff"]).replace(" ", "T"))
    tag = (f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_"
           f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}")
    print(f"snapshot {tag} as_of={as_of_d} cutoff={cutoff}")

    # مراجع مقایسه: ممیزی وفادارانهٔ ۲-ک-۱ (ورودی‌های موتور) + ریکاوری تاریخ‌ها
    val_path = os.path.join(OUT_DIR, f"valuation_audit_{tag}.json")
    pub_path = os.path.join(OUT_DIR, f"publish_recovery_{tag}.json")
    prev_val = json.load(open(val_path, encoding="utf-8"))
    prev_pub = json.load(open(pub_path, encoding="utf-8"))
    shortlist = list(prev_val["population"]["shortlist_ids"])
    print(f"shortlist: {len(shortlist)} companies")

    v_art = json.load(open(os.path.join(args.artifact_dir,
                                        "v2_value_pilot.json"), encoding="utf-8"))
    v_comps = v_art["v_observed_report"]["companies"]
    t_art = json.load(open(os.path.join(args.artifact_dir,
                                        "v2_t_pilot.json"), encoding="utf-8"))
    t_comps = t_art["t_observed_report"]["companies"]
    q_art = docs["q"]
    q_comps = q_art["companies"]

    import psycopg
    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"

    cids_arr = shortlist
    secs = fetch_securities(conn, cids_arr)
    names = fetch_company_names(conn, cids_arr)
    sec_ids = [s["security_id"] for s in secs.values() if s["security_id"]]

    # جمعیت benchmark مستقل momentum = همان ۲۷۱ شرکت آرتیفکت‌ها
    pop_ids = sorted(set(q_comps.keys()) | set(v_comps.keys())
                     | set(t_comps.keys()))
    cur = conn.cursor()
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.id::text AS security_id
            FROM core.securities s
            WHERE s.is_active AND s.company_id::text = ANY(%s)
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, security_id FROM sec
        """, (pop_ids,))
    sec_by_cid = dict(cur.fetchall())
    cur.close()
    all_sec_ids = sorted(sec_by_cid.values())

    superseded = fetch_superseded(conn)
    fact_rows = fetch_company_facts(conn, cids_arr)
    prices_all = fetch_all_prices(conn, all_sec_ids, as_of_d, cutoff)
    latest_prices = fetch_latest_price(conn, sec_ids, cutoff)
    tsetmc = fetch_tsetmc_shares(conn, sec_ids, cutoff)
    vendor = fetch_share_structure(conn, sec_ids, as_of_d)
    share_events = fetch_share_events(conn, cids_arr)
    corp_actions = fetch_corporate_actions(conn, sec_ids)

    resolver = CodalPublishResolver(conn, CACHE_DIR_DEFAULT)

    hist_all = build_daily_history(
        [{**r, "security_id": sid} for sid, rs in prices_all.items()
         for r in rs])
    probe = my_t_probe(hist_all, sec_by_cid, list(sec_by_cid.keys()), as_of_d)

    # گروه‌بندی ردیف‌ها per company
    rows_by_company = defaultdict(list)
    for r in fact_rows:
        rows_by_company[r["company_id"]].append(r)

    events_by_company = defaultdict(list)
    for e in share_events:
        events_by_company[e["company_id"]].append(e)
    actions_by_security = defaultdict(list)
    for a in corp_actions:
        actions_by_security[a["security_id"]].append(a)

    results = {}
    status_counts = Counter()

    for cid in shortlist:
        sec = secs.get(cid) or {}
        sid = sec.get("security_id")
        symbol = sec.get("codal_symbol")
        checks = {}
        notes = []

        # ── ۱) بازیابی مستقل تاریخ انتشار همه دوره‌های شرکت ─────────────────
        rows_c = rows_by_company.get(cid) or []
        periods = sorted({(r["jalali_period_text"], r["period_end_date"])
                          for r in rows_c})
        per_res = {}
        for pj, pg in periods:
            try:
                res = resolver.resolve_statement(cid, symbol, pj, pg)
                per_res[(pj, pg)] = res
            except Exception as exc:  # رزالور نباید اجرا را بکشد
                per_res[(pj, pg)] = None
                notes.append(f"resolver error {pg}: {exc}")

        def row_pub(r):
            """(publish_dt, evidence_class) مستقل برای یک ردیف گزارش."""
            if r["published_at"] is not None:
                return r["published_at"], "E1_db_published_at"
            res = per_res.get((r["jalali_period_text"], r["period_end_date"]))
            if res is not None and res.status == VERIFIED and res.publish_at:
                return res.publish_at, "E2_recovered_verified"
            return None, "unproven"

        # ── ۲) سلول‌های مستقل (winner per (fy,fm) با رتبهٔ خودم) ────────────
        my_cells = defaultdict(dict)
        for r in rows_c:
            if r["report_id"] in superseded:
                continue
            if r["canonical_unit"] not in (None, "rial", "rial_per_share"):
                continue
            fy, fm = r["fiscal_year"], r["fiscal_month"]
            if fy is None or fm is None:
                fy, fm = fiscal_ym(r["period_end_date"])
            key = (fy, fm)
            cell = my_cells.setdefault(key, {"_period": r["period_end_date"],
                                             "_ver": r["version_no"],
                                             "metrics": {}})
            if (r["period_end_date"], r["version_no"]) < \
                    (cell["_period"], cell["_ver"]):
                continue
            cell["_period"], cell["_ver"] = (r["period_end_date"],
                                             r["version_no"])
            pub, cls = row_pub(r)
            m = cell["metrics"].setdefault(r["metric_code"], {})
            m[r["period_order"]] = {
                "value": fnum(r["canonical_value"]),
                "report_id": r["report_id"], "version_no": r["version_no"],
                "period_end": str(r["period_end_date"]),
                "pub_at": pub.isoformat() if pub else None,
                "pit": cls, "title": r["title"],
                "unit": r["canonical_unit"],
            }

        def vis(d):
            return d is not None and d["pit"] in ("E1_db_published_at",
                                                  "E2_recovered_verified")

        # سلول برندهٔ موتور: publish_recovery هر دو ردیف برنده (جدید + سال
        # قبل) را دارد ولی ترتیب گزارش‌Id است؛ موتور max دوره را برنده می‌گیرد
        pub_entry = prev_pub["companies"].get(cid) or {}
        scoring_rows = pub_entry.get("scoring_rows") or []
        winner_row = None
        if scoring_rows:
            winner_row = max(scoring_rows,
                             key=lambda s: (str(s.get("period_end_date") or ""),
                                            s.get("version_no") or 0))
        winner_period = winner_row.get("period_end_date") if winner_row \
            else None
        winner_key = None
        for key, cell in my_cells.items():
            if str(cell["_period"]) == str(winner_period):
                if winner_key is None or key > winner_key:
                    winner_key = key

        # ── ۳) TTM مستقل ───────────────────────────────────────────────────
        ann_months = []
        cell_duration = {}
        for key, cell in my_cells.items():
            # مدت دوره: عنوان ردیف برندهٔ سلول؛ عنوان نامه‌های E2 بعداً اضافه می‌شود
            dur = None
            for m in cell["metrics"].values():
                for d in m.values():
                    if d["title"]:
                        dur = title_duration_months(d["title"])
                        break
                if dur:
                    break
            cell_duration[key] = dur
            if dur == 12:
                ann_months.append(key[1])
        # عنوان‌های بازیابی‌شده هم در مدت نقش دارند (نامه‌های E2)
        for (pj, pg), res in per_res.items():
            if res is None:
                continue
            for ev in getattr(res, "evidence", None) or []:
                t = ev.get("title") if isinstance(ev, dict) else None
                d = title_duration_months(t)
                if d:
                    try:
                        fy, fm = fiscal_ym(pg)
                        if cell_duration.get((fy, fm)) is None:
                            cell_duration[(fy, fm)] = d
                        if d == 12:
                            ann_months.append(fm)
                    except Exception:
                        pass
        annual_month = Counter(ann_months).most_common(1)[0][0] \
            if ann_months else 12
        fiscal_explicit = bool(ann_months)

        ttm_out = {}
        if winner_key:
            fy, fm = winner_key
            is_ann = cell_duration.get(winner_key) == 12
            for metric, mt in (("net_profit", "net_profit_ttm"),
                               ("revenue", "revenue_ttm"),
                               ("operating_profit", "operating_profit_ttm")):
                v, prov, legs = my_ttm(my_cells, metric, fy, fm,
                                       annual_month, is_ann, vis)
                ttm_out[mt] = {"value": v, "prov": prov, "legs": legs}
        else:
            notes.append("سلول برندهٔ موتور در سلول‌های مستقل یافت نشد")

        equity = None
        if winner_key:
            d = (((my_cells.get(winner_key) or {}).get("metrics") or {})
                 .get("total_equity") or {}).get(1)
            if d and d["value"] is not None and vis(d):
                equity = d["value"]

        # مقایسه با ورودی‌های موتور (ممیزی وفادار ۲-ک-۱)
        prev_c = prev_val["companies"].get(cid) or {}
        eng = prev_c.get("engine_inputs") or {}
        ttm_cmp = {}
        for mt in ("net_profit_ttm", "revenue_ttm"):
            mine = (ttm_out.get(mt) or {}).get("value")
            theirs = eng.get(mt)
            if theirs is None and mine is None:
                continue  # هیچ طرف مقدار ندارد — مقایسه بی‌معنا
            ttm_cmp[mt] = {
                "mine": mine, "engine": theirs,
                "match": rdiff_ok(mine, theirs) if None not in (mine, theirs)
                else False,
                "prov": (ttm_out.get(mt) or {}).get("prov"),
                "unproven_legs": [k for k, v in
                                  ((ttm_out.get(mt) or {}).get("legs") or
                                   {}).items() if not v["visible"]],
            }

        # ── ۴) بازار مستقل: قیمت/سهام/ارزش بازار ───────────────────────────
        p = latest_prices.get(sid) if sid else None
        my_price = (p["last"] if p and p["last"] is not None
                    else (p["close"] if p else None))
        my_trade_date = p["trade_date"] if p else None
        tlist = tsetmc.get(sid) or []
        my_shares, my_share_source = None, None
        t_cross = None
        if tlist:
            my_shares = tlist[0]["shares_count"]
            my_share_source = "TSETMC_ZTITAD_CURRENT"
            vlist = sorted(vendor.get(sid) or [],
                           key=lambda x: (x["as_of_date"],
                                          x["collected_at"] or datetime.min
                                          .replace(tzinfo=None)))
            if vlist and vlist[-1]["shares_count"]:
                t_cross = {"vendor_shares": vlist[-1]["shares_count"],
                           "agree": rdiff_ok(my_shares,
                                             vlist[-1]["shares_count"])}
        elif vendor.get(sid):
            vlist = sorted(vendor[sid], key=lambda x: x["as_of_date"])
            my_shares = vlist[-1]["shares_count"]
            my_share_source = "BRS_SHARE_STRUCTURE_CURRENT(fallback)"
        mcap = (my_price * my_shares
                if (my_price and my_price > 0 and my_shares
                    and my_shares > 0) else None)

        # ── ۵) ارزندگی مستقل + مقایسه با آرتیفکت ───────────────────────────
        net_ttm = (ttm_out.get("net_profit_ttm") or {}).get("value")
        rev_ttm = (ttm_out.get("revenue_ttm") or {}).get("value")
        pe_pub = (mcap / net_ttm) if (mcap and net_ttm and net_ttm > 0) \
            else None
        pe_diag = (mcap / net_ttm) if (mcap and net_ttm not in (None, 0)) \
            else None
        ps = (mcap / rev_ttm) if (mcap and rev_ttm and rev_ttm > 0) else None
        pb = (mcap / equity) if (mcap and equity and equity > 0) else None

        v_factors = ((v_comps.get(cid) or {}).get("factors") or {})
        val_cmp = {}
        for k, mine, art in (("pe", pe_pub, (v_factors.get("pe") or {})
                              .get("raw_value")),
                             ("ps", ps, (v_factors.get("ps") or {})
                              .get("raw_value")),
                             ("pb", pb, (v_factors.get("pb") or {})
                              .get("raw_value"))):
            val_cmp[k] = {"mine": mine, "artifact": art,
                          "match": rdiff_ok(mine, art)
                          if None not in (mine, art)
                          else (mine is None and art is None)}

        # قرارداد زیان‌دهی: آرتیفکت pe را فقط برای np>0 منتشر می‌کند
        loss_making = net_ttm is not None and net_ttm <= 0
        art_pe_status = (v_factors.get("pe") or {}).get("raw_status")
        pe_contract_ok = True
        if loss_making and art_pe_status not in (
                "not_applicable", "missing", "invalid"):
            pe_contract_ok = False
        if not loss_making and net_ttm is not None and art_pe_status == \
                "not_applicable":
            pe_contract_ok = False

        # ── ۶) ردیابی سلول‌های مؤثر بر Q (برنده + سال قبل + پایه‌های TTM) ──
        trace_rows = []
        for sr in scoring_rows[:2]:
            res = (sr.get("resolved") or {})
            resolution = res.get("resolution") or {}
            evs = resolution.get("evidence") or []
            tracing = None
            for ev in evs:
                if not isinstance(ev, dict):
                    continue
                tracing = (ev.get("tracing_no")
                           or (ev.get("cache_corroboration") or {})
                           .get("tracing_no")
                           or (ev.get("source_report_id")
                               if ev.get("kind") == "db_codal_report_row"
                               and str(ev.get("source_report_id") or "")
                               .isdigit() else None))
                if tracing:
                    break
            trace_rows.append({
                "cell": "winner" if sr is winner_row else "prev_year",
                "report_id": sr.get("report_id"),
                "version_no": sr.get("version_no"),
                "period_end": sr.get("period_end_date"),
                "status": res.get("status"),
                "publish_at": res.get("publish_at"),
                "tracing_no": tracing,
            })

        # سازگاری نسخه‌ها: اگر برای همان دوره ردیف codal هم هست، مقدارها
        # باید با ردیف برندهٔ legacy بخوانند
        version_checks = []
        if winner_key and scoring_rows:
            wperiod = my_cells[winner_key]["_period"]
            winner_report = winner_row.get("report_id") if winner_row else None
            by_metric = defaultdict(lambda: defaultdict(list))
            for r in rows_c:
                if str(r["period_end_date"]) != str(wperiod):
                    continue
                if r["canonical_unit"] not in (None, "rial", "rial_per_share"):
                    continue
                by_metric[r["metric_code"]][r["period_order"]].append(
                    (fnum(r["canonical_value"]), r["source"],
                     r["report_id"] == winner_report))
            for metric, orders in sorted(by_metric.items()):
                if metric not in ("net_profit", "revenue", "total_equity",
                                  "operating_profit"):
                    continue
                for order, vals in sorted(orders.items()):
                    srcs = {v[1] for v in vals}
                    if len(srcs) < 2:
                        continue
                    base = next((v[0] for v in vals if v[2]), None)
                    others = [v[0] for v in vals if not v[2]]
                    for o in others:
                        ok = rdiff_ok(base, o) if None not in (base, o) \
                            else base is None and o is None
                        version_checks.append(
                            {"metric": metric, "order": order,
                             "legacy": base, "codal": o, "agree": ok})
        version_conflicts = [vc for vc in version_checks if not vc["agree"]]

        # ── ۷) ریسک قرنطینه/ sentinel در سلول‌های مصرف‌شده ──────────────────
        used_facts_sentinels = []
        if winner_key:
            for metric, orders in (my_cells[winner_key]["metrics"].items()):
                for order, d in orders.items():
                    if d["value"] in SENTINELS:
                        used_facts_sentinels.append(
                            {"metric": metric, "order": order,
                             "value": d["value"], "cell": list(winner_key)})
        for mt in ("net_profit_ttm", "revenue_ttm"):
            for leg in (ttm_out.get(mt) or {}).get("legs", {}).values():
                if leg.get("value") in SENTINELS:
                    used_facts_sentinels.append(
                        {"metric": mt, "leg": leg["cell"],
                         "value": leg["value"]})

        # missingهای Q مؤثر (از آرتیفکت — نه امتیاز، فقط وضعیت خام)
        q_factors = ((q_comps.get(cid) or {}).get("factors") or {})
        q_missing = [k for k, f in q_factors.items()
                     if (f.get("raw_status") in ("missing", "invalid"))
                     and f.get("essential")]

        # ── ۸) کفایت پوشش رویدادها ──────────────────────────────────────────
        vlist = sorted(vendor.get(sid) or [], key=lambda x: x["as_of_date"])
        coverage = {"share_count_steps": 0, "steps_without_events": 0,
                    "snapshot_history": {
                        "n_snapshots": len({v["as_of_date"] for v in vlist}),
                        "first": str(vlist[0]["as_of_date"]) if vlist else None,
                        "last": str(vlist[-1]["as_of_date"]) if vlist else None},
                    "method_note": (
                        "اسنپ‌شات‌های vendor فقط روزهای اخیر را دارند؛ تشخیص "
                        "گام از تاریخچهٔ اسنپ‌شات محدود است. کنترل اصلی تغییر "
                        "سرمایه، cross-check سهامِ کاشفته از EPS گزارش با "
                        "تعداد سهام فعلی است (eps_cross_check). نبود رویداد "
                        "ثبت‌شده هرگز معادل اثبات نبود تغییر سرمایه نیست."),
                    "detail": []}
        for a, b in zip(vlist, vlist[1:]):
            if not a["shares_count"] or not b["shares_count"]:
                continue
            dev = abs(b["shares_count"] - a["shares_count"]) / \
                max(a["shares_count"], 1)
            if dev <= 0.005:
                continue
            coverage["share_count_steps"] += 1
            lo = (a["as_of_date"] + timedelta(days=1))
            hi = b["as_of_date"]
            hit = []
            for e in events_by_company.get(cid, []):
                d = (e["effective_date"]
                     or (e["registered_at"].date() if e["registered_at"]
                         else None)
                     or (e["announced_at"].date() if e["announced_at"]
                         else None))
                if d and lo <= d <= hi and e["status"] != "REJECTED":
                    hit.append({"event_type": e["event_type"],
                                "date": str(d), "status": e["status"]})
            for ca in actions_by_security.get(sid, []):
                if ca["action_date"] and lo <= ca["action_date"] <= hi:
                    hit.append({"action_type": ca["action_type"],
                                "date": str(ca["action_date"])})
            if not hit:
                coverage["steps_without_events"] += 1
            coverage["detail"].append({
                "from": str(a["as_of_date"]), "to": str(b["as_of_date"]),
                "shares_from": a["shares_count"], "shares_to": b["shares_count"],
                "recorded_events": hit})

        # EPS-implied shares (cross-check سرمایهٔ مؤثر)
        # نبود رویداد ثبت‌شده معادل اثبات نبود تغییر سرمایه نیست؛ این
        # cross-check اقتصادی است که تغییر سرمایه را از سوی دیگر کنترل می‌کند
        eps_check = None
        if winner_key:
            wm = my_cells[winner_key]["metrics"]
            eps = (wm.get("eps") or {}).get(1, {}).get("value")
            np1 = (wm.get("net_profit") or {}).get(1, {}).get("value")
            wpub = (((my_cells.get(winner_key) or {}).get("metrics")
                     or {}).get("net_profit") or {}).get(1, {}).get("pub_at")
            if eps and np1 and my_shares:
                implied = np1 / eps
                dev = abs(implied - my_shares) / max(implied, my_shares, 1)
                eps_check = {"implied_shares": implied,
                             "used_shares": my_shares,
                             "rel_dev": dev, "flag": dev > 0.05,
                             "winner_period_end": str(
                                 my_cells[winner_key]["_period"]),
                             "winner_publish_at": wpub,
                             "used_vs_implied_ratio": (my_shares / implied
                                                       if implied else None)}

        # ── ۹) پروب مستقل T ─────────────────────────────────────────────────
        pr = probe.get(cid) or {}
        t_factors = ((t_comps.get(cid) or {}).get("factors") or {})
        t_cmp = {}
        for fid, mine in (("momentum_3m_rel", pr.get("momentum_3m_rel")),
                          ("momentum_6m_rel", pr.get("momentum_6m_rel"))):
            art = (t_factors.get(fid) or {}).get("raw_value")
            t_cmp[fid] = {"mine": mine, "artifact": art,
                          "match": rdiff_ok(mine, art)
                          if None not in (mine, art)
                          else (mine is None and art is None)}
        vol_mine, liq_mine, tdiag = my_vol_liq(
            hist_all.get(sid) or [])
        t_cmp["low_volatility"] = {
            "mine": vol_mine,
            "artifact": (t_factors.get("low_volatility") or {}).get("raw_value"),
            "match": rdiff_ok(vol_mine,
                              (t_factors.get("low_volatility") or {})
                              .get("raw_value"))
            if vol_mine is not None
            and (t_factors.get("low_volatility") or {}).get("raw_value")
            is not None
            else vol_mine is None
            and (t_factors.get("low_volatility") or {}).get("raw_value")
            is None}
        t_cmp["liquidity"] = {
            "mine": liq_mine,
            "artifact": (t_factors.get("liquidity") or {}).get("raw_value"),
            "match": rdiff_ok(liq_mine,
                              (t_factors.get("liquidity") or {})
                              .get("raw_value"))
            if liq_mine is not None
            and (t_factors.get("liquidity") or {}).get("raw_value")
            is not None
            else liq_mine is None
            and (t_factors.get("liquidity") or {}).get("raw_value") is None}

        # ── ۱۰) وضعیت‌بندی نهایی (مستقل از امتیاز و Risk Gate) ──────────────
        reasons = []
        status = "independently_checked"

        def downgrade(new, why):
            nonlocal status
            order = {"independently_checked": 0,
                     "consistent_but_not_independent": 1,
                     "insufficient_evidence": 2,
                     "conflicting": 3}
            if order[new] > order[status]:
                status = new
            reasons.append(why)

        # تعارض‌ها
        if not pe_contract_ok:
            downgrade("conflicting",
                      f"قرارداد انتشار P/E زیان‌ده رعایت نشده: "
                      f"net_ttm={net_ttm}، وضعیت آرتیفکت={art_pe_status}")
        if not all(c["match"] for c in val_cmp.values()):
            bad = [k for k, c in val_cmp.items() if not c["match"]]
            if set(bad) == {"pe"} and loss_making:
                pass  # تفاوت ناشی از قرارداد انتشار زیان‌ده — بالا کنترل شد
            else:
                downgrade("conflicting",
                          f"ناسازگاری مقدار بازتولید مستقل با آرتیفکت: {bad}")
        if not all(c["match"] for c in ttm_cmp.values()):
            bad = [k for k, c in ttm_cmp.items() if not c["match"]]
            downgrade("conflicting",
                      f"TTM مستقل با ورودی موتور نمی‌خواند: {bad} "
                      f"(پایه‌های اثبات‌نشده: "
                      f"{ {k: c['unproven_legs'] for k, c in ttm_cmp.items() if not c['match']} })")
        if version_conflicts:
            downgrade("conflicting",
                      f"ناسازگاری مقدار بین نسخه legacy و codal در {len(version_conflicts)} سلول")
        if used_facts_sentinels:
            downgrade("conflicting",
                      f"مقدار قرنطینه‌شده در سلول‌های مصرف‌شده: "
                      f"{len(used_facts_sentinels)} مورد")
        if not all(c["match"] for c in t_cmp.values()):
            bad = [k for k, c in t_cmp.items() if not c["match"]]
            downgrade("conflicting", f"پروب مستقل T نمی‌خواند: {bad}")
        if any(tr["status"] not in (VERIFIED, "db_evidence") 
               for tr in trace_rows):
            downgrade("conflicting",
                      "وضعیت ردیابی سلول مؤثر مخالف verified است: "
                      + ", ".join(f"{tr['cell']}={tr['status']}"
                                  for tr in trace_rows
                                  if tr["status"] not in (VERIFIED,
                                                          "db_evidence")))

        # ناکافی‌ها
        if not scoring_rows:
            downgrade("insufficient_evidence", "سلول برندهٔ Q یافت نشد")
        elif winner_key is None:
            downgrade("insufficient_evidence",
                      "سلول برندهٔ موتور در سلول‌های مستقل قابل تطبیق نبود")
        if my_price is None or my_shares is None:
            downgrade("insufficient_evidence",
                      "قیمت یا تعداد سهام PIT در دسترس نیست")
        if not trace_rows:
            downgrade("insufficient_evidence",
                      "ردیابی سلول‌های مؤثر بر Q در دسترس نیست")

        # غیرمستقل‌ها (سازگار اما اثبات مستقل ناقص)
        unproven_legs_all = sorted(
            {f"{mt}:{leg}" for mt, c in ttm_cmp.items()
             for leg in c["unproven_legs"]})
        if unproven_legs_all:
            downgrade("consistent_but_not_independent",
                      f"پایه‌های TTM با تاریخ انتشار اثبات‌شده نیست: "
                      f"{unproven_legs_all}")
        if not fiscal_explicit:
            downgrade("consistent_but_not_independent",
                      "تقویم مالی صریح از عناوین استخراج نشد؛ ماه سالانه "
                      f"پیش‌فرض {annual_month} استفاده شد")
        if any(tr["status"] != VERIFIED for tr in trace_rows):
            downgrade("consistent_but_not_independent",
                      "حداقل یک سلول مؤثر بدون تاریخ انتشار verified: "
                      + ", ".join(f"{tr['cell']}={tr['status']}"
                                  for tr in trace_rows
                                  if tr["status"] != VERIFIED))
        if my_share_source and "fallback" in (my_share_source or ""):
            downgrade("consistent_but_not_independent",
                      "منبع سهام fallback (BRS) است، نه TSETMC جاری")
        if t_cross is not None and not t_cross["agree"]:
            downgrade("conflicting",
                      "دو منبع سهام نمی‌خوانند: "
                      f"TSETMC={my_shares} vendor={t_cross['vendor_shares']}")
        if coverage["steps_without_events"] > 0:
            downgrade("consistent_but_not_independent",
                      f"{coverage['steps_without_events']} تغییر تعداد سهام "
                      "بدون رویداد ثبت‌شده — نبود رویداد، اثبات نبود تغییر "
                      "سرمایه نیست و نیازمند بررسی است")
        if eps_check and eps_check["flag"]:
            ratio = eps_check.get("used_vs_implied_ratio")
            downgrade("consistent_but_not_independent",
                      "شواهد ردیفی از افزایش سرمایهٔ احتمالی پس از آخرین "
                      f"گزارش: پایهٔ سهام کاشفته از EPS گزارش "
                      f"({eps_check['implied_shares']:,.0f}) با تعداد سهام "
                      f"فعلی ({eps_check['used_shares']:,.0f}) نمی‌خواند "
                      f"(نسبت {ratio:.2f}x، انحراف {eps_check['rel_dev']:.1%}؛"
                      f" گزارش {eps_check['winner_period_end']} منتشرشده "
                      f"{(eps_check['winner_publish_at'] or '')[:10]}) — بدون "
                      "هیچ رویداد ثبت‌شده در share_events/corporate_actions؛ "
                      "پوشش رویدادها ناکافی است و نبود رویداد اثبات نبود "
                      "تغییر سرمایه نیست. نسبت‌های mcap-based (P/E و …) از "
                      "این ناهم‌خوانی متأثر نمی‌شوند؛ تفسیر EPS و هر تحلیل "
                      "مبتنی بر سرمایه باید پس از احراز افزایش سرمایه از "
                      "گزارش‌های کدال بعدی انجام شود")
        if q_missing:
            downgrade("consistent_but_not_independent",
                      f"فاکتورهای essential با داده مفقود/نامعتبر: {q_missing}")

        status_counts[status] += 1
        results[cid] = {
            "company_id": cid, "symbol": symbol,
            "display_name": names.get(cid),
            "shortlist": True,
            "status": status, "status_label": STATUS_FA[status],
            "status_definition": STATUS_DEFS[status],
            "reasons": reasons,
            "checks": {
                "q_cell_trace": trace_rows,
                "fact_version_consistency": {
                    "n_compared": len(version_checks),
                    "n_conflicts": len(version_conflicts),
                    "detail": version_checks[:20]},
                "independent_ttm": ttm_cmp,
                "independent_ttm_prov": {mt: (ttm_out.get(mt) or {})
                                         .get("prov") for mt in ttm_out},
                "independent_market": {
                    "price": my_price, "trade_date": str(my_trade_date)
                    if my_trade_date else None,
                    "shares": my_shares, "share_source": my_share_source,
                    "tsetmc_vs_vendor": t_cross,
                    "market_cap": mcap},
                "independent_valuation": {
                    "pe_published": pe_pub, "pe_diagnostic_lossmaking": pe_diag,
                    "ps": ps, "pb": pb, "loss_making": loss_making,
                    "pe_publication_contract_ok": pe_contract_ok,
                    "compare": val_cmp},
                "denominator_checks": {
                    "net_ttm": net_ttm, "revenue_ttm": rev_ttm,
                    "total_equity": equity,
                    "pe_denominator_positive": bool(net_ttm and net_ttm > 0),
                    "ps_denominator_positive": bool(rev_ttm and rev_ttm > 0),
                    "pb_denominator_positive": bool(equity and equity > 0),
                    "units": "rial (canonical_unit فیلتر شده)",
                },
                "event_coverage": coverage,
                "eps_cross_check": eps_check,
                "sentinel_risk": {
                    "n_used_fact_sentinels": len(used_facts_sentinels),
                    "detail": used_facts_sentinels},
                "q_missing_essential": q_missing,
                "t_probe": {"compare": t_cmp, "diag": tdiag,
                            "bench_n6": pr.get("bench_n6"),
                            "bench_n3": pr.get("bench_n3")},
                "fiscal_calendar": {"annual_month": annual_month,
                                    "explicit": fiscal_explicit},
            },
        }
        print(f"{names.get(cid) or symbol}: {status} — {reasons[:2]}")

    conn.rollback()
    conn.close()

    os.makedirs(OUT_DIR, exist_ok=True)
    result = {
        "mission": "گام ۲-ک-۲ P0 — اعتبارسنجی اقتصادی مستقل ۱۶ نامزد",
        "independence_note": (
            "TTM/قیمت/سهام/نسبت‌ها/فاکتورهای T نمونه با پیاده‌سازی مستقل از "
            "توابع valuation موتور (بدون import direct_valuation، "
            "pit_share_snapshot، select_current_shares، resolve_ttm، "
            "fiscal_calendar) از ردیف‌های خام بازتولید شدند."),
        "status_definitions": STATUS_DEFS,
        "snapshot_binding": binding,
        "population": {"n_companies": len(shortlist), "shortlist_ids": shortlist},
        "status_counts": dict(status_counts),
        "companies": results,
        "generated_note": GENERATED_NOTE,
    }
    json_path = os.path.join(OUT_DIR, f"independent_validation_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {json_path}")

    md_path = write_md(result, tag)
    print(f"wrote {md_path}")
    print("statuses:", dict(status_counts))

    # همین فایل به‌عنوان overlay گو هم مصرف می‌شود (تشخیص با prefix
    # independent_validation_؛ گیت binding در qvtLoadOverlays اعمال می‌شود)
    print(f"overlay-ready: {json_path}")
    return 0


def write_md(result: dict, tag: str) -> str:
    b = result["snapshot_binding"]
    lines = []
    w = lines.append
    w(f"# اعتبارسنجی اقتصادی مستقل ۱۶ نامزد — {str(b['as_of'])[:10]}")
    w("")
    w(f"- اتصال snapshot: Q `{b['q']['sha256'][:16]}…` | V `{b['v']['sha256'][:16]}…` | "
      f"T `{b['t']['sha256'][:16]}…` — cutoff `{b['cutoff']}`")
    w(f"- {result['independence_note']}")
    w("- نبود رویداد ثبت‌شده هرگز معادل اثبات نبود تغییر سرمایه گرفته نشده است.")
    w("")
    w("## تعریف وضعیت‌ها")
    w("")
    for k, v in result["status_definitions"].items():
        w(f"- **{k}** ({STATUS_FA[k]}): {v}")
    w("")
    w("## جمع‌بندی")
    w("")
    for k, v in sorted(result["status_counts"].items()):
        w(f"- **{k}** ({STATUS_FA[k]}): {v}")
    w("")
    w("## وضعیت به تفکیک شرکت")
    w("")
    for cid, r in result["companies"].items():
        w(f"### {r['display_name']} ({r['symbol']}) — {r['status_label']} "
          f"`{r['status']}`")
        w("")
        for reason in r["reasons"]:
            w(f"- {reason}")
        if not r["reasons"]:
            w("- بدون نکتهٔ کاهنده؛ همهٔ کنترل‌ها گذشت")
        tr = r["checks"]["q_cell_trace"]
        for t in tr:
            w(f"- ردیابی {t['cell']}: نسخه {t['version_no']} | TracingNo "
              f"`{t['tracing_no']}` | انتشار {t['publish_at']} | {t['status']}")
        iv = r["checks"]["independent_valuation"]
        cmp = iv["compare"]
        w(f"- P/E: موتور={cmp['pe']['artifact']} | مستقل={cmp['pe']['mine']} "
          f"(زیان‌ده={iv['loss_making']}) | P/S: موتور={cmp['ps']['artifact']} "
          f"| مستقل={cmp['ps']['mine']} | P/B: موتور={cmp['pb']['artifact']} "
          f"| مستقل={cmp['pb']['mine']}")
        it = r["checks"]["independent_ttm"]
        w(f"- TTM سود: موتور={it['net_profit_ttm']['engine']} | مستقل="
          f"{it['net_profit_ttm']['mine']} ({it['net_profit_ttm']['prov']}) | "
          f"TTM فروش: موتور={it['revenue_ttm']['engine']} | مستقل="
          f"{it['revenue_ttm']['mine']} ({it['revenue_ttm']['prov']})")
        ec = r["checks"]["event_coverage"]
        w(f"- پوشش رویداد: {ec['share_count_steps']} گام تغییر سرمایه، "
          f"{ec['steps_without_events']} گام بدون رویداد ثبت‌شده")
        tp = r["checks"]["t_probe"]
        w("- پروب T: " + " | ".join(
            f"{k}={'✓' if v['match'] else '✗'}"
            for k, v in tp["compare"].items()))
        w("")
    path = os.path.join(OUT_DIR, f"independent_validation_{tag}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


if __name__ == "__main__":
    sys.exit(main())
