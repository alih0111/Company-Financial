# Test Environment (PHASE A)

- generated_at (UTC): 2026-09-24T19:49:58+00:00
- isolation method: **local PostgreSQL instance, brand-new dedicated database**
- docker: **not available** (fallback branch used)
- PostgreSQL server_version: 18.4 (num 180004)
- host: localhost
- port: 5432
- maintenance user: (redacted)
- maintenance database (used only for CREATE DATABASE): postgres
- **test database: company_financial_test_v121**
- test database newly created in this run: True
- credentials: NOT stored (never printed)

## Safety confirmation
- The py2 production database `postgres` is **never** used for DDL/DML.
- All DDL/DML below target only `company_financial_test_v121`.
- A name guard rejects any target DB not starting with `company_financial_test_`.
- No SQL Server connection is made.
