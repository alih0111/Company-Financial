# SESSION HANDOFF — Company-Financial (CURRENT)

> No credentials/passwords/tokens are stored in this file. Credentials are read
> from `.env` at runtime only.
>
> This replaces the obsolete handoff that reported `ANALYTICS_PARITY_FAIL` as the
> current state. The v3.7 parity work is historical; canonical analytics v1 is now
> the current model and the v3.7 view is a frozen compatibility oracle.

---

## 1. Project goal

Iranian listed-company fundamental/quant system:
- ingest Codal + market data, normalize to a **canonical PostgreSQL** schema,
- compute versioned quantitative scores, PIT-safe and reproducible,
- serve them to a React client through the Go API,
- then (later phases) Signal Engine → Portfolio → Risk → Paper Trading.

Target pipeline:
```
Codal / Market Data -> Ingestion -> Canonical PostgreSQL
  -> Fundamental / Market / Analytics engines -> Signal -> Portfolio -> Risk
  -> Execution -> Broker Adapter -> Portfolio Accounting -> React UI
```
SQL Server is retained as **compatibility / mirror / fallback / rollback**, not
the destination.

---

## 2. Canonical database

- Schema: **`canonical_postgres_v1_2_1`** — `TEST_DATABASE_PASS` (74/74 tests).
- Namespaces: `core`, `ingestion`, `raw`, `fundamentals`, `market`, `analytics`,
  `auth`, `portfolio`.
- Principles: Company != Security; UUID identity; `tsetmc_ins_code` on Security;
  aliases not identity; explicit legacy mapping; monetary IRR `numeric`; EPS =
  `rial_per_share`; report/report_version/parse_run separated; raw→normalized→
  analytics; append-only/revision-aware market data; PIT-safe versioned analytics.
- Forbidden in canonical: `Product1`, `Product2`, `Product3`, `NPUnitRatio`,
  `OpK`, `OpAmt`.
- Shadow DB: `company_financial_analytics_shadow_v121`.

---

## 3. Canonical ingestion — READY

Gate: **`CANONICAL_INGESTION_LAYER_READY`** and
**`CANONICAL_INGESTION_COMBINED_SOAK_PASS`** (2026-09-25).

- Four domains canonical-primary: `MARKET_PRICE`, `MONTHLY_ACTIVITY`,
  `FINANCIAL_STATEMENT`, `CODAL`.
- Approved writer: `go-app/py2/src/canonical_ingest/` (only canonical writer).
  The older `codal_ingestor` SQLAlchemy/Alembic schema is NON-CANONICAL and
  guarded.
- Real scripts wired via `go-app/py/canonical_hook.py`; reversible per-domain
  authority flags (`CDF_*_INGESTION_AUTHORITY=canonical|legacy`).
- Combined soak: 3 cycles, 0 unexplained mismatch, 0 partial parse runs, retry
  backlog 0, `score_runs` unchanged, no cross-domain interference.
- SQL Server **must not be deleted** yet.

Combined soak report: `ingestion_migration_v1/COMBINED_SOAK_REPORT.md`.

---

## 4. Analytics — canonical v1

- Gate: **`CANONICAL_V1_METRICS_READY`**.
- Engine: `canonical_postgres_v1_2_1/analytics_canonical_v1/compute_metrics.py`
  (`score_version = canonical-v1-dev`, report-chain TTM, PIT-safe, no legacy
  heuristics).
- Current completed run: **`489a6df0-2d37-44de-a0c5-ef0d5daa7191`**,
  `as_of_date = 2026-09-25`, 267 company scores, 5607 factor scores.
- Prior run preserved: `c6cb1579-2c28-4526-b3eb-f71d781ca4a4`.
- **v3.7 frozen oracle** (compatibility only, not future architecture):
  `849a4efd49711101eb5e29c719d8c233efa0d7e6c928d47b21882540cbbac264`.
- Do NOT modify canonical-v1 in place; future experimental models use
  `canonical-v2-exp-*`.

### Analytics refresh contract — READY

- Gate: **`ANALYTICS_REFRESH_READY`**.
- Contract: `integration_shadow_v1/ANALYTICS_REFRESH_CONTRACT.md`.
- Orchestrator: `canonical_postgres_v1_2_1/analytics_canonical_v1/orchestrate_refresh.py`.
- Modes: `CHECK_ONLY` (default), `RUN_IF_STALE` (routine), `FORCE_RUN`.
- Append-only; deterministic staleness rule; `RUN_IF_STALE` blocked on degraded
  ingestion; idempotent (second run = `NOT_STALE`).
- E2E proof: stale detected → `RUN_IF_STALE` → new completed run →
  Go selects it → `score_stale=false`.

---

## 5. Backtesting / model validation

Frozen gates: `BACKTEST_FRAMEWORK_READY`, `BACKTEST_MEASUREMENT_HARDENED`,
`FACTOR_MODEL_VALIDATION_READY`, OOS protocol frozen. No production weight
optimization yet. Model-v2 experimentation is the next model phase (not started).

---

## 6. Go canonical read integration — COMPLETE (no cutover)

Gate: **`GO_CANONICAL_READS_COMPLETE`**.
Key-endpoint canary: **`KEY_READ_ENDPOINTS_CANARY_READY`**.

Read modes: `LEGACY` (default) / `SHADOW` / `CANONICAL` (not enabled broadly).
SHADOW serves legacy and compares canonical; **0 unexplained mismatches** across
all endpoints.

| Endpoint | SHADOW status | Canary-ready |
| --- | --- | --- |
| `/api/price-history` | 0 unexpected | yes (5% identity-guarded rollout) |
| `/api/SalesData2` | 0 unexpected, presentation defined | yes |
| `/api/SalesData` | 0 unexpected, income-statement presentation undefined | no |
| `/api/summary` | 0 unexpected (expected semantic change vs v3.7) | yes (product decision) |
| `/api/AllCompanyScores` | 0 unexpected | yes |
| `/api/CompanyScores` | 0 unexpected | yes |
| `/api/CompanyNames` | 0 unexpected (identity presentation) | no |
| `/api/StockPriceScore` | out of scope (technical) | no |
| `/api/detail` | adaptable later (route broken) | no |
| `/api/analyze` | LEGACY_AI_ONLY | no |

- `Product1/2/3` = **CLIENT_UNUSED**, deprecated compatibility-only.
- `percentage`/`wow` contract:
  `integration_shadow_v1/FUNDAMENTALS_PRESENTATION_CONTRACT.md`.
- Company/Security contract:
  `integration_shadow_v1/COMPANY_IDENTITY_API_CONTRACT.md`.
- Score endpoints call canonical analytics; Go does not recompute the model.
- Stale detection via `integration.PG.Metadata` → `GET /api/health/shadow`,
  `go-app/cmd/readstatus`.

