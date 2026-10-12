"""گام ۲-ک-۲ P3 — آماده‌سازی طرح دائمی backfill تاریخ انتشار (بدون اجرا).

خروجی‌ها (همه فقط سند؛ هیچ UPDATE/INSERT/DELETE روی دیتابیس انجام نمی‌شود):
  * backfill_plan_{tag}.json / .md  — مجموعه دقیق ردیف‌های واجد شرایط
    (report_id، تاریخ انتشار اثبات‌شده، منشأ شواهد، TracingNo) + کنترل تعارض
  * sql/122_publish_at_backfill_draft.sql — پیش‌نویس UPDATE idempotent +
    اسکریپت rollback + پیش‌نمایش تغییرات
  * شبیه‌سازی اثر روی PIT/انتخاب سلول‌ها: با تاریخ‌های جدید، کدام ردیف‌ها از
    گونهٔ «eligible بدون تاریخ» خارج می‌شوند و آیا سلول برندهٔ هیچ شرکتی عوض
    می‌شود (اثر بالقوه بر Q/V/T) — قبل از هر اعمال واقعی.

قواعد سخت: فقط ردیف‌هایی که تاریخ انتشارشان با شواهد واقعی (E1/E2 verified)
اثبات شده واجد شرایط‌اند؛ تعارض یا تطبیق مبهم = حذف از طرح و ثبت در فهرست
بازبینی. هیچ حدس یا الگوی تأخیری به‌کار نمی‌رود.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "provenance_v1"))
sys.path.insert(0, os.path.join(REPO, "canonical_postgres_v1_2_1",
                                "analytics_canonical_v1"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from codal_publish_resolver import (  # noqa: E402
    CodalPublishResolver, gregorian_to_jalali_text, norm_digits)
from run_publish_recovery import (  # noqa: E402
    CACHE_DIR_DEFAULT, GENERATED_NOTE, build_dsn, fiscal_ym, load_artifacts)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
SQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql")
ART_BASE = os.path.join(REPO, "canonical_postgres_v1_2_1",
                        "analytics_canonical_v1", "output")

VERIFIED = "verified_publication_date"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", default=ART_BASE)
    args = ap.parse_args()

    docs, binding = load_artifacts(args.artifact_dir)
    as_of_d = date.fromisoformat(str(binding["as_of"])[:10])
    cutoff = datetime.fromisoformat(str(binding["cutoff"]).replace(" ", "T"))
    tag = (f"{str(binding['as_of'])[:10]}_q{binding['q']['sha256'][:8]}_"
           f"v{binding['v']['sha256'][:8]}_t{binding['t']['sha256'][:8]}")
    print(f"snapshot {tag}")

    q_comps = docs["q"]["companies"]
    v_comps = (docs["v"]["v_observed_report"]["companies"])
    t_comps = (docs["t"]["t_observed_report"]["companies"])
    pop_ids = sorted(set(q_comps) | set(v_comps) | set(t_comps))
    print(f"population: {len(pop_ids)} companies")

    import psycopg
    conn = psycopg.connect(build_dsn())
    conn.execute("SET default_transaction_read_only = on")

    cur = conn.cursor()
    # نماد کدال هر شرکت
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

    # همه ردیف‌های مالی جمعیت (بدون پیش‌فیلتر) — برای شبیه‌سازی eligibility
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

    # رزالور فقط برای ردیف‌های بدون published_at (با کش محلی per snapshot)
    cache_path = os.path.join(OUT_DIR, f"_backfill_resolver_cache_{tag}.json")
    need = sorted({(r["company_id"], r["period_end_date"]) for r in rows
                   if r["published_at"] is None})
    resolved = {}
    if os.path.isfile(cache_path):
        cached = json.load(open(cache_path, encoding="utf-8"))
        resolved = {tuple(k.split("|", 1)): v for k, v in cached.items()}
        for k in [k for k, v in resolved.items() if v is None]:
            resolved[k] = None
    missing = [k for k in need if k not in resolved]
    if missing:
        resolver = CodalPublishResolver(conn, CACHE_DIR_DEFAULT)
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
            if (i + 1) % 1000 == 0:
                print(f"  resolved {i + 1}/{len(missing)}")
        conn.rollback()
        cache = {f"{k[0]}|{k[1]}": v for k, v in resolved.items()}
        json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                  ensure_ascii=False)
        print(f"resolver cache written: {cache_path}")
    conn.rollback()
    conn.close()

    # ── ردیف‌های واجد شرایط backfill + کنترل تعارض ──────────────────────────
    plan_rows = []
    review_rows = []
    for r in rows:
        if r["published_at"] is not None:
            continue  # فقط کمبود legacy
        if r["report_id"] in superseded:
            continue
        res = resolved.get((r["company_id"], r["period_end_date"]))
        if not res:
            review_rows.append({**_row_ref(r),
                                "reason": (res or {}).get("status")
                                or "resolver_error"})
            continue
        if res.get("status") != VERIFIED or not res.get("publish_at"):
            review_rows.append({**_row_ref(r), "reason": res.get("status")})
            continue
        pub_iso = res["publish_at"]
        # شواهد از کش (دیکشنری) یا مستقیم
        ev_list = res.get("evidence") or []
        plan_rows.append({
            "report_id": r["report_id"],
            "company_id": r["company_id"],
            "codal_symbol": symbols.get(r["company_id"]),
            "period_end_date": str(r["period_end_date"]),
            "version_no": r["version_no"],
            "publish_at": pub_iso,
            "evidence": ev_list,
        })

    # تعارض: اگر برای همان report_id چند تاریخ متفاوت از دوره‌های مختلف
    # بازیابی شده باشد؟ غیرممکن است (تاریخ per period)؛ اما کنترل دوبل:
    by_report = defaultdict(set)
    for pr in plan_rows:
        by_report[pr["report_id"]].add(pr["publish_at"])
    conflicts = {rid for rid, dts in by_report.items() if len(dts) > 1}
    plan_rows = [pr for pr in plan_rows if pr["report_id"] not in conflicts]
    for rid in conflicts:
        review_rows.append({"report_id": rid,
                            "reason": "conflicting_resolved_dates"})

    # ── شبیه‌سازی eligibility و برندهٔ سلول‌ها ──────────────────────────────
    # before: (published_at IS NULL AND period_end <= as_of) OR
    #         (published_at IS NOT NULL AND published_at <= cutoff)
    # after : published_at IS NOT NULL (backfilled) AND published_at <= cutoff
    # اثر روی سهمیهٔ امتیازدهی: شبیه‌سازی دقیق گفتهٔ موتور بعد از backfill —
    # ردیف‌هایی که تاریخ می‌گیرند با published_at ≤ cutoff سنجیده می‌شوند؛
    # بقیه (بدون تاریخ تأییدشده) با قاعدهٔ legacy (period_end ≤ as_of) می‌مانند
    resolved_dt = {}
    for (cid, ped), res in resolved.items():
        if res is not None and res.get("status") == VERIFIED and res.get("publish_at"):
            resolved_dt[(cid, ped)] = datetime.fromisoformat(res["publish_at"])

    def eligible(r, after):
        if r["report_id"] in superseded:
            return False
        if r["published_at"] is not None:
            return r["published_at"] <= cutoff
        key = (r["company_id"], r["period_end_date"])
        if not after:
            return r["period_end_date"] <= as_of_d
        if key in resolved_dt:  # این ردیف در backfill تاریخ می‌گیرد
            return resolved_dt[key] <= cutoff
        return r["period_end_date"] <= as_of_d  # بدون تاریخ می‌ماند

    def winners(after):
        idx = defaultdict(dict)
        for r in rows:
            if not eligible(r, after):
                continue
            cid = r["company_id"]
            fy, fm = r["fiscal_year"], r["fiscal_month"]
            if fy is None or fm is None:
                fy, fm = fiscal_ym(r["period_end_date"])
            key = (fy, fm)
            cell = idx[cid].setdefault(key, {"_period": r["period_end_date"],
                                             "_ver": r["version_no"],
                                             "_rep": r["report_id"]})
            if (r["period_end_date"], r["version_no"]) > \
                    (cell["_period"], cell["_ver"]):
                cell["_period"], cell["_ver"], cell["_rep"] = \
                    r["period_end_date"], r["version_no"], r["report_id"]
        return {cid: {k: c["_rep"] for k, c in cells.items()}
                for cid, cells in idx.items()}

    before_w = winners(False)
    after_w = winners(True)
    changed = []
    for cid in sorted(set(before_w) | set(after_w)):
        bw, aw = before_w.get(cid) or {}, after_w.get(cid) or {}
        for k in sorted(set(bw) | set(aw)):
            if bw.get(k) != aw.get(k):
                changed.append({"company_id": cid,
                                "codal_symbol": symbols.get(cid),
                                "cell": list(k),
                                "winner_before": bw.get(k),
                                "winner_after": aw.get(k)})
                break  # per company one sample row is enough in summary

    # اثر روی سهمیهٔ امتیازدهی: ردیف‌هایی که از «eligible بی‌تاریخ» خارج
    # می‌شوند (publish_at > cutoff) — این‌ها همان ریسک lookahead بالقوه‌اند
    newly_ineligible = [
        {"report_id": r["report_id"], "company_id": r["company_id"],
         "period_end_date": str(r["period_end_date"]),
         "publish_at": resolved_dt[(r["company_id"],
                                    r["period_end_date"])].isoformat()}
        for r in rows
        if r["published_at"] is None and r["report_id"] not in superseded
        and (r["company_id"], r["period_end_date"]) in resolved_dt
        and resolved_dt[(r["company_id"], r["period_end_date"])] > cutoff
    ]

    result = {
        "mission": "گام ۲-ک-۲ P3 — طرح backfill تاریخ انتشار (بدون اجرا)",
        "snapshot_binding": binding,
        "generated_note": GENERATED_NOTE,
        "not_executed": "این طرح صرفاً سند است؛ هیچ تغییری روی دیتابیس اعمال نشده",
        "plan_rows_count": len(plan_rows),
        "review_rows_count": len(review_rows),
        "review_reasons": dict(Counter(rr.get("reason") for rr in review_rows)),
        "conflicting_report_ids": sorted(conflicts),
        "pit_impact": {
            "cells_changed_winner_companies": len(changed),
            "changed_samples": changed[:50],
            "newly_ineligible_rows": len(newly_ineligible),
            "newly_ineligible_sample": newly_ineligible[:50],
            "note": "ردیف‌هایی که تاریخ انتشارشان بعد از cutoff است بعد از "
                    "backfill از امتیازدهی خارج می‌شوند — این دقیقاً همان "
                    "رفع ریسک lookahead است، نه از دست دادن داده",
        },
        "plan_rows": plan_rows,
        "review_rows": review_rows[:500],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    jpath = os.path.join(OUT_DIR, f"backfill_plan_{tag}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"wrote {jpath}")

    # ── SQL draft (idempotent + rollback) ───────────────────────────────────
    os.makedirs(SQL_DIR, exist_ok=True)
    tag_safe = re.sub(r"[^A-Za-z0-9_]", "_", tag)
    values = ",\n".join(
        f"  ('{pr['report_id']}'::uuid, '{pr['publish_at']}'::timestamptz)"
        for pr in plan_rows[:2000])
    rollback_values = ",\n".join(
        f"  ('{pr['report_id']}'::uuid)" for pr in plan_rows[:2000])
    sql = f"""-- =====================================================================
