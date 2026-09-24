# compat_v37 DDL — COMPATIBILITY_ONLY_NOT_CANONICAL

The schema below is created **only** on the isolated shadow database
`company_financial_analytics_shadow_v121`. It is disposable compatibility/test
state and is **not** part of Canonical PostgreSQL v1.2.1. It creates no canonical
company, security, statement, or fact, and is never applied to any canonical
schema (`core`, `ingestion`, `fundamentals`, `market`, `analytics`).

Created by `analytics_v37_compat/build_v37_compat_population.py`.

```sql
-- COMPATIBILITY_ONLY_NOT_CANONICAL
CREATE SCHEMA IF NOT EXISTS compat_v37;

CREATE TABLE IF NOT EXISTS compat_v37.scoring_subjects (
    legacy_subject_id     text PRIMARY KEY,   -- 'legacy:<legacy CompanyID>'
    legacy_company_id     text NOT NULL,      -- exact v3.7 subject identity
    company_name          text,
    symbol                text,
    instrument_code       text,
    canonical_company_id  uuid,               -- nullable; mapping only, never created here
    canonical_security_id uuid,
    has_monthly           boolean NOT NULL,
    has_financial         boolean NOT NULL,
    has_market_price      boolean NOT NULL,
    appears_in_v37        boolean NOT NULL,
    subject_origin        text,               -- 'mahane', 'miandore2', or 'mahane+miandore2'
    notes                 text
);
```

* Writes are guarded to the `company_financial_analytics_shadow_` prefix by
  `migration_tools/common.py` (`pg_pilot_conn`).
* The table is re-`TRUNCATE`d and reloaded idempotently on each build.
* `legacy_subject_id` deliberately uses the legacy identity, **not** a canonical UUID.
