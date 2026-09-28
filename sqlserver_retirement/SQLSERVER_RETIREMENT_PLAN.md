# SQL SERVER RETIREMENT PLAN

## Current stage

**Ingestion: STAGE_1** (PostgreSQL canonical-primary, SQL Server mirror/fallback).
**Application reads/auth/portfolio: STAGE_0** (SQL Server still authoritative and
required).

Overall the repository does **not** satisfy STAGE_2 or STAGE_3: the full current
application is not operational with SQL Server offline.

| Stage | Definition | Satisfied? |
| --- | --- | --- |
| STAGE_0 | SQL Server authoritative/required | application reads/auth: **yes** |
| STAGE_1 | PostgreSQL canonical-primary, SQL Server mirror/fallback | ingestion: **yes** |
| STAGE_2 | PostgreSQL primary, SQL Server optional fallback | **no** |
| STAGE_3 | PostgreSQL standalone, SQL Server offline-safe | **no** |
| STAGE_4 | SQL Server retired/archive only | **no** |

## True PostgreSQL-primary requirements — checklist

| Requirement | Status |
| --- | --- |
| Application starts without SQL Server | **PASS** (lazy pool, no init connect) |
| Canonical ingestion operates without SQL Server | **PARTIAL** (market/monthly/codal yes; financial no; real scripts coupled) |
| Core financial reads operate without SQL Server | **FAIL** (handlers read SQL first) |
| Analytics/score reads operate without SQL Server | **FAIL** (summary/AllCompanyScores/CompanyScores read SQL first) |
| Active React pages operate without SQL Server | **FAIL** |
| Authentication has a PostgreSQL path or explicit exemption | **FAIL** (SQL only) |
| Portfolio/family have a PostgreSQL path or explicit exemption | **FAIL** (SQL only) |
| No required endpoint silently depends on SQL fallback | **FAIL** |
| Health clearly reports SQL Server offline as expected/retired | **FAIL** (no SQL component in health) |

## Blockers and smallest safe fixes (do not implement in this task)

Priority order per the task.

### 1. Startup/runtime coupling
- **Startup: not a blocker.** Keep the lazy `config.GetDB()`.
- Add a `sqlserver` component to `/api/health/shadow` (or a `/api/health/full`)
  that reports SQL Server reachable/unreachable and, when a retirement flag is
  set, reports it as `RETIRED_EXPECTED` rather than system failure.
  *Smallest fix:* a bounded `PingContext` with 2 s timeout + a
  `CDF_SQLSERVER_RETIRED` flag that changes the label.

### 2. Active reads (highest value)
- **SalesData2 / AllCompanyScores / CompanyScores / price-history:** reorder the
  handler so that when canonical serving is enabled (`CDF_FUND_CANARY_ENABLED` /
  `CDF_PRICE_HISTORY_CANARY_ENABLED` or endpoint CANONICAL mode), it attempts the
  canonical read **before** the legacy read, and only falls back to legacy when
  canonical fails. Today legacy runs first, so SQL offline always 500s.
  *Smallest fix:* guard the legacy computation behind `if route != RouteCanary ||
  canonical failed`.
- **CompanyNames:** add a canonical reader that unions `core.security_aliases`
  symbols (contract already documented) and serve it in CANONICAL mode.
- **summary:** serve canonical `analytics.company_scores` in CANONICAL mode
  (semantics differ by design; product decision required).

### 3. Authentication
- Add a PostgreSQL `auth.users` writer/reader (schema namespace `auth` already
  exists). *Smallest fix:* a read path for login (username/email + bcrypt hash +
  isAdmin) and a write path for register; a one-time copy of the 4 existing users
  from SQL Server. JWT stays DB-free.

### 4. Portfolio / family
- `portfolio` already has a canonical namespace. *Smallest fix:* persist holdings
  in a PostgreSQL `portfolio.holdings` table (replacing the `Users.Portfolio`
  JSON blob) and read live prices from canonical `market.price_observations` /
  analytics instead of `vw_AIStockMetrics`.
- `family` has no canonical schema yet; requires new tables under a
  `portfolio`/`family` namespace and a data copy. Larger; can be exempted
  explicitly in STAGE_2.

