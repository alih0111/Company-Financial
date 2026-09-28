# SQL SERVER DEPENDENCY AUDIT

Executable audit of every remaining runtime SQL Server dependency, verified
against current code (not prior docs). Machine-readable:
`output/sqlserver_dependencies.csv`.

## Method

Searched all Go, Python, React/TS, scripts, config and `.env` for
`go-mssqldb`, `pyodbc`, `dbo.*`, `codal.dbo`, `config.GetDB`, `DB_SERVER`,
`sqlserver_conn`, `os/exec` script triggers; then traced each hit to the live
call path and ran an offline test (`cmd/offlinetest`) plus an ingestion probe
(`probe_ingestion_offline.py`).

## Classification rules

`READ_REQUIRED`/`WRITE_REQUIRED` = active path needs SQL Server;
`MIRROR_ONLY`/`FALLBACK_ONLY` = SQL Server is secondary;
`LEGACY_UNUSED` = endpoint exists but no active client use;
`TEST_ONLY`/`MIGRATION_ONLY` = harness/tooling; `DEPRECATED` = compatibility only.

## Summary by layer

### Go API — application (active)

| Endpoint | SQL Server object | Type | Blocker |
| --- | --- | --- | --- |
| `/api/login` | `Users` (SELECT/UPDATE) | WRITE_REQUIRED | **YES** |
| `/api/register` | `Users` (SELECT/INSERT) | WRITE_REQUIRED | **YES** |
| `/api/users/get-items` | `Users.ViewedItems` | WRITE_REQUIRED | **YES** |
| `/api/CompanyNames` | `miandore2` | READ_REQUIRED | **YES** |
| `/api/SalesData` | `miandore2` | READ_REQUIRED | **YES** |
| `/api/SalesData2` | `mahane` (legacy read first) | READ_REQUIRED | **YES** |
| `/api/CompanyScores` | `mahane`,`miandore2`,`FullPE` | READ_REQUIRED | **YES** |
| `/api/AllCompanyScores` | `mahane`,`miandore2`,`FullPE` | READ_REQUIRED | **YES** |
| `/api/summary` | `vw_AIStockMetrics` | READ_REQUIRED | **YES** |
| `/api/price-history` | `MarketPriceHistory` | READ_REQUIRED | **YES** |
| `/api/portfolio` | `Users.Portfolio` + `vw_AIStockMetrics` | WRITE_REQUIRED | **YES** |
| `/api/family/*` | `Family*` | WRITE_REQUIRED | **YES** |
| `/api/GetUrl`,`/api/GetUrl2` | `miandore2`,`mahane` | READ_REQUIRED | **YES** (ScriptModal) |
| ingestion triggers (`/api/brs/collect`, `/api/sync-codal`, `/api/run-script*`, `/api/fetchAllData`, `/api/FetchFullPE`) | scripts | WRITE_REQUIRED | **YES** (admin) |

### Go API — legacy/unused (not a shutdown blocker)

| Endpoint | Use | Classification |
| --- | --- | --- |
| `/api/detail` | route lacks `:companyID`; not client-called | LEGACY_UNUSED |
| `/api/analyze` | not client-called; AI phase | LEGACY_UNUSED |
| `/api/export/scores` | not client-called | LEGACY_UNUSED |
| `/api/StockPriceScore` | client fetches but **never renders** (`App.tsx` destructures `stockPriceScore`, unused) | DEPRECATED_SAFE_TO_DISABLE |

### Go startup / middleware (safe)

- `config/db.go`: builds the connection string at `init()` and opens lazily; **no
  connection or ping at startup**. `GetDB()` returns a lazy pool.
- `middleware/auth.go`: `init()` loads `.env` only; JWT verification is DB-free.
- `handlers/auth.go`: `init()` loads `.env` only.
- No `MustConnect`, no startup ping, no DB init job.

**Conclusion: the Go server starts with SQL Server offline** (proven in the
offline test; only `.env` must be present).

### Python ingestion

| Component | Type | Offline behaviour |
| --- | --- | --- |
| `canonical_hook` MARKET / MONTHLY / CODAL authoritative | canonical write first | **continues**, mirror DEGRADED |
| `canonical_hook` FINANCIAL (`_facts_from_db`) | READ_REQUIRED | **CANONICAL_FAILED** |
| real scripts `brs_prices.py`, `MianSql.py`, `MianSql2.py`, `sync_codal.py` | RUNTIME_COUPLING | **cannot reach the hook** (connect fails) |
| `canonical_ingest` writer package | pure PostgreSQL | works |
| migration drivers/tools, legacy backtests | MIGRATION_ONLY / LEGACY_UNUSED | n/a |

## Blocker categories

### CRITICAL_SHUTDOWN_BLOCKER
1. `config`/`middleware`/`handlers` **startup is safe**, but every active read
   handler calls `config.GetDB()` unconditionally before any canonical path, so
   the active React experience is unavailable without SQL Server.
2. Python ingestion runtime coupling: the real scripts connect to SQL Server
   before invoking the canonical hook.
3. Financial canonical path reads facts from SQL Server (`_facts_from_db`).

### ACTIVE_FEATURE_BLOCKER
- Authentication (`Users`), Portfolio (`Users.Portfolio`), Family (`Family*`),
  Viewed-items, URL lookups, ingestion triggers.

### OPTIONAL_LEGACY_DEPENDENCY
- `StockPriceScore`, `detail`, `analyze`, `export/scores`.

### SAFE_TO_IGNORE
- Migration tooling, legacy backtests, `.env` presence.

### SAFE_TO_DEPRECATE
- `StockPriceScore` (unrendered), `detail` (broken route), `analyze`
  (AI-later), `export/scores` (unused).

---

## POST-DECOUPLING UPDATE (this task)

Refreshed inventory: `output/sqlserver_dependencies_after.csv`.

Resolved (now SQL-free for active use):
- **Reads** — CompanyNames, SalesData, SalesData2, CompanyScores, AllCompanyScores,
  summary, price-history are now **canonical-first** (canonical served before any
  SQL Server call). Offline result: HTTP 200.
- **Auth** — `CDF_AUTH_BACKEND=postgres` serves login/register from `auth.users`;
  4 users migrated.
- **Portfolio** — `CDF_PORTFOLIO_BACKEND=postgres` uses the canonical `portfolio`
  namespace; migrated and offline 200.
- **Financial ingestion** — `ingest_financial_authoritative_by_key(..., facts=...)`
  writes canonical facts from normalized in-memory parser output; SQL Server is
  no longer the transport.
- **Family** — explicit `CDF_FAMILY_BACKEND=disabled` → 503 `deferred=true`.

Remaining non-core references (classification):
- `MIRROR_ONLY`: ingestion legacy mirror writes.
- `ROLLBACK_ONLY`: auth/portfolio SQL backends, financial `facts=None` fallback.
- `MIGRATION_ONLY` / `TEST_ONLY`: migration tools, offline canary harnesses.
- `DEPRECATED`: StockPriceScore, detail, analyze, export/scores.
- `ACTIVE_OPTIONAL` (admin/side-effect, not migrated): GetUrl/GetUrl2, ingestion
  triggers, viewed-items.
- `RUNTIME_COUPLING` (remaining blocker for the ingestion *entrypoints*, not the
  hook): the four real Python scripts open SQL Server at startup.

`CRITICAL_SHUTDOWN_BLOCKER` and `ACTIVE_FEATURE_BLOCKER` counts for **core React
financial functionality**: 0.
