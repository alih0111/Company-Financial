"""Build V12.37 from unchanged local raw archives with the V12.36 extraction correction.

No network, database, package installation, contract edit, or ledger write.
V12.32/V12.33 outputs remain untouched.
"""
from __future__ import annotations
import ast, hashlib, json, sys
import os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ranking_research.top10_six_month.common import legacy
from ranking_research.top10_six_month.market_adapter import correct_volume
from ranking_research.v2_inputs import ArchiveSnapshots, CM
from ranking_research.return_v2.events import cutoff
from ranking_research.future_eval_v12_30.monthly_sales_replay import build_monthly, timeline
from ranking_research.return_v8.features import FIELDS
from ranking_research.future_eval_v12_30.income_statement_selection import income_statement_view, latest_income_statement_cell, locked_engine_factor

DATE = os.environ.get("V1237_RANKING_DATE", "2026-10-14")
OWNER_PACK = ROOT / "ranking_research/output/owner_current_market_2026-10-15"
OWNER_REG = json.loads((OWNER_PACK / "registration.json").read_text(encoding="utf-8"))
OWNER_INPUTS = Path(OWNER_REG["financial_path"]).parent
PACK = Path(os.environ.get("V1237_MARKET_PACK", str(OWNER_PACK)))
REPORTS_PATH = Path(os.environ.get("V1237_REPORTS_PATH", str(OWNER_INPUTS / "input_reports.json")))
COMPARATIVES_PATH = Path(os.environ.get("V1237_COMPARATIVES_PATH", str(OWNER_INPUTS / "comparative_lineage.json")))
OWNER_LINEAGE_PATH = Path(os.environ.get("V1237_OWNER_LINEAGE_PATH", str(OWNER_INPUTS / "current_live_lineage.json")))
SHARE_PATH = Path(OWNER_REG["share_snapshot_path"])
EVENTS = Path(os.environ.get("V1237_EVENTS_PATH", str(ROOT / "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet")))
UNIVERSE = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
OUT = Path(os.environ.get("V1237_OUTPUT_DIR", str(ROOT / "ranking_research/output/return_v12_37/v12_37_20261022_existing_archive_extraction_fix_01")))
FINANCIAL = [i for i in range(21) if i not in (15, 19, 20)]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def ratio(a, b, *, positive_denominator=False, scale=1.0):
    if a is None or b is None: return np.nan
    try: a, b = float(a), float(b)
    except (TypeError, ValueError): return np.nan
    if not np.isfinite(a) or not np.isfinite(b) or b == 0 or (positive_denominator and b <= 0): return np.nan
    return a / b * scale

class LocalSnapshots(ArchiveSnapshots):
    """All cross-period facts are already attached from the verified local lineage."""
    def parsed(self, record):
        return {"statements": {}, "period_headers": {}}

def load_report_records():
    records = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
    comparisons = json.loads(COMPARATIVES_PATH.read_text(encoding="utf-8"))
    by_key = {(r["company_id"], str(r["tracing_no"])): r for r in records}
    matched = 0
    for item in comparisons:
        rec = by_key.get((item["company_id"], str(item["tracing_no"])))
        if rec is None: raise RuntimeError("UNMATCHED_VERIFIED_COMPARATIVE")
        if item.get("source_page_id") is not None:
            if (item.get("company_id_verified") != item.get("company_id")
                    or item.get("basis") != "parent"
                    or int(item.get("period_order", 0)) not in (2, 3)
                    or item.get("canonical_unit") not in ("rial", "rial_per_share")):
                raise RuntimeError("COMPARATIVE_LINEAGE_IDENTITY_OR_BASIS_INVALID")
            available = pd.Timestamp(item.get("available_at_utc"))
            if available.tzinfo is None or available.tz_convert("UTC") > pd.Timestamp(cutoff(DATE)):
                raise RuntimeError("COMPARATIVE_NOT_AVAILABLE_AT_EVALUATION_CUTOFF")
            manifest_path = Path(rec["dynamic_manifest_path"])
            manifest_bytes = manifest_path.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != rec.get("dynamic_manifest_sha256"):
                raise RuntimeError("COMPARATIVE_DYNAMIC_MANIFEST_HASH_MISMATCH")
            manifest = json.loads(manifest_bytes)
            page = next((p for p in manifest.get("pages", []) if p.get("page_id") == item.get("source_page_id")), None)
            source_path = Path(item.get("source_page_path", ""))
            if (page is None or str(source_path.resolve()) != str(Path(page["path"]).resolve())
                    or not source_path.is_file() or sha(source_path) != item.get("source_page_sha256")
                    or page.get("sha256") != item.get("source_page_sha256")
                    or page.get("received_at_utc") != item.get("source_page_received_at_utc")
                    or manifest.get("available_at_utc") != item.get("available_at_utc")):
                raise RuntimeError("COMPARATIVE_SOURCE_PAGE_RECEIPT_MISMATCH")
        fact = {"statement_type": item["statement_type"], "metric_code": item["metric_code"],
                "value": float(item["canonical_value"]), "unit": item["canonical_unit"],
                "period_order": int(item["period_order"]), "basis": "parent"}
        old = next((f for f in rec["facts"] if (f.get("statement_type"), f.get("metric_code"), int(f.get("period_order", 1))) ==
                    (fact["statement_type"], fact["metric_code"], fact["period_order"])), None)
        if old is not None:
            if not np.isclose(float(old["value"]), fact["value"], rtol=1e-12, atol=1):
                raise RuntimeError("COMPARATIVE_FACT_CONFLICT")
        else: rec["facts"].append(fact)
        matched += 1
    if matched != len(comparisons): raise RuntimeError("COMPARATIVE_LINEAGE_COUNT_MISMATCH")
    return records, len(comparisons)