Key artifacts:
`integration_shadow_v1/{ENDPOINT_MIGRATION_MATRIX,REMAINING_READ_ENDPOINT_AUDIT,FUNDAMENTALS_READ_MIGRATION,ANALYTICS_READ_MIGRATION,SYMBOL_PAGE_CANONICAL_REPORT,SQLSERVER_REMAINING_DEPENDENCIES}.md`,
`integration_shadow_v1/integration_manifest.json`,
`integration_shadow_v1/output/go_read_completion_summary.json`.

---

## 7. Remaining SQL Server dependencies

Full inventory: `integration_shadow_v1/SQLSERVER_REMAINING_DEPENDENCIES.md`.

- READS still served by SQL Server for the seven SHADOW endpoints (canary
  gated, not data gaps).
- No canonical path: `StockPriceScore` (technical), `detail` (broken route),
  `analyze` (LLM).
- WRITES not migrated: AUTH (`Users`), PORTFOLIO (`Users.Portfolio`), FAMILY
  (`Family*`).
- MIRRORS: `canonical_hook`; FALLBACKS: per-domain authority config.
- DEPRECATED compatibility: `CodalReports`, `CodalSyncState`, `vw_AIStockMetrics`
  (frozen oracle), `FullPE`, `TrackedTickers`.

---

## 8. Tests / environment

- Go: `go build ./...`, `go vet ./...`, `go test ./...` → pass
  (`go-app/integration`; `cmd/{shadowcheck,symbolvalidate,readstatus}`).
- Python: `go-app/py/tests` 57 passed; `analytics_canonical_v1/tests` 25 passed;
  `analytics_v37_oracle` 3 passed.
- Python venv: `D:\RFA\Company-Financial\.venv\Scripts\python.exe`
  (has `psycopg[binary]`, `pyodbc`, `python-dotenv`, `jdatetime`, `pytest`).
- Canonical DB env: `CDF_PILOT_DB` / `CDF_CANONICAL_DB` =
  `company_financial_analytics_shadow_v121`; DSN from `go-app/.env`
  (`DATABASE_URL`). Server `localhost:5432`.
- SQL Server: `go-app/.env` (`DB_SERVER/DB_NAME/DB_USER/DB_PASSWORD`),
  read-only for analysis; mirror writes only via ingestion.

Run examples:
```powershell
# analytics tests
$env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
& .venv\Scripts\python.exe -m pytest canonical_postgres_v1_2_1\analytics_canonical_v1\tests -q
# refresh status / run-if-stale
& .venv\Scripts\python.exe canonical_postgres_v1_2_1\analytics_canonical_v1\orchestrate_refresh.py --mode CHECK_ONLY
# Go read SHADOW comparison
$env:CDF_READ_MODE="shadow"; $env:CDF_CANONICAL_DB="company_financial_analytics_shadow_v121"
go run ./cmd/shadowcheck   # from go-app/
```

---

## 9. Final bounded read canary — PASS

Gate: **`FINAL_CANONICAL_READ_CANARY_PASS`** (`integration_shadow_v1/FINAL_READ_CANARY_REPORT.md`).

- Harness `go-app/cmd/finalcanary` drives the real handlers via httptest with the
  identity guard and automatic legacy fallback. Endpoints: `SalesData2`,
  `AllCompanyScores`, `CompanyScores`, `price-history`.
- 0 unexplained mismatches, 0 HTTP errors, 0 writes. Coverage: canonical serving
  only via the fund/price canary allowlist (default read mode still LEGACY).
- Identity guard: collisions (`جم پیلن`, `های وب`) and legacy-only names forced to
  legacy.
- Failure injection: PG unavailable → legacy fallback (HTTP 200); missing score
  run → no stale score served as current.
- Score metadata: `canonical-v1-dev`, `score_as_of=2026-09-25`, `score_stale=false`.
- Artifacts: `output/final_read_canary.csv`, `output/final_read_canary_summary.json`,
  `output/canary_inject_pg/`, `output/canary_inject_run/`.

## 10. Model v2 experimentation — WEAK

Directory `model_v2_validation/`; frozen OOS protocol (dev 2021–2023, val 2024,
holdout 2025, forward 2026). canonical-v1 remains the application default.

- Candidates: `canonical-v2-exp-a` (Robust Core), `-b` (Coverage-Aware),
  `-c` (Category-Balanced). Selected `-a`, config hash
  `4997a85e4d6f33e72dc2c1d27286002d736f21073c377337aaac009306255364`.
- Selection used development + validation only; holdout evaluated once per frozen
  candidate (no leakage).
- Key finding: v2 candidates cut the coverage bias enormously
  (corr(score, n_factors) 0.576 → 0.055 dev; 0.575 → 0.115 holdout).
- Holdout 2025: IC comparable (exp-a 0.161 vs baseline 0.166) but baseline has
  higher return (0.747 vs 0.636); exp-a turnover higher.
- Gates: **`MODEL_V2_VALIDATION_WEAK`**,
  **`MODEL_V2_NOT_READY_FOR_SIGNAL_ENGINE_EVALUATION`**.
- Artifacts: `MODEL_V2_PROTOCOL.md`, `MODEL_V2_EXPERIMENTS.md`,
  `MODEL_V2_RESULTS.md`, `MODEL_V2_HOLDOUT_REPORT.md`,
  `MODEL_V2_RECOMMENDATION.md`, `MODEL_REGISTRY.json`, `output/model_v2_*.{csv,json}`.

## 12. SQL Server shutdown readiness — BLOCKED

Executable audit (`sqlserver_retirement/`). Gate:
**`SQLSERVER_STOP_BLOCKED`**.

- Go server **starts** without SQL Server (lazy pool, no init connect), but
  active read handlers call `config.GetDB()` before canonical, so SQL Server
  offline → HTTP 500 on CompanyNames, SalesData, SalesData2, CompanyScores,
  AllCompanyScores, summary, price-history, StockPriceScore, export, portfolio,
  family, login.
- Ingestion offline: MARKET/MONTHLY/CODAL canonical continue (`DEGRADED_LEGACY_MIRROR`);
  FINANCIAL canonical fails (`_facts_from_db`); the real scripts cannot reach the
  hook at all.
- Stage: ingestion STAGE_1; application reads/auth/portfolio STAGE_0.
- Artifacts: `SQLSERVER_DEPENDENCY_AUDIT.md`, `SQLSERVER_OFFLINE_TEST_REPORT.md`,
  `SQLSERVER_RETIREMENT_PLAN.md`, `output/sqlserver_{dependencies,offline_failures}.csv`,
  `output/sqlserver_shutdown_summary.json`, `output/ingestion_offline_probe.json`.
- Smallest first fix: reorder canaried handlers to canonical-first.

## 11. Current next task

Single next action: **bounded coverage-controlled revalidation of
`canonical-v2-exp-a`** (coverage-matched cross-sections; no holdout tuning), then
a new versioned turnover-reduction experiment. Only after consistent dev+val
evidence, consider Signal Engine evaluation.

Do NOT start Signal Engine implementation yet.
Do NOT replace canonical-v1 as the application default.
Do NOT migrate auth/portfolio writes. Do NOT remove SQL Server.

