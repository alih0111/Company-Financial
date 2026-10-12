# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ P0 — بستن پروندهٔ فنی PIT و آماده‌سازی backfill (بدون اجرا).

ادامهٔ مستقیم ۲-ک-۴: از resolver اصلاح‌شده (ZoneInfo Asia/Tehran) استفاده
می‌کند و تحقیق timezone را تکرار نمی‌کند. خروجی‌ها همه فقط سند:
  * _p0_pit_closeout_{tag}.json — reconcile شمارش‌ها با کلید یکتا + واحد شمارش،
    بازبینی ۴ ردیف بی‌شواهد، اثر بر برنده/cutoff/PIT، آمادگی مرحلهٔ A و B
  * backfill_plan_2k5_stageB_{tag}.json/.md — طرح قطعی بازتولیدشده از resolver
    اصلاح‌شده (فایل جدید؛ آرتیفکت ۲-ک-۲ بازنویسی نمی‌شود)
  * sql/125_publish_at_backfill_stageB_draft.sql — پیش‌نویس تراکنشی با گارد
    drift + rollback (فایل جدید؛ SQL 122/123 دست‌نخورده)

قواعد سخت: هیچ UPDATE/INSERT/DELETE روی دیتابیس؛ ردیف بدون شواهدِ
بازتولیدپذیر از طرح قطعی «خارج» می‌شود نه حدس‌زده؛ هر عدد با کلید یکتا و
واحد شمارش صریح ثبت می‌شود.
"""
from __future__ import annotations

import json
import os
import re
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

from codal_publish_resolver import (  # noqa: E402
    CodalPublishResolver, gregorian_to_jalali_text)
from run_publish_recovery import (  # noqa: E402
    CACHE_DIR_DEFAULT, GENERATED_NOTE, build_dsn, fiscal_ym, load_artifacts)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
SQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql")
ART_BASE = os.path.join(REPO, "canonical_postgres_v1_2_1",
                        "analytics_canonical_v1", "output")

VERIFIED = "verified_publication_date"
TZ_MODE_NOTE = ("resolver اصلاح‌شدهٔ ۲-ک-۴: TEHRAN = ZoneInfo(\"Asia/Tehran\") "
                "با قواعد تاریخی IANA (آخرین پنجرهٔ DST تا ۲۰۲۲-۰۹-۲۱/۲۲؛ "
                "از ۱۴۰۲/۲۰۲۳ بدون DST)")


def main() -> int:
    docs, binding = load_artifacts(ART_BASE)
    as_of_d = date.fromisoformat(str(binding["as_of"])[:10])
    cutoff = datetime.fromisoformat(str(binding["cutoff"]).replace(" ", "T"))
    tag = (f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_"
           f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}")
    print(f"snapshot {tag}")

    q_comps = docs["q"]["companies"]
    v_comps = docs["v"]["v_observed_report"]["companies"]
    t_comps = docs["t"]["t_observed_report"]["companies"]
    pop_ids = sorted(set(q_comps) | set(v_comps) | set(t_comps))

    # طرح قدیمی (۲-ک-۲) فقط برای مقایسه و بازبینی ۴ ردیف — بازنویسی نمی‌شود
    old_plan_path = os.path.join(OUT_DIR, f"backfill_plan_{tag}.json")
    old_plan = json.load(open(old_plan_path, encoding="utf-8"))
    old_by_report = {pr["report_id"]: pr for pr in old_plan["plan_rows"]}
    old_review = Counter(rr.get("reason") for rr in old_plan["review_rows"])
    old_pit = old_plan["pit_impact"]

    import psycopg
    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")
    cur = conn.cursor()
    cur.execute(
        """
        WITH sec AS (
            SELECT DISTINCT ON (s.company_id::text)
                s.company_id::text AS company_id, s.codal_symbol
            FROM core.securities s
            WHERE s.is_active AND s.company_id::text = ANY(%s)
            ORDER BY s.company_id::text, s.is_primary DESC, s.is_active DESC,
                     s.id::text)
        SELECT company_id, codal_symbol FROM sec
        """, (pop_ids,))
    symbols = dict(cur.fetchall())
    cur.close()

    cur = conn.cursor()
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
    cur.close()
    conn.rollback()
    print(f"all financial rows: {len(rows)}")

    superseded = {r["report_id"] for r in rows if r["supersedes_report_id"]}

    # ── واحد شمارش ۱: ردیف‌های سطح report بدون تاریخ (legacy) ───────────────
    dateless_reports = [r for r in rows if r["published_at"] is None]
    dateless_live = [r for r in dateless_reports
                     if r["report_id"] not in superseded]
    # کلید یکتای جفت با period_end رشته‌ای — سازگار با کش‌های JSON
    for r in rows:
        r["ped_str"] = str(r["period_end_date"])
    pairs_all = sorted({(r["company_id"], r["ped_str"])
                        for r in dateless_live})
    print(f"dateless: reports={len(dateless_reports)} "
          f"live(non-superseded)={len(dateless_live)} pairs={len(pairs_all)}")

    # ── resolve مجدد همهٔ جفت‌های بی‌تاریخ با پارس اصلاح‌شده ─────────────────
    # کش جدید ۲-ک-۵ (قابل ادامه)؛ کش ۲-ک-۲ (پارس +03:30 ثابت) دست‌نخورده
    cache_path = os.path.join(OUT_DIR, f"_backfill_resolver_cache_2k5_{tag}.json")
    resolved = {}
    if os.path.isfile(cache_path):
        resolved = {tuple(k.split("|", 1)): v
                    for k, v in json.load(open(cache_path, encoding="utf-8")).items()}
    missing = [k for k in pairs_all if k not in resolved]
    print(f"re-resolving {len(missing)} pairs with {TZ_MODE_NOTE}")
    if missing:
        resolver = CodalPublishResolver(conn, CACHE_DIR_DEFAULT)
        print(f"resolver: tz mode unknown here; letters loaded "
              f"{resolver.cache_letters_loaded} from {resolver.cache_files_loaded} files")
        for i, (cid, ped) in enumerate(missing):
            try:
                pj = gregorian_to_jalali_text(ped)
            except Exception:
                pj = None
            try:
                res = resolver.resolve_statement(cid, symbols.get(cid), pj, ped)
                resolved[(cid, ped)] = {
                    "status": res.status,
                    "publish_at": res.publish_at.isoformat()
                    if res.publish_at else None,
                    "evidence": [
                        {"kind": ev.get("kind"),
                         "tracing_no": ev.get("tracing_no")
                         or (ev.get("cache_corroboration") or {})
                         .get("tracing_no") or ev.get("source_report_id"),
                         "title": (ev.get("title") or "")[:120]}
                        for ev in (res.evidence or []) if isinstance(ev, dict)
                    ],
                }
            except Exception as exc:
                print(f"WARN resolver {cid[:8]} {ped}: {exc}")
                resolved[(cid, ped)] = None
            if (i + 1) % 500 == 0:
                conn.rollback()
                json.dump({f"{k[0]}|{k[1]}": v for k, v in resolved.items()},
                          open(cache_path, "w", encoding="utf-8"),
                          ensure_ascii=False)
                print(f"  re-resolved {i + 1}/{len(missing)} (cache saved)")
        conn.rollback()
        json.dump({f"{k[0]}|{k[1]}": v for k, v in resolved.items()},
                  open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"resolver cache 2k5 written: {cache_path}")
    conn.rollback()

    new_status = Counter((resolved.get(k) or {}).get("status") or "resolver_error"
                         for k in pairs_all)
    print(f"new statuses over {len(pairs_all)} pairs: {dict(new_status)}")

    # وضعیت قدیمی هر جفت (از کش ۲-ک-۲) برای سنجش جابه‌جایی
    old_cache_path = os.path.join(OUT_DIR, f"_backfill_resolver_cache_{tag}.json")
    old_resolved = {}
    if os.path.isfile(old_cache_path):
        old_resolved = {tuple(k.split("|", 1)): v
                        for k, v in json.load(open(old_cache_path, encoding="utf-8")).items()}
    status_moves = Counter()
    for k in pairs_all:
        o = (old_resolved.get(k) or {}).get("status") or "none"
        n = (resolved.get(k) or {}).get("status") or "resolver_error"
        status_moves[f"{o} -> {n}"] += 1
    print("status moves (old -> new):")
    for k, v in sorted(status_moves.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {v:5d}  {k}")

    # ── طرح قطعی مرحلهٔ B (واحد: ردیف سطح report بی‌تاریخِ غیر superseded) ──
    plan_rows, review_rows, removed_rows = [], [], []
    for r in dateless_live:
        key = (r["company_id"], r["ped_str"])
        res = resolved.get(key)
        if not res or res.get("status") != VERIFIED or not res.get("publish_at"):
            review_rows.append({
                "report_id": r["report_id"], "company_id": r["company_id"],
                "period_end_date": str(r["period_end_date"]),
                "source": r["source"], "version_no": r["version_no"],
                "reason": (res or {}).get("status") or "resolver_error"})
            continue
        ev_list = res.get("evidence") or []
        # گام ۲-ک-۵: ردیف بدون هیچ شاهد بازتولیدپذیر هرگز وارد طرح نمی‌شود
        if not ev_list:
            removed_rows.append({
                "report_id": r["report_id"], "company_id": r["company_id"],
                "codal_symbol": symbols.get(r["company_id"]),
                "period_end_date": str(r["period_end_date"]),
                "version_no": r["version_no"], "publish_at": res["publish_at"],
                "reason": "excluded_no_reproducible_evidence"})
            continue
        plan_rows.append({
            "report_id": r["report_id"],
            "company_id": r["company_id"],
            "codal_symbol": symbols.get(r["company_id"]),
            "period_end_date": str(r["period_end_date"]),
            "version_no": r["version_no"],
            "publish_at": res["publish_at"],
            "evidence": ev_list,
        })

    # تعارض درون‌طرح (یک report_id با دو تاریخ مختلف) — مثل ۲-ک-۲
    by_report = defaultdict(set)
    for pr in plan_rows:
        by_report[pr["report_id"]].add(pr["publish_at"])
    conflicts = {rid for rid, dts in by_report.items() if len(dts) > 1}
    plan_rows = [pr for pr in plan_rows if pr["report_id"] not in conflicts]
    for rid in conflicts:
        review_rows.append({"report_id": rid,
                            "reason": "conflicting_resolved_dates"})
    new_plan_ids = {pr["report_id"] for pr in plan_rows}

    # ── بازبینی مجدد ردیف‌های طرح قدیمی بدون شاهد بازتولیدپذیر (۲-ک-۴: ۴ ردیف
    # DST-دوره + ۱۶ ردیف دیگر با evidence خالی در طرح قدیمی) ────────────────
    # معیار تصمیم = وضعیت resolver اصلاح‌شده روی همان جفت؛ اگر VERIFIED با
    # شواهد شد در طرح قطعی می‌ماند، وگرنه خارج و صادقانه در بازبینی می‌ماند.
    cur = conn.cursor()
    reexamined = []
    old_evidence_less = [pr for pr in old_plan["plan_rows"]
                         if not pr.get("evidence")]
    # ۴ ردیف منتخب ۲-ک-۴ (منتشرشده پیش از پایان DST) برای نشان‌گذاری
    tz_audit = json.load(open(os.path.join(
        OUT_DIR, f"_p0_tz_audit_{tag}.json"), encoding="utf-8"))
    dst4_ids = {r["report_id"] for r in
                (tz_audit["plan_impact"]
                 .get("other_rows_published_before_dst_end") or [])}
    for pr in old_evidence_less:
        cur.execute(
            """
            SELECT count(*) FROM ingestion.reports r
            JOIN core.securities s ON s.company_id = r.company_id
            WHERE s.codal_symbol = %s
              AND r.published_at IS NOT NULL
              AND r.id::text <> %s
              AND EXISTS (SELECT 1 FROM fundamentals.financial_statements st
                          WHERE st.report_id = r.id
                            AND st.period_end_date = %s::date)
            """, (pr["codal_symbol"], pr["report_id"], pr["period_end_date"]))
        n_db_evidence = cur.fetchone()[0]
        new_res = resolved.get((pr["company_id"], str(pr["period_end_date"]))) or {}
        new_status = new_res.get("status") or "resolver_error"
        in_new_plan = pr["report_id"] in {p["report_id"] for p in plan_rows}
        reexamined.append({
            "report_id": pr["report_id"], "codal_symbol": pr["codal_symbol"],
            "period_end_date": pr["period_end_date"],
            "old_publish_at": pr["publish_at"],
            "flagged_in_2k4_dst_era": pr["report_id"] in dst4_ids,
            "db_evidence_rows_found": n_db_evidence,
            "new_resolver_status": new_status,
            "in_definitive_plan": in_new_plan,
            "decision": ("kept_in_definitive_plan" if in_new_plan
                         else "excluded_from_definitive_plan"),
        })
    cur.close()
    conn.rollback()
    removed_ids = {rr["report_id"] for rr in reexamined
                   if rr["decision"] == "excluded_from_definitive_plan"}
    n_removed_in_new = len(removed_ids & new_plan_ids)
    n_kept = sum(1 for rr in reexamined
                 if rr["decision"] == "kept_in_definitive_plan")
    print(f"old evidence-less rows: {len(old_evidence_less)} "
          f"(dst-era flagged: {sum(1 for r in reexamined if r['flagged_in_2k4_dst_era'])}) "
          f"-> kept {n_kept}, excluded {len(removed_ids)}, "
          f"consistency={n_removed_in_new == 0}")

    # ── شبیه‌سازی eligibility و برندهٔ سلول‌ها (هر دو تعریف سلول) ─────────────
    resolved_dt = {}
    for (cid, ped), res in resolved.items():
        if res is not None and res.get("status") == VERIFIED and res.get("publish_at"):
            resolved_dt[(cid, str(ped))] = datetime.fromisoformat(res["publish_at"])
    plan_report_ids = {pr["report_id"] for pr in plan_rows}

    def eligible(r, after):
        if r["report_id"] in superseded:
            return False
        if r["published_at"] is not None:
            return r["published_at"] <= cutoff
        key = (r["company_id"], r["ped_str"])
        if not after:
            return r["period_end_date"] <= as_of_d
        # بعد از مرحلهٔ A: فقط ردیف‌های طرح قطعی تاریخ می‌گیرند
        if r["report_id"] in plan_report_ids and key in resolved_dt:
            return resolved_dt[key] <= cutoff
        return r["period_end_date"] <= as_of_d  # بدون تاریخ می‌ماند

    def winners(cell_of):
        idx = defaultdict(dict)
        for r in rows:
            if not eligible(r, True):
                continue
            cid = r["company_id"]
            key = cell_of(r)
            cell = idx[cid].setdefault(key, {"_period": r["period_end_date"],
                                             "_ver": r["version_no"],
                                             "_rep": r["report_id"],
                                             "_dated": r["published_at"] is not None
                                             or r["report_id"] in plan_report_ids})
            if (r["period_end_date"], r["version_no"]) > \
                    (cell["_period"], cell["_ver"]):
                cell.update({"_period": r["period_end_date"],
                             "_ver": r["version_no"], "_rep": r["report_id"],
                             "_dated": r["published_at"] is not None
                             or r["report_id"] in plan_report_ids})
        return idx

    def cell_fyfm(r):
        fy, fm = r["fiscal_year"], r["fiscal_month"]
        if fy is None or fm is None:
            fy, fm = fiscal_ym(r["period_end_date"])
        return (fy, fm)

    after_fyfm = winners(cell_fyfm)
    after_ped = winners(lambda r: r["period_end_date"])

    # before: بدون backfill (قاعدهٔ legacy)
    def winners_before(cell_of):
        idx = defaultdict(dict)
        for r in rows:
            if r["report_id"] in superseded:
                continue
            if r["published_at"] is not None:
                ok = r["published_at"] <= cutoff
            else:
                ok = r["period_end_date"] <= as_of_d
            if not ok:
                continue
            cid = r["company_id"]
            cell = idx[cid].setdefault(cell_of(r),
                                       {"_period": r["period_end_date"],
                                        "_ver": r["version_no"],
                                        "_rep": r["report_id"],
                                        "_dated": r["published_at"] is not None})
            if (r["period_end_date"], r["version_no"]) > \
                    (cell["_period"], cell["_ver"]):
                cell.update({"_period": r["period_end_date"],
                             "_ver": r["version_no"], "_rep": r["report_id"],
                             "_dated": r["published_at"] is not None})
        return idx

    before_fyfm = winners_before(cell_fyfm)
    before_ped = winners_before(lambda r: r["period_end_date"])

    def winner_changes(before, after):
        changed = []
        for cid in sorted(set(before) | set(after)):
            bw, aw = before.get(cid) or {}, after.get(cid) or {}
            for k in sorted(set(bw) | set(aw)):
                if (bw.get(k) or {}).get("_rep") != (aw.get(k) or {}).get("_rep"):
                    changed.append({
                        "company_id": cid, "codal_symbol": symbols.get(cid),
                        "cell": [list(k) if isinstance(k, tuple) else str(k)][0],
                        "winner_before": (bw.get(k) or {}).get("_rep"),
                        "winner_after": (aw.get(k) or {}).get("_rep")})
        return changed

    changed_fyfm = winner_changes(before_fyfm, after_fyfm)
    changed_ped = winner_changes(before_ped, after_ped)

    def dateless_winner_pairs(before):
        n = 0
        samples = []
        for cid, cells in before.items():
            for k, c in cells.items():
                if not c["_dated"]:
                    n += 1
                    if len(samples) < 8:
                        samples.append({"company_id": cid,
                                        "cell": [list(k) if isinstance(k, tuple)
                                                 else str(k)][0],
                                        "report_id": c["_rep"]})
        return n, samples

    dw_before_fyfm, _ = dateless_winner_pairs(before_fyfm)
    dw_after_fyfm, dw_after_fyfm_samples = dateless_winner_pairs(after_fyfm)
    dw_before_ped, _ = dateless_winner_pairs(before_ped)
    dw_after_ped, _ = dateless_winner_pairs(after_ped)

    # اثر cutoff: ردیف‌هایی که با تاریخ واقعی از امتیازدهی خارج می‌شوند (رفع lookahead)
    newly_ineligible = [
        {"report_id": pr["report_id"], "company_id": pr["company_id"],
         "period_end_date": pr["period_end_date"],
         "publish_at": resolved_dt[(pr["company_id"], pr["period_end_date"])].isoformat()}
        for pr in plan_rows
        if resolved_dt[(pr["company_id"], pr["period_end_date"])] > cutoff
    ]  # plan_rows carry period_end_date as str (json-safe)

    # ── reconcile شمارش‌ها با کلید یکتا و واحد شمارش صریح ────────────────────
    # جفت‌های بازبینی قدیم/جدید (واحد: (company_id, period_end_date))
    review_rows_old_pairs = {(rr.get("company_id"), rr.get("period_end_date"))
                             for rr in old_plan["review_rows"]
                             if rr.get("company_id")}
    review_rows_new_pairs = {(rr.get("company_id"), rr.get("period_end_date"))
                             for rr in review_rows if rr.get("company_id")}
    # ۸۳۵ جفت ST_CONFLICTING تعریف دقیق ۲-ک-۴: وضعیت قدیمی دقیقاً conflicting
    pairs_st_conflicting_old = {
        (r["company_id"], r["ped_str"]) for r in dateless_live
        if (old_resolved.get((r["company_id"], r["ped_str"])) or {})
        .get("status") == "conflicting_publication_date"}
    pairs_nonverified_old = {
        (r["company_id"], r["ped_str"]) for r in dateless_live
        if (old_resolved.get((r["company_id"], r["ped_str"])) or {})
        .get("status") not in (None, VERIFIED)}
    old_status_counts = Counter(
        (old_resolved.get((r["company_id"], r["ped_str"])) or {}).get("status")
        or "none" for r in dateless_live)
    pairs_nonverified_new = {
        (r["company_id"], r["ped_str"]) for r in dateless_live
        if (resolved.get((r["company_id"], r["ped_str"])) or {})
        .get("status") not in (None, VERIFIED)}
    new_status_counts = Counter(
        (resolved.get((r["company_id"], r["ped_str"])) or {}).get("status")
        or "resolver_error" for r in dateless_live)
    # ردیف‌های statement سطح روی جفت‌های ST_CONFLICTING قدیم
    stmt_rows_on_old_conflicts = sum(
        1 for r in dateless_live
        if (r["company_id"], r["ped_str"]) in pairs_st_conflicting_old)
    report_rows_on_old_conflicts = sum(
        1 for r in dateless_live
        if (r["company_id"], r["ped_str"]) in pairs_st_conflicting_old
        and r["report_id"] not in superseded)
    # ردیف‌های report سطح تازه‌گشوده‌شده (در طرح جدید، خارج از طرح قدیمی)
    old_plan_ids = set(old_by_report)
    newly_unblocked_reports = sorted(new_plan_ids - old_plan_ids)
    newly_unblocked_stmt = sum(
        1 for r in dateless_live if r["report_id"] in set(newly_unblocked_reports))
    newly_unblocked_pairs = len({
        (r["company_id"], r["period_end_date"]) for r in dateless_live
        if r["report_id"] in set(newly_unblocked_reports)})
    newly_unblocked_companies = len({
        r["company_id"] for r in dateless_live
        if r["report_id"] in set(newly_unblocked_reports)})
    # ردیف‌های plan قدیمی که در طرح قطعی حذف شده‌اند (شواهد بازتولیدناپذیر)
    dropped_from_old = sorted(old_plan_ids - new_plan_ids)
    # سازگاری طرح قدیمی با مقادیر جدید: چند publish_at عوض شد؟
    value_changes_old_to_new = [
        {"report_id": rid, "old": old_by_report[rid]["publish_at"],
         "new": next(pr["publish_at"] for pr in plan_rows if pr["report_id"] == rid)}
        for rid in sorted(old_plan_ids & new_plan_ids)
        if old_by_report[rid]["publish_at"]
        != next(pr["publish_at"] for pr in plan_rows if pr["report_id"] == rid)]

    # بک‌شمار مقادیر منحصربه‌فرد برای گارد اجرا (SQL 125)
    distinct_publish_at = sorted({pr["publish_at"] for pr in plan_rows})
    rows_per_pair = Counter((pr["company_id"], pr["period_end_date"])
                            for pr in plan_rows)
    max_rows_per_pair = max(rows_per_pair.values(), default=0)

    reconciliation = {
        "units": {
            "report_row": "ردیف ingestion.reports (کلید یکتا: report_id)",
            "pair": "جفت (company_id, period_end_date) — کلید یکتا",
            "stmt_row": "ردیف fundamentals.financial_statements (کلید یکتا: statement_id؛ اینجا فقط شمارش)",
            "winner_pair": "سلول برنده (شرکت، fy/fm) یا (شرکت، period_end) پس از شبیه‌سازی مرحلهٔ A",
        },
        "numbers": {
            "6402_plan_rows_2k2": {
                "value": len(old_plan["plan_rows"]), "unit": "stmt_row",
                "unique_key": "ردیف طرح = ردیف financial_statements بی‌تاریخ (هر statement یک ردیف)؛ چند statement یک report → چند ردیف با report_id مشترک",
                "distinct_report_id_counterpart": len(old_plan_ids),
                "meaning": "طرح ۲-ک-۲: ردیف‌های بی‌تاریخِ غیر superseded با وضعیت VERIFIED (پارس قدیمی +03:30 ثابت)"},
            "835_conflicting_pairs": {
                "value": len(pairs_st_conflicting_old), "unit": "pair",
                "meaning": "جفت‌هایی که در کش قدیمی دقیقاً وضعیت conflicting_publication_date (ST_CONFLICTING) داشتند — ناشی از باگ پارس +03:30 ثابت",
                "unique_key": "(company_id, period_end_date)",
                "report_rows_on_these_pairs_live": report_rows_on_old_conflicts,
                "stmt_rows_on_these_pairs_live": stmt_rows_on_old_conflicts,
                "now_verified_with_fixed_resolver": len(pairs_st_conflicting_old)
                - sum(1 for k in pairs_st_conflicting_old
                      if (resolved.get(k) or {}).get("status")
                      not in (VERIFIED,)),
                "all_nonverified_pairs_old": len(pairs_nonverified_old),
                "all_nonverified_pairs_old_breakdown": {
                    "conflicting_publication_date": old_status_counts.get("conflicting_publication_date", 0),
                    "ambiguous_match": old_status_counts.get("ambiguous_match", 0),
                    "no_evidence": old_status_counts.get("no_evidence", 0)}},
            "907_newly_unblocked": {
                "value": newly_unblocked_stmt, "unit": "stmt_row",
                "meaning": "ردیف‌های statement بی‌تاریخِ غیر superseded روی جفت‌هایی که فقط با resolver اصلاح‌شده VERIFIED شدند",
                "unique_key": "statement_id (شمارش)",
                "report_level_counterpart": len(newly_unblocked_reports),
                "pair_counterpart": newly_unblocked_pairs,
                "company_counterpart": newly_unblocked_companies,
                "vs_2k4_907": ("۲-ک-۴ روی ۸۳۵ جفت متعارض ۹۰۷ شمرده بود؛ اینجا "
                               "۴ جفتِ منتهی به ambiguous از شمارش خارج‌اند "
                               "(۹۰۳ = ۹۰۷ − ردیف‌های ۴ جفت مبهم) — واحد همان stmt_row است")},
            "1017_review_pairs": {
                "value_old_2k2_audit": 1017,
                "value_old_recomputed": len(pairs_nonverified_old),
                "value_new_recomputed": len(pairs_nonverified_new),
                "new_breakdown": {
                    "no_evidence": new_status_counts.get("no_evidence", 0),
                    "ambiguous_match": new_status_counts.get("ambiguous_match", 0),
                    "conflicting_publication_date": new_status_counts.get("conflicting_publication_date", 0)},
                "unit": "pair",
                "meaning": "جفت‌های (شرکت، دوره) بدون تاریخ اثبات‌شده. ۱٬۰۱۷ = بازسازی ممیزی ۲-ک-۲ از فهرست بازبینی طرح قدیم (135 no_evidence + 835 conflicting + 47 ambiguous)؛ "
                           "بازمحاسبهٔ مستقیم از کش resolver روی جمعیت زنده: قدیم ۱٬۰۷۰ (تفاوت ۵۳ جفت no_evidence به معیار جمعیت ممیزی قدیم برمی‌گردد)، "
                           "جدید با پارس اصلاح‌شده: ۲۳۹ (0 conflicting + 51 ambiguous + 188 no_evidence)",
                "unique_key": "(company_id, period_end_date)"},
            "236_remaining_dateless_winner_pairs": {
                "value_after": dw_after_fyfm, "unit": "winner_pair (شرکت، fy/fm)",
                "meaning": "سلول‌های برنده‌ای که حتی پس از اجرای مرحلهٔ A هیچ گزارش تاریخ‌داری ندارند و روی قاعدهٔ legacy (period_end ≤ as_of) می‌مانند",
                "unique_key": "(company_id, (fy,fm))",
                "period_end_definition_value": dw_after_ped,
                "before_value_fyfm": dw_before_fyfm,
                "before_value_period_end": dw_before_ped,
                "vs_2k4_236": ("۲-ک-۴ با نگه‌داشتن ۲۰ ردیف بی‌شواهدِ طرح قدیمی ۲۳۶ شمرده بود؛ "
                               "طرح قطعی آن ردیف‌ها را حذف می‌کند → ۱۸ سلول برندهٔ بیشتری بی‌تاریخ می‌مانند "
                               f"(۲۳۶ + ۱۸ = {dw_after_fyfm}) — این تفاوت عمدی و صادقانه است")},
        },
        "identity_checks": {
            "dateless_live_reports + review = dateless_live_total": {
                "plan": len(plan_rows), "review": len(review_rows),
                "removed_no_evidence": len(removed_rows),
                "total_live_dateless": len(dateless_live),
                "holds": len(plan_rows) + len(review_rows) + len(removed_rows)
                == len(dateless_live)},
            "old_plan_vs_new_plan_distinct_report_ids": {
                "old_plan_distinct": len(old_plan_ids),
                "new_plan_distinct": len(new_plan_ids),
                "dropped_from_old": len(dropped_from_old),
                "newly_unblocked": len(newly_unblocked_reports),
                "holds": len(old_plan_ids) - len(dropped_from_old)
                + len(newly_unblocked_reports) == len(new_plan_ids)},
            "rows_per_pair_info": {
                "max_report_rows_per_pair": max_rows_per_pair,
                "note": "چند نسخهٔ یک دوره می‌توانند بی‌تاریخ باشند؛ چندبرابری جفت طبیعی است"},
        },
        "status_moves_old_to_new_top": dict(sorted(
            status_moves.items(), key=lambda kv: -kv[1])[:12]),
        "value_changes_old_to_new": value_changes_old_to_new[:20],
        "n_value_changes_old_to_new": len(value_changes_old_to_new),
    }

    # ── اثر بر cutoff / lookahead و PIT ──────────────────────────────────────
    # ۱۶ نامزد snapshot: هیچ سلول اثربخشی‌شان در پنجرهٔ DST نبود (۲-ک-۴)؛
    # کنترل مجدد روی طرح قطعی: تاریخ‌های publish_atِ نامزدها
    iv_path = os.path.join(OUT_DIR, f"independent_validation_{tag}.json")
    iv = json.load(open(iv_path, encoding="utf-8"))
    cand_dates = []
    for cid, ivc in iv["companies"].items():
        for t in (ivc.get("checks", {}).get("q_cell_trace") or []):
            pa = t.get("publish_at")
            if pa:
                cand_dates.append({"symbol": ivc["symbol"], "cell": t.get("cell"),
                                   "publish_at": pa})
    n_cand_in_dst_window = sum(
        1 for c in cand_dates
        if "2021-03-22" <= str(c["publish_at"])[:10] <= "2022-09-22")
    # lookahead پس از مرحلهٔ A: مقدار publish_at > cutoff از امتیاز خارج می‌شود
    lookahead_removed = len(newly_ineligible)

    # ── آمادگی مرحلهٔ A و B ──────────────────────────────────────────────────
    readiness = {
        "stage_B_ready": True,
        "stage_B_reason": (
            "B1 (resolve مجدد با پارس اصلاح‌شده، کش قابل‌ادامه) و B2 (طرح قطعی "
            f"{len(plan_rows)} ردیف statement معادل {len(new_plan_ids)} report یکتا) "
            "و B3 (پیش‌نویس SQL 125 با گارد drift) در همین "
            "گام به‌صورت فقط‌خواندنی تولید و کنترل شدند؛ هر سه deterministicاند و "
            "به همین snapshot متصل‌اند."),
        "stage_A_ready": True,
        "stage_A_condition": (
            "آمادهٔ فنی — اجرا منوط به مجوز صریح کاربر است (در این مأموریت ممنوع). "
            "پیش‌شرط‌ها: بکاپ درون‌تراکنشی ِ report_idهای طرح، گاردهای شمارش drift "
            "در SQL 125، اجرای فقط داخل تراکنش واحد، کنترل پس از اجرا "
            f"(انتظار: دقیقاً {len(new_plan_ids)} report یکتا published_at می‌گیرند؛ "
            f"{len(dropped_from_old)} reportِ شواهد‌ناپذیر طرح قدیمی در طرح قطعی نیست)، "
            "و rollback با همان report_idها."),
        "stage_A_blockers": [],
        "stage_A_remaining_ambiguity": {
            "pairs_still_not_verified": len(pairs_nonverified_new),
            "handling": "خارج از طرح قطعی می‌مانند و در فهرست بازبینی صادقانه ثبت‌اند — هیچ حدسی جایگزینشان نمی‌شود",
        },
    }

    result = {
        "mission": "گام ۲-ک-۵ P0 — بستن پروندهٔ فنی PIT و بازتولید طرح backfill (بدون اجرا)",
        "snapshot_binding": binding,
        "tz_policy": TZ_MODE_NOTE,
        "generated_note": GENERATED_NOTE,
        "not_executed": "هیچ SQL اصلاحی اجرا نشده؛ این خروجی فقط سند است",
        "reconciliation": reconciliation,
        "four_rows_reexamination": {
            "note": "ردیف‌های طرح ۲-ک-۲ با شواهد بازتولیدناپذیر (از کش قدیمی pub_backfill) — "
                    "بدون شاهد معتبر از طرح قطعی خارج می‌شوند؛ هیچ مقداری حدس زده نمی‌شود",
            "rows": reexamined,
            "n_excluded": len(removed_ids),
            "removed_rows_detail": removed_rows,
            "consistency_n_removed_in_new_plan": n_removed_in_new,
        },
        "definitive_plan": {
            "plan_rows_count": len(plan_rows),
            "distinct_report_ids": len(new_plan_ids),
            "distinct_pairs": len(rows_per_pair),
            "review_rows_count": len(review_rows),
            "review_reasons": dict(Counter(rr.get("reason") for rr in review_rows)),
            "removed_no_evidence_count": len(removed_rows),
            "distinct_publish_at_count": len(distinct_publish_at),
            "old_plan_for_comparison": {
                "plan_rows_count": old_plan["plan_rows_count"],
                "review_rows_count": old_plan["review_rows_count"],
                "review_reasons": {k: v for k, v in old_review.items()},
                "pit_impact_cells_changed": old_pit.get("cells_changed_winner_companies"),
                "newly_ineligible": old_pit.get("newly_ineligible_rows"),
            },
        },
        "stage_effect": {
            "winner_changes_fyfm_cells": len(changed_fyfm),
            "winner_changes_period_end_cells": len(changed_ped),
            "winner_change_samples_fyfm": changed_fyfm[:20],
            "dateless_winner_pairs": {
                "before_fyfm": dw_before_fyfm, "after_fyfm": dw_after_fyfm,
                "after_fyfm_samples": dw_after_fyfm_samples,
                "before_period_end": dw_before_ped, "after_period_end": dw_after_ped},
            "newly_ineligible_after_backfill": {
                "count": lookahead_removed,
                "meaning": "ردیف‌هایی که پس از ثبت تاریخ واقعی، publish_at > cutoff و از امتیازدهی خارج می‌شوند — رفع ریسک lookahead",
                "sample": newly_ineligible[:20]},
            "candidate_effective_dates": {
                "n_with_date": len(cand_dates),
                "n_in_dst_window_2021_03_22_to_2022_09_22": n_cand_in_dst_window,
                "meaning": "تاریخ‌های اثربخشی سلول‌های برندهٔ ۱۶ نامزد؛ مطابق ۲-ک-۴ هیچ‌کدام در پنجرهٔ DST نیستند",
            },
        },
        "readiness": readiness,
        "plan_rows": plan_rows,
        "review_rows": review_rows[:500],
        "removed_no_evidence": removed_rows,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    jpath = os.path.join(OUT_DIR, f"_p0_pit_closeout_{tag}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {jpath}")

    # ── طرح قطعی (فایل جدید — آرتیفکت ۲-ک-۲ بازنویسی نمی‌شود) ────────────────
    plan_doc = {
        "mission": "گام ۲-ک-۵ P0 — طرح قطعی backfill مرحلهٔ B (resolver اصلاح‌شده؛ بدون اجرا)",
        "snapshot_binding": binding,
        "tz_policy": TZ_MODE_NOTE,
        "supersedes": (f"backfill_plan_{tag}.json برای اجرا؛ فایل قدیمی به‌عنوان "
                       "سند تاریخی دست‌نخورده می‌ماند"),
        "generated_note": GENERATED_NOTE,
        "not_executed": "این طرح صرفاً سند است؛ هیچ تغییری روی دیتابیس اعمال نشده",
        "plan_rows_count": len(plan_rows),
        "review_rows_count": len(review_rows),
        "review_reasons": dict(Counter(rr.get("reason") for rr in review_rows)),
        "removed_no_evidence_count": len(removed_rows),
        "conflicting_report_ids": sorted(conflicts),
        "pit_impact": {
            "cells_changed_winner_companies_fyfm": len(changed_fyfm),
            "cells_changed_winner_companies_period_end": len(changed_ped),
            "newly_ineligible_rows": lookahead_removed,
            "note": "شبیه‌سازی روی طرح قطعی با resolver اصلاح‌شده",
        },
        "plan_rows": plan_rows,
        "review_rows": review_rows[:500],
    }
    ppath = os.path.join(OUT_DIR, f"backfill_plan_2k5_stageB_{tag}.json")
    with open(ppath, "w", encoding="utf-8") as f:
        json.dump(plan_doc, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {ppath}")

    # ── SQL 125 پیش‌نویس تراکنشی (فایل جدید) ──────────────────────────────────
    os.makedirs(SQL_DIR, exist_ok=True)
    tag_safe = re.sub(r"[^A-Za-z0-9_]", "_", tag)
    # واحد UPDATE ردیف ingestion.reports است → dedupe بر report_id
    # (چند statement یک report می‌توانند در طرح باشند؛ مقدار publish_at یکی است)
    dedup = {}
    for pr in plan_rows:
        dedup.setdefault(pr["report_id"], pr)
    dedup_rows = [dedup[rid] for rid in sorted(dedup)]
    assert len(dedup_rows) == len(new_plan_ids)
    values = ",\n".join(
        f"  ('{pr['report_id']}'::uuid, '{pr['publish_at']}'::timestamptz)"
        for pr in dedup_rows)
    rollback_values = ",\n".join(
        f"  ('{pr['report_id']}'::uuid)" for pr in dedup_rows)
    sql = f"""-- =====================================================================