def extend_market(md, expected):
    """Append exact-ID daily raw prices; verify all overlap against old cache."""
    files = list(PACK.glob("*.json"))
    loaded = {}
    for path in files:
        if path.name in ("registration.json", "progress.json"): continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        cid = obj.get("company_id")
        if cid in expected.company_id.astype(str).values:
            if cid in loaded: raise RuntimeError("DUPLICATE_FROZEN_ID_IN_MARKET_PACKAGE")
            if str(obj.get("symbol")) != str(expected.set_index("company_id").loc[cid, "symbol"]):
                raise RuntimeError("MARKET_PACKAGE_ID_SYMBOL_MISMATCH")
            loaded[cid] = obj
    ids = set(expected.company_id.astype(str))
    if set(loaded) != ids: raise RuntimeError("MARKET_PACKAGE_FROZEN_ID_COVERAGE_MISMATCH")
    snapshots = json.loads(SHARE_PATH.read_text(encoding="utf-8"))
    share_rows = {str(x.get("id")): x for x in snapshots.get("rows", []) if x.get("id") is not None}
    report = {"records": len(loaded), "appended_rows": 0, "overlap_rows": 0, "overlap_value_mismatches": 0,
              "price_revision_rows": 0, "largest_close_revision_fraction": 0.0,
              "turnover_or_volume_revisions": 0, "largest_turnover_or_volume_revision_fraction": 0.0,
              "latest_date_count": 0, "market_latest_session": None,
              "symbols_with_30_valid_prices": 0, "share_matches": 0,
              "share_snapshot_collected_at": snapshots.get("collected_at"), "shares_by_company_id": {}}
    for row in expected.itertuples(index=False):
        obj = loaded[str(row.company_id)]; sym = str(row.symbol)
        if str(obj.get("security_id")) != str(md.sym2sid.get(sym)):
            raise RuntimeError("MARKET_INSCODE_SECURITY_ID_MISMATCH")
        raw_daily = obj.get("daily", [])
        daily = ast.literal_eval(raw_daily) if isinstance(raw_daily, str) else raw_daily
        by_date = {str(x["date"]): x for x in daily if x.get("date")}
        if by_date:
            report["market_latest_session"] = max(str(report["market_latest_session"] or ""), max(by_date))
        rec = md.data.get(sym)
        if rec is None: raise RuntimeError("MARKET_SYMBOL_MISSING_FROM_LOCAL_CACHE")
        old = {str(d): i for i, d in enumerate(rec["dates"])}
        for day, x in by_date.items():
            vals = (float(x["close_rial"]), float(x["trade_value_rial"]), float(x["volume"]))
            if day in old:
                i = old[day]; report["overlap_rows"] += 1
                checks = (rec["c"][i], rec["tval"][i], rec["vol"][i])
                if not np.isclose(float(checks[0]), vals[0], rtol=1e-10, atol=1):
                    report["price_revision_rows"] += 1
                    report["largest_close_revision_fraction"] = max(report["largest_close_revision_fraction"],abs(float(checks[0])-vals[0])/max(abs(float(checks[0])),abs(vals[0]),1.0))
                rec["c"][i] = vals[0]
                if not all(np.isclose(float(a), b, rtol=1e-10, atol=1) for a, b in zip(checks[1:], vals[1:])):
                    report["overlap_value_mismatches"] += 1
                    frac=max(abs(float(a)-b)/max(abs(float(a)),abs(b),1.0) for a,b in zip(checks[1:],vals[1:]))
                    report["largest_turnover_or_volume_revision_fraction"] = max(report["largest_turnover_or_volume_revision_fraction"],frac)
                    report["turnover_or_volume_revisions"] += 1
                rec["tval"][i], rec["vol"][i] = vals[1], vals[2]
        new_days = sorted(d for d in by_date if d not in old)
        if new_days:
            rec["dates"] = np.concatenate([np.asarray(rec["dates"], dtype=str), np.asarray(new_days, dtype=str)])
            for key, val_idx in (("c", 0), ("tval", 1), ("vol", 2)):
                rec[key] = np.concatenate([np.asarray(rec[key], dtype=float), np.asarray([float(by_date[d][("close_rial", "trade_value_rial", "volume")[val_idx]]) for d in new_days])])
            order = np.argsort(rec["dates"], kind="stable")
            for key in ("dates", "c", "tval", "vol", "tcnt", "o", "h", "l"):
                if key in rec and len(rec[key]) == len(order): rec[key] = np.asarray(rec[key])[order]
            report["appended_rows"] += len(new_days)
        report["latest_date_count"] += int(str(max(by_date)) == DATE)
        good = (np.asarray(rec["dates"], dtype=str) <= DATE) & np.isfinite(rec["vol"]) & (rec["vol"] > 0) & np.isfinite(rec["tval"]) & (rec["tval"] > 0) & np.isfinite(rec["c"]) & (rec["c"] > 0)
        report["symbols_with_30_valid_prices"] += int(good.sum() >= 30)
        share = share_rows.get(str(obj.get("ins_code")))
        if share and share.get("z") and float(share["z"]) > 0:
            report["share_matches"] += 1
            report["shares_by_company_id"][str(row.company_id)] = {"shares": float(share["z"]), "market_snapshot_id": str(share.get("id")), "symbol_l18": share.get("l18"), "source_collected_at": snapshots.get("collected_at")}
    return loaded, report

