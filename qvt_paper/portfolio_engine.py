"""Shared target policy. Pure functions; no broker, prices, or account mutation."""
from __future__ import annotations
import math


def complete(row):
    return (row.get("full_coverage") is True and all(
        row.get(axis, {}).get("scored_factors") and all(
            f.get("kind") in ("policy_excluded", "not_implemented")
            for f in row[axis].get("missing_factors", [])) for axis in ("q", "v", "t")))


def choose(rows, policy):
    count, weight, industry_cap = policy["max_positions"], policy["position_weight"], policy["max_industry_weight"]
    if (not isinstance(count, int) or count <= 0 or not math.isfinite(weight) or not math.isfinite(industry_cap)
            or weight <= 0 or industry_cap < weight or count * weight > 1 + 1e-9 or industry_cap > 1):
        raise ValueError("invalid portfolio caps")
    selected, skipped, industries, identities = [], [], {}, set()
    ordered = sorted(rows, key=lambda r: (r["rank"], r["company_id"]))
    for row in ordered:
        cid = row["company_id"]
        if cid in identities:
            raise ValueError("duplicate portfolio identity")
        identities.add(cid)
        if row["status"] != "buy_review":
            continue
        reason = None
        if row.get("critical") or row.get("conditional") or row.get("negative_operating_profit"):
            reason = "قید کیفیت یا ریسک جدی"
        elif row.get("risk_gate_status") == "blocked":
            reason = "مانع در کنترل ریسک"
        elif not complete(row):
            reason = "اطلاعات بعضی عوامل کامل نیست"
        elif not row.get("industry"):
            reason = "صنعت معتبر برای کنترل تمرکز مشخص نیست"
        elif not isinstance(row.get("score"), (int, float)) or not math.isfinite(row["score"]):
            reason = "امتیاز معتبر نیست"
        elif len(selected) >= count:
            reason = "ظرفیت سبد تکمیل است"
        elif industries.get(row["industry"], 0) + weight > industry_cap + 1e-9:
            reason = "سقف تمرکز صنعت"
        if reason:
            skipped.append({"company_id": cid, "symbol": row["symbol"], "reason": reason})
            continue
        industries[row["industry"]] = industries.get(row["industry"], 0) + weight
        selected.append({"company_id": cid, "symbol": row["symbol"], "industry": row["industry"],
                         "rank": row["rank"], "score": row["score"], "weight": weight,
                         "reason": "شرایط مدل و کامل بودن عوامل برای آزمایش فراهم است",
                         "risk": row.get("main_risk"), "risk_gate_status": row.get("risk_gate_status"),
                         "status": "pending_reference", "status_label": "منتظر قیمت جلسهٔ بعد"})
    return selected, skipped
