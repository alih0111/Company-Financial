# SQL SERVER REMAINING DEPENDENCIES

Exact inventory of what still prevents application-level PostgreSQL-primary
operation. SQL Server is retained as mirror/fallback/rollback; nothing here was
removed. Counts are live row counts (2026-09-25).

## 1. READS — legacy-authoritative endpoints (not yet canonical-served)

Canonical SHADOW implementations exist for these; the *served* response is still
SQL Server (default `CDF_READ_MODE=legacy`).

| Route | SQL Server source | Canonical status |
| --- | --- | --- |
| `GET /api/AllCompanyScores` | `mahane`, `miandore2`, `FullPE` | SHADOW ready, not served |
| `GET /api/CompanyScores` | `mahane`, `miandore2`, `FullPE` | SHADOW ready, not served |
| `GET /api/summary` | `vw_AIStockMetrics` | SHADOW ready, not served (semantic change) |
| `GET /api/SalesData` | `miandore2` | SHADOW ready, not served (presentation) |
| `GET /api/SalesData2` | `mahane` | SHADOW ready, not served (presentation) |
| `GET /api/CompanyNames` | `miandore2` | SHADOW ready, not served (identity presentation) |
| `GET /api/price-history` | `MarketPriceHistory` | canary-capable (5% identity-guarded rollout) |
| `POST /api/GetUrl`, `POST /api/GetUrl2` | `miandore2.Url`, `mahane.Url` | not migrated |

## 2. READS — no canonical implementation (out of scope now)

| Route | SQL Server source | Reason |
| --- | --- | --- |
| `GET /api/StockPriceScore` | `dbo.StockData` (32,958) | technical indicators, out of current model |
| `GET /api/detail` | `vw_AIStockMetrics`, `mahane`, `miandore2`, `MarketPriceHistory` | route lacks `:companyID`; adaptable later |
| `POST /api/analyze` | `vw_AIStockMetrics` + external LLM | LEGACY_AI_ONLY, later phase |

## 3. WRITES

| Domain | SQL Server object | Notes |
| --- | --- | --- |
| AUTH | `Users` (4 rows) | register/login, `IsOnline`, `Token`, `ViewedItems` |
| PORTFOLIO | `Users.Portfolio` (NVARCHAR(MAX)) | holdings persisted per user |
| FAMILY | `FamilyAccounts`, `FamilyAssets`, `FamilyCashFlows`, `FamilyHistory`, `FamilyHoldings`, `FamilyPeople`, `FamilyPrices` | family asset accounting |
| INGESTION legacy write | `mahane`, `miandore2`, `MarketPriceHistory`, `CodalReports`, `CodalSyncState` | legacy scripts write first, canonical hook mirrors |

Auth and portfolio/family writes are explicitly **out of scope** for the read
migration task and must not be mixed in.

## 4. MIRRORS

- `go-app/py/canonical_hook.py` mirrors canonical-authoritative ingestion back to
  SQL Server (market/monthly/financial/codal). Mirror failure does not invalidate
  the canonical write (`CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`).
- Legacy scripts (`brs_prices.py`, `MianSql.py`, `MianSql2.py`, `sync_codal.py`)
  remain the SQL Server writers.

## 5. FALLBACKS / ROLLBACK

- Per-domain config: `CDF_MARKET_INGESTION_AUTHORITY=legacy`,
  `CDF_MONTHLY_INGESTION_AUTHORITY=legacy`,
  `CDF_FINANCIAL_INGESTION_AUTHORITY=legacy`,
  `CDF_CODAL_INGESTION_AUTHORITY=legacy`.
- `CDF_MARKET_FALLBACK_LEGACY` etc. control continuity writes on canonical failure.
- Go read rollback: `CDF_READ_MODE=legacy`, `CDF_PRICE_HISTORY_CANARY_ENABLED=false`.

## 6. AUTH

`Users` (4 rows) is the auth store. Not migrated.

## 7. PORTFOLIO

`Users.Portfolio` JSON blob. Not migrated.

## 8. LEGACY_AI

- `POST /api/analyze` external LLM (`AI_CHAT_URL`/`AI_API_KEY`) over legacy rows.
- Not deterministic scoring; LLM may only assist explanation.

## 9. DEPRECATED / compatibility-only

| Object | Rows | Status |
| --- | --- | --- |
| `CodalReports` | 48 | legacy sync registry, superseded by canonical `ingestion.*` |
| `CodalSyncState` | 2 | legacy watermark |
| `dbo.vw_AIStockMetrics` | 276 | **v3.7 compatibility oracle** (frozen), not future architecture |
| `FullPE` | 244 | legacy PE/price cache (analytics factor `PE` is canonical) |
| `TrackedTickers` | 282 | universe seed, still consumed by codal sync |

## Summary: what blocks PostgreSQL-primary reads

1. **Served response** still SQL Server for the seven SHADOW endpoints (gated on
   canary evidence; not a data gap).
2. **Canonical `AllCompanyScores`/`CompanyScores`** return factor-derived
   presentation values; canary decision pending.
3. **Presentation** (`percentage`/`wow`) for `SalesData` income statement has no
   canonical equivalent (Product1 heuristic); `SalesData2` is defined and ready.
4. **Score semantics**: `/api/summary` intentionally differs from v3.7; product
   decision required.
5. **Auth/portfolio/family writes** and **StockPriceScore/detail/analyze** remain
   SQL Server.

Machine-readable: `output/sqlserver_remaining_dependencies.csv`.