## 13. SQL Server shutdown readiness — UPDATED (supersedes section 12)

Gate: **`SQLSERVER_STOP_BLOCKED`** (narrowed). Stage: overall **STAGE_2**
(application core **STAGE_3-ready**; ingestion entrypoints **STAGE_1**).

Executable offline proof (SQL Server unreachable, `cmd/offlinetest`): server
starts; 0 `SQLSERVER_REQUIRED_FAIL` for core endpoints.
- Canonical-first (HTTP 200 offline): CompanyNames, SalesData, SalesData2,
  CompanyScores, AllCompanyScores, summary, price-history.
- Auth: `CDF_AUTH_BACKEND=postgres` (auth.users), 4 users migrated, offline
  login 200.
- Portfolio: `CDF_PORTFOLIO_BACKEND=postgres` (portfolio namespace), migrated,
  offline 200.
- Family: explicit deferral `CDF_FAMILY_BACKEND=disabled` → 503 `deferred=true`.
- Financial ingestion: `ingest_financial_authoritative_by_key(..., facts=...)`
  is SQL-free (offline canonical success); the legacy `facts=None` read is
  rollback only.
- Health: `sqlserver_status=RETIRED_EXPECTED`, `sqlserver_required=false`,
  `overall=HEALTHY` with `CDF_SQLSERVER_MODE=offline_expected`.

Remaining blocker (single): the four real Python ingestion scripts still open
SQL Server at startup (hook is decoupled). Also admin-optional: GetUrl/GetUrl2,
ingestion triggers, viewed-items.

Required configuration before manually stopping SQL Server:
```
CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
CDF_AUTH_BACKEND=postgres
CDF_PORTFOLIO_BACKEND=postgres
CDF_FAMILY_BACKEND=disabled
CDF_SQLSERVER_MODE=offline_expected
CDF_FUND_CANARY_ENABLED=true   (+ CDF_FUND_CANARY_COMPANIES)
CDF_PRICE_HISTORY_CANARY_ENABLED=true (+ CDF_PRICE_HISTORY_CANARY_SYMBOLS)
```
Rollback: set `CDF_AUTH_BACKEND=sqlserver`, `CDF_PORTFOLIO_BACKEND=sqlserver`,
`CDF_FAMILY_BACKEND=sqlserver`, `CDF_SQLSERVER_MODE=active`, and disable the
canary flags. SQL Server is retained (not deleted).

Artifacts: `sqlserver_retirement/` (see `output/sqlserver_retirement_summary.json`).

## 14. SQL Server retirement — STAGE_3 REACHED

Gate: **`SQLSERVER_CAN_BE_STOPPED`**. Stage: **STAGE_3** (PostgreSQL standalone;
SQL Server optional rollback/archive/mirror, not deleted).

- All four real ingestion entrypoints run with SQL Server unreachable
  (`brs_prices.cmd_daily`, `MianSql2.save_report_to_sql`,
  `MianSql.save_profit_loss_to_sql`, `sync_codal.run_sync`) via canonical-only
  branches and canonical identity resolution (`canonical_hook.resolve_legacy_key`).
- Financial canonical path uses normalized in-memory `facts_from_values(...)`;
  `_facts_from_db` is rollback-only.
- Go-trigger `POST /api/brs/collect` → `py/brs_prices.py daily` returns HTTP 200
  with SQL Server unreachable.
- Full offline retest: 0 `SQLSERVER_REQUIRED_FAIL`; auth/portfolio/analytics/react
  reads all operational; family explicit 503 deferred.
- Mirror failure ≠ canonical retry (proven).
- Static scan: 0 CRITICAL_SHUTDOWN_BLOCKER, 0 ACTIVE_FEATURE_BLOCKER.

Shutdown config and rollback config: see
`sqlserver_retirement/output/sqlserver_retirement_final.json`.
Artifacts: `sqlserver_retirement/FINAL_INGESTION_DECOUPLING.md`,
`SQLSERVER_OFFLINE_TEST_REPORT.md`, `SQLSERVER_DEPENDENCY_AUDIT.md`,
`SQLSERVER_RETIREMENT_PLAN.md`.

## 15. CORRECTION — real website SQL path (SQL Server actually stopped)

The earlier `SQLSERVER_CAN_BE_STOPPED` was harness-verified but the **live
process had no CDF_* retirement environment**, so active requests still hit
`localhost:1433`. Root cause: `go-app/.env` lacked the retirement config and the
process was stale.

Fixed and verified against the real backend (`go run main.go` on :5000, reverse
proxied as `rfa_back.systemgroup.net`), SQL Server kept STOPPED:
- retirement config persisted in `go-app/.env`;
- `offline_expected` now forces canonical routing and removes all legacy fallback
  (code-level invariant + residual SQL handlers gated);
- auth/portfolio default to postgres and family to disabled under
  `offline_expected`;
- backend restarted (SQL Server NOT restarted).

Result: all active endpoints 200 (family 503 deferred), PG login 200, unsafe
identities explicit 503 (no SQL), **0 network attempts to :1433** during a burst.
Gate: **`REAL_WEBSITE_SQLSERVER_OFFLINE_PASS`**.
Report: `sqlserver_retirement/REAL_WEBSITE_OFFLINE_REPORT.md`;
proof: `sqlserver_retirement/output/real_website_offline_proof.{csv,json}`.

## 16. Symbol-page UI/API contract fixes (live, SQL Server stopped)

Gate: **`SYMBOL_PAGE_UI_FIXED`**.

Real browser verification (Playwright, frontend :3000, SQL Server stopped):
کسرا/چکاپا/دزهراوی/کیمیا/شکیمیا all `/api/*` → 200, zero 5xx, zero SQL attempts.

Fixes:
- **Upper profit/EPS chart** was collapsed to one bar because canonical
  `net_profit` exists only for the latest report; now derives `percentage` from
  canonical **EPS** (complete history) and returns **oldest→newest**
  (`integration.EpsPercentage`, `OrderFinancialAscending`).
- **Lower sales chart** now returns **oldest→newest**
  (`integration.OrderMonthlyAscending`).
- **Score detail fills**: `/api/summary` now serves `analytics.factor_scores`
  percentiles as `*_rank` (progress bars) via `handlers/summary_canonical.go`.
- **Null semantics**: unmaterialized base metrics emit JSON `null` (UI `--`),
  not misleading `0`.
- **Offline timeouts**: 15 s canonical timeout in `offline_expected`; empty
  canonical data → `200 []` (not 503).
- CompanyScores donuts use canonical factor percentile×100.

Docs: `integration_shadow_v1/SYMBOL_PAGE_UI_CONTRACT.md`,
`SYMBOL_PAGE_BUGFIX_REPORT.md`; outputs
`symbol_page_endpoint_map.csv`, `symbol_page_field_comparison.csv`,
`symbol_page_bugfix_validation.csv`.

Remaining limitation: canonical-v1 does not persist factor `raw_value`, so base
metric text shows `--` (ranks/fills/category scores are correct).

