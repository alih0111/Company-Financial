"""PHASE P: verify executable tests cover exactly the integrity_test_plan IDs.

Run:
    python canonical_postgres_v1_2_1/tests/test_id_coverage.py
Exit code non-zero if any missing/duplicate IDs.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
RESULTS = BASE / "test_results"

PLAN_ID_RE = re.compile(r"^\|\s*([PCSMAL]\d{2})\s*\|")
TEST_DEF_RE = re.compile(r"def\s+test_([PCSMAL]\d{2})_")


def main() -> int:
    plan = (BASE / "integrity_test_plan.md").read_text(encoding="utf-8")
    plan_ids = [m.group(1) for line in plan.splitlines() if (m := PLAN_ID_RE.match(line))]

    impl_ids = []
    for tf in HERE.glob("test_*.py"):
        if tf.name == "test_id_coverage.py":
            continue
        impl_ids.extend(TEST_DEF_RE.findall(tf.read_text(encoding="utf-8")))

    plan_dup = {k: v for k, v in defaultdict(int, {i: plan_ids.count(i) for i in set(plan_ids)}).items() if v > 1}
    impl_dup = {k: v for k, v in defaultdict(int, {i: impl_ids.count(i) for i in set(impl_ids)}).items() if v > 1}
    missing = sorted(set(plan_ids) - set(impl_ids))
    extra = sorted(set(impl_ids) - set(plan_ids))

    lines = [
        "# Test ID Coverage (PHASE P)",
        "",
        f"- plan logical IDs: {len(plan_ids)} (unique {len(set(plan_ids))})",
        f"- executable IDs: {len(impl_ids)} (unique {len(set(impl_ids))})",
        f"- duplicate plan IDs: {plan_dup}",
        f"- duplicate executable IDs: {impl_dup}",
        f"- missing IDs (in plan, not executable): {missing}",
        f"- extra IDs (executable, not in plan): {extra}",
        "",
        f"RESULT: {'PASS' if not missing and not extra and not plan_dup and not impl_dup else 'FAIL'}",
        "",
    ]
    (RESULTS / "test_id_coverage.txt").write_text("\n".join(lines), encoding="utf-8")
    ok = not missing and not extra and not plan_dup and not impl_dup
    print(f"plan={len(plan_ids)} impl={len(impl_ids)} missing={missing} extra={extra} "
          f"plan_dup={plan_dup} impl_dup={impl_dup} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