### 5. Legacy-only unused endpoints
- Disable/deprecate `StockPriceScore` (unrendered), `detail` (broken route),
  `analyze` (AI phase), `export/scores` (unused) behind a flag; stop fetching them
  from the client. No migration needed.

### 6. Python ingestion runtime coupling
- **Financial:** replace `_facts_from_db` (SQL read) with a canonical fact source
  or pass facts from the parser, so the canonical write no longer needs SQL
  Server.
- **Real scripts:** restructure each script to compute/parse rows and write
  canonical **first**, with SQL Server mirror optional and non-blocking; today the
  scripts establish the SQL connection before the hook. *Smallest safe step:*
  move the hook call before any SQL read, and make the legacy connection lazy.
  This is the subtlest change and should be done per domain with the existing
  authority flags and soak harness.

### 7. Mirrors/fallback cleanup
- Once reads are canonical-primary, switch canaries to `CANONICAL` endpoint mode
  and make fallback explicit: a retired SQL Server should make endpoints fail
  clearly (or serve canonical) rather than silently depend on legacy.

## Recommended sequencing

1. Reorder the four canaried handlers to canonical-first (fixes the biggest class
   of offline 500s).
2. Add canonical `CompanyNames` + `summary` serving and the SQL Server health
   component with a `RETIRED_EXPECTED` label.
3. Add PostgreSQL auth (login/register) + copy the 4 users.
4. Migrate portfolio holdings to PostgreSQL; exempt family explicitly for now.
5. Fix Python financial fact sourcing + script ordering (canonical-first).
6. Deprecate unused legacy endpoints; then reassess STAGE_2 → STAGE_3.

No redesign, no deletion of SQL Server data, no change to Model v1/v2 in this task.

---

## POST-DECOUPLING STATUS (this task)

Completed: steps 1–4 and 6 above.

| Step | Status |
| --- | --- |
| 1. Canonical-first handlers | **DONE** — 7 endpoints serve canonical before SQL; offline 200 |
| 2. Canonical CompanyNames + summary | **DONE** |
| 3. PostgreSQL auth + copy users | **DONE** — 4 users, offline login 200 |
| 4. Portfolio to PostgreSQL; family exemption | **DONE** — portfolio PG offline 200; family explicit 503 deferred |
| 5. Python financial facts + script ordering | **PARTIAL** — hook is SQL-free with `facts=`; real scripts still open SQL at startup |
| 6. Deprecate unused endpoints | **DONE** — StockPriceScore/detail/analyze/export classified deprecated |

### Stage

- Application core: **STAGE_3-ready** (all React-critical pages, auth, portfolio,
  score/analytics reads operate with SQL Server unreachable).
- Ingestion entrypoints: **STAGE_1** (real scripts still connect to SQL Server
  before the canonical write).
- Overall: **STAGE_2** (PostgreSQL primary; SQL Server optional fallback for
  admin/optional features and ingestion entrypoints).

### Remaining to reach STAGE_3

1. Reorder `brs_prices.py`, `MianSql.py`, `MianSql2.py`, `sync_codal.py` to
   canonical-first and pass parser facts into the financial hook.
2. Migrate or permanently disable the admin-optional features (`GetUrl`/`GetUrl2`,
   ingestion triggers, `viewed-items`) under `offline_expected`.
3. Keep SQL Server as archive/rollback/mirror only (no deletion).

---

## FINAL STATUS — STAGE_3 reached

Step 1 (Python script ordering) is now **DONE**: all four real entrypoints run
canonical-first with SQL Server unreachable (see `FINAL_INGESTION_DECOUPLING.md`).
Step 2: admin-optional features declared `ACTIVE_OPTIONAL`; family explicitly
deferred (`CDF_FAMILY_BACKEND=disabled`, 503 `deferred=true`). Step 3: SQL Server
retained.

| Stage | Status |
| --- | --- |
| STAGE_3 (PostgreSQL standalone, SQL Server offline-safe) | **SATISFIED** |
| STAGE_4 (delete) | not performed (by instruction) |

Gate: **`SQLSERVER_CAN_BE_STOPPED`** with executable proof of real ingestion plus
the full application offline.
