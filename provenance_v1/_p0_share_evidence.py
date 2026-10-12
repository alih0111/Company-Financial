# -*- coding: utf-8 -*-
"""P0 ۲-ک-۳: گردآوری همهٔ شواهد تغییر سرمایه برای بوعلی و کرماشا — فقط‌خواندنی.

هیچ فرضی جایگزین شواهد نمی‌شود؛ هر عدد همراه منبع و تاریخ ثبت می‌شود.
"""
import re, json, sys
import psycopg

TARGETS = {
    "c78433dc-e873-4bc9-85c4-794f755e5637": "بوعلی",
    "89bfa0d8-db72-4298-b7cb-166c0304b58d": "کرماشا",
}


def build_dsn():
    txt = open("go-app/.env", encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


def fnum(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    conn = psycopg.connect(build_dsn(), connect_timeout=15)
    out = {}
    for cid, sym in TARGETS.items():
        ev = {"symbol": sym, "company_id": cid}
        sec = conn.execute(
            "select id, tsetmc_ins_code, codal_symbol, isin from core.securities "
            "where company_id=%s and is_primary=true order by valid_from desc nulls last", (cid,)).fetchall()
        ev["securities"] = [
            {"security_id": str(s[0]), "ins_code": s[1], "codal_symbol": s[2], "isin": s[3]} for s in sec]
        sec_ids = [str(s[0]) for s in sec]

        # 1) گزارش‌ها + پایهٔ سهام خودِ گزارش (capital، eps، net_profit) — ۳۰ ماه اخیر
        rows = conn.execute("""
            select r.id, r.tracing_no, r.letter_type, r.title, r.period_end_date,
                   r.published_at, r.report_type, r.supersedes_report_id,
                   fs.id stmt_id, fs.duration_months, fs.is_audited, fs.is_restated,
                   ff.metric_code, ff.period_order, ff.reported_value, ff.reported_unit,
                   ff.canonical_value, ff.canonical_unit
            from fundamentals.financial_statements fs
            join fundamentals.financial_facts ff on ff.statement_id = fs.id
            join ingestion.reports r on r.id = fs.report_id
            where fs.company_id = %s and fs.statement_type='income_statement'
              and r.period_end_date >= '2023-10-01'
              and ff.metric_code in ('capital','eps','net_profit','operating_eps')
              and ff.period_order in (1,3)
            order by r.period_end_date, r.published_at, ff.metric_code, ff.period_order
        """, (cid,)).fetchall()
        rep_map = {}
        for r in rows:
            k = (str(r[0]), r[4].isoformat() if r[4] else None, str(r[6]))
            e = rep_map.setdefault(k, {
                "report_id": str(r[0]), "tracing_no": r[1], "letter_type": r[2],
                "title": r[3], "period_end": r[4].isoformat() if r[4] else None,
                "published_at": r[5].isoformat() if r[5] else None,
                "report_type": r[6], "supersedes": str(r[7]) if r[7] else None,
                "duration_months": r[9], "is_audited": r[10], "is_restated": r[11],
                "facts": {}})
            e["facts"].setdefault(r[12], {})[r[13]] = {
                "reported": fnum(r[14]), "reported_unit": r[15],
                "canonical": fnum(r[16]), "canonical_unit": r[17]}
        ev["income_report_timeline"] = list(rep_map.values())

        # 2) share_intervals — تاریخچهٔ پنجره‌ای سهام
        rows = conn.execute("""
            select valid_from, valid_to, shares_outstanding, basis, status, source,
                   knowledge_from, evidence
            from core.share_intervals where company_id=%s
            order by valid_from nulls last, id""", (cid,)).fetchall()
        ev["share_intervals"] = [
            {"valid_from": r[0].isoformat() if r[0] else None,
             "valid_to": r[1].isoformat() if r[1] else None,
             "shares_outstanding": fnum(r[2]), "basis": r[3], "status": r[4],
             "source": r[5], "knowledge_from": r[6].isoformat() if r[6] else None,
             "evidence": r[7] and (r[7] if isinstance(r[7], dict) else json.loads(r[7]))}
            for r in rows]

        # 3) share_structure — همهٔ اسنپ‌شات‌ها
        rows = conn.execute("""
            select shares_count, eps_rial, as_of_date, source, collected_at
            from core.share_structure where company_id=%s order by as_of_date, collected_at""", (cid,)).fetchall()
        ev["share_structure"] = [
            {"shares": fnum(r[0]), "eps_rial": fnum(r[1]), "as_of": r[2].isoformat() if r[2] else None,
             "source": r[3], "collected_at": r[4].isoformat() if r[4] else None} for r in rows]

        # 4) tsetmc_current_shares — تاریخچهٔ کامل اسنپ‌شات‌ها
        rows = conn.execute("""
            select t.shares_count, t.source, t.collected_at
            from market.tsetmc_current_shares t
            where t.security_id = any(%s::uuid[])
            order by t.collected_at""", (sec_ids,)).fetchall()
        ev["tsetmc_current_shares"] = [
            {"shares": fnum(r[0]), "source": r[1], "collected_at": r[2].isoformat() if r[2] else None}
            for r in rows]

        # 5) share_events — بدون فیلتر وضعیت
        rows = conn.execute("""
            select event_type, shares_before, shares_after, change_ratio,
                   capital_before_rial, capital_after_rial, nominal_value_rial,
                   announced_at, approved_at, registered_at, effective_date,
                   market_ex_date, economics_explicit, status, confidence, source,
                   source_report_id, metadata
            from core.share_events where company_id=%s order by announced_at nulls last, id""", (cid,)).fetchall()
        ev["share_events"] = [
            {"event_type": r[0], "shares_before": fnum(r[1]), "shares_after": fnum(r[2]),
             "change_ratio": fnum(r[3]), "capital_before_rial": fnum(r[4]),
             "capital_after_rial": fnum(r[5]), "nominal_value_rial": fnum(r[6]),
             "announced_at": r[7].isoformat() if r[7] else None,
             "approved_at": r[8].isoformat() if r[8] else None,
             "registered_at": r[9].isoformat() if r[9] else None,
             "effective_date": r[10].isoformat() if r[10] else None,
             "market_ex_date": r[11].isoformat() if r[11] else None,
             "economics_explicit": r[12], "status": r[13], "confidence": r[14],
             "source": r[15], "source_report_id": r[16],
             "metadata": r[17] and (r[17] if isinstance(r[17], dict) else json.loads(r[17]))}
            for r in rows]

        # 6) corporate_actions — بدون فیلتر
        rows = conn.execute("""
            select action_date, action_type, adjustment_factor, source, source_reference,
                   is_confirmed, detected_heuristically, metadata, event_semantics_status,
                   adjustment_evidence_status
            from market.corporate_actions where security_id = any(%s::uuid[])
            order by action_date nulls last""", (sec_ids,)).fetchall()
        ev["corporate_actions"] = [
            {"action_date": r[0].isoformat() if r[0] else None, "action_type": r[1],
             "adjustment_factor": fnum(r[2]), "source": r[3], "source_reference": r[4],
             "is_confirmed": r[5], "detected_heuristically": r[6],
             "metadata": r[7] and (r[7] if isinstance(r[7], dict) else json.loads(r[7])),
             "event_semantics_status": r[8], "adjustment_evidence_status": r[9]}
            for r in rows]

        # 7) vendor_snapshots — هر متاریخ مربوط به سهم/سرمایه
        rows = conn.execute("""
            select metric_code, value, unit, captured_at, vendor
            from market.vendor_snapshots where company_id=%s
              and (metric_code ilike '%%share%%' or metric_code ilike '%%capital%%'
                   or metric_code ilike '%%market_cap%%')
            order by captured_at, metric_code""", (cid,)).fetchall()
        ev["vendor_share_snapshots"] = [
            {"metric_code": r[0], "value": fnum(r[1]), "unit": r[2],
             "captured_at": r[3].isoformat() if r[3] else None, "vendor": r[4]}
            for r in rows]

        # 8) مرزهای تعدیل قیمت — جایی که is_adjusted/adjustment_method تغییر می‌کند
        rows = conn.execute("""
            select trade_date, closing_price_rial, is_adjusted, adjustment_method,
                   adjustment_version, closing_change_percent
            from market.daily_prices where security_id = any(%s::uuid[])
            order by trade_date""", (sec_ids,)).fetchall()
        bounds, prev_adj, prev_meth = [], None, None
        for r in rows:
            if prev_adj is not None and (r[2] != prev_adj or (r[3] or "") != (prev_meth or "")):
                bounds.append({"boundary_at": r[0].isoformat(),
                               "was": {"is_adjusted": prev_adj, "method": prev_meth},
                               "now": {"is_adjusted": r[2], "method": r[3]}})
            prev_adj, prev_meth = r[2], r[3]
        ev["price_adjustment_boundaries"] = bounds
        ev["price_rows_total"] = len(rows)
        if rows:
            ev["price_range"] = {"first": rows[0][0].isoformat(), "last": rows[-1][0].isoformat()}
            # افت‌های شدید قیمتی (نشان احتمالی ex-date بدون تعدیل)
            big = [r for r in rows if r[5] is not None and float(r[5]) <= -20]
            ev["big_drops_ge20pct"] = [
                {"date": r[0].isoformat(), "chg_pct": float(r[5]),
                 "close": fnum(r[1]), "is_adjusted": r[2]} for r in big]

        # 9) گزارش‌های کدال با عنوان افزایش سرمایه/مجمع — بعد از پایان سال مالی برنده
        wr = [e for e in ev["income_report_timeline"] if e["period_end"] == "2026-06-21"]
        winner_pub = wr[0]["published_at"][:10] if wr and wr[0]["published_at"] else "2026-07-21"
        rows = conn.execute("""
            select r.tracing_no, r.letter_type, r.title, r.period_end_date, r.published_at, r.source
            from ingestion.reports r
            where r.company_id=%s and r.published_at >= %s::timestamp
              and (r.title ilike '%%افزایش سرمایه%%' or r.title ilike '%%مجمع%%'
                   or r.title ilike '%%سرمایه%%')
            order by r.published_at""", (cid, winner_pub)).fetchall()
        ev["capital_related_letters_after_winner"] = [
            {"tracing_no": r[0], "letter_type": r[1], "title": r[2],
             "period_end": r[3].isoformat() if r[3] else None,
             "published_at": r[4].isoformat() if r[4] else None, "source": r[5]}
            for r in rows]

        # 10) همهٔ گزارش‌های بعد از گزارش برنده (هر نوع) — برای ردیابی گزارش بعدی
        rows = conn.execute("""
            select r.tracing_no, r.letter_type, r.title, r.period_end_date, r.published_at
            from ingestion.reports r
            where r.company_id=%s and r.published_at > %s::timestamp
            order by r.published_at""", (cid, winner_pub)).fetchall()
        ev["all_letters_after_winner"] = [
            {"tracing_no": r[0], "letter_type": r[1], "title": r[2],
             "period_end": r[3].isoformat() if r[3] else None,
             "published_at": r[4].isoformat() if r[4] else None}
            for r in rows]

        out[sym] = ev
    conn.close()
    tag = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
    with open(f"provenance_v1/output/_p0_share_evidence_{tag}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print("saved provenance_v1/output/_p0_share_evidence_" + tag + ".json")
    for sym, ev in out.items():
        print(f"\n== {sym}: reports={len(ev['income_report_timeline'])} "
              f"intervals={len(ev['share_intervals'])} struct={len(ev['share_structure'])} "
              f"cur_shares={len(ev['tsetmc_current_shares'])} events={len(ev['share_events'])} "
              f"actions={len(ev['corporate_actions'])} vend={len(ev['vendor_share_snapshots'])} "
              f"bounds={len(ev['price_adjustment_boundaries'])} drops={len(ev.get('big_drops_ge20pct', []))} "
              f"cap_letters={len(ev['capital_related_letters_after_winner'])} "
              f"after_winner={len(ev['all_letters_after_winner'])}")


if __name__ == "__main__":
    main()
