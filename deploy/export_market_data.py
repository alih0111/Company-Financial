"""Export only public-market schemas, excluding users and private portfolios."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, unquote

SCHEMAS = ('core', 'ingestion', 'raw', 'fundamentals', 'market', 'analytics')
IDENTITY_COLUMNS = 'id,source_system,source_table,legacy_key,entity_type,target_uuid,mapping_method,confidence,created_at'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True, help='local private backend .env')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from dotenv import dotenv_values
    values = dotenv_values(args.env_file)
    raw = next((values.get(key) for key in ('CANONICAL_DATABASE_URL', 'CDF_CANONICAL_URL', 'DATABASE_URL') if values.get(key)), '')
    parsed = urlsplit(raw.replace('postgresql+psycopg://', 'postgresql://'))
    if parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname:
        raise SystemExit('A valid PostgreSQL source URL is required in the selected environment file.')
    executable = shutil.which('pg_dump')
    if not executable:
        raise SystemExit('pg_dump must be installed and on PATH (use the server major version or newer).')
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith('PG'):
            environment.pop(name)
    environment.update({
        'PGHOST': parsed.hostname, 'PGPORT': str(parsed.port or 5432),
        'PGUSER': unquote(parsed.username or ''), 'PGPASSWORD': unquote(parsed.password or ''),
        'PGDATABASE': values.get('CDF_CANONICAL_DB') or values.get('CDF_PILOT_DB') or unquote(parsed.path.lstrip('/')),
        'PGOPTIONS': '-c default_transaction_read_only=on',
    })
    from urllib.parse import parse_qs
    options = parse_qs(parsed.query)
    for name in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'connect_timeout'):
        if name in options:
            environment['PG'+name.upper()] = options[name][-1]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    import psycopg
    from psycopg import sql
    connection = psycopg.connect(
        host=environment['PGHOST'], port=environment['PGPORT'], dbname=environment['PGDATABASE'],
        user=environment['PGUSER'], password=environment['PGPASSWORD'],
        options='-c default_transaction_read_only=on',
        **{key: options[key][-1] for key in ('sslmode','sslrootcert','sslcert','sslkey','connect_timeout') if key in options},
    )
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    command = [executable, '--format=custom', '--data-only', '--no-owner', '--no-acl', '--exclude-table-data=core.legacy_entity_map']
    command += [f'--schema={schema}' for schema in SCHEMAS] + ['--snapshot='+snapshot]
    with os.fdopen(descriptor, 'wb') as stream:
        result = subprocess.run(command, env=environment, stdout=stream, stderr=subprocess.PIPE)
    if result.returncode:
        output.unlink(missing_ok=True)
        raise SystemExit('Market export failed; incomplete file removed. Check source connectivity and pg_dump version.')
    # The general identity map also contains user/portfolio mappings. Transfer
    # only market identities, excluding free-text notes and private mappings.
    identity_path = output.with_suffix('.identity.csv')
    try:
        identity_descriptor = os.open(identity_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(identity_descriptor, 'wb') as stream:
            columns = sql.SQL(',').join(map(sql.Identifier, IDENTITY_COLUMNS.split(',')))
            with connection.cursor().copy(sql.SQL("COPY (SELECT {} FROM core.legacy_entity_map WHERE entity_type IN ('company','security','report')) TO STDOUT WITH (FORMAT CSV, HEADER true)").format(columns)) as copy:
                for block in copy:
                    stream.write(block)
    except Exception:
        output.unlink(missing_ok=True)
        # Do not remove a pre-existing sidecar that caused O_EXCL to fail.
        if 'identity_descriptor' in locals():
            identity_path.unlink(missing_ok=True)
        raise SystemExit('Identity export failed; newly created incomplete files were removed.')
    connection.rollback()
    connection.close()
    print(f'Exported public-market schemas to {output} and market identities to {identity_path}. User, family, chat and portfolio data were excluded.')


if __name__ == '__main__':
    main()
