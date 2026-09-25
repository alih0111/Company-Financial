# INGESTION INVENTORY

Read-only inventory of the active ingestion flows feeding the current SQL Server
application, and their canonical PostgreSQL destinations. Machine-readable:
`ingestion_inventory.csv`.

Source of truth: repository at the current revision (py/ legacy stack, py2
clean-room stack, 6 Go `os/exec` triggers) plus the canonical schema
`canonical_postgres_v1_2_1`.

## 1. Domains and flows

| Domain | Entrypoint | Legacy tables | Canonical destination | Mapping proven | Dual-write |
| --- | --- | --- | --- | --- | --- |
| MONTHLY_ACTIVITY | `py/MianSql2.py` via `scraper2.py`, `codal_processor.py`, `sync_codal.py` | `mahane` | `fundamentals.monthly_activities` | yes | **yes** |
| FINANCIAL_STATEMENT | `py/MianSql.py` via `scraper.py`, `codal_processor.py` | `miandore2` | `fundamentals.financial_statements`, `fundamentals.financial_facts` | yes | **yes** |
| CODAL_REPORT | `py/sync_codal.py` + `codal_feed.py`/`codal_registry.py`/`codal_prefilter.py` | `CodalReports`, `CodalSyncState` | `ingestion.reports`, `ingestion.report_versions`, `ingestion.parse_runs`, `raw.report_payloads` | partial (chain) | **yes (writer)** |
| MARKET_PRICE | `py/brs_prices.py` (also `py/price.py`) | `MarketPriceHistory` | `market.price_observations` | yes | **yes** |
| IDENTITY_METADATA | `py/codal_universe.py` + migration tools | `TrackedTickers`, source ins codes | `core.*` (+ `legacy_entity_map`, `security_aliases`) | yes | resolution only |
| OTHER | `py/scraperFullPE.py`, `py/family_import.py`, backfill/_apply_view | `FullPE`, `Family*`, view DDL | none / `portfolio.*` | n/a | no (out of scope) |
| py2 stack | `py2/src/codal_ingestor` | — (its own PG schema) | **not** canonical schema | no | no |

### Notes per flow

- `mahane.Value1/Value2` = monthly production/sales quantity; `Value3` = monthly
  sales/revenue in **million_rial** (verified against
  `reported_sales_amount`). Canonical `sales_amount_rial = Value3 × 1e6`.
- `miandore2` financial columns map through the migration `FACT_MAP` only
  (`eps`, `operating_eps`, `capital`, `operating_profit`, `finance_cost`,
  `other_non_operating`, `revenue`, `net_profit`, balance-sheet and cash-flow
  metrics). `Product1/2/3` (legacy `EPS × Capital` heuristics) are **never**
  written as canonical facts.
- `MarketPriceHistory.CollectedAt` is the actual source collection time and is
  preserved as `market.price_observations.collected_at` (new ingestion must not
  use migration time).
- `CodalReports` provides report metadata; the canonical chain is
  report → report_version (content hash) → parse_run (parser execution) →
  normalized output.
- `py2` targets a **separate, non-canonical** PostgreSQL schema and is not part
  of the canonical application path; reconcile in Phase 3.

## 2. Go `os/exec` ingestion triggers (unchanged this phase)

`run-script`, `run-script2`, `fetchAllData`, `FetchFullPE`, `brs/collect`,
`sync-codal`. See `GO_INGESTION_TRIGGER_PLAN.md` for the future canonical
routing plan. No Go code was changed in this phase.

## 3. Classification

`CODAL_REPORT`, `MONTHLY_ACTIVITY`, `FINANCIAL_STATEMENT`, `MARKET_PRICE`,
`IDENTITY_METADATA`, `OTHER` as in the CSV. Auth/portfolio/family write paths are
`OTHER` and explicitly out of scope.