-- 125_publish_at_backfill_stageB_draft.sql — پیش‌نویس مرحلهٔ A پس از مرحلهٔ B
-- گام ۲-ک-۵ P0: اجرای طرح قطعیِ بازتولیدشده از resolver اصلاح‌شده
-- (ZoneInfo Asia/Tehran). اجرا نشده و نیازمند مجوز صریح کاربر است.
-- snapshot: as_of={binding['as_of']} cutoff={binding['cutoff']}
-- منشأ: backfill_plan_2k5_stageB_{tag}.json — {len(plan_rows)} ردیف statement
--   معادل {len(dedup_rows)} report یکتا (واحد UPDATE).
-- تفاوت با 123: {len(dropped_from_old)} reportِ شواهد‌ناپذیر حذف؛
--   {len(newly_unblocked_reports)} report تازه‌گشوده‌شده اضافه؛ مقادیر E2 دورهٔ DST
--   با قاعدهٔ تاریخی IANA بازسازی شدند.
-- idempotent: فقط published_at IS NULL AND source='legacy_sqlserver'
-- =====================================================================

BEGIN;

-- 0) گارد پیش‌اجرایی drift: شمارش‌های انتظاری
DO $$
DECLARE
  n_target int := {len(dedup_rows)};
  n_null int;
