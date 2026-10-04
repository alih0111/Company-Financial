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

## 35. Fetch-backlog drawdown + transient-zombie requeue (executed)

Gates kept: `UNIVERSE_TIMELINE_AUDIT_READY`, `UNIVERSE_DISCOVERY_ADVANCED`,
`UNIVERSE_BACKFILL_IN_PROGRESS`, `NET_PROFIT_RECONCILIATION_CLEAN`.
SQL Server OFFLINE; discovery/search calls ZERO (all batches `--skip-discovery`);
CAPTCHA 0 (no bypass/evasion; `captcha_events.csv` empty).

- **State audit first** (no blind trust in stale counts): a prior `sustainable_run`
  had been hard-killed mid-flight (status file stuck `RUNNING`, last checkpoint
  کپارس/1259201); no python processes running. BEFORE (re-audited from queue+PG):
  required 7,917 / recovered 2,603 / terminal 477 / pending 2,935 / unknown 1,902
  → coverage **32.9 %**; PFP 137, CWSL 61, PDU 63, NFR 9, DC 3; discovered 212 /
  undiscovered 61; queue 9,778 rows (DISCOVERED 6,827, WRITTEN 2,674,
  FAILED_RETRYABLE 267, FETCH_PENDING 10); dup-current 0; CAPTCHA 0; disk C: 6.2 GB.
- **Zombie-row fix (new)** `historical_codal_backfill/requeue_transient.py`: rows in
  `FAILED_RETRYABLE` with transient browser/runtime reasons (`Page.goto` timeout,
  `Page.content` while navigating, `Page crashed`) or the pre-v2
  `operating_profit` parser requirement were never picked by `best_candidate`
  (only `SOURCE_TEMPORARY_ERROR` is retry-eligible) — 74 permanent zombies.
  Requeued 91 rows across 26 symbols to `DISCOVERED` (prev_reason retained,
  `requeue_count` cap 3, no CAPTCHA rows touched, zero network). Same mechanism
  as the شپنا/فملی transient-timeout precedent (§30).
- **4 fetch-only batches** (company-completion order from `audit_timeline.py`,
  pause 15 s/30 s, recycle 12, durable checkpoint per report):
  batch1 10 symbols 125 processed (104 WRITTEN, 4 STE, 17 goto-FAILED);
  batch2 14 symbols 152 processed (144 WRITTEN, 8 STE, **7 companies complete**);
  batch3 12 symbols 278 processed (263 WRITTEN, 15 STE);
  batch4 12 symbols **stopped at yield degradation** (recent-60 ratio 0.49 <
  0.75 rule; Codal error shells/timeouts ~03:30 local): 162 processed
  (130 WRITTEN, 10 STE, 22 FAILED).
  Session totals: **717 processed / 641 WRITTEN / 37 SOURCE_TEMPORARY_ERROR /
  39 transient FAILED** (requeueable), ≈873 facts, unique-live-report yield
  0.86/0.95/0.95/0.80.
- **AFTER**: recovered **3,239** (+636), pending **2,299** (−636), unknown 1,902
  (unchanged — fetch-only), terminal 477 → coverage **40.9 %** (+8.0 pts).
  DC 3→**4** (دانا 29/29), CWSL 61→**69** (+8: ساوه، وسپه، سرچشمه، برکت،
  وخارزم، غگیلا، غپاک، اروند — several gained `SOURCE_NOT_FOUND_CONFIRMED`
  terminals for genuinely absent periods, e.g. اروند term=14), PFP 137→128.
- **Reconciliation** (`reconcile_net_profit.py`): net_profit fact rows 2,911→**3,523**;
  unique current 1398+ periods 2,626→**3,267**; **duplicate-current violations = 0**;
  legacy_sqlserver unresolved-title rows 275→246, current-display collisions 0 →
  `NET_PROFIT_RECONCILIATION_CLEAN`.
- **API** `GET /api/SalesData` (authenticated) 16 companies (9 session-completed +
  regression بپیوند/کاسپین/فولاد/خودرو/فملی/شبندر/بزاگرس): 16/16 HTTP 200,
  chronological ASC, title durations 3/6/9/12, no duplicate periods, no EPS
  fallback, no fiscal-year gaps; source↔canonical conversion 4,195 checked /
  0 mismatches. وسپه flag = documented legacy non-Esfand row (no title, value 0,
  `legacy_sqlserver` origin) — deferred, untouched.
- PIT: analytics **25 passed**, CAPTCHA/no-bypass **20 passed**. Disk C: 5.7 GB,
  D: 8.2 GB (guard 2.0 GB never tripped). Queue final: DISCOVERED 6,202,
  WRITTEN 3,315, FAILED_RETRYABLE 251 (86 `SOURCE_TEMPORARY_ERROR`),
  FETCH_PENDING 10, DEFERRED 0. Discovered 212 / undiscovered 61 (unchanged).
- Artifacts: `output/{fetch_zbatch1..4.txt, zbatch1..4.log, api_validation_after.csv,
  batch1_before_stamp.txt}`; new script `requeue_transient.py`.
- Resume (next session): when Codal responsive → `requeue_transient.py` (39 new
  transient rows), `enrich_queue.py` + `audit_timeline.py`, then
  `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-per-company 25 --skip-discovery`. Discovery waves for the 61 undiscovered
  companies remain secondary. Do NOT start Model v2 / Signal Engine; do NOT
  enable SQL Server; do NOT fetch pre-1398.

## 36. Investment chat assistant (new page + API)

- Backend: `go-app/handlers/chat_handler.go`, route `POST /api/chat` (protected,
  registered in `main.go`). Answers are rule-based and grounded **only** in the
  canonical score data already served by `/api/summary`
  (`integration.Default().FetchSummaryCanonical` → `analytics.company_scores` +
  `analytics.factor_scores`). No SQL Server, no invented numbers.
- Intents (Persian keyword match; text normalized for ZWNJ/punctuation/ي-ک):
  greeting/help, top picks («بهترین/پیشنهاد/بخرم/خرید/سبد»), weakest list,
  single-company analysis («تحلیل فولاد»), two-company comparison
  («مقایسه فولاد و فملی»), market overview as fallback. Company matching is by
  symbol token or company-name containment (longest match wins).
- Verdicts are **relative** (percentile rank inside the scored universe), not
  absolute score thresholds, because the live run's distribution is compressed
  (268 companies, mean 35.9, median 34.0, max 66.4, only 12 at/above 60). Every
  reply ends with an explicit "not buy/sell advice" line.
- Optional LLM upgrade: when `AI_CHAT_URL` + `AI_API_KEY` (+ optional `AI_MODEL`)
  are set, the same rule-engine context is posted to the chat-completions endpoint
  and its answer replaces the rule reply; any error/timeout falls back silently to
  the rule engine. Currently unset → rule engine only.
- Frontend: `client/src/components/ChatPage.tsx` (lazy route `/chat`, sidebar entry
  «دستیار سرمایه‌گذاری»), `sendChatMessage()` appended to
  `client/src/utils/api.ts`. RTL bubbles (user left / assistant right, per RTL chat
  convention), quick-prompt chips, typing indicator, Persian-digit formatting.
- Verified: `go build ./...` + `go vet ./handlers/` clean; client `tsc -b` and
  `npm run build` clean (ChatPage 4.8 kB chunk); endpoint smoke-tested for all six
  intents against 268 companies; UI exercised in-browser against a local-API dev
  server (quick-prompt ranking and per-company analysis rendered correct data).
  `go run .` on :5000 restarted; output continues in `go-app/go-app-live.log`.
- Gotcha: non-ASCII request bodies passed through Git Bash/curl get mangled by the
  Windows shell (every intent then falls through to the market overview). Test
  `/api/chat` with a UTF-8 client (browser or Node), never a curl argument string.


## 37. Fetch drawdown to <1500 + discovery cadence resumed; stopped on disk guard

Gate kept: `UNIVERSE_BACKFILL_IN_PROGRESS`; `NET_PROFIT_RECONCILIATION_CLEAN`
re-verified. SQL Server OFFLINE. Fetch phase ZERO Codal search calls; no CAPTCHA
(0 events, no bypass — on challenge the batch pauses and the documented headful
human-resume flow is used).

- **State refresh first** (`requeue_transient.py` 22 rows فخاس/تاصیکو;
  `enrich_queue.py` 0; `audit_timeline.py`; `reconcile_net_profit.py`):
  recovered 3,239 / terminal 477 / pending 2,299 / unknown 1,902 → coverage
  40.9 %; DC 4, CWSL 69, PFP 128, PDU 63, NFR 9; discovered 212 / undiscovered 61;
  disk C: 5.7 GB. No drift from §35.
- **New regression guard** `historical_codal_backfill/check_zombie_holes.py`:
  every actionable pending timeline unit must have ≥1 fetchable queue candidate
  (DISCOVERED/FETCH_PENDING/CAPTCHA_REQUIRED); RETRYABLE-only units are the
  documented deferred debt, not zombies. Result: 2,252/2,252 candidates →
  **ZOMBIE_ACTIONABLE_HOLES = 0** (re-run at end: 1,350/1,350 → 0).
- **5 fetch-only batches** (`--skip-discovery`, company-completion order,
  checkpoint per report): 1,246 reports processed / **1,186 WRITTEN** /
  45 `SOURCE_TEMPORARY_ERROR` / 14 transient `FAILED` / 1 `PARSE_FAILED`
  (→FAILED_PERMANENT, new debt class); rolling yield 0.86–0.99, session 0.95.
  Batch sizes: 236, 279, 258, 298, 175. Disk guard stopped the phase at
  C: 2.13 GB (Temp cleaned → 2.6 GB; PostgreSQL/raws/lineage untouched).
- **Discovery resumed at pending≈1,500** (spec §13/§14): `discovery_wave.py
  --wave 15 --limit 15` → 15 attempted, **10 discovered** (all reached 1398
  cutoff), 5 throttled (recorded with `next_retry_at`), 32 search calls,
  **+510 letters**, 0 HTTP errors, 0 CAPTCHA. Then enrich → audit → 2 fetch
  batches (batch 8 on the newly discovered companies, batch 9 next tranche).
- **BEFORE → AFTER (this session)**: recovered 3,239 → **4,421 (+1,182)**;
  pending 2,299 → **1,427 (−872 net)**; discovery_unknown 1,902 → **1,587
  (−315)**; actionable pending+unknown 4,201 → **3,014 (−1,187)**;
  terminal 477 → **482**; coverage 40.9 % → **55.8 % (+14.9 pts)**.
  Companies: DC 4→**9**, CWSL 69→**75** (کلر، فاراک، شستا، حتوکا، حکشتی،
  حپارسا + …), PFP 128→127, PDU **63→53**, NFR 9. Discovered 212→**222**,
  undiscovered 61→**51**.
- **Reconciliation**: net_profit facts 3,523 → **4,676**; unique current 1398+
  periods **4,453**; **duplicate-current violations = 0**; legacy collisions 0.
- **API** `GET /api/SalesData` (authenticated) 17 companies (session DC/CWSL +
  regression set): 17/17 HTTP 200, chronological, 3/6/9/12 title durations,
  cumulative, no duplicate periods, no EPS fallback, no year gaps; DB conversion
  5,348 values / 0 mismatches.
- **PIT**: analytics **25**, backtesting **27**, CAPTCHA/unit **20** — all passed;
  `published_at`=source / `collected_at`=acquisition unchanged.
- Final queue: WRITTEN 4,501, DISCOVERED 5,528, FAILED_RETRYABLE 288,
  FETCH_PENDING 10, FAILED_PERMANENT 1 (10,328 rows). CAPTCHA 0.
  Disk C: 2.6 GB / D: 8.2 GB (guard 2.0 GB → **fetch phase stopped here**).
- Artifacts: `output/{fetch_zbatch5..9.txt, zbatch5..9.log, zwave15.log,
  api_validation_session2.csv}`; new script `check_zombie_holes.py`.
- Resume (next session, after freeing disk headroom): `requeue_transient.py`
  (14+3 transient rows), `enrich_queue.py`, `audit_timeline.py`,
  `reconcile_net_profit.py`, then
  `sustainable_run.py --from-file output/universe_fetch_order.txt
  --max-per-company 25 --skip-discovery` (pending 1,427 = 1,350 actionable +
  backlog), then discovery wave 16 for the remaining **51 undiscovered**
  companies (`--wave 16 --limit 15 --max-pages 8`; wave-15 throttled 5 retry
  first). Milestone: undiscovered < 30, then 0 or explicit terminal state.
  Do NOT start Model v2 / Signal Engine; do NOT enable SQL Server; no pre-1398.

## 37. Upgrade plan approved — Phase 0 done (real numbers materialized)

Plan (user-approved): make the chat assistant a grounded analyst + portfolio
builder. Guiding rule: the LLM never produces numbers; every figure comes from a
Go tool over canonical data. Phases: 0 (data/real numbers) → 1 (tools +
tool-calling loop) → 2 (risk/portfolio engine in Go) → 3 (PIT backtest
validation) → 4 (structured blocks + UI) → 5 (external data: sector/board,
shares/free-float, index series) → 6 (personalization, family cash/assets).

Phase 0 — completed and verified live:

- Root cause found and fixed: `analytics.factor_scores.raw_value` was NULL for
  all 28,035 rows, so no consumer could state an actual P/E, growth or margin
  (the chat's "تحلیل کیمیا" printed no P/E or growth line). The engine only
  stored percentiles. Same for `analytics.metric_snapshots` (0 rows).
- `analytics_canonical_v1/compute_metrics.py`: added `FACTOR_RAW_SPEC`
  (factor → raw metric field, unit, higher_is_better) + `METRIC_UNITS`; `store_run`
  now writes `raw_value` and unit metadata per factor and one `metric_snapshots`
  row per (company, base metric) with its unit.
- Ran `orchestrate_refresh.py --mode RUN_IF_STALE` (the supported path; it targets
  the app DB `company_financial_analytics_shadow_v121`). New run
  `5fc702b2-8746-45a6-aa64-709bd15a4112`, as_of 2026-09-29: 267 companies,
  5,607 factor rows (**3,349 with raw_value**), **4,825 metric_snapshot rows**.
- Verified live: `/api/summary` non-null counts went from 0 to pe_approx 262/268,
  sales_growth_12m 182, operating_margin 100, roe 101, financial_leverage 101,
  current_ratio 101, cash_conversion 94, avg_trade_value_30d 268, price_return_30d
  261, volatility_30d 268, interest_coverage 119.
- Unit semantics confirmed from the engine (matter for any consumer): growths /
  margins / ROE / momentum are **percent**; `margin_trend` pct_point;
  `volatility_30d` daily percent stdev; `avg_trade_value_30d`, `latest_price`,
  `*_ttm` are **rial**; `eps_ttm` rial_per_share; `current_ratio`, `debt_ratio`,
  `cash_conversion`, `interest_coverage`, `pe/ps/pb` are ratios;
  `sales_stability` 0..1; `earnings_quality` is a non-operating share where
  **lower is better** (rank uses higher=False). `operating_profit_growth` can be
  an astronomically large percent from a small denominator (observed range
  −1.8e10 … +2.4e11) — the rank caps it at ±250; display must not print it.
- Go: `integration.SymbolPage` (identity + monthly + financial + market + scores
  + factor scores + metric snapshots + freshness) was reachable only from
  `cmd/symbolvalidate`. Added `SymbolPage` to the `canonicalSource` interface and
  a `Shadow.FetchSymbolPageCanonical` wrapper (+ test fake).
- Chat company analysis now reads that bundle: real P/E, P/S, P/B, margins, ROE,
  growth, 30-day return, daily vol, average trade value, current ratio, leverage,
  cash conversion, TTM revenue/net profit, EPS — with unit-aware Persian phrases,
  an outlier guard (|growth| > 1000% is not printed; a footnote counts them),
  explicit data-limit lines (missing balance sheet, stale market vs score run) and
  as-of lines (last monthly activity, last financial report, market date).
- `GET /api/detail` revived as canonical-only: `?companyID=<legacy 32-hex>` or
  `?companyName=`; returns summary (canonical scores), identity, monthly,
  profit (EPS/revenue/operating/net profit/capital, million_rial), market
  (OHLC/volume/trade_value/change), `metrics` (29 base metrics with units) and
  `meta`. Previously it read the retired SQL Server view and read a path param the
  route never registered, so it always returned 400 — nothing depended on it.
- Client: `BigDataTable` and `ScoreBreakdown` now render percent values through an
  outlier-safe formatter (`>+1000%` / `<−1000%`) instead of printing
  millions-of-percent growth figures that materialization newly exposed.
- Verified: `go build ./...`, `go vet ./handlers/ ./integration/`,
  `go test ./integration/` (ok), `tsc -b`, `npm run build` all clean; endpoint
  smoke tests for chat + `/api/detail` against the live DB. Backend restarted
  (`go run .` on :5000, logs continue in `go-app/go-app-live.log`).
- Not yet visually re-verified: the `/Table` and score-breakdown rendering with
  the new real values (type-checked and build-verified only).

Remaining: Phase 1 (tool registry + agent loop; needs `AI_CHAT_URL`/`AI_API_KEY`,
with a JSON-action fallback if the provider lacks tool calling), Phase 2
(`go-app/quant`: returns/vol/max-drawdown/covariance shrinkage, inverse-vol +
min-variance with caps, rules fallback), Phase 3 (extend
`backtesting_v1/portfolio_simulator.py` — currently equal-weight top-20, "no
optimizer" — to score every weighting scheme on the frozen PIT snapshot), Phase 4
(block payloads + client renderer, reuse ScoreBreakdown/Portfolio table/charts,
apply-to-portfolio only after confirmation), Phase 5 (sector/board, shares/free
float, index series → enables sector caps and beta), Phase 6 (personalization via
real portfolio + family cash).

## 38. Phase 1 done — tool-calling assistant is live (LLM grounded on canonical data)

Configured LLM (`.env` is gitignored; keys never logged or echoed):
`AI_CHAT_URL=https://api.avalai.ir/v1/chat/completions` with model routing
`AI_MODEL=glm-5.3-flash` (main), `AI_MODEL_HARD=deepseek-v4.1-flash`,
`AI_MODEL_CHEAP=deepseek-coder`. All three were probed for real tool calling
against the gateway and all returned proper `tool_calls`; `gpt-4o-mini` also
works (kept as an alternative). Note: the account balance is very low
(~0.12 units) — `claude-sonnet-4-5` is already refused with "insufficient
credit", so cheap/flash models are the only usable ones right now.

- `go-app/handlers/chat_tools.go` — 8 read-only tools, every number comes from
  canonical PG or the `quant` package: `search_companies`, `screen_companies`,
  `get_company_profile`, `get_company_financials`, `get_monthly_sales`,
  `get_price_stats`, `get_my_portfolio`, `compare_companies`.
- `go-app/handlers/chat_agent.go` — the agent loop: OpenAI-style `tools` +
  `tool_choice:auto`, up to 6 rounds, 45s per model call and a 100s budget;
  model routing by task class (`looksHard` sends سبد/مقایسه/ریسک/بازار questions
  to the hard model); system prompt forbids inventing numbers and requires the
  "not advice" line; unknown tools and bad arguments degrade to an error message
  handed back to the model instead of failing the request.
- `go-app/quant/returns.go` — deterministic series math (daily returns, mean,
  stdev, annualized volatility, downside deviation, cumulative return, max
  drawdown, window return, correlation). Units documented per function; this is
  the foundation Phase 2's optimizer builds on.
- `go-app/integration/scores.go` — added `AllScoreInputRow.FactorRank(code)`.
- `POST /api/chat` now prefers the agent and silently falls back to the rule
  engine when the LLM is unset or errors; `GET /api/health/ai` (protected)
  reports configured/reachable/model/latency without exposing the key.
- Verified live: "بهترین سهمها برای سرمایهگذاری" → `screen_companies`, 10 names
  with real P/E/growth/liquidity, explicitly labelled "ranked list, not an
  optimized portfolio" (21s); "تحلیل فولاد" → `search_companies` +
  `get_company_profile` + `get_company_financials` + `get_price_stats`, giving
  TTM revenue/net profit/EPS, quarterly YoY decline, 365-day return +58.6%/30d,
  annualized vol 34.9%, max drawdown −49.4%, liquidity 10.79e12 rial/day, plus a
  data-quality warning about zero/incomplete revenue in some periods and the
  capital increase (38s); "سبد سهام من چطوره و چه ریسکی داره؟" routed to
  `deepseek-v4.1-flash` → `get_my_portfolio` → honest "no portfolio registered"
  (6.6s). Tool traces are logged to `go-app/go-app-live.log.err`.
- Latency is 7–40s for a deep multi-tool answer (several model+tool rounds);
  Phase 4 must add progress/streaming before this feels good in the UI.
- Not done in this phase: `build_portfolio` tool (needs the Phase 2 optimizer),
  structured response blocks, SSE.

Next: Phase 2 — `go-app/quant/optimize.go` (shrunk covariance, inverse-volatility
and min-variance weights with per-name caps + liquidity/coverage eligibility),
expose it as the `build_portfolio` tool, then Phase 3 — extend
`backtesting_v1/portfolio_simulator.py` (equal-weight top-20, "no optimizer") to
score every weighting scheme on the frozen PIT snapshot *before* any scheme is
presented as a recommended portfolio.

### 38a. LLM findings from live verification (important for cost/latency)

- All three configured models really do tool calling through the AvalAI gateway
  (verified with a real `tools` payload): `glm-5.3-flash` 1.4s,
  `deepseek-v4.1-flash` 2.2s, `deepseek-coder` 4.1s for the same probe. The
  previous probe that showed "no tool calls" was testing without sending `tools`
  in the body — not a model limitation.
- `glm-5.3-flash` is a **reasoning model**: responses carry
  `reasoning_content` and the visible `content` only appears after reasoning
  finishes. With `max_tokens=64` all 63 completion tokens went to reasoning and
  `content` came back empty (`finish_reason=length`) — that is why
  `/api/health/ai` first reported an empty reply. The agent loop sets no
  `max_tokens`, so real answers are fine, but the token/latency cost per round is
  higher than a non-reasoning model. `/api/health/ai` now uses 512 tokens and
  falls back to the reasoning snippet for its sample line.
- Measured end-to-end latency: 21s for a screening answer (2 model rounds +
  screen call), 38s for a full single-company analysis (4 tools in one round),
  6.6s for the portfolio question. Multi-round tool use is the main driver;
  Phase 4 should stream progress.
- **Account credit is nearly exhausted**: balance ≈ 0.12 units, and
  `claude-sonnet-4-5` is already refused with "insufficient credit". Cheap/flash
  models are the only usable ones until the balance is topped up. If speed and
  cost matter more than reasoning depth, `gpt-4o-mini` (tool-capable, ~1s,
  non-reasoning) works on the same key and only needs `AI_MODEL` changed.

### 38b. Cost-capped model config (owner request: cheapest possible, ceiling = deepseek-v4.1-flash)

Provider pricing read from `GET /v1/models` (per 1M tokens: input / cached-input / output):

| model | in | cached | out | note |
|---|---|---|---|---|
| glm-5.3-flash | 0.075 | 0.015 | 0.25 | reasoning model → burns reasoning tokens billed as output; 3–6s/round; removed |
| deepseek-v4.1-flash | 0.15 | **0.003** | 0.6 | chosen: cheapest reliable non-reasoning tool-caller |
| deepseek-coder | 0.22 | 0.007 | 0.66 | **more expensive than v4.1-flash** — the "cheap tasks" label was wrong; removed |
| deepseek-flash / gpt-4o-mini | 0.15 | 0.003 / 0.075 | 0.6 | same price; kept as alternatives |

The gateway's genuinely cheapest models (gpt-oss-20b 0.007/0.03, nemotron, llama 1b/3b,
granite-micro) are not trustworthy for Persian financial analysis or tool calling, so
they are not used.

- `.env` now: `AI_MODEL=deepseek-v4.1-flash`, `AI_MODEL_HARD=deepseek-v4.1-flash`,
  `AI_MODEL_CHEAP=deepseek-v4.1-flash`. The hard/cheap knobs stay so a stronger or
  cheaper model can be enabled later without code changes.
- Structural token cuts: `agentMaxRounds` 6→4, history sent 8→4 messages,
  `screen_companies` default rows 15→10 (max 40→25). Prompt tokens are re-sent and
  re-billed on every tool round, so these are direct cost cuts.
- `callAgentModel` now logs `tokens prompt/completion/total` per round so cost is
  observable in `go-app/go-app-live.log.err`.
- Measured on a real question ("سه سهم نقدشونده با P/E زیر ۷"): 3 rounds,
  9,026 prompt + 960 completion ≈ 10k tokens ≈ **$0.002/question** at the listed
  rates, 15.3s wall clock. Prompt dominates, and the provider's cached-input rate is
  50× lower, so prefix caching is the main further saving if it applies.
- Rough balance note: the account showed ≈0.12 units, i.e. on the order of tens of
  questions at this per-question cost (unit-to-currency mapping not confirmed).

## 39. Phase 2 done — Go portfolio builder live; Phase 3 (PIT validation) in flight

Phase 2 (live, verified):
- `go-app/quant/returns.go` + `portfolio.go`: deterministic series math — daily
  returns, stdev, annualized/downside vol (250 trading days), cumulative return,
  max drawdown, window return, correlation, aligned returns over a union calendar
  with forward-fill and per-series start column (pre-listing padding must not
  enter the covariance), sample covariance with a `start_row`, diagonal
  shrinkage (λ=0.3), capped equal/inverse-vol/min-variance weights via projected
  gradient + water-filling cap projection, portfolio vol/series, Sharpe-like
  (rf=0), average pairwise correlation, one-way turnover, cash-buffer scaling.
  `go test ./quant/` passes, including the analytic two-asset min-variance check.
- `go-app/handlers/portfolio_build.go` + the `build_portfolio` tool (9 tools now):
  universe = canonical scores with liquidity/score floors (risk profile: low 12
  names/10% cap/10% cash/liq≥0.6, medium 15/12/5/0.4, high 20/15/0/0.25),
  parallel PIT price fetch (≤30 candidates, ≤1000-day window), aligned covariance,
  weighting, and a report that states its own limits: no index → no beta/rf=0,
  no sector tags → no industry caps, no forward-return estimate, dropped names
  listed, and "not yet backtest-validated". Turnover vs the user's real portfolio
  when one exists. Verified live: cap respected, min-variance vol 17.2% vs 19.8%
  equal-weight on the same names, avg pairwise corr 0.19.
- Note for Phase 4/UX: selection is score-ranked then min-variance-weighted, so
  low-score/high-vol names can get tiny weights and mid-score names can get the
  cap — expected optimizer behaviour, but a "score tilt" variant may be wanted.

Phase 3 (validation gate, in flight):
- `backtesting_v1/risk_model.py` (+7 passing tests): same math in Python, PIT
  weights per rebalance from closes ≤ signal date only; `PriceStore.window_closes/
  window_dates` (bisect over a cached sorted date list) for cheap PIT windows.
- `run_backtest.py`: `cfg.weighting != "equal"` now attaches PIT weights to every
  selected member; new `run(..., simulator=)` selector — "corrected" is the
  Phase-2 cash-aware policy and the only one honouring weights (`simulate` ignores
  them; that was caught before any conclusion was drawn). Smoke test on
  2026-01→06 confirms the three schemes produce different paths.
- Full-window runs (66 monthly rebalances, 2021-01→2026-06, top-20, 10bps/side,
  simulate_corrected for all schemes) launched for equal / inverse_vol /
  min_variance into `output/weighting_validation/<scheme>/`; one run ≈ 14 min
  wall. `weighting_validation.py` will emit comparison.md/json with a
  risk-adjusted verdict; until it passes, `build_portfolio` keeps its
  "not backtest-validated" label.

### 39a. Phase 3 verdict — validation gate changed the default (as designed)

Full-window PIT runs (66 monthly rebalances, 2021-01→2026-06, top-20, 10 bps/side,
`simulate_corrected` for every scheme) — `output/weighting_validation/`:

| scheme | net cum | ann. return | vol | maxDD | sharpe-like | turnover |
|---|---|---|---|---|---|---|
| equal (capped) | +874.3% | 56.5% | 10.0% | −24.7% | **1.47** | 28.2% |
| inverse_vol | +830.5% | 51.0% | 9.7% | −23.2% | 1.40 | 28.2% |
| min_variance | +729.2% | 47.8% | 10.0% | **−20.9%** | 1.30 | 28.2% |

Verdict: no risk-adjusted edge for the optimizer over equal weighting on this
path — equal keeps the best Sharpe-like; min-variance's only edge is ~3.8pp
shallower max drawdown at a large return cost. Action taken: `build_portfolio`
default method switched **min_variance → equal**, the scheme table is now quoted
in the tool output, and the stale "not validated" warnings/system-prompt line
were replaced with "weights chosen from the 2021–2026 PIT backtest; past
performance is no guarantee". `min_variance`/`inverse_vol` remain selectable
(low-drawdown variant). Comparison artifacts: `weighting_validation/comparison.{md,json}`.
Caveat kept: one full-window path ≠ OOS protocol; the coverage-controlled
revalidation (§38 note) is still the follow-up before making stronger claims.

Everything rebuilt, `go test ./quant/` and `go vet` clean, backend restarted.

Remaining: Phase 4 (SSE progress + structured blocks + client renderer),
Phase 5 (sector/board, shares/free float, index series), Phase 6
(personalization over real portfolio + family cash).

## 40. Phase 4 done — live progress streaming + markdown answers

- `POST /api/chat/stream` (`go-app/handlers/chat_stream.go`): SSE with events
  `open` → `progress` (`round` / `tool_start` / `tool_done` / `tool_error`) →
  `notice` (rule-engine fallback) → `final` (chatResponseBody with `tools_used`).
  `X-Accel-Buffering: no` is set for reverse proxies. `runChatAgent` now takes an
  event sink (nil = old behaviour) and returns `tools_used`; the synchronous
  `/api/chat` response also carries `tools_used`.
- Client: `sendChatMessageStream()` in `api.ts` (fetch + manual SSE frame
  parsing, graceful abort), `ChatPage` shows a live Persian progress chip
  («پروفایل بنیادی شرکت…» / «ساخت سبد…» / «در حال تحلیل…») under the typing dots
  and falls back to the synchronous endpoint if the stream fails.
- Markdown rendering: `react-markdown` + `remark-gfm` (installed with
  `--legacy-peer-deps`; React 19 peer conflict) so the model's natural Markdown
  (tables, bold, bullets) renders properly instead of raw `|---|` pipes. Styled
  table/ul/ol/a components.
- Verified in-browser end-to-end (temp dev server on :3010 pointed at the local
  API): progress chip visible mid-stream during a multi-tool question; final
  comparison answer rendered with a real Markdown table. Backend event timeline
  confirmed from Node: open 0.1s → 4 rounds, 9 tool events → final 16.1s with
  `tools_used`.
- Known quirk (not a product bug): Playwright's fill+Enter did not trigger the
  React keydown handler in the IAB; clicking the send button works. Real typing
  uses the same keydown path — worth a manual Enter check on a real keyboard.
- Remaining in Phase 4 (deferred): token-level streaming (`stream:true` to the
  provider), structured `blocks` payload with an apply-to-portfolio flow.

Remaining overall: Phase 5 (sector/board + shares/free float + index ingestion →
enables industry caps and beta), Phase 6 (personalization over the real
portfolio + family cash), plus the deferred Phase-4 items above.

## 41. Phase 5 done — industry classification + share structure live (sector caps active)

- Source proven reachable and sufficient: `Api.BrsApi.ir/Tsetmc/AllSymbols.php`
  (1 request, ~1636 instruments) carries `cs/cs_id` (TSETMC industry category —
  49 distinct, e.g. فولاد = «فلزات اساسی»), `z` (shares outstanding),
  `mv` (market value rial), `eps`, `isin`. TSETMC/Codal are also reachable from
  this server, but BRS needed no new credentials.
- New canonical tables (DDL `canonical_postgres_v1_2_1/sql/115_market_meta.sql`,
  applied to the shadow DB):
  `core.company_classification` (PIT: category change closes valid_to), 
  `core.share_structure` (daily snapshot, unique on security+date).
- New collector `go-app/py/sync_market_meta.py` (--dry-run supported): matched
  **265** canonical securities, 1,371 BRS rows unmatched (funds/rights outside
  the canonical universe — expected). Unmatched canonical names (e.g. غاذر)
  have a TSETMC code mismatch — they report as «نامشخص» and are excluded from
  industry caps. Run it daily (it is idempotent per day); a cron entry next to
  the BRS daily collector is the natural place.
- Go: `integration/market_meta.go` (`MarketMetaByLegacyCompanyIDs` → interface +
  Shadow wrapper), `quant.CapByGroup` (single-pass proportional group cap with
  redistribution; unit-tested including the compliant-input no-op), wired into
  `build_portfolio`: default industry cap 25% (`industry_cap` arg), per-holding
  industry in the output, an industry-exposure table, and coverage-aware
  warnings (partial coverage is disclosed per-name).
- Verified live: risk-profile-high portfolio → 19/20 names classified, 25% cap
  applied, غاذر reported as unmatched. `go build/vet/test` clean; backend
  restarted.
- Deferred (needs history or budget): index *history* — BRS `Index.php?type=1`
  works (TEDPIX + equal-weight index + market value + trades snapshot, free tier
  100 req/day) and `History.php` needs `l18` with a 10/day limit; plan is to
  accumulate a daily snapshot into `market.index_observations` via the daily
  collector and enable beta once enough history builds up. Beta currently stays
  "unavailable" in tool outputs.

## 42. Phase 6 done — personalization live (persistent prefs, capital-aware portfolios, portfolio critique)

- `chat.user_settings` (DDL `sql/120_chat_settings.sql`, applied): per-user
  risk_level + capital_rial. Dedicated test user `chat_smoke_test` created in
  auth.users (no working login; JWT-minted for smoke tests only).
- Tools added (11 total): `get_my_preferences`, `set_my_preferences`
  (`go-app/handlers/chat_settings.go`), and `critique_my_portfolio` — critiques
  the user's REAL holdings: weights, top-3 concentration, HHI, sector exposure
  vs the 25% industry cap (using `core.company_classification`), and portfolio
  vol/max-drawdown computed from each holding's actual price history (series
  that fail the history check are dropped, never padded).
  `readPortfolioHoldings` now also returns security_id + legacy company id.
