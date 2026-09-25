"""Failure-injection through the real canonical hook (no legacy data harmed)."""

from __future__ import annotations

import json
import os
import pathlib
import sys

GO_APP = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
sys.path.insert(0, str(GO_APP / "py"))
sys.path.insert(0, str(GO_APP / "py2" / "src"))
os.chdir(GO_APP)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO_APP / ".env")

OUT = GO_APP.parent / "ingestion_migration_v1" / "output"
GOOD = "company_financial_analytics_shadow_v121"


def counts():
    from canonical_ingest import config
    from canonical_ingest.db import transaction
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM market.price_observations")
        obs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fundamentals.monthly_activities")
        ma = cur.fetchone()[0]
    return {"price_observations": obs, "monthly_activities": ma}


def main():
    import canonical_hook

    result = {}

    # 1) LEGACY_ONLY: zero PostgreSQL writes and no canonical import.
    os.environ["CDF_INGESTION_MODE"] = "legacy_only"
    os.environ["CDF_CANONICAL_DB"] = GOOD
    before = counts()
    r = canonical_hook.dual_write_market_rows([{"company_id": "x", "symbol": "x", "gregorian_date": "2026-09-24",
                                                "closing_price": 1, "volume": 1}])
    after = counts()
    result["legacy_only"] = {"hook": r, "before": before, "after": after, "zero_writes": before == after}

    # 2) DUAL_WRITE + unresolved identity -> quarantine.
    os.environ["CDF_INGESTION_MODE"] = "dual_write"
    canonical_hook._loaded = False
    r = canonical_hook.dual_write_monthly_values("__unknown_id__", "نامعلوم", "1405/06/31", [0, 0, 0])
    result["unresolved_identity"] = r

    # 3) PostgreSQL unavailable / disallowed database -> canonical_error, legacy untouched.
    os.environ["CDF_CANONICAL_DB"] = "definitely_production_db"
    os.environ.pop("CDF_ALLOW_NON_TEST_PG", None)
    canonical_hook._loaded = False
    r = canonical_hook.dual_write_monthly_values("b88121029d7e973410b008320f8fe378", "قاسم", "1405/06/31", [0, 0, 1])
    result["postgres_unavailable"] = r

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase2_failure_injection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
