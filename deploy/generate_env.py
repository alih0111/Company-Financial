"""Create deployment secrets locally without printing them or replacing a file."""
from pathlib import Path
import base64
import os
import secrets


def main():
    destination = Path(__file__).resolve().parent / '.env'
    content = f'''# Private deployment settings. Never commit or paste this file into chat.
# Use a hostname here for automatic HTTPS; :80 is for the local smoke check only.
SITE_ADDRESS=:80
RFA_VERSION=local
POSTGRES_PASSWORD={secrets.token_hex(32)}
APP_DB_PASSWORD={secrets.token_hex(32)}
JWT_SECRET={secrets.token_hex(48)}
CDF_SECRET_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}
# Enable after configuring and testing the mail account.
CDF_REGISTRATION_ENABLED=0
# Durable daily data budgets for ordinary accounts; reset at Tehran midnight.
CDF_DATA_DAILY_REQUESTS=300
CDF_DATA_DAILY_RECORDS=12000
CDF_DATA_DAILY_BYTES=8388608
CDF_DATA_DAILY_SYMBOLS=40
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=
SMTP_PASSWORD=
SMTP_FROM=
AI_CHAT_URL=
AI_API_KEY=
AI_MODEL=
BRS_API_KEY=
# Enable after importing market/company data and checking the ingest pipeline.
CODAL_AUTO_SYNC_ENABLED=0
'''
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('Deployment settings already exist; preserved without changes.')
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    print('Created deploy/.env with new random secrets. Values were not printed.')


if __name__ == '__main__':
    main()