## 17. Quarterly-profit semantics (کاسپین regression)

Gate: **`QUARTERLY_PROFIT_DATA_PARTIAL`**.

- The upper chart historically plotted the cumulative net-profit proxy
  `EPS × Capital` (== legacy `Product1`), not standalone quarterly profit nor raw
  EPS. The prior raw-EPS substitution was removed.
- True historical `net_profit` is **SOURCE_ABSENT** (`dbo.miandore2.NetProfitAmount`
  NULL historically; 162 companies have EPS but no net_profit) — not a migration
  defect. No fabrication/repair performed.
- The chart now shows **standalone quarterly profit** via
  `integration.DeriveQuarterlyProfit`: `Q1=cumQ1`, `Qn=cumQn−cumQ(n−1)` **within
  the same fiscal year only**, resetting at the fiscal boundary; negatives
  supported; oldest→newest.
- API `SalesData` exposes `periodEndDate/fiscalYear/quarter/cumulativeNetProfit/
  quarterlyNetProfit`; `percentage = quarterlyNetProfit/1e6` (single documented
  meaning).
- کاسپین FY1404 quarters increase 3,862.6 → 5,260.46 → 5,558.0 → 7,130.12
  (profitability improvement reflected); FY1405 Q1 = 12,465.8 (no cross-year
  subtraction).
- Docs: `integration_shadow_v1/QUARTERLY_PROFIT_CONTRACT.md`,
  `KASPIN_FINANCIAL_RECONCILIATION.md`, `FINANCIAL_HISTORY_DATA_AUDIT.md`,
  `QUARTERLY_PROFIT_BUGFIX_REPORT.md`; outputs
  `kaspin_financial_periods.csv`, `net_profit_coverage_audit.csv`,
  `quarterly_profit_validation.csv`, `financial_history_repair_summary.json`.
- Limitation: true net_profit history source-absent; fiscal year inferred from
  Jalali year. Top KPI base values remain `--` (unmaterialized) by design.

## 18. Cumulative-profit chart semantics (corrected)

Gate: **`CUMULATIVE_PROFIT_DATA_INCOMPLETE`**.

- The upper chart now plots **reported cumulative (YTD) net profit** per period
  (`fundamentals.financial_facts.net_profit`, `period_order=1`), `FY: 3M→6M→9M→12M`
  then next FY resets. **No standalone-quarter subtraction, no EPS substitution.**
- New read `PG.NetProfitSeriesByLegacyCompanyID` /
  `Shadow.FetchCumulativeProfitCanonical`; API exposes `fiscalYear`, `periodOrder`
  (3/6/9/12), `periodEndDate`, `cumulativeNetProfitRial/Million`; compatibility
  `percentage = cumulativeNetProfitMillion`.
- `DeriveQuarterlyProfit` retained as a separate utility, not used by the chart.
- **Data reality:** source `miandore2.NetProfitAmount` non-null for only 378/6864
  rows; 162 companies have zero; کاسپین has 1/27 (only 1405/03/31). Historical
  cumulative net profit is **source-absent**; no repair possible (fabrication
  forbidden). Reaching CORRECT requires re-ingesting historical net profit from
  Codal reports.
- Docs: `integration_shadow_v1/CUMULATIVE_PROFIT_CHART_CONTRACT.md`,
  `CUMULATIVE_PROFIT_BUGFIX_REPORT.md`; updated `KASPIN_FINANCIAL_RECONCILIATION.md`;
  outputs `kaspin_cumulative_profit.csv`, `cumulative_profit_validation.csv`,
  `net_profit_coverage_audit.csv`.

## 19. Historical Codal net-profit backfill (source verified; execution pending)

Gates: **`HISTORICAL_CODAL_SOURCE_READY`**, **`HISTORICAL_NET_PROFIT_BACKFILL_PARTIAL`**,
**`CUMULATIVE_PROFIT_DATA_INCOMPLETE`**.

- Historical Codal income statements are **recoverable**: `LetterType=6` by
  `Symbol` returns کاسپین's 75 financial letters with real TracingNo/URL; the page
  renders via Playwright (`CHROMIUM_BINARY`) and the proven parser
  `codal_ingestor.parsers.profit_loss` extracts net_profit matching `miandore2`
  exactly. Unit resolved from the page note → `million_rial`.
- Runner implemented: `historical_codal_backfill/backfill_net_profit.py`
  (discover → render → parse → canonical lineage report/version/raw/parse_run →
  statement/fact; idempotent, checkpoint, failure classes; SQL Server not used).
- کاسپین before/after = **1/23** income-statement net_profit periods; full pilot
  not completed in-session (headless-browser runtime). All documents/artifacts:
  `historical_codal_backfill/`.
- Recommended next action: run the runner (`--symbol "کاسپین" --pages 4
  --max-reports 40`) in an environment with a working Playwright browser, then run
  the post-backfill PIT tests (see `PIT_SAFETY_REPORT.md`).

## 20. کاسپین historical net-profit backfill — PASS

Gates: **`KASPIN_HISTORICAL_NET_PROFIT_PASS`**,
**`CUMULATIVE_PROFIT_CHART_CORRECT_FOR_KASPIN`**.

- Recovered **38** کاسپین cumulative `net_profit` periods from Codal (was 1/23);
  75 letters discovered, 38 unique economic periods, 0 unrecoverable.
- Unit exact: `million_rial → IRR (×1e6)` for all 38 (e.g. 12,467,922 →
  12,467,922,000,000).
- Full lineage: codal report/version/raw/parse_run → statement → fact;
  `published_at` preserved, `collected_at=now`.
- Idempotent: second run inserted 0 facts, 0 failures.
- Live API `GET /api/SalesData?companyName=کاسپین` → 38 ordered cumulative points,
  no EPS, FY reset correct; browser confirms.
- PIT: analytics 25 + backtesting 27 + Go tests pass (no leakage).
- Runner: `historical_codal_backfill/backfill_net_profit.py`.
- Limitation: duration from period month (append-only statements can't store
  `duration_months`); non-Esfand fiscal years pending.
- Next: decide on full-universe backfill (not run here).

## 21. Period-semantics hardening + full-universe prerequisites

Gates: **`HISTORICAL_PERIOD_SEMANTICS_READY`**,
**`HISTORICAL_HETEROGENEOUS_PILOT_FAIL`** (operational, not correctness),
**`HISTORICAL_NET_PROFIT_FULL_BACKFILL_PARTIAL`**,
**`CUMULATIVE_PROFIT_UNIVERSE_INCOMPLETE`**.

- Duration is now parsed from the Codal report **title** (۳/۶/۹ ماهه, سال مالی),
  never the calendar month; `periodOrderFromMonth` no longer used for the chart.
  Unit-tested incl. non-Esfand (`TestFiscalYearDurationFromTitle`). Canonical
  location = `ingestion.reports.title` (statements are append-only).
- Current-report selection = `DISTINCT ON (period_end_date) ORDER BY published_at
  DESC`; all versions/raw preserved.
