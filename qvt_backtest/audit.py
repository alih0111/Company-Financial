"""Check score/selection/accounting artifacts without rerunning or tuning scores."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qvt_backtest/output"
summary = json.loads((OUT / "latest.json").read_text(encoding="utf8"))
run = Path(summary["run_path"])
scores = pd.read_parquet(run / "historical_scores.parquet")
failures = []
if not scores.ui_score.between(0, 20).all(): failures.append("score outside fixed 20 point ceiling")
if scores.duplicated(["as_of", "symbol"]).any(): failures.append("duplicate identity/date")
for name, ascending, field in (("TIMING_TOP10", False, "ui_score"), ("TIMING_BOTTOM10", True, "ui_score"), ("V1_MATCHED_TOP10", False, "baseline_score")):
    expected = scores.sort_values(["as_of", field, "symbol"], ascending=[True, ascending, True]).groupby("as_of", sort=True).head(10)
    actual = pd.read_csv(run / f"{name}_selections.csv")
    if list(zip(expected.as_of, expected.symbol)) != list(zip(actual.as_of, actual.symbol)):
        failures.append(f"{name} selection mismatch")
checked = 0
for path in run.glob("*_nav.csv"):
    frame = pd.read_csv(path)
    checked += len(frame)
    if not np.allclose(frame.value_post_trade, frame.value_pre_trade - frame.transaction_cost, atol=1e-12, rtol=1e-12):
        failures.append(f"{path.name} NAV conservation")
    if (frame.cash_weight < -1e-9).any(): failures.append(f"{path.name} negative cash")
    if not (frame.exec_date > frame.score_date).all(): failures.append(f"{path.name} historical same-day execution")
manifest = {}
for directory in (ROOT / "historical_codal_backfill/output/raw_closing_universe", ROOT / "score_v2_research/_cache"):
    for path in sorted(directory.glob("*")):
        if path.is_file() and (path.suffix == ".gz" or path.name in ("corp_actions_confirmed.parquet", "calendar.parquet", "securities.parquet")):
            manifest[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
(run / "source_archive_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
result = {"status": "passed" if not failures else "failed", "failures": failures,
          "score_rows": len(scores), "nav_rows": checked, "source_files_hashed": len(manifest),
          "full_qvt_certified": False, "note": "Accounting and fixed-selection audit; not historical financial provenance or queue-execution certification"}
(run / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
print(json.dumps(result, ensure_ascii=False))
if failures: sys.exit(1)
