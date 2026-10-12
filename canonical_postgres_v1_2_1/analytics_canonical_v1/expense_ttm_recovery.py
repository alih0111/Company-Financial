"""READ-ONLY order-3 recovery from the project's own raw Codal letter
archive (raw.report_payloads) — step 2-B-8.

Why: the legacy migration stored only period_order 1 / 2 facts for
finance_cost / other_non_operating (store-wide census: zero order-3 rows
anywhere), while the interim Codal letters themselves carry a third value
column (prior fiscal year, same restated basis). The raw letters of the
collection pipeline live in raw.report_payloads. This module re-reads
those letters READ-ONLY and recovers the order-3 leg ONLY when every gate
holds:

  identity  : the payload letter belongs to the same company and the same
              Jalali period (fy, fm) as the engine's latest report cell,
              is PIT-eligible (published <= cutoff, or no published_at and
              period_end <= as_of) and not superseded; if several letters
              match, exactly ONE of them must pass the value gate
  columns   : value columns are selected by the letter cells' own
              periodEndToDate fields — current == the statement period,
              prior-same == (year-1, same month/day), prior-annual ==
              yearEndToDate - 1 year; percent columns carry no period date
              and are never consumed
  rows      : the finance-cost row must match exactly; the other-nonop row
              may be split into sub-rows (agricultural statement format) —
              a subset of candidate rows is accepted only when it
              reproduces BOTH canonical anchors (the stored reported_value
              of order 1 AND order 2) EXACTLY (Decimal equality)
  window    : current and prior-same column dates differ by exactly one
              year, so o1 + o3 - o2 stays a same-window TTM on one
              restated basis (all three columns of one letter)

Everything else is refused with a named state — no guessing, no scaling,
no fabricated values. Recovered values are converted million_rial -> rial
with the store's uniform convention (canonical/reported ratio is exactly
1e6 across all 1040 finance_cost facts). Sentinel-legged results are
quarantined downstream by the pilot resolver (2-B-4.2 discipline).

This module performs SELECT-only database access and never mutates the
engine's structures, the database, or the ingestion pipeline.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "migration_tools"))

from common import pg_pilot_conn  # noqa: E402

MILLION = Decimal(1_000_000)

EXPENSE_METRICS = ("finance_cost", "other_non_operating")

# per-(company, metric) outcome states (census rollups name the class)
STATE_RECOVERED = "recovered"
STATE_BLANK_ANNUAL_CELL = "letter_blank_annual_cell"      # class B
STATE_NO_PAYLOAD = "no_payload_letter"                    # class C
STATE_NO_ANCHOR = "no_anchor_facts"
STATE_AMBIGUOUS_LETTERS = "ambiguous_letters"             # class D
STATE_GRID_UNPARSABLE = "grid_unparsable"                 # class D
STATE_NO_TABLE = "no_statement_table"                     # class D
STATE_WINDOW_UNPROVABLE = "window_columns_unprovable"     # class D
STATE_ROW_FAILED = "row_identity_failed"                  # class D
STATE_ROW_AMBIGUOUS = "row_identity_ambiguous"            # class D

CLASS_OF_STATE = {
    STATE_RECOVERED: "A_extracted_not_stored",
    STATE_BLANK_ANNUAL_CELL: "B_absent_from_letter",
    STATE_NO_PAYLOAD: "C_no_payload_in_project_archive",
    STATE_NO_ANCHOR: "D_identity_unprovable",
    STATE_AMBIGUOUS_LETTERS: "D_identity_unprovable",
    STATE_GRID_UNPARSABLE: "D_identity_unprovable",
    STATE_NO_TABLE: "D_identity_unprovable",
    STATE_WINDOW_UNPROVABLE: "D_identity_unprovable",
    STATE_ROW_FAILED: "D_identity_unprovable",
    STATE_ROW_AMBIGUOUS: "D_identity_unprovable",
}

_CELL_RE = re.compile(r'\{"metaTableId".*?\}')
_CTRL_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_FC_RE = re.compile(r"^هزینه\s*ها?ی\s*مالی$")
# the non-operating line may be split into labelled sub-rows
_ONOP_RE = re.compile(r"سایر")


def normalize_label(s) -> str:
    """Codal letters mix Arabic yeh/kaf, RTL control marks and ZWNJ into
    Persian labels — normalize before any comparison."""
    t = _CTRL_RE.sub("", str(s))
    t = (t.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
         .replace("\u200c", " "))
    return re.sub(r"\s+", " ", t).strip()


def _dec(s):
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if not t or t in ("-", "–"):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_letter_cells(html: str) -> list:
    cells = []
    for m in _CELL_RE.finditer(html):
        try:
            cells.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            continue
    return cells


def _jdate(s):
    m = re.fullmatch(r"(1[34]\d{2})/(\d{1,2})/(\d{1,2})", str(s or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _minus_one_year(d):
    return (d[0] - 1, d[1], d[2])


def extract_order3(html: str, period_j: tuple, anchors: dict):
    """Pure core. anchors = {metric: {"o1": Decimal(rep), "o2": Decimal(rep)}}.

    Returns ({metric: outcome}, fatal_error) where outcome = {
      "state": STATE_RECOVERED | STATE_BLANK_ANNUAL_CELL |
               STATE_ROW_FAILED | STATE_ROW_AMBIGUOUS,
      "value": Decimal canonical rial | None,
      "window_dates": {...}, "evidence": {...}}
    """
    cells = parse_letter_cells(html)
    if not cells:
        return None, STATE_GRID_UNPARSABLE
    by_table = defaultdict(list)
    for c in cells:
        by_table[c["metaTableId"]].append(c)

    # the statement table: the one carrying finance-cost-labelled rows
    cand_tables = []
    for tid, tcells in sorted(by_table.items()):
        titles = {}
        for c in tcells:
            if c["columnCode"] == 1:
                titles[c["rowCode"]] = normalize_label(c.get("value") or "")
        fc_rows = [rc for rc, t in titles.items()
                   if _FC_RE.fullmatch(t) and "مالیات" not in t]
        onop_rows = [rc for rc, t in titles.items()
                     if _ONOP_RE.match(t)
                     and "غیرعملیاتی" in t and "ریال" not in t]
        if fc_rows:
            cand_tables.append({"tid": tid, "tcells": tcells,
                                "titles": titles, "fc_rows": fc_rows,
                                "onop_rows": onop_rows})
    if not cand_tables:
        return None, STATE_NO_TABLE
    if len(cand_tables) > 1:
        # several tables declare finance-cost rows; only one may carry
        # populated value columns (the other is usually an empty shell)
        cand_tables = [t for t in cand_tables if t["onop_rows"]]
        if len(cand_tables) != 1:
            return None, STATE_NO_TABLE
    tab = cand_tables[0]

    # ---- column resolution: by the cells' own periodEndToDate -----------
    col_dates: dict = {}
    for c in tab["tcells"]:
        cc = c["columnCode"]
        if cc == 1:
            continue
        d = _jdate(c.get("periodEndToDate"))
        if d is None:
            continue
        col_dates.setdefault(cc, set()).add(d)
    col_dates = {cc: next(iter(ds)) for cc, ds in col_dates.items()
                 if len(ds) == 1}
    cur_cols = [cc for cc, d in col_dates.items() if d == period_j]
    if len(cur_cols) != 1:
        return None, STATE_WINDOW_UNPROVABLE
    cur_col = cur_cols[0]
    prev_expected = _minus_one_year(period_j)
    prev_cols = [cc for cc, d in col_dates.items() if d == prev_expected]
    if len(prev_cols) != 1:
        return None, STATE_WINDOW_UNPROVABLE
    prev_col = prev_cols[0]

    yend = None
    for c in tab["tcells"]:
        if c["columnCode"] == cur_col:
            yend = _jdate(c.get("yearEndToDate"))
            if yend:
                break
    if not yend:
        return None, STATE_WINDOW_UNPROVABLE
    ann_expected = _minus_one_year(yend)
    ann_cols = [cc for cc, d in col_dates.items() if d == ann_expected]
    if len(ann_cols) != 1 or ann_cols[0] in (cur_col, prev_col):
        return None, STATE_WINDOW_UNPROVABLE
    ann_col = ann_cols[0]

    grid: dict = defaultdict(dict)
    for c in tab["tcells"]:
        grid[c["rowCode"]][c["columnCode"]] = _dec(c.get("value"))

    window_dates = {"current": period_j, "prior_same": prev_expected,
                    "prior_annual": ann_expected,
                    "year_end_to_date": yend}

    def _match_rows(row_ids, o1, o2):
        """Exactly one row / disjoint subset must reproduce both anchors."""
        singles = [rc for rc in row_ids
                   if grid[rc].get(cur_col) == o1
                   and grid[rc].get(prev_col) == o2]
        if len(singles) == 1:
            return [singles[0]]
        if len(singles) > 1:
            return None
        # the split-subrow case: exactly one subset sums to both anchors
        subset_hits = []
        ids = list(row_ids)[:6]
        n = len(ids)
        if n >= 2:
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = ids[i], ids[j]
                    if (grid[a].get(cur_col) is not None
                            and grid[b].get(cur_col) is not None
                            and grid[a][cur_col] + grid[b][cur_col] == o1
                            and grid[a][prev_col] is not None
                            and grid[b][prev_col] is not None
                            and grid[a][prev_col] + grid[b][prev_col] == o2):
                        subset_hits.append([a, b])
        if len(subset_hits) == 1:
            return subset_hits[0]
        return None

    out: dict = {}
    for metric in EXPENSE_METRICS:
        a = anchors.get(metric)
        if not a:
            out[metric] = {"state": STATE_ROW_FAILED, "value": None,
                           "window_dates": window_dates, "evidence": {}}
            continue
        row_ids = tab["fc_rows"] if metric == "finance_cost" \
            else tab["onop_rows"]
        hits = _match_rows(row_ids, a["o1"], a["o2"])
        base_evidence = {
            "meta_table_id": tab["tid"],
            "column_dates": {str(cc): "-".join(str(x) for x in col_dates[cc])
                             for cc in sorted(col_dates)},
            "consumed_columns": {"current": cur_col, "prior_same": prev_col,
                                 "prior_annual": ann_col},
            "window_dates": {k: "-".join(str(x) for x in v)
                             for k, v in window_dates.items()},
        }
        if hits is None:
            too_many = [rc for rc in row_ids
                        if grid[rc].get(cur_col) == a["o1"]
                        and grid[rc].get(prev_col) == a["o2"]]
            out[metric] = {
                "state": STATE_ROW_AMBIGUOUS if len(too_many) > 1
                else STATE_ROW_FAILED,
                "value": None, "window_dates": window_dates,
                "evidence": {**base_evidence,
                             "candidate_rows": [
                                 {"row": rc,
                                  "title": tab["titles"].get(rc, ""),
                                  "current": str(grid[rc].get(cur_col)),
                                  "prior_same": str(grid[rc].get(prev_col))}
                                 for rc in row_ids[:6]]}}
            continue
        rows_used = hits
        annual_vals = [grid[rc].get(ann_col) for rc in rows_used]
        evidence = {**base_evidence,
                    "rows_used": [{"row": rc,
                                   "title": tab["titles"].get(rc, ""),
                                   "current": str(grid[rc].get(cur_col)),
                                   "prior_same": str(grid[rc].get(prev_col)),
                                   "prior_annual":
                                       str(grid[rc].get(ann_col))}
                                  for rc in rows_used]}
        if any(v is None for v in annual_vals):
            out[metric] = {"state": STATE_BLANK_ANNUAL_CELL, "value": None,
                           "window_dates": window_dates,
                           "evidence": evidence}
            continue
        o3_rep = sum(annual_vals)          # million_rial
        out[metric] = {"state": STATE_RECOVERED,
                       "value": o3_rep * MILLION,      # canonical rial
                       "value_rep": o3_rep,
                       "window_dates": window_dates,
                       "evidence": evidence}
    return out, None


def _statement_anchors(cur, cid: str, latest: tuple):
    """reported_value anchors for the latest cell (max period_end, then
    version — the Engine's own cell-choice rule)."""
    import jdatetime
    rows = cur.execute("""
        SELECT st.id::text AS sid, st.period_end_date, rv.version_no AS ver,
               st.fiscal_year, st.fiscal_month,
               f.metric_code, f.period_order, f.reported_value
        FROM fundamentals.financial_statements st
        JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
        JOIN fundamentals.financial_facts f ON f.statement_id = st.id
        WHERE st.company_id = %s
          AND f.metric_code = ANY(%s) AND f.period_order IN (1, 2)
          AND f.reported_value IS NOT NULL""",
        (cid, list(EXPENSE_METRICS))).fetchall()
    stmts: dict = {}
    for r in rows:
        ped = r["period_end_date"]
        jy = jdatetime.date.fromgregorian(date=ped) if ped else None
        jm = (jy.year, jy.month) if jy else None
        if latest not in (jm, (r["fiscal_year"], r["fiscal_month"])):
            continue
        key = (r["sid"], ped, r["ver"])
        stmts.setdefault(key, {}).setdefault(
            r["metric_code"], {})[r["period_order"]] = r
    if not stmts:
        return None, None
    best = max(stmts, key=lambda k: (k[1], k[2]))
    facts = stmts[best]
    anchors = {}
    for metric in EXPENSE_METRICS:
        fr = facts.get(metric) or {}
        if fr.get(1) is None or fr.get(2) is None:
            return None, None
        anchors[metric] = {
            "o1": Decimal(str(fr[1]["reported_value"])),
            "o2": Decimal(str(fr[2]["reported_value"]))}
    import jdatetime as _jd
    jy = _jd.date.fromgregorian(date=best[1])
    return anchors, (jy.year, jy.month, jy.day)


def _candidate_letters(cur, cid: str, latest: tuple, as_of, cutoff):
    """PIT-eligible, non-superseded codal letters of this company that
    carry a raw payload, restricted to the latest Jalali period."""
    import jdatetime
    rows = cur.execute("""
        SELECT rep.id::text AS report_id, rep.title, rep.period_end_date,
               rep.published_at, rep.source_url,
               rv.id::text AS rv_id, rv.version_no, rv.collected_at,
               rp.payload_type, rp.content_text
        FROM ingestion.reports rep
        JOIN ingestion.report_versions rv ON rv.report_id = rep.id
        JOIN raw.report_payloads rp ON rp.report_version_id = rv.id
        WHERE rep.company_id = %s
          AND rep.report_type = 'financial_statement'
          AND rep.source = 'codal'
          AND ((rep.published_at IS NULL
                AND rep.period_end_date <= %s)
               OR (rep.published_at IS NOT NULL
                   AND rep.published_at <= %s))
          AND rep.id NOT IN (SELECT supersedes_report_id
                             FROM ingestion.reports
                             WHERE supersedes_report_id IS NOT NULL)
        ORDER BY rep.published_at DESC NULLS LAST""",
        (cid, as_of, cutoff)).fetchall()
    out = []
    for r in rows:
        ped = r["period_end_date"]
        jy = jdatetime.date.fromgregorian(date=ped) if ped else None
        if not jy or (jy.year, jy.month) != latest:
            continue
        out.append(r)
    return out


def recover_expense_order3(rep_index: dict, durations_by_company: dict,
                           as_of, cutoff, company_ids=None,
                           conn=None) -> tuple:
    """READ-ONLY recovery for every interim latest cell that has orders
    1+2 but no order 3, for both expense metrics.

    Returns (results, census):
      results = {cid: {metric: {"state", "order": 3, "value": float rial,
                                "evidence": {...}}}}   (recovered only
      carries value; refusals carry state + reason)
      census  = {metric: {state: n}} + {"class_rollup": {...}}
    """
    own_conn = conn is None
    pg = conn or pg_pilot_conn(autocommit=True)
    try:
        from psycopg.rows import dict_row
        cur = pg.cursor(row_factory=dict_row)
        results: dict = {}
        census: dict = {m: defaultdict(int) for m in EXPENSE_METRICS}
        census["class_rollup"] = defaultdict(int)

        def _record(cid, metric, state, extra=None):
            rec = {"state": state}
            rec.update(extra or {})
            results.setdefault(cid, {})[metric] = rec
            census[metric][state] += 1
            census["class_rollup"][CLASS_OF_STATE.get(
                state, "D_identity_unprovable")] += 1

        for cid in sorted(rep_index):
            if company_ids is not None and cid not in company_ids:
                continue
            rep = rep_index.get(cid) or {}
            if not rep:
                continue
            latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
            if (durations_by_company.get(cid) or {}).get(latest) == 12:
                continue  # annual letters resolve directly (2-B-7 path)
            gaps = []
            for metric in EXPENSE_METRICS:
                d = (rep.get(latest) or {}).get(metric) or {}
                if d.get(1) is not None and d.get(2) is not None \
                        and d.get(3) is None:
                    gaps.append(metric)
            if not gaps:
                continue  # nothing to recover for this company
            for metric in gaps:
                census[metric]["targets"] += 1

            anchors, period_j = _statement_anchors(cur, cid, latest)
            if not anchors:
                for metric in gaps:
                    _record(cid, metric, STATE_NO_ANCHOR, {
                        "reason": "no statement facts for the latest cell"})
                continue
            letters = _candidate_letters(cur, cid, latest, as_of, cutoff)
            if not letters:
                for metric in gaps:
                    _record(cid, metric, STATE_NO_PAYLOAD, {
                        "reason": "no raw payload letter of the same "
                                  "period in raw.report_payloads"})
                continue
            # parse each candidate letter once; judge per metric
            parses = []
            for letter in letters:
                pm, err = extract_order3(
                    letter["content_text"], period_j, anchors)
                parses.append((letter, pm, err))
            for metric in gaps:
                passing = [(letter, pm[metric])
                           for letter, pm, err in parses
                           if pm and pm[metric]["state"] == STATE_RECOVERED]
                if len(passing) == 1:
                    letter, outcome = passing[0]
                    evidence = {
                        "report_id": letter["report_id"],
                        "rv_id": letter["rv_id"],
                        "title": letter["title"],
                        "published_at": str(letter["published_at"]),
                        "source_url": letter["source_url"],
                        "payload_type": letter["payload_type"],
                        **outcome["evidence"],
                    }
                    _record(cid, metric, STATE_RECOVERED, {
                        "order": 3, "value": float(outcome["value"]),
                        "window_dates": outcome["window_dates"],
                        "evidence": evidence})
                elif len(passing) > 1:
                    _record(cid, metric, STATE_AMBIGUOUS_LETTERS, {
                        "reason": f"{len(passing)} payload letters of the "
                                  "same period both reproduce the anchors "
                                  "— identity not provable"})
                else:
                    # no letter recovered this metric: the most precise
                    # per-metric refusal state available
                    state = None
                    for _letter, pm, err in parses:
                        if pm and pm[metric].get("state"):
                            st = pm[metric]["state"]
                            if st in (STATE_ROW_AMBIGUOUS,
                                      STATE_BLANK_ANNUAL_CELL):
                                state = st
                                break
                            if state is None:
                                state = st
                    if state is None:
                        state = next((err for _l, _p, err in parses
                                      if err), STATE_ROW_FAILED)
                    _record(cid, metric, state, {
                        "reason": "letter evidence does not prove the "
                                  "order-3 leg for this metric"})
        census = {**{m: dict(sorted(c.items()))
                     for m, c in census.items() if m != "class_rollup"},
                  "class_rollup": dict(sorted(
                      census["class_rollup"].items()))}
        return results, census
    finally:
        if own_conn:
            pg.close()
