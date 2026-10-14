"""Local research pipeline with OS lock, checkpoints and separate step logs.

No scheduled task, observer enablement, network collection or brokerage access.
"""
import contextlib
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STEPS = ["collect_financial_history.py", "build_financial_panel.py", "audit_financial_coverage.py",
         "extended_financial.py",
         "reconstructed_replay.py", "audit_reconstructed.py", "compare_extended.py",
         "classify_archive_gaps.py", "execute_roadmap.py", "audit_roadmap.py",
         "walkforward_research.py",
         "../qvt_paper/build_strategy_status.py", "write_execution_report.py"]


@contextlib.contextmanager
def pipeline_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        handle.close()
        raise RuntimeError("Another investment pipeline is running") from None
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-archive-scan", action="store_true", help="Use a just-completed local collection checkpoint; no downloads")
    args = parser.parse_args()
    steps = list(STEPS)
    if args.skip_archive_scan:
        history = HERE / "output/financial_history"
        checkpoint = json.loads((history / "progress.json").read_text(encoding="utf8"))
        reports = json.loads((history / "reports.json").read_text(encoding="utf8"))
        if (checkpoint["status"] != "batch_complete" or sum(bool(r["facts"]) for r in reports) != checkpoint["parsed_reports"] or
                sum(len(r["facts"]) for r in reports) != checkpoint["facts"]):
            raise ValueError("Cannot skip incomplete or inconsistent collection")
        steps.remove("collect_financial_history.py")
    out = HERE / "output/pipeline"
    with pipeline_lock(out / "run.lock"):
        run = out / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run.mkdir(parents=True, exist_ok=False)
        state = {"status": "running", "mode": "research_only", "real_orders": 0, "stages": []}
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        for name in steps:
            print("Running " + name, flush=True)
            with (run / (Path(name).stem + ".log")).open("w", encoding="utf8") as log:
                result = subprocess.run([sys.executable, str(HERE / name)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            state["stages"].append({"name": name, "exit_code": result.returncode})
            state["status"] = "failed" if result.returncode else "running"
            (run / "checkpoint.json").write_text(json.dumps(state, indent=2), encoding="utf8")
            if result.returncode:
                raise SystemExit("Pipeline stopped at " + name + "; inspect that stage log. Last published result remains intact unless a preceding stage passed.")
        state["status"] = "completed"
        (run / "checkpoint.json").write_text(json.dumps(state, indent=2), encoding="utf8")
        print(json.dumps({"run": str(run), "status": "completed", "real_orders": 0}), flush=True)


if __name__ == "__main__":
    main()