- Runner hardened: normalized-parse content hash (storage-idempotent), reuse of
  stored raw payloads (no refetch), resource-limit args, isolated non-persistent
  browser with retries/cleanup.
- Non-Esfand candidates found: حکشتی(3), وخارزم(3), سبزوا(6), سکرد(6), دعبید(9),
  داسوه(9), شپاکسا(9).
- کاسپین pilot still PASS (38/38). Non-Esfand multi-symbol run did not complete
  in-session (browser runtime) → full universe deferred.
- PIT suites still pass (analytics 25, backtesting 27, Go).
- Artifacts: `historical_codal_backfill/{PERIOD_SEMANTICS_HARDENING.md,
  CORRECTED_REPORT_SELECTION.md, HETEROGENEOUS_PILOT_REPORT.md,
  FULL_UNIVERSE_BACKFILL_REPORT.md, PIT_SAFETY_REPORT.md}` and outputs
  `universe_preflight.csv`, `non_esfand_validation.csv`,
  `corrected_report_validation.csv`, `full_backfill_runs.csv`,
  `full_backfill_failures.csv`, `coverage_before_after.csv`,
  `full_backfill_summary.json`.

## 22. CAPTCHA-aware backfill acquisition redesign

Gate: **`CAPTCHA_AWARE_BACKFILL_READY`**.

- New runner `historical_codal_backfill/captcha_aware_backfill.py`: cache-first
  (reuse `raw.report_payloads`, never refetch), discovery/fetch separated with a
  durable JSONL queue, pre-render title filtering, economic-period dedup,
  one-at-a-time bounded fetching (concurrency 1; ≤5/session, ≤30/hour; pauses),
  CAPTCHA detection + pause (no bypass/evasion), `--interactive-captcha`/`--headful`
  human resume, `--parse-cached-only` (zero network), `BACKFILL_PAUSED_CAPTCHA`.
- Data semantics unchanged (cumulative net_profit, real Codal source,
  million_rial→IRR, title duration, no EPS, PIT-safe, idempotent).
- Pilot: کاسپین discovery 75 → local reparse reused 62 raws (zero browser),
  live fetch 1 report (0 CAPTCHA), queue checkpoint/resume works. Non-bypass
  asserted by test.
- Artifacts: `historical_codal_backfill/{CAPTCHA_AWARE_RUNBOOK.md,
  OPERATIONAL_RUNBOOK.md}`; `output/{backfill_queue.csv,backfill_queue.jsonl,
  captcha_events.csv,acquisition_metrics.json,coverage_progress.csv}`.
- Next: iterate bounded batches (priority_symbols.txt, coverage-ordered) with
  operator CAPTCHA resume; re-run PIT after batches.

## 23. Global historical net-profit recovery (execution)

Gates: **`UNIVERSE_CACHED_BACKFILL_PASS`** · **`UNIVERSE_BACKFILL_IN_PROGRESS`**.

- Universe: 273 companies (264 with income statements); net_profit periods
  410 → 414.
- **Cached-only universe pass (zero network)** executed: 217 raws found, 186
  parsed, 0 new facts (cache only covers already-backfilled companies),
  unit_unresolved 31. No Codal access.
- **Bounded live fetch** executed for فولاد/خودرو/شپنا: 6 reports, 2 sessions,
  1 browser recycle, **0 CAPTCHA**; results فولاد 4/27, خودرو 2/28, شپنا 2/27
  (+4 net_profit periods).
- Queue: WRITTEN 70, DISCOVERED 113, FETCH_PENDING 11, FAILED_RETRYABLE 1,
  CAPTCHA_REQUIRED 0.
- Still live-needed: **162 zero-net_profit companies** (discovery not yet run for
  them).
- Progress artifacts: `historical_codal_backfill/output/{universe_queue.csv,
  coverage_before_after.csv, universe_cached_pass.json, backfill_queue.csv,
  captcha_events.csv, acquisition_metrics.json, coverage_progress.csv}`;
  report `GLOBAL_HISTORICAL_RECOVERY_PROGRESS.md`.
- Resume: `python historical_codal_backfill/captcha_aware_backfill.py --fetch
  --from-file priority_symbols.txt --max-reports-per-session 3
  --max-reports-per-hour 6` (add `--interactive-captcha --headful` if challenged).

## 24. Universe recovery — real batches executed

Gate: **`UNIVERSE_BACKFILL_IN_PROGRESS`** (no CAPTCHA encountered; work remains).

- Priority list from canonical coverage: 162 zero-history symbols
  (`output/priority_zero_net_profit_symbols.txt`).
- Discovery across 162: +500 letters (queue 832); some `discover:HTTPError`
  (Codal throttling) recorded resumable.
- 3 live batches, **30 reports**, 0 CAPTCHA, 3 browser recycles, hour cap 10.
- Coverage: zero 162→**159**, partial 92→**95**, net_profit periods 410→**438**
  (+28); efficiency ≈0.93 periods/report; 3 companies zero→partial.
- Queue: WRITTEN 100, DISCOVERED 583, FETCH_PENDING 11, FAILED_RETRYABLE 138.
- Validated 5 symbols via API (cumulative, ASC, title durations, negatives, no EPS).
- PIT analytics 25 + CAPTCHA tests 5 pass. C: ~3.8 GB free.
- Resume: `captcha_aware_backfill.py --discover ...` then `--fetch
  --max-reports-per-session 5 --max-reports-per-hour 10`; `--interactive-captcha
  --headful --resume` on challenge.
- Artifacts: `GLOBAL_HISTORICAL_RECOVERY_PROGRESS.md`,
  `output/{priority_zero_net_profit_symbols.txt,priority_universe.csv,
  universe_queue.csv,coverage_before_after.csv,acquisition_metrics.json,
  coverage_progress.csv,backfill_queue.csv,captcha_events.csv}`.

## 25. Sustainable recovery + priority website batches

Gate unchanged: **`UNIVERSE_BACKFILL_IN_PROGRESS`**.

- Disk: C: 3.75 → **5.08 GB free** (removed unused bundled Playwright browser +
  temp); guard **2.0 GB** (`output/resource_guard.json`).
- New executor `historical_codal_backfill/sustainable_run.py`: 1398 discovery
  cutoff (dynamic pages), exponential backoff + `next_retry_at`, per-symbol
  discovery cache (0 search calls when complete), company-completion fetch,
  cache-first, one-at-a-time, CAPTCHA-aware, disk guard.
- Priority website symbols (`output/priority_website_symbols.txt`): فولاد، خودرو،
  شپنا، آریا، بپیوند، بزاگرس، شبندر، فملی، بترانس، وغدیر.
- This task: 27 live reports, **+21 net_profit periods** (438→459), 0 CAPTCHA.
  Universe: zero 162→**159**, partial 92→**95**.
- Discovery cache: 10 symbols, all cutoff_reached; retry queue
  `output/discovery_retry_queue.csv`.
