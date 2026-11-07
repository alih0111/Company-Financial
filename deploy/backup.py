"""Back up the deployment database and runtime volumes; no credentials in arguments."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import os
import subprocess

root = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=root/'backups')
    args = parser.parse_args()
    destination = args.directory.resolve()/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination.mkdir(parents=True, mode=0o700)
    compose = ['docker', 'compose', '--env-file', str(root/'deploy/.env')]
    for filename, command in [
        ('database.dump', ['exec', '-T', 'db', 'pg_dump', '-U', 'rfa_owner', '-d', 'company_financial', '--format=custom', '--no-owner', '--no-acl']),
        ('runtime.tar', ['exec', '-T', 'app', 'tar', '-C', '/app', '-cf', '-', '.runtime', 'go-app/.runtime', 'ranking_research/output', 'client/public']),
    ]:
        path = destination/filename
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            result = subprocess.run(compose+command, cwd=root, stdout=stream, stderr=subprocess.PIPE)
        if result.returncode:
            path.unlink(missing_ok=True)
            raise SystemExit('Backup did not finish. Check deployment availability; incomplete file removed.')
    print(f'Backup completed: {destination}. Store a protected copy off the server.')


if __name__ == '__main__':
    main()
