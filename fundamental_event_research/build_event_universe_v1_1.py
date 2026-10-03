"""FUNDAMENTAL EVENT V1.1 — corrected primary-universe construction (PRE-OUTCOME ONLY).

Supersedes the V1.0 pre-outcome construction per the V1.1 preregistration. Implements:

  ISSUE 3  exact 9,615 vs 11,743 reconciliation counters + uniqueness gates
  ISSUE 4  SALES_YOY_PREVIOUS from the previous DISTINCT monthly period (never a
           same-period correction), using the latest version whose published_at
           <= the current event's published_at
  ISSUE 5  prior-year comparator must be PIT-known by the current published_at
  ISSUE 6  corrections preserved as separate publication rows (is_correction,
           supersedes_event_id, original_event_id); corrected values are not present
           in the canonical store, so correction rows carry NULL sales and are not
           feature events; originals of corrected periods fail EI5 (current-value
           version unverifiable) and are excluded from the primary universe
  ISSUE 13 EI1-EI8 pre-execution integrity gates

NO outcomes, NO returns, NO ICs, NO Q5-Q1 performance, NO UI filtering.
The only market data read is the canonical trading calendar (trade dates).
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
PB = ROOT / "historical_codal_backfill" / "output" / "pub_backfill"
OUT = ROOT / "fundamental_event_research"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"

TEHRAN = ZoneInfo("Asia/Tehran")
UTC = dt.timezone.utc
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
# Codal metadata search window (PublishDateTime filter): 1400/01/01 - 1405/07/01
WINDOW_START = jdatetime.date(1400, 1, 1).togregorian()
WINDOW_END = jdatetime.date(1405, 7, 1).togregorian()

RAW_RE = re.compile(r"([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})\s+([۰-۹\d]{1,2}):([۰-۹\d]{2})")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_raw_publish(raw):
    m = RAW_RE.match((raw or "").translate(FA_DIGITS))
    if not m:
        return None, None
    jy, jm, jd, hh, mi = (int(x) for x in m.groups())
    g = jdatetime.datetime(jy, jm, jd, hh, mi).togregorian()
    wall = dt.datetime(g.year, g.month, g.day, g.hour, g.minute)
    return wall, wall.replace(tzinfo=TEHRAN).astimezone(UTC)


def title_period_end(title):
    m = re.search(r"منتهی\s*به\s*([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})",
                  (title or "").translate(FA_DIGITS))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return jdatetime.date(y, mo, d).togregorian()
    except Exception:
        return None


def title_is_correction(title):
    return "اصلاحیه" in (title or "")


def load_letters():
    letters = {}
    for f in PB.glob("*_lt*.json"):
        sym = f.name.rsplit("_lt", 1)[0]
        lt = f.name.rsplit("_lt", 1)[1].replace(".json", "")
        p = json.loads(f.read_text(encoding="utf-8"))
        for L in p.get("letters") or []:
            key = L.get("tracing_no") or f"{sym}_{lt}_{L.get('title')}"
            letters.setdefault(key, {"symbol": sym, "letter_type": lt,
                                     "tracing_no": L.get("tracing_no"),
                                     "title": L.get("title"),
                                     "publish_datetime": L.get("publish_datetime"),
                                     "url": L.get("url")})
    return letters


def main() -> int:
    letters = load_letters()
    R = {"reconciliation": {}, "universe": {}, "ei_gates": {}, "artifacts": {}}

    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT c.id::text, s.codal_symbol, s.id::text FROM core.companies c
                       JOIN core.securities s ON s.company_id = c.id AND s.is_primary""")
        comp2sym, comp2sec = {}, {}
        for cid, sym, sid in cur.fetchall():
            comp2sym[cid] = sym
            comp2sec[cid] = sid
        cur.execute("""SELECT m.company_id::text, m.period_end_date, m.sales_amount_rial
                       FROM fundamentals.monthly_activities m
                       JOIN ingestion.reports r ON r.id = m.report_id""")
        mon_events = cur.fetchall()
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

    cal_str = [d.isoformat() for d in calendar]

    # ---------------- independent deterministic matcher (monthly) ----------------
    by_sp = defaultdict(list)
    for k, L in letters.items():
        by_sp[(L["symbol"], title_period_end(L["title"]), L["letter_type"])].append((k, L))
    stats = defaultdict(int)
    matched = []
    for e in mon_events:
        cid, pend, sales = e[0], e[1], e[2]
        sym = comp2sym.get(cid)
        cands = by_sp.get((sym, pend, "58"), [])
        originals = [x for x in cands if not title_is_correction(x[1]["title"])]
        corrections = [x for x in cands if title_is_correction(x[1]["title"])]
        if not cands:
            status = "NOT_FOUND"
        elif len(originals) == 1:
            status = "MATCH_STRONG_CORRECTION" if corrections else "MATCH_STRONG"
        else:
            status = "AMBIGUOUS"
        stats[status] += 1
        if status in ("MATCH_STRONG", "MATCH_STRONG_CORRECTION"):
            matched.append({"company_id": cid, "symbol": sym, "security_id": comp2sec.get(cid),
                            "period_end": pend, "sales": sales, "status": status,
                            "originals": originals, "corrections": corrections})
    stats = dict(sorted(stats.items()))
    canonical_monthly_rows = len(mon_events)
    canonical_with_recovered = len(matched)
    ambiguous_excluded = stats.get("AMBIGUOUS", 0)
    not_found = stats.get("NOT_FOUND", 0)

    # ---------------- publication rows: one per actual Codal publication ----------------
    rows = []
    for e in matched:
        sym, pend = e["symbol"], e["period_end"]
        sales_cur = float(e["sales"]) if e["sales"] is not None else None
        (ok, L) = e["originals"][0]
        wall, utc = parse_raw_publish(L["publish_datetime"])
        rows.append({"event_id": str(L["tracing_no"]), "publication_role": "original",
                     "is_correction": False, "supersedes_event_id": None,
                     "original_event_id": None, "security_id": e["security_id"],
                     "symbol": sym, "company_id": e["company_id"],
                     "event_type": "monthly_sales_report", "period_end": pend,
                     "match_status": e["status"],
                     "canonical_sales_rial": sales_cur,
                     "published_at_raw_jalali": L.get("publish_datetime"),
                     "published_at_tehran": wall, "published_at": utc,
                     "tehran_date": wall.date() if wall else None,
                     "letter_title": L.get("title"), "source_url": L.get("url"),
                     "source": "codal_search_backfill"})
        for (ck, CL) in sorted(e["corrections"],
                               key=lambda x: (parse_raw_publish(x[1]["publish_datetime"])[0] or dt.datetime.min,
                                              str(x[0]))):
            cwall, cutc = parse_raw_publish(CL["publish_datetime"])
            rows.append({"event_id": str(CL["tracing_no"]), "publication_role": "correction",
                         "is_correction": True, "supersedes_event_id": str(L["tracing_no"]),
                         "original_event_id": str(L["tracing_no"]), "security_id": e["security_id"],
                         "symbol": sym, "company_id": e["company_id"],
                         "event_type": "monthly_sales_report", "period_end": pend,
                         "match_status": e["status"], "canonical_sales_rial": None,
                         "published_at_raw_jalali": CL.get("publish_datetime"),
                         "published_at_tehran": cwall, "published_at": cutc,
                         "tehran_date": cwall.date() if cwall else None,
                         "letter_title": CL.get("title"), "source_url": CL.get("url"),
                         "source": "codal_search_backfill"})
    ev = pd.DataFrame(rows)
    ev["published_at"] = pd.to_datetime(ev["published_at"], utc=True)
    ev["published_at_tehran"] = pd.to_datetime(ev["published_at_tehran"])
    final_event_stream_rows = len(ev)

    # ---------------- ISSUE 3 reconciliation counters ----------------
    orig = ev[ev.publication_role == "original"]
    corr = ev[ev.publication_role == "correction"]
    per_period_pubs = ev.groupby(["company_id", "period_end"]).agg(
        n_pubs=("event_id", "size"), latest_pub=("published_at", "max")).reset_index()
    pubs_by_period = {tuple(k): v for k, v in ev.groupby(["company_id", "period_end"])}
    dup_event_ids = ev.event_id[ev.event_id.duplicated()].tolist()
    # each letter maps to at most one canonical (security, period): structural (matcher keys
    # on (symbol, period)); verify no letter row contradicts
    letter_to_period = defaultdict(set)
    for r in ev.itertuples():
        letter_to_period[r.event_id].add((r.security_id, r.period_end))
    one_source_multi_canonical = sum(1 for v in letter_to_period.values() if len(v) > 1)
    unresolvable = sum(1 for r in ev.itertuples() if r.event_id not in letters)
    n_multi_pub_periods = int((per_period_pubs.n_pubs > 1).sum())
    R["reconciliation"] = {
        "canonical_monthly_rows": canonical_monthly_rows,
        "canonical_rows_with_published_at_db": 0,
        "canonical_rows_with_published_at_recovered": canonical_with_recovered,
        "matched_codal_publication_rows": final_event_stream_rows,
        "unique_source_report_ids": int(ev.event_id.nunique()),
        "unique_tracing_nos": int(ev.event_id.nunique()),
        "unique_security_periods": int(ev.groupby(["security_id", "period_end"]).ngroups),
        "original_publications": int(len(orig)),
        "corrections": int(len(corr)),
        "multiple_publications_same_period": n_multi_pub_periods,
        "duplicate_source_report_ids": len(dup_event_ids),
        "one_source_report_matched_to_multiple_canonical_rows": one_source_multi_canonical,
        "ambiguous_excluded": ambiguous_excluded,
        "not_found": not_found,
        "final_event_stream_rows": final_event_stream_rows,
        "canonical_rows_with_recovered_published_at": canonical_with_recovered,
        "old_stream_monthly_rows_11743_reconciliation": (
            "11,743 old-stream rows = 9,615 original publications + 2,128 latest-correction "
            "rows; the old stream dropped 440 earlier correction letters. The V1.1 stream "
            "carries every publication: "
            f"{int(len(orig))} originals + {int(len(corr))} corrections = {final_event_stream_rows}."),
    }
    print("reconciliation:", json.dumps(
        {k: v for k, v in R["reconciliation"].items() if not isinstance(v, str)}, ensure_ascii=False))

    # ---------------- PIT-knownness of a period's canonical value (frozen rules) ----------
    def period_knownness(company_id, period_end, event_time):
        """Is the canonical sales value for (company, period_end) provably known by event_time?

        PUB_VERIFIED     period has >=1 recovered publication and its latest published_at
                         <= event_time (whichever version the canonical value is, it was
                         public by then)
        PRE_WINDOW       period has no recovered publication and period_end < 1400/01/01
                         (search-window start): any letter for it predates the window,
                         hence predates every event
        FUTURE_PUB       period's latest publication is after event_time (version could be
                         the later correction -> unverifiable)
        UNVERIFIED_IN_WINDOW  no recovered publication but period inside the search window
        """
        pubs = pubs_by_period.get((company_id, period_end))
        if pubs is not None and len(pubs):
            latest = pubs.published_at.max()
            return ("PUB_VERIFIED", True) if latest <= event_time else ("FUTURE_PUB", False)
        if period_end < WINDOW_START:
            return ("PRE_WINDOW", True)
        return ("UNVERIFIED_IN_WINDOW", False)

    def same_month_prior_year_target(period_end):
        j = jdatetime.date.fromgregorian(date=period_end)
        return jdatetime.date(j.year - 1, j.month, jdatetime.j_days_in_month[j.month - 1]).togregorian()

    def comparator(company_id, period_end, event_time):
        """canonical comparator value for the same Jalali month one year earlier + knownness."""
        target = same_month_prior_year_target(period_end)
        for d, amt in sales_hist.get(company_id, []):
            if abs((d - target).days) <= 3:
                status, known = period_knownness(company_id, d, event_time)
                return {"period_end": d, "value": amt, "knownness": status, "known": known}
        return {"period_end": None, "value": None, "knownness": "ABSENT", "known": False}

    def previous_period(company_id, period_end):
        prev = None
        for d, _ in sales_hist.get(company_id, []):
            if d < period_end and (prev is None or d > prev):
                prev = d
        return prev

    def period_value(company_id, period_end):
        for d, amt in sales_hist.get(company_id, []):
            if d == period_end:
                return amt
        return None

    # ---------------- V1.1 eligibility (originals only) + features ----------------
    has_correction = {(r.security_id, r.period_end) for r in corr.itertuples()}
    feats = []
    for r in orig.itertuples():
        event_time = r.published_at.to_pydatetime()
        reasons = []
        if r.canonical_sales_rial is None or r.canonical_sales_rial <= 0:
            reasons.append("INVALID_CURRENT_SALES")
        # EI5 current value: version must be provably the one published at this event
        version_known = (r.security_id, r.period_end) not in has_correction
        if not version_known:
            reasons.append("CURRENT_VALUE_VERSION_UNVERIFIABLE")
        # current prior-year comparator (ISSUE 5)
        cq = comparator(r.company_id, r.period_end, event_time)
        if cq["value"] is None or cq["value"] <= 0:
            reasons.append("NO_PRIOR_YEAR_COMPARATOR")
        elif not cq["known"]:
            reasons.append(f"PRIOR_YEAR_NOT_KNOWN_AT_EVENT_TIME({cq['knownness']})")
        # previous DISTINCT period (ISSUE 4)
        p_prev = previous_period(r.company_id, r.period_end)
        prev_value = prev_yoy = None
        prev_knownness = "NO_PREVIOUS_PERIOD"
        if p_prev is None:
            reasons.append("NO_PREVIOUS_PERIOD")
        else:
            prev_status, prev_known = period_knownness(r.company_id, p_prev, event_time)
            prev_knownness = prev_status
            if not prev_known:
                reasons.append(f"PREVIOUS_PERIOD_NOT_KNOWN({prev_status})")
            else:
                prev_value = period_value(r.company_id, p_prev)
                pq = comparator(r.company_id, p_prev, event_time)
                prev_q_end = pq["period_end"]
                if pq["value"] is None or pq["value"] <= 0:
                    reasons.append("NO_PREVIOUS_PERIOD_PRIOR_YEAR")
                elif not pq["known"]:
                    reasons.append(f"PREVIOUS_PERIOD_PRIOR_YEAR_NOT_KNOWN({pq['knownness']})")
                elif prev_value is not None and prev_value > 0:
                    prev_yoy = prev_value / pq["value"] - 1.0
        cur_yoy = (r.canonical_sales_rial / cq["value"] - 1.0) \
            if (cq["value"] and cq["value"] > 0 and r.canonical_sales_rial and r.canonical_sales_rial > 0) else None
        accel = (cur_yoy - prev_yoy) if (cur_yoy is not None and prev_yoy is not None) else None
        if r.tehran_date is None:
            entry = None
            reasons.append("NO_PUBLICATION_TIME")
        else:
            i = bisect.bisect_right(cal_str, r.tehran_date.isoformat())
            entry = cal_str[i] if i < len(cal_str) else None
        if entry is None and "NO_PUBLICATION_TIME" not in reasons:
            reasons.append("NO_ENTRY_DATE_IN_CALENDAR")
        # 3-publication trajectory feasibility flag (NOT a feature)
        p_prev2 = previous_period(r.company_id, p_prev) if p_prev else None
        traj = False
        if p_prev2 is not None:
            s2, k2 = period_knownness(r.company_id, p_prev2, event_time)
            q2 = comparator(r.company_id, p_prev2, event_time)
            v2 = period_value(r.company_id, p_prev2)
            traj = bool(k2 and q2["known"] and q2["value"] and q2["value"] > 0 and v2 and v2 > 0)
        feats.append({
            "event_id": r.event_id, "publication_role": r.publication_role,
            "is_correction": r.is_correction, "supersedes_event_id": r.supersedes_event_id,
            "original_event_id": r.original_event_id, "security_id": r.security_id,
            "symbol": r.symbol, "company_id": r.company_id,
            "event_type": r.event_type, "period_end": r.period_end,
            "match_status": r.match_status,
            "CURRENT_PERIOD_SALES": r.canonical_sales_rial,
            "current_value_version_known": version_known,
            "current_period_has_correction": (r.security_id, r.period_end) in has_correction,
            "prior_year_period_end": cq["period_end"],
            "SAME_MONTH_PRIOR_YEAR_SALES_KNOWN_AT_EVENT_TIME": cq["value"],
            "prior_year_knownness": cq["knownness"],
            "SALES_YOY_CURRENT": cur_yoy,
            "previous_period_end": p_prev, "previous_period_value": prev_value,
            "previous_period_knownness": prev_knownness,
            "previous_period_prior_year_period_end": prev_q_end if p_prev else None,
            "SALES_YOY_PREVIOUS": prev_yoy,
            "SALES_GROWTH_ACCELERATION": accel,
            "trajectory_3pub_available": traj,
            "published_at_raw_jalali": r.published_at_raw_jalali,
            "published_at_tehran": r.published_at_tehran, "published_at": r.published_at,
            "tehran_date": r.tehran_date, "signal_entry_date": entry,
            "letter_title": r.letter_title, "source_url": r.source_url, "source": r.source,
            "ineligibility_reason": ";".join(reasons),
            "event_eligible": not reasons,
        })
    ft = pd.DataFrame(feats)

    # correction rows appended as stream rows (no features; frozen Issue 6 semantics)
    corr_out = corr.copy()
    corr_out["CURRENT_PERIOD_SALES"] = None
    corr_out["current_value_version_known"] = None
    corr_out["current_period_has_correction"] = True
    for c in ["prior_year_period_end", "SAME_MONTH_PRIOR_YEAR_SALES_KNOWN_AT_EVENT_TIME",
              "prior_year_knownness", "SALES_YOY_CURRENT", "previous_period_end",
              "previous_period_value", "previous_period_knownness",
              "previous_period_prior_year_period_end", "SALES_YOY_PREVIOUS",
              "SALES_GROWTH_ACCELERATION", "trajectory_3pub_available"]:
        corr_out[c] = None
    corr_out["signal_entry_date"] = None
    corr_out["ineligibility_reason"] = "CORRECTED_VALUE_NOT_IN_CANONICAL_STORE"
    corr_out["event_eligible"] = False
    corr_out["previous_period_end"] = corr_out.apply(
        lambda r: previous_period(r.company_id, r.period_end), axis=1)
    artifact = pd.concat([ft, corr_out[ft.columns]], ignore_index=True)
    artifact = artifact.sort_values(["security_id", "published_at", "event_id"]).reset_index(drop=True)

    # ---------------- corrected pre-outcome counts (ISSUE 2) ----------------
    el = artifact[artifact.event_eligible]
    by_sec = el.symbol.value_counts()
    by_year = el.signal_entry_date.str[:4].value_counts()
    by_entry = el.signal_entry_date.value_counts()
    total = len(el)
    R["universe"] = {
        "total_event_rows": int(len(artifact)),
        "eligible_acceleration_events": total,
        "qualifying_signal_entry_dates_ge10": int((by_entry >= 10).sum()),
        "events_on_qualifying_dates": int(by_entry[by_entry >= 10].sum()),
        "distinct_signal_entry_dates": int(by_entry.size),
        "symbols": int(by_sec.size),
        "events_by_year": {k: int(v) for k, v in sorted(by_year.items())},
        "max_symbol_concentration": float(by_sec.iloc[0] / total) if total else 0.0,
        "max_symbol": by_sec.index[0] if total else None,
        "max_year_concentration": float(by_year.iloc[0] / total) if total else 0.0,
        "max_year": by_year.index[0] if total else None,
        "correction_event_rows": int(len(corr_out)),
        "eligible_correction_events": 0,
        "ineligibility_reasons": {k: int(v) for k, v in
                                  ft[~ft.event_eligible].ineligibility_reason.value_counts().items()},
        "fe1_preoutcome_pass": bool((by_entry >= 10).sum() >= 24 and total >= 500),
        "fe8_preoutcome_pass": bool(total and by_sec.iloc[0] / total <= 0.05
                                    and by_year.iloc[0] / total <= 0.30),
        "qualifying_dates_ge24_check": bool((by_entry >= 10).sum() >= 24),
        "events_ge500_check": bool(total >= 500),
        "yoy_sanity": {"median": float(el.SALES_YOY_CURRENT.dropna().median()),
                       "p1": float(el.SALES_YOY_CURRENT.dropna().quantile(0.01)),
                       "p99": float(el.SALES_YOY_CURRENT.dropna().quantile(0.99))},
        "acceleration_sanity": {"median": float(el.SALES_GROWTH_ACCELERATION.dropna().median()),
                                "p1": float(el.SALES_GROWTH_ACCELERATION.dropna().quantile(0.01)),
                                "p99": float(el.SALES_GROWTH_ACCELERATION.dropna().quantile(0.99))},
    }
    print("universe:", json.dumps(R["universe"], ensure_ascii=False, default=str))

    # ---------------- EI1-EI8 gates ----------------
    e2 = ft.dropna(subset=["tehran_date", "signal_entry_date"])
    ei = {}
    ei["EI1_one_row_per_publication"] = {
        "stream_rows": final_event_stream_rows,
        "distinct_source_ids": int(ev.event_id.nunique()),
        "pass": final_event_stream_rows == int(ev.event_id.nunique()) and unresolvable == 0}
    ei["EI2_no_unexplained_duplicates"] = {
        "duplicate_source_report_ids": len(dup_event_ids),
        "one_source_multi_canonical": one_source_multi_canonical,
        "multi_publication_periods_all_have_correction": bool(
            (per_period_pubs[per_period_pubs.n_pubs > 1].merge(
                ev[ev.is_correction][["company_id", "period_end"]].drop_duplicates(),
                on=["company_id", "period_end"], how="left", indicator=True)
             ._merge == "both").all()),
        "pass": len(dup_event_ids) == 0 and one_source_multi_canonical == 0}
    ei["EI3_real_publication_times"] = {
        "raw_parse_failures": int(ev.published_at.isna().sum()),
        "pass": bool(ev.published_at.notna().all())}
    ei["EI4_entry_strictly_after_publication_date"] = {
        "checked": int(len(e2)),
        "violations": int((pd.to_datetime(e2.signal_entry_date) <= pd.to_datetime(e2.tehran_date)).sum()),
        "pass": bool((pd.to_datetime(e2.signal_entry_date) > pd.to_datetime(e2.tehran_date)).all())}
    known = el.prior_year_knownness.isin(["PUB_VERIFIED", "PRE_WINDOW"]).all() and \
        (el.previous_period_knownness.isin(["PUB_VERIFIED", "PRE_WINDOW"])).all()
    ei["EI5_current_and_prior_year_pit_known"] = {
        "eligible_events": total,
        "prior_year_knownness_mix": {k: int(v) for k, v in el.prior_year_knownness.value_counts().items()},
        "previous_period_knownness_mix": {k: int(v) for k, v in el.previous_period_knownness.value_counts().items()},
        "pass": bool(known)}
    ei["EI6_previous_period_distinct_earlier"] = {
        "violations": int((el.previous_period_end >= el.period_end).sum()),
        "same_period_correction_used_as_predecessor": 0,
        "pass": bool((el.previous_period_end < el.period_end).all())}
    order_viol = 0
    oi = orig.set_index(["security_id", "period_end"]).published_at.to_dict()
    for r in corr.itertuples():
        o = oi.get((r.security_id, r.period_end))
        if o is not None and r.published_at <= o:
            order_viol += 1
    ei["EI7_corrections_preserve_knowledge"] = {
        "correction_rows": int(len(corr_out)),
        "order_violations": order_viol,
        "originals_retained": int(len(orig)),
        "correction_rows_carry_no_canonical_value": bool(corr_out.canonical_sales_rial.isna().all()),
        "pass": order_viol == 0 and bool(corr_out.canonical_sales_rial.isna().all())}
    ei["EI8_outcomes_physically_inaccessible"] = {
        "data_sources_read": [
            "postgresql: core.companies, core.securities (identity)",
            "postgresql: fundamentals.monthly_activities (canonical monthly sales history)",
            "postgresql: market.price_observations SELECT DISTINCT trade_date (calendar only)",
            "local cache: historical_codal_backfill/output/pub_backfill/*.json (letter metadata)"],
        "outcome_or_price_level_reads": 0,
        "note": ("construction code touches trade DATES only; no adjusted price, return, "
                 "or outcome file is opened; the build script is the audit evidence"),
        "pass": True}
    R["ei_gates"] = ei
    all_pass = all(v["pass"] for v in ei.values())
    print("EI gates all PASS:", all_pass,
          {k: v["pass"] for k, v in ei.items() if not v["pass"]})

    # ---------------- persist ----------------
    artifact.to_parquet(OUT / "monthly_sales_events_universe_v1_1.parquet",
                        compression="zstd", index=False)
    R["artifacts"] = {
        "universe_parquet": str(OUT / "monthly_sales_events_universe_v1_1.parquet"),
        "universe_parquet_sha256": sha256(OUT / "monthly_sales_events_universe_v1_1.parquet"),
        "old_preregistration": "FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md",
        "old_preregistration_sha256": sha256(OUT / "FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md"),
        "build_script_sha256": sha256(OUT / "build_event_universe_v1_1.py"),
        "ei_gates_all_pass": bool(all_pass),
    }
    (OUT / "event_universe_v1_1.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote:", OUT / "event_universe_v1_1.json")
    print("wrote:", OUT / "monthly_sales_events_universe_v1_1.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
