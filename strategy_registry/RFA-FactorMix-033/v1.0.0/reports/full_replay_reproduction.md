# Replay of frozen FactorMix-033 from 1402 to latest available prices

Read-only research; no production, original cache, official adjustment table or
paper ledger writes. The exact selected weights and portfolio policy are reused.

Run from `D:/RFA/Company-Financial` with the existing project Python environment:

```powershell
$env:OPENBLAS_NUM_THREADS='4'
& .venv/Scripts/python.exe ranking_research/experiments/replay_1402_to_now_20261106/run_available.py
& .venv/Scripts/python.exe ranking_research/experiments/replay_1402_to_now_20261106/full_replay.py
& .venv/Scripts/python.exe ranking_research/experiments/replay_1402_to_now_20261106/active_calendar.py
& .venv/Scripts/python.exe -m pytest ranking_research/experiments/replay_1402_to_now_20261106/test_replay.py -q --junitxml=ranking_research/experiments/replay_1402_to_now_20261106/artifacts/tests.junit.xml
& .venv/Scripts/python.exe ranking_research/experiments/replay_1402_to_now_20261106/report.py
```

The February 24 historical prefix must reproduce, both daily NAV and scores.
Later financial inputs are publication-reconstructed only at decision dates
and the required 90-day reference dates; future current-owner factors are never
substituted. New mechanical reference-price resets are kept in this experiment,
rounded to the existing 8-decimal cache convention, with raw response hashes.
They are not an official certification of cash dividends, rights economics or
actual-share portfolio accounting. Two old confirmed factors whose raw reset
cannot be rederived are retained unchanged and explicitly recorded.

The source weights were researched using part of the displayed history, and
historical receipt times remain unproven. The output is a retrospective research
simulation, not live account performance or untouched out-of-sample validation.

The primary result uses the observed-equity-activity calendar: after the frozen
February 24 prefix, days with no tradable opening anywhere in the 254-name
equity universe are not counted as stock sessions. The original generic-calendar
result is retained as a separate control, not relabeled as the same scenario.
