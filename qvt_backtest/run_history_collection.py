"""One resumable archive job, not a recurring scheduler or trading worker."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qvt_backtest/output/financial_history"
OUT.mkdir(parents=True, exist_ok=True)
lock = OUT / "collection.lock"
try:
    with lock.open("x", encoding="utf8") as f:
        f.write(str(__import__("os").getpid()))
except FileExistsError:
    raise SystemExit("Collection already locked; inspect saved PID before restarting")
try:
    subprocess.run([sys.executable, str(ROOT / "qvt_backtest/collect_financial_history.py"),
                    "--fetch", "--max-downloads", "10000", "--delay", "2"], check=True)
    subprocess.run([sys.executable, str(ROOT / "qvt_backtest/build_financial_panel.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "qvt_backtest/export_share_history.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "qvt_backtest/reconstructed_replay.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "qvt_backtest/audit_reconstructed.py")], check=True)
except Exception as exc:
    (OUT / "job_error.json").write_text(json.dumps({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                  "error": str(exc)}), encoding="utf8")
    raise
finally:
    lock.unlink()