- `build_portfolio` personalization: risk level and capital default from the
  user's saved settings; when capital is known the output lists per-name
  approximate amounts and quantities (floor(amount/price), labelled تقریبی).
- System-prompt rule added: everything is RIAL; if the user speaks toman, ×10
  and state the conversion, confirming the rial number before
  set_my_preferences. Found live: the model stored «۵۰۰ میلیون تومان» as 5e8
  rial (10× off) — the rule addresses it.
- Verified live with the real test user: set prefs → «ثبت شد»؛ get prefs →
  both values; personalized portfolio ran with saved risk/capital; critique on
  an empty portfolio answered honestly. Full flow with holdings requires a
  portfolio row for the test user (next session can upsert a few holdings and
  re-run critique).
- Deferred: client «apply to portfolio» button (needs the structured
  `portfolio` block on the response — the text output already carries
  amounts/quantities), token-level streaming, daily cron for
  `sync_market_meta.py`, index-history accumulation (beta).


## 43. Drawdown to 592 pending + discovery 100 % + one documented reconcile flag (financial-recovery track)

Gate kept: `UNIVERSE_BACKFILL_IN_PROGRESS`. `NET_PROFIT_RECONCILIATION_CLEAN`
requirement re-verified (duplicate-current violations = 0), but see the
**documented flag** below: the script's stricter gate string now reads
`NET_PROFIT_RECONCILIATION_FAIL` because of 1 heuristic legacy-display collision.
SQL Server OFFLINE. Fetch phase: ZERO Codal search calls; CAPTCHA 0 (no bypass).

- **Health/refresh first**: disk C: 6.3 GB → D: 8.0 GB; guard 2.0 GB unchanged;
  no backfill process running. `requeue_transient.py` 14 rows; `enrich_queue.py` 0;
  audit; reconcile; `check_zombie_holes.py` → 0. No drift from §37.
- **Discovery finished**: waves 16–20 (73 companies attempted, 68 discovered,
  7 throttled then retried, 0 CAPTCHA) → **PARTIAL_DISCOVERY_UNKNOWN = 0**
  (no company remains discovery-unknown), undiscovered 51 → **0 attempted-pending**,
  12 companies have no 1398+ letters at all (source-absent; NFR class 9 + 3),
  discovery cache complete 265. Letters added ≈ 2,153.
- **14 fetch-only batches** (10–23; `--skip-discovery`; company-completion order;
  checkpoint per report): 2,235 reports processed / **≈2,100 WRITTEN** /
  112 `SOURCE_TEMPORARY_ERROR` / 21 transient `FAILED` / 4 now
  `DEFERRED_SOURCE_TEMPORARY_ERROR` (retry cap engaged as designed) / 1 `FAILED_PERMANENT`.
  Rolling yield 0.93–0.99 through batch 22, then the tail degraded
  (batch 23: 0.73; recent-40/74 = 0.74) → **fetch phase stopped on the yield guard**
  (remaining holes are dominated by Codal system-error shells for 1398/3M letters;
  per policy they are acquisition debt, not terminal).
- **BEFORE → AFTER (this session)**: recovered 4,421 → **6,506 (+2,085)**;
  pending 1,427 → **592 (−835 net)**; discovery_unknown 1,587 → **261 (−1,326)**;
  actionable pending+unknown 3,014 → **853 (−2,161)**; terminal 482 → **558**;
  coverage 55.8 % → **82.2 % (+26.4 pts)**. Companies: DC 9→**19**,
  CWSL 75→**95**, PFP 128→150, PDU 63→**0**, NFR 9 — **30 companies
  terminalized** (target +20 met). `zero_recovered_1398_plus` 84 → **13**.
- **Queue**: WRITTEN 6,603, DISCOVERED 5,498, FAILED_RETRYABLE 365,
  FETCH_PENDING 10, DEFERRED 4, FAILED_PERMANENT 1 (12,481 rows).
- **Quality**: `reconcile_net_profit.py` → net_profit facts **6,642**, unique
  current 1398+ periods **6,548**, **duplicate_current_violations = 0**;
  API `GET /api/SalesData` **33/33 companies** (19 DC + 8 CWSL + regression set)
  HTTP 200, chronological, 3/6/9/12, cumulative, no duplicate periods, no EPS
  fallback, no year gaps; source↔canonical conversion 7,314 values / 0 mismatches.
  PIT: analytics **25**, backtesting **34**, CAPTCHA/unit **20** — all passed.
  Disk C: 7.1 GB / D: 7.6 GB.
- **DOCUMENTED FLAG — `period_end_mismatch_audit.json` (new)**:
  8 of 6,620 codal lineage reports (0.12 %) carry a `period_end_date` one period
  early (Jalali leap-Esfand `x/12/30` conversion bug in the pre-existing lineage
  writer: e.g. tracing 748716 دلقما 1399/12/30 stored as 2020-03-19 instead of
  2021-03-20). **7 of the 8 have 0 statements / 0 facts** (no data effect);
  **1** (شلیا tracing 752545, 6M ending 1398/11/30) carries 1 net_profit fact
  attributed one year early. Consequences: (a) the reconcile script flags exactly
  1 `legacy_current_display_collision` (دلقما, 1399, 12M) because the legacy row
  at the true period end has no codal title next to it, so its gate string reads
  FAIL even though duplicate-current = 0 and the live API for دلقما is clean
  (27 rows, no duplicate (fy, periodOrder), all checks pass); (b) 1 value
  (شلیا) sits at the wrong period_end. NOT repaired here — writing to lineage
  rows is a data change requiring an explicit decision; the correct fix is to
  re-derive `period_end_date` for those 8 tracings from their own titles and
  move the single شلیا fact, then re-run reconcile.
- Artifacts: `output/{fetch_zbatch10..23.txt, zbatch10..23.log, zwave16..20.log,
  api_validation_session3.csv, period_end_mismatch_audit.json}`.
- Resume (next session): `requeue_transient.py` (21 transient rows),
  `enrich_queue.py`, `audit_timeline.py`, `reconcile_net_profit.py`,
  `check_zombie_holes.py`, then fetch the remaining **452 actionable units**
  (121 companies, mostly 1–4 units each) via a closest-to-terminal batch built
  from the audit CSV — only when the rolling yield is ≥ 0.75 (the tail is
  error-shell heavy now; respect backoff, do not hammer). Decide on the 8
  mis-dated lineage rows. Discovery: nothing left to discover; the 12
  no-letter companies are source-absent terminal candidates.
  Do NOT start Model v2 / Signal Engine; do NOT enable SQL Server; no pre-1398.

## 44. Market assets live — indices (شاخص کل/هم‌وزن) + gold & commodity funds (عیار/مثقال/…) with stock-like pages and price charts

Requested feature: exchange indices and gold/commodity fund symbols in the data,
each selectable like a stock with a working price chart.

- **Data model (canonical)**:
  - Indices are NOT securities — a new append-only table
    `market.index_observations` (DDL `canonical_postgres_v1_2_1/sql/116_market_assets.sql`,
    applied to the shadow DB; added to `tests/run_ddl.py` SQL_ORDER). Unique per
    (index_code, trade_date); a same-day re-run upserts. An index has no issuer,
    no ISIN and a level rather than an IRR price, so it must not fake a
    `core.securities` row (Company != Security invariant kept).
  - Funds ARE tradable securities: 59 gold/commodity ETFs (عیار، مثقال، طلا،
    ناب، گلدیس، …) registered as issuer `core.companies` + `core.securities`
    (`security_type` gold/commodity) + `core.security_aliases` (symbol, company
    name, brs name). They therefore flow through the EXISTING read paths with no
    changes: `/api/CompanyNames`, `/api/price-history`, stock dashboard, chart.
    مثقال was previously fuzzy-matched as a `stock`; it is now typed correctly.
  - Registry: `go-app/py/market_assets.json` (indices with stable codes
    TEDPIX/TEDPIX_EW/… + funds with ins_code). Refresh candidates with
    `python py/market_assets.py discover`.
- **Collector `go-app/py/market_assets.py`** (`ensure | backfill | daily | status | discover`):
  - `ensure` is idempotent; identity = tsetmc ins_code, then EXACT codal_symbol —
    never the display name (ناب/ناب2 share one legal name; a name lookup silently
    merged the second series — fixed).
  - `backfill` prefers BRS `Candlestick.php?type=3` (adjusted) and falls back to
    `History.php?type=0` (unadjusted daily OHLC → written to the canonical
    'adjusted' series slot but flagged `is_adjusted=false`,
    `adjustment_method='none'`, `source='brs_history'`); a later Candlestick run
    supersedes it (latest collected_at wins). `--limit` (default 8),
    `--min-rows`, `--all` make it resumable; gold funds are processed first.
  - `daily` = index snapshot (`Index.php?type=3` + type=1 market-wide stats) +
    today's fund prices from one AllSymbols request. Placeholder prices
    (untraded new series report 1 rial) are skipped (`MIN_VALID_PRICE_RIAL=100`).
    Fund daily snapshots use `source='brs_daily'` so they are appended, not
    deduped away by history rows, and win the latest-observation read.
  - **BRS free plan quota is the hard constraint**: ~10 requests/day per history
    endpoint (Candlestick 402s beyond that: `usage_today_limit: 10`). Today عیار
    (1,953 candles) + 4 more got full history; 51/59 funds have data, 8 remain
    (mostly the "2" second series + گلدیس/درنا/نگین فارس/همیان partials). Keep
    running `backfill` daily (gold first) until `status` reports 0 missing, or
    upgrade the BRS plan. Index history does not exist on BRS at all — it
    accumulates one row/day from now (charts start with 1 candle).
- **API (Go)**: `GET /api/market/assets` (indices + funds with latest price /
  change / observation count), `POST /api/market/collect` (admin → collector),
  and `GET /api/price-history` now serves indices by name («شاخص کل») or code
  (TEDPIX) through the identical JSON contract (cheap `looksLikeIndex` gate so
  the stock path pays no extra query). `integration/canonical.go` CompanyNames
  now orders companies before bare symbols/aliases so the client's default
  dashboard selection stays a real company (آتش — a newly added fund — had become
  names[0]); comparison is set-based, so ordering is safe.
- **Client**: new `/market` page («بازار و طلا» in the sidebar,
  `client/src/components/MarketPage.tsx`) — index cards with level + change,
  gold/commodity fund lists with search, and the SAME `PriceChart` component for
  the selection (indices via price-history, funds as securities); admin buttons
  for daily refresh and per-symbol history backfill.
- **PRE-EXISTING BUG FIXED**: `App.tsx` rendered `dataScore[0].epsGrowth` after
  only `dataScore &&` — an empty score array (any symbol without fundamentals,
  e.g. a fund) unmounted the whole React tree (blank page). Now gated on
  `hasFundamentals` and `dataScore.length`, with an explicit amber notice for
  market assets without financials.
- Verified live: migration applied; `ensure` 59 funds (50+8 created);
  `daily` 7 index rows + 58 funds; `/api/market/assets` 200 (7 indices, 59 funds);
  `/api/price-history?companyName=شاخص کل` and `عیار` (365 rows) 200;
  `go build/vet/test` clean, `tsc -b` clean, `vite build` clean; browser-verified
  /market (index card + عیار candlestick+volume chart) and /dashboard?companyname=عیار
  (no crash, notice + price chart). Go backend restarted on :5000.
- Resume (next session): keep the daily trio — `brs_prices.py daily`,
  `sync_market_meta.py`, and `market_assets.py daily` + `market_assets.py backfill`
  (resumable, gold first) — on the same cron; check `market_assets.py status`.
  If BRS quota is upgraded, run `backfill --all` once for full adjusted history.

## 45. Family assets: dollar (دلار) as a manually-entered, broker-independent asset

Request: add USD to family assets (سهام/طلا/نقد) entered per person manually —
explicitly NOT sourced from the Agah broker sync.

- **The model already had `category='dollar'`** (DB CHECK, Go validation, UI
  option, donut, `dollar_total`) but no dollar asset existed and — the real trap —
  `reconcileBrokerHoldingsPG` (family_broker_pg.go) does a FULL replacement of a
  person's holdings on every Agah sync (`DELETE ... asset_id <> ALL(keep)`),
  which would have silently erased any manually-entered dollar holding.
- **Broker sync now preserves manual assets**: before the replacement DELETE,
  holdings whose `family.assets.category IN ('dollar','other')` are added to the
  keep-list, so only broker-manageable categories (stock/gold) are reconciled.
  This is the load-bearing change; everything else was already wired.
- **Market price sync skips manual categories**: `syncFamilyPricesFromMarketPG`
  (family_assets_pg.go) ignores `dollar`/`other` assets entirely — they no longer
  appear in the «missing» list and their manual prices in `family.prices` are
  never touched by the daily BRS collector (which auto-calls this sync).
- **Asset created**: `family.assets` id 22 «دلار», category dollar, no symbol,
  commission_rate 0, sort_order 0. Initial price 2,547,000 rial (آزاد, tgju
  1405/07/08) inserted into `family.prices` — correctable any time in «ثبت قیمت روز».
- **UI polish**: `$` badge next to دلار in the price form and the assets table;
  the summary card now reads «سهام / طلا / دلار».
- **Gotcha worth remembering**: `canonical_ingest.db.connect()` does NOT commit —
  closing rolls back. Writes must use `transaction()`. The first dollar insert
  silently vanished this way; the read-back inside the same transaction made it
  look successful.
- **Verified**: API round-trip — asset listed with latest_price 2,547,000
  (1405/07/08); temp holding for علی (1,000 دلار, cost 2.4B) → value 2,547,000,000,
  profit +147M (+6.1%), `dollar_total` aggregated, then removed (state restored);
  `POST /family/sync-prices` → 11 updated / missing = stale stock symbols only,
  dollar excluded and price intact; `go build/vet` clean, `tsc -b` + `vite build`
  clean; browser-verified /assets (price form row «دلار$✎», portfolio table row,
  summary card). Go backend restarted on :5000.
- Usage: for each person → «سبد اشخاص» → «افزودن دارایی به سبد» → دلار + تعداد
  (تعداد دلار) + بهای تمام‌شده (ریال). Rate updates: «خلاصه و ثبت قیمت» → دلار row.
- Follow-up (same session): «پرتفوی کل» table now (a) hides assets whose
  total_quantity is 0 (e.g. a freshly created-but-unheld asset), and (b) adds a
  «جمع کل» footer (بهای تمام‌شده / ارزش / سود+درصد / وزن) plus the same totals
  row in the CSV export. Empty state text when nothing is held.
- Follow-up 2: «پرتفوی کل» columns are now sortable — click a header to sort
  (first click desc, click again toggles asc; active column highlighted with
  FaSortUp/FaSortDown). Sort keys: name (fa localeCompare), latest_price,
  price_date (Jalali text sorts correctly), total_quantity, total_cost,
  total_value, total_profit, weight. Default sort = ارزش desc. CSV export and
  the جمع کل footer follow the sorted order. `tsc -b` + `vite build` clean;
  verified in-browser (name asc/desc, تعداد کل desc).
