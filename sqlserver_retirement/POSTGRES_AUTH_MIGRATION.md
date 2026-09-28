# POSTGRES AUTH MIGRATION

## Result: COMPLETE — PostgreSQL auth works with SQL Server offline

- Canonical target: `auth.users` (`id uuid`, `username citext unique-ish`,
  `email citext`, `password_hash text`, `is_admin bool`, `is_active bool`,
  `created_at`, `updated_at`, `last_login_at`).
- Backend switch: `CDF_AUTH_BACKEND=postgres|sqlserver` (default `sqlserver` for
  rollback). Set `postgres` for retirement.
- Login/register: `handlers/auth_pg.go` (`loginPostgres`, `registerPostgres`),
  dispatched from `handlers/auth.go`. JWT issuance is unchanged; the middleware is
  DB-free.

## Migration

`sqlserver_retirement/migrate_auth_portfolio.py`:
- reads the 4 legacy `Users` rows (UserName, Email, Password, IsAdmin, Portfolio);
- upserts into `auth.users` by username. **An existing `password_hash` is never
  overwritten**; only email/is_admin/updated_at are refreshed.
- password hashes (bcrypt) are copied verbatim so existing credentials keep
  working; hashes are never logged or written to artifacts.

Idempotency (two runs):

| run | inserted | updated | users |
| --- | --- | --- | --- |
| 1 | 4 | 0 | arthur, ali, admin, samanehjoon |
| 2 | 0 | 4 | same (no duplicates) |

Artifact: `output/auth_migration_summary.json`.

## Credential compatibility

- Bcrypt hashes are portable across stores; the migration copies them unchanged.
- Proven end-to-end with an isolated test user
  (`offlinetest_user` / known password) created directly in `auth.users`:
  `POST /api/login` returned **200 + JWT while SQL Server was unreachable**.
- No password was reset or mutated.

## Rollback

Set `CDF_AUTH_BACKEND=sqlserver` to use the legacy `Users` path again. SQL Server
is not deleted.
