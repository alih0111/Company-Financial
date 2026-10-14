"""Conservative support for old Codal tables with separately rendered headers.

Only explicit report-level million-rial declarations before the first table,
non-consolidated report headings, known statement IDs and dated columns qualify.
No table-position guesses; comparative numbers never become prior-period facts.
"""
import re
from bs4 import BeautifulSoup
import collect_financial_history as H


def legacy_facts(html, period):
    # Most rejected modern exports have no report-header unit declaration.
    # Avoid building a large DOM when this mandatory evidence is absent.
    prefix = re.split(r"<table\b", html, maxsplit=1, flags=re.I)[0]
    prefix = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", prefix, flags=re.S | re.I)
    plain = H.P.norm_title(H.P.html_unescape(re.sub(r"<[^>]*>", " ", prefix)))
    if "کلیهمبالغدرجشدهبهمیلیونریال" not in plain or "تلفیقی" in plain:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style"]):
        junk.decompose()
    first = soup.find("table")
    if first is None:
        return []
    header = " ".join(t.strip() for t in first.find_all_previous(string=True) if t.strip())
    normalized = H.P.norm_title(header)
    if "کلیهمبالغدرجشدهبهمیلیونریال" not in normalized or "تلفیقی" in normalized:
        return []
    facts = []
    kinds = {"grdInterimStatement": "income_statement", "gvCashFlow": "cash_flow"}
    for suffix, statement in kinds.items():
        table = soup.find("table", id=lambda value: value and value.endswith(suffix))
        if table is None:
            continue
        headings = table.find_previous("table")
        if headings is None or "Grid" in headings.get("class", []):
            continue
        header_rows = H.P._rows(str(headings))
        candidates = []
        for row in header_rows[:4]:
            dated = [(i, H.P.jalali_in(cell)) for i, cell in enumerate(row) if H.P.jalali_in(cell)]
            if len(dated) >= 2 and dated[0][1] > dated[1][1]:
                candidates.append(dated)
        if len(candidates) != 1:
            continue
        dated = candidates[0]
        if H.F.jalali_to_gregorian(*dated[0][1]).isoformat() != period:
            continue
        column = dated[0][0]
        titles = {H.P.norm_title(title): metric for (st, metric), title in H.P.ROW_TITLES.items() if st == statement}
        titles[H.P.norm_title("جمع درآمدهای عملیاتی")] = "revenue"
        if statement == "cash_flow":
            titles[H.P.norm_title("جریان خالص ورود (خروج) وجه نقد ناشی از فعالیت‌های عملیاتی")] = "operating_cash_flow"
        found, ambiguous = {}, set()
        for row in H.P._rows(str(table)):
            if len(row) <= column:
                continue
            metric = titles.get(H.P.norm_title(row[0]))
            value = H.P.to_number(row[column])
            if metric is None or value is None:
                continue
            if metric in found:
                ambiguous.add(metric)
            found[metric] = value
        for metric, value in found.items():
            if metric in ambiguous:
                continue
            facts.append({"statement_type": statement, "metric_code": metric,
                          "value": value if metric in H.P.PER_SHARE else value * 1e6,
                          "unit": "rial_per_share" if metric in H.P.PER_SHARE else "rial",
                          "basis": "parent", "period_order": 1})
    return facts


def main():
    catalog = {str(r["letter"]["TracingNo"]): r for r in H.C.read(H.OUT / "catalog_versions.json")}
    recovered = []
    for rec in H.C.read(H.OUT / "reports.json"):
        if rec["facts"]:
            continue
        html, _ = H.C.report_html(rec["symbol"], catalog[rec["tracing_no"]]["letter"], False, 0)
        facts = legacy_facts(html, rec["period_end"]) if html else []
        if facts:
            overlay = {**rec, "facts": facts, "parser_version": "legacy-separate-header-v1",
                       "original_record_sha256": H.hashlib.sha256((H.OUT / "reports" / f"{rec['company_id']}_{rec['tracing_no']}.json").read_bytes()).hexdigest(),
                       "unit_evidence": "Explicit all-report million-rial declaration before first table; non-consolidated heading"}
            H.C.write(H.OUT / "recovered_reports" / f"{rec['company_id']}_{rec['tracing_no']}.json", overlay)
            recovered.append({"symbol": rec["symbol"], "tracing_no": rec["tracing_no"], "facts": len(facts)})
    H.C.write(H.OUT / "legacy_recovery.json", {"reports": recovered, "originals_changed": False,
              "note": "Separate parsed overlays; excluded balance sheets with mirrored columns; strict parent/unit/date guards"})
    print(H.json.dumps({"recovered_reports": len(recovered), "facts": sum(r["facts"] for r in recovered), "reports": recovered}, ensure_ascii=False))


if __name__ == "__main__":
    main()