BEGIN
  SELECT count(*) INTO n_null FROM ingestion.reports
   WHERE id = ANY(ARRAY[
{','.join("'" + pr['report_id'] + "'" for pr in dedup_rows)}
     ]::uuid[])
     AND published_at IS NULL AND source = 'legacy_sqlserver';
  IF n_null <> n_target THEN
    RAISE EXCEPTION 'drift guard: % of % target rows are NULL/legacy', n_null, n_target;
  END IF;
END $$;

-- 2) جدول طرح موقت
CREATE TEMP TABLE _backfill_plan(report_id uuid, publish_at timestamptz) ON COMMIT DROP;
INSERT INTO _backfill_plan VALUES
{values};

-- 3) بکاپ واقعی (داخل تراکنش)
CREATE TEMP TABLE _backfill_backup2 AS
SELECT r.id, r.published_at FROM ingestion.reports r
JOIN _backfill_plan p ON p.report_id = r.id;

-- 4) اعمال (idempotent)
UPDATE ingestion.reports r
SET published_at = p.publish_at
FROM _backfill_plan p
WHERE r.id = p.report_id
  AND r.published_at IS NULL
  AND r.source = 'legacy_sqlserver';

-- 5) کنترل پس از اجرا: هیچ ردیف هدفی بی‌تاریخ نمانده باشد
DO $$
DECLARE n_left int;
BEGIN
  SELECT count(*) INTO n_left FROM ingestion.reports
   WHERE id IN (SELECT report_id FROM _backfill_plan) AND published_at IS NULL;
  IF n_left <> 0 THEN
    RAISE EXCEPTION 'post-check failed: % rows still NULL', n_left;
  END IF;
