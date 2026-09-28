# FINANCIAL INGESTION DECOUPLING

Goal: the canonical financial write must not use SQL Server as an intermediate
transport. One normalized in-memory fact set feeds both the canonical writer and
(optionally) the legacy mirror, so they cannot diverge.

## Before (coupled)

```
legacy script -> SQL Server miandore2 write
canonical_hook._canonical_financial_write -> _facts_from_db(company_id, report_date) -> SQL Server read
  -> canonical_ingest.dual_write_financial
```
`_facts_from_db` connected to `dbo.miandore2`; with SQL Server offline the
canonical financial write returned `CANONICAL_FAILED` even in canonical-authority
mode.

## After (decoupled)

```
parser output (in memory)
  -> normalized facts (one representation)
  -> canonical_ingest.dual_write_financial   (canonical write, authoritative)
  -> optional legacy mirror
```

Implemented in `go-app/py/canonical_hook.py`:

- `_canonical_financial_write(company_id, report_date, facts=None)` — when
  `facts` is supplied, writes them directly; only falls back to the legacy
  `_facts_from_db` read when `facts is None`.
- `dual_write_financial_by_key(..., facts=None)` and
  `ingest_financial_authoritative_by_key(..., facts=None)` propagate the in-memory
  facts.

### Fact shape (one normalized representation)

```python
{"statement_type": "income_statement", "metric_code": "net_profit", "period_order": 1,
 "comparison_type": "current", "reported_value": Decimal("1234567"),
 "reported_unit": "million_rial", "canonical_value": Decimal("1.234567e12"),
 "canonical_unit": "rial", "kind": "m", "source_row_key": "income_statement:net_profit:1"}
```
`canonical_value` is the IRR/rial_per_share value; `reported_value` keeps the
source unit. Product1/2/3/NPUnitRatio/OpK/OpAmt remain forbidden and are asserted
out by the hook.

## Executable proof (SQL Server unreachable)

`probe_ingestion_offline.py` → `output/ingestion_offline_final.json`:

| Path | Outcome |
| --- | --- |
| financial, in-memory facts | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` (2 facts written, mirror injected-failed) |
| financial, legacy fallback (`facts=None`) | `CANONICAL_FAILED` (SQL read) — retained only as rollback |
| market / monthly / codal | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` / success |

## What remains (residual)

The **real scripts** (`MianSql.py`, `MianSql2.py`, `brs_prices.py`,
`sync_codal.py`) still open a SQL Server connection at startup and read
existing/registry rows before calling the hook. The hook itself is now SQL-free
for all domains, but the scripts must be reordered to:

```
source fetch -> normalize -> canonical write -> optional SQL mirror
```

and to pass parser facts into `ingest_financial_authoritative_by_key(..., facts=...)`.
Until that reordering lands, the canonical writer is decoupled and proven, but the
script entrypoints are not. This is the remaining ingestion blocker.
