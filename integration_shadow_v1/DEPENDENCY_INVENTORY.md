# DEPENDENCY INVENTORY — Phase 1 Shadow Integration

> Scope: read-only inventory of the existing Go/Python application data dependencies,
> performed **before** any behavior change. Source of truth is the repository at
> revision `4fb0a04` plus the working tree changes described in
> `SHADOW_INTEGRATION_REPORT.md`.
>
> No credentials, JWT, passwords or connection strings are recorded here.

Machine-readable companion: `dependency_inventory.csv`.

## 1. Current Go DB architecture

- Framework: Gin (`go-app/main.go`). JWT-protected `/api` group.
- Single legacy backend: SQL Server `codal` via `go-app/config/db.go`.
  - `config.init()` loads `go-app/.env` and builds a `server=…;user id=…;password=…;database=…`
    string from `DB_SERVER`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
  - `config.GetDB()` calls `sql.Open("sqlserver", …)`. Every handler opens a **new**
    `*sql.DB` pool and defers `Close()`. There is no ORM usage despite `gorm` being
    an indirect dependency.
- Raw SQL is embedded directly in handlers. There is no repository layer today.
- Python is invoked by Go via `exec.Command("python", "py/<script>.py", …)` in 6 handlers.
- No Go tests existed before this phase.

## 2. Current Python DB architecture

- `go-app/py/` — legacy stack, **SQL Server via `pyodbc`**:
  - ingestion writers: `MianSql.py` (miandore2), `MianSql2.py` (mahane),
    `brs_prices.py`/`price.py` (MarketPriceHistory), `scraperFullPE.py` (FullPE),
    `sync_codal.py` + `codal_*.py` (CodalReports/CodalSyncState/TrackedTickers).
  - manual/one-off: `family_import.py`, `backfill_history.py`, `_backfill_v32.py`,
    `_apply_view.py`.
  - legacy analytics consumers (read-only): `backtest*.py` (file outputs only).
  - **No PostgreSQL anywhere in `py/`.**
- `go-app/py2/` — clean-room `codal-ingestor`, **PostgreSQL via SQLAlchemy + psycopg**:
  tables `companies`, `reports`, `report_versions`, `monthly_activities`,
  `financial_facts`; Alembic `0001_initial`; `DATABASE_URL` from `py2/.env`.
  It is **not invoked by Go** and is a *separate* ingestion stack.

## 3. Endpoint classification summary

| Class | Count | Examples |
| --- | --- | --- |
| LEGACY_READ | 2 | `config.GetDB`, health |
| LEGACY_WRITE | 16 | auth, portfolio, family, all ingestion scripts |
| CANONICAL_READ_CANDIDATE | 8 | CompanyNames, price-history, summary, sales data, export |
| NOT_READY_FOR_MIGRATION | 5 | in-Go legacy scoring, StockData, analyze/detail |
| OUT_OF_SCOPE | 15 | auth writes, family/portfolio writes, ingestion triggers |

Selected Phase-1 surface (3 read-only endpoints):

1. `GET /api/CompanyNames` → canonical `core.companies` identity.
2. `GET /api/price-history` → canonical `market.daily_prices`.
3. `GET /api/summary` → canonical `analytics.company_scores` (score-versioned).

## 4. Legacy SQL Server objects referenced

`Users`, `vw_AIStockMetrics`, `mahane`, `miandore2`, `FullPE`, `MarketPriceHistory`,
`StockData`, `FamilyPeople`, `FamilyAssets`, `FamilyHoldings`, `FamilyPrices`,
`FamilyAccounts`, `FamilyCashFlows`, `FamilyHistory`, `CodalReports`,
`CodalSyncState`, `TrackedTickers`, `StockData`.

## 5. Hidden coupling identified

- `scraperFullPE.py` writes with a **hard-coded** `localhost … Trusted_Connection=yes`
  connection while reading with env credentials. Not touched in Phase 1; flagged.
- `go-app/Stock/go/main.go` is a separate module with its own SQL Server bootstrap and
  a `python …/import_facts.py` call. Not wired into `go-app/main.go`; out of scope.
- Several handlers (`AIStockDetail`, `Analyze`) read the legacy scoring view and must
  not be converted to canonical analytics formulas in Go.
- `Portfolio`/family handlers perform DDL (`ALTER TABLE`, `CREATE TABLE`) as part of
  read paths. These are **write paths** and remain untouched.

## 6. Phase separation (explicit)

- **A. Application read integration** — this phase (3 endpoints).
- **B. Analytics consumption** — this phase, read-only, version-selected.
- **C. Ingestion write migration** — later phase (Python `py/` + `py2/`).
- **D. Portfolio/auth write migration** — later phase.

This phase performs A + B only.