-- 122_publish_at_backfill_draft.sql — پیش‌نویس؛ اجرا نشده و نیازمند مجوز
-- گام ۲-ک-۲ P3: ثبت تاریخ انتشار واقعی (از شواهد E1/E2) برای ردیف‌های
-- legacy بدون تاریخ. idempotent: فقط published_at IS NULL را لمس می‌کند و
-- با بار دوم هیچ ردیفی تغییر نمی‌کند. rollback با اسکریپت دوم.
-- منشأ: backfill_plan_{tag}.json (snapshot q{binding['q']['sha256'][:8]} …)
-- پیش‌نیاز اجرا: بکاپ گرفتن از ingestion.reports این report_idها
-- =====================================================================

BEGIN;

-- 0) بکاپ داخل‌تراکنشی (به‌جای جدول دائمی؛ فقط مجوز اجرا می‌سازد نه این فایل)
-- CREATE TABLE IF NOT EXISTS audit.published_at_backfill_{tag_safe} AS
--   SELECT id, published_at FROM ingestion.reports
--   WHERE id::text = ANY(ARRAY[...report_ids...]);

-- 1) اعمال (idempotent)
WITH plan(report_id, publish_at) AS (VALUES
{values}
)
UPDATE ingestion.reports r
SET published_at = plan.publish_at
FROM plan
WHERE r.id = plan.report_id
  AND r.published_at IS NULL            -- idempotency guard
  AND r.source = 'legacy_sqlserver';    -- فقط ردیف‌های هدف

