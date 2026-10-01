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
