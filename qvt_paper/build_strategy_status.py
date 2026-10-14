"""Read-only current target preview plus explicit research readiness gates."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from portfolio_engine import choose

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def main():
    path = HERE / "output/current_ranking.json"
    ranking = json.loads(path.read_text(encoding="utf8"))
    policy_path = HERE / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf8"))
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Tehran")).date().isoformat()
    cutoff = dt.datetime.fromisoformat(ranking["cutoff"].replace("Z", "+00:00"))
    fresh = ranking["as_of"] == today and cutoff.tzinfo is not None and cutoff <= now
    positions, skipped = choose(ranking["ranked"], policy) if fresh else ([], [])
    research = json.loads((ROOT / "qvt_backtest/output/roadmap_latest.json").read_text(encoding="utf8"))
    if research.get("independent_audit", {}).get("status") != "passed":
        raise ValueError("research output not independently checked")
    plan = {"version": "qvt-strategy-preview-v1", "mode": "simulation", "real_orders": 0,
            "as_of": ranking["as_of"], "cutoff": ranking["cutoff"], "generated_at": now.isoformat(),
            "snapshot_fresh": fresh, "source_hashes": {a: ranking["sources"][a]["sha256"] for a in ("q", "v", "t")},
            "source_ranking_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "positions": positions, "cash_weight": 1 - sum(p["weight"] for p in positions), "skipped": skipped,
            "status_label": "برنامهٔ فرضی بر اساس دادهٔ امروز آماده است" if fresh else "برای برنامهٔ امروز داده باید به‌روز شود",
            "research_run": research["run_path"], "promotion_ready": False,
            "broker": {"name": "Agah", "connection_requested": False, "official_api_available": False},
            "note": "این خروجی برنامهٔ آزمایشی انتخاب سهم است؛ به دارایی‌های واقعی کاربر یا کارگزاری متصل نیست و دستور خرید نیست."}
    out = HERE / "output/strategy_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")
    tmp.replace(out)
    print(json.dumps({"fresh": fresh, "positions": len(positions), "cash_weight": plan["cash_weight"], "real_orders": 0}))


if __name__ == "__main__":
    main()
