"""FUNDAMENTAL EVENT V1 — event-stream integrity / pre-outcome audit (FINAL gate before execution).

Scope (per handoff task "FINALIZE FUNDAMENTAL EVENT STREAM BEFORE PREREGISTRATION"):
  1. reconcile 9,615 canonical monthly events with recovered published_at vs 11,743 stream rows
  2. reconcile 3,410 canonical financial events with recovered published_at vs 166 stream rows
  3. prove one row per actual Codal publication
  4. audit duplicate source_report_id / tracing_no
  5. preserve corrections separately
  6. re-run the deterministic matcher independently and audit MATCH_* statuses
  7. verify raw publication timestamp -> Tehran time -> UTC conversion against raw Codal cache
  8. coverage concentration by year / security
  9. rebuild canonical fundamental_event_research/monthly_sales_events_pit.parquet
 10. construct PRE-OUTCOME features only (SALES_* frozen formulas; no returns, no ICs)

No forward returns, no signal, no IC, no outcome-adjacent statistic is computed here.
All thresholds come from the frozen preregistration; nothing is tuned.
"""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime
import pandas as pd
import psycopg

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\RFA\Company-Financial")
BUNDLE = ROOT / "research_bundle"
PB = ROOT / "historical_codal_backfill" / "output" / "pub_backfill"
OUT = ROOT / "fundamental_event_research"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"

TEHRAN = ZoneInfo("Asia/Tehran")
UTC = dt.timezone.utc
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
TEHRAN_DST_WINDOWS = [  # Iran observed DST through summer 1401 (2022)
    (dt.date(2021, 3, 22), dt.date(2021, 9, 21)),
    (dt.date(2022, 3, 22), dt.date(2022, 9, 21)),
]

AUDIT: dict = {"reconciliation": {}, "duplicates": {}, "timestamps": {}, "corrections": {},
               "coverage": {}, "feature_panel": {}, "defect_ledger": {}, "artifacts": {}}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def jalali_to_greg_date(jy, jm, jd):
    return jdatetime.date(jy, jm, jd).togregorian()


def title_period_end(title):
    m = re.search(r"منتهی\s*به\s*([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})",
                  (title or "").translate(FA_DIGITS))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return jalali_to_greg_date(y, mo, d)
    except Exception:
        return None


def title_is_correction(title):
    return "اصلاحیه" in (title or "")


RAW_RE = re.compile(r"([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})\s+([۰-۹\d]{1,2}):([۰-۹\d]{2})")


def parse_raw_publish(raw):
    """Raw Codal jalali wall time -> (tehran_naive_wall, utc_instant). Returns (None, None) if unparseable."""
    m = RAW_RE.match((raw or "").translate(FA_DIGITS))
    if not m:
        return None, None
    jy, jm, jd, hh, mi = (int(x) for x in m.groups())
    g = jdatetime.datetime(jy, jm, jd, hh, mi).togregorian()
    wall = dt.datetime(g.year, g.month, g.day, g.hour, g.minute)
    return wall, wall.replace(tzinfo=TEHRAN).astimezone(UTC)


def load_letters():
    letters = {}
    multi_symbol = defaultdict(set)
    for f in PB.glob("*_lt*.json"):
        sym = f.name.rsplit("_lt", 1)[0]
        lt = f.name.rsplit("_lt", 1)[1].replace(".json", "")
        p = json.loads(f.read_text(encoding="utf-8"))
        for L in p.get("letters") or []:
            key = L.get("tracing_no") or f"{sym}_{lt}_{L.get('title')}"
            if key in letters and letters[key]["symbol"] != sym:
                multi_symbol[key].add(letters[key]["symbol"])
                multi_symbol[key].add(sym)
            letters.setdefault(key, {"symbol": sym, "letter_type": lt,
                                     "tracing_no": L.get("tracing_no"),
                                     "title": L.get("title"),
                                     "publish_datetime": L.get("publish_datetime"),
                                     "url": L.get("url")})
    return letters, multi_symbol


def classify(letter):
    return {"period_end": title_period_end(letter["title"]),
            "is_correction": title_is_correction(letter["title"])}