- PIT analytics 25 + CAPTCHA tests 5 pass.
- Resume: `sustainable_run.py --from-file ... --max-per-company 12` (raise the
  per-company cap to actually finish companies); interactive CAPTCHA via
  `captcha_aware_backfill.py --fetch --interactive-captcha --headful --resume`.

## 26. Priority company-completion batch (executed)

Gate unchanged: **`UNIVERSE_BACKFILL_IN_PROGRESS`**.

- Ran `sustainable_run.py` on priority website symbols with `--max-per-company 12`
  (~33 min). Result: net_profit periods **459 → 540 (+81)**; **2 priority
  companies COMPLETE for 1398→present** (آریا, بزاگرس) from 0.
- Priority per-symbol (1398+ expected vs recovered): فولاد 9/10, خودرو 4/5,
  شپنا 7/8, آریا 13/13, بپیوند 15/16, بزاگرس 13/13, شبندر 14/29, فملی 13/29,
  بترانس 14/29; وغدیر `IDENTITY_UNRESOLVED`.
- Universe: zero 159, partial 95, complete 10 (priority symbols were already
  partial). Queue: WRITTEN 202, DISCOVERED 777, FETCH_PENDING 11,
  FAILED_RETRYABLE 139, FAILED_PERMANENT 7. CAPTCHA 0. Disk ~5.09 GB.
- PIT analytics 25 passed; discovery cache used (0 search calls).
- Artifacts: `output/priority_1398_completion.csv`, `website_symbol_validation.csv`,
  `acquisition_metrics.json`, `coverage_progress.csv`.
- Resume: `sustainable_run.py --from-file output/priority_website_symbols.txt
  --max-pages 8 --max-per-company 12` (then `priority_zero_net_profit_symbols.txt`).

## 27. Targeted completion + 1398+ official metric

Gate unchanged: **`UNIVERSE_BACKFILL_IN_PROGRESS`**.

- Standardized the official metric to the **1398→present** window:
  `complete_1398_plus` / `partial_1398_plus` / `zero_1398_plus`
  (`output/coverage_1398_plus.csv`, `coverage_1398_plus_summary.json`).
  Counter reconciliation: the old "universe complete 10" was **all-history**
  (np>=income across all periods); priority "COMPLETE 0→2" was the **1398+**
  window. The gate now uses 1398+.
- Targeted fetches: **بپیوند** 1401/12 was WRITTEN → **COMPLETE_1398_PLUS**.
  فولاد/خودرو/شپنا' 1398/3M reports render **without a P/L table** →
  terminal `UNSUPPORTED_REPORT_FORMAT` (not a network failure).
- **وغدیر = `VAGHADIR_IDENTITY_BLOCKED`**: no canonical security/company named
  وغدیر; the alias `شغدیر` is a **distinct** entity. Not fabricated.
- Official 1398+ coverage (over 170 discovered symbols): **complete 3**
  (آریا، بزاگرس، بپیوند), partial 6, zero 0, identity_unresolved 1,
  no_financial_reports 9, discovery_pending 160; expected 152 / recovered 103 →
  **67.8%**.
- API verified for آریا (23, from 1398/12/29), بزاگرس (17), بپیوند (26, from
  1398/03/31) — ASC, title durations, no EPS. PIT analytics 25 passed.
- Disk ~5.09 GB; CAPTCHA 0.
- Resume: `sustainable_run.py --from-file output/priority_website_symbols.txt
  --max-pages 8 --max-per-company 20`, then zero-history list.

## 28. Completeness denominator bug fixed (fiscal-timeline audit)

Gates: **`FOOLAD_DISCOVERY_CONTINUITY_PASS`**,
**`FOOLAD_NET_PROFIT_1398_PLUS_COMPLETE`**,
**`PRIORITY_1398_TIMELINE_AUDIT_PASS`**. Universe still
`UNIVERSE_BACKFILL_IN_PROGRESS`.

- **Root cause of the فولاد 1400→1404 gap:** those letters were present in the
  queue but with `report_year=None` (enqueued by an earlier discovery path), so
  the denominator (built from `report_year`) omitted them, hiding the gap and
  never selecting them as fetch candidates.
- Fix: `enrich_queue.py` backfilled `report_year`/`duration` for **695** queue
  records; `audit_timeline.py` now builds a **fiscal-timeline denominator
  (1398→present)** with continuity fields (`missing_fiscal_years`,
  `discovery_continuity_complete`) instead of `recovered/discovered`.
- فولاد: recovered all missing periods (15 reports) → **28/28 complete
  1398→present**; API continuous 1398/06/31→1405/03/31, FY resets, no gap.
- Re-audit with the fixed denominator downgraded previous provisional
  "complete" symbols: only **فولاد** is `complete_1398_plus`; آریا (3 pending,
  3 unknown), بپیوند (3 pending), بزاگرس (9 pending, 3 unknown), خودرو/شپنا/
  شبندر/فملی/بترانس still pending. `gaps=[]` (continuity restored for all).
- وغدیر = `VAGHADIR_IDENTITY_BLOCKED` (no canonical entity).
- Artifacts: `output/fiscal_period_coverage_1398_plus.csv`,
  `output/fiscal_year_gap_audit.csv`, `output/priority_timeline_audit.json`,
  `foolad_fiscal_matrix.csv`; `universe_queue.csv` now carries continuity fields.
- Method: product readiness metric is **timeline_audited_coverage_1398_plus**,
  not discovered-set coverage.
- Resume: continue fetching pending priority periods (company-completion), then
  zero-history universe; re-run `audit_timeline.py` after batches.

## 29. Priority recovery on corrected fiscal timeline

Gate: **`PRIORITY_TIMELINE_RECOVERY_IN_PROGRESS`** (not yet complete);
universe `UNIVERSE_BACKFILL_IN_PROGRESS`.

- Authoritative unit = symbol + fiscal_year + duration_months (1398→present),
  separate counts: recovered / terminal_source_limited / pending_fetch /
  discovery_unknown (`output/priority_symbol_counts.csv`,
  `fiscal_period_coverage_1398_plus.csv`).
- Two ordered batches (fewest-pending first) this task: **+~30 reports**,
  net_profit periods 540 → ~600+, 0 CAPTCHA, disk ~5.12 GB.
- Priority results:
  - **DATA_COMPLETE_1398_PLUS**: بپیوند (29/29).
  - **COMPLETE_WITH_SOURCE_LIMITATIONS**: فولاد (28/29, 1 `UNIT_UNRESOLVED`),
    خودرو (28/29), شبندر (28/29), بترانس (28/29).
  - **PARTIAL_FETCH_PENDING**: شپنا (24/29), فملی (27/29).
  - **PARTIAL_DISCOVERY_UNKNOWN**: آریا (26/29, 3 unknown), بزاگرس (26/29, 3 unknown).
  - **IDENTITY_BLOCKED**: وغدیر.
