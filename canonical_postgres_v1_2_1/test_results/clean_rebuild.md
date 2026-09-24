# Clean Rebuild (PHASE R)

- generated_at (UTC): 2026-09-24T20:01:01+00:00
- database: company_financial_test_v121 (dropped and recreated from zero)

## DDL

| file | status |
| --- | --- |
| 001_extensions.sql | PASS |
| 010_core.sql | PASS |
| 020_ingestion.sql | PASS |
| 030_raw.sql | PASS |
| 040_fundamentals.sql | PASS |
| 050_market.sql | PASS |
| 060_auth.sql | PASS |
| 070_portfolio.sql | PASS |
| 080_analytics.sql | PASS |
| 090_indexes.sql | PASS |

## pytest

```
74 passed in 13.23s
```

RESULT: PASS