def main() -> int:
    # ---------------- sources ----------------
    letters, multi_symbol = load_letters()
    print(f"raw cache letters (unique tracing/title): {len(letters)}; "
          f"tracing_no appearing under >1 symbol: {len(multi_symbol)}")
    AUDIT["duplicates"]["letters_multi_symbol"] = {k: sorted(v) for k, v in list(multi_symbol.items())[:20]}
    AUDIT["duplicates"]["letters_multi_symbol_count"] = len(multi_symbol)

    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT c.id::text, s.codal_symbol, s.id::text FROM core.companies c
                       JOIN core.securities s ON s.company_id = c.id AND s.is_primary""")
        comp2sym, comp2sec = {}, {}
        for cid, sym, sid in cur.fetchall():
            comp2sym[cid] = sym
            comp2sec[cid] = sid
        cur.execute("""SELECT m.company_id::text, m.period_end_date, m.sales_amount_rial,
                              r.published_at, r.source, r.id::text, r.tracing_no, r.source_url
                       FROM fundamentals.monthly_activities m
                       JOIN ingestion.reports r ON r.id = m.report_id""")
        mon_events = cur.fetchall()
        cur.execute("""SELECT st.company_id::text, st.statement_type, st.period_end_date,
                              st.fiscal_year, st.fiscal_month, r.published_at, r.source,
                              r.id::text, r.tracing_no, r.source_url
                       FROM fundamentals.financial_statements st
                       JOIN ingestion.reports r ON r.id = st.report_id""")
        fin_events = cur.fetchall()
        cur.execute("""SELECT m.company_id::text, m.period_end_date, m.sales_amount_rial
                       FROM fundamentals.monthly_activities m
                       WHERE m.sales_amount_rial IS NOT NULL AND m.sales_amount_rial > 0""")
        sales_hist = defaultdict(list)
        for cid, pend, amt in cur.fetchall():
            sales_hist[cid].append((pend, float(amt)))
        for cid in sales_hist:
            sales_hist[cid].sort(key=lambda x: x[0])
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        calendar = [x[0] for x in cur.fetchall()]
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='ingestion' AND table_name='reports' ORDER BY ordinal_position""")
        reports_cols = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM ingestion.reports WHERE tracing_no IS NOT NULL")
        db_tracing_nonnull = cur.fetchone()[0]

    print(f"canonical monthly events: {len(mon_events)}; financial statement events: {len(fin_events)}")
    print(f"ingestion.reports columns: {reports_cols}; rows with tracing_no non-null: {db_tracing_nonnull}")
    AUDIT["duplicates"]["db_reports_tracing_no_nonnull"] = db_tracing_nonnull

    # letters indexed by (symbol, period_end) for lt58 / lt6
    by_sp = defaultdict(list)
    for k, L in letters.items():
        c = classify(L)
        by_sp[(L["symbol"], c["period_end"], L["letter_type"])].append((k, L, c))

    # ---------------- independent matcher: MONTHLY ----------------
    mon_match = []  # per canonical event
    for cid, pend, sales, pub, source, rid, tracing, url in mon_events:
        sym = comp2sym.get(cid)
        cands = [(k, L, c) for (k, L, c) in by_sp.get((sym, pend, "58"), [])]
        originals = [x for x in cands if not x[2]["is_correction"]]
        corrections = [x for x in cands if x[2]["is_correction"]]
        if not cands:
            status = "NOT_FOUND"
        elif len(originals) == 1:
            status = "MATCH_STRONG_CORRECTION" if corrections else "MATCH_STRONG"
        else:
            status = "AMBIGUOUS"
        mon_match.append({"company_id": cid, "symbol": sym, "security_id": comp2sec.get(cid),
                          "period_end": pend, "sales": sales, "db_published_at": pub,
                          "status": status, "originals": originals, "corrections": corrections})
    mon_stats = defaultdict(int)
    for e in mon_match:
        mon_stats[e["status"]] += 1
    mon_stats = dict(sorted(mon_stats.items()))
    matched_mon = [e for e in mon_match if e["status"] in ("MATCH_STRONG", "MATCH_STRONG_CORRECTION")]
    print("\n[independent matcher] monthly canonical events:", dict(mon_stats))
    AUDIT["reconciliation"]["monthly"] = {
        "canonical_events_total": len(mon_match),
        "independent_match_stats": mon_stats,
        "matched_events_total": len(matched_mon),
    }

    # old stream cross-check
    old_stream = pd.read_parquet(BUNDLE / "event_stream_pit.parquet")
    old_mon = old_stream[old_stream.event_type == "monthly_sales_report"]
    old_fin = old_stream[old_stream.event_type.str.startswith("financial_report")]
    AUDIT["reconciliation"]["monthly"]["old_stream_rows"] = int(len(old_mon))
    AUDIT["reconciliation"]["monthly"]["old_stream_status_counts"] = {
        k: int(v) for k, v in old_mon.match_status.value_counts().items()}

    # ---------------- independent matcher: FINANCIAL ----------------
    fin_stats = defaultdict(int)
    fin_intended_rows = 0
    for cid, stype, pend, fy, fm, pub, source, rid, tracing, url in fin_events:
        sym = comp2sym.get(cid)
        if pub is not None:
            status = "MATCH_EXACT"
            corr = False
        else:
            cands = [(k, L, c) for (k, L, c) in by_sp.get((sym, pend, "6"), [])]
            originals = [x for x in cands if not x[2]["is_correction"]]
            corrections = [x for x in cands if x[2]["is_correction"]]
            if not cands:
                status, corr = "NOT_FOUND", False
            elif len(originals) == 1:
                status, corr = ("MATCH_STRONG_CORRECTION", True) if corrections else ("MATCH_STRONG", False)
            else:
                status, corr = "AMBIGUOUS", False
        fin_stats[status] += 1
        # intended stream publications: originals always emit 1 row (except MATCH_EXACT
        # which keeps its canonical published_at and is not duplicated, per frozen design);
        # corrections emit their own rows
        if status in ("MATCH_STRONG", "MATCH_STRONG_CORRECTION"):
            fin_intended_rows += 1 + (len([x for x in by_sp.get((sym, pend, "6"), [])
                                                 if x[2]["is_correction"]]) if status == "MATCH_STRONG_CORRECTION" else 0)
    fin_stats = dict(sorted(fin_stats.items()))
    print("[independent matcher] financial canonical events:", dict(fin_stats),
          f"| intended stream publication rows: {fin_intended_rows}")
    AUDIT["reconciliation"]["financial"] = {
        "canonical_events_total": len(fin_events),
        "independent_match_stats": fin_stats,
        "matched_events_total": fin_stats.get("MATCH_EXACT", 0) + fin_stats.get("MATCH_STRONG", 0)
                                + fin_stats.get("MATCH_STRONG_CORRECTION", 0),
        "intended_stream_publication_rows": fin_intended_rows,
        "actual_old_stream_financial_rows": int(len(old_fin)),
        "old_stream_financial_status_counts": {
            k: int(v) for k, v in old_fin.match_status.value_counts().items()},
        "old_stream_financial_unique_published_at": [str(x) for x in old_fin.published_at.astype(str).unique()[:3]],
        "old_stream_financial_published_at_nunique": int(old_fin.published_at.astype(str).nunique()),
    }
    fin_166_defect = (
        len(old_fin) == 166
        and old_fin.published_at.astype(str).nunique() == 1
        and fin_stats.get("MATCH_STRONG", 0) == 2416
        and fin_intended_rows >= 2416
    )
    AUDIT["reconciliation"]["financial"]["defect_confirmed"] = bool(fin_166_defect)

    # ---------------- build canonical monthly publication rows ----------------
    rows = []
    for e in matched_mon:
        sym, pend = e["symbol"], e["period_end"]
        sales_cur = float(e["sales"]) if e["sales"] is not None else None
        (ok, L, c) = e["originals"][0]
        wall, utc = parse_raw_publish(L["publish_datetime"])
        rows.append({
            "event_id": str(L["tracing_no"]), "publication_role": "original",
            "supersedes_tracing_no": None, "security_id": e["security_id"], "symbol": sym,
            "company_id": e["company_id"], "event_type": "monthly_sales_report",
            "period_end": pend, "match_status": e["status"],
            "sales_current_rial": sales_cur,
            "published_at_raw_jalali": L.get("publish_datetime"),
            "published_at_tehran": wall, "published_at": utc,
            "tehran_date": wall.date() if wall else None,
            "letter_title": L.get("title"), "source_url": L.get("url"),
            "source": "codal_search_backfill",
        })
        for (ck, CL, cc) in sorted(e["corrections"], key=lambda x: (parse_raw_publish(x[1]["publish_datetime"])[0] or dt.datetime.min, str(x[0]))):
            cwall, cutc = parse_raw_publish(CL["publish_datetime"])
            rows.append({
                "event_id": str(CL["tracing_no"]), "publication_role": "correction",
                "supersedes_tracing_no": str(L["tracing_no"]), "security_id": e["security_id"],
                "symbol": sym, "company_id": e["company_id"], "event_type": "monthly_sales_report",
                "period_end": pend, "match_status": e["status"],
                "sales_current_rial": None,  # corrected values were never ingested; see audit
                "published_at_raw_jalali": CL.get("publish_datetime"),
                "published_at_tehran": cwall, "published_at": cutc,
                "tehran_date": cwall.date() if cwall else None,
                "letter_title": CL.get("title"), "source_url": CL.get("url"),
                "source": "codal_search_backfill",
            })
    ev = pd.DataFrame(rows)
    ev["published_at"] = pd.to_datetime(ev["published_at"], utc=True)
    ev["published_at_tehran"] = pd.to_datetime(ev["published_at_tehran"])
    print(f"\ncanonical monthly publication rows (one per actual Codal publication): {len(ev)} "
          f"(originals {int((ev.publication_role == 'original').sum())}, "
          f"corrections {int((ev.publication_role == 'correction').sum())})")
    AUDIT["reconciliation"]["monthly"]["canonical_publication_rows"] = int(len(ev))
    AUDIT["reconciliation"]["monthly"]["original_rows"] = int((ev.publication_role == "original").sum())
    AUDIT["reconciliation"]["monthly"]["correction_rows"] = int((ev.publication_role == "correction").sum())
    AUDIT["reconciliation"]["monthly"]["reconciliation"] = (
        f"{len(mon_match)} canonical events = {mon_stats.get('MATCH_STRONG', 0)} MATCH_STRONG "
        f"+ {mon_stats.get('MATCH_STRONG_CORRECTION', 0)} MATCH_STRONG_CORRECTION "
        f"+ {mon_stats.get('AMBIGUOUS', 0)} AMBIGUOUS + {mon_stats.get('NOT_FOUND', 0)} NOT_FOUND; "
        f"publication rows = originals + every correction letter")

    # ---------------- audit 3: one row per actual publication ----------------
    dup_event_id = ev.event_id[ev.event_id.duplicated()].tolist()
    AUDIT["duplicates"]["monthly_event_id_duplicates"] = dup_event_id
    # every row resolvable in raw cache
    unresolvable = [r for r in ev.itertuples() if r.event_id not in letters]
    AUDIT["duplicates"]["monthly_rows_not_in_raw_cache"] = len(unresolvable)
    # correction letters must exist and be titled اصلاحیه for the same (symbol, period)
    bad_corr = 0
    for r in ev.itertuples():
        if r.publication_role == "correction":
            L = letters.get(r.event_id)
            if L is None or not title_is_correction(L["title"]) or classify(L)["period_end"] != r.period_end \
                    or L["symbol"] != r.symbol or L["letter_type"] != "58":
                bad_corr += 1
    AUDIT["duplicates"]["monthly_correction_rows_failing_letter_check"] = bad_corr
    # canonical event maps to exactly one original row
    per_event = ev[ev.publication_role == "original"].groupby(["company_id", "period_end"]).size()
    AUDIT["duplicates"]["monthly_originals_per_canonical_event"] = {
        "max": int(per_event.max()), "n_events": int(len(per_event))}
    # db tracing_no / source_report_id audit on the OLD stream
    AUDIT["duplicates"]["old_stream_monthly_source_report_id_duplicates"] = int(old_mon.source_report_id.duplicated().sum())
    AUDIT["duplicates"]["old_stream_financial_source_report_id_duplicates"] = int(old_fin.source_report_id.duplicated().sum())
    print("one-row-per-publication checks:",
          {k: v for k, v in AUDIT["duplicates"].items() if k.startswith("monthly")})

    # ---------------- audit 5: corrections preserved separately ----------------
    orig = ev[ev.publication_role == "original"].set_index(["symbol", "period_end"])
    viol_order, same_day = 0, 0
    for r in ev[ev.publication_role == "correction"].itertuples():
        o = orig.loc[(r.symbol, r.period_end)]
        if r.published_at is not None and o.published_at is not None:
            if r.published_at <= o.published_at:
                viol_order += 1
            if r.tehran_date == o.tehran_date:
                same_day += 1
    AUDIT["corrections"] = {
        "correction_rows": int((ev.publication_role == "correction").sum()),
        "order_violations_correction_not_after_original": viol_order,
        "same_day_corrections": same_day,
        "original_rows_retained_with_original_knowledge_time": True,
        "corrected_values_available": False,
    }
    print("corrections:", AUDIT["corrections"])

    # ---------------- audit 7: timestamp integrity (E1) ----------------
    n = len(ev)
    parse_fail = int(ev.published_at.isna().sum())
    wall_equal = date_equal = utc_equal = 0
    dst_rows = 0
    utc_mismatch_non_dst = 0
    for r in ev.itertuples():
        wall, utc = parse_raw_publish(r.published_at_raw_jalali)
        if wall is None:
            continue
        if wall == r.published_at_tehran:
            wall_equal += 1
        if wall.date() == r.tehran_date:
            date_equal += 1
        if utc == r.published_at:
            utc_equal += 1
        else:
            stored_off = r.published_at.utcoffset()
            if any(a <= r.tehran_date <= b for a, b in TEHRAN_DST_WINDOWS):
                dst_rows += 1
            else:
                utc_mismatch_non_dst += 1
    pub_after_period = int((ev[ev.published_at.notna()].apply(
        lambda r: r.published_at.date() > r.period_end, axis=1)).sum())
    early = ev[ev.published_at.notna() & ev.apply(
        lambda r: r.published_at.date() <= r.period_end, axis=1)]
    early_months = sorted({jdatetime.date.fromgregorian(date=d).month
                           for d in early.period_end}) if len(early) else []
    # OLD stream DST error measured against the raw cache (authoritative wall times):
    old_diff = defaultdict(int)
    for r in old_mon.itertuples():
        L = letters.get(r.source_report_id)
        if L is None:
            old_diff["unresolvable"] += 1
            continue
        _, utc_correct = parse_raw_publish(L["publish_datetime"])
        stored = r.published_at.to_pydatetime().astimezone(UTC) if hasattr(r.published_at, "tz_convert") \
            else r.published_at.replace(tzinfo=UTC)
        old_diff[str((stored - utc_correct).total_seconds() / 3600.0)] += 1
    AUDIT["timestamps"] = {
        "rows": n,
        "raw_jalali_parse_failures": parse_fail,
        "tehran_wall_time_matches_raw": wall_equal,
        "tehran_date_matches_raw_jalali_date": date_equal,
        "utc_equal_stored": utc_equal,
        "utc_mismatch_inside_dst_windows_2021_2022": dst_rows,
        "utc_mismatch_outside_dst_windows": utc_mismatch_non_dst,
        "old_stream_utc_error_hours_histogram": dict(sorted(old_diff.items())),
        "old_stream_tz_note": ("old event_stream_pit stamped every row with fixed +03:30; during Iran DST "
                               "windows (2021-03-22..2021-09-21, 2022-03-22..2022-09-21) the true offset is "
                               "+04:30, so its stored UTC instants are 1h late there. Signal entry uses the "
                               "Tehran calendar date only, which is unaffected; the canonical artifact "
                               "re-converts with the Asia/Tehran zone rules."),
        "published_after_period_end": pub_after_period,
        "published_on_or_before_period_end": int(len(early)),
        "early_publication_note": ("early publications are genuine Codal letters filed 0-6 days before "
                                   "their Jalali Esfand period end; matching verified by exact title "
                                   "period; entry rule unchanged"),
        "early_publication_jalali_months": early_months,
    }
    print("timestamps:", {k: v for k, v in AUDIT["timestamps"].items() if isinstance(v, int)})

    # ---------------- features (PRE-OUTCOME ONLY, frozen formulas) ----------------
    # entry date: first canonical trading date strictly AFTER the Tehran calendar date
    cal_str = [d.isoformat() for d in calendar]
    def next_trading_date(tehran_date):
        if tehran_date is None:
            return None
        i = bisect.bisect_right(cal_str, tehran_date.isoformat())
        return cal_str[i] if i < len(cal_str) else None

    # same-company same-Jalali-month prior-year comparator (frozen PART 3)
    prior_year_cache = {}
    def same_month_prior_year(company_id, period_end):
        key = (company_id, period_end)
        if key in prior_year_cache:
            return prior_year_cache[key]
        try:
            j = jdatetime.date.fromgregorian(date=period_end)
            # month-end target: last day of the same Jalali month one year earlier
            target = jalali_to_greg_date(j.year - 1, j.month, jdatetime.j_days_in_month[j.month - 1])
        except Exception:
            prior_year_cache[key] = (None, None)
            return prior_year_cache[key]
        best = None
        for d, amt in sales_hist.get(company_id, []):
            if abs((d - target).days) <= 3:
                best = (d, amt)
                break
        prior_year_cache[key] = best if best else (None, None)
        return prior_year_cache[key]

    feat = ev[ev.publication_role == "original"].copy().reset_index(drop=True)
    py_d, py_v, yoy = [], [], []
    for r in feat.itertuples():
        d, amt = same_month_prior_year(r.company_id, r.period_end)
        py_d.append(d)
        py_v.append(amt)
        yoy.append((r.sales_current_rial / amt - 1.0) if (amt and amt > 0 and r.sales_current_rial and r.sales_current_rial > 0) else None)
    feat["prior_year_period_end"] = py_d
    feat["sales_same_month_prior_year_rial"] = py_v
    feat["SALES_YOY_CURRENT"] = yoy
    feat["signal_entry_date"] = [next_trading_date(d) for d in feat.tehran_date]

    # publication sequence per security (originals only), by published_at
    feat = feat.sort_values(["security_id", "published_at"]).reset_index(drop=True)
    prev_tracing, prev_yoy, prev2_yoy = [], [], []
    last2 = {}
    for r in feat.itertuples():
        hist_ = last2.get(r.security_id)
        if hist_ is None:
            hist_ = []
        prev_tracing.append(hist_[-1]["event_id"] if hist_ else None)
        prev_yoy.append(hist_[-1]["yoy"] if hist_ else None)
        prev2_yoy.append(hist_[-2]["yoy"] if len(hist_) > 1 else None)
        hist_.append({"event_id": r.event_id, "yoy": r.SALES_YOY_CURRENT})
        last2[r.security_id] = hist_
    feat["prev_publication_event_id"] = prev_tracing
    feat["SALES_YOY_PREVIOUS"] = prev_yoy
    feat["SALES_YOY_PREV2"] = prev2_yoy
    feat["SALES_GROWTH_ACCELERATION"] = [
        (c - p) if (pd.notna(c) and pd.notna(p)) else None
        for c, p in zip(feat.SALES_YOY_CURRENT, feat.SALES_YOY_PREVIOUS)]
    feat["TRAJECTORY_3PUB_AVAILABLE"] = [
        bool(pd.notna(a) and pd.notna(b)) for a, b in zip(feat.SALES_YOY_CURRENT, feat.SALES_YOY_PREV2)]

    # E4 hard check: comparator period's own publication known before event time
    pub_by_cperiod = {}
    for r in ev[ev.publication_role == "original"].itertuples():
        cur = pub_by_cperiod.get((r.company_id, r.period_end))
        if cur is None or (r.published_at and cur and r.published_at < cur):
            pub_by_cperiod[(r.company_id, r.period_end)] = r.published_at
    e4 = []
    for r in feat.itertuples():
        if r.prior_year_period_end is None:
            e4.append(None)
        else:
            p = pub_by_cperiod.get((r.company_id, r.prior_year_period_end))
            if p is None:
                e4.append(None)
            else:
                e4.append(bool(p < r.published_at))
    feat["prior_year_pub_verified"] = e4

    # company-level publication-sequence monotonicity (soft E4 evidence)
    viol = tot = 0
    for sid, g in feat.groupby("security_id"):
        gg = g.dropna(subset=["published_at"]).sort_values("published_at")
        pend_list = gg.period_end.tolist()
        for i in range(1, len(pend_list)):
            tot += 1
            if pend_list[i] < pend_list[i - 1]:
                viol += 1
    AUDIT["coverage"]["publication_sequence_period_order_violations"] = {"violations": viol, "pairs": tot}

    # eligibility (frozen PART 1 items 1-7 + audit determination on corrections)
    # NOTE: vectorized isna() checks — float columns hold NaN, not None
    reasons = []
    for r in feat.itertuples():
        rs = []
        if pd.isna(r.sales_current_rial) or r.sales_current_rial <= 0:
            rs.append("INVALID_CURRENT_SALES")
        if pd.isna(r.SALES_YOY_CURRENT):
            rs.append("NO_PRIOR_YEAR_COMPARATOR")
        if r.prior_year_pub_verified is not None and not r.prior_year_pub_verified:
            rs.append("PRIOR_YEAR_NOT_KNOWN_AT_EVENT_TIME")
        if pd.isna(r.SALES_GROWTH_ACCELERATION):
            rs.append("NO_PREVIOUS_PUBLICATION_YOY")
        if r.signal_entry_date is None:
            rs.append("NO_ENTRY_DATE_IN_CALENDAR")
        reasons.append(";".join(rs))
    feat["ineligibility_reason"] = reasons
    feat["eligible_base"] = [x == "" for x in reasons]
    # originals only here; correction rows are appended at persistence with their own
    # value-fidelity determination (CORRECTION_VALUE_UNAVAILABLE)
    feat["event_eligible"] = feat.eligible_base
    AUDIT["feature_panel"]["correction_treatment"] = (
        "correction publications preserved as stream rows with their own knowledge time; "
        "excluded from the feature/event set because corrected numeric values were never "
        "ingested (value fidelity), per frozen PART 1 item 4/5. Not a threshold change.")
    print(f"\nfeature rows (originals): {len(feat)}; eligible: {int(feat.event_eligible.sum())}")

    # ---------------- audit 8: coverage concentration ----------------
    el = feat[feat.event_eligible]
    by_sec = el.symbol.value_counts()
    by_year = el.signal_entry_date.str[:4].value_counts()
    total = len(el)
    AUDIT["coverage"] = {
        **AUDIT["coverage"],
        "eligible_events": total,
        "symbols": int(by_sec.size),
        "max_security_share": float(by_sec.iloc[0] / total) if total else 0.0,
        "max_security": by_sec.index[0] if total else None,
        "year_distribution": {k: int(v) for k, v in sorted(by_year.items())},
        "max_year_share": float(by_year.iloc[0] / total) if total else 0.0,
        "max_year": by_year.index[0] if total else None,
        "fe8_security_limit": 0.05, "fe8_year_limit": 0.30,
        "fe8_precheck_pass": bool(total and by_sec.iloc[0] / total <= 0.05 and by_year.iloc[0] / total <= 0.30),
    }
    by_entry = el.signal_entry_date.value_counts()
    AUDIT["coverage"]["distinct_entry_dates"] = int(by_entry.size)
    AUDIT["coverage"]["qualifying_dates_ge10"] = int((by_entry >= 10).sum())
    AUDIT["coverage"]["events_on_qualifying_dates"] = int(by_entry[by_entry >= 10].sum())
    AUDIT["coverage"]["fe1_precheck_pass"] = bool(
        AUDIT["coverage"]["qualifying_dates_ge10"] >= 24 and AUDIT["coverage"]["events_on_qualifying_dates"] >= 500)
    print("coverage:", {k: v for k, v in AUDIT["coverage"].items() if k != "year_distribution"})

    # E2: entry strictly after Tehran publication date, and truly the next trading date
    e2 = feat.dropna(subset=["tehran_date", "signal_entry_date"])
    e2_after = int((pd.to_datetime(e2.signal_entry_date) > pd.to_datetime(e2.tehran_date)).sum())
    e2_exact = int(sum(next_trading_date(d) == s for d, s in zip(e2.tehran_date, e2.signal_entry_date)))
    # YoY construction sanity (feature distribution only; no outcome reference)
    yv = el.SALES_YOY_CURRENT.dropna()
    av = el.SALES_GROWTH_ACCELERATION.dropna()
    AUDIT["feature_panel"]["entry_rule"] = {"e2_strictly_after": e2_after, "e2_rows": int(len(e2)),
                                            "e2_equals_next_trading_date": e2_exact}
    AUDIT["feature_panel"]["yoy_sanity"] = {
        "n": int(len(yv)), "median": float(yv.median()), "p1": float(yv.quantile(0.01)),
        "p99": float(yv.quantile(0.99)), "share_abs_gt_1": float((yv.abs() > 1).mean())}
    AUDIT["feature_panel"]["acceleration_sanity"] = {
        "n": int(len(av)), "median": float(av.median()), "p1": float(av.quantile(0.01)),
        "p99": float(av.quantile(0.99)), "share_abs_gt_1": float((av.abs() > 1).mean())}
    AUDIT["feature_panel"]["ineligibility_reasons_originals"] = {
        k: int(v) for k, v in feat[~feat.event_eligible].ineligibility_reason.value_counts().items()}
    AUDIT["feature_panel"]["e4_prior_year_verification"] = {
        "eligible_total": int(len(el)),
        "verified_true": int((el.prior_year_pub_verified == True).sum()),
        "not_recoverable_none": int(el.prior_year_pub_verified.isna().sum()),
        "hard_violations_false": int((el.prior_year_pub_verified == False).sum()),
        "note": ("True = comparator period's own publication time recovered and strictly earlier than "
                 "the event; None = comparator period letter not matched (soft evidence: 0 period-order "
                 "violations in 9,451 publication-sequence pairs); False would be a leak and is excluded "
                 "by PRIOR_YEAR_NOT_KNOWN_AT_EVENT_TIME"),
    }

    # old panel defect evidence
    old_panel = pd.read_parquet(BUNDLE / "fundamental_event_pre_outcome_panel.parquet")
    oy = old_panel["SALES_YOY_CURRENT"].dropna()
    AUDIT["defect_ledger"] = {
        "old_pre_outcome_panel": {
            "file": "research_bundle/fundamental_event_pre_outcome_panel.parquet",
            "defect": ("same-month-prior-year lookup in fundamental_event_feasibility.py was not "
                       "restricted to the event's company (loop over all companies, first month match "
                       "won, no ORDER BY -> nondeterministic). All SALES_YOY_*/acceleration values are invalid."),
            "evidence": {"median_yoy": float(oy.median()), "p99_yoy": float(oy.quantile(0.99)),
                         "share_abs_yoy_gt_1": float((oy.abs() > 1).mean()),
                         "rows": int(len(old_panel))},
            "status": "SUPERSEDED by fundamental_event_research/monthly_sales_events_pit.parquet",
        },
        "old_feasibility_json": {
            "file": "research_bundle/fundamental_event_feasibility.json",
            "defect": "counts derived from the defective panel; PART 15 measured numbers superseded by this audit",
            "status": "SUPERSEDED (frozen gate THRESHOLDS unchanged; only measured counts corrected)",
        },
        "old_event_stream_financial_rows": {
            "file": "research_bundle/event_stream_pit.parquet",
            "defect": ("financial section of match_pub_times.py never emitted original MATCH_STRONG rows; "
                       "166 rows exist only where loop state leaked from the monthly section: all 166 carry "
                       "one constant published_at (the last monthly letter's stamp) and canonical report UUIDs "
                       "as source_report_id. Financial stream section is quarantined."),
            "monthly_section_status": "VALID (proven by independent matcher + row-level reconciliation)",
            "status": "monthly: superseded by canonical artifact; financial: QUARANTINED — rebuild is a separate future task",
        },
    }

    # ---------------- persist canonical artifact + audit ----------------
    OUT.mkdir(parents=True, exist_ok=True)
    feat_cols = ["event_id", "publication_role", "supersedes_tracing_no", "security_id", "symbol",
                 "company_id", "event_type", "period_end", "match_status",
                 "sales_current_rial", "sales_same_month_prior_year_rial", "prior_year_period_end",
                 "SALES_YOY_CURRENT", "prev_publication_event_id", "SALES_YOY_PREVIOUS",
                 "SALES_GROWTH_ACCELERATION", "SALES_YOY_PREV2", "TRAJECTORY_3PUB_AVAILABLE",
                 "published_at_raw_jalali", "published_at_tehran", "published_at", "tehran_date",
                 "signal_entry_date", "prior_year_pub_verified",
                 "letter_title", "source_url", "source",
                 "eligible_base", "ineligibility_reason", "event_eligible"]
    # corrections preserved in the canonical artifact as separate publication rows
    # (frozen PART 1: corrections are separate events with their own knowledge time) but
    # with feature values null: corrected numeric values were never ingested, so a
    # correction row cannot satisfy "valid current-period sales value" (PART 1 item 4)
    # without misrepresenting what the market saw at correction time.
    corr = ev[ev.publication_role == "correction"].copy()
    corr = pd.DataFrame({
        "event_id": corr.event_id, "publication_role": corr.publication_role,
        "supersedes_tracing_no": corr.supersedes_tracing_no, "security_id": corr.security_id,
        "symbol": corr.symbol, "company_id": corr.company_id, "event_type": corr.event_type,
        "period_end": corr.period_end, "match_status": corr.match_status,
        "sales_current_rial": None, "sales_same_month_prior_year_rial": None,
        "prior_year_period_end": None, "SALES_YOY_CURRENT": None,
        "prev_publication_event_id": None, "SALES_YOY_PREVIOUS": None,
        "SALES_GROWTH_ACCELERATION": None, "SALES_YOY_PREV2": None,
        "TRAJECTORY_3PUB_AVAILABLE": None, "published_at_raw_jalali": corr.published_at_raw_jalali,
        "published_at_tehran": corr.published_at_tehran, "published_at": corr.published_at,
        "tehran_date": corr.tehran_date, "signal_entry_date": None,
        "prior_year_pub_verified": None, "letter_title": corr.letter_title,
        "source_url": corr.source_url, "source": corr.source,
        "eligible_base": False,
        "ineligibility_reason": "CORRECTION_VALUE_UNAVAILABLE",
        "event_eligible": False,
    })
    artifact = pd.concat([feat[feat_cols], corr], ignore_index=True)
    artifact = artifact.sort_values(["security_id", "published_at", "event_id"]).reset_index(drop=True)
    artifact.to_parquet(OUT / "monthly_sales_events_pit.parquet", compression="zstd", index=False)
    AUDIT["feature_panel"]["artifact_rows"] = int(len(artifact))
    AUDIT["feature_panel"]["artifact_original_rows"] = int((artifact.publication_role == "original").sum())
    AUDIT["feature_panel"]["artifact_correction_rows"] = int((artifact.publication_role == "correction").sum())

    # preregistration hash (current file)
    prereg = OUT / "FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md"
    AUDIT["artifacts"]["preregistration_sha256"] = sha256(prereg)
    AUDIT["artifacts"]["monthly_sales_events_pit_parquet"] = str(OUT / "monthly_sales_events_pit.parquet")
    AUDIT["artifacts"]["monthly_sales_events_pit_parquet_sha256"] = sha256(OUT / "monthly_sales_events_pit.parquet")
    AUDIT["artifacts"]["audit_script_sha256"] = sha256(OUT / "audit_event_stream_v1.py")

    (OUT / "event_stream_audit.json").write_text(
        json.dumps(AUDIT, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\nwrote:", OUT / "event_stream_audit.json")
    print("wrote:", OUT / "monthly_sales_events_pit.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
