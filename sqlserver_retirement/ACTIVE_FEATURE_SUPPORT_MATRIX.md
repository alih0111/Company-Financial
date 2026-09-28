# ACTIVE FEATURE SUPPORT MATRIX (SQL Server offline)

Executable result with SQL Server unreachable
(`CDF_FUND_CANARY_ENABLED=true`, `CDF_PRICE_HISTORY_CANARY_ENABLED=true`,
`CDF_AUTH_BACKEND=postgres`, `CDF_PORTFOLIO_BACKEND=postgres`,
`CDF_FAMILY_BACKEND=postgres`, `CDF_SQLSERVER_MODE=offline_expected`).

| Feature / endpoint | Classification | Offline result | React-critical |
| --- | --- | --- | --- |
| Go server startup | STARTUP_SAFE | starts, health 200 | yes |
| `GET /api/health/shadow` | SUPPORTED | 200, overall HEALTHY | yes |
| `POST /api/login` | SUPPORTED (PG) | 200 + JWT | yes |
| `POST /api/register` | SUPPORTED (PG) | works (needs email verification code) | yes |
| `GET /api/CompanyNames` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/SalesData` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/SalesData2` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/CompanyScores` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/AllCompanyScores` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/summary` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/price-history` | SUPPORTED (canonical) | 200 | yes |
| `GET /api/portfolio`, `POST`, `DELETE` | SUPPORTED (PG) | 200 | yes |
| Family assets (`/api/family/*`) | SUPPORTED (PG `family` namespace) | 200 (reads + writes) | admin-only |
| `GET /api/StockPriceScore` | DEPRECATED_SAFE_TO_DISABLE | 500 (unused by UI) | no |
| `GET /api/export/scores` | DEPRECATED_SAFE_TO_DISABLE | 500 (unused) | no |
| `GET /api/detail` | FUTURE_FEATURE | route broken | no |
| `POST /api/analyze` | FUTURE_FEATURE (AI) | 500 | no |
| `POST /api/GetUrl`, `/api/GetUrl2` | ACTIVE_OPTIONAL (admin) | 500 | admin-only |
| `POST /api/users/get-items` | ACTIVE_OPTIONAL | 500 | yes (non-fatal UI side-effect) |
| ingestion triggers (`/api/brs/collect`, `/api/sync-codal`, `/api/run-script*`) | ACTIVE_OPTIONAL (admin) | 500 | admin-only |

## React-critical coverage

The representative symbol page calls `CompanyNames`, `SalesData`, `SalesData2`,
`CompanyScores`, `AllCompanyScores`, `StockPriceScore`, `price-history` and
`/api/summary`. All **except `StockPriceScore`** return 200 with SQL Server
offline. `StockPriceScore` is fetched by the hook but **never rendered** by the
client, so its deprecation does not break any page.

## Family assets (PostgreSQL)

- **Family assets** (`/api/family/*`) are backed by the dedicated canonical
  PostgreSQL `family` namespace (`canonical_postgres_v1_2_1/sql/100_family.sql`,
  applied with `migration_tools/apply_family_schema.py`).
- Go handlers: `handlers/family_assets_pg.go`, dispatched from
  `handlers/family_assets.go` when `CDF_FAMILY_BACKEND=postgres`.
- Legacy `dbo.Family*` data migrated via `sqlserver_retirement/migrate_family.py`
  (preserves IDs; idempotent).
- `CDF_FAMILY_BACKEND=disabled` still yields an explicit `503 deferred=true`
  (kept as the default when SQL Server is `offline_expected` and no backend is
  set).

## Explicit deferrals

- **Admin script triggers + GetUrl/GetUrl2 + viewed-items** — optional admin /
  side-effect features; not required to render the core financial pages. Not
  migrated in this task.