def main():
    if not all((ROOT / "score_v2_research/_cache" / n).exists() for n in ("corp_actions_confirmed.parquet", "calendar.parquet", "securities.parquet")):
        raise RuntimeError("LOCAL_MARKET_CACHE_INCOMPLETE")
    _, _, _, _, R = legacy(); ref = R.V.load_reference_data(); md = R.V.MarketData(ref)
    volume_audit = correct_volume(md)
    expected = pd.read_csv(UNIVERSE, dtype={"symbol": str, "company_id": str})
    loaded_market, market_audit = extend_market(md, expected)
    records, comparison_count = load_report_records()
    owner_features_path = Path(OWNER_REG["financial_path"])
    owner_frame = pd.read_csv(owner_features_path, dtype={"company_id": str, "symbol": str}).set_index("company_id", drop=False)
    if owner_frame.index.duplicated().any(): raise RuntimeError("OWNER_CURRENT_FEATURE_IDENTITY_DUPLICATE")
    owner_lineage_path = OWNER_LINEAGE_PATH
    owner_lineage = json.loads(owner_lineage_path.read_text(encoding="utf-8"))
    fresh_ids_path = os.environ.get("V1237_FRESH_FINANCIAL_IDS_PATH")
    fresh_financial_ids = set(json.loads(Path(fresh_ids_path).read_text(encoding="utf-8"))) if fresh_ids_path and Path(fresh_ids_path).exists() else set()
    lineage_by_company = {}
    for item in owner_lineage: lineage_by_company.setdefault(str(item["company_id"]), []).append(item)
    selected_ids = {str(x.company_id): {"symbol": str(x.symbol), "security_id": md.sym2sid.get(str(x.symbol))} for x in expected.itertuples(index=False)}
    if any(not x["security_id"] for x in selected_ids.values()): raise RuntimeError("FROZEN_ID_TO_SECURITY_JOIN_FAILED")
    gaps_path = ROOT / "ranking_research/return_v6/known_report_gap_events.parquet"
    from ranking_research.return_v6.common import V2
    gaps_all = pd.read_parquet(V2 / "known_report_gap_events.parquet")
    for cid in selected_ids:
        pass
    from ranking_research.v2_inputs import H
    intervals = json.loads((ROOT / "qvt_backtest/output/financial_history/share_intervals.json").read_text(encoding="utf-8"))["intervals"]
    snapshots = LocalSnapshots(records, [], selected_ids, md, intervals)
    eng, metrics, _ = snapshots.snapshot(DATE, cutoff(DATE))
    report_index = eng.report_index()
    all_titles = eng.codal_titles
    income_index = income_statement_view(report_index)
    income_periods = {cid: set(periods) for cid, periods in income_index.items()}
    eng.codal_titles = [title for title in all_titles
        if (title["company_id"], tuple(CM.fiscal_ym(title["period_end_date"]))) in
        {(cid, period) for cid, periods in income_periods.items() for period in periods}]
    # The locked financial engine is reused unchanged. Its statement-index view
    # now excludes balance-only report markers, which must not block an older
    # but still latest-available income statement.
    eng.report_index = lambda: income_index
    income_metrics = eng.compute()
    eng.report_index = lambda: report_index
    eng.codal_titles = all_titles
    selected_records = [r for r in H.select_asof(records, cutoff(DATE)) if r["period_end"] <= DATE]
    selected_by_company = {}
    for report in selected_records: selected_by_company.setdefault(str(report["company_id"]), []).append(report)

    skeleton = expected[["symbol", "company_id"]].copy(); skeleton["decision_time"] = DATE
    monthly_events = pd.read_parquet(EVENTS)
    monthly = build_monthly(monthly_events, skeleton, [DATE], [], jalali=True, keep_corrections=True)
    monthly = monthly.drop_duplicates(["symbol", "company_id"], keep="last")
    monthly_history = timeline(monthly_events, [DATE], jalali=True, keep_corrections=True)
    event_by_id = monthly_events.set_index("event_id", drop=False).to_dict("index")
    rows = []
    for base in expected.itertuples(index=False):
        cid, sym = str(base.company_id), str(base.symbol); metric = metrics.get(cid, {}); rep = report_index.get(cid, {})
        if cid not in owner_frame.index or str(owner_frame.loc[cid,"symbol"]) != sym: raise RuntimeError("OWNER_CURRENT_FEATURE_IDENTITY_MISMATCH")
        current = owner_frame.loc[cid]
        if isinstance(current, pd.DataFrame): raise RuntimeError("OWNER_CURRENT_FEATURE_IDENTITY_DUPLICATE")
        hist = json.loads(current.history_values) if pd.notna(current.history_values) else []
        owner_values = {}; net = op = revenue = np.nan
        # The alternate model's score columns are never read. These are its retained
        # canonical TTM statement values and balance inputs, independently mapped.
        if cid not in fresh_financial_ids and current.source_valid and len(hist) >= 4 and all(isinstance(x,dict) for x in hist[:4]):
            newest = hist[0]
            owner_net = float(current.net_profit_ttm) if pd.notna(current.net_profit_ttm) else np.nan
            owner_op = float(current.operating_profit_ttm) if pd.notna(current.operating_profit_ttm) else np.nan
            owner_rev = float(newest.get("revenue")) if newest.get("revenue") is not None else np.nan
            if np.isfinite(owner_net) and np.isfinite(owner_op) and np.isfinite(owner_rev):
                owner_values = {"revenue_growth": float(current.sales_yoy)*100 if str(current.sales_growth_status)=="comparable" and pd.notna(current.sales_yoy) else np.nan,
                           "operating_margin": ratio(owner_op, abs(owner_rev), scale=100),
                           "net_margin": ratio(owner_net, abs(owner_rev), scale=100),
                           "roe": ratio(owner_net, current.total_equity, positive_denominator=True, scale=100),
                           "interest_coverage": float(current.interest_coverage_ttm) if pd.notna(current.interest_coverage_ttm) else np.nan,
                           "cash_conversion": ratio(newest.get("operating_cash_flow"), owner_net, positive_denominator=True),
                           "leverage": ratio(float(current.debt_ratio)*float(current.total_assets), current.total_equity, positive_denominator=True) if pd.notna(current.debt_ratio) and pd.notna(current.total_assets) else np.nan,
                           "current_ratio": float(current.current_ratio) if pd.notna(current.current_ratio) else np.nan}
                net, op, revenue = owner_net, owner_op, owner_rev
        else: owner_values = {}
        latest = max(rep, default=None); cell = rep.get(latest, {}); own = lambda name, order=1: cell.get(name, {}).get(order)
        latest_income, income_cell = latest_income_statement_cell(income_index, cid)
        income_own = lambda name, order=1: income_cell.get(name, {}).get(order)
        net, op, revenue = (net, op, revenue) if owner_values else (metric.get("net_profit_ttm"), metric.get("operating_profit_ttm"), metric.get("revenue_ttm"))
        values = {name: metric.get(name, np.nan) for name in FIELDS}
        for name in ("sales_growth_12m", "sales_growth_3m", "sales_stability"): values[name] = np.nan
        values["operating_margin"] = ratio(op, abs(revenue) if revenue is not None else None, scale=100)
        values["net_margin"] = ratio(net, abs(revenue) if revenue is not None else None, scale=100)
        values["roe"] = ratio(net, own("total_equity"), positive_denominator=True, scale=100)
        op_now = ratio(own("operating_profit"), abs(own("revenue")) if own("revenue") is not None else None, scale=100)
        op_prev = ratio(own("operating_profit", 2), abs(own("revenue", 2)) if own("revenue", 2) is not None else None, scale=100)
        values["margin_trend"] = op_now-op_prev if np.isfinite(op_now) and np.isfinite(op_prev) and abs(op_now)<=200 and abs(op_prev)<=200 else np.nan
        finance_cost = own("finance_cost"); values["interest_coverage"] = ratio(own("operating_profit"), abs(finance_cost) if finance_cost is not None else None)
        values["cash_conversion"] = ratio(metric.get("ocf_ttm"), net, positive_denominator=True)
        values["earnings_quality"] = ratio(abs(own("other_non_operating")) if own("other_non_operating") is not None else None, abs(own("operating_profit")) if own("operating_profit") is not None else None, scale=100)
        income_values = income_metrics.get(cid, {})
        for name in ("operating_profit_growth", "net_profit_growth", "margin_trend", "earnings_quality"):
            candidate = income_values.get(name)
            # Preserve the direct locked-formula value already derived from the
            # selected period cell when the aggregate engine has no value. The
            # former unconditional NaN assignment erased valid local inputs.
            # These are TTM/paired-period outputs from the locked engine. A
            # single-period report ratio is not a valid TTM fallback.
            selected_value = locked_engine_factor(candidate)
            values[name] = selected_value if selected_value is not None else np.nan
        values["leverage"] = ratio(own("total_liabilities"), own("total_equity"), positive_denominator=True)
        values["current_ratio"] = ratio(own("current_assets"), own("current_liabilities"), positive_denominator=True)
        for field in ("operating_margin", "net_margin"):
            if np.isfinite(values[field]) and abs(values[field])>200: values[field]=np.nan
        if np.isfinite(values["roe"]) and abs(values["roe"])>300: values["roe"]=np.nan
        if np.isfinite(values["interest_coverage"]) and values["interest_coverage"]>10000: values["interest_coverage"]=np.nan
        if not np.isfinite(values["cash_conversion"]) or not -2<=values["cash_conversion"]<=5: values["cash_conversion"]=np.nan
        if not np.isfinite(values["leverage"]) or not 0<=values["leverage"]<=50: values["leverage"]=np.nan
        if not np.isfinite(values["current_ratio"]) or not 0<=values["current_ratio"]<=15: values["current_ratio"]=np.nan
        for name,value in owner_values.items():
            if np.isfinite(value): values[name] = value
        if np.isfinite(values["operating_margin"]) and abs(values["operating_margin"])>200: values["operating_margin"]=np.nan
        if np.isfinite(values["net_margin"]) and abs(values["net_margin"])>200: values["net_margin"]=np.nan
        if np.isfinite(values["roe"]) and abs(values["roe"])>300: values["roe"]=np.nan
        if np.isfinite(values["interest_coverage"]) and values["interest_coverage"]>10000: values["interest_coverage"]=np.nan
        if not np.isfinite(values["cash_conversion"]) or not -2<=values["cash_conversion"]<=5: values["cash_conversion"]=np.nan
        if not np.isfinite(values["leverage"]) or not 0<=values["leverage"]<=50: values["leverage"]=np.nan
        if not np.isfinite(values["current_ratio"]) or not 0<=values["current_ratio"]<=15: values["current_ratio"]=np.nan

        market = md.data.get(sym); idx = np.array([], dtype=int)
        if market is not None:
            dates=np.asarray(market["dates"],dtype=str)
            idx=np.flatnonzero((dates<=DATE)&(market["vol"]>0)&(market["tval"]>0)&np.isfinite(market["c"])&(market["c"]>0))
        tail=idx[-30:] if len(idx) else np.array([],dtype=int)
        if len(tail): values["avg_trade_value_30d"]=float(np.mean(market["tval"][tail]))
        else: values["avg_trade_value_30d"]=np.nan
        # Corporate-action cache ends on 2026-09-30. Do not treat unverified
        # 2026-10-01..14 actions as absent; locked price-return factors are masked.
        values["volatility_30d"]=np.nan; values["price_momentum_30d"]=np.nan
        last_i=idx[-1] if len(idx) else None; price=float(market["c"][last_i]) if last_i is not None else np.nan
        latest_price_date = str(market["dates"][last_i]) if last_i is not None else None
        latest_price_age = (pd.Timestamp(DATE)-pd.Timestamp(latest_price_date)).days if latest_price_date else 9999
        share=market_audit["shares_by_company_id"].get(cid)
        raw_eps, raw_report_net=own("eps"),own("net_profit")
        eps=ratio(net,raw_report_net,positive_denominator=True)*float(raw_eps) if raw_eps is not None and float(raw_eps)>0 else np.nan
        share_ok=bool(share and last_i is not None and 0 <= latest_price_age <= 7)
        values["pe"]=ratio(price,eps,positive_denominator=True) if share_ok else np.nan
        values["ps"]=values["pe"]*values["net_margin"]/100 if share_ok and np.isfinite(values["pe"]) and 0<values["pe"]<=60 and values["net_margin"]>0 and values["pe"]*values["net_margin"]/100<=100 else np.nan
        values["pb"]=values["pe"]*values["roe"]/100 if share_ok and np.isfinite(values["pe"]) and 0<values["pe"]<=60 and values["roe"]>0 and values["pe"]*values["roe"]/100<=30 else np.nan
        monthly_row=monthly.loc[(monthly.company_id.astype(str)==cid)&(monthly.symbol.astype(str)==sym)]
        mrow=monthly_row.iloc[-1] if len(monthly_row) else None
        if mrow is not None:
            for field in ("sales_growth_12m","sales_growth_3m","sales_stability"): values[field]=mrow.get(field,np.nan)
        lineage=[x for x in lineage_by_company.get(cid,[]) if str(x.get("period"))<=DATE and x.get("published_at") and pd.Timestamp(x["published_at"])<pd.Timestamp(cutoff(DATE))]
        finance=[{"tracing_no":str(x.get("tracing_no")),"period_end":str(x.get("period")),"published_at":str(x.get("published_at")),"source":x.get("source"),"received_at":x.get("observed_at")} for x in lineage]
        source_period=max((r["period_end"] for r in selected_by_company.get(cid,[])),default=None)
        owner_period=str(current.financial_period_end) if pd.notna(current.financial_period_end) else None
        # These four values are explicitly tied to the latest income-statement
        # period, which can differ from the latest balance-sheet period above.
        # Their period/publication lineage is stored per row; no value is shifted
        # to the newer balance-sheet date.
        income_period_date = None
        income_sources = []
        if latest_income is not None:
            for report in selected_records:
                if str(report["company_id"]) != cid:
                    continue
                key = tuple(CM.fiscal_ym(pd.Timestamp(report["period_end"]).date()))
                if key == latest_income and any(f.get("statement_type") == "income_statement" for f in report.get("facts", [])):
                    income_sources.append({"tracing_no": str(report["tracing_no"]), "period_end": str(report["period_end"]),
                        "published_at": str(report["published_at"]), "observed_at": str(report.get("observed_at")),
                        "sha256": report.get("sha256"), "source": report.get("source")})
            if income_sources:
                income_period_date = max(x["period_end"] for x in income_sources)
        latest_selected=max(selected_by_company.get(cid,[]),key=lambda x:(str(x.get("period_end")),str(x.get("published_at"))),default=None)
        latest_report={"period_end":str(latest_selected.get("period_end")) if latest_selected else (str(current.financial_period_end) if pd.notna(current.financial_period_end) else None),
                       "published_at":str(latest_selected.get("published_at")) if latest_selected else max((x["published_at"] for x in finance if x["period_end"]==str(current.financial_period_end)),default=None)}
        financial_age=(pd.Timestamp(DATE)-pd.Timestamp(latest_report["period_end"])).days if latest_report.get("period_end") else 9999
        price_date=str(market["dates"][last_i]) if last_i is not None else None
        price_age=(pd.Timestamp(DATE)-pd.Timestamp(price_date)).days if price_date else 9999
        report_count=len({x["period_end"] for x in finance}); market_n=len(idx);now=pd.Timestamp(DATE)
        jy=now.year-(622 if now.month<3 or now.month==3 and now.day<21 else 621); jm={1:11,2:12,3:1,4:2,5:3,6:4,7:5,8:6,9:7,10:8,11:9,12:10}[now.month]
        try: ly,lm=map(int,json.loads(current.quarter_keys)[0])
        except Exception: ly,lm=latest if latest else (0,0)
        months_old=jy*12+jm-ly*12-lm
        dq=(.28 if report_count>=16 else .16 if report_count>=8 else .09 if report_count>=4 else 0)+(.21 if market_n>=90 else .13 if market_n>=30 else .06 if market_n>=10 else 0)+(.09 if last_i is not None else 0)+(.08 if finance and months_old<=5 else .045 if finance and months_old<=8 else 0)+(.06 if price_age<=7 else .035 if price_age<=14 else 0)
        chosen={}
        for r in finance:
            key=str(r["period_end"]); pub=pd.Timestamp(r["published_at"])
            if key not in chosen or pub>chosen[key]: chosen[key]=pub
        latest_period=max(chosen,default="0000")
        gaps=gaps_all[(gaps_all.company_id.astype(str)==cid)&(gaps_all.day.astype(str)<=DATE)]
        blocked=any(bool(g.guard_period) and str(g.guard_period)<=DATE and (str(g.guard_period)>latest_period or str(g.guard_period) in chosen and g.pub>chosen[str(g.guard_period)] and (pd.Timestamp(latest_period)-pd.Timestamp(g.guard_period)).days<1000) for g in gaps.itertuples())
        if blocked:
            for name in FIELDS[2:15]+["leverage","current_ratio"]: values[name]=np.nan
        # Ratios that need current point-in-time shares use the contemporaneous
        # TSETMC share observation, never another model's stored valuation score.
        share=market_audit["shares_by_company_id"].get(cid)
        share_ok=bool(share and last_i is not None and 0 <= latest_price_age <= 7)
        market_cap=share["shares"]*price if share_ok else np.nan
        values["pe"]=ratio(market_cap,net,positive_denominator=True)
        values["ps"]=ratio(market_cap,revenue,positive_denominator=True)
        current_equity=own("total_equity") if cid in fresh_financial_ids else (current.total_equity if pd.notna(current.total_equity) else None)
        values["pb"]=ratio(market_cap,current_equity,positive_denominator=True) if current_equity is not None else np.nan
        if not (np.isfinite(values["pe"]) and 0<values["pe"]<=60): values["pe"]=np.nan
        if not (np.isfinite(values["ps"]) and 0<values["ps"]<=100): values["ps"]=np.nan
        if not (np.isfinite(values["pb"]) and 0<values["pb"]<=30): values["pb"]=np.nan
        versions=[]
        for known,month,value,state,event_id in monthly_history.get(cid,[]):
            if str(known)[:10]>DATE: continue
            ev=event_by_id.get(str(event_id),{})
            versions.append({"period_month":month,"known_from":str(known),"sales_current_rial":value,"version_state":state,"event_id":str(event_id),"published_at":str(ev.get("published_at")),"source":ev.get("source"),"source_url":ev.get("source_url"),"received_at":None})
        rows.append({"decision_time":DATE,"effective_date":DATE,"evaluation_date":DATE,"publication_cutoff":cutoff(DATE).isoformat(),"symbol":sym,"company_id":cid,"symbol_index":int(base.symbol_index),**values,"net_profit_ttm":net,"dq":float(dq),"publication_cutoff_at":cutoff(DATE).isoformat(),"price_date":price_date,"financial_period_end":latest_report.get("period_end"),"financial_latest_published_at":latest_report.get("published_at"),"financial_factor_period_end":income_period_date,"financial_factor_lineage":json.dumps(income_sources,ensure_ascii=False),"received_at":None,"financial_age_days":financial_age,"blocked":bool(blocked),"financial_lineage":json.dumps(finance,ensure_ascii=False),"sales_lineage":json.dumps({"selected_month_versions":versions,"latest_period":mrow.get("latest_period") if mrow is not None else None,"known_months":int(mrow.get("known_months",0) or 0) if mrow is not None else 0,"source":str(EVENTS.relative_to(ROOT)).replace("\\","/"),"received_at":None,"correction_policy":"V11 verified correction replay; unverified correction masks previous value"},ensure_ascii=False),"observed_masks":json.dumps({f:bool(np.isfinite(float(values[f]))) if values[f] is not None else False for f in FIELDS}),"financial_report_count":len(finance),"price_valid_sessions_30d":int(len(tail)),"price_age_days":int(price_age),"valuation_provenance":json.dumps({"share_snapshot_id":share.get("market_snapshot_id") if share else None,"share_as_of":price_date if share else None,"share_collected_at":market_audit["share_snapshot_collected_at"],"price_date":price_date,"price_basis":"unadjusted TSETMC close; adjusted share/corporate action metadata unavailable after 2026-09-30"},ensure_ascii=False)})
    panel=pd.DataFrame(rows).sort_values("symbol_index",kind="stable").reset_index(drop=True)
    expected_ids=set(expected.company_id.astype(str))
    if len(panel)!=254 or panel.company_id.nunique()!=254 or set(panel.company_id.astype(str))!=expected_ids: raise RuntimeError("FROZEN_IDENTITY_PANEL_FAILED")
    OUT.mkdir(parents=True,exist_ok=True); p=OUT/"normalized_raw_factor_panel.parquet"; panel.to_parquet(p,index=False,compression="zstd");panel.to_csv(OUT/"normalized_raw_factor_panel.csv",index=False,encoding="utf-8-sig")
    counts={f:int(pd.to_numeric(panel[f],errors="coerce").notna().sum()) for f in FIELDS}
    market_files={str(x.relative_to(ROOT)).replace("\\","/"):sha(x) for x in sorted(PACK.glob("*.json")) if x.name not in ("registration.json","progress.json")}
    manifest={"status":"PREPARATION_UNCONFIRMED","evaluation_date":DATE,"publication_cutoff_at":cutoff(DATE).isoformat(),"received_at":None,"receipt_limitation":"Source acquisition times do not establish availability at an earlier cutoff; no PIT claim.","universe_count":254,"identity_status":"Exact frozen company_id and symbol joins; all 254 retained.","source_dates":{"market_latest_session":market_audit["market_latest_session"],"financial_period_latest":max(str(x.financial_period_end) for x in owner_frame.itertuples() if pd.notna(x.financial_period_end)),"financial_publication_latest":max(x["published_at"] for z in lineage_by_company.values() for x in z if x.get("published_at")),"monthly_publication_latest":str(monthly_events.published_at.max()),"corporate_action_cache_latest":"2026-09-30"},"market_package":{"path":str(PACK.relative_to(ROOT)).replace("\\","/"),"registration_sha256":sha(PACK/"registration.json"),"daily_file_sha256":market_files,"shares_source_path":str(SHARE_PATH.relative_to(ROOT)).replace("\\","/"),"audit":{k:v for k,v in market_audit.items() if k!="shares_by_company_id"},"volume_audit":volume_audit},"financial":{"reports_path":str(REPORTS_PATH.relative_to(ROOT)).replace("\\","/"),"comparatives_path":str(COMPARATIVES_PATH.relative_to(ROOT)).replace("\\","/"),"current_features_path":str(owner_features_path.relative_to(ROOT)).replace("\\","/"),"current_lineage_path":str(owner_lineage_path.relative_to(ROOT)).replace("\\","/"),"report_versions":len(records),"verified_comparative_facts":comparison_count,"selected_by_company":254,"published_at_preserved":True,"observed_at_not_used_as_received_at":True},"factors":{"factor_observed_counts":counts,"volatility_30d":"masked: official confirmed corporate-action cache only through 2026-09-30","price_momentum_30d":"masked: official confirmed corporate-action cache only through 2026-09-30"},"source_sha256":{str(x.relative_to(ROOT)).replace("\\","/"):sha(x) for x in [REPORTS_PATH,COMPARATIVES_PATH,owner_features_path,owner_lineage_path,SHARE_PATH,PACK/"registration.json",EVENTS,UNIVERSE,ROOT/"score_v2_research/_cache/corp_actions_confirmed.parquet",ROOT/"score_v2_research/_cache/calendar.parquet"]},"panel_sha256":sha(p),"network_requests":0,"database_connections":0,"package_installs":0,"official_ledger_written":False}
    (OUT/"extraction_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(OUT),"evaluation_date":DATE,"factor_observed_counts":counts,"market_audit":manifest["market_package"]["audit"],"verified_comparative_facts":comparison_count,"panel_sha256":manifest["panel_sha256"]},ensure_ascii=False))

if __name__=="__main__": main()
