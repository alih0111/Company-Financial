"""Prompt without echo, then pass the new administrator password via stdin."""
from pathlib import Path
import argparse
import getpass
import subprocess

root = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    password = getpass.getpass('New administrator password (15+ characters, at most 72 bytes): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords did not match; nothing was changed.')
    if len(password)<15 or len(password.encode())>72 or '\n' in password or '\r' in password:
        raise SystemExit('Password must contain at least 15 characters, at most 72 bytes and no line breaks.')
    subprocess.run([
        'docker', 'compose', '--env-file', str(root/'deploy/.env'),
        'exec', '-T', 'app', 'rfa', 'admin', '--username', args.username, '--email', args.email,
    ], input=password+'\n', text=True, check=True, cwd=root)


if __name__ == '__main__':
    main()
