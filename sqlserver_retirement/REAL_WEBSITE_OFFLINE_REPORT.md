# REAL WEBSITE SQL SERVER OFFLINE REPORT

**Gate: `REAL_WEBSITE_SQLSERVER_OFFLINE_PASS`**

SQL Server was ACTUALLY STOPPED; the live website was returning a SQL error.
This report is based on the running backend and the real HTTP path, not harnesses.

## 1. Reproduced failure and root cause

Observed live error:
```
unable to open tcp connection with host 'localhost:1433': ... actively refused it
```

Call chain (real):
```
React (http://rfa_back.systemgroup.net/api)
  -> HTTP.SYS reverse proxy rfa_back.systemgroup.net:80
  -> Go backend :5000  (go run main.go)
  -> a read handler calling config.GetDB()   [read mode defaulted to LEGACY]
  -> go-mssqldb
  -> localhost:1433  (SQL Server STOPPED)
```

Root cause: the **live process environment had no `CDF_*` retirement
configuration**. `go-app/.env` contained only DB/SMTP/JWT/BRS keys, so:
- `CDF_READ_MODE` unset → global read mode **LEGACY**;
- `CDF_AUTH_BACKEND`/`CDF_PORTFOLIO_BACKEND`/`CDF_FAMILY_BACKEND` unset → default
  **sqlserver**;
- fund/price canaries disabled.

The previous `SQLSERVER_CAN_BE_STOPPED` conclusion was correct for the harness
(in-process env) but the **real process was never configured/restarted with the
retirement environment**, so it still attempted `localhost:1433`.

## 2. Effective runtime environment BEFORE the fix

From the pre-fix process behaviour (no `CDF_*` present):

| Variable | Effective |
| --- | --- |
| `CDF_CANONICAL_DB` | (unset) → DATABASE_URL `postgres` default db |
| `CDF_INGESTION_MODE` | (unset) → `legacy_only` |
| `CDF_SQLSERVER_MODE` | (unset) → `active` |
| `CDF_MARKET/MONTHLY/FINANCIAL/CODAL_INGESTION_AUTHORITY` | (unset) → `legacy` |
| `CDF_AUTH_BACKEND` | (unset) → `sqlserver` |
| `CDF_PORTFOLIO_BACKEND` | (unset) → `sqlserver` |
| `CDF_FAMILY_BACKEND` | (unset) → `sqlserver` |
| `CDF_FUND_CANARY_ENABLED` / `CDF_PRICE_HISTORY_CANARY_ENABLED` | (unset) → false |
| `CDF_READ_MODE` | (unset) → `legacy` |

Stale process: the old backend PID 44352 (started 07:17) predated the retirement
work. It was replaced (PID 15784) and then a clean restart (PID 40260) was
performed to guarantee the latest code + configuration.

## 3. Fix made

1. **Environment (durable)** — added the retirement configuration to
   `go-app/.env` so every launch is correct:
   `CDF_CANONICAL_DB`, `CDF_INGESTION_MODE=dual_write`,
   `CDF_SQLSERVER_MODE=offline_expected`, all four
   `CDF_*_INGESTION_AUTHORITY=canonical`, `CDF_AUTH_BACKEND=postgres`,
   `CDF_PORTFOLIO_BACKEND=postgres`, `CDF_FAMILY_BACKEND=disabled`,
   `CDF_FUND_CANARY_ENABLED=true`, `CDF_PRICE_HISTORY_CANARY_ENABLED=true`.
2. **Code invariant** (`integration`): when `CDF_SQLSERVER_MODE=offline_expected`,
   `ModeFor` **always returns CANONICAL**, and `PriceHistoryRoute`,
   `SalesDataRoute`, `SalesData2Route`, `CompanyScoresRoute`, `CompanyNamesRoute`,
   `SummaryRoute`, `AllCompanyScoresRoute` **never return LEGACY** — even for
   legacy global mode or unsafe identities.
3. **No legacy fallback in offline mode** (`price_history.go`): canonical fetch
   directly; on failure an explicit `503` with `reason=sqlserver_offline_expected`;
   SQL Server is never contacted.
