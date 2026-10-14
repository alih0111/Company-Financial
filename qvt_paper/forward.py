"""Forward QVT decision journal. No brokerage, database writes or historical fills.

refresh exports the real authenticated handler locally, freezes a monthly decision,
then observes only source-proven future sessions. --fetch reads official TSETMC
history for the frozen universe. Outputs are separate from certified Shadow V1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_engine import choose, complete

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
CACHE = ROOT / "provenance_v1/output/coverage_verified/market/closing"
TEHRAN = ZoneInfo("Asia/Tehran")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, obj, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        tmp.replace(path)


def stamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def profile(row):
    return (row["model_family"], *(tuple(sorted(row[a]["scored_factors"])) for a in ("q", "v", "t")))


def checked_cache(cid):
    record = read(CACHE / f"{cid}.json")
    # Cache writer intentionally uses JSON's default ASCII serialization here.
    expected = hashlib.sha256(json.dumps(record["rows"], sort_keys=True).encode()).hexdigest()
    if record["company_id"] != cid or record["payload_sha256"] != expected:
        raise ValueError("price-cache provenance mismatch")
    ins = str(record["ins_code"])
    dates = set()
    for day in record["rows"]:
        raw = day["raw"]
        if str(raw["insCode"]) != ins or dt.datetime.strptime(str(raw["dEven"]), "%Y%m%d").date().isoformat() != day["date"]:
            raise ValueError("price identity/date mismatch")
        if day["date"] in dates:
            raise ValueError("duplicate price date")
        dates.add(day["date"])
        for field in ("pClosing", "priceYesterday", "qTotTran5J"):
            value = float(raw[field])
            if not math.isfinite(value) or value < 0 or (field == "pClosing" and value == 0):
                raise ValueError("invalid source price/volume")
    return record


def canonical_identities():
    # Read only, same canonical mapping used by the verified collector.
    import sys
    os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
    sys.path.insert(0, str(ROOT / "canonical_postgres_v1_2_1/analytics_canonical_v1"))
    from compute_metrics import pg_pilot_conn
    with pg_pilot_conn(autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only=on")
        return {str(r[0]): (str(r[1]), str(r[2])) for r in conn.execute(
            "SELECT id::text,company_id::text,tsetmc_ins_code FROM core.securities WHERE is_active=true").fetchall()}


def freeze(ranking, policy, now, out=OUTPUT):
    today = now.astimezone(TEHRAN).date().isoformat()
    if ranking["as_of"] != today or stamp(ranking["cutoff"]) > now:
        raise ValueError("new decisions require a same-day, non-future ranking; refresh the bundle")
    source_hashes = {a: ranking["sources"][a]["sha256"] for a in ("q", "v", "t")}
    if any(len(h) != 64 for h in source_hashes.values()):
        raise ValueError("missing source hashes")
    month = today[:7]
    destination = out / "decisions" / month
    if (destination / "decision.json").exists():
        existing = read(destination / "decision.json")
        if existing["policy_sha256"] != digest(policy):
            raise ValueError("frozen policy changed; use a new version and independent journal")
        return existing
    # A failed freeze can leave diagnostics, but never a half-published decision.
    folder = out / "decisions" / (".pending-" + uuid.uuid4().hex)
    rows = ranking["ranked"]
    selected, skipped = choose(rows, policy)
    universe = [r for r in rows if complete(r)]
    if len(universe) < 30:
        raise ValueError("insufficient frozen universe to independently evidence the session calendar")
    groups = {}
    for row in universe:
        groups.setdefault(profile(row), []).append(row)
    # Do not compare low-coverage stocks with complete stocks, or different families.
    comparable = max(groups.values(), key=lambda g: (len(g), str(profile(g[0]))))
    if len(comparable) < 20:
        raise ValueError("insufficient comparable cohort for disjoint high/low groups")
    comparable.sort(key=lambda r: (r["rank"], r["company_id"]))
    ids = canonical_identities()
    references = {}
    for row in universe:
        cid = row["company_id"]
        rec = checked_cache(cid)
        if ids.get(rec["security_id"]) != (cid, str(rec["ins_code"])):
            raise ValueError("canonical security identity does not match source cache")
        if stamp(rec["collected_at"]) > now:
            raise ValueError("future collection time")
        valid = [d for d in rec["rows"] if d["date"] <= today]
        if not valid:
            raise ValueError("missing current quote")
        last = max(valid, key=lambda d: d["date"])
        references[cid] = {"security_id": rec["security_id"], "ins_code": rec["ins_code"],
                           "symbol": row["symbol"], "date": last["date"], "close_rial": last["raw"]["pClosing"],
                           "cache_sha256": rec["payload_sha256"], "collected_at": rec["collected_at"]}
        save(folder / "initial_prices" / f"{cid}.json", rec, exclusive=True)
    for order in selected:
        order["reference"] = references[order["company_id"]]
    decision = {"version": policy["version"], "decision_id": f"QVT-PAPER-{month}", "mode": "reference_only",
                "frozen_at": now.isoformat(), "decision_date": today, "score_as_of": ranking["as_of"],
                "cutoff": ranking["cutoff"], "source_hashes": source_hashes,
                "policy_sha256": digest(policy), "policy": policy, "ranking_sha256": digest(ranking),
                "positions": selected, "skipped": skipped, "universe": references,
                "cohorts": {"high_score": [r["company_id"] for r in comparable[:10]],
                            "low_score": [r["company_id"] for r in comparable[-10:]],
                            "equal_weight": [r["company_id"] for r in comparable]},
                "cohort_factor_profile": profile(comparable[0]),
                "cash_weight": round(1 - sum(o["weight"] for o in selected), 10)}
    save(folder / "ranking.json", ranking, exclusive=True)
    save(folder / "policy.json", policy, exclusive=True)
    save(folder / "decision.json", decision, exclusive=True)
    folder.rename(destination)
    return read(destination / "decision.json")


def fetch_prices(decision, now, out):
    today = now.astimezone(TEHRAN).date()
    folder = out / "observations" / decision["decision_id"] / now.strftime("%Y%m%dT%H%M%S%fZ")
    for cid, identity in decision["universe"].items():
        ins = identity["ins_code"]
        url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins}/0"
        time.sleep(1.0)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://cdn.tsetmc.com/"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
        observed = dt.datetime.now(dt.timezone.utc)
        days = []
        for raw in payload.get("closingPriceDaily", []):
            if str(raw.get("insCode")) != ins:
                raise ValueError("official instrument identity mismatch")
            date = dt.datetime.strptime(str(raw["dEven"]), "%Y%m%d").date()
            if date > today or date.isoformat() < decision["decision_date"]:
                continue
            if date == today and observed.astimezone(TEHRAN).time() < dt.time(12, 45):
                continue
            days.append({"date": date.isoformat(), "raw": raw})
        rec = {"company_id": cid, "ins_code": ins, "collected_at": observed.isoformat(),
               "source_url": url, "rows": days, "payload_sha256": digest(days)}
        save(folder / f"{cid}.json", rec, exclusive=True)
    return folder


def collect_evidence(decision, out):
    panels = {cid: {} for cid in decision["universe"]}
    records = []
    for folder in sorted((out / "observations" / decision["decision_id"]).glob("*")):
        records.extend(sorted(folder.glob("*.json")))
    for path in records:
        rec = read(path)
        cid = rec["company_id"]
        if cid not in panels or str(rec["ins_code"]) != str(decision["universe"][cid]["ins_code"]):
            raise ValueError("observation identity mismatch")
        if digest(rec["rows"]) != rec["payload_sha256"] or stamp(rec["collected_at"]) <= stamp(decision["frozen_at"]):
            raise ValueError("observation provenance mismatch")
        for day in rec["rows"]:
            raw = day["raw"]
            if str(raw["insCode"]) != str(rec["ins_code"]) or str(raw["dEven"]) != day["date"].replace("-", ""):
                raise ValueError("observation date mismatch")
            if day["date"] > stamp(rec["collected_at"]).astimezone(TEHRAN).date().isoformat():
                raise ValueError("future source date")
            for field in ("pClosing", "priceYesterday", "qTotTran5J"):
                if not math.isfinite(float(raw[field])) or float(raw[field]) < 0:
                    raise ValueError("invalid price observation")
            if day["date"] > decision["decision_date"]:
                # First-seen wins; later vendor revisions never restate this study.
                panels[cid].setdefault(day["date"], raw)
    return panels


def sessions(panels):
    breadth = {}
    for panel in panels.values():
        for date, row in panel.items():
            if float(row["qTotTran5J"]) > 0 and float(row["pClosing"]) > 0:
                breadth[date] = breadth.get(date, 0) + 1
    return sorted(d for d, n in breadth.items() if n >= 30 and dt.date.fromisoformat(d).weekday() not in (3, 4))


def reference_return(panel, start, end, calendar):
    if start not in panel or end not in panel:
        return None, "missing_exact_session"
    if panel[start]["qTotTran5J"] <= 0 or panel[end]["qTotTran5J"] <= 0:
        return None, "no_trade_reference"
    if float(panel[start]["pClosing"]) <= 0:
        return None, "invalid_close"
    previous = float(panel[start]["pClosing"])
    for date in calendar:
        if not start < date <= end:
            continue
        if date not in panel:
            return None, "missing_intermediate_session"
        row = panel[date]
        # A price reset cannot be treated as loss/profit without action evidence.
        yesterday = float(row["priceYesterday"])
        if abs(yesterday - previous) > max(1.0, previous * 0.005):
            return None, "corporate_action_review"
        previous = float(row["pClosing"])
        if previous <= 0:
            return None, "invalid_close"
    return float(panel[end]["pClosing"]) / float(panel[start]["pClosing"]) - 1, None


def observe(decision, out=OUTPUT):
    frozen_dir = out / "decisions" / decision["decision_date"][:7]
    ranking = read(frozen_dir / "ranking.json")
    if digest(ranking) != decision["ranking_sha256"] or digest(read(frozen_dir / "policy.json")) != decision["policy_sha256"]:
        raise ValueError("frozen input integrity failure")
    panels = collect_evidence(decision, out)
    calendar = sessions(panels)
    summary = {"version": decision["version"], "decision_id": decision["decision_id"], "mode": "reference_only",
               "frozen_at": decision["frozen_at"], "score_as_of": decision["score_as_of"],
               "source_hashes": decision["source_hashes"], "virtual_capital_rial": decision["policy"]["virtual_capital_rial"],
               "cash_weight": decision["cash_weight"], "positions": decision["positions"], "skipped": decision["skipped"],
               "status": "pending_session", "status_label": "منتظر جلسهٔ بعد از ثبت تصمیم",
               "reference_date": None, "valued_at": None, "return_pct": None, "benchmark_return_pct": None,
               "cohort_results": {}, "real_orders": 0, "completed_cycles": 0,
               "note": "آزمایش مشترک مدل با سرمایهٔ فرضی؛ قیمت پایانی مرجع است و اجرای واقعی معامله را اثبات نمی‌کند."}
    reference_file = frozen_dir / "execution_reference.json"
    if calendar and reference_file.exists() and read(reference_file)["date"] != calendar[0]:
        summary.update(status="needs_evidence", status_label="تعارض شواهد تقویم؛ بازده متوقف شد")
        save(frozen_dir / "summary.json", summary)
        return summary
    if calendar:
        start, end = calendar[0], calendar[-1]
        if not reference_file.exists():
            save(reference_file, {"date": start, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()}, exclusive=True)
        summary.update(reference_date=start, valued_at=end, status="observing", status_label="در حال ثبت عملکرد فرضی")
        returns = {cid: reference_return(panel, start, end, calendar) for cid, panel in panels.items()}
        cost = decision["policy"]["one_way_cost_rate"]
        stock_returns = []
        positions = []
        for order in decision["positions"]:
            item = dict(order)
            ret, issue = returns[order["company_id"]]
            item["status"] = "reference_observed" if issue is None else "needs_evidence"
            item["status_label"] = "قیمت مرجع ثبت شد" if issue is None else "منتظر شواهد قیمت / تعدیل"
            item["reference_date"] = start
            item["reference_price_rial"] = panels[order["company_id"]].get(start, {}).get("pClosing")
            item["return_pct"] = None if ret is None else 100 * ((1 + ret) * (1 - cost) / (1 + cost) - 1)
            item["issue"] = issue
            positions.append(item)
            stock_returns.append(None if ret is None else order["weight"] * ((1 + ret) * (1 - cost) / (1 + cost) - 1))
        summary["positions"] = positions
        if all(r is not None for r in stock_returns):
            summary["return_pct"] = 100 * sum(stock_returns)
        else:
            summary.update(status="needs_evidence", status_label="محاسبهٔ بازده منتظر تکمیل شواهد")
        for name, cids in decision["cohorts"].items():
            values = [returns[cid][0] for cid in cids]
            summary["cohort_results"][name] = {"n": len(cids), "n_valid": sum(r is not None for r in values),
                "return_pct": 100 * sum(values) / len(values) if values and all(r is not None for r in values) else None}
        summary["benchmark_return_pct"] = summary["cohort_results"]["equal_weight"]["return_pct"]
        summary["completed_cycles"] = int((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days >= 30 and
                                           summary["return_pct"] is not None and summary["benchmark_return_pct"] is not None)
    summary["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    summary["cost_assumption"] = "۰٫۵٪ هزینهٔ فرضی ورود و ۰٫۵٪ خروج؛ بازده سبد پس از هر دو هزینه است. مرجع مقایسه بدون هزینه است."
    save(frozen_dir / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("refresh", "observe", "tick"))
    parser.add_argument("--fetch", action="store_true", help="collect official future-session evidence")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    if args.command in ("refresh", "tick"):
        export = OUTPUT / "current_ranking.json"
        export.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["go", "run", "./cmd/rankingcheck", "--output", str(export)], cwd=ROOT / "go-app", check=True)
        ranking = read(export)
        if args.command == "refresh":
            decision = freeze(ranking, read(HERE / "policy.json"), now)
            decisions = [decision]
        else:
            if ranking["as_of"] == now.astimezone(TEHRAN).date().isoformat():
                freeze(ranking, read(HERE / "policy.json"), now)
            paths = sorted((OUTPUT / "decisions").glob("*/decision.json"))
            decisions = [read(p) for p in paths if not p.parent.name.startswith(".")]
            if not decisions:
                raise ValueError("no forward decision; refresh the QVT ranking bundle")
    else:
        paths = sorted((OUTPUT / "decisions").glob("*/decision.json"))
        if not paths:
            raise ValueError("freeze a forward decision first")
        decisions = [read(p) for p in paths if not p.parent.name.startswith(".")]
    summaries = []
    for decision in decisions:
        if decision["policy_sha256"] != digest(read(HERE / "policy.json")):
            raise ValueError("policy no longer matches frozen decision")
        if args.fetch and now.astimezone(TEHRAN).date().isoformat() > decision["decision_date"]:
            fetch_prices(decision, now, OUTPUT)
        summaries.append(observe(decision))
    summary = summaries[-1]
    # This mutable view points to immutable decisions and first-seen evidence.
    save(OUTPUT / "latest.json", summary)
    print(json.dumps({k: summary[k] for k in ("decision_id", "status", "cash_weight", "return_pct", "real_orders")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
