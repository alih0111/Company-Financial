# POSTGRES PORTFOLIO MIGRATION

## Result: COMPLETE (core) — PostgreSQL portfolio works with SQL Server offline

Canonical target: the existing `portfolio` namespace (no legacy view replica).

| Concept | Table |
| --- | --- |
| user portfolio | `portfolio.portfolios` (`portfolio_type='personal'`) |
| instrument | `portfolio.assets` (`security_id`, `asset_type='stock'`, name, symbol) |
| holding | `portfolio.positions` (`quantity`, `avg_cost_rial`, `cost_basis_rial`) |
| live price | `market.price_observations` (latest adjusted close, lateral subquery) |

- Backend switch: `CDF_PORTFOLIO_BACKEND=postgres|sqlserver` (default
  `sqlserver`).
- Handlers: `handlers/portfolio_pg.go` (`getPortfolioPG`, `upsertHoldingPG`,
  `deleteHoldingPG`), dispatched from `handlers/portfolio.go`.
- Identity: `core.legacy_entity_map` (security first, then company primary
  security); the legacy 32-hex company id is returned in `company_id` for client
  compatibility by reverse lookup. Names/symbols are presentation only.
- Enrichment (market value, gain, weight) uses canonical market data, **not**
  `vw_AIStockMetrics`.

## Migration

`migrate_auth_portfolio.py` (same run as auth):
- parses the legacy `Users.Portfolio` JSON array
  (`company_id`, `symbol`, `company_name`, `quantity`, `buy_price`, `buy_date`);
- ensures one `portfolio.portfolios` row per user (`name='default'`);
- resolves `security_id` via the explicit legacy map (0 unresolved);
- inserts `portfolio.assets` (idempotent by `security_id`) and upserts
  `portfolio.positions`.

Artifact: `output/portfolio_migration_summary.json` — 1 portfolio, 1 position,
0 unresolved securities; idempotent on re-run (positions re-upserted, no
duplicates).

## Residual

- `buy_date`, `note`, and the raw JSON blob format are not preserved (canonical
  uses transactions/positions). Buy date/notes can be recovered later via
  `portfolio.transactions`.
- The legacy JSON blob remains in SQL Server for rollback/archive.
