#!/bin/sh
set -eu
# PostgreSQL invokes this only when initializing an EMPTY volume. Never point
# this script at a populated database; updates use reviewed migrations/backups.
for migration in /schema/*.sql; do
    printf 'Applying schema: %s\n' "$(basename "$migration")"
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 --file "$migration"
done
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
    --set app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE rfa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
GRANT CONNECT ON DATABASE company_financial TO rfa_app;
GRANT USAGE ON SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat TO rfa_app;
GRANT SELECT ON ALL TABLES IN SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat TO rfa_app;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat TO rfa_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat TO rfa_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rfa_owner IN SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rfa_app;
ALTER DEFAULT PRIVILEGES FOR ROLE rfa_owner IN SCHEMA core, ingestion, raw, fundamentals, market, analytics, auth, portfolio, chat GRANT USAGE, SELECT ON SEQUENCES TO rfa_app;
SQL
