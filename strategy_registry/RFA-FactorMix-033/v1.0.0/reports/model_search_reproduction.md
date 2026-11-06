# Feature and model search for RFA

This is the user's authorized expansion beyond the earlier fixed P1 portfolio
search. It changes features and weights only inside a separate research run.
No production code, public paper ledger, account, source panel or old policy is
modified. Historical data has already been inspected: the verification period
is explicitly reused and cannot be described as an untouched future sample.

The feature bank has 44 factors/derived inputs and 21 missingness indicators.
212 model definitions (reference, source factor deletion/reweighting, group
mixtures and 36 learned models) are crossed with 14 portfolio policies.
Learned models refit in January and July, using only labels whose full forward
return interval has ended by the preceding fit cutoff.

Run in PowerShell from `D:/RFA/Company-Financial` using the existing environment:

```powershell
$env:OMP_NUM_THREADS='4'
$env:OPENBLAS_NUM_THREADS='4'
& .venv/Scripts/python.exe ranking_research/experiments/feature_model_search_20261106/features.py
& .venv/Scripts/python.exe -m pytest ranking_research/experiments/feature_model_search_20261106/test_research.py -q --junitxml=ranking_research/experiments/feature_model_search_20261106/artifacts/tests.junit.xml
& .venv/Scripts/python.exe ranking_research/experiments/feature_model_search_20261106/run.py
& .venv/Scripts/python.exe ranking_research/experiments/feature_model_search_20261106/feature_audit.py
& .venv/Scripts/python.exe ranking_research/experiments/feature_model_search_20261106/report.py
```

The locked protocol fingerprints the feature preparation, model bank, runner
and input matrices. Score caches may be reused only with the same hashes.
Selection uses data through 2024, then freezes the chosen model/policy before
computing reused verification results for January 2025 to February 24, 2026.
Model fitting inside that verification period follows the declared expanding
schedule and still excludes all uncompleted labels.

The final research decision, drawdown limits and inference caveats are recorded
in `REPORT.fa.md` and `artifacts/research_decision.json`. The prior P1 strategy
remains a control; no policy is silently activated.
