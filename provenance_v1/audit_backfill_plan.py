# -*- coding: utf-8 -*-
"""P1 ۲-ک-۳: ممیزی هدفمند طرح backfill ۲-ک-۲ — بدون تکرار resolver، بدون اجرا.

ورودی‌ها: backfill_plan_{tag}.json + resolver cache (کامل) + کش کدال pub_backfill + DB فقط‌خواندنی.
خروجی: backfill_plan_audit_{tag}.json + .md + طرح اجرای مرحله‌ای (بدون هیچ اجرایی).
"""
import json, re, sys, collections, glob, os
from datetime import date, datetime
import psycopg

sys.path.insert(0, "provenance_v1")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
OUT = "provenance_v1/output"
CACHE_DIR = os.path.join("historical_codal_backfill", "output", "pub_backfill")


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
    if dt is None:
        return None
    return dt if isinstance(dt, str) else dt.isoformat()


def main():
    plan = json.load(open(f"{OUT}/backfill_plan_{TAG}.json", encoding="utf-8"))
    cache = json.load(open(f"{OUT}/_backfill_resolver_cache_{TAG}.json", encoding="utf-8"))
    iv = json.load(open(f"{OUT}/independent_validation_{TAG}.json", encoding="utf-8"))

    as_of_d = date.fromisoformat(str(plan["snapshot_binding"]["as_of"])[:10])
    cutoff = datetime.fromisoformat(str(plan["snapshot_binding"]["cutoff"]).replace(" ", "T"))
    pop_ids = sorted({r["company_id"] for r in plan["plan_rows"]} |
                     {r["company_id"] for r in plan["review_rows"]})
    plan_pairs = {(r["company_id"], r["period_end_date"]) for r in plan["plan_rows"]}
    plan_by_rid = {r["report_id"]: r for r in plan["plan_rows"]}
    resolved = {tuple(k.split("|", 1)): v for k, v in cache.items()}

    # کش کدال: letters_by_tracing با parse جلالی→گرگوری (مطابق resolver) — فقط‌خواندنی
    from codal_publish_resolver import parse_publish_datetime
    letters_by_tracing = {}
    n_cache_files = 0
    for fp in glob.glob(os.path.join(CACHE_DIR, "*.json")):
        n_cache_files += 1
        try:
            doc = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        items = doc.get("letters") if isinstance(doc, dict) else doc
        for lt in (items or []):
            if not isinstance(lt, dict):
                continue
            tid = str(lt.get("tracing_no") or "").strip()
            if tid:
                letters_by_tracing[tid] = {
                    "publish_at": parse_publish_datetime(lt.get("publish_datetime")),
                    "title": lt.get("title")}
    print(f"codal cache files: {n_cache_files}, letters indexed: {len(letters_by_tracing)}")

    conn = psycopg.connect(build_dsn(), connect_timeout=15)
    cur = conn.cursor()
    cur.execute("""
        SELECT st.company_id::text, st.period_end_date, r.id::text AS report_id,
               rv.version_no, r.source, r.letter_type, r.title, r.published_at,
               r.supersedes_report_id::text, r.processing_status,
               COALESCE(CAST(r.tracing_no AS text), r.source_report_id) AS tracing_no
        FROM fundamentals.financial_statements st
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN ingestion.reports r ON r.id = st.report_id
        WHERE st.company_id::text = ANY(%s)
    """, (pop_ids,))
    rows = []
    seen = set()
    for r in cur.fetchall():
        d = dict(zip([c[0] for c in cur.description], r))
        key = (d["company_id"], iso(d["period_end_date"]), d["report_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(d)
    conn.rollback()

    # نامه‌های کدال تاریخ‌دار مستقیم از ingestion.reports (برای جفت‌های بازبینی) —
    # تطبیق مثل resolver: period_end_date OR jalali_period_text
    unverified_pair_list = sorted(
        k for k, v in resolved.items() if v is None or v["status"] != "verified_publication_date")
    from codal_publish_resolver import gregorian_to_jalali_text
    cur.execute(
        "SELECT id::text AS report_id, company_id::text, period_end_date, jalali_period_text,"
        " source, letter_type, title, published_at, supersedes_report_id::text,"
        " processing_status, COALESCE(CAST(tracing_no AS text), source_report_id) AS tracing_no"
        " FROM ingestion.reports WHERE company_id::text = ANY(%s) AND source='codal'",
        (pop_ids,))
    all_codal = []
    for r in cur.fetchall():
        d = dict(zip([c[0] for c in cur.description], r))
        d["period_end_date"] = iso(d["period_end_date"])
        all_codal.append(d)
    conn.rollback()
    print(f"all codal rows for population: {len(all_codal)}")
    e1_rows = []
    for cid, ped in unverified_pair_list:
        pj = None
        try:
            pj = gregorian_to_jalali_text(date.fromisoformat(ped))
        except Exception:
            pj = None
        e1_rows.extend(
            {**d, "version_no": None} for d in all_codal
            if d["company_id"] == cid and d["published_at"] is not None
            and (d["period_end_date"] == ped or (pj and d["jalali_period_text"] == pj)))
    conn.close()
    print(f"row universe (report-level distinct): {len(rows)}")

    superseding = {r["report_id"] for r in rows if r["supersedes_report_id"]}
    dateless = [r for r in rows if r["published_at"] is None]
    backfill_targets = [r for r in dateless if r["report_id"] not in superseding]

    def pk(cid, ped):
        return (cid, iso(ped) if not isinstance(ped, str) else ped)

    by_pair = collections.defaultdict(list)
    for r in rows:
        by_pair[pk(r["company_id"], r["period_end_date"])].append(r)

    # ── بازسازی کامل مجموعهٔ بازبینی از کش ──────────────────────────────────
    review_full = []
    for r in backfill_targets:
        res = resolved.get(pk(r["company_id"], r["period_end_date"]))
        reason = (res or {}).get("status") if res else "resolver_error"
        if reason != "verified_publication_date":
            review_full.append({**{k: r[k] for k in
                                   ("company_id", "period_end_date", "report_id", "version_no",
                                    "source", "letter_type", "title", "supersedes_report_id",
                                    "processing_status", "tracing_no")},
                                "reason": reason})
    n_reconstructed = collections.Counter(x["reason"] for x in review_full)
    print("reconstructed review rows:", dict(n_reconstructed),
          "| plan says:", plan["review_reasons"])

    # ── تحلیل عمیق تعارض‌ها ──────────────────────────────────────────────────
    def title_flags(t):
        t = t or ""
        return {"audited": ("حسابرسی شده" in t) or ("حسابرسی‌شده" in t),
                "unaudited": ("حسابرسی نشده" in t) or ("حسابرسی‌نشده" in t),
                "consolidated": "تلفیقی" in t,
                "standalone": ("مستقل" in t) or ("خالص" in t)}

    e1_by_pair = collections.defaultdict(list)
    for r in e1_rows:
        e1_by_pair[(r["company_id"], r["period_end_date"])].append(r)

    ca = {"by_delta_bucket": collections.Counter(),
          "by_direction": collections.Counter(),
          "by_title_family": collections.Counter(),
          "by_version": collections.Counter(),
          "by_e1_letter_count": collections.Counter(),
          "ambiguous_patterns": collections.Counter(),
          "no_evidence_patterns": collections.Counter(),
          "db_vs_cache_relation": collections.Counter(),
          "delta_minutes_hist": collections.Counter(),
          "samples": []}
    for (cid, ped) in sorted(unverified_pair_list):
        res = resolved.get((cid, ped))
        if not res or res["status"] not in ("conflicting_publication_date", "ambiguous_match",
                                            "no_evidence"):
            continue
        e1 = e1_by_pair.get((cid, ped), [])
        stmt_rows = by_pair.get((cid, ped), [])
        if res["status"] == "no_evidence":
            has_codal = any(r["source"] == "codal" for r in e1 + stmt_rows)
            ca["no_evidence_patterns"][
                "company_has_other_codal_rows" if has_codal else "legacy_only_company"] += 1
            continue
        fams = set()
        for r in e1:
            tf = title_flags(r["title"])
            fams.add(("حسابرسی‌شده" if tf["audited"] else "حسابرسی‌نشده" if tf["unaudited"] else "؟")
                     + "/" + ("تلفیقی" if tf["consolidated"] else "مستقل" if tf["standalone"] else "؟"))
        n_letters = len({str(r["tracing_no"]) for r in e1 if r["tracing_no"]})
        if res["status"] == "ambiguous_match":
            ca["ambiguous_patterns"][
                f"letters={n_letters};fam={'|'.join(sorted(fams)) or '؟'}"] += 1
            continue
        ca["by_e1_letter_count"][f"e1_letters={n_letters}"] += 1
        for r in e1:
            tid = str(r["tracing_no"] or "").strip()
            lt = letters_by_tracing.get(tid)
            db_dt = r["published_at"]
            cache_dt = lt.get("publish_at") if lt else None
            tf = title_flags(r["title"])
            fam = ("حسابرسی‌شده" if tf["audited"] else "حسابرسی‌نشده" if tf["unaudited"] else "نامشخص") \
                + "/" + ("تلفیقی" if tf["consolidated"] else "مستقل" if tf["standalone"] else "بدون نشانگر")
            ca["by_title_family"][fam] += 1
            ca["by_version"][str(r["version_no"])] += 1
            if db_dt is None or cache_dt is None:
                ca["db_vs_cache_relation"]["cache_missing" if cache_dt is None else "db_missing"] += 1
                continue
            cdt = datetime.fromisoformat(str(cache_dt).replace(" ", "T"))
            delta_days = (cdt - db_dt).total_seconds() / 86400.0
            delta_min = delta_days * 24 * 60
            b = ("<=61min" if abs(delta_min) <= 61 else
                 "<1d" if abs(delta_days) < 1 else "1-7d" if abs(delta_days) <= 7
                 else "8-30d" if abs(delta_days) <= 30 else "31-365d" if abs(delta_days) <= 365
                 else ">1y")
            ca["by_delta_bucket"][b] += 1
            ca["by_direction"]["cache_later" if delta_days > 0 else "cache_earlier"] += 1
            ca["delta_minutes_hist"][f"{int(abs(delta_min))}min"] += 1
            ca["db_vs_cache_relation"]["both_present_disagree"] += 1
            if len(ca["samples"]) < 8:
                ca["samples"].append({
                    "company_id": cid, "period_end": ped, "tracing_no": tid,
                    "db_published_at": iso(db_dt), "cache_publish_at": str(cache_dt),
                    "delta_days": round(delta_days, 3), "title": (r["title"] or "")[:90],
                    "version_no": r["version_no"], "source": r["source"]})

    # ── برندگان فعلی با قرارداد موتور ────────────────────────────────────────
    def eligible(r, after):
        if after and r["report_id"] in plan_by_rid:
            dt = datetime.fromisoformat(plan_by_rid[r["report_id"]]["publish_at"])
            return dt.astimezone(cutoff.tzinfo) <= cutoff
        if r["published_at"] is not None:
            return r["published_at"] <= cutoff
        return r["period_end_date"] <= as_of_d

    winners_before, winners_after, row_flips = {}, {}, []
    for key, rs in by_pair.items():
        cand = [r for r in rs if r["report_id"] not in superseding and eligible(r, False)]
        if cand:
            winners_before[key] = max(cand, key=lambda r: (r["period_end_date"], r["version_no"]))["report_id"]
        cand2 = [r for r in rs if r["report_id"] not in superseding and eligible(r, True)]
        if cand2:
            winners_after[key] = max(cand2, key=lambda r: (r["period_end_date"], r["version_no"]))["report_id"]
        for r in rs:
            if r["report_id"] in superseding:
                continue
            if eligible(r, False) != eligible(r, True):
                row_flips.append({"report_id": r["report_id"], "company_id": r["company_id"],
                                  "period_end": iso(r["period_end_date"])})
    changed_pairs = sorted(k for k in set(winners_before) | set(winners_after)
                           if winners_before.get(k) != winners_after.get(k))
    print(f"row flips: {len(row_flips)} | changed winner pairs: {len(changed_pairs)}")

    # ── Q1 ───────────────────────────────────────────────────────────────────
    shortlist_winner_rids = {}
    for cid, c in iv["companies"].items():
        for t in c["checks"]["q_cell_trace"]:
            shortlist_winner_rids[t["report_id"]] = (c["symbol"], t["cell"], t.get("period_end"))
    review_rids = {x["report_id"] for x in review_full}
    shortlist_hits = {rid: v for rid, v in shortlist_winner_rids.items() if rid in review_rids}

    unverified_pairs = {k for k, v in resolved.items()
                        if v is None or v["status"] != "verified_publication_date"}
    dateless_winner_pairs = []
    for key, rid in winners_before.items():
        if key in unverified_pairs:
            row = next(r for r in by_pair[key] if r["report_id"] == rid)
            dateless_winner_pairs.append({
                "company_id": key[0], "period_end": key[1], "winner_report_id": rid,
                "source": row["source"], "version_no": row["version_no"]})
    eligible_rows_in_review_pairs = sum(
        1 for key in unverified_pairs for r in by_pair.get(key, [])
        if r["report_id"] not in superseding and eligible(r, False))

    # ── Q3 ───────────────────────────────────────────────────────────────────
    verified_pairs = {k for k, v in resolved.items()
                      if v and v["status"] == "verified_publication_date"}
    companies_verified = {k[0] for k in verified_pairs}
    companies_plan = {k[0] for k in plan_pairs}
    missing_companies = sorted(companies_verified - companies_plan)
    missing_detail = {}
    for cid in missing_companies:
        vps = sorted(k for k in verified_pairs if k[0] == cid)
        reasons = []
        for k in vps:
            rs = [r for r in by_pair.get(k, []) if r["report_id"] not in superseding]
            dl = [r for r in rs if r["published_at"] is None]
            if not rs:
                reasons.append({"pair": k[1], "why": "no report row in row-universe for this pair"})
            elif not dl:
                reasons.append({"pair": k[1], "why": "all rows already dated — nothing to backfill"})
            else:
                reasons.append({"pair": k[1], "why": f"{len(dl)} dateless rows NOT in plan?"})
        missing_detail[cid] = {"verified_pairs": len(vps), "reasons": reasons[:8],
                               "n_reasons": len(reasons)}

    # Q3 (ادامه): جمعیت ۲۶۲ = شرکت‌های q_origin_after=verified_from_source در ممیزی انتشار ۲-ک-۲
    pr = json.load(open(f"{OUT}/publish_recovery_{TAG}.json", encoding="utf-8"))
    pr_comps = pr["companies"]
    if isinstance(pr_comps, dict):
        pr_comps = list(pr_comps.values())
    verified_from_source = {c["company_id"] for c in pr_comps
                            if c.get("q_origin_after") == "verified_from_source"}
    q3_missing = sorted(verified_from_source - companies_plan)
    q3_plan_not_verified = sorted(companies_plan - verified_from_source)
    q3_plan_not_verified_reason = {}
    for cid in q3_plan_not_verified:
        wpairs = sorted(k for k in verified_pairs if k[0] == cid)
        statuses = collections.Counter(
            (resolved.get(k) or {}).get("status") for k in sorted(k for k in by_pair if k[0] == cid))
        q3_plan_not_verified_reason[cid] = {
            "verified_pairs_of_company": len(wpairs),
            "all_pair_statuses": dict(statuses),
            "backfill_rows": sum(1 for r in plan["plan_rows"] if r["company_id"] == cid)}
    q3_missing_reason = {}
    for cid in q3_missing:
        pairs_c = sorted(k for k in by_pair if k[0] == cid)
        statuses = collections.Counter(
            (resolved.get(k) or {}).get("status") or "no_pair_row" for k in pairs_c)
        dated_rows = [r for r in rows if r["company_id"] == cid and r["published_at"] is not None]
        q3_missing_reason[cid] = {
            "pairs": len(pairs_c), "pair_statuses": dict(statuses),
            "n_dated_report_rows": len(dated_rows),
            "n_dateless_backfill_targets": sum(
                1 for r in backfill_targets if r["company_id"] == cid),
            "scoring_rows_verified": sum(
                1 for c in pr_comps if c["company_id"] == cid
                for srow in c["scoring_rows"] if srow.get("status") == "verified_publication_date")}

    # ── Q4 ───────────────────────────────────────────────────────────────────
    import subprocess
    greps = subprocess.run(
        ["grep", "-rln", "published_at", "--include=*.py", "--include=*.go",
         "canonical_postgres_v1_2_1/analytics_canonical_v1", "provenance_v1", "go-app"],
        capture_output=True, text=True).stdout.strip().splitlines()
    consumers = sorted(g for g in greps if not any(
        x in g for x in ("_p0_", "audit_backfill_plan", "prepare_publish_backfill",
                         "run_capital_root_cause", "run_publish_recovery")))

    audit = {
        "mission": "گام ۲-ک-۳ P1 — ممیزی هدفمند طرح backfill (بدون اجرا، بدون تکرار resolver)",
        "binding": plan["snapshot_binding"],
        "row_universe": {
            "report_level_rows": len(rows), "pairs": len(by_pair),
            "dateless_report_rows": len(dateless),
            "superseding_excluded": len(superseding),
            "backfill_targets": len(backfill_targets)},
        "review_reconstruction": {
            "by_rows": dict(n_reconstructed), "total_rows": len(review_full),
            "plan_file_counts": plan["review_reasons"],
            "note": "فایل طرح سطرهای بازبینی را تا ۵۰۰ ذخیره کرده بود؛ بازسازی کامل از کش انجام شد "
                    "(بدون resolve جدید). شمارش سطرها با طرح تفاوت multiplicity دارد؛ جفت‌ها ملاک‌اند.",
            "pairs_by_status": dict(collections.Counter(
                (v or {}).get("status") or "resolver_error" for v in resolved.values()))},
        "conflict_deep_dive": {
            "method": "برای هر جفت conflicting: published_at سطر codal در DB در برابر تاریخ همان tracing در کش کدال (pub_backfill) مقایسه شد.",
            **{k: (dict(v) if isinstance(v, collections.Counter) else v)
               for k, v in ca.items()}},
        "q1_winner_relation": {
            "shortlist_winner_cells_total": len(shortlist_winner_rids),
            "shortlist_winner_cells_in_review": shortlist_hits,
            "n_current_winner_pairs_with_dateless_winner_in_unverified_pairs": len(dateless_winner_pairs),
            "dateless_winner_pairs_sample": dateless_winner_pairs[:12],
            "eligible_rows_in_unverified_pairs": eligible_rows_in_review_pairs},
        "q2_plan_independence": {
            "plan_pairs_all_verified": all(
                (resolved.get(k) or {}).get("status") == "verified_publication_date"
                for k in plan_pairs),
            "plan_rows_with_publish_gt_cutoff": sum(
                1 for r in plan["plan_rows"]
                if datetime.fromisoformat(r["publish_at"]).astimezone(cutoff.tzinfo) > cutoff),
            "winner_pairs_changed": [f"{k[0][:8]}|{k[1]}" for k in changed_pairs],
            "row_level_eligibility_flips": row_flips},
        "q3_companies": {
            "companies_with_verified_pairs": len(companies_verified),
            "companies_with_plan_rows": len(companies_plan),
            "missing_company_ids": missing_companies,
            "missing_detail": missing_detail,
            "population_262_definition": "شرکت‌هایی که در ممیزی انتشار ۲-ک-۲ (publish_recovery) وضعیت q_origin_after=verified_from_source دارند — سلول‌های مؤثر Q آن‌ها تاریخ انتشار تأییدشده گرفت",
            "population_262_count": len(verified_from_source),
            "population_262_minus_plan": q3_missing,
            "population_262_minus_plan_reason": q3_missing_reason,
            "plan_minus_population_262": q3_plan_not_verified,
            "plan_minus_population_262_reason": q3_plan_not_verified_reason},
        "q4_consumers": {
            "code_paths_reading_published_at": consumers,
            "n_paths": len(consumers),
            "row_level_eligibility_flips": len(row_flips)},
    }
    with open(f"{OUT}/backfill_plan_audit_{TAG}.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1, default=str)
    print("saved backfill_plan_audit", TAG)
    print("Q1 shortlist hits:", shortlist_hits or "هیچ")
    print("dateless winner pairs:", len(dateless_winner_pairs),
          "| eligible rows in review pairs:", eligible_rows_in_review_pairs)
    print("delta buckets:", dict(ca["by_delta_bucket"]))
    print("direction:", dict(ca["by_direction"]))
    print("title families:", dict(ca["by_title_family"]))
    print("versions:", dict(ca["by_version"]))
    print("ambiguous:", dict(list(ca["ambiguous_patterns"].items())[:6]))
    print("no_evidence:", dict(ca["no_evidence_patterns"]))
    print("Q3:", len(companies_verified), "verified-pairs vs", len(companies_plan),
          "plan |", len(verified_from_source), "verified_from_source | 262-minus-plan:",
          json.dumps(q3_missing_reason, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