-- 2) کنترل پس از اعمال: هیچ ردیفی نباید باقی بماند
-- SELECT count(*) FROM ingestion.reports WHERE id::text = ANY(...) AND published_at IS NULL;

COMMIT;

-- ======================= ROLLBACK (برای اضطرار) =========================
-- بازگرداندن تاریخ‌های اعمال‌شده به NULL (بر اساس بکاپ گام 0):
-- WITH plan(report_id) AS (VALUES
{rollback_values}
-- )
-- UPDATE ingestion.reports r SET published_at = NULL
-- FROM plan WHERE r.id = plan.report_id AND r.source = 'legacy_sqlserver';
"""
    spath = os.path.join(SQL_DIR, "122_publish_at_backfill_draft.sql")
    with open(spath, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"wrote {spath}")

    # خلاصه MD
    md = [
        f"# طرح backfill تاریخ انتشار — {str(binding['as_of'])[:10]} (بدون اجرا)",
        "",
        f"- snapshot: Q `{binding['q']['sha256'][:16]}…` | V `{binding['v']['sha256'][:16]}…` | "
        f"T `{binding['t']['sha256'][:16]}…` — cutoff `{binding['cutoff']}`",
        f"- ردیف‌های واجد شرایط (تاریخ اثبات‌شده واقعی): **{len(plan_rows)}**",
        f"- ردیف‌های بازبینی (تعارض/مبهم/بی‌شواهد): **{len(review_rows)}** — "
        + ", ".join(f"{k}={v}" for k, v in sorted(Counter(rr.get('reason') for rr in review_rows).items())),
        "",
        "## اثر شبیه‌سازی‌شده روی PIT و سلول‌های برنده",
        "",
        f"- شرکت‌هایی که سلول برنده‌شان عوض می‌شود: **{len(changed)}**",
        f"- ردیف‌هایی که پس از backfill از امتیازدهی خارج می‌شوند "
        f"(publish_at > cutoff): **{len(newly_ineligible)}** — این حذف، رفع "
        "ریسک lookahead است",
        "",
        "## پیش‌نویس SQL",
        "",
        f"- فایل: `provenance_v1/sql/122_publish_at_backfill_draft.sql` — "
        "idempotent (فقط published_at IS NULL) + اسکریپت rollback + پیش‌نیاز "
        "بکاپ؛ اجرای آن نیازمند تصمیم و مجوز جداگانه است.",
        "",
        GENERATED_NOTE,
    ]
    mpath = os.path.join(OUT_DIR, f"backfill_plan_{tag}.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"wrote {mpath}")
    print(f"plan rows: {len(plan_rows)} | review: {len(review_rows)} | "
          f"winner changes: {len(changed)} | newly ineligible: {len(newly_ineligible)}")
    return 0


def _row_ref(r):
    return {"report_id": r["report_id"], "company_id": r["company_id"],
            "period_end_date": str(r["period_end_date"]),
            "source": r["source"], "version_no": r["version_no"]}


if __name__ == "__main__":
    sys.exit(main())
