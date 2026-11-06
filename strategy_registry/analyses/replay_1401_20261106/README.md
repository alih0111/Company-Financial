# Frozen FactorMix-033: 1401 start

Fresh 100,000,000 toman; first available session 2022-03-26 (1401-01-06),
last input session 2026-11-04 (1405-08-13). The archived v1.0.0 engine, weights,
policy, input matrices and observed-equity calendar are used without retuning.
Existing 1402 replay, registry version, UI and forward journal are not changed.

From the project root:

```powershell
& .venv/Scripts/python.exe strategy_registry/analyses/replay_1401_20261106/run.py
& .venv/Scripts/python.exe -m pytest strategy_registry/analyses/replay_1401_20261106/test_replay.py -q --junitxml=strategy_registry/analyses/replay_1401_20261106/artifacts/tests.junit.xml
& .venv/Scripts/python.exe strategy_registry/analyses/replay_1401_20261106/report.py
```

The protocol is recorded before simulation and refuses different inputs/settings
on a rerun. Both candidate and P1 BASE start at the same time with fresh cash.
P1 uses its original portfolio rule; this comparison changes scoring and policy,
not just the scoring rule. Files are local research artifacts, not live results.

Prior prices/fundamentals are used only as indicator history. Temporal source
reconstruction limitations, historical model selection and fixed-universe
survivorship risk still apply. See REPORT.fa.md and the archived strategy report.