4. **Residual SQL handlers gated**: `StockPriceScore` (200 deprecated payload),
   `users/get-items` (200 no-op), `GetUrl`/`GetUrl2` (503), `export/scores`,
   `detail`, `analyze`, `FetchFullPE` (503), family (503 deferred), and the
   `RunBrsCollector` family-sync skips SQL.
5. **Config fail-safes** (`config`): with `offline_expected`, `AuthBackend` and
   `PortfolioBackend` force `postgres`, `FamilyBackend` forces `disabled`
   regardless of contradictory env.
6. **Backend restart**: killed stale `go.exe`/`main.exe`, relaunched
   `go run main.go` in `go-app` (PID 40260). SQL Server was NOT restarted.

## 4. Effective runtime environment AFTER the fix

| Variable | Effective |
| --- | --- |
| `CDF_SQLSERVER_MODE` | `offline_expected` |
| `CDF_CANONICAL_DB` | `company_financial_analytics_shadow_v121` |
| `CDF_INGESTION_MODE` | `dual_write` |
| `CDF_AUTH_BACKEND` | `postgres` |
| `CDF_PORTFOLIO_BACKEND` | `postgres` |
| `CDF_FAMILY_BACKEND` | `disabled` |
| `CDF_*_INGESTION_AUTHORITY` | `canonical` (all four) |
| `CDF_FUND_CANARY_ENABLED` / `CDF_PRICE_HISTORY_CANARY_ENABLED` | `true` |

`/api/health/shadow` reports: `postgres_status=HEALTHY`,
`sqlserver_status=RETIRED_EXPECTED`, `sqlserver_required=false`,
`sqlserver_mode=offline_expected`, `overall=HEALTHY`.

## 5. Real HTTP results (SQL Server stopped)

Via `http://localhost:5000` and via the real proxy
(`http://localhost/api/...` with `Host: rfa_back.systemgroup.net`):

| Request | Result | SQL attempted |
| --- | --- | --- |
| `GET /api/health/shadow` | 200 | no |
| `POST /api/login` (postgres) | 200 + JWT | no |
| `GET /api/CompanyNames` | 200 | no |
| `GET /api/SalesData` | 200 | no |
| `GET /api/SalesData2` | 200 | no |
| `GET /api/CompanyScores` | 200 | no |
| `GET /api/AllCompanyScores` | 200 | no |
| `GET /api/summary` | 200 | no |
| `GET /api/price-history` | 200 | no |
| `GET /api/StockPriceScore` | 200 deprecated/unsupported (no SQL) | no |
| `POST /api/users/get-items` | 200 accepted (persisted:false) | no |
| `GET /api/portfolio` | 200 (postgres) | no |
| `GET /api/family/assets` | 503 explicit deferred | no |
| unsafe identity `شکیمیا` / `خاهن` via SalesData2 | 503 explicit canonical-unavailable | no |

Proxy path (`rfa_back.systemgroup.net`) verified: `health 200`,
`CompanyNames 200`.

## 6. Network-level proof

A 400-iteration `netstat` poll for `:1433` run concurrently with a burst across
all active endpoints recorded **0** matches. No active supported website request
attempted `localhost:1433`.

## 7. Regression guard

`go-app/integration/offline_test.go`:
- `TestOfflineExpectedForcesCanonicalMode` — `ModeFor` returns canonical, `AnyShadow` true.
- `TestOfflineExpectedRoutesNeverLegacy` — all seven routes return `RouteCanary`
  even for an unsafe identity.

`go test ./...` passes.

## 8. Remaining notes

- `score_stale=true` (canonical market data newer than the last score run). This
  is the analytics freshness signal, unrelated to SQL Server; run
  `orchestrate_refresh.py --mode RUN_IF_STALE` if a fresh score is desired.
- `read_mode` in health shows the global value (`legacy`) while effective routing
  is forced canonical under `offline_expected`; this is cosmetic.
- SQL Server is retained (not deleted).
