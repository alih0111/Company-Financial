# SQL SERVER OFFLINE TEST REPORT (POST-DECOUPLING)

Executable proof that the active application works with SQL Server completely
unreachable. SQL Server was **not stopped or modified**: the Go server was pointed
at an unreachable host:port (`DB_SERVER=127.0.0.1,59999`) so the lazy pool never
connects. PostgreSQL (shadow) remained online.

- Harness: `go-app/cmd/offlinetest` (real handlers, httptest).
- Raw results: `output/sqlserver_offline_endpoints.csv`, `output/sqlserver_offline_test.json`.
- Ingestion probe: `probe_ingestion_offline.py` → `output/ingestion_offline_final.json`.
- Auth/portfolio migration: `migrate_auth_portfolio.py`.

## Configuration under test

```
DB_SERVER=127.0.0.1,59999            # SQL Server unreachable
CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
CDF_FUND_CANARY_ENABLED=true
CDF_FUND_CANARY_COMPANIES=کسرا,چکاپا,وسپه,خودرو
CDF_PRICE_HISTORY_CANARY_ENABLED=true
CDF_PRICE_HISTORY_CANARY_SYMBOLS=وسپه,خودرو
CDF_AUTH_BACKEND=postgres
CDF_PORTFOLIO_BACKEND=postgres
CDF_FAMILY_BACKEND=disabled
CDF_SQLSERVER_MODE=offline_expected
```

## Endpoint outcomes

| Endpoint | HTTP | Class |
| --- | --- | --- |
| `GET /api/health/shadow` | 200 | CANONICAL_OK (overall HEALTHY) |
| `POST /api/login` | 200 | OK_WITHOUT_SQLSERVER (JWT issued) |
| `GET /api/CompanyNames` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/SalesData` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/SalesData2` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/CompanyScores` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/AllCompanyScores` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/price-history` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/summary` | 200 | OK_WITHOUT_SQLSERVER |
| `GET /api/portfolio` | 200 | OK_WITHOUT_SQLSERVER (PostgreSQL) |
| `GET /api/family/assets` | 503 | DEFERRED_OK (explicit deferral) |
| `GET /api/StockPriceScore` | 500 | DEPRECATED_SAFE_TO_DISABLE |
| `GET /api/export/scores` | 500 | LEGACY_UNUSED |

Counts: `CANONICAL_OK=1`, `OK_WITHOUT_SQLSERVER=9`, `DEFERRED_OK=1`,
`DEPRECATED_SAFE_TO_DISABLE=1`, `LEGACY_UNUSED=1`, `SQLSERVER_REQUIRED_FAIL=0`.

## Startup

`server_startup_ok=true`, `sqlserver_reachable=false` — the Go server starts and
serves with no SQL Server connection.

## Health

`/api/health/shadow` reports `postgres_status=HEALTHY`, `sqlserver_status=RETIRED_EXPECTED`,
`sqlserver_required=false`, `sqlserver_mode=offline_expected`, `overall=HEALTHY`.
A retired SQL Server does not mark the application unhealthy.

## Ingestion (SQL Server unreachable)

| Domain | Outcome |
| --- | --- |
| MARKET_PRICE | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` |
| MONTHLY_ACTIVITY | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` |
| CODAL | `CANONICAL_SUCCESS_LEGACY_SUCCESS` |
| FINANCIAL (in-memory facts) | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` |
| FINANCIAL (legacy fallback, `facts=None`) | `CANONICAL_FAILED` (rollback only) |
| real script `_sqlserver_conn()` | `OperationalError 08001` (scripts remain coupled) |

## Exact remaining non-core failures

- `StockPriceScore`, `export/scores`, `detail`, `analyze` — deprecated/unused.
- `family/*` — explicitly deferred (503).
- admin script triggers + `GetUrl/GetUrl2` + `viewed-items` — SQL-coupled.
- Python real ingestion scripts establish SQL before the (now SQL-free) hook.

---

## FINAL UPDATE — real ingestion + Go-trigger offline (STAGE_3)

`prove_real_ingestion_offline.py` (SQL Server unreachable, canonical authority):

| Domain | Entrypoint | Result | SQL connected |
| --- | --- | --- | --- |
| MARKET_PRICE | `brs_prices.cmd_daily` | EXECUTED, canonical inserted 269 | no |
| MONTHLY_ACTIVITY | `MianSql2.save_report_to_sql` | EXECUTED | no |
| FINANCIAL_STATEMENT | `MianSql.save_profit_loss_to_sql` | EXECUTED (in-memory facts) | no |
| CODAL | `sync_codal.run_sync` | EXECUTED (canonical-only, 0 errors) | no |

Go-trigger (real `POST /api/brs/collect` → `exec python py/brs_prices.py daily`):
**HTTP 200 `GO_TRIGGER_OK`**, SQL Server unreachable.

Full offline endpoint retest: `OK_WITHOUT_SQLSERVER=10`, `CANONICAL_OK=1`,
`GO_TRIGGER_OK=1`, `DEFERRED_OK=1`, `DEPRECATED=1`, `LEGACY_UNUSED=1`,
**`SQLSERVER_REQUIRED_FAIL=0`**. `server_startup_ok=true`.

Artifacts: `output/real_ingestion_offline_proof.csv`,
`output/go_trigger_offline_proof.csv`, `output/sqlserver_retirement_final.json`.