- فولاد is NOT "28/28 recovered": it is 28 recovered + 1 terminal source-limited.
- PIT analytics 25 passed. Terminals are not counted as recovered.
- Resume: regenerate `output/priority_fetch_order.txt` via `audit_timeline.py`,
  then `sustainable_run.py --from-file output/priority_fetch_order.txt
  --max-per-company 25`; run discovery retry for آریا/بزاگرس/وغدیر unknown
  periods when backoff allows.

## 30. PRIORITY TIMELINE RECOVERY COMPLETE

Gate: **`PRIORITY_TIMELINE_RECOVERY_COMPLETE`**; universe remains
`UNIVERSE_BACKFILL_IN_PROGRESS`.

Final priority table (1398→present, required all 29):
- DATA_COMPLETE_1398_PLUS: **بپیوند** (29/29).
- COMPLETE_WITH_SOURCE_LIMITATIONS (28 recovered + 1 terminal): فولاد، خودرو،
  شپنا، آریا، بزاگرس، شبندر، فملی، بترانس.
- IDENTITY_BLOCKED: وغدیر (`VAGHADIR_IDENTITY_BLOCKED_CONFIRMED`).

Key closeouts: شپنا/فملی pending were transient `Page.goto` timeouts/crashes —
retried and WRITTEN. آریا/بزاگرس 1398/3M genuinely absent from Codal (only
6/9/12 exist) → terminal `SOURCE_NOT_FOUND_CONFIRMED`. وغدیر has no canonical
security/company (شغدیر is distinct) — not mapped.

Verification: API for شپنا/فملی/آریا/بزاگرس = 28 rows each, ASC, continuous
1398/06/31→1405/03/31. PIT analytics 25 passed. Disk ~5.11 GB. CAPTCHA 0.

Artifacts: `output/priority_symbol_counts.csv`, `priority_timeline_audit.json`,
`fiscal_period_coverage_1398_plus.csv`, `fiscal_year_gap_audit.csv`.

Next: begin the timeline-audited universe (enrich globally, audit timeline, then
fetch exact holes). Do not refetch terminal priority symbols.

NEXT_SESSION_READY = YES

## 31. GLOBAL timeline-audited 1398+ recovery (executed)

Gate unchanged: **`UNIVERSE_BACKFILL_IN_PROGRESS`**; priority still
`PRIORITY_TIMELINE_RECOVERY_COMPLETE`. SQL Server OFFLINE; no CAPTCHA bypass.

- `enrich_queue.py` run globally (all queue rows). `audit_timeline.py` extended to
  audit **ALL 273 canonical companies** (atomic unit
  `symbol + fiscal_year + duration_months`), still writing the priority subset
  artifacts unchanged.
- Global audit: required **7,917** / recovered **563** / terminal **88** /
  pending **539** / unknown **6,727** periods → coverage **7.1 %**.
  Status: `PARTIAL_DISCOVERY_UNKNOWN` 228, `PARTIAL_FETCH_PENDING` 20,
  `COMPLETE_WITH_SOURCE_LIMITATIONS` 14, `NO_FINANCIAL_REPORTS` 9,
  `DATA_COMPLETE_1398_PLUS` 2, `IDENTITY_BLOCKED` 1. 47 companies discovered,
  227 not yet discovered.
- Executed exact-hole, company-completion batches (no CAPTCHA): batch2 66 reports
  / 4 companies complete / +124 periods; batches 1 & 3 time-budgeted and
  checkpointed per report; discovery wave 1 (40 companies) = 15 discovered,
  25 Codal search throttles recorded `RETRY` with backoff (no evasion).
- Session movement: recovered **281 → 563 (+282)**, coverage **3.5 % → 7.1 %**,
  `DATA_COMPLETE_1398_PLUS` 1→2, `COMPLETE_WITH_SOURCE_LIMITATIONS` 8→14,
  queue 1,143 → 2,141. Disk 5.06 GB free (guard 2.0 GB). 0 CAPTCHA.
- Verification: canonical unit exact (million_rial ×1e6 → IRR, negatives OK,
  cumulative `period_order=1`, raw+title+`published_at` retained);
  PIT analytics **25 passed**, CAPTCHA/no-bypass **5 passed**.
- Artifacts: `historical_codal_backfill/GLOBAL_TIMELINE_RECOVERY_REPORT.md`,
  `output/{universe_symbol_counts.csv,fiscal_period_coverage_1398_plus.csv,
  fiscal_year_gap_audit.csv,universe_timeline_audit.json,
  universe_timeline_summary.json,universe_fetch_order.txt,
  discovery_retry_order.txt,discovery_cache.jsonl}`.
- Resume: `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-pages 10 --max-per-company 25`, then discovery retry via
  `output/discovery_retry_order.txt --discover-only`.
- Do NOT start Model v2 / Signal Engine; do not fetch pre-1398.

## 32. FULL-UNIVERSE DISCOVERY ADVANCE (executed)

New gate: **`UNIVERSE_DISCOVERY_ADVANCED`** (kept: `UNIVERSE_TIMELINE_AUDIT_READY`,
`UNIVERSE_BACKFILL_IN_PROGRESS`). Discovery was the bottleneck; 6 bounded discovery
waves + exact-hole fetches executed. SQL Server OFFLINE, no CAPTCHA bypass.

- New runner `historical_codal_backfill/discovery_wave.py`: bounded, resumable,
  metadata-only; dynamic pagination until 1398 cutoff OR source exhausted (no fixed
  page count as proof); persists `last_page, oldest_discovered_report_year,
  cutoff_reached, source_exhausted, metadata_enriched,
  discovery_continuity_complete`; exponential backoff + `next_retry_at` +
  `attempt_count` + Retry-After; skips discovery-complete symbols.
- `audit_timeline.py` now consumes discovery completeness: for a discovery-complete
  symbol, a fiscal year/duration with no source letter is terminal
  `SOURCE_NOT_FOUND_CONFIRMED` (UNKNOWN → TERMINAL), not `DISCOVERY_UNKNOWN`.
- `sustainable_run.py` gained `--skip-discovery` (hole-fetch with zero search calls).
- Waves: 87 companies attempted, **67 discovered**, 66 reached 1398 cutoff, 1 source
  exhausted, **17 throttled** (esp. wave 2 — paused per policy, then resumed),
  186 search calls, **+3,106 letters**, 0 CAPTCHA, 3 non-HTTP errors.
- BEFORE → AFTER: discovered companies 47→**117**; undiscovered 227→**157**;
  DISCOVERY_UNKNOWN 6,727→**4,699 (−2,028)**; discovered-pending 539→2,183;
  recovered 563→**768**; terminal 88→267; CWSL 14→**23**; PARTIAL_DISCOVERY_UNKNOWN
  228→**159**; PARTIAL_FETCH_PENDING 20→80; coverage 7.1 %→**9.7 %**.
  Canonical net_profit facts 760→1,152; queue WRITTEN 491→819.
- Each wave: `enrich_queue.py` → `audit_timeline.py` → exact-hole fetch
  (`--skip-discovery`, cache-first, company-by-company). Raws reused where present.