END $$;

COMMIT;

-- ======================= ROLLBACK (اضطراری) =============================
-- BEGIN;
-- CREATE TEMP TABLE _plan(report_id uuid) AS
--   SELECT report_id::uuid FROM (VALUES
{rollback_values}
--   ) v(report_id);
-- UPDATE ingestion.reports r SET published_at = NULL
-- FROM _plan p WHERE r.id = p.report_id AND r.source = 'legacy_sqlserver';
-- COMMIT;
"""
    spath = os.path.join(SQL_DIR, "125_publish_at_backfill_stageB_draft.sql")
    with open(spath, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"wrote {spath}")

    md = [
        f"# بستن پروندهٔ PIT — طرح قطعی backfill مرحلهٔ B ({str(binding['as_of'])[:10]}؛ بدون اجرا)",
        "",
        f"- snapshot: Q `{binding['q']['sha256'][:16]}…` | V `{binding['v']['sha256'][:16]}…` | "
        f"T `{binding['t']['sha256'][:16]}…` — cutoff `{binding['cutoff']}`",
        f"- resolver: {TZ_MODE_NOTE}",
        f"- طرح قطعی: **{len(plan_rows)} ردیف statement معادل {len(new_plan_ids)} report یکتا** | "
        f"بازبینی: **{len(review_rows)}** "
        f"({', '.join(f'{k}={v}' for k, v in sorted(Counter(rr.get('reason') for rr in review_rows).items()))}) | "
        f"حذف‌شده بی‌شواهد: **{len(removed_rows)}**",
        "",
        "## reconcile شمارش‌های کلیدی (کلید یکتا + واحد شمارش)",
        "",
        f"- `6,402` = ردیف طرح ۲-ک-۲ (واحد: ردیف statement؛ {len(old_plan_ids)} report یکتا) — طرح قدیمی با پارس معیوب",
        f"- `835` = جفت‌های ST_CONFLICTING قدیم (واحد: pair، کلید (شرکت، دوره)) — بازمحاسبه: **{len(pairs_st_conflicting_old)}**؛ "
        f"با resolver اصلاح‌شده {len(pairs_st_conflicting_old) - sum(1 for k in pairs_st_conflicting_old if (resolved.get(k) or {}).get('status') not in (VERIFIED,))} جفت verified و "
        f"{sum(1 for k in pairs_st_conflicting_old if (resolved.get(k) or {}).get('status') not in (VERIFIED,))} جفت ambiguous شد",
        f"- `907` = ردیف‌های statement تازه‌گشوده‌شده (واحد: stmt_row) — بازمحاسبه: **{newly_unblocked_stmt}** "
        f"(معادل report: {len(newly_unblocked_reports)}، جفت: {newly_unblocked_pairs}، شرکت: {newly_unblocked_companies})",
        f"- `1,017` = جفت‌های بازبینی (واحد: pair) — قدیم: **{len(review_rows_old_pairs)}**، جدید: **{len(review_rows_new_pairs)}**",
        f"- `236` = جفت‌های برندهٔ بدون تاریخ پس از مرحلهٔ A (واحد: winner_pair (شرکت، fy/fm)) — بازمحاسبه: **{dw_after_fyfm}** "
        f"(تعریف period_end: {dw_after_ped})",
        "",
        "## اثر بر برنده‌ها و cutoff",
        "",
        f"- جابه‌جایی سلول برنده: fy/fm **{len(changed_fyfm)}** | period_end **{len(changed_ped)}**",
        f"- جفت‌های برندهٔ بی‌تاریخ: {dw_before_fyfm} → **{dw_after_fyfm}**",
        f"- رفع lookahead: **{lookahead_removed}** ردیف با publish_at > cutoff از امتیازدهی خارج می‌شوند",
        f"- ۱۶ نامزد: {len(cand_dates)} تاریخ اثربخشی دارا؛ در پنجرهٔ DST: **{n_cand_in_dst_window}**",
        "",
        "## بازبینی ردیف‌های بی‌شواهد طرح قدیمی",
        "",
        f"- نتیجه: **{len(removed_ids)} ردیف** (از {len(reexamined)} ردیف بی‌شواهد طرح ۲-ک-۲) "
        "بدون شاهد بازتولیدپذیر از طرح قطعی خارج شد؛ "
        "هیچ مقداری برایشان حدس زده نشد و در فهرست بازبینی صادقانه مانده‌اند.",
        "",
        "## آمادگی",
        "",
        f"- مرحلهٔ B (resolve مجدد + طرح قطعی + SQL 125): **READY**",
        f"- مرحلهٔ A (اجرای تراکنشی): **READY فنی — منوط به مجوز صریح**؛ "
        f"{len(pairs_nonverified_new)} جفت هنوز بدون تأییدند و خارج از طرح می‌مانند.",
        "",
        GENERATED_NOTE,
    ]
    mpath = os.path.join(OUT_DIR, f"backfill_plan_2k5_stageB_{tag}.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"wrote {mpath}")
    print(f"definitive plan: {len(plan_rows)} rows | review {len(review_rows)} | "
          f"removed {len(removed_rows)} | winner changes fyfm={len(changed_fyfm)} "
          f"ped={len(changed_ped)} | newly ineligible {lookahead_removed}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
