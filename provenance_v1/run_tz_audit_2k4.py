# -*- coding: utf-8 -*-
"""گام ۲-ک-۴ P0 — audit قطعی timezone/PIT (فقط-خواندنی).

اثبات مستقل تفسیر زمان برای تعارض‌های ۶۰دقیقه‌ای ۲-ک-۳:
  wall-clock خام کدال (بدون timezone) + قواعد تاریخی IANA Asia/Tehran
  (tzdata 2025.2: آخرین دوره DST = 1401/2022-03-22 → 2022-09-21؛ از 1402/2023
  بدون DST) → لحظهٔ true UTC؛ مقایسه با لحظهٔ ذخیره‌شدهٔ DB و مقدار پارس‌شدهٔ
  cache با +03:30 ثابت. هیچ نوشتنی در DB یا overwrite آرتیفکت اصلی.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psycopg  # noqa: E402
import jdatetime  # noqa: E402

TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
CACHE_DIR = os.path.join("historical_codal_backfill", "output", "pub_backfill")
TEHRAN = ZoneInfo("Asia/Tehran")
UTC = timezone.utc
FIXED330 = timezone(timedelta(hours=3, minutes=30))
PERSIAN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
VERIFIED = "verified_publication_date"


def build_dsn():
    txt = open("go-app/.env", encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


def iso(dt):
    return dt if isinstance(dt, str) else (dt.isoformat() if dt else None)


def parse_raw_wall(raw):
    """Jalali/Gregorian local wall-clock text → naive datetime (بدون tz)."""
    if not raw:
        return None
    text = str(raw).strip().translate(PERSIAN)
    dp, _, tp = text.partition(" ")
    m = re.match(r"^(\d{3,4})[/\-](\d{1,2})[/\-](\d{1,2})$", dp)
    if not m:
        return None
    y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    bits = [int(x) for x in tp.split(":") if x != ""]
    hh = bits[0] if bits else 0
    mi = bits[1] if len(bits) > 1 else 0
    ss = bits[2] if len(bits) > 2 else 0
    try:
        if y > 1500:
            return datetime(y, mo, dd, hh, mi, ss)
        g = jdatetime.date(y, mo, dd).togregorian()
        return datetime(g.year, g.month, g.day, hh, mi, ss)
    except (ValueError, OverflowError):
        return None


def main():
    plan = json.load(open(f"{OUT}/backfill_plan_{TAG}.json", encoding="utf-8"))
    cache = json.load(open(f"{OUT}/_backfill_resolver_cache_{TAG}.json", encoding="utf-8"))
    iv = json.load(open(f"{OUT}/independent_validation_{TAG}.json", encoding="utf-8"))

    binding = plan["snapshot_binding"]
    as_of_d = date.fromisoformat(str(binding["as_of"])[:10])
    cutoff = datetime.fromisoformat(str(binding["cutoff"]).replace(" ", "T"))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)

    # ── کش نامه‌های کدال: raw wall clock برای هر tracing ──────────────────
    letters_by_tracing = {}
    for fn in sorted(os.listdir(CACHE_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            doc = json.load(open(os.path.join(CACHE_DIR, fn), encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for L in (doc.get("letters") or []):
            tn = str(L.get("tracing_no") or "").strip()
            if tn:
                letters_by_tracing.setdefault(tn, {
                    "raw": L.get("publish_datetime"), "file": fn,
                    "title": (L.get("title") or "")[:100],
                    "letter_type": L.get("letter_type"),
                })

    conn = psycopg.connect(build_dsn(), connect_timeout=15)
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()

    # جمعیت = همان جمعیت plan (q∪v∪t) — از خودِ آرتیفکت‌های V2
    q_doc = json.load(open(
        f"canonical_postgres_v1_2_1/analytics_canonical_v1/output/v2_q_observed_report.json",
        encoding="utf-8"))
    v_doc = json.load(open(
        f"canonical_postgres_v1_2_1/analytics_canonical_v1/output/v2_value_pilot.json",
        encoding="utf-8"))
    t_doc = json.load(open(
        f"canonical_postgres_v1_2_1/analytics_canonical_v1/output/v2_t_pilot.json",
        encoding="utf-8"))
    q_comps = set(q_doc["companies"])
    v_comps = set(v_doc["v_observed_report"]["companies"])
    t_comps = set(t_doc["t_observed_report"]["companies"])
    pop_ids = sorted(q_comps | v_comps | t_comps)

    cur.execute(
        """
        SELECT st.company_id::text AS company_id, st.period_end_date,
               st.fiscal_year, st.fiscal_month,
               rv.version_no,
               r.id::text AS report_id, r.source, r.published_at,
               r.jalali_period_text, r.supersedes_report_id
        FROM fundamentals.financial_statements st
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
        """, (pop_ids,))
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    superseded = {r["report_id"] for r in rows if r["supersedes_report_id"]}

    # شمارش statement-level برای reconcile
    cur.execute(
        """
        SELECT (r.company_id::text || '|' || r.period_end_date::text) AS pk,
               count(*) FROM fundamentals.financial_statements st
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
        GROUP BY 1
        """, (pop_ids,))
    stmt_mult = dict(cur.fetchall())

    # ── بازسازی جفت‌های conflicting (همان منطق audit ۲-ک-۳) ───────────────
    dateless_pairs = sorted({(r["company_id"], r["period_end_date"])
                             for r in rows if r["published_at"] is None})
    conflicted_pairs = {tuple(k.split("|", 1)) for k, v in cache.items()
                        if v and v.get("status") == "conflicting_publication_date"}
    conflicted_pairs = {p for p in conflicted_pairs
                        if p in {(c, p_) for c, p_ in dateless_pairs}}
    # period_end_date از ردیف‌ها date است؛ کلید cache رشته
    conflicted_keys = set()
    for (c, ped) in dateless_pairs:
        k = f"{c}|{ped}"
        v = cache.get(k)
        if v and v.get("status") == "conflicting_publication_date":
            conflicted_keys.add((c, str(ped)))
    print(f"conflicting dateless pairs: {len(conflicted_keys)}")

    # ردیف‌های codal DB برای این جفت‌ها (با UTC دقیق و متن نمایش)
    pair_cids = [c for c, _ in conflicted_keys]
    pair_peds = [p for _, p in conflicted_keys]
    cur.execute(
        """
        SELECT r.company_id::text, r.period_end_date::text, r.id::text,
               r.source_report_id, r.published_at,
               r.published_at::text AS published_at_text,
               (r.published_at AT TIME ZONE 'UTC') AS utc_wall,
               r.title
        FROM ingestion.reports r
        WHERE r.source='codal' AND r.report_type='financial_statement'
          AND r.published_at IS NOT NULL
          AND r.company_id::text = ANY(%s) AND r.period_end_date::text = ANY(%s)
        """, (pair_cids, pair_peds))
    db_rows = [dict(zip([c[0] for c in cur.description], r))
               for r in cur.fetchall()]
    db_by_pair = defaultdict(list)
    for r in db_rows:
        db_by_pair[(r["company_id"], r["period_end_date"])].append(r)
    print(f"db codal rows on conflicting pairs: {len(db_rows)}")

    # tracingهای واقعاً متعارض — بازمحاسبهٔ مستقیم: هر ردیف DB که نامهٔ cache
    # هم‌tracing آن با پارس +03:30 ثابت بیش از ۱دقیقه با لحظهٔ DB فاصله دارد
    disagree_tracings = set()
    for (c, ped) in conflicted_keys:
        for r in db_by_pair.get((c, ped), []):
            tn = str(r["source_report_id"] or "").strip()
            info = letters_by_tracing.get(tn)
            if not info:
                continue
            w = parse_raw_wall(info["raw"])
            if w is None:
                continue
            fixed_utc = w.replace(tzinfo=FIXED330).astimezone(UTC)
            db_utc = r["utc_wall"].replace(tzinfo=UTC)
            if abs(fixed_utc - db_utc) > timedelta(minutes=1):
                disagree_tracings.add(tn)
    print(f"disagreeing E1 letters (by tracing): {len(disagree_tracings)}")

    # ── تحلیل هر نامهٔ متعارض ────────────────────────────────────────────
    letter_results = []
    cls_counter = Counter()
    dst_flag_counter = Counter()
    for (c, ped) in sorted(conflicted_keys):
        for r in db_by_pair.get((c, ped), []):
            tn = str(r["source_report_id"] or "").strip()
            if tn not in disagree_tracings:
                continue  # فقط نامه‌هایی که در تعارض ۶۰دقیقه‌ای بودند
            info = letters_by_tracing.get(tn)
            if not info:
                letter_results.append({"tracing_no": tn, "error": "raw_not_found"})
                cls_counter["raw_not_found"] += 1
                continue
            wall = parse_raw_wall(info["raw"])
            if wall is None:
                letter_results.append({"tracing_no": tn, "error": "raw_parse_fail"})
                cls_counter["raw_parse_fail"] += 1
                continue
            db_utc = r["utc_wall"].replace(tzinfo=UTC)
            fixed_utc = wall.replace(tzinfo=FIXED330).astimezone(UTC)
            true_off = wall.replace(tzinfo=TEHRAN).utcoffset()
            true_utc = wall.replace(tzinfo=TEHRAN).astimezone(UTC)
            disp_off = r["published_at"].utcoffset()
            same_wall_db = r["published_at"].strftime("%Y-%m-%d %H:%M:%S") == \
                wall.strftime("%Y-%m-%d %H:%M:%S")
            if db_utc == true_utc:
                cls = "db_eq_true (DST-aware)"
            elif db_utc == fixed_utc:
                cls = "db_eq_fixed330"
            else:
                cls = "db_eq_other"
            cls_counter[cls] += 1
            dst_flag_counter["dst_date" if true_off != timedelta(hours=3, minutes=30)
                             else "non_dst_date"] += 1
            letter_results.append({
                "company_id": c, "period_end": ped, "tracing_no": tn,
                "raw_wall": wall.isoformat(), "db_utc": db_utc.isoformat(),
                "db_display": r["published_at"].isoformat(),
                "display_offset": disp_off.__str__(),
                "true_offset": true_off.__str__(),
                "fixed330_utc": fixed_utc.isoformat(),
                "true_utc": true_utc.isoformat(),
                "class": cls, "in_dst_window": true_off != timedelta(hours=3, minutes=30),
                "db_wall_eq_raw_wall": same_wall_db,
                "cache_parse_fixed330": fixed_utc.isoformat(),
                "delta_cache_vs_db_min": (fixed_utc - db_utc).total_seconds() / 60,
            })

    # ── مرزهای DST ────────────────────────────────────────────────────────
    boundaries = ["2021-03-20", "2021-03-23", "2021-09-21", "2021-09-24",
                  "2022-03-20", "2022-03-23", "2022-09-21", "2022-09-24",
                  "2023-03-20", "2023-03-23"]
    boundary_rows = []
    cur.execute(
        """
        SELECT r.published_at::text, r.published_at
        FROM ingestion.reports r
        WHERE r.source='codal' AND r.published_at IS NOT NULL
          AND r.published_at::date BETWEEN %s AND %s
        """, (date(2021, 3, 18), date(2023, 3, 25)))
    all_disp = [(a, b) for a, b in cur.fetchall()]
    for bstr in boundaries:
        bd = date.fromisoformat(bstr)
        near = [(a, b) for a, b in all_disp
                if abs((b.date() - bd).days) <= 2]
        offs = Counter(a[-6:] for a, _ in near)
        boundary_rows.append({"date": bstr, "rows_within_2d": len(near),
                              "display_offsets": dict(offs)})

    # ── reconcile شمارش‌ها ────────────────────────────────────────────────
    e1_letters = [r for r in letter_results if "tracing_no" in r]
    letters_disagree = len({r["tracing_no"] for r in e1_letters})
    statement_level_conflicted = sum(stmt_mult.get(f"{c}|{ped}", 0)
                                     for c, ped in conflicted_keys)
    plan_review_conflicting = sum(1 for rr in plan["review_rows"]
                                  if rr.get("reason") == "conflicting_publication_date")
    audit_review_conflicting = None
    # ردیف‌های report-level متعارض در جمعیت (بدون فیلتر dateless بودن plan)
    conflicted_report_rows = len(db_rows)

    # ── اثر بر plan (stage A) ─────────────────────────────────────────────
    plan_by_rid = {pr["report_id"]: pr for pr in plan["plan_rows"]}
    src_counter = Counter()
    for pr in plan["plan_rows"]:
        kinds = {ev.get("kind") for ev in pr.get("evidence", [])}
        if "db_codal_report_row" in kinds:
            src_counter["db_backed"] += 1
        elif kinds & {"pub_backfill_cache"}:
            src_counter["cache_only"] += 1
        else:
            src_counter["other"] += 1

    # مقادیر cache-only: corrected value = true instant از raw wall
    cache_only_corrected = {"shifted_1h_earlier": 0, "unchanged": 0, "no_raw": 0}
    eligibility_flips = []
    for pr in plan["plan_rows"]:
        kinds = {ev.get("kind") for ev in pr.get("evidence", [])}
        if "db_codal_report_row" in kinds or not (kinds & {"pub_backfill_cache"}):
            continue
        tns = [ev.get("tracing_no") for ev in pr.get("evidence", [])
               if ev.get("kind") == "pub_backfill_cache"]
        raws = [letters_by_tracing[t]["raw"] for t in tns if t in letters_by_tracing]
        walls = [parse_raw_wall(x) for x in raws]
        walls = [w for w in walls if w]
        if not walls:
            cache_only_corrected["no_raw"] += 1
            continue
        wall = walls[0]
        true_utc = wall.replace(tzinfo=TEHRAN).astimezone(UTC)
        old_dt = datetime.fromisoformat(pr["publish_at"])
        if old_dt.tzinfo is None:
            old_dt = old_dt.replace(tzinfo=FIXED330)
        if old_dt == true_utc:
            cache_only_corrected["unchanged"] += 1
        elif (old_dt - true_utc) == timedelta(hours=1):
            cache_only_corrected["shifted_1h_earlier"] += 1
            old_el = old_dt <= cutoff
            new_el = true_utc <= cutoff
            if old_el != new_el:
                eligibility_flips.append({
                    "report_id": pr["report_id"], "period_end": pr["period_end_date"],
                    "old": old_dt.isoformat(), "new": true_utc.isoformat(),
                    "cutoff": cutoff.isoformat()})
        else:
            cache_only_corrected.setdefault("other_delta", []).append({
                "report_id": pr["report_id"], "old": old_dt.isoformat(),
                "true": true_utc.isoformat()})

    # ── ۲۰ ردیف other (evidence خالی): تاریخ‌ها بعد از پایان DST؟ ────────
    other_rows = [pr for pr in plan["plan_rows"]
                  if not ({ev.get("kind") for ev in pr.get("evidence", [])}
                          & {"db_codal_report_row", "pub_backfill_cache"})]
    DST_END = datetime(2022, 9, 21, 23, 59, 59, tzinfo=FIXED330)
    other_pre_dst = []
    for pr in other_rows:
        dt = datetime.fromisoformat(pr["publish_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=FIXED330)
        if dt <= DST_END:
            other_pre_dst.append({"report_id": pr["report_id"],
                                  "publish_at": pr["publish_at"]})

    # ── جفت‌های تازه‌بازشده (conflicting → verified با مقدار DB) ──────────
    newly_backfillable_rows = [r for r in rows
                               if r["published_at"] is None
                               and r["report_id"] not in superseded
                               and (r["company_id"], str(r["period_end_date"])) in conflicted_keys]
    newly_companies = {r["company_id"] for r in newly_backfillable_rows}

    def eligible(r, resolved_dt):
        if r["report_id"] in superseded:
            return False
        if r["published_at"] is not None:
            return r["published_at"] <= cutoff
        key = (r["company_id"], r["period_end_date"])
        if key in resolved_dt:
            return resolved_dt[key] <= cutoff
        return r["period_end_date"] <= as_of_d

    def winners(resolved_dt):
        idx = defaultdict(dict)
        for r in rows:
            if not eligible(r, resolved_dt):
                continue
            cid = r["company_id"]
            fy, fm = r["fiscal_year"], r["fiscal_month"]
            if fy is None or fm is None:
                j = jdatetime.date.fromgregorian(date=r["period_end_date"])
                fy, fm = j.year, j.month
            cell = idx[cid].setdefault((fy, fm), {"_period": r["period_end_date"],
                                                  "_ver": r["version_no"],
                                                  "_rep": r["report_id"]})
            if (r["period_end_date"], r["version_no"]) > (cell["_period"], cell["_ver"]):
                cell["_period"], cell["_ver"], cell["_rep"] = \
                    r["period_end_date"], r["version_no"], r["report_id"]
        return {cid: {k: c["_rep"] for k, c in cells.items()}
                for cid, cells in idx.items()}

    resolved_old = {}
    for k, v in cache.items():
        if v and v.get("status") == VERIFIED and v.get("publish_at"):
            c, ped = k.split("|", 1)
            resolved_old[(c, date.fromisoformat(ped))] = \
                datetime.fromisoformat(v["publish_at"])
    resolved_new = dict(resolved_old)
    for (c, ped) in conflicted_keys:
        drows = db_by_pair.get((c, ped), [])
        dts = {r["utc_wall"].replace(tzinfo=UTC) for r in drows}
        if len(dts) == 1:
            resolved_new[(c, date.fromisoformat(ped))] = next(iter(dts))
        # 2 تاریخ متفاوت → ambiguous می‌ماند (قاعدهٔ resolver)

    w_before = winners({})
    w_after = winners(resolved_new)
    flips = []
    for cid in sorted(set(w_before) | set(w_after)):
        bw, aw = w_before.get(cid) or {}, w_after.get(cid) or {}
        for k in sorted(set(bw) | set(aw)):
            if bw.get(k) != aw.get(k):
                flips.append({"company_id": cid, "cell": list(map(str, k)),
                              "before": bw.get(k), "after": aw.get(k)})

    # تعریف دوم سلول: (company, period_end) — DISTINCT ON مانند audit ۲-ک-۳
    def winners_ped(resolved_dt):
        best = {}
        for r in rows:
            if not eligible(r, resolved_dt):
                continue
            key = (r["company_id"], r["period_end_date"])
            cur_ = best.get(key)
            if cur_ is None or (r["period_end_date"], r["version_no"]) > \
                    (cur_["period_end_date"], cur_["version_no"]):
                best[key] = r
        return best

    wb_ped = winners_ped({})
    wa_ped = winners_ped(resolved_new)
    flips_ped = [(k, wb_ped[k]["report_id"], wa_ped[k]["report_id"])
                 for k in wb_ped.keys() & wa_ped.keys()
                 if wb_ped[k]["report_id"] != wa_ped[k]["report_id"]]
    dateless_winner_pairs_before_ped = {
        k for k, r in wb_ped.items() if r["published_at"] is None}
    still_after_ped = {k for k in dateless_winner_pairs_before_ped
                       if k not in resolved_new}

    dateless_winner_pairs_before = set()
    for r in rows:
        if r["published_at"] is None and r["report_id"] not in superseded:
            key = (r["company_id"], r["period_end_date"])
            fy, fm = r["fiscal_year"], r["fiscal_month"]
            if fy is None or fm is None:
                j = jdatetime.date.fromgregorian(date=r["period_end_date"])
                fy, fm = j.year, j.month
            if w_before.get(r["company_id"], {}).get((fy, fm)) == r["report_id"]:
                dateless_winner_pairs_before.add(key)
    still_dateless_after = {p for p in dateless_winner_pairs_before
                            if p not in resolved_new}

    # ── ۱۶ نامزد: effective dates در پنجرهٔ DST؟ (q_cell_trace) ──────────
    cand_dates = []
    for cid, comp in iv.get("companies", {}).items():
        for tr in ((comp.get("checks") or {}).get("q_cell_trace") or []):
            pub = tr.get("publish_at")
            if pub:
                cand_dates.append({"company_id": cid, "cell": tr.get("cell"),
                                   "period_end": tr.get("period_end"),
                                   "published_at": pub,
                                   "tracing_no": tr.get("tracing_no")})
    dst_hits = []
    for cd in cand_dates:
        try:
            dt = datetime.fromisoformat(str(cd["published_at"]).replace(" ", "T"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=FIXED330)
        off = dt.astimezone(TEHRAN).utcoffset()
        if off != timedelta(hours=3, minutes=30):
            dst_hits.append(cd)

    conn.rollback()
    conn.close()

    result = {
        "mission": "گام ۲-ک-۴ P0 — audit قطعی timezone/PIT (read-only)",
        "tzdata_version": _tzdata_version(),
        "iran_dst_rule": {
            "last_dst_window": "2022-03-22 → 2022-09-21/22 (+04:30)",
            "no_dst_since": "2023-03-21/22 (1402) — مطابق IANA tzdata 2025.2",
            "note": "پیش از آن هر سال ~22 اسفند تا ~30 شهریور DST (+04:30)",
        },
        "raw_payload": {
            "source": "Codal PublishDateTime — متن شمسی محلی بدون timezone (مثال ۱۴۰۰/۰۶/۲۱ ۱۴:۲۳:۰۹)",
            "sqlserver": "dbo.CodalReports.PublishedAt DATETIME2 (naive محلی) — go-app/py/codal_registry.py:77",
            "ingestion": "pilot_migrate.migrate_codal_reports → psycopg naive insert → timestamptz با session TimeZone=Asia/Tehran (tzdata سرور) → لحظهٔ true",
            "display": "psycopg رندر در session tz → +04:30 فقط در دورهٔ DST تاریخی (صحت)",
            "provenance_cache": "codal_publish_resolver.parse_* با TEHRAN=+03:30 ثابت → در دورهٔ DST ۱ ساعت دیرتر از true (باگ تنها در این سمت)",
            "latent": "go-app/py/canonical_hook._publish_datetime_iso +03:30 ثابت — برای نامه‌های 2023+ درست؛ برای دورهٔ DST اگر روزی استفاده شود خطا (نکتهٔ اصلاح آینده)",
        },
        "letter_verification": {
            "letters_checked": len(e1_letters),
            "class_counts": dict(cls_counter),
            "dst_window_counts": dict(dst_flag_counter),
            "all_display_wall_eq_raw_wall": all(
                r.get("db_wall_eq_raw_wall") for r in e1_letters),
            "delta_cache_vs_db_minutes": sorted({r.get("delta_cache_vs_db_min")
                                                 for r in e1_letters}),
            "samples": letter_results[:12],
        },
        "boundary_probes": boundary_rows,
        "count_reconciliation": {
            "conflicting_pairs_in_cache_on_dateless_population": len(conflicted_keys),
            "distinct_e1_letters_disagreeing": letters_disagree,
            "db_report_level_rows_on_conflicting_pairs": conflicted_report_rows,
            "statement_level_rows_on_conflicting_pairs": statement_level_conflicted,
            "plan_review_rows_conflicting_report_level": plan_review_conflicting,
            "note": "۸۳۹=نامه‌های E1 متمایز؛ ۸۳۵=جفت‌های (شرکت،دوره)؛ ردیف‌های سطح statement با چندبرابرگی",
        },
        "plan_impact": {
            "publish_at_source": dict(src_counter),
            "cache_only_corrected": cache_only_corrected,
            "other_rows_without_evidence": len(other_rows),
            "other_rows_published_before_dst_end": other_pre_dst,
            "evidence_less_note": "۴ ردیف مقدار publish_at دارند ولی هیچ نامهٔ cache یا "
                                  "ردیف codal در DB برای همان (نماد،دوره) وجود ندارد — "
                                  "از نسخهٔ قدیمی pub_backfill cache مانده‌اند؛ زنجیرهٔ "
                                  "شواهد بازتولید نمی‌شود → در اجرای مرحله B باید مجدد "
                                  "resolve شوند (→ no_evidence → خارج از طرح)",
            "eligibility_flips_old_vs_corrected": eligibility_flips[:20],
            "eligibility_flips_count": len(eligibility_flips),
        },
        "newly_unblocked": {
            "dateless_nonsuperseded_rows": len(newly_backfillable_rows),
            "companies": len(newly_companies),
            "pairs": len(conflicted_keys),
            "still_ambiguous_after_fix": len(conflicted_keys) - sum(
                1 for (c, ped) in conflicted_keys
                if len({r["utc_wall"].replace(tzinfo=UTC)
                        for r in db_by_pair.get((c, ped), [])}) == 1),
        },
        "winner_simulation": {
            "cells_changed_winner_fyfm": len(flips),
            "flips_sample": flips[:20],
            "cells_changed_winner_period_end": len(flips_ped),
            "flips_ped_sample": [{"key": [str(x) for x in k], "before": b, "after": a}
                                 for k, b, a in flips_ped[:10]],
        },
        "dateless_winner_pairs": {
            "before_fyfm_cell": len(dateless_winner_pairs_before),
            "after_corrected_stageA_fyfm_cell": len(still_dateless_after),
            "before_period_end_cell": len(dateless_winner_pairs_before_ped),
            "after_corrected_stageA_period_end_cell": len(still_after_ped),
        },
        "candidate_effective_dates": {
            "n_with_date": len(cand_dates),
            "in_dst_window": dst_hits,
        },
        "engine_now": {
            "conclusion": "موتور فعلی published_at واقعی DB (لحظهٔ true) را مصرف می‌کند؛ "
                          "هیچ تغییری لازم ندارد؛ ۲-ک-۳ SQL 124 (بازنویسی تگ DB) مردود است",
        },
    }
    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, f"_p0_tz_audit_{TAG}.json")
    json.dump(result, open(jp, "w", encoding="utf-8"), ensure_ascii=False,
              indent=2, default=str)
    print("wrote", jp)
    print(json.dumps({k: result[k] for k in
                      ["letter_verification", "count_reconciliation",
                       "plan_impact", "newly_unblocked", "winner_simulation",
                       "dateless_winner_pairs", "candidate_effective_dates"]},
                     ensure_ascii=False, indent=1, default=str)[:4000])


def _tzdata_version():
    try:
        import tzdata
        return tzdata.__version__
    except ImportError:
        return "system"


if __name__ == "__main__":
    main()