- Disk 5.06 GB free (guard 2.0 GB). PIT: analytics **25 passed**, CAPTCHA/no-bypass
  **5 passed** (`published_at` source / `collected_at` fetch).
- Artifacts: `historical_codal_backfill/GLOBAL_DISCOVERY_ADVANCE_REPORT.md`,
  `output/{discovery_waves.csv,discovery_wave_last.json,discovery_cache.jsonl,
  universe_symbol_counts.csv,universe_timeline_summary.json,fiscal_period_coverage_1398_plus.csv,
  fiscal_year_gap_audit.csv,universe_fetch_order.txt,discovery_retry_order.txt}`.
- Resume: `discovery_wave.py --limit 15 --max-pages 8 --wave 7`, then enrich+audit,
  then `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-per-company 25 --skip-discovery`.
- Remaining: 157 undiscovered companies + 2,183 discovered-pending periods.
  Do NOT start Model v2 / Signal Engine; do NOT fetch pre-1398.

## 33. Discovery ↔ exact-hole fetch cycle 2 (executed)

Gates kept: **`UNIVERSE_TIMELINE_AUDIT_READY`**, **`UNIVERSE_DISCOVERY_ADVANCED`**,
**`UNIVERSE_BACKFILL_IN_PROGRESS`**.

- Alternating cycles: discovery waves 7–10 → enrich → audit → exact-hole fetch
  (`sustainable_run.py --skip-discovery`) → audit. This task: **4 waves, 60
  companies attempted, 60 discovery-complete**, 0 throttled, 0 HTTP errors,
  157 search calls, **+2,758 letters**.
- BEFORE→AFTER: discovered 117→**176**; undiscovered 157→**98**;
  DISCOVERY_UNKNOWN 4,699→**2,959 (−1,740)**; discovered-pending 2,183→3,626;
  RECOVERED 768→**896 (+128)**; terminal 267→436; CWSL 23→**27**;
  PARTIAL_DISCOVERY_UNKNOWN 159→**99**; coverage 9.7 %→**11.3 %**.
  Queue WRITTEN 819→948; canonical net_profit facts 1,152→1,267.
  Pending created +1,443 / consumed +128 → net +1,315.
- **Net_profit reconciliation** (`reconcile_net_profit.py` →
  `output/net_profit_reconciliation.json`): total facts 1,267; one income
  statement per (company, period_end) and one net_profit fact per statement;
  unique 1398+ economic periods 905; pre-1398 rows 10; legacy_sqlserver-origin
  unresolved-title rows 352 (outside the 1398+ denominator);
  **duplicate-current violations = 0** → `NET_PROFIT_RECONCILIATION_CLEAN`.
  The apparent 21 “multi-row” periods were cr LEFT-JOIN fan-out over corrected
  Codal reports at the same period_end_date (identical value), not duplicate facts.
- **API duplicate safety**: authenticated `GET /api/SalesData` for 16 companies →
  **0 duplicate (fiscalYear, periodOrder)** keys (بپیوند 29/29, کاسپین 38/38, …).
- CAPTCHA 0. Disk 4.86 GB free (guard 2.0). PIT analytics **25 passed**,
  CAPTCHA/no-bypass **5 passed**.
- Artifacts: `historical_codal_backfill/GLOBAL_DISCOVERY_CYCLE2_REPORT.md`,
  `historical_codal_backfill/reconcile_net_profit.py`,
  `output/{net_profit_reconciliation.json,discovery_waves.csv,
  universe_symbol_counts.csv,universe_timeline_summary.json,
  fiscal_period_coverage_1398_plus.csv,fiscal_year_gap_audit.csv,
  universe_fetch_order.txt,discovery_retry_order.txt}`.
- Resume: `discovery_wave.py --limit 15 --max-pages 8 --wave 11`, then enrich +
  audit, then `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-per-company 25 --skip-discovery`.
- Remaining: 98 undiscovered companies + 3,626 discovered-pending periods.
  Do NOT start Model v2 / Signal Engine; do NOT fetch pre-1398.

## 34. Universe reconciliation + fetch-heavy cycle (executed)

Gates: new **`CANONICAL_UNIVERSE_COUNT_RECONCILED`**; kept
`UNIVERSE_TIMELINE_AUDIT_READY`, `UNIVERSE_DISCOVERY_ADVANCED`,
`UNIVERSE_BACKFILL_IN_PROGRESS`, `NET_PROFIT_RECONCILIATION_CLEAN`.

- **Universe reconciled: 273 canonical companies** (the reported 274 was 273 + the
  queue-only unresolved symbol `وغدیر`, which has no canonical identity; it is now
  reported separately in `output/unlinked_queue_symbols.csv`). Core checks clean:
  273 companies / 273 primary securities, 0 multi-primary, 0 duplicate codalsymbol,
  0 null identity, 0 alias duplication, 0 join fan-out. No identity fabricated.
  Frozen roster: `output/canonical_universe_roster.csv` (273 rows) — all counts now
  use it. `audit_timeline.py` reports `canonical_companies` + `unlinked_queue_symbols`.
- Discovery waves 11–14: attempted 60, **discovered 36**, throttled 24 (wave 14 full
  block → discovery paused, fetch continued), search calls 99, +1,673 letters.
  `undiscovered 98 → 61`; DISCOVERY_UNKNOWN 2,959 → **1,902**.
- Heavier fetch: 4 `--skip-discovery` batches (0 search calls), RECOVERED
  896 → **1,218 (+322)**; WRITTEN 948 → 1,275; pending created +1,000 / consumed
  +322 → net +678. DATA_COMPLETE 2→3, CWSL 27→40 (+14 terminal companies).
- Recon (`reconcile_net_profit.py`): facts 1,588; unique 1398+ periods 1,232;
  **duplicate-current violations 0**; **legacy_sqlserver unresolved-title rows 346,
  current-display collisions 0** → `NET_PROFIT_RECONCILIATION_CLEAN`.
- API `GET /api/SalesData` (authenticated) 17 companies: 0 duplicate
  `(fiscalYear, periodOrder)`, chronological, cumulative, no EPS fallback.
- CAPTCHA 0; disk 4.78 GB (guard 2.0); PIT analytics **25**, CAPTCHA/no-bypass **5**.
- Artifacts: `historical_codal_backfill/GLOBAL_FETCH_HEAVY_REPORT.md`,
  `output/{canonical_universe_roster.csv,canonical_universe_reconciliation.json,
  unlinked_queue_symbols.csv,net_profit_reconciliation.json,universe_symbol_counts.csv,
  universe_timeline_summary.json,discovery_waves.csv,universe_fetch_order.txt,
  discovery_retry_order.txt}`.
- Resume: `discovery_wave.py --limit 15 --max-pages 8 --wave 15`, then enrich+audit,
  then `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-per-company 25 --skip-discovery`.
- Remaining: 61 undiscovered companies + 4,304 discovered-pending periods.
  Do NOT start Model v2 / Signal Engine; do NOT fetch pre-1398; no final gate yet.