- Follow-up 3: the top stat row of /assets was reworked. Removed the redundant
  «ارزش دارایی‌ها» (merged مانده into «جمع کل») and the arbitrary ±3%
  «بهترین/بدترین حالت فردا» cards. New `client/src/components/MarketPulseCards.tsx`
  renders a 4-card «نبض بازار» strip above the family cards: شاخص کل and
  شاخص کل (هم‌وزن) (level + today's change% from /api/market/assets), طلا via
  مثقال (price + today's change + ~30-day change computed client-side from
  price-history), and دلار (manual rate from the family state). Degrades
  gracefully — cards simply don't render when their data is missing. Family
  cards grid rebalanced to 3 columns.
- Follow-up 4: the three family cards were densified. «سود / زیان کل» now also
  shows the cost base and the best/worst holding by profit_pct (real data, not a
  projection). «سهام / طلا / دلار» shows the category total, a 3-segment stacked
  allocation bar (same colors as the donut) and each category's weight %.
  `tsc -b` + `vite build` clean; verified in-browser.


## 43b. Period-end repair (8 lineage dates) + fetch tail stopped on yield guard

Financial-recovery track. Gates at end: `NET_PROFIT_RECONCILIATION_CLEAN`
(duplicate-current 0, legacy collisions 0), `ZOMBIE_ACTIONABLE_HOLES = 0`,
`UNIVERSE_BACKFILL_IN_PROGRESS`. SQL Server OFFLINE; CAPTCHA 0.

### PERIOD-END REPAIR (root cause + fix)
- **Root cause** was NOT the arithmetic converter (`jdatetime` is exact, incl.
  leap Esfand 30): `extract_date_from_table` took the FIRST date-bearing
  statement-header column, which is the **comparative (prior-period) column**
  for some letters → statement attributed to the wrong economic period
  (e.g. شلیا 752545 title ۱۳۹۸/۱۱/۳۰ stored as ۱۳۹۷/۱۱/۳۰ = 2019-02-19).
- **Shared fix**: `period_end_from_title()` in `codal_ingestor/parsers/common.py`
  (title "منتهی به YYYY/MM/DD" is authoritative; table header only a fallback) +
  `report_title=` parameter on `parse_profit_loss_html`; all backfill call sites
  (sustainable_run / backfill_net_profit ×2 / captcha_aware ×2 / targeted_finish)
  now pass the letter title. No symbol-specific logic.
- **Tests**: `historical_codal_backfill/tests/test_period_end_title.py` — 15 cases:
  title extraction (1399/12/30, 1400/12/29, 1403/12/30, 1398/05/31, 1398/11/30, …),
  exact Gregorian conversions (leap + non-leap Esfand), parser regression
  (title beats the comparative column), fallback preserved. All pass.
- **Repair** (`repair_period_end.py`, canonical patterns only — reports metadata is
  schema-mutable (only source identity is immutable); statements/facts immutable →
  append-only correction): 8 reports corrected.
  - 7 metadata-only (0 statements/facts): تایرا 1066941 (2023-03-20→2023-06-21),
    تایرا 1301680 (2024-03-19→2024-12-20), دلقما 748716 (2020-03-19→2021-03-20),
    دامین 752100 (2020-03-19→2021-03-20), شکربن 752867, کطبس 755390, کپرور 762086
    (2020-03-19→2021-03-20).
  - 1 fact-bearing: شلیا 752545 (2019-02-19→2020-02-19) — reparsed the stored raw
    with the fixed parser → new report version + parse_run; the corrected
    net_profit fact was attached to the EXISTING statement at the true period
    (1398/11/30 = 2020-02-19); no duplicate economic period; old statement/fact
    preserved as evidence.
- **Read guard (1 generic condition)** in `NetProfitSeriesByLegacyCompanyID`:
  a period is current only if its statement period is backed by an identified
  source period (a Codal letter normalized to that period, or the statement's own
  report carrying the same period). Universe-wide effect: exactly 1 displayed
  period removed (شلیا's orphaned 2019-02-19 row); legacy-only periods unaffected
  (their own reports carry the period). Live :5000 process must be restarted to
  pick this up (validated on a temp :5099 instance + SQL-level proof:
  263→263 companies, only شلیا 26→25 rows, total periods 6643→6642).
- **Result**: mismatch detector 6,620/6,620 consistent (was 8 wrong); دلقما
  legacy collision GONE; the orphaned prior-parse fact is now classified as an
  unresolved-title evidence row (`codal: 1`) instead of a display collision;
  **reconcile gate = NET_PROFIT_RECONCILIATION_CLEAN** (duplicate-current 0,
  legacy collisions 0). API on the fixed code: 24/24 companies pass incl. all 7
  affected; شلیا 25 rows, no (fy, periodOrder) duplicate, value at
  2020-02-19 / 1398 / 6M. PIT: analytics 25, backtesting 34,
  backfill/captcha/period-end 35 (incl. the 15 new), Go integration tests pass.

### FETCH TAIL (batches 24–28) — stopped on the yield guard
- 372 processed / **279 WRITTEN** / 81 `SOURCE_TEMPORARY_ERROR` / 12 retryable →
  rolling yield 0.75 overall; recent-40 fell to **0.67 < 0.75 → phase stopped**
  (tail dominated by Codal system-error shells for 1398/3M letters; capped rows
  moved to `DEFERRED_SOURCE_TEMPORARY_ERROR` (now 7), never terminal).
- pending 592 → **325**; recovered 6,506 → **6,773 (+267)**; terminal 558.
- **Split (unit-level)**: actionable `DISCOVERED_PENDING_FETCH` **157**
  (121→~100 companies, 1–4 units each) · deferred temporary-source debt
  `RETRYABLE` **161** · true terminal `SOURCE_NOT_FOUND_CONFIRMED` **558** ·
  period-level `DISCOVERY_UNKNOWN` **1,711**.
- CAPTCHA 0. Disk C: 6.9 GB / D: 7.6 GB. Queue: WRITTEN 6,724→6,854 range during
  the phase; final states: DISCOVERED 5,220, FAILED_RETRYABLE 390, FETCH_PENDING 10,
  DEFERRED 6(+1), FAILED_PERMANENT 1.

### EXTERNAL CHANGE — universe expanded by a parallel session (not this track)
At 19:15 local another session inserted **50 commodity/gold funds** into
core.companies/securities (طلا، کهربا، سینرژی، سیمین، جام طلا، امرالد، آلتون،
عیار، …) → canonical companies 273 → **323**, `required_periods` 7,917 → **9,367**,
`NO_FINANCIAL_REPORTS` 9 → **59**, period-level unknown 261 → **1,711** (the
funds' ~1,450 units), so the headline `timeline_coverage_percent` diluted
82.2 % → 72.3 %. The financial-recovery numbers above are unchanged in scope on
the original 273-company roster (recovered 6,773 / pending 325 within it).
**Decision needed**: either the funds are in scope (then Codal net-profit
discovery must be run for them — they are funds; many may have no income
statements) or the timeline audit should scope to the operating-company roster.
Not changed here.

- Artifacts: `output/{period_end_mismatch_audit.json, period_end_correction_results.csv,
  api_validation_after_period_fix.csv, fetch_zbatch24..28.txt, zbatch24..28.log}`;
  code: `parsers/common.py (period_end_from_title)`, `parsers/profit_loss.py
  (report_title=)`, `repair_period_end.py`, `check_zombie_holes.py`,
  `canonical.go` (current-period guard), `tests/test_period_end_title.py`.
- Resume: (1) decide the funds scoping question; (2) restart the live Go process
  to pick up the read guard; (3) `requeue_transient.py` → enrich → audit →
  reconcile → zombie → fetch the remaining **157 actionable units** only when the
  rolling yield ≥ 0.75 (respect backoff; the 161 RETRYABLE units stay debt until
  Codal serves real pages). Do NOT start Model v2 / Signal Engine; do NOT enable
  SQL Server; no pre-1398.

### 43b addendum — final probe + closing split (same session)
- A small probe (batch 29, 8 companies, 44 reports: 31 WRITTEN / 13 STE,
  yield 0.70) confirmed the Codal late-night error-shell window is still active
  → fetch stays stopped per the yield guard. CAPTCHA 0 throughout.
- Final gates after refresh: pending **296**, recovered **6,802**, coverage
  72.6 % (323-company scope incl. the 50 external funds), reconcile
  **NET_PROFIT_RECONCILIATION_CLEAN**, **ZOMBIE_ACTIONABLE_HOLES = 0**
  (127/127; the 15 flagged just before were a stale-CSV artifact — always
  re-run `audit_timeline.py` before `check_zombie_holes.py`).
- Closing split (unit-level): actionable **127** · deferred temporary-source
  debt (RETRYABLE) **161** · true terminal (SOURCE_NOT_FOUND_CONFIRMED) **558** ·
  period-level DISCOVERY_UNKNOWN **1,711** (≈1,450 belong to the 50 external
  funds). net_profit facts **6,907**. Disk C: 6.9 GB.

### 43b part 2 — CORPORATE_NET_PROFIT_SCOPE_1398_PLUS reconciled; live :5000 restarted
- Root cause of the 273→323 drift: a parallel session inserted 50 gold/commodity
  fund companies (primary `security_type`='gold'/'commodity') for the market-assets
  track. Additionally مثقال — a commodity fund — had been inside the ORIGINAL 273
  all along (0 Codal letters, legal_name NULL).
- Explicit scope frozen (`freeze_corporate_scope.py` →
  `output/corporate_net_profit_scope_1398_plus.csv` + `_meta.json`): rule
  **corporate ⟺ primary security_type='stock'** — no name heuristics.
  Universe split: **canonical security universe 331** (272 stock + 51 commodity +
  8 gold) · **corporate net-profit subjects 272** · **NOT_APPLICABLE_CORPORATE_
  NET_PROFIT 51** fund instruments (مثقال + the 50 new) + 8 secondary "2"
  securities owned by fund companies. Nothing deleted; market/portfolio data intact.
- `audit_timeline.py` now consumes the frozen scope file: instruments outside it
  can never silently enter the corporate denominator (scope-drift guard) and are
  reported separately. Regression tests: `tests/test_corporate_scope.py` (8 cases
  incl. "a fund security does not enter corporate expected periods").
- **Corrected corporate timeline (272 subjects)**: required **7,888** (the 1,479
  fund units + مثقال's 29 left the denominator: 9,367−1,450−29) · recovered
  **6,802** · terminal **558** · pending **296** · period-level unknown **232** ·
  coverage **86.2 %** · DC 19 / CWSL 96 / PFP 149 / NFR 8 (=272) · zombie 0 ·
  reconcile **CLEAN**.
- Roster diff vs the old frozen 273: **272 unchanged corporate** · 0 new
  legitimate corporate · 0 removed · **مثقال reclassified out (fund, was
  mis-scoped in the old 273)** · 51 fund instruments + 8 secondary securities
  excluded. Gate **CORPORATE_NET_PROFIT_SCOPE_RECONCILED** = set.
- **Live :5000 restarted** with the fixed code (old `go run` child killed; new
  instance verified listening). Validation on :5000: 14/14 companies pass —
  شلیا 25 rows with the value at 2020-02-19/1398/6M, دلقما 27 clean, all other
  affected + ordinary + non-Esfand (وخارزم/حکشتی) samples: no duplicate
  (fiscalYear, periodOrder), HTTP 200.
- Fetch remains STOPPED (latest probe yield 0.70 < 0.75). Resume command when a
  probe ≥ 0.75: `sustainable_run.py --from-file <closest-to-terminal list>
  --skip-discovery --max-per-company 25` (recompute the list from the scoped
  audit; ~127 actionable units).

### 43b part 3 — FINAL CORPORATE CLOSEOUT: gates emitted
- Discovery closed for all 272 corporate subjects (wave 21: the last 8 companies
  بمولد/تاتمس/ثالوند/دزهراوی/رمپنا/غدام/فبستم/یاقوت → +309 letters; source-exhausted
  for 1) → **DISCOVERY_UNKNOWN = 0**.
- Actionable tail drained (probe yield 0.90 → batches 31/32: 256 processed,
  231 WRITTEN, yield 0.94/0.78) → **ACTIONABLE_PENDING = 0**; recovered **7,098**,
  terminal **610**, coverage **90.0 %** (272-corporate scope).
- New company classification `COMPLETE_WITH_DEFERRED_ACQUISITION_DEBT` added to
  the audit (actionable vs debt counters split): final company states
  DC **20** / CWSL **101** / **DEFERRED_DEBT 150** / NFR **1** = 272 — no ambiguous
  company remains.
- Reconcile: facts **7,185**, unique current periods **7,163**,
  duplicate-current **0**, legacy collisions **0**, gate **CLEAN**. The last
  heuristic flag (دجابر 1402/3M) was a **unit-label conflation**, not a collision:
  a legacy Q1 row (1402/03/31) vs a Q4 letter titled "۳ ماهه منتهی به ۱۴۰۲/۱۲/۲۹"
  share the (fy,dur) label but are different economic periods; the reconcile now
  reports such rows separately (`legacy_label_conflations: 1`) using the
  title-derived economic date, and only same-economic-period rows count as
  collisions.
- Final API on live :5000: **43/43 pass** (DC + CWSL + deferred-debt + banks +
  non-Esfand + previously problematic + corrected-report symbols); conversion
  7,857 values / 0 mismatches. The وسپه exact_conversion flag was a validator
  artifact on a None/None legacy row (validator fixed; the documented legacy
  no-title limitation remains).
- **GATES EMITTED** (`output/corporate_backfill_final_gates.json`):
  `HISTORICAL_NET_PROFIT_FULL_BACKFILL_PARTIAL` (180 deferred acquisition-debt
  periods) + `CUMULATIVE_PROFIT_UNIVERSE_READY`; `UNIVERSE_BACKFILL_IN_PROGRESS`
  superseded (actionable exhausted; only backoff-gated deferred debt remains).

## 46. Backfill CLOSEOUT + Model v2 data-readiness rebaseline (financial-recovery track)

Canonical closeout doc: `historical_codal_backfill/CORPORATE_NET_PROFIT_CLOSEOUT.md`
(single source of truth; supersedes conflicting counters in §23–§43b).
Gates: `CORPORATE_NET_PROFIT_SCOPE_RECONCILED` + `NET_PROFIT_RECONCILIATION_CLEAN`
+ `HISTORICAL_NET_PROFIT_FULL_BACKFILL_PARTIAL` + `CUMULATIVE_PROFIT_UNIVERSE_READY`
(`UNIVERSE_BACKFILL_IN_PROGRESS` retired).

- Maintenance debt workflow: `historical_codal_debt_retry.py` — probe-gated
  (≥0.75), capped, no discovery/CAPTCHA-bypass, never reclassifies debt as
  SOURCE_NOT_FOUND, never rewrites the gate artifact. The 180 deferred periods
  are maintenance debt, NOT project backlog.
- Guard suite: `corporate_backfill_guards.py` — G1 scope drift, G2 fund in
  timeline, G3 duplicate-current, G4 discovery-unknown, G5 zombie holes,
  G6 period_end mismatch, G7 EPS/unit conversion, G8 SQL Server dependency,
  G9 live API fiscal duplication → **ALL GUARDS PASS**.
- Model v2 rebaseline (`model_v2_validation/output/MODEL_V2_REBASELINE.json`):
  analytics recomputed (run `9ebb4335`, 271 companies, 5,691 factor rows) →
  signals rebuilt (13,481 rows) → factor decision table re-run: **8 factor class
  changes**, notably NetProfitGrowthRank INSUFFICIENT_DATA(3.9 % cov) →
  ROBUST_SIGNAL(82.4 %) and SalesGrowth3MRank WEAK → ROBUST; medium-coverage
  stratum 96 → 2,063 signals. Model v2 holdout: baseline IC 0.1721 / exp-a
  0.1617 / exp-c 0.1720; coverage-bias correlation 0.50 baseline vs 0.12–0.24
  candidates. Selection (frozen dev+val rule) still picks exp-a; gate stays
  **MODEL_V2_VALIDATION_WEAK** — now model-level only, data blocker removed.
- Data-debt impact: 150/272 companies affected but 129 have a single missing
  period of ~29; forward returns statistically indistinguishable
  (0.0326 vs 0.0329). No imputation performed.
- Signal Engine NOT started.

## 47. MODEL_V2_1_ROBUST_SET — pre-registered experiment (result: WEAK)

Pre-registration: `model_v2_validation/MODEL_V2_1_PREREGISTRATION.md` (frozen
before any Holdout/Forward read). Config hash
`e543ea3e3e957fbfbccd2f3fe26256cd1274b1d7c78727ef43f98bb074565373`.
Candidates (untouched exp-a/b/c left as-is): `canonical-v2.1-a` equal-weight over
the 6 ROBUST_SIGNAL factors · `-b` weights ∝ Dev-IC21 (PERank .294,
NetProfitGrowth .319, SalesGrowth .133, SalesGrowth3M .131, LowVolatility .115,
RevenueGrowth .009) · `-c` coverage-neutral (β=0.0005 fitted on Dev) ·
`-a-NPGX` ablation without NetProfitGrowthRank.

- **Frozen decision rule (Dev+Val only) produced NO eligible candidate → gate
  `MODEL_V2_1_VALIDATION_WEAK`.** v2.1-a failed R4 (Val turnover 0.655 > 0.65)
  by 0.005; v2.1-b failed R1 (Val IC21 0.1901 < baseline 0.1917); v2.1-c failed
  R4 (0.664). Rule not relaxed after seeing results.
- Dev 2021–23 IC21: baseline 0.0765 · a 0.1159 · **b 0.1276** · c 0.1158 ·
  a-NPGX 0.0923. Val 2024: baseline 0.1917 · a 0.2095 · b 0.1901 · c 0.2093.
- Holdout 2025 (diagnostic): baseline 0.1721 · a 0.1533 · **b 0.1707** · c 0.1528 ·
  a-NPGX 0.1327. Forward 2026 (diagnostic): baseline 0.3589 · a 0.3750 ·
  **b 0.3792** · c 0.3741 · a-NPGX 0.3365.
- Coverage-bias control is the robust-set's real win: coverage–score correlation
  0.013–0.075 (candidates) vs 0.41–0.50 (baseline) across Dev/Val/Holdout.
- **NetProfitGrowthRank ablation**: Δ IC21 = +0.0236 (Dev), −0.0134 (Val),
  +0.0206 (Holdout), +0.0384 (Forward) → net positive in 3 of 4 periods; Δ spread
  positive in all; small coverage-corr cost. The recovered history adds
  measurable, if not decisive, model value.
- Audits (`output/model_v2_1_audits.json`): return convention = **raw_price_return**
  → cumulative 9.886 vs 2.480 means compounded net-of-cost wealth multiples
  (+988.6% vs +248.0%), equal-weight, monthly, 1-day execution lag; corporate
  actions unavailable → **RETURN_SERIES_NOT_PROMOTION_GRADE** (IC evidence stays
  usable). Lookahead: 250-sample audit → 0 violations (250/250 entry strictly
  after signal; 144 exposure signals correctly excluded by the PIT filter);
  backtesting PIT suite 34/34.
- Signal Engine NOT started.

## 48. FINAL bounded historical-share increment — Stage-4 ambiguity resolution (2026-10-01)

**Framing (user-issued task order):** the Model v2/v2.1 rebaseline result was accepted; one
bounded confounder remained — PERank_DIRECT coverage 41.9% vs factor-level direct IC *better*
than legacy in Dev/Val. One FINAL coverage increment was authorized: resolve the existing 311
`MATCH_AMBIGUOUS` TSETMC↔Codal LT28 events using **LT28 bodies only**, then rebuild
PE_DIRECT → PERank_DIRECT_V2 → frozen Model v2/v2.1 with **zero methodology changes**. After
this task historical-share acquisition is CLOSED regardless of gate outcome.

**Phase 1 — decomposition (pre-acquisition)** (`historical_codal_backfill/
coverage_decomposition.py`, `output/coverage_decomposition_pre_stage4.json`): all 13,481 grid
rows classified by first blocker (OTHER = 0, exhaustive): COVERED 5,648 · MISSING_PRICE 1 ·
MISSING_NET_PROFIT_TTM 645 · NO_TSETMC_SHARE_HISTORY 671 · PRE_FIRST_EVENT_UNKNOWN 758 ·
NO_CODAL_MATCH 91 · **AMBIGUOUS_CODAL_MATCH 3,403 (91 symbols — max recoverable)** ·
CODAL_PUBLISHED_AFTER_SIGNAL 1,916 · NEGATIVE_OR_INVALID_PE 348. Reconciliation exact:
5,996 v1 jsonl rows all on-grid; 5,648 valid-PE = the v1 rebaseline hit count; 348 invalid =
the rank-less rows the frozen `direct_ranks()` correctly skips.

**Phase 2 — body fetch** (`run_stage4_bodies.py`): 96 AMBIG symbols via `acquire_lt28`
unchanged policy — **594 network calls, 0×429, 0 CAPTCHA, ~55 min**, cache-first, bodies only
(no attachments/OCR/other letter types). 651 OK bodies total incl. pilot.

**Phase 3/4 — economic resolution** (`stage4_matcher.py` + `universe_join.py` Stage-4):
deterministic, economics-first (capital/par vs TSETMC count, tol 1e-6, capital used for
RECONCILIATION ONLY — shares stay TSETMC-authoritative), chronology second, contradiction
never accepted; Stage-3 records locked (zero demotions); amendments candidates with own
published_at; ZWNJ-normalized parser (fixes `به‌مبلغ` misses of the acquire-time parser).
Result: **311 AMBIG → 233 MATCH_EXACT + 21 MATCH_STRONG + 57 MATCH_STILL_AMBIGUOUS (23
symbols)**; NO_MATCH 0. knowledge_from = matched letter's published_at only; valid_from =
dEven only; 16 new unit tests (`tests/test_stage4_matcher.py`); parser parity vs Darou's
8-transition chain verified; 5-symbol end-to-end spot-check passed.

**Phase 5 — coverage before/after** (`output/coverage_decomposition_post_stage4.json`,
`universe_coverage_v2.json`): PIT-safe share rows 6,255 → **9,156 (46.4% → 67.9%)**; share-
valid 11,725 unchanged. RECOVERABLE_AMBIGUITY_RESOLVED = 3,062; LEGITIMATE_FUTURE_KNOWLEDGE_
BLOCK = 4,016 (incl. CODAL_PUBLISHED_AFTER_SIGNAL 2,246 — ambiguity resolved but the letter
post-dates the signal cutoff; PIT NOT weakened). First-blocker post: COVERED 8,205 · AMBIG
250 · published-after 2,246 · invalid-PE 614 · rest structural, OTHER = 0.

**Phase 6/7 — PE_DIRECT/PERank_DIRECT_V2** (`universe_pe_perank.py --tag v2`, append-only;
v1 artifacts untouched): `pe_direct_universe_v2.jsonl` **8,819 rows** (5,996) — valid PE
8,205 · PE<=0 375 · PE>60 239; +2,557 newly ranked, 0 dropped; engine rows reused from
`engine_rows_grid.json` (compute_metrics has no share_intervals dependency — verified; one-
date spot-check each load). CALC = `perank-direct-v2+tsetmc-shares+codal-knowledge+ambiguity-
resolved`.

**Phase 8 — factor IC (63d fwd, frozen split; Holdout/Forward descriptive)**: Dev: legacy
0.1579 → V1 0.1646 → **V2 0.1743**. Val: 0.2289 → 0.2216 → 0.2049. (`perank_direct_
validation_v2.json` carries ret_21 too; ad-hoc stage 5-6 reports are now reproducible.)

**Phase 9/10 — frozen model rerun** (`model_v2_direct_rebaseline_v2.py`, artifact `model_v2_
direct_perank_rebaseline_v2.json`): direct hits 5,648 → **8,205**; legacy lost 7,641 → 5,152.
Direct world Dev/Val IC21: a 0.1013/0.1946 · b 0.0968/0.1462 · c 0.1010/0.1949 (baseline
0.0765/0.1917). **v2.1-a and c now PASS R1** (previously failed Val vs baseline). Legacy
world reproduces §47 exactly (a 3/4 rules, b fails R1, c fails R4) — harness sanity check.
exp-a/exp-b (previously unexecuted older Model v2) closed: **legacy world fully eligible
(4/4 rules: a 0.0939/0.2082, b 0.0940/0.2146)**; direct world fails R1+R2 (a 0.0737/0.1996,
b 0.0759/0.1991, Dev pos-frac 0.69). Direct IC deltas vs V1 rebaseline: +0.0024…+0.0054
Dev/Val across a/b/c; Val pos-frac +0.083 (a/c); Dev turnover −0.008.

**Designations:**
- `MODEL_V2_DIRECT_REBASELINE = FAIL` (exp-a/b direct world: 2/4 rules each)
- `MODEL_V2_1_DIRECT_REBASELINE = FAIL` (direct world best a/c = 2/4 rules)
- `MODEL_V2_1_PREREGISTERED_GATE = FAIL` — failure MODE moved: R1 now passes (coverage
  dilution was real and material), remaining failures are **R2 (Dev pos-frac 0.72 < 0.75)**
  and **R4 (turnover 0.664/0.661 > 0.65)** — properties of the candidate set, not coverage.
- Answer to the task question: resolving the ambiguity materially improved direct coverage
  (+45%) and every direct Dev/Val IC, and moved v2.1-a/c past R1 — but did NOT flip the
  preregistered gate. Missingness dilution was a genuine confounder, not the whole story.

**STOP RULE EXECUTED:** `HISTORICAL_SHARE_REPAIR_COMPLETE = YES`. Historical-share
acquisition CLOSED (no OCR, no more LT28 sources, no nominal-value work, no alternative
share-history sources to be proposed). Next task: **RETURN_SERIES_CORPORATE_ACTION_
INTEGRITY** (`market.corporate_actions` empty; ex-date source discovery; contract amendment
before any writer). Signal Engine still NOT started. Holdout/Forward untouched as
decision surfaces; `RETURN_SERIES_NOT_PROMOTION_GRADE` still ACTIVE.

## 49. RETURN_SERIES_CORPORATE_ACTION_INTEGRITY — complete (2026-10-02)

Goal: determine whether the historical return series can be made adjustment-aware and
auditable, and if so build it — without reopening historical-share work, without tuning
anything, without the Signal Engine. Audit-first artifact: `backtesting_v1/
RETURN_PATH_AUDIT.md` (Phases 1-3) + `backtesting_v1/CORPORATE_ACTION_TAXONOMY.md`
(Phases 4/5/7/8, frozen).

**PHASE 1-2 findings (audit).** The "raw_price_return" label was a misnomer: `market.
price_observations` contains ONLY an adjusted series (705,812 rows `vendor_adjusted` +
5,546 later `NULL`-method rows from `brs_daily`; 1,163 duplicate (security,date) groups =
pre-existing PriceStore last-row-wins hazard, finding A1). `vendor_snapshots` empty; no
dividend data anywhere in the DB. Local evidence: TSETMC share-change cache, 708 cached
LT28 bodies (capital economics + funding source), 1,250 flagged ≥25% moves.

**PHASE 3 (endpoint validation).** 11 guessed adjustment endpoints → 404;
`TseClient2.aspx?t=ClosingPrices` → 500 (retired channel). **VALIDATED:
`cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{insCode}/0` = RAW daily
OHLC** (`pClosing`, `priceYesterday` re-based at events). Raw-ness proven on دارو
(25,420 → 1,280 across the ×19.92 event where the vendor series is continuous). The
official TSE adjustment algorithm (gap rule) was recovered from a verbatim port of
TSETMC's own client: event = price discontinuity; capital iff a share-change record
matches; else dividend = the gap; backward coefficient = after/before.

**PHASE 5 (two-axis proof).** دارو price re-base (ex) **2025-07-29** vs share-change
`dEven` **2025-08-21** vs LT28 publish 2025-08-25 — the frozen distinction is measurable,
not theoretical.

**PHASE 6 (pilot, 5 symbols).** Vendor series decoded: base field = **`pDrCotVal` (last
trade), NOT `pClosing`** (finding A3 — the whole model history ran on last-trade levels);
vendor ≡ **Mode 1 (capital + dividends)** backward-adjusted. Event-level vendor F-step
agreement: capital 20/20 verifiable, dividends 39/51 (all misses = windows merged with a
capital event, one post-migration staleness — وبملت 2026-07-25, gap≈1.0 noise).
**The promotion deficit was auditability, not missing adjustment.**

**PHASE 7 (decision).** Representation **B — raw prices + event-by-event factors**
(`CORPORATE_ACTION_TAXONOMY.md`); vendor series demoted to cross-check. No UI
considerations; smallest deterministic chain supporting forward returns, IC, backtests,
reproducibility, PIT-safe sourcing.

**PHASE 9 (pipeline).** Raw daily history fetched for the research universe (**238/238,
0 failures**, paced, gzip-cached, raw responses preserved). `build_corporate_actions.py`
→ **`market.corporate_actions` = 7,013 rows** (cash_dividend 4,344 · other/price-up
re-bases 1,775 · rights_issue 480 · capital_increase 384 · reverse_split 30; 237/238
symbols), idempotent (`source='tsetmc_gap_rule_v1'`), every row carries ex_date,
last_cum_date, reference prices, detection method, provenance ids; capital events
share-change-confirmed (`is_confirmed=true`), dividends flagged `detected_heuristically`
(no announcement source was crawled — per scope). Taxonomy field rule fixed during
validation: `adjustment_factor` = **after/before** (the backward coefficient); an inverted
chain was caught immediately by the factor-IC sanity check and corrected before any
model claim. Raw price tables untouched; `test_phase2` fabrication guard updated
deliberately (source-tag + confirmation/heuristic invariants instead of 0-rows).

**PHASE 10 (`FORWARD_RETURN_ADJUSTED_V1`, `phase3_signals_adjusted_v1.csv`).** Same
entry/exit semantics (frozen execution dates, global calendar, exact-date closes, None
rules). Coverage IMPROVED: ret_63 non-null 12,062 → 13,199. Windows straddling an event:
257 (5d) / 1,543 (21d) / 4,456 (63d). |Δ| vs legacy: median ≈1.0-1.1%, mean 1.4-1.6%
(the residual = pClosing-vs-pDrCotVal field difference + vendor staleness, documented).

**PHASE 11 (frozen harness on adjusted returns; PERank_DIRECT_V2).** Factor IC ret_63:
Dev +0.167 / Val +0.208 / Holdout +0.177 — reproduces the legacy-target evidence on an
auditable series. Direct world: baseline dev/val IC21 0.0753/0.1801; v2.1-a
**0.0992/0.1932 — passes R1+R3+R4, fails ONLY R2** (Dev pos-frac 0.72 < 0.75, same
near-miss as the raw world); b fails R1+R2; c fails R2+R4; exp-a 2/4, exp-b 3/4 (also
R2). Legacy-perank world: a/c 3/4 (R2), b 2/4. Holdout/Forward descriptive:
baseline 0.1728/0.2864, v2.1-a 0.1373/0.3297.

**PHASE 12 designations:**
- `RETURN_SERIES_INTEGRITY = PASS` — raw source validated 238/238; 7,013 provenance-
  complete events; vendor cross-check consistent at all verifiable events; adjusted
  coverage ≥ legacy; factor/model evidence reproduces.
- `CORPORATE_ACTION_PIPELINE = PASS` — idempotent, evidence-classified, provenance-
  complete, no raw writes, taxonomy frozen.
- `MODEL_V2_1_ADJUSTED_RETURN_GATE = FAIL` — no eligible candidate on adjusted returns.
  **Did return adjustment materially change the preregistered conclusion? NO.** The gate
  fails in both worlds; v2.1-a is the strongest candidate in both (3/4 rules, sole
  blocker R2 Dev positive-fraction 0.72 vs 0.75, identical near-miss) — but the evidence
  base is now promotion-grade and auditable, and the IC levels are measured on a
  defensible target rather than a black box.

`RETURN_SERIES_NOT_PROMOTION_GRADE` = LIFTED for FORWARD_RETURN_ADJUSTED_V1 (absolute-
return metrics may now be computed on the adjusted target; the legacy vendor target
remains frozen for comparison). Signal Engine still NOT started. Next open items: the
R2 near-miss is a candidate-set property (not tunable in this task); Signal-Engine
evaluation decision now has both prerequisites (share repair + return integrity) closed.

## 50. Return-layer integrity hardening — semantics separated from mechanics (2026-10-02)

Bounded hardening pass after provisional acceptance of §49. No historical-share work, no
model redesign, no gate change. Artifacts: `sql/118_corporate_action_semantics.sql`
(idempotent), `historical_codal_backfill/build_corporate_actions.py` (rewritten),
`semantic_hardening_report.json`, `return_reproducibility_demo.json`,
`CORPORATE_ACTION_TAXONOMY.md` (hardening section).

- **TASK 1/2**: all 4,344 price-gap-inferred `cash_dividend` labels DOWNGRADED to
  `PRICE_ADJUSTMENT_UNCLASSIFIED` (a price gap alone must not become a dividend); dividend
  amounts kept as `metadata.dividend_per_share_hypothesis`. Final: CONFIRMED 414
  (capital_increase 384 + reverse_split 30 — independently confirmed by TSETMC share-change
  records), INFERRED 480 (rights_issue — funding source from cached LT28 letter text),
  UNCLASSIFIED 6,119. No adjustment evidence deleted; 7,013 rows intact.
- **TASK 3**: option B — one table with `event_semantics_status` (CONFIRMED/INFERRED/
  UNCLASSIFIED) + `adjustment_evidence_status` (CONFIRMED/INVALID), idempotent migration
  registered in run_ddl.py. Return builder consumes CONFIRMED mechanical factors only.
- **TASK 4**: `CANONICAL_RETURN_PRICE = TSETMC pClosing` (official weighted close) frozen;
  no contract pins pDrCotVal (legacy last-trade semantics were a migration artifact — A3);
  legacy pDrCotVal series preserved for comparison; no mixing.
- **TASK 6**: exact rule = `priceYesterday(t+1) != pClosing(t)` (1e-6 tol, NO size
  threshold). 837,287 pairs → 7,013 flagged (0.84%, 1:1 with rows); **12,904 unflagged
  ≥5% and 2,734 unflagged ≥10% ordinary moves preserved**; 17.5% of flags are <0.5%
  reference revisions — not a big-move filter.
- **TASK 5/8**: chain rebuilt from raw + CONFIRMED factors only (vendor = cross-check);
  دارو example raw 25,420→1,280, factor 0.05035405, back-adjusted continuous (1.000000);
  **sha256 of phase3_signals_adjusted_v1.csv unchanged ⇒ FORWARD_RETURN_ADJUSTED_V1
  numerically equivalent**; no V2; measured gate result stands without rerun.
- **TASK 7**: mechanical factor consistency 12/12 in every share-event stratum; semantic
  precision reported separately (dividends not locally validatable → UNCLASSIFIED).

**TASK 9 gates:** `PRICE_ADJUSTMENT_PIPELINE = PASS` · `CORPORATE_ACTION_SEMANTICS =
PARTIAL` (honest: 414 confirmed / 480 inferred / 6,119 unclassified pending official
announcement evidence — no fabrication) · `RETURN_SERIES_INTEGRITY = PASS` (dates real,
factors reproducible, ordinary moves not suppressed, pClosing frozen, provenance complete).
`MODEL_V2_1_ADJUSTED_RETURN_GATE = FAIL` retained (numbers byte-identical).

**TASK 10: `DATA_INTEGRITY_BLOCKERS_CLOSED = YES`.** Historical shares AND return series
are both closed. R2 near-miss (Dev positive-fraction 0.72 vs 0.75) is accepted as the
candidate's result — R2/weights/factors untouchable without a new preregistered
experiment. Next project decision: **WHAT TO DO AFTER MODEL_V2_1_VALIDATION_WEAK** (not
data repair). Signal Engine NOT started automatically. Tests 180+62 green (fabrication
guard now enforces source-tag + confirmation/heuristic invariants).

## 51. MODEL V2.1 CLOSED — R2 root cause + Model v2.2 preregistered (2026-10-02)

v2.1 formally closed with `MODEL_V2_1_FINAL_STATUS = VALIDATION_WEAK` (immutable closeout:
`model_v2_validation/MODEL_V2_1_FINAL_CLOSEOUT.md`, hash-pinned to the final artifacts:
adjusted CSV `bf7cc191…`, pe_direct_universe_v2 `121dbb51…`, eval JSONs recorded). R2's
0.72-vs-0.75 is the accepted final result; no rescue is permitted.

**R2 diagnosis (Dev 2021-2023 ONLY; `model_v2_1_r2_diagnostics.py` →
`output/model_v2_1_r2_diagnostics.json`)**: 36 dates = 26 positive / 10 negative / 7
near-zero — exactly ONE date short of 0.75; nearest negative |IC| = 0.0022; quarter-block
bootstrap P(pos-frac ≥ 0.75) = 0.432 (threshold inside the sampling distribution);
negatives diffuse (all 3 years, 8 of 12 quarters, longest run 2) with two heavy dates
(2022-07-31 −0.332, 2023-10-31 −0.233). Factor attribution on the five worst dates:
LowVolatilityRank strongly negative on all five (−0.13…−0.53), PERank on four. Factor
availability: RevenueGrowthRank **5.2%**, SalesGrowth 29.7%, PERank 56.4%, LowVol 99.99%.
Redundancy: growth-family pairwise corr up to 0.649. LOO (diagnostic): NPGX −0.0223,
SalesGrowth +0.0005, RevenueGrowth −0.0009. Verdict: small-number-of-dates stability on a
thin diffuse margin + two heavy regime dates; NOT broad structural weakness. No regime
label exists in the codebase (year/quarter used). Holdout/Forward untouched.

**Model v2.2 preregistered** (`model_v2_validation/MODEL_V2_2_PREREGISTRATION.md`, frozen
BEFORE execution; MODEL_V2_2_EXECUTED = NO): binding data-snooping statement (2024/2025/
2026 can never be untouched holdouts again); exactly three Dev-grounded hypotheses — H1
missing-data interaction (RevenueGrowthRank 5.2% availability), H2 growth-family
redundancy (4/6 weight in one correlated family), H3 LowVolatilityRank unstable
contribution (diagnostic context; NOT removed — turnover anchor). Candidates: PRIMARY
`canonical-v2.2-a` = {PERank_DIRECT_V2, GrowthComposite(NPGX,SG,SG3M), LowVol} 1/3;
ablation `-b` = five factors (isolates H1); ablation `-c` = GrowthComposite₄ incl.
RevenueGrowth (isolates H2). Same R1-R4 thresholds (unchanged), same missing policy,
TOP_N 20, FORWARD_RETURN_ADJUSTED_V1, PERank_DIRECT_V2. Exploratory historical evaluation
procedure frozen (one deterministic execution; Holdout/Forward descriptive only);
confirmatory SHADOW protocol defined (≥12 future monthly dates, mean IC21 > 0, pf ≥ 0.75,
turnover ≤ 0.65, ≥ baseline; single judgment). Signal Engine boundary: RESEARCH_SIGNAL_
READY (exploratory PASS + shadow running) vs PROMOTION_READY (shadow confirmatory PASS +
integrity gates); Signal Engine work requires PROMOTION_READY.

**Final outputs: MODEL_V2_1_CLOSED = YES · MODEL_V2_2_PREREGISTERED = YES ·
MODEL_V2_2_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO.** STOP here per the task order.

## 52. MODEL V2.2 EXECUTED (once) — EXPLORATORY_GATE = FAIL, VALIDATION_WEAK (2026-10-02)

Preregistration clarified (shadow baseline pinned to frozen `canonical-v1-dev` mean IC21 on
identical shadow dates; shadow-scorer boundary section §8C added) and re-frozen:
**sha256 e4edbb781c110a584008a35a9ee36a871326d5e999e86c4c0f86f0431ae5bd25**. Executed
EXACTLY ONCE (`model_v2_2_execution.py` → `output/model_v2_2_execution.json`; input hash
verified `bf7cc191…`). All historical results EXPLORATORY_HISTORICAL. Baseline
canonical-v1-dev: Dev/Val IC21 0.0753/0.1801.

| candidate | Dev IC21 | Val IC21 | Dev pf | Val pf | Dev turn | Val turn | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|---|---|---|---|---|
| v2.2-a (primary) | +0.0705 | +0.1798 | 0.6944 | 0.8333 | 0.6502 | 0.6302 | FAIL | FAIL | PASS | FAIL |
| v2.2-b (abl.) | +0.1120 | +0.1988 | 0.7222 | 0.8333 | 0.6269 | 0.6352 | PASS | **FAIL** | PASS | PASS |
| v2.2-c (abl.) | +0.0705 | +0.1798 | 0.6944 | 0.8333 | 0.6502 | 0.6302 | FAIL | FAIL | PASS | FAIL |

(verbatim note: a vs c differ on exactly the 822 rows / 6.1% where RevenueGrowthRank
exists — identical at reporting precision.)

**MODEL_V2_2_EXPLORATORY_GATE = FAIL · primary = MODEL_V2_2_VALIDATION_WEAK ·
MODEL_V2_2_SHADOW_ELIGIBLE = NO.** No shadow spec created; no v2.3; no redesign.

**Hypothesis verdicts:** H1 (drop RevenueGrowthRank) — mechanism CONFIRMED
(renormalization frequency 97.9% → 70.6%; Dev IC 0.0992→0.1120, Val 0.1932→0.1988; R1
flipped to PASS) but Dev positive-fraction UNCHANGED at 0.7222 → R2 untouched. H2 (family
collapse) — REJECTED: collapse destroyed IC (Dev 0.1120→0.0705) and pos-frac
(0.7222→0.6944); upweighting LowVol to 1/3 diluted the strongest growth signal. H3 — NOT
experimentally tested (no candidate changes LowVolatilityRank), as preregistered.

v2.1-a vs v2.2-a: score rank correlation 0.9371, mean top-20 Jaccard 0.7244 — same model
family; v2.2-b fails R2 at the IDENTICAL 26/36 as v2.1-a. The R2 blocker (LowVol/PERank
negative dates) is structural across every preregistered variant and is ACCEPTED.

**Final outputs: MODEL_V2_1_CLOSED = YES · MODEL_V2_2_PREREGISTERED = YES ·
MODEL_V2_2_EXECUTED = YES · MODEL_V2_2_EXPLORATORY_GATE = FAIL ·
MODEL_V2_2_SHADOW_ELIGIBLE = NO · PRODUCTION_SIGNAL_ENGINE_STARTED = NO ·
DATA_INTEGRITY_BLOCKERS_CLOSED = YES.** Per the frozen stop rule: the robust-six family
is closed; any further research cycle requires new Dev-only evidence and a new
preregistration. STOP.

## 53. Research program decision — robust-six family CLOSED, no new family justified (2026-10-02)

Bounded Development-only decision analysis (`research_decision_analysis.py` →
`output/research_decision_panel.json`; document `RESEARCH_PROGRAM_DECISION.md`). Part 1
records the eight CLOSED findings (PE repair, PERank_DIRECT quality, return integrity,
RG availability, family redundancy, dual R2 failure, 26/36-vs-27/36, dead test periods).

**PART 3 — REGIME_MECHANISM_EVIDENCE = NONE.** Seven ex-ante state variables (breadth,
median trailing return, cross-sectional dispersion, volatility level, negative-PE
prevalence, PE dispersion, recent capital-adjustment fraction) median-split the 36 Dev
dates: negative dates at chance concentration (4–6 of 10) on every variable; several
wrong-signed (composite did BETTER in high-vol / high-neg-PE halves); correlations with
date IC between −0.15 and +0.15.

**PART 4 — LowVolatilityRank**: positive mean IC in every year (+0.027/+0.026/+0.059),
pf 0.556; +0.128 on positive composite dates vs −0.200 on negative; NO correlation with
ex-ante vol (−0.012), turnover (−0.053) or coverage (+0.026); rank-corr +0.177 with
PERank, −0.068 with NPGX. Negative episodes = RANDOM/NOISY, not systematic or
regime-dependent. Not removed, not reweighted.

**PART 5 — PERank_DIRECT_V2**: 12 negative Dev dates; all state correlations weak
(−0.22…+0.12); state means on negative dates ≈ identical to all dates; industry
domination NOT DERIVABLE (no sector columns). Ordinary sampling variation.

**PART 6/7 — NEW_MODEL_FAMILY_JUSTIFIED = NO.** Both allowed hypothesis classes
(regime-conditional reliability; cross-sectional confidence weighting) fail criteria 2+4
(ex-ante observability + Development support) — there is NO stable pre-observable state
behind the R2 failures. Zero surviving hypotheses. The research program STOPS: the
26/36-vs-27/36 shortfall is sampling noise around a modest positive mean IC (+0.086),
not an unexplained mechanism. Any future research requires genuinely new external
evidence and a new preregistration.

**Final outputs: ROBUST_SIX_FAMILY_CLOSED = YES · NEW_MODEL_FAMILY_JUSTIFIED = NO ·
SIGNAL_ENGINE_STARTED = NO · DATA_INTEGRITY_BLOCKERS_CLOSED = YES.** Infrastructure note:
a research-only shadow scorer is technically feasible but remains OFF (no shadow-eligible
candidate exists). Signal Engine NOT STARTED. STOP.

## 54. UI score historically validated — STRONG, monotone, POSITIVE spread (2026-10-02)

Product question: did the EXACT 0-100 score users see (canonical-v1-dev) predict relative
performance historically? Answer: **YES** — tested directly on the frozen grid.

- **PHASE 0**: production scorer = compute_metrics.py Engine (canonical-v1-dev, VAL_DIRECT);
  quant_score = DQ x (growth 36 + profitability 26 + valuation 16 + market 11, weighted
  rank sums with penalties); UI = analytics.company_scores run 0d2e5bc7 via
  summary_canonical.go -> ScoreBreakdown.tsx. Explicitly DIFFERENT from the tested v2.1/
  v2.2 composites. Manifest: ui_score_historical_v1/ui_score_production_manifest.json.
- **PHASE 3 parity**: fresh Engine run with the stored live-run parameters = 243/271
  exact; 28/271 differ ONLY in growth_score (<=2.4 points) because the stored run predates
  the current rank step (NetProfitGrowthRank EPS-fallback rank change). Explainable ->
  reconstruction used the CURRENT production implementation.
- **PHASE 2/4**: ui_score_historical_v1.jsonl = 13,481/13,481 grid rows (63 dates x 238
  symbols), every component preserved (raw metrics, ranks, contributions, categories, DQ,
  flags); shares injected from the validated TSETMC+Codal knowledge path (task directive);
  adjusted forward returns 21/63/126/252 (pClosing + confirmed factors).
- **Results**: IC21 +0.110 (pf .857) · IC63 +0.154 (pf .935) · IC126 +0.181 (pf 1.00) ·
  IC252 +0.157 (pf .982). Quintile means strictly monotonic Q1<Q2<Q3<Q4<Q5 on 63/126/252;
  Q5-Q1 = +0.07pp / +4.9pp / +11.0pp / +17.0pp (positive 4/4). Excess vs universe: Q1
  below, Q5 above at every horizon. Categories: Growth short, Valuation+Market long,
  Profitability weakest; combination matches/beats every category. DQ multiplier = gate
  not alpha (corr with ret63 +0.02); scores >=60 rare (83 rows), 80-100 band EMPTY
  historically. IC63 positive in every year 2021-2026 (+0.081..+0.253).
- **Gates: UI_SCORE_RECONSTRUCTION = PASS · UI_SCORE_HISTORICAL_PREDICTIVE_EVIDENCE =
  STRONG · UI_SCORE_MONOTONICITY = PASS (3/4 horizons; 21d flat) ·
  UI_SCORE_HIGH_VS_LOW_SPREAD = POSITIVE (4/4).**
- Score semantics for the product: a RANKING + quality summary — NOT a probability of
  profit. No score changes made. Signal Engine still NOT STARTED. Artifacts:
  UI_SCORE_HISTORICAL_VALIDATION.md, ui_score_historical_v1.jsonl,
  ui_score_historical_v1_analysis.json.

## 55. UI-score robustness audit — PASS on all four verdicts (2026-10-02)

Final robustness audit of the exact production UI score (§54). Artifact:
`output/ui_score_robustness_audit.json` (script `ui_score_robustness_audit.py`); results
appended to `UI_SCORE_HISTORICAL_VALIDATION.md`.

- **TASK 1**: scorer machinery in MACHINE PARITY between current Engine and the
  reconstruction scorer (growth/prof/market/DQ zero diffs, 271 companies). Valuation
  differences (234 companies, mean |dq| 2.11, max 15.32) trace entirely to the share INPUT
  source (production core.share_structure vs task-directed core.share_intervals:
  195 identical, 1 >1% (خودکفا 25%), 70 rec-missing, 4 prod-missing). Study labelled
  validation of CURRENT_PRODUCTION_SCORE — not historical UI code.
- **TASK 2 survivorship**: all 238 research symbols active today; canonical DB has 0
  delisted primary securities; 0 intra-sample trading stops; new entries 2022-26 are real
  listings (+4/+4/+3/+5/+2); reconstruction per-date symbol sets identical to the frozen
  phase3 grid. The list is PRESENT-DAY (B) at the issuer level: companies delisted during
  2021-26 are absent from the DB entirely — structural upward bias on ABSOLUTE returns,
  unquantifiable from canonical data; cross-sectional ranking result far less sensitive.
- **TASK 3**: PIT rank audit 2021/2023/2025 — within-date recomputed percentiles match
  stored ranks exactly.
- **TASK 4**: coverage 100%/98.4%/96.9%/86.5% at 21/63/126/252d (13,481/13,270/13,056/
  11,654 valid rows).
- **TASK 5 block bootstrap (B=2000, horizon-length blocks)**: IC CI95 [+0.082,+0.141] /
  [+0.122,+0.194] / [+0.134,+0.228] / [+0.099,+0.235] — P(IC<=0)=0.000 all horizons.
  Q5-Q1 CI95: 21d [-0.019,+0.021] (NOT distinguishable from 0) · 63d [+0.016,+0.077]
  (P=0.0005) · 126d [+0.044,+0.166] · 252d [+0.029,+0.316].
- **TASK 6 non-overlapping cohorts**: 63d 17 cohorts meanIC +0.171 pf .94 spread +9.1pp;
  126d 9 cohorts +0.148 pf 1.00 +8.0pp; 252d 5 cohorts +0.126 pf 1.00 +10.4pp; 21d 32
  cohorts +0.101 pf .84 +0.6pp. Direction confirmed everywhere.
- **TASK 7**: strictly monotonic MEANS and MEDIANS Q1<Q2<Q3<Q4<Q5 at 63/126/252d; 21d means
  not monotonic (Q3 dip) but medians monotonic (0.5%->3.7%).
- **TASK 8**: 21d discrepancy explained — mean spread +0.07pp vs median +2.46pp and 1%-
  winsorized mean +2.69pp: extreme outliers cancel the mean; rank IC unaffected. 21d =
  WEAK economically.
- **TASK 9**: observed production score range 2.1-71.9 (p99 52.2); 80+ NEVER occurred —
  the 0-100 scale is not empirically calibrated over its full range.
- **TASK 10**: DQ interaction — pre-DQ IC63 +0.162 / spread +5.7pp vs post-DQ +0.154 /
  +4.9pp: the multiplier slightly HURTS ranking (mainly suppresses dq=0.80 rows);
  diagnostic only, unchanged.
- **TASK 11**: monthly top-quintile turnover 33.6% (66% persist), top-decile 44.1% —
  operationally meaningful stability.

**Verdicts: UI_SCORE_CURRENT_CODE_PARITY = PASS · UI_SCORE_PIT_UNIVERSE_INTEGRITY = PASS
(with the explicit present-day-list survivorship caveat) · UI_SCORE_DEPENDENCE_ROBUSTNESS
= PASS · UI_SCORE_HISTORICAL_RANKING_VALUE = STRONG · 21D = WEAK (real rank signal, ~zero
mean spread) · 63_126D = STRONG · 252D = STRONG.** Plain answer: yes — the higher-scored
of two otherwise eligible stocks was more likely to outperform subsequently, robustly at
63-252d. Statistical ranking value strong at all horizons; economic top-vs-bottom spread
meaningful only at 63d+. Signal Engine still NOT STARTED. STOP.

## 56. Survivorship resolution — gates final (2026-10-02)

Provisional PARTIAL revisions accepted and resolved with market-wide evidence. Method:
bounded Codal enumeration of LetterType=58 monthly activity reports (mandatory for listed
producers) for three probe months — 1400/05, 1402/05, 1404/05 (2021/2023/2025). Raw
responses cached (`output/survivorship_probe/`); scripts `enumerate_codal_issuers.py`,
candidate tables `survivorship_candidates_final.json`, input sensitivity
`ui_score_input_sensitivity.json`.

- LT58 filer population: **618 (2021-07) → 725 (2023-07) → 860 (2025-07); union 914**.
- vs the canonical/research universe: 229 in the 238 list + 33 canonical matches; **651
  filers ABSENT from the canonical DB** (270 operating, 168 investment, 21 insurance,
  13 banks, 11 leasing, 8 financing — مخابرات ایران، بیمه البرز، بورس تهران among them).
- Month patterns: 339 absent filers alive in ALL THREE probes (pure coverage gap);
  **~34 stopped filing during the window (the plausible true-exit set, 3.7% of filers)**;
  155 first filed 1404 (new listings). Verdict: the dominant issue is COVERAGE breadth
  (the canonical universe covers ~29% of market filers), not delisting survivorship.
- The 651 have NO ingested fundamentals → the exact production scorer cannot run for them
  → kept EXPLICITLY MISSING (no invented data; scoring would need a new ingestion
  pipeline, out of scope). Survivorship direction (were disappeared names low-score?)
  UNVERIFIED, not assumed.
- **PHASE 8 input sensitivity** (vendor vs TSETMC share source, as_of 2026-10-01, 271
  companies): score rank corr **0.956**, mean |Δ| 2.11, max 15.32; top-quintile overlap
  86.2%, top-decile 74.2%; movers >2/5/10 points: 71/39/7. Material for individual
  rankings; production source untouched.
- **FINAL GATES: UI_SCORE_SCORER_FORMULA_PARITY = PASS · UI_SCORE_CURRENT_INPUT_PARITY =
  PARTIAL · UI_SCORE_PIT_UNIVERSE_INTEGRITY = PARTIAL · UI_SCORE_DEPENDENCE_ROBUSTNESS =
  PASS · UI_SCORE_HISTORICAL_RANKING_VALUE = STRONG** (within the reconstructed available
  historical universe).
- **FINAL CLAIM (mandated PARTIAL wording): higher UI scores ranked future returns better
  within the reconstructed available historical universe, with residual survivorship
  uncertainty.** Inclusion of later-disappeared equities does NOT materially weaken the
  conclusion (exit set ~34, unscorable without new ingestion); 21d remains economically
  WEAK. Signal Engine NOT STARTED. STOP.

## 57. UI-score current share-source contract FROZEN (2026-10-02)

Final task: single canonical valuation/share source for the UI score. Contract document:
`canonical_postgres_v1_2_1/analytics_canonical_v1/UI_SCORE_CURRENT_SOURCE_CONTRACT.md`.
Evidence: `output/share_source_reconciliation_ui271.json`,
`output/ui_score_canonical_source_recompute.json`,
`output/ui_score_input_sensitivity.json`,
`output/tsetmc_share/nonresearch_instruments.json` (zTitad fetched for the 33 non-research
UI subjects).

- **PHASE 1**: vendor source = `brs_all_symbols` daily snapshot (588 rows / 325 securities,
  as_of 2026-09-29..10-01; Engine gate as_of_date <= as_of AND collected_at <= cutoff; no
  fallback; missing -> valuation penalty). TSETMC: zTitad (live instrument master) +
  GetInstrumentShareChange.numberOfShareNew (chain terminal state).
- **PHASE 2 reconciliation (271 UI subjects)**: vendor vs zTitad — EXACT **266**,
  TSETMC_ONLY 5, **zero count disagreements**. vendor vs latest chain-new — EXACT 242,
  no-chain 23, DIFF_GT_5PCT 1 (خودکفا: cached chain snapshot stale vs live master; vendor
  agrees with zTitad).
- **PHASE 3 decision**: PRIMARY = TSETMC zTitad; CROSS-CHECK = vendor core.share_structure;
  deterministic fallback = vendor when zTitad unavailable; both missing -> existing penalty.
  Criteria all favor zTitad (direct count, live freshness, chain continuity 215/216, after
  the fill 271/271 coverage, current-date semantics).
- **PHASE 4 recompute** (share input substituted, formula untouched, cutoff-corrected
  injection): Spearman vs production **0.9985**, 112 exact, mean |delta| 0.116, top-decile
  overlap **1.0**; only 3 companies move >2 points — ALL GAIN valuation (vendor snapshot
  was missing, zTitad covers them); nobody loses. (First injection run had collected_at >
  cutoff and was rejected by the PIT gate — corrected; nothing was stored to analytics.)
- **PHASE 5 coherence**: 216 open-ended historical chains; **terminal chain == canonical
  current for 215/216**; 55 no-chain companies covered by the current-source rule. No
  unexplained current-vs-history contradiction.
- **PHASE 6 parity**: formula EXACT; input semantics consistent (current = zTitad as the
  chain's live continuation; historical = chain + Codal knowledge); score near-exact;
  valuation gains confined to the 5 previously-valuation-less companies. Deployment =
  next production refresh implements PRIMARY/CROSS-CHECK/FALLBACK in the Engine share
  loader (NOT executed in this task; no analytics writes).
- **PHASE 7 frozen product meaning**: cross-sectional ranking/quality score; historically
  better medium/long-horizon returns within the available universe; NOT a probability,
  expected return, guarantee, or full-range-calibrated (observed 2.1-71.9, 80+ unobserved).
- **PHASE 8 FINAL GATES: UI_SCORE_HISTORICAL_VALIDATION = PASS_WITH_UNIVERSE_CAVEAT ·
  UI_SCORE_CURRENT_SHARE_SOURCE = VALIDATED · UI_SCORE_CURRENT_PRODUCTION_CONTRACT = PASS ·
  UI_SCORE_READY_FOR_PRODUCT_USE = YES · SURVIVORSHIP_EFFECT_ON_FULL_MARKET = UNRESOLVED**
  (per the standing correction: the absent/delisted issuers were never reconstructed or
  scored, and the three-month LetterType=58 filer union is not a definitive market census).
  Signal Engine NOT STARTED. STOP.

## 58. Current share-source contract DEPLOYED and validated on a new run (2026-10-02)

The PIT correction was applied first: the earlier synthetic-cutoff recompute was reclassified
as a counterfactual sensitivity test only — zTitad was actually acquired 2026-10-02 and is
never backdated. Then the approved contract was implemented and deployed:

- **Migration** `sql/119_tsetmc_current_shares.sql`: market.tsetmc_current_shares (real
  collected_at, immutable; registered in run_ddl.py). **Engine**: select_current_shares()
  precedence (PRIMARY TSETMC_ZTITAD_CURRENT with real collected_at <= cutoff; FALLBACK BRS
  core.share_structure; both missing -> existing penalty) wired into load()/compute();
  historical market_pit='trade_date' runs never read the new table (no current-zTitad
  leakage into historical as_of). **Provenance** per subject: share_source,
  share_source_collected_at, share_source_fallback_used, share_cross_check_status.
- **PHASE 7 tests**: 8 regression tests (eligibility before/after cutoff, latest-snapshot
  selection, vendor fallback, both-missing penalty path, disagreement provenance, stamp
  non-mutation, SELECT-only source audit) — all pass; **full canonical suite 188 passed**.
- **Collector** `collect_tsetmc_current_shares.py`: 323/323 instruments fetched with REAL
  collected_at 2026-10-02 14:55:53-15:01:18 Tehran.
- **New versioned analytics run**: `e5998f6d-93ab-4577-b13a-7b2f89c39c02`, as_of 2026-10-02,
  cutoff 15:15+03:30 (> acquisition), --store, 271 companies. In-memory recomputation
  matches the stored run 271/271 exact. (A first attempt without CDF_PILOT_DB connected to
  the migration-pilot DB and failed harmlessly at load() — nothing written.)
- **PHASE 4 reconciliation on the new run**: share_source TSETMC_ZTITAD_CURRENT x271,
  fallback x0; cross-check 266 AGREE + 5 TSETMC_ONLY; collected_at window 14:55:53-15:01:18.
- **PHASE 5 score impact**: old production run (2026-10-01) vs new run: Spearman 0.9977,
  top-quintile overlap 0.964, top-decile 0.929, movers >2/>5/>10 = 5/3/0, mean |delta| 0.177.
  **Source-only at the same new cutoff**: Spearman 0.9984, quintile/decile overlap 1.0,
  movers 3/2/0, mean |delta| 0.116 — the share-source effect is negligible at the current
  date; the small total delta is dominated by the new date's market data.
- **PHASE 6 terminal-chain consistency**: EXACT 247 · NO_CHAIN 23 ·
  CURRENT_NEWER_THAN_CHAIN 1 (خودکفا — live master fresher than the cached chain, correctly
  classified, never treated as a historical fact) · CONFLICT 0.

**FINAL GATES: UI_SCORE_CURRENT_SHARE_SOURCE = VALIDATED ·
UI_SCORE_CURRENT_PRODUCTION_CONTRACT = PASS · SOURCE_CONTRACT_DEPLOYED = YES ·
PIT_BACKDATING_PRESENT = NO · UI_SCORE_READY_FOR_PRODUCT_USE = YES ·
UI_SCORE_HISTORICAL_VALIDATION = PASS_WITH_UNIVERSE_CAVEAT (unchanged) ·
SURVIVORSHIP_EFFECT_ON_FULL_MARKET = UNRESOLVED (unchanged).** Score formula, DQ, weights,
and thresholds untouched. Signal Engine NOT STARTED. STOP.

## 59. NEW TRACK — Signal Engine preregistered (design only; nothing executed) (2026-10-02)

Separate research track opened after the UI-score validation chain closed (§54-§58). The
UI score stays frozen and READY FOR PRODUCT USE; the Signal Engine answers a DIFFERENT
question — entry-timing favorability given an otherwise attractive stock — and is NOT a
rename of the UI score.

- **Frozen artifact**: `signal_engine/SIGNAL_ENGINE_PREREGISTRATION_V1.md` (+ input
  inventory `signal_engine/input_inventory.json` over the frozen grid, inventory-only — no
  signals/ICs/returns computed).
- **Objective/targets**: PRIMARY 63-trading-day forward adjusted EXCESS return vs the
  same-date equal-weight eligible universe; SECONDARY 126d; 21d diagnostic; monthly cadence;
  pClosing + validated adjustment pipeline; 252d explicitly NOT a target.
- **Allowed inputs** (inventory measured): mom 20/30/60/90, dist_high60, drawdown_60,
  vol_30, downside_vol_30 (97.5-100%), liq_30 (57.3% — FEATURE ONLY, no eligibility cutoff),
  market breadth/dispersion/vol level (99.9%, ex-ante demonstrated), frozen UI score + 4
  category scores (100%). No external macro, no new datasets, no future regime labels.
- **Architectures (exactly two)**: A = score + timing overlay (PREFERRED — interpretable,
  low overfit risk, sticky underlying layer); B = unified signal rank (alternative). First
  experiment: 1 primary + max 2 ablations; no weight search/feature mining/grid search.
- **Gates SG1-SG8 frozen with rationale** (anchored to the measured UI baselines): IC63(excess)
  >= +0.05; pf >= 0.60 and positive in >=5 of 6 years; Q5-Q1 excess >= +2pp with bootstrap CI
  excluding 0; IC CI excluding 0; **incremental (decisive): delta-IC63 >= +0.02 AND
  delta(Q5-Q1 excess) >= +1.0pp vs the UI score on identical dates/universe**; turnover <= 0.50;
  coverage >= 85%; all leakage tests L1-L6 + no PIT violation. Thresholds frozen BEFORE
  execution, anchored to the measured baselines (UI IC63 0.154, Q5-Q1 +4.9pp, turnover 0.336).
- **Evaluation design**: Dev 2021-23 may inform design within limits; 2024-2026 =
  EXPLORATORY_HISTORICAL; true confirmation = shadow protocol (>=12 future monthly dates,
  frozen logic, no replacement, no early promotion). SIGNAL_RESEARCH_READY vs
  SIGNAL_PROMOTION_READY distinguished; only PROMOTION_READY authorizes production
  recommendations.
- **Product boundary**: UI score remains visible and unchanged; research labels
  (FAVORABLE/NEUTRAL/UNFAVORABLE) are never exposed to users.
- Unresolved blockers carried: survivorship/universe (UNRESOLVED; not a definitive census),
  liq_30 coverage 57.3%, 21d economically weak (no 21d claims).

**FINAL OUTPUTS: UI_SCORE_STATUS = READY · SIGNAL_ENGINE_PREREGISTERED = YES ·
SIGNAL_ENGINE_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO · SIGNAL_RESEARCH_READY = YES ·
SIGNAL_PROMOTION_READY = NO.** STOP after preregistration per the task order.

## 60. Signal V1 exact experiment specification FROZEN (2026-10-02)

The preregistration amendment (Parts E1-E13) is appended to
`signal_engine/SIGNAL_ENGINE_PREREGISTRATION_V1.md` and hash-frozen BEFORE execution,
without inspecting any Signal Engine return outcome.

- **Frozen hash (SHA-256): 149ba4afd112f63443316a986ac793af60a60f572e13cf446850a6dcea3859ae**
- Frozen: `signal-v1-A` (UI-Q5 attractiveness universe [descending UI score, Q5 =
  rs[4*floor(n/5):n]]; timing-eligible = all 3 features present; TIMING_CORE = 1/3
  Momentum60Rank + 1/3 DistanceFrom60DayHighRank + 1/3 InverseVolatility30Rank, midranks
  within the timing-eligible UI-Q5; FINAL_SIGNAL_RANK_A = rank of TIMING_CORE) · ablation
  `signal-v1-A-momentum` (1/2 Momentum60Rank + 1/2 DistanceFrom60DayHighRank) · alternative
  `signal-v1-B` (0.50 UI_RANK + 0.50 TIMING_CORE on the full signal-eligible universe).
- Frozen: baselines on IDENTICAL universes (A: UI rank within timing-eligible UI-Q5; B: UI
  rank within full signal-eligible), Q1/Q5 semantics per architecture, excess target vs the
  FULL base product universe, SG2b amended to 4-of-5 full years (2021-2025; 2026
  descriptive), E10 turnover convention (1 - |prev ∩ cur| / |prev|; SG6 uses mean), E11
  bootstrap (seed 20261002, B=2000, blocks 3/6 monthly dates for 63/126d, date-level unit),
  E12 leakage tests L1-L7 (implemented with the pipeline build), E13 liq_30 NOT in V1.
- If `signal-v1-A` fails SG1-SG8: SIGNAL_V1_PRIMARY_GATE = FAIL; A-momentum/B are NOT
  auto-promoted; any primary switch requires a NEW preregistration.
- **SIGNAL_RESEARCH_READY returns to YES**: the exact spec is frozen with a recorded hash,
  and the L1-L7 leakage tests are specified for implementation with the pipeline build.

**Status: UI_SCORE_STATUS = READY · SIGNAL_ENGINE_PREREGISTERED = YES ·
SIGNAL_V1_EXACT_SPEC_FROZEN = YES · SIGNAL_ENGINE_EXECUTED = NO · SIGNAL_ENGINE_STARTED =
NO · SIGNAL_RESEARCH_READY = YES · SIGNAL_PROMOTION_READY = NO ·
SURVIVORSHIP_EFFECT_ON_FULL_MARKET = UNRESOLVED.** STOP — no execution in this task.

## 61. SIGNAL V1 EXECUTED once — PRIMARY GATE = FAIL, no shadow eligibility (2026-10-02)

Executed EXACTLY once under preregistration hash 149ba4af... (verified PASS before any run).
Pipeline split per the frozen structural separation: `build_signal_v1_snapshot.py`
(construction only; NO outcome-source references; snapshot frozen+hashed BEFORE outcomes)
then `evaluate_signal_v1.py` (outcome attach + SG1-SG8). Artifacts:
`signal_engine/output/signal_v1_snapshot.jsonl` (2,797 rows, SHA-256
4719eced10fde8f5bcb030764fd11c1acee41671429a0018a8cd7bcd7aca472a),
`signal_v1_integrity.json`, `signal_v1_results.json`.

- **Leakage L1-L7: ALL PASS** (structural separation enforced: construction source contains
  zero outcome/current-share references; L5/L6 drop-later invariance verified on 3 dates x
  40 names; snapshot has no outcome columns).
- **Coverage (SG7 PASS)**: UI-Q5 rows 2,797; timing-eligible 2,733 (**97.71%**); missing
  Momentum60 64 / DistanceFrom60DayHigh 64 / Volatility30 61.
- **PRIMARY signal-v1-A (63d excess, 62 dates, 2,733 rows)**: mean IC **+0.0548** (SG1 PASS
  by 0.0048) · positive fraction **0.581** (SG2a FAIL) · annual IC63: 2021 +0.090,
  2022 -0.076, 2023 -0.006, 2024 +0.167, 2025 +0.088 -> **3 of 5 full years (SG2b FAIL)** ·
  **Q5-Q1 mean excess -0.20pp / median -0.92pp (SG3 FAIL - negative)** · bootstrap IC CI95
  [-0.018, +0.122] (SG4 FAIL) · Q5-Q1 excess by date mean -0.20pp (SG3) · mean |delta| small.
- **SG5 (decisive) FAIL**: Delta IC63 = **-0.0074** (timing UNDERPERFORMED the UI baseline on
  identical rows); Delta Q5-Q1 excess = +0.12pp (< +1.0pp). Baseline (UI rank, identical
  rows): IC63 +0.0622, pf 0.645, Q5-Q1 excess -0.32pp.
- **SG6 FAIL**: mean top-timing-quintile turnover **0.633** > 0.50 (median 0.625, p90 0.875).
- **Ablation A-momentum** (no inverse vol): IC63 +0.032, pf 0.613, spread -0.54pp, turnover
  0.651 -> inverse volatility HELPED relative to momentum-only (A 0.055 > 0.032) but neither
  passes anything.
- **Architecture B**: IC63 +0.064, pf 0.645, Delta IC63 vs identical-row UI baseline
  **+0.0018** (no increment), spread -0.15pp, turnover 0.606. B is the UI score diluted by
  half-weight timing; no improvement over the cleaner A architecture.
- **126d secondary**: A +0.085 (pf 0.705) but Q5-Q1 spread -2.96pp · B +0.095 / -3.31pp —
  no rescue. **21d diagnostic**: A +0.036, spread -1.03pp — no rescue.
- Interpretation: within the top-attractiveness quintile, chasing 60d momentum/proximity-to-
  highs ADDS TURNOVER WITHOUT PAYOFF at 63d (Q5 mean excess NEGATIVE; Q1 best of all five on
  means) — momentum among good companies mean-reverted at this horizon in this market.
  Consistent with the recorded LowVolatility/momentum instability diagnostics. The UI score
  alone remains the ranking instrument.

**FINAL: SIGNAL_ENGINE_EXECUTED = YES · SIGNAL_V1_PRIMARY_GATE = FAIL ·
SIGNAL_V1_SHADOW_ELIGIBLE = NO · SIGNAL_PROMOTION_READY = NO · SIGNAL_ENGINE_STARTED = NO ·
UI_SCORE_STATUS = READY (unchanged) · SURVIVORSHIP_EFFECT_ON_FULL_MARKET = UNRESOLVED.**
Per the frozen stop rule: no Signal V2, no redesign, no rescue by A-momentum/B; any future
timing research requires a NEW preregistration with a different economic mechanism. STOP.

## 62. Product state FROZEN — Signal V1 closed, product spec created (2026-10-02)

- **Signal V1 formally closed**: `signal_engine/SIGNAL_V1_CLOSEOUT.md` (SIGNAL_V1_FINAL_STATUS
  = FAIL; primary IC63 +0.0548, pf 0.581, Q5-Q1 excess -0.20pp, Delta IC63 -0.0074, Delta
  spread +0.12pp, turnover 0.633, coverage 97.71%; SG1/SG7/SG8 PASS, SG2a/SG2b/SG3/SG4/SG5/SG6
  FAIL). Interpretation corrected per the accepted language: the preregistered 60d-momentum /
  60d-high-distance / inverse-30d-vol combination did not provide robust incremental timing
  value beyond the UI score in the available historical universe; the highest timing quintile
  did not outperform the lowest. NO causal regime claim. Artifacts preserved (prereg hash
  149ba4af..., snapshot 4719eced..., results, validation, contract). SIGNAL_RESEARCH_PAUSED =
  YES; resumption only with a genuinely different economic mechanism + new preregistration.
- **Product boundary frozen**: no mechanical BUY/HOLD/SELL conversion of the UI score; no
  "score >= X => BUY" or "top quintile => BUY" rules; the historical evidence supports
  ranking only.
- **Product spec created**: `product/UI_SCORE_PRODUCT_SPEC.md` — score meaning, category
  contributions, DQ role, higher/lower semantics, frozen historical evidence, limitations,
  explanation contract (top-3 positive / top-3 weak drivers from the existing decomposition,
  deterministic, no generated conclusions), descriptive bands anchored to the CURRENT run
  distribution (LOW <24.5 / BELOW AVERAGE 24.5-30.7 / AVERAGE 30.7-38.0 / ABOVE AVERAGE
  38.0-48.2 / HIGH >48.2; percentile-labels alternative documented; distribution-based
  only, no deployment), historical-context display decision (allowed with mandatory
  available-universe + not-a-guarantee + no-probability caveats), and the binding
  allowed/prohibited UI wording policy (Persian examples included).
- **Status: UI_SCORE_STATUS = READY · UI_SCORE_PRODUCT_SPEC_READY = YES · SIGNAL_V1_CLOSED
  = YES · SIGNAL_RESEARCH_PAUSED = YES · SIGNAL_ENGINE_STARTED = NO · SIGNAL_PROMOTION_READY
  = NO · DATA_INTEGRITY_BLOCKERS_CLOSED = YES · SURVIVORSHIP_EFFECT_ON_FULL_MARKET =
  UNRESOLVED.** STOP.

## 63. Research bundle for external review — READY (2026-10-02)

Self-contained bundle at `research_bundle/` (27 MB): monthly_pit_panel.parquet (13,409 x 97),
daily_market_panel.parquet (837,525 x 15, zstd), event_panel.parquet (20,348),
market_state_daily.parquet (6,163 daily rows, equal-weight covered-universe state),
outcomes.parquet (13,409; SEPARATE from features; 21/63/126/252d adjusted + excess),
DATA_INVENTORY.md (full field inventory incl. UNUSED_OR_UNDERUSED_DATA + provenance flags),
DATA_DICTIONARY.md, COVERAGE_SUMMARY.csv + COVERAGE_BY_YEAR.csv, FEATURE_PROVENANCE.csv
(94 columns: 59 used-in-UI, 6 robust-six/V2, 3 Signal V1, 35 NEVER_USED), README, and
references/ (UI validation, Signal V1 closeout + prereg, share-source contract, product
spec, return-path audit). Builder: historical_codal_backfill/build_research_bundle.py.

Inventory findings for the next-hypothesis decision: share volume UNAVAILABLE in the TSETMC
historical endpoint (null everywhere; trade count + trade value ARE stored); official index
series NOT stored (7 pilot rows); liquidity_30 57.3%; sales-growth features ramp 0->69% with
the monthly-activity backfill; PE/PS/PB ramp 52->76% with the share path; ocf_ttm not
materialized in the frozen artifact (derivable via Engine re-run); NEVER_USED inventory
includes return_5d/10d/120d, mom_20/90, vol_10/20/60, downside vol, drawdown_20/120,
120d-high distance, 20d/60d-low distance, liquidity_20/60, trade_count, market-state
variables, daily open/high/low/priceYesterday/priceChange, baseVol/market classification
(current-only). Outcomes kept SEPARATE from features; bundle contains NO research results.
RESEARCH_BUNDLE_READY = YES. STOP.

## 64. Research bundle REPAIRED and re-exported — v2 (2026-10-02)

External review found bundle-integrity defects; all repaired and documented in
`research_bundle/BUNDLE_INTEGRITY_AUDIT.md`. Builder:
`historical_codal_backfill/repair_research_bundle.py`.

1. **Outcomes (critical)**: the v1 bundle's fwd helper divided the corporate-action FACTOR
   chain (a1/a0-1 = 0 whenever no event fell in the window — 89% of 21d, ~2/3 of 63d
   windows; فولاد 2021-01-31 63d = 0.0). Rebuilt as ADJUSTED PRICE returns
   (adjp[exit]/adjp[entry]-1; adjp = pClosing x cumulative CONFIRMED factors) — identical
   to the validated ui_score_historical_v1 implementation. **Parity: IC21 +0.1103, IC63
   +0.1543, IC126 +0.1806, IC252 +0.1571 — reproduces the frozen UI validation.**
2. **13,409 vs 13,481**: all 72 dropped rows = raw TSETMC cache depth (no row on/before the
   signal date for late-listed names) — accidental loss, repaired; monthly panel now
   13,481 rows x 102 cols (72 repaired rows carry UI outputs with NULL price features).
3. **UI quintile convention**: bundle used DESCENDING (Q1 = highest); canonical convention
   frozen as ASCENDING (Q1 = lowest, Q5 = highest; verified against the validated
   ui_score_historical_analysis.py sort and the IC sign); ui_rank retained.
4. **Daily identities**: security_id 837,525/837,525 non-null via core.securities; 238
   symbols / 238 ids / 0 conflicts. Trade-activity flags added: security_traded,
   zero_trade_reason (traded / market_closed_no_covered_trades / no_trade_unknown —
   فولاد's 2026 zero stretches = carried-price no-trade rows, classified, not synthesized).
5. **Event panel**: financial-statement events RESTORED (8,157 — the v1 statements query
   contributed 0 rows due to a join defect); all classes mapped company -> primary
   security (8,157 + 12,180 mapped, 0 unmapped); total 28,508 rows.
6. **Event-timing audit**: financial_report published_at 595/8,157 (7.3%, Codal-ingested
   subset); monthly_sales_report 0/12,180 (legacy migration carries period_end only —
   EVENT_TIMING_PIT_READY = NO for this class); LT28 1,158/1,158 (jalali PublishDateTime
   converted to UTC); corporate actions = ex-date only.
7. **Reproduction test**: 50 samples x 4 horizons on the CANONICAL trading calendar —
   **191/191 values reproduce exactly** (the v1 check's 57 mismatches were its own
   daily-panel-date-set calendar, incl. non-trading placeholder rows — fixed);
   فولاد 2021-01-31 63d = +0.077447 from both paths. First test run's 57 "mismatches"
   were calendar mismatches, not value errors — classified in repair_audit trail.
8. Independent review finding recorded (QUALITY PULLBACK REVERSAL, IC63 -0.019, unfavorable)
   — not acted on, no V2.

**Repackage: research_bundle_v2_for_review.zip — 14.46 MB, 20 files, SHA-256
8dd9dc2ae5425f4a256f223ac1f90dde1aec6a34197a16a3095e596c391b30a6.**

**GATES: RESEARCH_BUNDLE_V2_READY = YES · OUTCOME_PARITY = PASS · MONTHLY_GRID_PARITY =
PASS · UI_QUINTILE_SEMANTICS = PASS · DAILY_IDENTITY_MAPPING = PASS ·
EVENT_IDENTITY_MAPPING = PASS · EVENT_TIMING_PIT_READY = PARTIAL ·
TRADE_ACTIVITY_SEMANTICS = VALIDATED.** Product boundary unchanged (UI score READY, no
signal in product, SIGNAL_RESEARCH_PAUSED = YES). STOP.

## 65. Event-timing readiness — monthly YES, financial PARTIAL, fundamental-event signal FEASIBLE (2026-10-02)

Data/event-time preparation ONLY. No returns analyzed, no signals built. Artifacts:
`research_bundle/event_stream_pit.parquet` (11,909 publication rows), `matching_audit.json`,
`EVENT_TIMING_READINESS.md`, `reproduction_test.json` (191/191 canonical-calendar parity).

- **PART 1 metadata fixes**: README counts (13,481/28,508), liquidity coverage corrected to
  truthful qTotCap-ramp values (liq_20 69.6%, liq_30 57.0%, liq_60 36.6%), market-state
  columns (breadth/dispersion/vol_level) materialized into the monthly panel from raw
  caches (100% coverage), DATA_DICTIONARY quintile convention corrected to ascending
  (Q1 = lowest, Q5 = highest).
- **PART 2 identity audit**: `ingestion.reports` carries tracing_no/letter_type/title/
  source_url — the identity keys needed for per-symbol recovery. 275 companies have
  Codal-sourced reports. Legacy-migrated reports (19,081 + 12,180 monthly) have none.
- **PART 3 backfill**: per-symbol Codal search (LetterType 58 + 6, window 1400/01/01–
  1405/07/01) over all 238 covered symbols: **474 fresh fetches, 0 failures, ~55 min**.
  Raw responses cached. **27,497 unique letters recovered** with real PublishDateTime
  (jalali → UTC), TracingNo, Title, Url.
- **PART 4 matching**: monthly — MATCH_STRONG 7,487 + MATCH_STRONG_CORRECTION 2,128 +
  AMBIGUOUS 6 + NOT_FOUND 2,559 (symbol + jalali period-end from title, deterministic).
  financial — MATCH_EXACT 595 (already had real published_at) + MATCH_STRONG 2,416 +
  MATCH_STRONG_CORRECTION 399 + AMBIGUOUS 2,665 (consolidated/standalone variants) +
  NOT_FOUND 2,082.
- **PART 5 PIT provenance**: published_at = REAL Codal stamp (jalali → UTC); collected_at =
  backfill acquisition time (2026-10-02); knowledge gate = published_at ≤ cutoff.
  collected_at is lineage only.
- **PART 6 coverage**: monthly — 9,615/12,180 = 78.9% with real publication times, 164
  symbols, every year 2021–2026 covered. financial — 3,410/8,157 = 41.8%; the gap is
  AMBIGUOUS (2,665: multiple letter variants per period) + NOT_FOUND (2,082).
- **PART 7 corrections**: preserved as separate stream rows (2,128 monthly + 399 financial
  MATCH_STRONG_CORRECTION); original stays the knowledge time; 4 superseding reports in
  the whole canonical window — corrections are NOT sufficiently represented for standalone
  correction-event research.
- **PART 8 event_stream_pit**: 11,909 publication rows (monthly 11,743 + financial 166
  matched-strong rows in the stream; the financial MATCH_EXACT 595 retain their original
  published_at in the canonical data). Each row: published_at (real), security_id, symbol,
  event_type, period_end, is_correction, sales/revenue/net_profit/operating_profit/EPS
  where canonical, match_status, source identifiers.
- **PART 9 feasibility**: FUNDAMENTAL_EVENT_SIGNAL_FEASIBLE = YES — the monthly sales path
  (9,615 real-publication events, 164 symbols, 2021–2026) supports all four PIT-safe
  constructions (pre-publication state, newly published info, deterministic revision vs
  prior publication, post-publication signal timestamp). The financial path is PARTIAL
  (41.8% with real pub times; the AMBIGUOUS financial events need variant resolution).
- **PART 10**: UI-score delta explicitly excluded from the first event hypothesis (mixes
  fundamental with price movement).
- **PART 11**: trade-activity path preserved as secondary (buyer/seller direction and
  historical volume unavailable).

**FINAL GATES: MONTHLY_REPORT_EVENT_TIMING_READY = YES · FINANCIAL_REPORT_EVENT_TIMING_READY
= PARTIAL · FUNDAMENTAL_EVENT_SIGNAL_FEASIBLE = YES · BUNDLE_METADATA_CONSISTENCY = PASS ·
SIGNAL_V2_CREATED = NO · SIGNAL_RESEARCH_EXECUTED = NO · SIGNAL_PROMOTION_READY = NO ·
UI_SCORE_STATUS = READY.** STOP.

## 66. FUNDAMENTAL EVENT V1 PREREGISTERED — design only, nothing executed (2026-10-02)

New research family opened: FUNDAMENTAL EVENT / POST-PUBLICATION REPRICING. Separate from
Signal V1 (timing overlay) and the UI score (cross-sectional quality ranking).

- **Artifact**: `fundamental_event_research/FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md`
- **Pre-outcome feasibility** (PART 15, `fundamental_event_feasibility.py` →
  `research_bundle/fundamental_event_feasibility.json`): 11,743 monthly events with real
  published_at + valid sales; 11,489 eligible with valid acceleration; 278 qualifying
  dates (≥10 events); 9,810 events on qualifying dates; 164 symbols; FE1 PASS; FE8
  concentration PASS (max security 0.9%, max year 20.7%).
- **Frozen feature**: SALES_GROWTH_ACCELERATION = SALES_YOY_CURRENT − SALES_YOY_PREVIOUS
  (YoY monthly sales growth change between consecutive publications). PRIMARY candidate:
  `fundamental-event-v1-acceleration`. Ablation: `fundamental-event-v1-level` (YoY level
  only). No other features.
- **Gates FE1–FE8 frozen with rationale** (anchored: FE2 +0.05 = UI validation floor;
  FE3 0.60; FE4 +2.0pp = 40% of UI full-universe spread; FE5 bootstrap CIs; FE6 +0.02 /
  +1.0pp incremental; FE6 turnover N/A for events; FE7 leakage E1–E8; FE8 concentration).
  Bootstrap: seed 20261003, B=2000, 63d block = 3 months.
- **Leakage tests E1–E8 frozen** (real publication time, entry after publication, correct
  period matching, prior-year availability, previous-publication-only YoY, corrections
  don't overwrite, date isolation, outcome separation).
- **Pre-outcome sample**: `research_bundle/fundamental_event_pre_outcome_panel.parquet`
  (11,743 events with features, eligibility, entry dates, YoY values).
- **FINAL: FUNDAMENTAL_EVENT_PREREGISTERED = YES · FUNDAMENTAL_EVENT_EXACT_SPEC_FROZEN =
  YES (SHA-256 recorded below) · FUNDAMENTAL_EVENT_EXPERIMENT_FEASIBLE = YES ·
  FUNDAMENTAL_EVENT_EXECUTED = NO · FUNDAMENTAL_EVENT_SHADOW_ELIGIBLE = NO ·
  SIGNAL_ENGINE_STARTED = NO · SIGNAL_PROMOTION_READY = NO.** STOP.

## 67. EVENT-STREAM INTEGRITY AUDIT — monthly PASS, panel defects found and repaired, preregistration READY (2026-10-03)

FINAL pre-registration gate per handoff. Independent audit script
`fundamental_event_research/audit_event_stream_v1.py` (re-implements the deterministic
matcher from scratch; NO returns, NO ICs, NO outcome access). Report:
`fundamental_event_research/EVENT_STREAM_INTEGRITY_AUDIT.md` +
`event_stream_audit.json`. No threshold changed; nothing tuned.

- **Monthly reconciliation 9,615 vs 11,743 — RESOLVED, legitimate**: 9,615 = 7,487
  MATCH_STRONG + 2,128 MATCH_STRONG_CORRECTION canonical events; the stream's extra rows
  were the corrections' own publication rows (2,128 latest-correction rows). Row-by-row
  proven. Independent matcher reproduces frozen stats exactly (6 AMBIGUOUS, 2,559
  NOT_FOUND).
- **Financial 3,410 vs 166 — RESOLVED as a construction DEFECT**: `match_pub_times.py`
  never emitted financial original rows; the 166 rows exist only via loop-state leak
  (all 166 share ONE constant published_at = the last monthly letter's stamp; canonical
  report UUIDs as source_report_id). Financial stream section QUARANTINED (not deleted);
  financial event timing stays PARTIAL; financial stream rebuild = future task. Does not
  affect the monthly-only preregistration.
- **Defects found in the previous pre-outcome artifacts (both repaired here)**:
  (a) `fundamental_event_feasibility.py` prior-year lookup was NOT restricted to the
  event's company → every SALES_YOY_* / acceleration value in
  `research_bundle/fundamental_event_pre_outcome_panel.parquet` is invalid (median YoY
  +3.22, p99 +3,069 — impossible); PART 15 measured counts were wrong.
  (b) the old stream carried only 2,128 of **2,568** correction letters (dropped 440
  publications) and used a fixed +03:30 tz → 1,809/11,743 UTC instants 1h late inside
  Iran's 2021/2022 DST windows (entry dates unaffected — date-based rule).
- **Canonical artifact created**:
  `fundamental_event_research/monthly_sales_events_pit.parquet` — 12,183 publication
  rows (9,615 originals + 2,568 corrections), one row per actual Codal publication,
  0 duplicate tracing_no, 100% resolvable in the raw backfill cache, corrections never
  overwrite originals (0 order violations; 69 same-day), zone-correct UTC + Tehran local +
  raw jalali retained. SHA-256
  `15d39e5389dc47de82d89d62d18debfc272d88bcbda5ca95f05a886d6fadefdf`.
- **Pre-outcome features rebuilt (frozen formulas, same-company comparators)**:
  SALES_CURRENT · SALES_SAME_MONTH_PRIOR_YEAR · SALES_YOY_CURRENT (median +0.458 —
  plausible) · SALES_YOY_PREVIOUS (strict immediate predecessor) ·
  SALES_GROWTH_ACCELERATION (median +0.002) · 3-publication trajectory availability flag
  (feasibility only). Entry rule frozen: first canonical trading date strictly AFTER the
  Tehran publication date (E2: 9,615/9,615 exact). Corrections excluded as events
  (`CORRECTION_VALUE_UNAVAILABLE` — corrected values were never ingested; value-fidelity
  determination, not a threshold change).
- **Corrected pre-outcome counts (supersede invalid PART 15 numbers; gate thresholds
  unchanged)**: 8,270 eligible events · 161 symbols · 230 qualifying dates (≥10) · 7,662
  events on qualifying dates · max security share 0.77% (≤5%) · max year share 21.93%
  (≤30%). FE1 pre-check PASS · FE8 pre-check PASS. E4: 7,458 verified + 812
  unrecoverable-but-flagged (0 hard violations; 0/9,451 sequence-order violations).
- **Preregistration untouched**: `FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md` SHA-256
  `5dff31d525a58b6474d06956eab5abff5a93ff898f3571358ac0d3b637c66fd1` (design, formulas,
  gates FE1–FE8, bootstrap settings, E1–E8 unchanged; measured counts corrected by the
  audit report).

**FINAL GATES: MONTHLY_EVENT_STREAM_INTEGRITY = PASS ·
MONTHLY_EVENT_TIMESTAMP_INTEGRITY = PASS · MONTHLY_EVENT_COVERAGE = PASS ·
MONTHLY_FUNDAMENTAL_REVISION_FEATURES_READY = YES ·
FUNDAMENTAL_EVENT_PREREGISTRATION_READY = YES · FUNDAMENTAL_EVENT_EXECUTED = NO ·
SIGNAL_V2_CREATED = NO · SIGNAL_ENGINE_STARTED = NO · SIGNAL_PROMOTION_READY = NO ·
UI_SCORE_STATUS = READY.** STOP — awaiting explicit instruction to execute
`fundamental-event-v1-acceleration` under the frozen preregistration.

## 68. FUNDAMENTAL EVENT V1.1 PREREGISTERED — superseding pre-execution correction (2026-10-03)

External review found material spec/sample inconsistencies in V1.0. No outcomes had been
inspected → clean pre-execution correction. **V1.0 file+hash preserved immutable
(5dff31d525a58b6474d06956eab5abff5a93ff898f3571358ac0d3b637c66fd1); NOT edited, NOT
deleted.**

- **New binding spec**: `fundamental_event_research/FUNDAMENTAL_EVENT_V1_PREREGISTRATION_V1_1.md`
  — **SHA-256 c1dacaf19377c5c8f89fd15d9ed782aef5db84317b2d90031cc42d31c543d9d4** (the ONLY
  binding execution specification).
- **Issue 1 — UI-Q5 eligibility REMOVED**: primary universe = ALL PIT-ready eligible
  monthly-sales publication events; UI score is ONLY the identical-row baseline
  (PIT source frozen: monthly_pit_panel.parquet, latest signal_date ≤ entry date). Any
  UI-conditioned variant forbidden in V1.1.
- **Issue 4 — previous-DISTINCT-period semantics frozen**: SALES_YOY_PREVIOUS from the
  previous distinct monthly period (latest version whose published_at ≤ current event
  time); same-period corrections structurally excluded as predecessors (EI6).
- **Issue 5 — comparator PIT-knownness frozen**: PUB_VERIFIED (latest pub ≤ event time) /
  PRE_WINDOW (period before the 1400/01/01 search-window start) only; otherwise
  ineligible. Corrected-period ORIGINALS excluded (EI5: current-value version
  unverifiable — 2,123 events).
- **Issue 6 — corrections**: 2,568 separate publication rows preserved
  (is_correction, supersedes_event_id, original_event_id); corrected VALUES are not in
  the canonical store → rows carry NULL sales, 0 eligible (frozen semantic kept; data
  limitation documented; recovery is future work).
- **Issue 3 — reconciliation EXACT**: 12,180 canonical monthly rows = 9,615 recovered +
  6 AMBIGUOUS + 2,559 NOT_FOUND; stream = 12,183 publications = 9,615 originals + 2,568
  corrections; 12,183 unique tracing_nos; 0 duplicates; 0 letters mapped to multiple
  canonical rows; 2,128 multi-publication periods (all correction semantics). Old 11,743
  = 9,615 + 2,128 latest-correction rows (440 earlier corrections had been dropped).
  EVENT_STREAM_UNIQUENESS = PASS.
- **Issue 2 — corrected primary universe (FE1/FE8 recomputed; thresholds unchanged)**:
  6,091 eligible acceleration events · 203 qualifying dates (≥10) · 5,442 events on
  qualifying dates · 160 symbols · years 556/962/1,213/1,327/1,268/765 · max symbol
  concentration 1.03% (دفرا) · max year 21.79% (2024). FE1 PASS, FE8 PASS.
- **Issue 13 — EI1–EI8 all PASS** (one row per publication; no unexplained duplicates;
  real publication times incl. DST-correct UTC; entry strictly after publication date;
  PIT-known current + comparators; distinct earlier previous period; corrections preserve
  knowledge; outcomes physically inaccessible to construction code).
- Evidence: `build_event_universe_v1_1.py` · `event_universe_v1_1.json` ·
  `monthly_sales_events_universe_v1_1.parquet` (SHA-256 bcd69f109fd1a3be…, full hash in
  JSON). Outcome contract + FE2–FE8 thresholds + bootstrap settings retained verbatim.

**FINAL: OLD_PREREGISTRATION_PRESERVED = YES · EVENT_STREAM_COUNT_RECONCILED = YES ·
EVENT_STREAM_UNIQUENESS = PASS · PREVIOUS_PERIOD_SEMANTICS = PASS ·
CORRECTED_PRIMARY_UNIVERSE = PASS · FE1_PREOUTCOME = PASS · FE8_PREOUTCOME = PASS ·
FUNDAMENTAL_EVENT_V1_1_PREREGISTERED = YES · FUNDAMENTAL_EVENT_V1_1_EXACT_SPEC_FROZEN =
YES · FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO ·
SIGNAL_PROMOTION_READY = NO · UI_SCORE_STATUS = READY.** STOP — awaiting explicit
execution instruction.

## 69. V1.2 PRE-EXECUTION GATES — arithmetic/timestamps/dedup PASS; PRE-EVENT UI BASELINE NOT PROVABLE → NO V1.2 (2026-10-03)

Three final pre-execution ambiguities audited against the FROZEN V1.1 artifact (read-only;
`audit_prereg_gates_v1_2.py` → `event_universe_v1_2_gates.json`; NO outcomes/returns/ICs).

- **EVENT_COUNT_ARITHMETIC = PASS (Issue 1)** — from the artifact: 12,183 rows = **9,615
  originals + 2,568 corrections** (sum exact); 12,183 unique tracing_no; 9,615 unique
  security-periods; 2,128 multi-publication periods; corrections/period = 1×1,762, 2×309,
  3×43, 4×11, 5×3. Chain exact: 9,615 canonical periods + 2,128 latest-correction rows +
  **440 earlier correction letters** = 12,183. The "9,618 originals" in the 2026-10-03 chat
  summary was a reporting typo; the frozen V1.1 MD and the artifact both say 9,615.
- **EVENT_TIME_NORMALIZATION = PASS (Issue 6)** — binding V1.1 artifact re-verified row
  by row against the raw Codal cache: 0 incorrect UTC rows, 0 incorrect Tehran wall/date
  rows, 0 incorrect signal-entry rows; raw jalali preserved. The 1,809-row +1h DST defect
  exists ONLY in the quarantined legacy `research_bundle/event_stream_pit.parquet`.
  current_incorrect_timestamp_rows = 0.
- **ONE_SECURITY_PER_SIGNAL_DATE = PASS (Issue 4)** — 6 duplicate (entry-date × security)
  groups / 18 rows among 6,091 eligible events, all caused by consecutive monthly
  publications entering on the same trading day. Deterministic pre-outcome rule applied:
  keep the latest published_at per group; 0 exact-timestamp ties (tracing_no tie-break not
  applicable — different-period originals are not revisions). 12 rows dropped → 6,079.
- **Final counts (Issue 5; V1.1 eligibility + dedup rule; FE1/FE8 thresholds unchanged)**:
  6,079 eligible acceleration events · 390 unique signal-entry dates · 203 qualifying
  dates (≥10) · 5,441 events on qualifying dates · 160 symbols · max symbol 1.04% ·
  max year 21.78% · FE1 PASS · FE8 PASS.
- **PRE_EVENT_UI_BASELINE_PIT_READY = NO (Issues 2–3) → NO V1.2 spec created.** The UI
  panel (`monthly_pit_panel.parquet`) preserves only month-end `signal_date` (as_of); it
  has NO per-snapshot knowledge-cutoff column, and its documented legacy-input rule is
  `period_end ≤ as_of` (DATA_INVENTORY line 111). Under the candidate mapping (latest
  signal_date strictly before publication): 6,024/6,079 events would have a baseline
  (55 lost), median age 27d (p75 28, p90 52.7, max 213; ≤31d 89.3%, 32–62d 6.2%,
  >62d 4.5%), and **96 events' selected snapshot provably already contains the event's
  own period value** (filing-lag median 5d; 2.4% of filings cross a month-end). "UI
  snapshot cutoff < event published_at" is therefore unprovable for legacy-input
  components and DIRECTLY violated for 96 events. Per the do-not-invent rule, no baseline
  mapping was persisted and no staleness cutoff was optimized. FE6 baseline coverage
  figures above are DIAGNOSTIC ONLY (binding = false).
- **Remedy path (recorded, not executed)**: rebuild/extend the UI panel to persist, per
  snapshot row, the max `published_at` over all fundamental inputs (true knowledge
  cutoff) using the now-recovered monthly publication times; revisit this gate with a new
  preregistration clarification. All other V1.1 semantics (feature, entry rule, outcomes,
  FE1–FE8, bootstrap, EI1–EI8) remain frozen and untouched.

**FINAL: OLD V1.0 HASH PRESERVED (5dff31d5…) · V1.1 HASH PRESERVED AND BINDING
(c1dacaf1…) · EVENT_COUNT_ARITHMETIC = PASS · PRE_EVENT_UI_BASELINE_PIT_READY = NO ·
ONE_SECURITY_PER_SIGNAL_DATE = PASS · EVENT_TIME_NORMALIZATION = PASS ·
FUNDAMENTAL_EVENT_V1_2_PREREGISTERED = NO · FUNDAMENTAL_EVENT_V1_2_EXACT_SPEC_FROZEN =
NO · FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO ·
SIGNAL_PROMOTION_READY = NO.** STOP — execution remains blocked on the UI-baseline
knowledge-cutoff limitation; next move is the user's.

## 70. UI-SCORE PIT LINEAGE AUDIT + PIT-CORRECT RESEARCH PANEL v2 + PRE-EVENT BASELINE (2026-10-03)

DATA-LINEAGE task only. Production UI score UNCHANGED. FE1–FE8 UNCHANGED. No event
outcomes inspected beyond the explicitly authorized validation rerun of the fixed score
(task 12). V1.0 hash 5dff31d5… and V1.1 hash c1dacaf1… preserved; V1.1 remains the binding
execution spec. NO V1.2 created.

- **Knowledge-time classification (task 2)**: monthly sales/activity → v1 basis D (legacy
  `period_end ≤ as_of` proxy; compute_metrics.py lines 315–338) with real publication times
  now recoverable for 9,615/12,180 periods; statement families (revenue/profits/EPS/
  margins/ROE/coverage/cash-quality/leverage/current-ratio) → D for 7,562 legacy reports,
  A for 595 codal; LT6 letters recover 2,815 statement rows; shares/market-cap → A
  (share_intervals knowledge_from, already provable); PE/PS/PB → mixed C+D/A; liquidity/
  volatility/momentum → C (trade_date frozen proxy); DQ inherits input bases.
- **Visibility rule (frozen)**: visible_from = real DB published_at (codal) or LATEST
  recovered (company, period) publication (conservative latest-version rule); unprovable →
  invisible → existing DQ missing-data behavior. period_end NEVER used as publication time.
  Cutoff convention = the original validated one: 23:59:59 UTC on the signal date.
- **Existing panel classification (task 4)**: of 13,481 snapshots — PROVABLY_PIT_SAFE 102 ·
  DIRECT_LEAK_CONFIRMED 4,500 · UNPROVABLE_LEGACY_KNOWLEDGE_TIME 8,879 (730d contribution
  window, conservative). **UI_HISTORICAL_PIT_STATUS = PARTIAL.**
- **PIT-correct rebuild (task 6)**: `ui_score_research/ui_score_historical_pit_v2.parquet`
  — 12,604 rows, 63 frozen signal dates, 235 symbols; EXACT production Engine
  (canonical-v1-dev, VAL_DIRECT, weights/DQ/penalties/caps/ranks untouched); the ONLY
  change = input visibility (`build_ui_pit_panel_v2.py`, PITEngine — two SQL predicates).
  SHA-256 543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a.
- **Validation rerun (task 12, frozen convention: per-date Spearman ≥5 pairs; quintiles
  ≥10 rows; dependence-aware bootstrap seed 20261003 B=2000, block=4 dates≈3 months)**:
  IC21 **0.0574** (frozen 0.1103) · IC63 **0.0853** (0.1543) · IC126 **0.1096** (0.1806) ·
  IC252 **0.1031** (0.1571) → **UI_HISTORICAL_VALIDATION_PIT_REPAIR = MATERIALLY_WEAKER**
  (all four horizons; a-priori materiality |ΔIC| ≥ 0.02). Positive fractions 0.73/0.79/
  0.90/0.82. Q5−Q1 63d mean spread **+1.78pp** (frozen-era ≈ +4.9pp), bootstrap CI
  [−2.38, +5.69]. IC63 bootstrap CI [0.047, 0.125] — positive ranking value PERSISTS but
  is materially weaker: a material share of the frozen historical evidence came from
  inputs not yet public at the snapshot dates. Production score unchanged; historical
  ICs must henceforth be quoted with this caveat.
- **Pre-event UI baseline (tasks 9–11)**:
  `fundamental_event_research/pre_event_ui_baseline_pit.parquet` — latest v2 snapshot with
  `knowledge_cutoff < published_at` per event. Coverage: **5,902/6,079 = 97.09%** (177
  missing); qualifying-date events 5,302/5,441 = 97.45%. Age: median 27d, p75 28, p90 32,
  max 213; ≤31d 89.5%, 32–62d 6.1%, >62d 4.5% (no cutoff optimized). FE6 identical-row
  universe: **5,902 events, 196 qualifying dates (≥10 identical rows), 5,258 events, 160
  symbols** → FE6_PREOUTCOME_SAMPLE_ADEQUATE = YES (a-priori rule ≥24 dates & ≥500 events).
- **FINAL: UI_HISTORICAL_PIT_STATUS = PARTIAL · UI_PIT_RECONSTRUCTION_FEASIBLE = YES ·
  UI_PIT_RESEARCH_PANEL_CREATED = YES · PRE_EVENT_UI_BASELINE_PIT_READY = YES ·
  FE6_PREOUTCOME_SAMPLE_ADEQUATE = YES · UI_HISTORICAL_VALIDATION_PIT_REPAIR =
  MATERIALLY_WEAKER · FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO ·
  SIGNAL_PROMOTION_READY = NO · UI_SCORE_STATUS (production) = READY.** STOP — awaiting
  explicit instruction to execute Fundamental Event V1 under the frozen V1.1 spec.

## 71. SCORE DEEP AUDIT V1 — complete diagnostic of canonical-v1-dev on the PIT-correct panel (2026-10-03)

DIAGNOSTIC ONLY (task-scoped). Production score/formula/DQ/weights UNCHANGED. No Score V2
built. No portfolio backtest. Fundamental Event V1 NOT executed.

- **SCORE_AUDIT_INPUT_PARITY = PASS** — exact reproduction on
  `ui_score_historical_pit_v2.parquet`: IC21 +0.0574 · IC63 +0.0853 · IC126 +0.1096 ·
  IC252 +0.1031; IC63 boot CI [0.047, 0.125]; 63d Q5−Q1 +1.78pp.
- **Formula documented & verified** (compute_metrics.py:719-790): quant = DQ×(G+P+V+M),
  raw max 89; midrank percentiles with neutral placeholders (0.3/0.5/0.0); explicit
  penalties (growth −6/−5; profitability −10/−4/−3 + EQ nonlinear to −8; valuation −8
  invalid-PE); DQ = boolean coverage 0.30/0.20/0.20/0.15/0.15.
- **Coverage under PIT gating**: statement-derived families ~4% (n≈9/date), revenue 5%,
  PE 9%, PS/PB 2%, **Liquidity 0% (trade_value_rial 96% NULL in DB — dead weight in v1
  AND v2)**; price metrics ~100%; monthly-sales 40-61% with 2021-22 ≈ 0 ramp.
- **Component attribution**: strongest = SalesGrowth12M (0.109/0.121, pos 0.897),
  SalesGrowth3M, LowVolatility, CashConversion; ≈ zero = ROE, Revenue/OpProfitGrowth,
  IntCov, EQ, MarginTrend, PE; **negative both horizons = NetMargin, PS, PB, Leverage,
  CurrentRatio** (small magnitudes, yearly signs flip).
- **Redundancy**: PE↔PS 0.77 · PE↔PB 0.76 · Leverage↔CurrentRatio 0.82 (|ρ|≥0.70).
- **Category attribution**: Growth IC63 0.0781 [0.041,0.119] · MarketRisk 0.0687
  [0.002,0.134] · Profitability 0.0146 [−0.011,0.039] · Valuation 0.0058 [−0.017,0.027].
- **LOCO ablation** (no reallocation, DQ preserved): removing Growth −0.011 IC63 /
  −1.07pp spread; Profitability ±0.000; Valuation −0.003; MarketRisk +0.0003 (spread
  −2.25pp). Nothing harmful enough to justify removal by itself.
- **DQ helps**: pre→post IC63 0.0823→0.0853, spread 1.60→1.78pp; ~0 rows move ≥10pct.
- **Effective weights**: accounting 93.9% vs price-derived 6.1%; Liquidity 3.4% nominal →
  0% effective.
- **Yearly stability**: FULL IC63 0.025/0.024/0.042/0.164/0.151/0.214 (2021→2026);
  LOYO excluding 2021-23 → ~0.10, excluding 2024-25 → ~0.067 — ranking power concentrates
  where fundamental visibility exists (data ramp, NOT used to exclude years).
- **Monotonicity**: 63d Q-means upward with Q2/Q3 inversion (9.7% dates strictly
  monotonic); 126d nearly monotone (14.8% strict); reported, not hidden.
- **Persistence**: month-to-month rank ρ 0.930; top-decile turnover 22.5%/mo; top-quintile
  **19.8%/mo**.
- **Distribution**: min 2.06 · median 24.0 · p99 50.9 · max 71.27 — a scaled rank
  composite, NOT a probability, NOT an expected return.
- **Price dominance check**: accounting 93.9% vs price 6.1% effective mass — the score is
  genuinely fundamental-driven; price sleeve adds 126d diversification.
- **GATES: SCORE_V2_RESEARCH_JUSTIFIED = YES** (3 redundant pairs |ρ|≥0.70; 5
  both-horizon-negative components; Liquidity/PS/PB nominal-effective collapse;
  Profitability & Valuation CIs cross zero — weaker overall IC alone was NOT used as a
  reason) **· SCORE_PORTFOLIO_BACKTEST_JUSTIFIED = YES** (positive IC63/126 CI,
  235 symbols, ρ 0.930, 19.8% turnover) **· UI_SCORE_CURRENT_FORMULA_CHANGED = NO ·
  SCORE_V2_CREATED = NO · FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO.**
- Files: `ui_score_research/SCORE_DEEP_AUDIT_V1.md` + `score_deep_audit_v1.json` +
  5 required CSVs + 2 supporting CSVs (coverage, weight concentration). STOP.

## 72. SCORE PORTFOLIO V1 PREREGISTERED — pre-outcome feasibility PASS, execution NOT authorized (2026-10-03)

Research priority changed: AUTOMATED PERIODIC PORTFOLIO MANAGEMENT with the EXISTING
validated score. No Score V2, no UI optimization, Fundamental Event V1 stays paused.

- **Frozen spec**: `portfolio_research/SCORE_PORTFOLIO_V1_PREREGISTRATION.md` —
  **SHA-256 10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c**.
  Score source `ui_score_historical_pit_v2.parquet` (543dfbf7…), canonical-v1-dev
  UNCHANGED incl. dead weights (Liquidity/PS/PB kept deliberately). PRIMARY
  `score-portfolio-v1-top20` (top 20% by rank, equal weight, n = max(1, floor(0.2N)),
  tie-break (score DESC, symbol ASC)); SECONDARY diagnostic `top10` (cannot rescue
  primary). Monthly rebalance on the 63 frozen score dates; EXECUTION_DATE = first
  canonical trading date strictly after the knowledge cutoff; execution price = canonical
  pClosing; identity key = SYMBOL (score-panel is_primary security_id ≠ daily-panel
  research-symbol mapping — documented). Tradability = daily-panel row AND
  security_traded==True; failures → cash (no substitute, no look-ahead); existing holder
  carried but not sellable. Cash 0%. Costs: GROSS/LOW/BASE/HIGH = 0/25/50/100 bps
  one-way, BASE 50 = primary convention. Benchmark = equal-weight ALL eligible names,
  identical execution/costs. Bootstrap seed 20261003, B=2000, 6-month moving blocks.
  Gates PV1–PV8 frozen (PV2 +2.0pp net excess @50bps; PV3 bootstrap lower bound >0; PV4
  3/5 years; PV5 DD ≤ bench+5pp; PV6 turnover ≤30%; PV7 breadth ≥20; PV8 cash ≤10%).
- **PORTFOLIO_RETURN_SEMANTICS = PRICE_PLUS_MECHANICAL_ADJUSTMENTS** — the canonical
  chain captures capital_increase/rights_issue/reverse_split + heuristic gaps and does
  NOT capture cash dividends; "total shareholder return" is NOT a permitted label.
- **Pre-outcome feasibility** (`feasibility_score_portfolio_v1.py` →
  `score_portfolio_v1_feasibility.json` + by-date CSV): 63 rebalance dates; median 212
  eligible names/date (79-227); Top20 median 42 holdings (min 15; PV7 pre-check PASS);
  Top10 median 21; **0 expected failed executions on all 63 execution dates; expected
  involuntary cash 0% (PV8 pre-check PASS)** → **PORTFOLIO_V1_FEASIBLE = YES**.
  Coverage ramp by year inherited from the score panel (median eligible 124→221) and will
  be reported as the DATA-COVERAGE diagnostic; NO start-year chosen.
- **NO portfolio returns, CAGR, drawdown, or excess returns were computed in this task.**

**FINAL: SCORE_PORTFOLIO_V1_PREREGISTERED = YES · SCORE_PORTFOLIO_V1_EXACT_SPEC_FROZEN =
YES · PORTFOLIO_V1_FEASIBLE = YES · PORTFOLIO_V1_EXECUTED = NO ·
PORTFOLIO_V1_SHADOW_ELIGIBLE = NO · SCORE_V2_CREATED = NO ·
FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO ·
UI_SCORE_CURRENT_FORMULA_CHANGED = NO.** STOP — awaiting explicit execution instruction.

## 73. PORTFOLIO V1 IDENTITY CONTRACT + CASH-DIVIDEND AUDIT — identity PASS, total-return PARTIAL (2026-10-03)

Two implementation questions closed before execution. Preregistration hash verified
immutable: 10e6aa0e… No returns computed. No spec changes.

- **PART 1/2 — identity**: DB invariant: 331 security rows = 331 unique symbols = 331
  unique ins_codes; every scored symbol maps to exactly ONE issuer/instrument. A=0, C=0,
  D=0, E=0, F=0 normalization collisions. The 8 multi-symbol issuers are same-issuer
  secondary instruments (fund X/X2 classes, distinct ins_codes). The daily panel's 238
  security ids are a SEPARATE legacy namespace (all foreign to core.securities); instrument
  identity for all 235 scored symbols is PROVEN three-way: symbol string (score panel =
  daily panel = raw-cache index) + **ins_code (core.securities = raw-cache index,
  235/235 exact)**. `portfolio_research/portfolio_identity_map.parquet` created:
  portfolio_security_key = company_id:ins_code, 235 rows, mapping_status UNIQUE ×235,
  **0 ambiguous rows**.
- **PART 3 — feasibility recheck on the canonical identity**: identical to the symbol-only
  run — 63 dates, median 212 eligible, Top20 median 42 holdings, **0 expected failed
  executions, 0% involuntary cash**; 0 ambiguous rows in any selection. Previous claims
  HOLD.
- **PART 4/5 — dividends**: NO disclosure-level dividend data exists anywhere (0 report
  titles, no fact metric, no dividend table, caches are letter metadata only). The only
  dividend-like data is **4,344 `dividend_per_share_hypothesis` values inside corporate-
  action metadata — PRICE-GAP-DERIVED (taxonomy PRICE_ADJUSTMENT_UNCLASSIFIED) and
  therefore NOT used as dividend inputs (prohibited)**. By year (gap events/symbols):
  2021 452/198 · 2022 465/202 · 2023 427/215 · 2024 451/213 · 2025 432/216 · 2026 277/205.
- **KEY SEMANTICS FINDING**: all these dividend-like gaps carry
  `adjustment_evidence_status='CONFIRMED'` — the official TSETMC gap factors are ALREADY
  applied in the return chain. Since wealth reconstruction depends on the FACTOR (not the
  label), the frozen V1 return stream implicitly includes the wealth effect of 2,504
  dividend-like ex-date events (2021-2026) without any fabrication. Unprovable: official
  gap-detection completeness and per-gap attribution (immaterial for wealth).
- **VERDICTS: PORTFOLIO_IDENTITY_CONTRACT = PASS · PORTFOLIO_EXECUTION_MAPPING_READY =
  YES · CASH_DIVIDEND_DATA_AVAILABLE = NO · TOTAL_RETURN_RECONSTRUCTION = PARTIAL ·
  PORTFOLIO_V1_EXISTING_SPEC_EXECUTION_READY = YES.** Research execution readiness = YES;
  real-money wealth interpretation readiness = PARTIAL (dividend wealth implicitly
  included via official gap factors but unverifiable without disclosure data; the frozen
  preregistration's PRICE_PLUS_MECHANICAL_ADJUSTMENTS terminology remains exactly right).
- Path to a disclosure-backed total-return V1.1 (recorded, not started): collect Codal
  AGM/board DPS + ex/entitlement dates into a canonical dividend table.
- Files: `portfolio_identity_map.parquet`, `portfolio_identity_dividend_audit.json`,
  `audit_identity_and_dividends.py`. STOP — awaiting execution instruction for
  SCORE PORTFOLIO V1.

## 74. SCORE PORTFOLIO V1 EXECUTED EXACTLY ONCE — PRIMARY GATE FAIL (PV3 only) (2026-10-03)

Preregistration hash verified byte-for-byte before execution (10e6aa0e…); score artifact
hash verified (543dfbf7…); identity map 235/235 UNIQUE verified; prereg UNCHANGED after
execution (re-verified).

- **Execution**: 63 monthly rebalances, 62 monthly periods (exec dates 2021-02-01 →
  2026-07-01), sequential wealth simulation, execution = canonical pClosing on the
  CONFIRMED adjusted chain at the first canonical trading date strictly after each score
  date; identity key company_id:ins_code; tradability = daily-panel row AND
  security_traded==True; **0 failed targets and 0 carried valuations across all 63
  rebalances**; costs 0/25/50/100 bps one-way on absolute traded notional, paid from
  portfolio cash only (no borrowing; buys scale proportionally when cash is short).
  Benchmark = equal-weight ALL eligible names with identical rules.
- **PV1 PASS · PV2 PASS · PV3 FAIL · PV4 PASS · PV5 PASS · PV6 PASS · PV7 PASS ·
  PV8 PASS → SCORE_PORTFOLIO_V1_PRIMARY_GATE = FAIL** (no near-miss override).
- **Top20 @ 50 bps**: annualized **43.03%**, cumulative **+535%** (6.35×), MDD **−25.50%**,
  vol 35.48%, Sharpe-like 1.185, positive months 54.8%, median holdings **44**, cash ≈0%,
  avg turnover **29.84%** (median 27.85%, p90 45.79%), notional/capital 43.7×.
  Benchmark: 35.53% / 3.81× / MDD −29.42% / turnover 16.72%.
- **Excess**: annualized **+7.50pp** (PV2 PASS), terminal wealth +1.54×, mean monthly
  excess **+0.4617%**, median +0.3529%, positive-month fraction 59.7%; yearly excess
  +4.70 / −21.33 / −0.61 / +11.41 / +25.57 / +15.09pp (2021→2026; **3 of 5 full years
  positive → PV4 PASS**); PV5 PASS (Top20 MDD 3.9pp better than benchmark).
- **PV3 FAIL**: 6-month-block bootstrap (seed 20261003, B=2000, block=7 periods) 95% CI
  for mean monthly excess **[−0.343%, +1.208%]** — lower bound < 0; annualized equivalent
  CI [−4.12%, +14.49%]; CAGR-difference CI [−4.71%, +19.44%]. The point-estimate excess is
  positive but not robust at the preregistered dependence-aware standard.
- **Top10 DIAGNOSTIC ONLY**: 48.15% / 6.62× / MDD −26.14% / Sharpe 1.235 / turnover 32.2% —
  does not change the primary gate; no variant created.
- **Implementation note (PV1 record)**: costs financed from portfolio cash only; when
  cash+sells could not cover buys+costs, buys scaled proportionally and cash floored at 0
  (no borrowing/margin). An initial run had a negative-cash artifact; it was corrected
  BEFORE gates were evaluated and the corrected run is the single official execution.
- **Data-ramp context** (no year excluded): median eligible 92→221, fundamental input
  coverage 0% (2021) → 67% (2026) — the score was effectively price-driven early; no
  start date preferred.
- **FINAL: SCORE_PORTFOLIO_V1_PRIMARY_GATE = FAIL · SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE =
  NO · PORTFOLIO_PRODUCTION_READY = NO · REAL_MONEY_AUTOMATION_READY = NO ·
  SCORE_V2_CREATED = NO · FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO ·
  UI_SCORE_CURRENT_FORMULA_CHANGED = NO · prereg hash 10e6aa0e… PRESERVED.**
  No strategy modification, no rescue, no re-run. STOP.

## 75. PORTFOLIO V1 ACCOUNTING REPAIR RUN — root cause fixed, unit tests PASS, PRIMARY GATE PASS (conditional on parity sign-off) (2026-10-03)

External review rejected the first net results (cost magnitude inconsistent with
turnover/notional). Quarantined: PORTFOLIO_V1_NET_RESULT_VALID = NO. Old artifacts
preserved. Prereg hash 10e6aa0e… re-verified immutable.

- **Root cause found (deeper than the review's hypothesis)**: bps conversion and the cost
  LEDGER were correct (0/0.0025/0.005/0.01; fees = 0.005 × actual notionals). The defect
  was POSITION-FINANCING: the buy-financing factor f was applied to TARGET POSITIONS
  instead of BUY DELTAS, destroying (1−f)×current_value of held positions at every
  rebalance where buys exceeded cash+sells. The leak is cost-rate INDEPENDENT → BOTH gross
  and net paths collapsed (value_pre 1.0 → 0.0002 by 2025) and the reported "+535%" was
  growth ratios compounded across a collapsing path.
- **Repair**: f scales BUY DELTAS only; invariant NAV_post = NAV_pre − cost asserted at
  every rebalance (500-case randomized sweep exact). Unit tests A-E ALL PASS (A bps
  conversion; B one-way purchase buy+fee=100; C full rotation ≈1% drag; D zero turnover;
  E proportional reduction, cash ≥ 0).
- **GROSS_PATH_PARITY = FAIL (documented)**: the old gross path contained the same leak
  and was itself invalid — no valid prior gross exists to anchor parity. This parity
  failure + root cause is the ONE item requiring reviewer sign-off before the PASS gate
  below is treated as final (task section 9 stop rule honored: reason identified and
  stated, not hidden).
- **Cost reconciliation (review's section 6)**: gross→LOW/BASE/HIGH observed drag 2.08 /
  4.13 / 8.12 pp/yr vs fees-implied 1.37 / 2.74 / 5.50 pp/yr — stable 1.48-1.52 ratio
  across scenarios (early-fee compounding signature); total notional/capital 28.29×;
  total fees 0.2497 initial units (BASE). The quarantined "43.7× notional, 0.04pp drag"
  inconsistency is fully explained and eliminated.
- **OFFICIAL REPAIRED RESULTS (BASE 50bps, PRICE_PLUS_MECHANICAL_ADJUSTMENTS)**:
  Top20 ann **39.79%**, cum **+464.5%** (5.645×), MDD **−26.85%**, vol 35.63%, Sharpe
  1.118, median holdings 44, cash ≈0%, turnover **29.31%**, 0 failed/0 carried.
  Benchmark: 32.47% / 3.275× / MDD −29.50% / turnover 10.44%.
  Excess: **+7.32pp** annualized; mean monthly +0.4973%; positive months 58.1%; yearly
  excess +1.22 / −0.46 / −3.67 / +8.24 / +17.29 / +15.43 pp (2021→2026).
  Bootstrap (seed 20261003, B=2000, block=7): mean monthly excess CI
  **[+0.0653%, +0.9612%]** — lower bound > 0; annualized CI [+0.78%, +11.53%]; CAGR-diff
  CI [+0.88%, +15.25%].
- **Top10 DIAGNOSTIC ONLY**: 44.58% / 5.717× / MDD −27.40% / turnover 31.29%.
- **GATES (recomputed from the repaired path): PV1-PV8 ALL PASS →
  SCORE_PORTFOLIO_V1_PRIMARY_GATE = PASS** — conditional on reviewer sign-off of the
  gross-parity failure explanation. **SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE = YES (per
  frozen rule IF the gate stands) · PORTFOLIO_PRODUCTION_READY = NO ·
  REAL_MONEY_AUTOMATION_READY = NO · SCORE_V2_CREATED = NO ·
  FUNDAMENTAL_EVENT_EXECUTED = NO · SIGNAL_ENGINE_STARTED = NO.**
- Files: SCORE_PORTFOLIO_V1_RESULTS_ACCOUNTING_REPAIRED.md +
  score_portfolio_v1_results_accounting_repaired.json (all artifact hashes recorded) +
  monthly/trades/holdings/yearly/bootstrap _accounting_repaired files. Old artifacts
  quarantined, not deleted. STOP — awaiting reviewer sign-off on the parity explanation.

## 76. PORTFOLIO V1 FINAL CERTIFICATION — all reconciliations PASS, PRIMARY GATE certified (2026-10-03)

Certification of the repaired artifacts ONLY (no new execution, no parameter change).
Prereg hash 10e6aa0e… verified immutable. Root-cause explanation ACCEPTED by the user
(old gross path invalid; repaired run = candidate official result).

- **OLD_GROSS_PATH_VALID = NO · REPAIRED_GROSS_INTERNAL_CONSISTENCY = PASS**: the repaired
  0-bps path re-executes bit-identically (max |Δ| = 0.0) and satisfies the monthly
  return/NAV identity to 4.4e-16.
- **BENCHMARK_WEALTH_RECONCILIATION = PASS** — the reported "cumulative +227.5% (3.275×)"
  was a PROSE TYPO: the artifact's 3.2755 is the CUMULATIVE RETURN (+327.55%); the
  terminal wealth multiple is **4.2755×** (proof: 3.275^(12/62)−1 = 25.8% ≠ 32.47% CAGR,
  while 4.2755^(12/62)−1 = 32.47% exactly). Initial NAV (post entry cost) 0.995025;
  final NAV 4.275451; 62 monthly periods; convention wealth^(12/62)−1.
- **TOP20_WEALTH_RECONCILIATION = PASS**: final NAV 5.645069×, cumulative +464.51%,
  CAGR 39.79% — product(1+monthly) == path ratio exact; all summary metrics re-derived
  from a fresh deterministic re-execution match the certified JSON.
- **Excess wealth verified from NAVs**: 5.645069 − 4.275451 = **+1.3696×**.
- **Return-series/NAV identity (all 9 series: Top20/Bench × 4 costs + Top10)**: max abs
  error **8.88e-16**; external cash flows zero.
- **TRADE_COST_LEDGER_RECONCILIATION = PASS**: Σ trade costs == Σ monthly costs (diff 0.0);
  every trade cost = |notional| × rate exactly. Top20 BASE: buys 25.347 + sells 24.596 =
  notional 49.943 (28.29× avg capital), fees 0.2497. Bench BASE: notional 7.865, fees
  0.0393.
- **SELF_FINANCING_INVARIANTS = PASS**: independent ledger replay reproduces the engine
  path to ≤ 2.19e-9 across all 9 series; 0 negative-cash rows; 0 NAV failures;
  0 position failures; 0 external injections. (An initial replay-check FAIL was a bug in
  the CHECK itself — the replay dropped positions between periods; fixed and re-certified.)
- **Turnover verified from the frozen formula**: Top20 29.31% · Bench 10.44% · Top10
  31.29%; relationship to traded notional documented (related, not interchangeable).
- **Yearly returns recomputed from NAV (end-date attribution — standard; supersedes the
  repaired MD's start-attribution table)**: excess +1.81 / +0.54 / −7.69 / +9.15 / +12.15
  pp (2021→2025) + 22.47pp (2026 descr.) → **4 of 5 full years positive → PV4 PASS**.
- **BOOTSTRAP_INPUT_CERTIFIED = PASS**: 62 obs; excess-vector hash
  c0a0e62b…; seed 20261003, B=2000, block=7; CI reproduced exactly
  [+0.0653%, +0.9612%]; no stale series.
- **GATES RE-CERTIFIED: PV1–PV8 ALL PASS → SCORE_PORTFOLIO_V1_PRIMARY_GATE = PASS ·
  SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE = YES · PORTFOLIO_PRODUCTION_READY = NO ·
  REAL_MONEY_AUTOMATION_READY = NO** (boundary unchanged: exploratory sample,
  survivorship unresolved, data ramp, ~62 obs, dividend completeness unproven, no shadow
  period yet).
- Files: SCORE_PORTFOLIO_V1_FINAL_CERTIFICATION.md +
  score_portfolio_v1_final_certification.json (all hashes recorded) +
  certify_portfolio_v1.py. All prior artifacts preserved for lineage. STOP.

## 77. BOOTSTRAP BLOCK-SPEC CERTIFICATION — spec means 6 monthly returns; PV3 re-certified PASS on the compliant block (2026-10-03)

Prereg hash 10e6aa0e… verified immutable. The remaining spec-compliance question (frozen
"6-month moving blocks" vs implemented block=7) resolved:

- **Frozen spec (verbatim, section 9)**: "Monthly portfolio observations; seed 20261003,
  B = 2000, 6-month moving blocks (date-level resampling); bootstrap CIs for mean monthly
  excess return and its annualized equivalent; if technically valid, CAGR difference via
  time-block paths. 95% intervals; block size never altered after results."
- **BOOTSTRAP_BLOCK_SPEC = UNAMBIGUOUS_6_RETURNS**: the prereg's explicit observation
  unit is monthly portfolio RETURN observations; a 6-month block of that series is 6
  return observations. The endpoint-span reading does not rescue the implemented 7 either
  (7 return observations span ~7 monthly periods, not 6). No endpoint/span convention is
  defined anywhere in the prereg.
- **IMPLEMENTED_BOOTSTRAP_COMPLIES_WITH_FROZEN_SPEC = NO** — block=7 was an unstated
  implementation helper (max consecutive observations within a 182.6-day date span).
- **PV3 recomputed on the certified excess vector with block = 6 monthly returns** (same
  62 obs, seed 20261003, B=2000, circular moving-block mechanics unchanged):
  mean monthly excess +0.4973% · CI95 **[+0.0303%, +0.9953%]** (lower bound > 0 → PV3
  PASS) · annualized equivalent CI [+0.36%, +11.94%] · CAGR-difference CI
  [+0.31%, +16.00%]. BLOCK7 CI [+0.0653%, +0.9612%] retained for the record.
  **PV3_ROBUST_TO_BLOCK_INTERPRETATION = YES** (lower bound > 0 under BOTH 6 and 7).
- **Certification finding (bounded)**: the engine's NAV arithmetic carries set-iteration-
  order float nondeterminism across processes — byte-level excess-vector hashes differ
  while elementwise agreement is ≤4.7e-16; block-7 CIs computed on three vector variants
  agree to <1e-9 and block-6 CIs to 1.5e-17. Economically identical; documented, not a
  strategy defect.
- **CERTIFIED OFFICIAL PV3 BASIS**: block = 6 monthly returns, CI [+0.0303%, +0.9953%].
  All other certified numbers (Top20 39.79%/5.6451×, Bench 32.47%/4.2755×, excess +7.32pp,
  MDDs, turnover, fees, yearly returns) UNCHANGED.
- **PV3_FINAL = PASS → SCORE_PORTFOLIO_V1_PRIMARY_GATE = PASS ·
  SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE = YES · PORTFOLIO_PRODUCTION_READY = NO ·
  REAL_MONEY_AUTOMATION_READY = NO.**
- Files: certify_bootstrap_block_spec.py · bootstrap_block_spec_certification.json.
  STOP.

## 78. SHADOW V1 — FORWARD-ONLY PAPER PORTFOLIO CREATED AND VALIDATED (2026-10-03)

SCORE_PORTFOLIO_V1 accepted (PRIMARY_GATE=PASS, SHADOW_ELIGIBLE=YES) → user commissioned a
forward-only shadow/paper implementation of the frozen `score-portfolio-v1-top20`. No
historical dates are shadow observations; no real orders ever.

- **Frozen spec** `portfolio_shadow/SHADOW_V1_SPEC.md`, SHA-256
  `959b56904added66812ab3726fc067112d7bc12ab3d58d8334f3c4381540df3a`, SPEC_FROZEN_AT_UTC
  = 2026-10-03T18:45:00Z, recorded in `shadow_v1_state.json` before any rebalance.
- **Start rule (frozen §1)**: first completed `analytics.score_runs` row (canonical-v1-dev)
  with `completed_at > SPEC_FROZEN_AT_UTC` plus a mid-session guard (as_of < completion date
  OR source_cutoff_at ≥ 12:45 Tehran); then monthly = earliest qualifying run whose as_of
  falls in a strictly later calendar month. Decision inputs are read from the PERMANENT DB
  tables (score_runs/company_scores/factor_scores), so the ephemeral canonical_v1_metrics.json
  overwrite can never alter a frozen decision. Last pre-freeze run (as_of 2026-10-02,
  input hash d75b8c5b…) is a TEST FIXTURE ONLY and can never qualify.
- **Selection (frozen §3)** = prereg §3 exactly: n = max(1, floor(0.20 × N_eligible)) over
  ALL scored companies, order (quant_score DESC, symbol ASC), equal weights before failed
  executions. The user's "highest 20%" phrasing = the frozen percentile rule (median
  holdings 42 in backtest); fixture rebuild produced 271 eligible → 54 selected.
- **Identity (frozen §4)**: company_id:ins_code via core.securities, cross-checked vs the
  certified identity map (MAP_VERIFIED / DB_RESOLVED / IDENTITY_ERROR → target stays cash).
- **Data contracts (frozen §5, evidence-based)**: path-A prices = raw closing caches
  (pClosing) × CONFIRMED tsetmc_gap_rule_v1 factors ONLY; path-B (market.price_observations,
  vendor_adjusted legacy_brs_adjusted) is diagnostic-only. DB feed findings logged:
  phantom carry-over sessions (Fri 2026-10-02 = re-stamped Wed 2026-09-30 for 276/282
  securities; a re-stamped 9-24 row hid the real Sat 9-26 close), 1,420 intraday dup pairs,
  token holiday sessions (5 securities). Shadow calendar: no Thu/Fri + breadth ≥ 30
  (only 4 Thu/Fri dates ever, all collector artifacts; real sessions ≥ 230 since Aug-2026).
  Raw caches last refreshed 2026-10-01 22:57 covering 2026-09-30 — refresh lag handled by
  the §15b 7-day finalize deadline.
- **Determinism (§13, engineering only)**: `deterministic_accounting.py` = byte-faithful
  port of the certified `repair_accounting_v1.rebalance_accounts` with SORTED iteration.
  Validation (`portfolio_shadow/tests/run_shadow_validation.py` → determinism_report.json):
  T1 unit tests A–E PASS · T2 500-case invariant sweep PASS · T3 parity vs certified engine
  max abs diff 5.68e-14 (≤1e-12 required; summation-order noise) · T4 observer month-close
  behavior (carry/sell/failed-cash/scaling/NAV identity) PASS · **T5 byte-identical
  artifacts across 3 processes with PYTHONHASHSEED 1/2/3 → SHADOW_BUILD_DETERMINISTIC=PASS**.
- **Accounting**: CERTIFIED_REPAIRED engine semantics only (NAV_post = NAV_pre − cost exact,
  cash ≥ 0, buy-delta scaling, position continuity, 50 bps BASE one-way); quarantined code
  never imported. Benchmark = equal-weight ALL eligible, same engine/conventions.
- **Artifacts (§14)**: per month, written ONCE, never overwritten: shadow_snapshot_YYYY_MM.json,
  shadow_targets_YYYY_MM.parquet, shadow_orders_YYYY_MM.parquet,
  shadow_portfolio_state_YYYY_MM.json (decision-time), then
  shadow_execution_observations_YYYY_MM.parquet + shadow_execution_summary_YYYY_MM.json
  (observer). Hashes recorded in state. No shadow month exists yet; state decisions = [].
- **Final flags**: SHADOW_V1_SPEC_FROZEN=YES · SHADOW_BUILD_DETERMINISTIC=PASS ·
  SHADOW_ACCOUNTING_ENGINE=CERTIFIED_REPAIRED (deterministic port, parity-proven) ·
  SHADOW_IDENTITY_READY=YES (235/271 map-verified, 271/271 DB-resolved) ·
  SHADOW_DATA_PIPELINE_READY=YES (with documented feed defects + cache-refresh dependency) ·
  SHADOW_LIVE_START_READY=YES (awaiting first post-freeze production score run) ·
  REAL_MONEY_ORDERS_ENABLED=NO · BROKER_CONNECTION_ENABLED=NO.
- Files: portfolio_shadow/{SHADOW_V1_SPEC.md, shadow_v1_state.json, SHADOW_V1_ISSUES.md,
  build_shadow_portfolio.py, observe_shadow_execution.py, shadow_common.py,
  deterministic_accounting.py, tests/*}. STOP.

## 79. Shadow V1 pre-launch certification — schedule/calendar/price parity, forward refresh, identity onboarding (2026-10-03)

User directive after technical acceptance of the Shadow V1 harness: certify live-start readiness across
4 axes (monthly decision-schedule parity, execution-calendar parity, forward raw-price refresh readiness,
deterministic identity onboarding) WITHOUT starting Shadow Month #1, preserving the frozen V1 spec.

**Recovered historical rule (Part 1).** All 63 certified SCORE_PORTFOLIO_V1 score dates = the LAST
canonical trading date of the calendar month (44/63 = calendar month-end; 19/63 walked back over
non-trading month-ends; 2026-02/03/04 skipped = coverage-gap precedent); knowledge_cutoff = EOD UTC of
the score date, all 63. Full table: `portfolio_shadow/launch_audit/historical_decision_schedule.json`.

**Schedule parity (Part 2).** V1 rule replays 63/63 over the historical series but FAILS as written on
real production stamps (would fire mid-month, e.g. as_of 2026-10-01). NOT launched under V1. Superseding
pre-first-decision spec `portfolio_shadow/SHADOW_V1_1_SPEC.md` frozen, sha256
`f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e` (V1 spec `959b5690...` preserved
unchanged): decision month M requires the earliest post-freeze canonical-v1-dev run whose as_of_date is
the CERTIFIABLE last canonical trading date of M (two-clause certainty: structural Thu/Fri walk-back, or
month fully elapsed + last recorded session — rescues holiday month-ends like 2024-03), cutoff window
[12:45 Tehran as_of, EOD UTC as_of], no backfill (decision frozen before E begins), skipped months logged.

**Guard (Part 3):** OPERATIONAL_ONLY (window frozen in V1.1 §3; can only disqualify, never shift).

**Calendar parity (Part 4): PASS** — 63/63 exact execution-date matches; 50 excluded low-breadth artifact
dates (breadth 1-6), none ever a certified execution date; 0 shadow-only dates.

**Price contract parity (Part 5): PASS** — 3 independent legs (certified execution pipeline chain; the
repair_accounting_v1 chain the observer imports; independent recomputation) = ZERO difference on 229
priced pairs of 233 samples (4 consistent-absent), covering all four corporate-action classes 2021-2026;
229 exact-session raw pClosing checks, 0 conflicting duplicates. No vendor-adjusted BRS.

**Forward refresh (Part 6): PROVEN** — `portfolio_shadow/refresh_raw_caches_forward.py`; cycle
19:25:19-19:32:04 UTC, all fetches post-freeze; session 2026-10-03 acquired with raw pClosing and 0
insCode mismatches; coverage 271/271 scored companies (was 238); merge append-only by (dEven,hEven),
first-seen-wins; 172 same-day late arrivals skipped; 2207 vendor revisions ignored (field audit: 0
pClosing changes); 6 pre-2021 Thu/Fri vendor-history dates reported + calendar-excluded.

**Identity onboarding (Part 7): READY** — `portfolio_shadow/onboard_shadow_identities.py`, append-only
`identity_onboarding_ledger.jsonl` (36 onboarded, batch ONBOARD-20261003T193414Z): 235
HISTORICAL_MAP_VERIFIED + 36 FORWARD_MAP_VERIFIED, 0 UNRESOLVED/AMBIGUOUS of 271. Only verified
identities receive fills; unresolved/ambiguous targets stay cash.

**Harness defect fixed pre-first-use:** `raw_caches_max_date()` filename parse leaked ".json" into
ins_code -> would always return None -> every observation would finalize by deadline as DATA_MISSING.

**Eligibility layers (Part 8):** SCORE ELIGIBLE >= SELECTED TOP20 >= IDENTITY VERIFIED >= PRICE
OBSERVABLE >= EXECUTABLE; execution failure never alters the ranking universe.

**Decision #1 (Part 9) / clock (Part 10):** no genuinely qualifying run exists (predicate audit of all
12 canonical-v1-dev runs: 0 pass — the two 2026-09-30 runs sit exactly on September's certified last
trading date but pre-date the freeze); Decision #1 not created; SHADOW_FORWARD_CLOCK_STARTED = NO.

**Certification:** `portfolio_shadow/SHADOW_V1_LAUNCH_CERTIFICATION.md` +
`shadow_v1_launch_certification.json`. Suite T1-T5 re-executed after V1.1 changes: all PASS (T3 max diff
5.68e-14; T5 byte-identical across seeds 1/2/3); production dry-runs no-ops. Final flags:
SHADOW_DECISION_SCHEDULE_PARITY = FAIL(V1)/PASS(V1.1); MID_SESSION_GUARD = OPERATIONAL_ONLY;
SHADOW_EXECUTION_CALENDAR_PARITY = PASS; SHADOW_PRICE_CONTRACT_PARITY = PASS;
FORWARD_RAW_CACHE_REFRESH_PROVEN = YES; SHADOW_IDENTITY_ONBOARDING_READY = YES;
SHADOW_DATA_PIPELINE_READY = YES; SHADOW_LIVE_START_READY = YES (under V1.1);
SHADOW_FORWARD_CLOCK_STARTED = NO; REAL_MONEY_ORDERS_ENABLED = NO; BROKER_CONNECTION_ENABLED = NO.

Monthly operational sequence: pipeline produces the month's last-trading-day run (e.g. 2026-10-31) ->
refresh caches -> onboard identities -> `build_shadow_portfolio.py` (before E) -> `observe_shadow_execution.py`
after E. STOP.

## 80. SHADOW V1.1 ACCEPTED BY OPERATOR — readiness check executed, no qualifying run exists, clock NOT started (2026-10-03)

Operator accepted the V1.1 launch certification (active spec `SHADOW_V1_1_SPEC.md`,
SHA `f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e`; V1
`959b5690…` preserved unchanged — both re-verified byte-identical after acceptance).
Standing instruction: build Decision #1 **only** when a real post-freeze production
`canonical-v1-dev` run satisfies the frozen V1.1 §2/§9 rule; until then no shadow
decision and no strategy changes. No research, backtest, Score V2, or Fundamental
Event V1.

**Readiness check (read-only, `launch_audit/decision1_readiness_check.py`, run
2026-10-03T19:56Z):** completed `analytics.score_runs` rows after freeze
(2026-10-03T19:40:34Z) = **0**. All 12 canonical-v1-dev completions pre-date the
freeze (latest 2026-10-02 15:04 Tehran = test-fixture run). Decision #1 not created;
`decisions = []`; SHADOW_FORWARD_CLOCK_STARTED = NO; REAL_MONEY_ORDERS_ENABLED = NO;
BROKER_CONNECTION_ENABLED = NO.

Earliest possible Decision #1: a run with `as_of_date = 2026-10-31` (October's last
canonical trading date, a Saturday; structural clause (a) vacuous) completed after
that session with `source_cutoff_at` in the V1.1 §3 window — or, via clause (b), any
run whose as_of is October's last recorded session and built after 2026-10-31.
Then: refresh caches -> onboard identities -> `build_shadow_portfolio.py` before the
projected execution date -> `observe_shadow_execution.py` after it. STOP.

## 81. SHADOW V1.1 HISTORICAL WALK-FORWARD REPLAY executed — parity PASS, live shadow untouched (2026-10-03/04, operator-directed)

Replay of the frozen V1.1 harness over all 63 certified historical decision dates
(2021-01 .. 2026-06) in a fully separate `portfolio_shadow_replay/` directory. Engine =
live shadow modules (`build_shadow_portfolio` selection semantics, `observe_shadow_execution`
close semantics, `deterministic_accounting`, certified `repair_accounting_v1` price chain);
PIT source = `ui_score_historical_pit_v2.parquet` (SHA verified); spec SHA f396b5f6… verified.
Label: HISTORICAL_REPLAY_ONLY — not forward validation, not promotion evidence.

Result: 63/63 months; wealth 5.6451 vs bench 4.2755; MDD −26.85%; Sharpe 1.12;
avg turnover 29.3%; median holdings 44; 171 unique securities; 583 spells (median 2 mo,
p90 9, max 56). **SHADOW_REPLAY_PORTFOLIO_PARITY = PASS** vs `score_portfolio_v1_*_accounting_repaired`
(all fields ≤ 3.2e-15 abs diff; 0 selection/date/count mismatches; tradability sources agree on
all 14,805 (E,symbol) pairs; execution calendar re-derived 63/63 identical). Determinism:
byte-identical re-run under PYTHONHASHSEED=7. Artifacts: SHADOW_V1_1_HISTORICAL_REPLAY.md,
shadow_replay_monthly.csv, shadow_replay_targets/trades.parquet, security_holding_history.csv,
shadow_replay_yearly.csv, shadow_replay_parity.json, replay_state.json,
current_nonshadow_preview.csv (NON_SHADOW_CURRENT_PREVIEW from run 0d2e5bc7, as_of 2026-10-01,
271 eligible / 54 selected; fixture run e5998f6d excluded). LIVE_SHADOW_STATE_MODIFIED = NO
(state sha 63493408… byte-identical before/after); decisions = []; SHADOW_FORWARD_CLOCK_STARTED = NO;
REAL_MONEY_ORDERS_ENABLED = NO; BROKER_CONNECTION_ENABLED = NO. STOP.

## 82. INVESTOR VIEW FROM 1403-01 built — display-only rescaling of the certified replay (2026-10-04, operator-directed)

Pure display scaling of the §81 certified replay artifacts — no strategy rerun, no accounting/cost
change, no certified artifact modified. Window = first certified decision with score_date ≥ Farvardin
1403 (= 2024-03-20): **2024-03-30** (1403-01-11), exec 2024-04-02, through 2026-06-30 (exec 2026-07-01)
= 25 decision months / 24 certified return periods (final decision has no subsequent period by
construction). Transformation: investor_capital(t) = 100,000,000 × NAV_cert(t) / NAV_cert_pre(E_first);
benchmark anchored identically at its own pre-trade value (1.895991388206585).

Result: FINAL 302,249,093 toman (+202.25% cum, +73.85% ann. over 24 periods, window MDD −20.29%) vs
benchmark 225,499,476 (+125.50%, MDD −19.92%); excess wealth 76,749,616 toman; total costs 7,077,834
toman (all 25 certified rebalances, 50bps BASE unchanged); avg turnover 24.86%; 134 unique securities;
median holding 7.0 months (289 window spells, median 2, max 25 — غمینو held all 25 months). Persian
years: 1403 +26.00% (12 mo), 1404 +76.01% (11 mo, MDD −20.29%), 1405-to-date +36.29% (2 mo; certified
2026-02/03/04 gap absent by construction). Window-start note documented: certified first rebalance cost
127,531 toman (~12.8bps, continuous portfolio); fresh full-notional entry (~50bps ≈ 500k) NOT applied
per display-scaling-only instruction. Window-start carry note: entered/retained counts are relative to
the carried certified portfolio; غپینو's SELL row in 1403-01 has no UI score (genuinely absent from that
month's eligible panel). Builder `build_investor_view_1403.py` reads certified artifacts only, aborts on
input-hash mismatch (monthly CSV c00f22a9… verified), embeds a Jalali calendar with Nowruz anchor asserts
(1403/1404/1405). Outputs byte-identical under PYTHONHASHSEED=99. Files: INVESTOR_VIEW_FROM_1403.md
(1,879 lines, 25 per-month security-decision sections), investor_view_from_1403_monthly.csv (25 rows),
investor_view_from_1403_summary.json. Label: HISTORICAL_REPLAY_ONLY — not forward validation, not a
guarantee, not a real-money record; PRICE_PLUS_MECHANICAL_ADJUSTMENTS, not proven full TSR.
LIVE_SHADOW_STATE_MODIFIED = NO (state sha 63493408… unchanged); decisions = [];
SHADOW_FORWARD_CLOCK_STARTED = NO. STOP.

## 82b. SCORE V2 RESEARCH PROGRAM executed — full 40-phase matrix; PROMOTION GATE FAIL, preserved (2026-10-03/04, operator-directed)

Complete preregistered research program in separate `score_v2_research/`. Protocol frozen BEFORE
any outcome-based computation: `SCORE_V2_RESEARCH_PROTOCOL.md` SHA
`c4bc1998067925e64c8bc772d0e279106626d50698a91a0632ee6573102e2816`. Split 42/6/15
(dev 2021-01..2024-06 / val 2024H2 / locked holdout 2025-01..2026-06, holdout evaluated exactly once).
Baseline reproduction exact: V1 IC21/63/126/252 = 0.0574/0.0853/0.1096/0.1031, Top20 CAGR 39.79%,
excess +7.32pp, MDD −26.85%, turnover 29.31% (all deltas 0.0000) through the certified engine.
PIT contract PASS (leakage tests A/B 2,145 comparisons each, C, D, Ichimoku synthetic).
New PIT-safe features built: raw TSETMC high/low/volume/qTotCap (canonical Ichimoku YES),
trade_value_30d liquidity (coverage 98.5%), 11 chained-fundamental candidates (only
profit_growth_accel passed the frozen inclusion rule: dev IC63 +0.1434, coverage 51%).
Candidates V2-A..F + B-COV × M1/M2/M3; finalists frozen: primary V2-C|M2 (fundamental+technical,
no Ichimoku), challenger V2-B|M1. Locked holdout: primary IC63 0.1524 < V1 0.1601 → G2 FAIL;
IC126 0.1775 > 0.1668 (G3 pass). Portfolio (BASE 50bps, full history): V2-C CAGR 43.18% vs 39.79%,
excess +10.71pp, MDD −25.57% (G5/G6/G7 pass) but turnover 39.0% > 35% → G8 FAIL; incremental
block-6 bootstrap CI [−0.0014, +0.0043] spans 0 (not strong). Ichimoku ablations: YES by frozen
criterion (dev+val only); technical block incremental YES; fundamental reweighting alone NO
(walk-forward OOF 0.038/0.050 vs V1 0.058 on the same window). OVERFIT_RISK = SEVERE (6/9
pre-declared warnings; improvement concentrated in 2023–2024, 2025–2026 incremental ≈ 0/negative).
Current preview (SCORE_V2_RESEARCH_CURRENT_PREVIEW, as_of 2026-10-01, production run 0d2e5bc7,
fixture run excluded): V2 demotes دقاضی/سباقر/غاذر/دلقما strongly, keeps کیمیا/شسپا top.
SCORE_V2_PROMOTION_GATE = FAIL (G2, G8) → SCORE_V2_SHADOW_RESEARCH_CANDIDATE = NO; result
preserved with root cause (val-period favorability + optimizer in-sample gap + turnover).
Determinism: 3 full pipeline runs PYTHONHASHSEED 0/7/123 → byte-identical
candidate_definitions.json / candidate_weights.csv / current_preview.csv / canonical score-panel
TSV SHA `1f19e9fa…`. Artifacts: SCORE_V2_FINAL_RESEARCH_REPORT.md (+ .json), protocol, panels,
diagnostics, holdout, portfolio, ablations, falsification, gates, tests/. All certified inputs and
artifacts byte-identical after the program (shadow state 63493408…, replay monthly c00f22a9…).
LIVE_SHADOW_STATE_MODIFIED = NO; SHADOW_FORWARD_CLOCK_STARTED = NO; PRODUCTION_SCORE_CHANGED = NO;
REAL_MONEY_ORDERS_ENABLED = NO; BROKER_CONNECTION_ENABLED = NO; SQL_SERVER_USED = NO. STOP.

### 82c — SCORE V2 DIAGNOSTIC PACKET (external-reviewer request, post-FAIL, read-only)
User requested a diagnostic packet from the FROZEN score_v2_research artifacts: no re-optimization, no
weight/model change, no holdout re-evaluation. Delivered `score_v2_research/SCORE_V2_DIAGNOSTIC_PACKET.md`
(+ run_diagnostic_packet.py, diagnostic_packet.json, diagnostic_{holdout_per_date,per_feature_ics,monthly_path,ichimoku_ics}.csv).
All recomputed quantities anchored to frozen aggregates (holdout ICs <=5e-4; certified-engine re-simulation
turnover/fees identical to 1e-15; G12 yearly incremental MATCH; incremental monthly series <1e-12; churn anchors MATCH).
Key new (post-hoc, labeled) evidence: per-date holdout IC deltas (V2−V1 IC63 mean −0.0077, pos 5/14; IC126 +0.0107, pos 9/13);
per-feature val/holdout ICs (profit_growth_accel 0.143→0.104→0.038 decay; traded_days_ratio_60 holdout −0.015;
PERank ~0 IC everywhere at 11.3% weight; rsi14 negative everywhere at 1.7%); churn attribution (SalesGrowth3MRank +
traded_days_ratio_60 + profit_growth_accel + vol_20/ma60_slope/rsi14 carry ~89% of weighted rank churn); monthly path
(2023 +7.79pp / 2024 +7.72pp incremental vs 2025 −0.95pp / 2026 −0.13pp). Verdicts: PROFIT_GROWTH_ACCEL_ROBUST = NO,
NEW_LIQUIDITY_INFORMATION_ROBUST = NO, ICHIMOKU_UNIQUE_INFORMATION = INCONCLUSIVE, OPTIMIZER_OVERFIT_CONFIRMED = YES.
NO_NEW_MODEL_WAS_TRAINED = YES; no pre-existing artifact modified; live shadow untouched.

## 83. SCORE V3 MINIMAL RESEARCH PROGRAM executed — preregistered 15-vector grid, GATE FAIL (M6, M10), preserved (2026-10-03/04, operator-directed)

Task: build a simpler, more robust score with low feature count, controlled turnover and
minimal degrees of freedom — explicitly NOT a continuation of the V2 optimizer; no V2
weights reused; 2025–2026 declared burned (historical evidence only). All artifacts under
`score_v3_minimal_research/` (v3lib.py, run_v3_trackA/trackB/final/preview.py,
compose_v3_report.py, outputs). Protocol `SCORE_V3_MINIMAL_PROTOCOL.md` SHA-frozen
BEFORE any outcome evaluation: `27face51296fd8d50b307ab7545566accaf31785039027dd7b8b6dcf1ecdbf92`.

Design frozen: 10-feature pool (4 V1 core + profit_growth_accel + vol_60/mdd_60/
dist_high_120/mom_120/ma60_slope; valuation preregistered OUT on frozen PERank evidence).
Exactly 5 candidates A–E × 3 fixed weight families (W1 equal-within-category, W2
V1-anchored, W3 conservative) = 15 vectors, zero optimization. Cap semantics: nominal
point scale with ΣW ≤ 100 free (literal sum-to-100 caps are arithmetically infeasible:
45+25+12.5 = 82.5 < 100); SalesGrowthRank clipped to 5.0 everywhere (coverage 0.2548 < 40%).
Track A = fixed-weight OOF on all 63 dates (identical date sets V1/V3 asserted); Track B =
nested rolling-origin (eval years 2022–2026, past-only selection inputs with 92d/31d lags).

Result: SELECTED = B-W1 (4 core + vol_60 + mdd_60; W1 weights {SGR 5.0, SG3M 12.5, NPGR 12.5,
Stab 12.5, vol_60 12.5, mdd_60 12.5}). B-W1 vs V1: OOF IC63 0.1203 vs 0.0853, IC126 0.1481 vs
0.1096, BASE CAGR 0.4369 vs 0.3979, turnover 0.2776 vs 0.2931, MDD −0.3085 vs −0.2685.
Track B: folds pick B-W1 4/5 years; pooled OOF 2022–2026 IC63 0.1459 vs 0.0999, IC126
0.1928 vs 0.1163; nested path CAGR 0.7135 vs 0.5960, MDD −0.1940 vs −0.2316 (BETTER).
Incremental V3−V1 (BASE, n=62): mean +0.00167/mo, block-6 CI [−0.00882, +0.00980]
(not significant), inc turnover −1.65pp, fees lower at every cost level.

GATES: M1–M5, M7–M9 PASS; **M6 FAIL** (MDD −0.3085 < tolerance −0.2985; the drawdown episode
is 2021-specific — nested 2022–26 MDD is better than V1) and **M10 FAIL** (excluding best
year 2024 +21.1pp, remaining cumulative incremental −6.15%; 2021 −13.3pp / 2022 −5.5pp).
→ **SCORE_V3_MINIMAL_RESEARCH_GATE = FAIL** (no rescue attempted, no threshold changed).
OVERFIT_RISK = MODERATE (similarity set {B-W1,B-W2}; Track B disagrees 1/5 folds — fold
2022 picked E-W1 with eligibility skipped after no combo was turnover-eligible in the
short past window, declared as deviation). PROFIT_ACCEL_INCREMENTAL_VALUE = YES
(D>C on IC63+CAGR within +1.5pp turnover, family-robust across W1/W2/W3);
ICHIMOKU_COMPACT_OVERLAY_VALUE = YES per frozen rule (marginal: ΔIC63 +0.0018, ΔIC126
+0.0035, ΔCAGR +1.67pp, Δturnover +0.88pp; overlay NOT part of the formula).
SCORE_V3_FUTURE_SHADOW_CANDIDATE = NO. Equal-weight probe ≈ B-W1 (IC63 0.1202 vs 0.1203 —
weighting-insensitive); leave-one-out shows vol_60/mdd_60 carry the added IC (removal
drops IC63 to 0.1055/0.1008); 100bps: V3 0.3994 vs V1 0.3580.
Preview `SCORE_V3_MINIMAL_CURRENT_PREVIEW` on production run 0d2e5bc7 (as_of 2026-10-01,
SELECT-only): Top-30 overlap V1↔V3 9/30, mean |rank change| 0.159; NOT published.
Deviations logged: protocol ΣW column mis-sums (per-feature weights authoritative,
protocol not edited); fold-2022 eligibility skip. Determinism: full pipeline re-run
reproduced all 10 outputs byte-identically (`_determinism_before.sha`). V1 frozen anchors
reproduced exactly. PRODUCTION_CHANGED = NO; LIVE_SHADOW_V1_1_CHANGED = NO.

## 84. SCORE V3 MINIMAL — CERTIFICATION CORRECTION + FAILURE ANATOMY AUDIT (2026-10-04)

Read-only audit of the frozen V3 program (task: certification correction + failure anatomy
BEFORE any future model design). No new model, no weight/feature change, no candidate
created; B-W1 unchanged; production/live Shadow untouched; Postgres SELECT-only.
Artifacts: `score_v3_minimal_research/audit/` (scripts `audit_partD.py`, `audit_efgh.py`,
`audit_abc_patch.py`; outputs `partA_caps.json`, `partB_fold_audit.csv`,
`partB_trackB_audit.json`, `partC_ichimoku.json`, `partD_universe.json`, `partE_*`,
`partEGH_summary.json`, `partF_loo_blocks.csv`, `partG_*`, `partH_*`; report
`SCORE_V3_MINIMAL_CERTIFICATION_AUDIT.md`). Method: exact position-tracking replication of
repair_accounting_v1.simulate (asserted == engine NAV path <1e-9 and == frozen
trackA_monthly.csv <1e-10) giving exact per-security w×r decompositions (monthly identity
sum_i w_i r_i = NAV_pre/NAV_post−1 asserted at 1e-10).

Verdicts:
- PART A caps: NOMINAL_CAP_CONTRACT_PASS = YES (frozen §5 nominal-scale enforcement).
  NORMALIZED_EFFECTIVE_CAP_CONTRACT_PASS = NO — effective shares w/67.5: 5 features at
  18.52% > 12.5% (SG3M/NPGR/Stab/vol_60/mdd_60), tech block 37.04% > 25%, low-coverage
  SGR 7.41% > 5%; Growth 44.44% OK. Weights NOT repaired (audit only).
- PART B Track B: TRACK_B_STRICT_PREREG_COMPLIANT = NO — fold 2022 only (eligible set
  EMPTY: 2021 ex-init churn >33% for ALL 15 combos incl. V1; executed code used a
  POST-PROTOCOL fallback = §17 steps 3–5 only → pick E-W1). Folds 2023–2026 fully
  compliant (all pick B-W1). STRICT_VALID_FOLDS_ONLY (2023–26): V3 IC63 0.1878 vs V1
  0.1240, IC126 0.2459 vs 0.1488, CAGR 0.8166 vs 0.6269, MDD −0.1940 vs −0.2316, inc
  boot CI [+0.39%, +1.43%] > 0. ALL_FOLDS_AS_EXECUTED = frozen pooled record (NOT fully
  OOF-certified due to the 2022 fallback). Caveat: strict window = the era that works;
  B-W1 2021–22 IC63 0.0134 < V1 0.0242, cum −5.3% vs +16.3%.
- PART C Ichimoku: corrected to INCONCLUSIVE (was mechanical YES). ΔIC63 +0.0018,
  ΔIC126 +0.0035 inside noise; ΔCAGR +1.67pp with turnover +0.88pp WORSE; overlay
  bootstrap NOT AVAILABLE. "Clearly improves" not met.
- PART D preview parity: PASS. Production run 0d2e5bc7 = 271 companies; preview scored
  all 271 (CSV rows 271, exact set match both ways). The "269" = technicals-coverage
  count: فاسمین (sec 08ba4f4a…, co 7905533f…) and کروی (sec 84f63b9a…, co 31a4e996…) have
  27 sessions < MIN_SESSIONS=200 → insufficient trading history; both got the SAME
  neutral-0.5 semantics as history (contrib 625.0 each); ranks 227/235 of 271 — no Top-30
  impact. No corrected artifact needed.
- PART E drawdown anatomy (BASE50, exact): V3 peak 2021-03-31 (NAV 1.00095) → trough
  2022-02-28 (NAV 0.69219), MDD −30.85%, recovery 2023-02-28 (23 rebalances underwater);
  V1 peak 2021-08-31 (NAV 1.10001) → same trough (0.80462), −26.85%, recovery 2022-12-31.
  Kill months: after the 2021-04-28 rebalance (V3 −12.9% vs V1 −7.3%) and especially the
  2021-05-31 and 2021-06-30 rows (V3 −8.3%/+2.0% vs V1 +5.8%/+12.0% = −14.1pp/−10.0pp in a
  +6.9%/+6.7% universe). Top drawdown contributors: سدور −3.79pp, سبجنو −2.77, کپشیر
  −2.67, دارو −2.61, پرداخت −2.47, سنیر −2.12, دتوزیع −2.01, غویتا −1.92 (15/20 also held
  by V1 at some point — V3 held them earlier/longer/heavier).
- PART F LOO-block (descriptive): the LOW-RISK block is the driver. minus vol_60: 21–22
  cum −5.3%→+5.6%, window MDD −30.8%→−26.5%; minus mdd_60 →+6.1%; minus BOTH (=A-W1,
  asserted) → 2021 −2.5%, cum +27.6%, MDD −25.9%, 21–22 IC63 0.0321 (best). But the block
  also supplies the 2023–26 edge: full IC63 0.1878 vs 0.1156 without it (≈V1 0.1240).
  Growth-block removals barely help 2021–22. Regime-dependent payoff, not a bug.
- PART G regime: episode bench cum −24.3%, universe cum −23.0%, mean breadth 39%, x-sec
  vol 11.1%; V3 BEAT V1 in the 5 broad DOWN months and lost everything in the 2 broad UP
  months (Jun–Jul 2021). V3 holdings vs V1: lower vol_60 (−0.49pp), shallower mdd_60
  (+17.9pp), higher mom_120 (+12.8pp), but median trade_value_30d −7.8bn rial (10x smaller
  in May 2021). YES — V3 unintentionally selected a different (less liquid, smaller)
  risk profile despite the vol screens; trailing 60d calmness did not protect forward.
  No PIT market-cap series (only current-share snapshots) and no sector columns exist →
  cap proxy = trade value; sector NOT inferred.
- PART H concentration: full cumulative incremental ratio +15.25%; excl best month
  (2023-01-31 +6.02pp) +9.18%; excl top-5 months −8.69%; excl 2024 −1.18% (month-level;
  M10 year-level −6.15%); 37/62 months positive; top-20 securities = 51.5% of positive
  mass. Top positive: دفرا +6.83pp, شسپا +4.17, آریا +3.58, گشان +3.34, شرانل +3.33.
  Top negative: غاذر −5.65pp, تپمپی −4.51, شمواد −4.49, غپینو −4.42, دارو −4.37.
  PERFORMANCE_CONCENTRATION = HIGH (one regime 2023–24 + a handful of months; not
  few-stock; not SEVERE since excl-best-month stays +9.2%).
- PART I: V3_ORIGINAL_GATE = FAIL; B_W1_RESEARCH_VALUE = MEDIUM;
  V3_MDD_FAILURE_PRIMARY_DRIVER = LOW-RISK block × 2021–22 regime (liquidity rotation);
  V3_M10_CONCENTRATION_PRIMARY_DRIVER = single-regime dependence on 2023–24 (2024);
  V3_RESULT_STILL_USABLE_FOR_RESEARCH = YES (evidence only);
  V3_FUTURE_SHADOW_CANDIDATE = NO; NO_NEW_MODEL_CREATED = YES; NO_WEIGHTS_CHANGED = YES;
  PRODUCTION_CHANGED = NO; LIVE_SHADOW_CHANGED = NO; SQL_SERVER_USED = NO.

## 85. Score research closure + liquidity-guard diagnostic (2026-10-03)

Task: formally close the score-model search; determine whether the V3 2021–22 failure is
better framed as scoring vs implementation/liquidity; prepare (draft only) a prospective
guard plan. No V4, no V3.1, no weight/threshold changes, no production/live-shadow change.

**New artifacts (all in `research_closure/`, additive only):**
- `SCORE_RESEARCH_CLOSURE.md` — V1/V2/V3 terminal verdicts + accepted failure findings +
  search formally closed. SHA-256 `44a867437e2894b1cfd1bde335ce9d7e040c6d4b436519a02a91deb2bc63f418`.
- `LIQUIDITY_GUARD_DEFS_FROZEN.md` — L0–L4 definitions, substitution semantics,
  verification gates, and all decision mappings, frozen BEFORE any return was computed.
  SHA-256 `5a3b454de6fa793fe61fdc9ed595fd7c8b704dcee89106f4e3f1cbe171e43bc4`.
- `guard_backtest.py` + outputs (guard_variants/substitutions/substitution_events,
  part2_liquidity_evidence + summary, part6_episode_guard + summary, part7_era_deltas,
  guard_backtest_summary.json with diagnostics), `capacity_current_v1.py` +
  part8_capacity_grid.csv + part9_current_v1_liquidity.csv + part9_summary.json.
- `LIQUIDITY_GUARD_RESULTS.md` — full report. `PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md`
  — DRAFT, NOT approved, NOT activated.

**Verification:** L0 runs asserted identical to `RA.simulate` and to the frozen
`trackA_monthly.csv` BASE rows (V1 cagr/mdd/turnover 0.3979/−0.2685/0.2931; V3 MDD
−0.3085; yearly == M7/M10 table); gross decomposition identity 1e-10 on every rebalance of
every run; tracker substitution counts == independent fail-set intersections (L1 225/243,
L4 recomputed from the guarded value_pre path); window/yearly product identity 0.00pp for
all 10 variants. Two implementation bugs were found and fixed before any result was
reported (guard mask applied in panel order to the score-sorted frame; event deltas using
rank as panel index) — documented in the report's bug log.

**Key findings:**
- Part 2 (frozen rule 6a): the V3 2021–22 failure was **PRIMARILY LIQUIDITY-SCREENING** —
  the score ranked semi-suspended names (failing-name median TD60 = 0.783, median own-rank
  17) into the Top-20%; a pure TD60 bottom-decile floor (L1) recovers +13.56pp of the
  21.56pp V3 2021–22 shortfall (62.9%) at +1.82pp turnover. V3's episode holdings had 2×
  V1's bottom-decile-TV30 share and 4× the 1B-toman capacity ratio.
- Part 5/7: V3-L1 full CAGR 46.36% (vs 43.69% L0), MDD −22.81% (vs −30.85%); but every
  guard costs 2023–26 cum (L1: −23.6pp V1 / −26.2pp V3; L3 −12.0pp V3; L4 −101pp V3).
  On V1 the trade is unfavorable in absolute terms (+5.4pp 21–22 vs −23.6pp 23–26).
- Part 9: current V1 Top20% (run 0d2e5bc7, as_of 2026-10-01, same run as the frozen
  preview) → **CURRENT_V1_HAS_LIQUIDITY_RISK = HIGH** (frozen 6b): 7/54 names fail
  L1/L2/L3 (جم پیلن3، شبهرن، غاذر، غبشهر، فایرا، پیزد، کسرا); جم پیلن3 at 16.8% of its
  30d ADV for a 1B-toman portfolio (TD60 0.433).
- Part 10 (frozen 6c): **all four guards UNACCEPTABLE** (2023–26 cum drop > 10pp on at
  least one model) → BEST_LIQUIDITY_GUARD = NONE. Nothing historically validated.
- Part 11: **NEXT_RESEARCH_DIRECTION = B** (keep V1 + prospective liquidity-guard
  research). Deviation disclosed: frozen §6d maps mechanically to D (guards UNACCEPTABLE +
  risk HIGH); overridden to B with full audit note (6a=YES identifies the mechanism; L1 is
  a concrete preregistrable candidate; B adopts nothing and defers to prospective data).
  No thresholds or definitions altered — only the direction token deviates, with the note
  as audit trail.
- Part 12: `PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md` drafted (L1 on V1, parallel
  research computation vs untouched Shadow V1.1, start ≥ first run after 2026-11-01 and
  explicit operator approval, 12-month horizon, pre-registered stop criteria, no orders).

**Final tokens:** SCORE_RESEARCH_CLOSED_FOR_NOW=YES; V1_REMAINS_PRIMARY=YES;
V2_REMAINS_REJECTED=YES; V3_REMAINS_REJECTED=YES;
V3_FAILURE_PRIMARILY_LIQUIDITY_REGIME=YES; BEST_LIQUIDITY_GUARD=NONE;
CURRENT_V1_HAS_LIQUIDITY_RISK=HIGH; NEXT_RESEARCH_DIRECTION=B;
PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING=YES (draft only);
NEW_SCORE_MODEL_CREATED=NO; PRODUCTION_CHANGED=NO; LIVE_SHADOW_CHANGED=NO;
BROKER_CONNECTED=NO; REAL_MONEY_ORDERS=NO; SQL_SERVER_USED=NO.

Standing Message A wait-state unchanged; production Signal Engine still not started;
SQL Server still disabled.

## 86. LIQUIDITY-GUARD RESULTS — AUDIT CORRECTION applied (2026-10-04, operator-directed)

Operator ruled the §85 liquidity results PARTIALLY ACCEPTED and ordered 5 corrections.
All L0–L3 results, all bug-fix documentation, and all frozen files are UNCHANGED; only
decision bookkeeping and audit documentation were edited. No rerun, no V4/V3.1, no
threshold search, no production/live-shadow change, Postgres SELECT-only, MSSQL untouched.

- **C1 — direction restored:** official preregistered result = frozen §6d mechanical
  **NEXT_RESEARCH_DIRECTION = D (INSUFFICIENT_EVIDENCE)**. The §85 "B" override retracted;
  B demoted to POST_HOC_RESEARCH_RECOMMENDATION = B with
  POST_HOC_RECOMMENDATION_IS_PREREG_RESULT = NO.
- **C2 — L4 provenance audited:** the original task PART 3 (frozen transcript
  `~/.zcode/cli/rollout/model-io-sess_9da553ba-….jsonl`, record completed 2026-10-04T16:10:58Z
  = 19:40:58 +0330) names verbatim "Optional L4 only if justified: portfolio-capacity rule
  based on target notional / recent average traded value", and
  `LIQUIDITY_GUARD_DEFS_FROZEN.md` §2 froze the exact L4 definition (C=1B toman grid
  midpoint, 5% participation) at 19:46:28 +0330 — BEFORE the first guarded-return output
  (`guard_variants.csv` birth 19:57:32). So: **L4_STATUS =
  PREREGISTERED_OPTIONAL_FROZEN_BEFORE_RETURNS** (the operator's
  EXPLORATORY_OUT_OF_ORIGINAL_SCOPE conditional does not trigger — the directive exists and
  is quoted in the report). Per the operator ruling, L4 is nonetheless
  **L4_OFFICIAL_SCOPE = EXCLUDED_PER_OPERATOR_RULING_2026_10_04**: official comparison /
  BEST_LIQUIDITY_GUARD / §6d use L0–L3 only; all L4 results preserved as exploratory
  diagnostics. Outcome-neutral: L1–L3 all UNACCEPTABLE (§6c) with or without L4 →
  BEST_LIQUIDITY_GUARD = NONE; §6d → D; §6a never used L4.
- **C3 — qualification:** V3_FAILURE_PRIMARILY_LIQUIDITY_REGIME = YES retained with
  POST_HOC_DESCRIPTIVE_MECHANISM = YES and FRESH_CAUSAL_VALIDATION = NO;
  V3_FAILURE_DIAGNOSIS_STATUS = POST_HOC_DESCRIPTIVE.
- **C4 — plan stays a DRAFT (NOT APPROVED, NOT ACTIVATED);** plan now labels L1's candidate
  selection explicitly POST-HOC; Shadow V1.1 and production V1 untouched.
- **C5 — artifact audit table added** to the results report (paths, SHAs, ordering vs first
  guarded return 19:57:32, modified-after flags, nature of modifications) + explicit
  confirmation that the mask-alignment and rank/index fixes were implementation-only
  (defs SHA identical before/after every code edit; frozen cross-asserts caught the mask
  bug; final code passes every frozen gate).

Artifact SHAs: `SCORE_RESEARCH_CLOSURE.md` 44a86743…f418 (unchanged);
`LIQUIDITY_GUARD_DEFS_FROZEN.md` 5a3b454d…3bc4 (unchanged — proof no definition moved);
`guard_backtest.py` 973f34bc…2085; `capacity_current_v1.py` f9eb6b39…edf3;
`LIQUIDITY_GUARD_RESULTS.md` rev1 b156b0f0…f313 → **rev2
841edc6db36e146495bab05c3a204c7874d7cbf548a0e3df6604d7fb1d517df7**;
`PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md` v1 3cc26ce1…9ddf →
**056a1044ded91b41b5de6d43e6906660452943bfdaa3a1c444b95f749d64039c**.

**Corrected final tokens (operator-required block):** SCORE_RESEARCH_CLOSED_FOR_NOW=YES;
V1_REMAINS_PRIMARY=YES; V2_REMAINS_REJECTED=YES; V3_REMAINS_REJECTED=YES;
V3_FAILURE_PRIMARILY_LIQUIDITY_REGIME=YES; V3_FAILURE_DIAGNOSIS_STATUS=POST_HOC_DESCRIPTIVE;
BEST_LIQUIDITY_GUARD=NONE; CURRENT_V1_HAS_LIQUIDITY_RISK=HIGH;
NEXT_RESEARCH_DIRECTION=D; NEXT_RESEARCH_DIRECTION_LABEL=INSUFFICIENT_EVIDENCE;
POST_HOC_RESEARCH_RECOMMENDATION=B; POST_HOC_RECOMMENDATION_IS_PREREG_RESULT=NO;
PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING=YES (operator-set; mechanical §6e under D would be
NO; draft dormant); PROSPECTIVE_GUARD_SHADOW_ACTIVATED=NO; NEW_SCORE_MODEL_CREATED=NO;
PRODUCTION_CHANGED=NO; LIVE_SHADOW_CHANGED=NO; BROKER_CONNECTED=NO; REAL_MONEY_ORDERS=NO;
SQL_SERVER_USED=NO.

Standing Message A wait-state unchanged; production Signal Engine not started; SQL Server
disabled.

## 87. Final bookkeeping / semantic audit correction (2026-10-04, Revision 3)

Operator ruling on §86: PARTIALLY ACCEPTED; two corrections, bookkeeping only — no backtest
rerun, no number/threshold/score/ranking/portfolio-rule/definition change.

**Correction 1 — L4 official scope.** The interim token
`L4_OFFICIAL_SCOPE = EXCLUDED_PER_OPERATOR_RULING_2026_10_04` mischaracterized the ruling
and is RETRACTED. Official scope read strictly from the frozen protocol:
`L4_OFFICIAL_SCOPE = INCLUDED_PER_FROZEN_PROTOCOL` (with
`L4_STATUS = PREREGISTERED_OPTIONAL_FROZEN_BEFORE_RETURNS`). Frozen evidence: defs §2 lists
L4 among the "Guards (maximum 4, definitions frozen)" as "(optional, included with
justification)" and itself supplies the a-priori justification (5% participation heuristic,
C = 1B toman grid midpoint) before any return; §6c applies "per guard" excluding none; §6d
BEST_LIQUIDITY_GUARD has no L4 carve-out. Include-vs-exclude invariance verified from the
frozen mapping only (no rerun): L4 also trips UNACCEPTABLE (−53.03pp V1 / −101.09pp V3
23–26 cum) → BEST_LIQUIDITY_GUARD = NONE either way; §6d → D either way; 6a never used L4.
No change to either official token.

**Correction 2 — prospective-plan token.** Official token corrected to
`PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING = NO` (mechanical frozen §6e under D; the interim
operator-set YES retracted). Draft existence recorded separately:
`PROSPECTIVE_GUARD_SHADOW_PLAN_DRAFT_EXISTS = YES`;
`PROSPECTIVE_GUARD_SHADOW_PLAN_STATUS = DORMANT_POST_HOC_DRAFT`;
`PROSPECTIVE_GUARD_SHADOW_ACTIVATED = NO`. Draft retained unchanged, NOT APPROVED, NOT
ACTIVATED. Shadow V1.1 and production V1 untouched.

**Artifacts:** `LIQUIDITY_GUARD_RESULTS.md` rev2 `841edc6d…17df7` → rev3
`969a97c2895c90b45a6615088a81cf0d59dff347a0aa23c9bd5b8576a9287536` (rev3 header, L4 STATUS
section, Part 5 scope note, Part 10 official-comparison paragraph, Part 11 §6e note, FINAL
STATUS replaced); `PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md`
`056a1044…039c` → `e24103657bfb84fc67170ef63d71ae52e4f91493910c6618232837a13317ef36` (one
official-status paragraph added). Unchanged, re-verified: defs `5a3b454d…3bc4`, closure
`44a86743…f418`, `guard_backtest.py` `973f34bc…2085`.

Standing Message A wait-state unchanged; production Signal Engine not started; SQL Server
disabled.
